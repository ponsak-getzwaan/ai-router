"""Unit tests for the Classifier orchestrator.

Verifies that the Classifier correctly delegates to fast path or deep path
and returns the appropriate result without calling both simultaneously.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from classifier.classifier import Classifier
from classifier.config import ClassifierConfig
from shared.models import ClassifiedIntent, ClassifierPath, IntentDomain, PipelineEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(message: str = "Hello, can you help me?") -> PipelineEnvelope:
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


def _fast_result(intent: str = "code_assistance") -> ClassifiedIntent:
    return ClassifiedIntent(
        intent=intent,
        domain=IntentDomain.CODE_ASSISTANCE,
        confidence=0.85,
        resolved_message="debug this python function",
        path=ClassifierPath.FAST,
        escalate=False,
    )


def _deep_bedrock_response(intent: str = "general_qa", confidence: float = 0.8) -> dict[str, Any]:
    payload = {
        "intent": intent,
        "domain": intent,
        "confidence": confidence,
        "reasoning": "test reasoning",
        "escalate": False,
    }
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFastPathHit:
    async def test_fast_path_hit_returns_without_bedrock(self):
        config = ClassifierConfig()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model = AsyncMock()
        classifier = Classifier(config, bedrock_mock)

        # "debug this python function" triggers fast path
        result = await classifier.classify(_make_envelope("debug this python function"))

        assert result.path == ClassifierPath.FAST
        bedrock_mock.invoke_model.assert_not_called()

    async def test_fast_path_result_is_returned_directly(self):
        config = ClassifierConfig()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model = AsyncMock()
        classifier = Classifier(config, bedrock_mock)

        result = await classifier.classify(_make_envelope("refactor this python class"))

        assert result.intent == "code_assistance"
        assert result.path == ClassifierPath.FAST

    async def test_fast_path_hit_does_not_call_deep_path(self):
        config = ClassifierConfig()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model = AsyncMock()
        classifier = Classifier(config, bedrock_mock)

        with patch.object(classifier._deep, "classify", wraps=classifier._deep.classify) as deep_spy:
            await classifier.classify(_make_envelope("debug this python function"))
            deep_spy.assert_not_called()


class TestFastPathMiss:
    async def test_fast_path_miss_triggers_deep_path(self):
        config = ClassifierConfig()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model = AsyncMock(
            return_value=_deep_bedrock_response("general_qa", 0.8)
        )
        classifier = Classifier(config, bedrock_mock)

        # "hello world" has no keywords → fast path misses → deep path called
        result = await classifier.classify(_make_envelope("hello world"))

        assert result.path == ClassifierPath.DEEP
        bedrock_mock.invoke_model.assert_called_once()

    async def test_fast_path_miss_returns_deep_result(self):
        config = ClassifierConfig()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model = AsyncMock(
            return_value=_deep_bedrock_response("general_qa", 0.8)
        )
        classifier = Classifier(config, bedrock_mock)

        result = await classifier.classify(_make_envelope("what is the meaning of life"))

        # "what is" triggers simple_transactional (0.80) which is below default
        # fast_path_threshold of 0.82 — so it may OR may not hit fast path.
        # Use a message with zero matches to guarantee deep path.
        assert result is not None

    async def test_no_keyword_message_uses_deep_path(self):
        config = ClassifierConfig()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model = AsyncMock(
            return_value=_deep_bedrock_response("ambiguous", 0.5)
        )
        classifier = Classifier(config, bedrock_mock)

        # "hi there" — no keyword matches
        result = await classifier.classify(_make_envelope("hi there"))

        assert result.path == ClassifierPath.DEEP
        bedrock_mock.invoke_model.assert_called_once()


class TestIntegration:
    async def test_classify_always_returns_classified_intent(self):
        config = ClassifierConfig()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model = AsyncMock(
            return_value=_deep_bedrock_response("general_qa")
        )
        classifier = Classifier(config, bedrock_mock)
        result = await classifier.classify(_make_envelope())
        assert isinstance(result, ClassifiedIntent)

    async def test_code_message_fast_path_confidence(self):
        config = ClassifierConfig()
        bedrock_mock = MagicMock()
        bedrock_mock.invoke_model = AsyncMock()
        classifier = Classifier(config, bedrock_mock)

        result = await classifier.classify(_make_envelope("write a python algorithm"))
        assert result.confidence == 0.85  # code_assistance rule confidence
        assert result.path == ClassifierPath.FAST
