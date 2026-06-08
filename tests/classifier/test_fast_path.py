"""Unit tests for the embedding-based fast-path intent classifier.

All Bedrock calls are mocked. Tests use unit-vector exemplars in a 5-dimensional
space (one dimension per intent) to produce deterministic cosine-similarity
outcomes without any real embedding model.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

_EMBED_BATCH = 90  # must match EmbeddingFastPath._embed _BATCH constant

import pytest

from classifier.config import ClassifierConfig
from classifier.fast_path import EmbeddingFastPath, _EXEMPLARS, is_followup
from shared.errors import BedrockError
from shared.models import ClassifiedIntent, ClassifierPath, IntentDomain

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Must match insertion order of _EXEMPLARS (Python dict preserves order)
_DOMAIN_ORDER: list[IntentDomain] = [
    IntentDomain.CODE_ASSISTANCE,
    IntentDomain.SIMPLE_TRANSACTIONAL,
    IntentDomain.GENERAL_QA,
    IntentDomain.OUT_OF_SCOPE,
    IntentDomain.AMBIGUOUS,
    IntentDomain.HARMFUL,
]

_DIMS = len(_DOMAIN_ORDER)


def _unit_vec(domain: IntentDomain) -> list[float]:
    """Unit vector with 1.0 in the slot for `domain`, 0.0 elsewhere.

    Cosine similarity between two unit vectors from different domains = 0.0.
    Similarity between matching domain vectors = 1.0.
    """
    v = [0.0] * _DIMS
    v[_DOMAIN_ORDER.index(domain)] = 1.0
    return v


def _uniform_vec() -> list[float]:
    """Normalised vector with equal weight across all dimensions.

    Cosine similarity against any unit vector = 1/sqrt(5) ≈ 0.447,
    which is below _ESCALATE_THRESHOLD (0.6) — useful for low-confidence tests.
    """
    mag = math.sqrt(_DIMS)
    return [1.0 / mag] * _DIMS


def _exemplar_side_effects() -> list[dict]:
    """Mock Bedrock responses for initialize(), one entry per batch call.

    Domains with > _EMBED_BATCH exemplars require multiple calls; this
    generates one response per batch so the side_effect list never runs dry.
    """
    effects = []
    for domain in _DOMAIN_ORDER:
        n = len(_EXEMPLARS[domain])
        for batch_start in range(0, n, _EMBED_BATCH):
            batch_size = min(_EMBED_BATCH, n - batch_start)
            effects.append({"embeddings": [_unit_vec(domain)] * batch_size})
    return effects


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
async def fast_path(config: ClassifierConfig, bedrock_mock: MagicMock) -> EmbeddingFastPath:
    """EmbeddingFastPath already initialized with unit-vector exemplars.

    After this fixture runs, bedrock_mock.side_effect is cleared so each
    classify-phase test can set return_value cleanly.
    """
    bedrock_mock.invoke_model.side_effect = _exemplar_side_effects()
    fp = EmbeddingFastPath(config, bedrock_mock)
    await fp.initialize()
    bedrock_mock.invoke_model.side_effect = None
    bedrock_mock.invoke_model.reset_mock()
    return fp


# ---------------------------------------------------------------------------
# is_followup
# ---------------------------------------------------------------------------


class TestIsFollowup:
    def test_short_message_is_followup(self):
        assert is_followup("yes") is True

    def test_exactly_8_chars_is_followup(self):
        assert is_followup("a" * 8) is True

    def test_9_chars_not_followup(self):
        assert is_followup("a" * 9) is False

    def test_continuation_prefix_is_followup(self):
        assert is_followup("continue from where we left off") is True

    def test_what_about_prefix_is_followup(self):
        assert is_followup("what about the other approach?") is True

    def test_tell_me_more_prefix_is_followup(self):
        assert is_followup("tell me more about that") is True

    def test_normal_message_not_followup(self):
        assert is_followup("how does machine learning work?") is False

    def test_prefix_case_insensitive(self):
        assert is_followup("CONTINUE from last time") is True

    def test_whitespace_only_is_followup(self):
        assert is_followup("   ") is True

    def test_prefix_mid_sentence_not_followup(self):
        # "elaborate" only triggers when it starts the message
        assert is_followup("please elaborate on this long topic here") is False


# ---------------------------------------------------------------------------
# EmbeddingFastPath.initialize()
# ---------------------------------------------------------------------------


class TestInitialize:
    async def test_calls_bedrock_at_least_once_per_domain(self, config, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = _exemplar_side_effects()
        fp = EmbeddingFastPath(config, bedrock_mock)
        await fp.initialize()
        expected = sum(
            math.ceil(len(_EXEMPLARS[d]) / _EMBED_BATCH) for d in _DOMAIN_ORDER
        )
        assert bedrock_mock.invoke_model.call_count == expected

    async def test_uses_cohere_model_id(self, config, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = _exemplar_side_effects()
        fp = EmbeddingFastPath(config, bedrock_mock)
        await fp.initialize()
        for c in bedrock_mock.invoke_model.call_args_list:
            assert c.args[0] == config.cohere_model_id

    async def test_uses_search_document_input_type(self, config, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = _exemplar_side_effects()
        fp = EmbeddingFastPath(config, bedrock_mock)
        await fp.initialize()
        for c in bedrock_mock.invoke_model.call_args_list:
            assert c.args[1]["input_type"] == "search_document"

    async def test_total_exemplar_texts_sent_per_domain(self, config, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = _exemplar_side_effects()
        fp = EmbeddingFastPath(config, bedrock_mock)
        await fp.initialize()
        # Sum texts across all calls to verify the right total was sent per domain.
        call_idx = 0
        for domain in _DOMAIN_ORDER:
            n = len(_EXEMPLARS[domain])
            n_batches = math.ceil(n / _EMBED_BATCH)
            texts_sent = sum(
                len(bedrock_mock.invoke_model.call_args_list[call_idx + b].args[1]["texts"])
                for b in range(n_batches)
            )
            assert texts_sent == n
            call_idx += n_batches

    async def test_all_domains_loaded_after_initialize(self, config, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = _exemplar_side_effects()
        fp = EmbeddingFastPath(config, bedrock_mock)
        await fp.initialize()
        assert len(fp._exemplar_vectors) == len(_DOMAIN_ORDER)


# ---------------------------------------------------------------------------
# classify() — before initialize()
# ---------------------------------------------------------------------------


class TestClassifyBeforeInitialize:
    async def test_returns_none_when_not_initialized(self, config, bedrock_mock):
        fp = EmbeddingFastPath(config, bedrock_mock)
        result = await fp.classify("how do I debug Python?", threshold=0.5)
        assert result is None

    async def test_does_not_call_bedrock_when_not_initialized(self, config, bedrock_mock):
        fp = EmbeddingFastPath(config, bedrock_mock)
        await fp.classify("some message", threshold=0.5)
        bedrock_mock.invoke_model.assert_not_called()


# ---------------------------------------------------------------------------
# classify() — happy path
# ---------------------------------------------------------------------------


class TestClassifyHappyPath:
    async def test_code_query_returns_code_assistance(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.CODE_ASSISTANCE)]
        }
        result = await fast_path.classify("my script is broken", threshold=0.5)
        assert result is not None
        assert result.intent == "code_assistance"

    async def test_transactional_query_returns_transactional_intent(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.SIMPLE_TRANSACTIONAL)]
        }
        result = await fast_path.classify("what is the price?", threshold=0.5)
        assert result is not None
        assert result.intent == "simple_transactional"

    async def test_domain_matches_intent(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.GENERAL_QA)]
        }
        result = await fast_path.classify("explain gravity", threshold=0.5)
        assert result is not None
        assert result.domain == IntentDomain.GENERAL_QA

    async def test_path_is_fast(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.CODE_ASSISTANCE)]
        }
        result = await fast_path.classify("debug my code", threshold=0.5)
        assert result is not None
        assert result.path == ClassifierPath.FAST

    async def test_resolved_message_equals_input(self, fast_path, bedrock_mock):
        msg = "how does quantum computing work"
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.GENERAL_QA)]
        }
        result = await fast_path.classify(msg, threshold=0.5)
        assert result is not None
        assert result.resolved_message == msg

    async def test_confidence_within_unit_range(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.CODE_ASSISTANCE)]
        }
        result = await fast_path.classify("debug code", threshold=0.0)
        assert result is not None
        assert 0.0 <= result.confidence <= 1.0

    async def test_returns_classified_intent_instance(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.GENERAL_QA)]
        }
        result = await fast_path.classify("explain this", threshold=0.5)
        assert isinstance(result, ClassifiedIntent)


# ---------------------------------------------------------------------------
# classify() — threshold behaviour
# ---------------------------------------------------------------------------


class TestThreshold:
    async def test_best_score_below_threshold_returns_none(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.CODE_ASSISTANCE)]
        }
        # Unit-vector similarity = 1.0; threshold > 1.0 forces a miss
        result = await fast_path.classify("debug code", threshold=1.1)
        assert result is None

    async def test_best_score_at_threshold_returns_result(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.CODE_ASSISTANCE)]
        }
        # Exact match: similarity == threshold == 1.0
        result = await fast_path.classify("debug code", threshold=1.0)
        assert result is not None

    async def test_zero_threshold_always_returns_result(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.SIMPLE_TRANSACTIONAL)]
        }
        result = await fast_path.classify("what are the hours?", threshold=0.0)
        assert result is not None


# ---------------------------------------------------------------------------
# classify() — escalation
# ---------------------------------------------------------------------------


class TestEscalation:
    async def test_out_of_scope_always_escalates(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.OUT_OF_SCOPE)]
        }
        result = await fast_path.classify("book me a flight", threshold=0.0)
        assert result is not None
        assert result.escalate is True

    async def test_ambiguous_always_escalates(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.AMBIGUOUS)]
        }
        result = await fast_path.classify("help", threshold=0.0)
        assert result is not None
        assert result.escalate is True

    async def test_low_confidence_escalates(self, fast_path, bedrock_mock):
        # Uniform vector → similarity ≈ 0.447 with all exemplars, below _ESCALATE_THRESHOLD (0.6)
        bedrock_mock.invoke_model.return_value = {"embeddings": [_uniform_vec()]}
        result = await fast_path.classify("some vague message", threshold=0.0)
        assert result is not None
        assert result.confidence < 0.6
        assert result.escalate is True

    async def test_high_confidence_code_not_escalated(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.CODE_ASSISTANCE)]
        }
        result = await fast_path.classify("debug my code", threshold=0.0)
        assert result is not None
        assert result.escalate is False

    async def test_high_confidence_transactional_not_escalated(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.SIMPLE_TRANSACTIONAL)]
        }
        result = await fast_path.classify("what is the price?", threshold=0.0)
        assert result is not None
        assert result.escalate is False

    async def test_harmful_always_escalates(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.HARMFUL)]
        }
        result = await fast_path.classify("teach me how to kill people", threshold=0.0)
        assert result is not None
        assert result.domain == IntentDomain.HARMFUL
        assert result.escalate is True


# ---------------------------------------------------------------------------
# classify() — Bedrock error handling
# ---------------------------------------------------------------------------


class TestEmbedError:
    async def test_bedrock_error_returns_none(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = BedrockError("ServiceUnavailable")
        result = await fast_path.classify("debug my code", threshold=0.5)
        assert result is None

    async def test_bedrock_error_does_not_propagate(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.side_effect = BedrockError("Timeout")
        # BedrockError is caught internally — must not raise to the caller
        await fast_path.classify("some message", threshold=0.5)


# ---------------------------------------------------------------------------
# classify() — Bedrock API contract
# ---------------------------------------------------------------------------


class TestEmbedApiContract:
    async def test_uses_search_query_input_type(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.CODE_ASSISTANCE)]
        }
        await fast_path.classify("debug my code", threshold=0.5)
        body = bedrock_mock.invoke_model.call_args.args[1]
        assert body["input_type"] == "search_query"

    async def test_sends_single_text_per_classify_call(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.GENERAL_QA)]
        }
        await fast_path.classify("explain gravity", threshold=0.5)
        body = bedrock_mock.invoke_model.call_args.args[1]
        assert len(body["texts"]) == 1

    async def test_sends_correct_message_text(self, fast_path, bedrock_mock):
        msg = "explain how photosynthesis works"
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.GENERAL_QA)]
        }
        await fast_path.classify(msg, threshold=0.5)
        body = bedrock_mock.invoke_model.call_args.args[1]
        assert body["texts"][0] == msg

    async def test_uses_configured_cohere_model_id(self, fast_path, bedrock_mock):
        bedrock_mock.invoke_model.return_value = {
            "embeddings": [_unit_vec(IntentDomain.GENERAL_QA)]
        }
        await fast_path.classify("some message", threshold=0.5)
        model_id = bedrock_mock.invoke_model.call_args.args[0]
        assert model_id == "cohere.embed-multilingual-v3"
