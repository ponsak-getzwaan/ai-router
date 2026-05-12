"""Unit tests for the deep-path (Sonnet) intent classifier.

All Bedrock calls are mocked. Tests cover happy path, error handling,
domain mapping, and field truncation.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from classifier.config import ClassifierConfig
from classifier.deep_path import DeepPathClassifier
from shared.errors import BedrockError
from shared.models import ClassifiedIntent, ClassifierPath, IntentDomain, PipelineEnvelope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bedrock_response(
    intent: str = "general_qa",
    confidence: float = 0.85,
    reasoning: str = "message is a general question",
    escalate: bool = False,
) -> dict[str, Any]:
    payload = {
        "intent": intent,
        "domain": intent,
        "confidence": confidence,
        "reasoning": reasoning,
        "escalate": escalate,
    }
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _make_envelope(message: str = "explain gravity") -> PipelineEnvelope:
    import hashlib
    import uuid
    from datetime import UTC, datetime

    return PipelineEnvelope(
        correlation_id=uuid.uuid4(),
        user_sub="test-user-sub",
        session_id="test-session",
        redacted_message=message,
        raw_message_hash=hashlib.sha256(message.encode()).hexdigest(),
        entity_types_redacted=(),
        entity_count=0,
        was_redacted=False,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip="127.0.0.1",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> ClassifierConfig:
    return ClassifierConfig()


@pytest.fixture
def bedrock_mock() -> MagicMock:
    mock = MagicMock()
    mock.invoke_model = AsyncMock()
    return mock


@pytest.fixture
def classifier(config, bedrock_mock) -> DeepPathClassifier:
    return DeepPathClassifier(config, bedrock_mock)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_successful_response_returns_intent(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(
            intent="code_assistance", confidence=0.9
        )
        result = await classifier.classify(_make_envelope())
        assert isinstance(result, ClassifiedIntent)
        assert result.intent == "code_assistance"
        assert result.confidence == pytest.approx(0.9)

    async def test_successful_response_maps_domain(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(
            intent="code_assistance", confidence=0.9
        )
        result = await classifier.classify(_make_envelope())
        assert result.domain == IntentDomain.CODE_ASSISTANCE

    async def test_result_uses_deep_path(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response()
        result = await classifier.classify(_make_envelope())
        assert result.path == ClassifierPath.DEEP

    async def test_resolved_message_equals_envelope_message(self, classifier, bedrock_mock):
        msg = "how does quantum computing work"
        bedrock_mock.invoke_model.return_value = _bedrock_response()
        result = await classifier.classify(_make_envelope(msg))
        assert result.resolved_message == msg


class TestDomainMapping:
    async def test_general_qa_intent_maps_to_general_qa_domain(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(intent="general_qa")
        result = await classifier.classify(_make_envelope())
        assert result.domain == IntentDomain.GENERAL_QA

    async def test_code_assistance_maps_to_correct_domain(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(intent="code_assistance")
        result = await classifier.classify(_make_envelope())
        assert result.domain == IntentDomain.CODE_ASSISTANCE

    async def test_simple_transactional_maps_to_correct_domain(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(intent="simple_transactional")
        result = await classifier.classify(_make_envelope())
        assert result.domain == IntentDomain.SIMPLE_TRANSACTIONAL

    async def test_out_of_scope_maps_to_correct_domain(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(intent="out_of_scope")
        result = await classifier.classify(_make_envelope())
        assert result.domain == IntentDomain.OUT_OF_SCOPE

    async def test_unknown_intent_maps_to_ambiguous_domain(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(intent="unknown_thing")
        result = await classifier.classify(_make_envelope())
        assert result.domain == IntentDomain.AMBIGUOUS

    async def test_ambiguous_intent_maps_to_ambiguous_domain(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(intent="ambiguous")
        result = await classifier.classify(_make_envelope())
        assert result.domain == IntentDomain.AMBIGUOUS


class TestEscalation:
    async def test_confidence_below_threshold_sets_escalate(self, classifier, bedrock_mock):
        # escalate_threshold=0.6; confidence=0.4 → escalate=True
        bedrock_mock.invoke_model.return_value = _bedrock_response(
            confidence=0.4, escalate=False
        )
        result = await classifier.classify(_make_envelope())
        assert result.escalate is True

    async def test_escalate_true_in_response_respected(self, classifier, bedrock_mock):
        # confidence=0.8 would normally not escalate, but response says escalate=True
        bedrock_mock.invoke_model.return_value = _bedrock_response(
            confidence=0.8, escalate=True
        )
        result = await classifier.classify(_make_envelope())
        assert result.escalate is True

    async def test_high_confidence_no_escalate_flag_not_escalated(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(
            confidence=0.9, escalate=False
        )
        result = await classifier.classify(_make_envelope())
        assert result.escalate is False

    async def test_confidence_at_threshold_not_escalated(self, classifier, bedrock_mock):
        # confidence=0.6 == escalate_threshold → not escalated
        bedrock_mock.invoke_model.return_value = _bedrock_response(
            confidence=0.6, escalate=False
        )
        result = await classifier.classify(_make_envelope())
        assert result.escalate is False


class TestErrorHandling:
    async def test_bedrock_error_returns_ambiguous_escalated(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = BedrockError("ClientError")
        result = await classifier.classify(_make_envelope())
        assert result.intent == "ambiguous"
        assert result.escalate is True
        assert result.confidence == 0.0

    async def test_malformed_json_returns_ambiguous_escalated(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "content": [{"type": "text", "text": "not json"}]
        }
        result = await classifier.classify(_make_envelope())
        assert result.intent == "ambiguous"
        assert result.escalate is True

    async def test_missing_content_key_returns_ambiguous(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {"unexpected": "data"}
        result = await classifier.classify(_make_envelope())
        assert result.intent == "ambiguous"
        assert result.escalate is True

    async def test_error_result_uses_deep_path(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = BedrockError("ServiceUnavailable")
        result = await classifier.classify(_make_envelope())
        assert result.path == ClassifierPath.DEEP

    async def test_error_result_resolved_message_set(self, classifier, bedrock_mock):
        msg = "some message"
        bedrock_mock.invoke_model.side_effect = BedrockError("Err")
        result = await classifier.classify(_make_envelope(msg))
        assert result.resolved_message == msg


class TestReasoningTruncation:
    async def test_reasoning_truncated_to_500_chars(self, classifier, bedrock_mock):
        long_reasoning = "x" * 600
        bedrock_mock.invoke_model.return_value = _bedrock_response(reasoning=long_reasoning)
        result = await classifier.classify(_make_envelope())
        assert result.reasoning is not None
        assert len(result.reasoning) <= 500

    async def test_short_reasoning_preserved(self, classifier, bedrock_mock):
        short = "simple factual question"
        bedrock_mock.invoke_model.return_value = _bedrock_response(reasoning=short)
        result = await classifier.classify(_make_envelope())
        assert result.reasoning == short

    async def test_empty_reasoning_becomes_none(self, classifier, bedrock_mock):
        bedrock_mock.invoke_model.return_value = _bedrock_response(reasoning="")
        result = await classifier.classify(_make_envelope())
        assert result.reasoning is None
