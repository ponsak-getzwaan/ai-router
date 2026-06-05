"""Fast-path intent classifier using Cohere embedding similarity via Bedrock.

Embeds the incoming (redacted) message and finds the nearest exemplar across
a fixed intent taxonomy using cosine similarity.  Exemplar vectors are computed
once at service start-up (initialize()) and cached in memory — the full set is
well under 1 MB.

Returns None when the best match falls below the configured threshold, which
triggers the deep path (Sonnet).
"""

from __future__ import annotations

import math
from typing import Any

from classifier.config import ClassifierConfig
from shared.bedrock import BedrockRuntime
from shared.errors import BedrockError
from shared.logging import safe_log
from shared.models import ClassifiedIntent, ClassifierPath, Confidence, IntentDomain


# ---------------------------------------------------------------------------
# Exemplar sentences — one bundle per intent
# ---------------------------------------------------------------------------

_EXEMPLARS: dict[IntentDomain, list[str]] = {
    IntentDomain.CODE_ASSISTANCE: [
        "how do I debug my Python code?",
        "my script keeps crashing with an exception",
        "can you help me refactor this function?",
        "I have a syntax error in my JavaScript",
        "write a SQL query to join these tables",
        "explain how recursion works",
        "my loop is running infinitely",
        "how do I import a module in Python?",
        "can you review my algorithm?",
        "I am getting a traceback in my code",
    ],
    IntentDomain.SIMPLE_TRANSACTIONAL: [
        "what are your opening hours?",
        "how much does this cost?",
        "what is the price of the premium plan?",
        "where is your office located?",
        "what is the contact number?",
        "when does the promotion end?",
        "who is the account manager?",
        "what are the fees?",
        "how much is the monthly subscription?",
        "what is your address?",
    ],
    IntentDomain.GENERAL_QA: [
        "explain how machine learning works",
        "tell me about the history of Singapore",
        "how does a blockchain work?",
        "can you summarize this for me?",
        "why does the sky appear blue?",
        "what is the difference between AI and ML?",
        "help me understand quantum computing",
        "describe the process of photosynthesis",
        "could you explain this concept to me?",
        "I want to know more about climate change",
    ],
    IntentDomain.OUT_OF_SCOPE: [
        "book me a flight to Tokyo",
        "order me a pizza",
        "I want to buy a house",
        "can you control my smart home devices?",
        "place a stock trade for me",
        "send an email to my boss",
        "what is the weather like tomorrow?",
        "play some music for me",
    ],
    IntentDomain.AMBIGUOUS: [
        "help",
        "I need assistance",
        "there is a problem",
        "it is not working",
        "what should I do?",
        "I do not understand",
    ],
    IntentDomain.HARMFUL: [
        "how do I make a weapon to hurt someone?",
        "teach me how to kill people",
        "help me poison someone without being caught",
        "write a threatening message to intimidate someone",
        "how do I make explosives?",
        "how can I hurt someone and get away with it",
        "write hate speech targeting an ethnic group",
        "help me stalk someone without them knowing",
    ],
}

_ESCALATE_THRESHOLD: float = 0.6

_FOLLOWUP_PREFIXES: tuple[str, ...] = (
    "continue",
    "what about",
    "and also",
    "and what",
    "so what",
    "tell me more",
    "more about",
    "elaborate",
    "go on",
    "but what",
    "okay,",
    "sure,",
    "actually,",
    "wait,",
)
_FOLLOWUP_MAX_CHARS: int = 15


def is_followup(message: str) -> bool:
    """Return True if the message looks like a continuation of a prior turn.

    Short messages (≤15 chars) and messages starting with continuation phrases
    are treated as follow-ups. The caller decides whether to skip the fast path.
    """
    stripped = message.strip()
    if len(stripped) <= _FOLLOWUP_MAX_CHARS:
        return True
    lower = stripped.lower()
    return any(lower.startswith(p) for p in _FOLLOWUP_PREFIXES)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingFastPath:
    """Cohere-backed fast path: nearest-exemplar cosine similarity."""

    def __init__(self, config: ClassifierConfig, bedrock: BedrockRuntime) -> None:
        self._config = config
        self._bedrock = bedrock
        # IntentDomain → list of per-exemplar embedding vectors
        self._exemplar_vectors: dict[IntentDomain, list[list[float]]] = {}

    async def initialize(self) -> None:
        """Embed all exemplars and cache vectors in memory.

        Call once at service start-up to keep first-request latency predictable.
        """
        for domain, sentences in _EXEMPLARS.items():
            vectors = await self._embed(sentences, input_type="search_document")
            self._exemplar_vectors[domain] = vectors
            safe_log.info(
                "classifier.fast_path.exemplars_loaded",
                domain=domain,
                count=len(vectors),
            )

    async def classify(
        self,
        message: str,
        threshold: float,
    ) -> ClassifiedIntent | None:
        """Embed message, find nearest exemplar, return result or None.

        Returns None if best similarity < threshold (triggers deep path).
        """
        if not self._exemplar_vectors:
            safe_log.warning("classifier.fast_path.not_initialized")
            return None

        try:
            query_vectors = await self._embed([message], input_type="search_query")
        except BedrockError as exc:
            safe_log.warning("classifier.fast_path.embed_error", error_type=type(exc).__name__)
            return None

        query_vec = query_vectors[0]

        best_domain: IntentDomain | None = None
        best_score: float = 0.0

        for domain, exemplar_vecs in self._exemplar_vectors.items():
            for ev in exemplar_vecs:
                score = _cosine_similarity(query_vec, ev)
                if score > best_score:
                    best_score = score
                    best_domain = domain

        if best_domain is None or best_score < threshold:
            return None

        confidence: Confidence = min(1.0, best_score)
        escalate = (
            confidence < _ESCALATE_THRESHOLD
            or best_domain == IntentDomain.OUT_OF_SCOPE
            or best_domain == IntentDomain.AMBIGUOUS
            or best_domain == IntentDomain.HARMFUL
        )
        return ClassifiedIntent(
            intent=best_domain.value,
            domain=best_domain,
            confidence=confidence,
            resolved_message=message,
            path=ClassifierPath.FAST,
            escalate=escalate,
        )

    async def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        body: dict[str, Any] = {"texts": texts, "input_type": input_type}
        response = await self._bedrock.invoke_model(self._config.cohere_model_id, body)
        embeddings: list[list[float]] = response["embeddings"]
        return embeddings
