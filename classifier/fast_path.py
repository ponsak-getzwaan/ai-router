"""Fast-path intent classifier using keyword heuristics.

Phase 1 MVP: pattern matching instead of Titan embeddings to avoid
the overhead of maintaining intent vectors in DynamoDB. Titan embedding
similarity is the Phase 2 upgrade path — just swap out _match() below.

Returns None if no pattern matches with sufficient confidence, which
triggers the deep path (Sonnet).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.models import ClassifiedIntent, ClassifierPath, Confidence, IntentDomain


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    intent: str
    domain: IntentDomain
    confidence: Confidence


_ESCALATE_THRESHOLD: float = 0.6

_RULES: tuple[_Rule, ...] = (
    # Code assistance — high signal keywords
    _Rule(
        re.compile(
            r"\b(debug|traceback|syntax error|exception|stacktrace|"
            r"function|class|method|variable|loop|import|module|"
            r"python|javascript|typescript|golang|rust|java|sql|"
            r"code|script|program|algorithm|refactor)\b",
            re.IGNORECASE,
        ),
        intent="code_assistance",
        domain=IntentDomain.CODE_ASSISTANCE,
        confidence=0.85,
    ),
    # Simple transactional — short, imperative, lookup-style
    _Rule(
        re.compile(
            r"\b(what is|what are|who is|who are|when is|where is|how much|"
            r"price of|cost of|opening hours|contact|phone number|address)\b",
            re.IGNORECASE,
        ),
        intent="simple_transactional",
        domain=IntentDomain.SIMPLE_TRANSACTIONAL,
        confidence=0.80,
    ),
    # General Q&A — catch-all for question patterns
    _Rule(
        re.compile(
            r"\b(explain|describe|summarise|summarize|tell me|"
            r"how does|how do|how can|why does|what does|can you|could you|"
            r"do you|are you|help me understand|I want to know)\b",
            re.IGNORECASE,
        ),
        intent="general_qa",
        domain=IntentDomain.GENERAL_QA,
        confidence=0.75,
    ),
)


def classify_fast(
    message: str,
    threshold: float,
) -> ClassifiedIntent | None:
    """Return a ClassifiedIntent if any rule fires above threshold, else None."""
    best: _Rule | None = None
    for rule in _RULES:
        if rule.pattern.search(message) and (best is None or rule.confidence > best.confidence):
            best = rule

    if best is None or best.confidence < threshold:
        return None

    return ClassifiedIntent(
        intent=best.intent,
        domain=best.domain,
        confidence=best.confidence,
        resolved_message=message,
        path=ClassifierPath.FAST,
        escalate=best.confidence < _ESCALATE_THRESHOLD,
    )
