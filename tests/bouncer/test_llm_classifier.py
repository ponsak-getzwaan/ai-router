"""Unit tests for the LLM classifier.

The fail-open invariant is the most critical thing tested here:
on ANY failure (timeout, Bedrock error, malformed response) the classifier
MUST return allowed=True. The rule gate is the only path that blocks.

See CLAUDE.md §3.4 and the Bouncer sequence diagram in docs/architecture.md.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from bouncer.llm_classifier import LLMClassifier
from shared.errors import BedrockError, BedrockTimeout
from shared.models import BouncerLayer
from tests.bouncer.conftest import NoOpMetrics, make_envelope


def _bedrock_response(pass_: bool, reason: str, confidence: float) -> dict[str, Any]:
    text = json.dumps({"pass": pass_, "reason": reason, "confidence": confidence})
    return {"content": [{"type": "text", "text": text}]}


@pytest.fixture
def bedrock_mock() -> MagicMock:
    mock = MagicMock()
    mock.invoke_model = AsyncMock()
    return mock


@pytest.fixture
def classifier(config, bedrock_mock) -> LLMClassifier:
    return LLMClassifier(config, bedrock_mock, NoOpMetrics())


class TestHappyPath:
    async def test_high_confidence_pass_is_allowed_not_escalated(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "safe", 0.95)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.allowed is True
        assert result.escalate is False
        assert result.confidence == pytest.approx(0.95)
        assert result.layer == BouncerLayer.LLM_CLASSIFIER
        assert result.timed_out is False

    async def test_low_confidence_pass_escalates(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "unclear", 0.5)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.allowed is True
        assert result.escalate is True
        assert result.timed_out is False

    async def test_haiku_fail_with_high_confidence_escalates(self, classifier, bedrock_mock):
        """pass=False from Haiku must escalate, NOT block the request."""
        bedrock_mock.invoke_model.return_value = _bedrock_response(False, "toxic", 0.9)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.allowed is True
        assert result.escalate is True

    async def test_confidence_exactly_at_threshold_is_not_escalated(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "safe", 0.7)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.escalate is False

    async def test_confidence_just_below_threshold_escalates(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "safe", 0.699)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.escalate is True


class TestFailOpen:
    """CRITICAL: The LLM classifier must never block the request."""

    async def test_timeout_returns_allowed_true_timed_out_true(self, classifier, bedrock_mock):
        """This is the primary fail-open test. See CLAUDE.md §3.4."""
        async def slow_response(*_: Any, **__: Any) -> dict[str, Any]:
            await asyncio.sleep(60)
            return {}

        bedrock_mock.invoke_model.side_effect = slow_response
        result = await classifier.classify(make_envelope(), remaining_budget_ms=10.0)

        assert result.allowed is True, "Timeout must NOT block the request"
        assert result.timed_out is True
        assert result.layer == BouncerLayer.TIMEOUT_FAIL_OPEN
        assert result.confidence == 0.0
        assert result.escalate is False

    async def test_bedrock_error_fails_open(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = BedrockError("ClientError")
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)

        assert result.allowed is True
        assert result.timed_out is False
        assert result.layer == BouncerLayer.TIMEOUT_FAIL_OPEN
        assert result.confidence == 0.0

    async def test_bedrock_timeout_exception_fails_open(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = BedrockTimeout("ReadTimeoutError")
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)

        assert result.allowed is True
        assert result.layer == BouncerLayer.TIMEOUT_FAIL_OPEN

    async def test_malformed_json_response_fails_open(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "content": [{"type": "text", "text": "NOT VALID JSON {{{}"}]
        }
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.allowed is True
        assert result.layer == BouncerLayer.TIMEOUT_FAIL_OPEN

    async def test_missing_content_key_fails_open(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {"unexpected_key": "unexpected_value"}
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.allowed is True

    async def test_empty_content_list_fails_open(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {"content": []}
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.allowed is True


class TestReasonSanitisation:
    async def test_newlines_are_stripped_from_reason(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "safe\nmore", 0.9)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert "\n" not in result.reason

    async def test_at_sign_is_stripped_from_reason(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "safe@bad", 0.9)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert "@" not in result.reason

    async def test_empty_reason_defaults_to_unclear(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "", 0.9)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.reason == "unclear"

    async def test_reason_is_truncated_to_safe_length(self, classifier, bedrock_mock):
        long_reason = "x" * 200
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, long_reason, 0.9)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert len(result.reason) <= 50


class TestConfidenceClamping:
    async def test_confidence_above_one_is_clamped(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "safe", 1.5)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.confidence <= 1.0

    async def test_confidence_below_zero_is_clamped(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(True, "safe", -0.5)
        result = await classifier.classify(make_envelope(), remaining_budget_ms=180.0)
        assert result.confidence >= 0.0
