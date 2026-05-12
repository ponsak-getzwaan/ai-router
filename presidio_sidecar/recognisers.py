"""Custom Presidio recognisers for Singapore entity types.

See docs/architecture.md §"PII redaction" and CLAUDE.md §7 Redactor.
Golden-file tests live in tests/redactor/golden/.
"""

from __future__ import annotations

import re

from presidio_analyzer import Pattern, PatternRecognizer  # type: ignore[import-untyped]


class SGNRICRecognizer(PatternRecognizer):
    """Singapore NRIC (citizens): starts with S or T."""

    PATTERNS = [
        Pattern(
            "SG_NRIC",
            r"\b[ST]\d{7}[A-Z]\b",
            score=0.85,
        )
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="SG_NRIC",
            patterns=self.PATTERNS,
            context=["nric", "ic", "identity card", "national registration"],
        )


class SGFINRecognizer(PatternRecognizer):
    """Singapore FIN (foreign permanent residents): starts with F, G, or M."""

    PATTERNS = [
        Pattern(
            "SG_FIN",
            r"\b[FGM]\d{7}[A-Z]\b",
            score=0.85,
        )
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="SG_FIN",
            patterns=self.PATTERNS,
            context=["fin", "foreign identification", "employment pass", "work permit"],
        )


class SGUENRecognizer(PatternRecognizer):
    """Singapore UEN (business entity number): 9-10 chars."""

    PATTERNS = [
        Pattern(
            "SG_UEN_STANDARD",
            r"\b\d{8}[A-Z]\b",
            score=0.75,
        ),
        Pattern(
            "SG_UEN_LOCAL_COMPANY",
            r"\b\d{9}[A-Z]\b",
            score=0.75,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="SG_UEN",
            patterns=self.PATTERNS,
            context=["uen", "business registration", "acra", "company number"],
        )


class SGPassportRecognizer(PatternRecognizer):
    """Singapore passport number: E or K + 7 digits + letter."""

    PATTERNS = [
        Pattern(
            "SG_PASSPORT",
            r"\b[EK]\d{7}[A-Z]\b",
            score=0.75,
        )
    ]

    def __init__(self) -> None:
        super().__init__(
            supported_entity="SG_PASSPORT",
            patterns=self.PATTERNS,
            context=["passport", "travel document"],
        )


def get_singapore_recognizers() -> list[PatternRecognizer]:
    return [
        SGNRICRecognizer(),
        SGFINRecognizer(),
        SGUENRecognizer(),
        SGPassportRecognizer(),
    ]
