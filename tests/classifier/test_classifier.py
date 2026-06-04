"""Unit tests for the Classifier orchestrator (classifier/classifier.py).

Tests cover routing logic only: when does fast path run, when is it skipped,
when does deep path run, and how is history forwarded.  The fast and deep path
implementations are mocked so these tests are decoupled from EmbeddingFastPath
and DeepPathClassifier internals.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from classifier.classifier import Classifier
from classifier.config import ClassifierConfig
from shared.models import ClassifiedIntent, ClassifierPath, IntentDomain, PipelineEnvelope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(message: str = "explain how gravity works") -> PipelineEnvelope:
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


def _make_result(
    path: ClassifierPath = ClassifierPath.FAST,
    intent: str = "code_assistance",
    domain: IntentDomain = IntentDomain.CODE_ASSISTANCE,
    confidence: float = 0.85,
    escalate: bool = False,
    message: str = "debug this",
) -> ClassifiedIntent:
    return ClassifiedIntent(
        intent=intent,
        domain=domain,
        confidence=confidence,
        resolved_message=message,
        path=path,
        escalate=escalate,
    )


_FAST_RESULT = _make_result(path=ClassifierPath.FAST)
_DEEP_RESULT = _make_result(path=ClassifierPath.DEEP, intent="general_qa", domain=IntentDomain.GENERAL_QA)

_HISTORY: list[dict[str, str]] = [
    {"role": "user", "content": "what is machine learning?"},
    {"role": "assistant", "content": "Machine learning is..."},
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config() -> ClassifierConfig:
    return ClassifierConfig()


@pytest.fixture
def classifier(config: ClassifierConfig) -> Classifier:
    """Classifier with both _fast and _deep replaced by AsyncMocks."""
    bedrock = MagicMock()
    bedrock.invoke_model = AsyncMock()
    c = Classifier(config, bedrock)
    c._fast = MagicMock()
    c._fast.initialize = AsyncMock()
    c._fast.classify = AsyncMock(return_value=_FAST_RESULT)
    c._deep = MagicMock()
    c._deep.classify = AsyncMock(return_value=_DEEP_RESULT)
    return c


# ---------------------------------------------------------------------------
# initialize()
# ---------------------------------------------------------------------------


class TestInitialize:
    async def test_delegates_to_fast_path(self, classifier):
        await classifier.initialize()
        classifier._fast.initialize.assert_awaited_once()

    async def test_does_not_call_deep_path(self, classifier):
        await classifier.initialize()
        classifier._deep.classify.assert_not_called()


# ---------------------------------------------------------------------------
# Fast path hit
# ---------------------------------------------------------------------------


class TestFastPathHit:
    async def test_returns_fast_result_when_fast_path_hits(self, classifier):
        result = await classifier.classify(_make_envelope())
        assert result is _FAST_RESULT

    async def test_deep_path_not_called_on_fast_hit(self, classifier):
        await classifier.classify(_make_envelope())
        classifier._deep.classify.assert_not_called()

    async def test_fast_path_called_with_redacted_message(self, classifier):
        envelope = _make_envelope("debug my Python script")
        await classifier.classify(envelope)
        classifier._fast.classify.assert_awaited_once_with(
            "debug my Python script", classifier._config.fast_path_threshold
        )

    async def test_fast_path_called_with_config_threshold(self, classifier, config):
        await classifier.classify(_make_envelope())
        _, threshold = classifier._fast.classify.call_args.args
        assert threshold == config.fast_path_threshold

    async def test_result_path_is_fast(self, classifier):
        result = await classifier.classify(_make_envelope())
        assert result.path == ClassifierPath.FAST


# ---------------------------------------------------------------------------
# Fast path miss → deep path
# ---------------------------------------------------------------------------


class TestFastPathMiss:
    async def test_deep_path_called_when_fast_returns_none(self, classifier):
        classifier._fast.classify = AsyncMock(return_value=None)
        await classifier.classify(_make_envelope())
        classifier._deep.classify.assert_awaited_once()

    async def test_returns_deep_result_on_fast_miss(self, classifier):
        classifier._fast.classify = AsyncMock(return_value=None)
        result = await classifier.classify(_make_envelope())
        assert result is _DEEP_RESULT

    async def test_deep_path_receives_envelope(self, classifier):
        classifier._fast.classify = AsyncMock(return_value=None)
        envelope = _make_envelope("what is the meaning of life")
        await classifier.classify(envelope)
        call_envelope = classifier._deep.classify.call_args.args[0]
        assert call_envelope is envelope

    async def test_deep_path_receives_none_history_by_default(self, classifier):
        classifier._fast.classify = AsyncMock(return_value=None)
        await classifier.classify(_make_envelope())
        history_kwarg = classifier._deep.classify.call_args.kwargs.get("history")
        assert history_kwarg is None

    async def test_result_path_is_deep(self, classifier):
        classifier._fast.classify = AsyncMock(return_value=None)
        result = await classifier.classify(_make_envelope())
        assert result.path == ClassifierPath.DEEP


# ---------------------------------------------------------------------------
# Follow-up detection
# ---------------------------------------------------------------------------


class TestFollowupDetection:
    async def test_no_history_fast_path_attempted_even_for_short_message(self, classifier):
        # "yes" is a follow-up by length, but no history → fast path still runs
        await classifier.classify(_make_envelope("yes"), history=None)
        classifier._fast.classify.assert_awaited_once()

    async def test_history_and_followup_skips_fast_path(self, classifier):
        # "yes" (≤15 chars) + history → fast path bypassed
        await classifier.classify(_make_envelope("yes"), history=_HISTORY)
        classifier._fast.classify.assert_not_called()

    async def test_history_and_followup_goes_to_deep_path(self, classifier):
        await classifier.classify(_make_envelope("continue"), history=_HISTORY)
        classifier._deep.classify.assert_awaited_once()

    async def test_history_and_non_followup_attempts_fast_path(self, classifier):
        # Long non-prefix message with history → fast path still runs
        msg = "explain the difference between supervised and unsupervised learning"
        await classifier.classify(_make_envelope(msg), history=_HISTORY)
        classifier._fast.classify.assert_awaited_once()

    async def test_history_continuation_prefix_skips_fast_path(self, classifier):
        await classifier.classify(_make_envelope("tell me more about that"), history=_HISTORY)
        classifier._fast.classify.assert_not_called()

    async def test_empty_history_list_does_not_skip_fast_path(self, classifier):
        # history=[] is falsy → fast path runs as normal
        await classifier.classify(_make_envelope("yes"), history=[])
        classifier._fast.classify.assert_awaited_once()


# ---------------------------------------------------------------------------
# History forwarding
# ---------------------------------------------------------------------------


class TestHistoryForwarding:
    async def test_history_forwarded_to_deep_path_on_fast_miss(self, classifier):
        classifier._fast.classify = AsyncMock(return_value=None)
        await classifier.classify(_make_envelope(), history=_HISTORY)
        history_kwarg = classifier._deep.classify.call_args.kwargs.get("history")
        assert history_kwarg is _HISTORY

    async def test_history_forwarded_to_deep_path_on_followup(self, classifier):
        await classifier.classify(_make_envelope("what about"), history=_HISTORY)
        history_kwarg = classifier._deep.classify.call_args.kwargs.get("history")
        assert history_kwarg is _HISTORY

    async def test_no_history_forwarded_as_none(self, classifier):
        classifier._fast.classify = AsyncMock(return_value=None)
        await classifier.classify(_make_envelope())
        history_kwarg = classifier._deep.classify.call_args.kwargs.get("history")
        assert history_kwarg is None


# ---------------------------------------------------------------------------
# Return type contract
# ---------------------------------------------------------------------------


class TestReturnType:
    async def test_fast_hit_returns_classified_intent(self, classifier):
        result = await classifier.classify(_make_envelope())
        assert isinstance(result, ClassifiedIntent)

    async def test_fast_miss_returns_classified_intent(self, classifier):
        classifier._fast.classify = AsyncMock(return_value=None)
        result = await classifier.classify(_make_envelope())
        assert isinstance(result, ClassifiedIntent)

    async def test_followup_path_returns_classified_intent(self, classifier):
        result = await classifier.classify(_make_envelope("yes"), history=_HISTORY)
        assert isinstance(result, ClassifiedIntent)
