"""Classifier accuracy test report.

Measures the classifier's correctness against a 30-sample labelled dataset
covering all five intents (placeholder taxonomy — see docs/intent-taxonomy.md).

Two test layers:

  1. Classifier routing accuracy (mocked deep path, no AWS — runs on every PR).
     Verifies end-to-end routing: the Classifier returns the correct intent
     for every sample when the deep path is mocked to echo the expected label.

  2. Full-classifier accuracy (real Bedrock — @pytest.mark.aws, merge-only).
     Sends every sample through the full Classifier.classify() pipeline
     and measures Sonnet's intent classification accuracy.

Usage:
  # Routing test only (no AWS, safe to run locally):
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

ACCURACY_SAMPLES: list[tuple[str, str, str]] = [
    # ── code_assistance ────────────────────────────────────────────────────
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
        "python+algorithm",
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
    (
        "Generate an image of the Singapore skyline at sunset",
        "out_of_scope",
        "image-generation",
    ),
    (
        "Write a poem about cherry blossoms",
        "out_of_scope",
        "creative-writing",
    ),
    (
        "Can you browse the web for me and find flights?",
        "out_of_scope",
        "web-browsing",
    ),
    (
        "Set a timer for 10 minutes",
        "out_of_scope",
        "device-action",
    ),
    (
        "Could you write music for my company's ad?",
        "out_of_scope",
        "creative-request",
    ),

    # ── ambiguous ──────────────────────────────────────────────────────────
    (
        "help",
        "ambiguous",
        "single-word",
    ),
    (
        "I need some assistance",
        "ambiguous",
        "vague-request",
    ),
    (
        "What about that thing we discussed earlier?",
        "ambiguous",
        "dangling-reference",
    ),
    (
        "yes",
        "ambiguous",
        "bare-affirmative",
    ),
]

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
# 1. Classifier routing accuracy, mocked deep path (unit — no AWS)
# ---------------------------------------------------------------------------
# The embedding fast path requires Bedrock, so initialize() is not called here.
# EmbeddingFastPath returns None (not-initialized guard), and the mocked deep
# path handles all samples. This verifies end-to-end pipeline routing.


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
    """Verify the full pipeline returns the correct intent for each sample.

    Deep-path Bedrock is mocked to return the expected intent. Fast path is
    not initialized so it returns None for all inputs, ensuring the deep path
    mock is always exercised. Tests routing correctness, not Sonnet accuracy.
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
# 2. Full-classifier accuracy with real Bedrock (@pytest.mark.aws, merge-only)
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
