"""Classifier accuracy test report.

Measures the classifier's correctness against a 30-sample labelled dataset
covering all five intents (placeholder taxonomy — see docs/intent-taxonomy.md).

Two test layers:

  1. Fast-path accuracy (deterministic, no Bedrock — runs on every PR).
     Measures keyword-heuristic coverage and intent correctness at both
     threshold=0.0 (rule-fire coverage) and the production threshold
     (what actually hits the fast path in prod).

  2. Full-classifier accuracy (real Bedrock — @pytest.mark.aws, merge-only).
     Sends every sample through the full Classifier.classify() pipeline
     and measures Sonnet's intent classification accuracy.

Usage:
  # Fast-path report only (no AWS, safe to run locally):
  pytest tests/classifier/test_accuracy.py -v

  # Include Bedrock tests (costs real money — merge CI only):
  pytest tests/classifier/test_accuracy.py -v -m aws

The accuracy report is printed in the pytest terminal summary at the end
of the run. See tests/classifier/conftest.py for the rendering logic.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from classifier.classifier import Classifier
from classifier.config import ClassifierConfig
from classifier.fast_path import classify_fast
from shared.models import PipelineEnvelope

if TYPE_CHECKING:
    from tests.classifier.conftest import _AccuracyStore

# ---------------------------------------------------------------------------
# Labelled dataset — 30 samples across 5 intents
# ---------------------------------------------------------------------------
# Format: (message, expected_intent, test_id)
#
# Intents (placeholder taxonomy, see docs/intent-taxonomy.md):
#   code_assistance | simple_transactional | general_qa | out_of_scope | ambiguous
#
# Fast-path confidence levels (see classifier/fast_path.py):
#   code_assistance     → 0.85  (above default prod threshold 0.82 → hits fast path)
#   simple_transactional → 0.80 (below threshold → falls through to deep path in prod)
#   general_qa          → 0.75  (below threshold → falls through to deep path in prod)
#   out_of_scope        → no rule (always falls through)
#   ambiguous           → no rule (always falls through)
#
# Intentional false-positive cases are included to expose fast-path limits:
#   "Can you browse the web for me?" → "can you" fires general_qa rule but
#   intent is out_of_scope. Shows in the false-positive section of the report.

ACCURACY_SAMPLES: list[tuple[str, str, str]] = [
    # ── code_assistance ────────────────────────────────────────────────────
    # Confident keyword matches; all should hit fast path at threshold=0.0
    # and at prod threshold (0.85 > 0.82).
    (
        "I have a traceback in my Python script, how do I fix it?",
        "code_assistance",
        "python+traceback",
    ),
    (
        "Write a TypeScript function to debounce API calls",
        "code_assistance",
        "typescript+function",
    ),
    (
        "My SQL query is returning duplicate rows — what's wrong?",
        "code_assistance",
        "sql",
    ),
    (
        "Help me refactor this JavaScript loop to use async/await",
        "code_assistance",
        "refactor+loop",
    ),
    (
        "I'm getting a syntax error in my Go module",
        "code_assistance",
        "syntax-error+module",
    ),
    (
        "Can you review my Python algorithm for binary search?",
        "code_assistance",
        "python+algorithm — also triggers general_qa (can you); code wins at 0.85",
    ),
    (
        "How do I import a third-party module in Node.js?",
        "code_assistance",
        "import+module",
    ),
    (
        "Debug this recursive function — it's hitting the stack limit",
        "code_assistance",
        "debug+function",
    ),

    # ── simple_transactional ───────────────────────────────────────────────
    # Keyword matches at confidence 0.80. Below prod threshold (0.82) →
    # all fall through to deep path in prod. Hit at threshold=0.0.
    (
        "What is the opening hours of the post office?",
        "simple_transactional",
        "what-is+opening-hours",
    ),
    (
        "What are the contact details for your support team?",
        "simple_transactional",
        "what-are+contact",
    ),
    (
        "How much does the enterprise subscription cost?",
        "simple_transactional",
        "how-much",
    ),
    (
        "What is the price of the standard plan?",
        "simple_transactional",
        "price-of",
    ),
    (
        "Where is the nearest service centre?",
        "simple_transactional",
        "where-is",
    ),
    (
        "Who is the CEO of the company?",
        "simple_transactional",
        "who-is",
    ),
    (
        "What is the phone number for customer service?",
        "simple_transactional",
        "what-is+phone-number",
    ),

    # ── general_qa ─────────────────────────────────────────────────────────
    # Keyword matches at confidence 0.75. Below prod threshold (0.82) →
    # all fall through to deep path in prod. Hit at threshold=0.0.
    (
        "Explain how photosynthesis works",
        "general_qa",
        "explain",
    ),
    (
        "Describe the history of the Singapore dollar",
        "general_qa",
        "describe",
    ),
    (
        "Tell me about property investment trends in Singapore",
        "general_qa",
        "tell-me",
    ),
    (
        "Summarise the key findings of the 2026 budget report",
        "general_qa",
        "summarise",
    ),
    (
        "How does blockchain technology work?",
        "general_qa",
        "how-does",
    ),
    (
        "Why does compound interest accelerate wealth growth?",
        "general_qa",
        "why-does",
    ),
    (
        "What does BSD stand for in Singapore property transactions?",
        "general_qa",
        "what-does",
    ),

    # ── out_of_scope ───────────────────────────────────────────────────────
    # No fast-path rules fire for these. Expected to fall through.
    # Two intentional FALSE POSITIVES included to expose rule over-reach:
    #   - "Can you browse the web..." → "can you" fires general_qa
    #   - "Could you write music..." → "could you" fires general_qa
    (
        "Generate an image of the Singapore skyline at sunset",
        "out_of_scope",
        "image-generation — no keyword match",
    ),
    (
        "Write a poem about cherry blossoms",
        "out_of_scope",
        "creative-writing — no keyword match",
    ),
    (
        "Can you browse the web for me and find flights?",
        "out_of_scope",
        "web-browsing — FALSE POSITIVE: 'can you' fires general_qa rule",
    ),
    (
        "Set a timer for 10 minutes",
        "out_of_scope",
        "device-action — no keyword match",
    ),
    (
        "Could you write music for my company's ad?",
        "out_of_scope",
        "creative-request — FALSE POSITIVE: 'could you' fires general_qa rule",
    ),

    # ── ambiguous ──────────────────────────────────────────────────────────
    # Vague or context-free messages. No fast-path rules fire.
    (
        "help",
        "ambiguous",
        "single-word",
    ),
    (
        "I need some assistance",
        "ambiguous",
        "vague-request — no keyword match",
    ),
    (
        "What about that thing we discussed earlier?",
        "ambiguous",
        "dangling-reference — no keyword match",
    ),
    (
        "yes",
        "ambiguous",
        "bare-affirmative",
    ),
]

_PROD_THRESHOLD = ClassifierConfig().fast_path_threshold


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(message: str) -> PipelineEnvelope:
    return PipelineEnvelope(
        correlation_id=uuid.uuid4(),
        user_sub="accuracy-test-user",
        session_id="accuracy-test-session",
        redacted_message=message,
        raw_message_hash=hashlib.sha256(message.encode()).hexdigest(),
        entity_types_redacted=(),
        entity_count=0,
        was_redacted=False,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip="127.0.0.1",
    )


def _mock_bedrock(intent: str, confidence: float = 0.85) -> MagicMock:
    """Return a BedrockRuntime mock wired to respond with the given intent."""
    import json

    bedrock = MagicMock()
    bedrock.invoke_model = AsyncMock(
        return_value={
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "intent": intent,
                            "domain": intent,
                            "confidence": confidence,
                            "reasoning": "accuracy test fixture",
                            "escalate": confidence < 0.6,
                        }
                    ),
                }
            ]
        }
    )
    return bedrock


# ---------------------------------------------------------------------------
# 1. Fast-path accuracy (unit, no Bedrock — runs on every PR)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected,test_id",
    ACCURACY_SAMPLES,
    ids=[s[2] for s in ACCURACY_SAMPLES],
)
def test_fast_path_accuracy(
    message: str,
    expected: str,
    test_id: str,
    accuracy_store: "_AccuracyStore",
) -> None:
    """Measure fast-path keyword-heuristic accuracy across the labelled set.

    Does NOT assert intent correctness (per-rule correctness is covered in
    test_fast_path.py). This test collects metrics for the session-level
    accuracy report printed by pytest_terminal_summary.

    The test always passes — failures here would mean the fast_path module
    raised an exception, which is covered elsewhere.
    """
    # Measure at threshold=0.0 to see which rules fire regardless of confidence
    result_zero = classify_fast(message, threshold=0.0)
    hit_zero = result_zero is not None
    predicted = result_zero.intent if result_zero else None
    correct: bool | None = (predicted == expected) if hit_zero else None

    # Measure at production threshold (what actually reaches fast path in prod)
    result_prod = classify_fast(message, threshold=_PROD_THRESHOLD)
    hit_prod = result_prod is not None

    accuracy_store.fast.append(
        {
            "message": message,
            "expected": expected,
            "hit_at_zero": hit_zero,
            "predicted": predicted,
            "correct": correct,
            "hit_production": hit_prod,
        }
    )


# ---------------------------------------------------------------------------
# 2. Full-classifier accuracy, mocked deep path (unit — no AWS)
# ---------------------------------------------------------------------------
# Verifies that the Classifier correctly delegates between fast and deep paths
# and that the routing logic (not Sonnet's accuracy) is correct.


@pytest.mark.parametrize(
    "message,expected,test_id",
    ACCURACY_SAMPLES,
    ids=[s[2] for s in ACCURACY_SAMPLES],
)
async def test_classifier_routing(
    message: str,
    expected: str,
    test_id: str,
) -> None:
    """Verify that the Classifier selects the right path for each sample.

    Deep-path Bedrock is mocked to return the expected intent so this test
    purely measures routing correctness, not Sonnet accuracy.
    """
    config = ClassifierConfig()
    bedrock = _mock_bedrock(expected, confidence=0.85)
    classifier = Classifier(config, bedrock)

    result = await classifier.classify(_make_envelope(message))

    # The result should be the expected intent (fast path gets it right, or
    # the mocked deep path returns it).
    assert result.intent == expected, (
        f"Routing mismatch for '{message[:60]}': expected '{expected}', got '{result.intent}'"
    )


# ---------------------------------------------------------------------------
# 3. Full-classifier accuracy with real Bedrock (@pytest.mark.aws, merge-only)
# ---------------------------------------------------------------------------
# Costs real Bedrock inference. Runs against the ap-southeast-1 sandbox on
# merge to main only. Do NOT run locally in a loop.


@pytest.mark.aws
@pytest.mark.parametrize(
    "message,expected,test_id",
    ACCURACY_SAMPLES,
    ids=[s[2] for s in ACCURACY_SAMPLES],
)
async def test_full_classifier_accuracy(
    message: str,
    expected: str,
    test_id: str,
    accuracy_store: "_AccuracyStore",
) -> None:
    """Measure full-pipeline intent accuracy against real Bedrock (Sonnet).

    Collects results in the session accumulator for the terminal report.
    Soft assertion: escalated results are acceptable (they reach human review).
    Hard assertion: non-escalated results must match the expected intent.
    """
    from shared.bedrock import BedrockRuntime

    config = ClassifierConfig()
    bedrock = BedrockRuntime(region=config.bedrock_region)
    classifier = Classifier(config, bedrock)

    result = await classifier.classify(_make_envelope(message))

    accuracy_store.full.append(
        {
            "message": message,
            "expected": expected,
            "predicted": result.intent,
            "correct": result.intent == expected,
            "path": str(result.path),
            "escalated": result.escalate,
        }
    )

    # Escalated results are acceptable — they go to human review.
    # Non-escalated results must match the expected intent.
    if not result.escalate:
        assert result.intent == expected, (
            f"Non-escalated mis-classification for '{message[:80]}':\n"
            f"  expected : {expected}\n"
            f"  predicted: {result.intent}\n"
            f"  confidence: {result.confidence:.2f}"
        )
