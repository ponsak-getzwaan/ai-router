"""Golden-file tests for Singapore Presidio recognisers.

Skipped automatically if presidio_analyzer is not installed (it lives only in
the presidio sidecar container, not the orchestrator venv).

Each golden file in tests/redactor/golden/ defines:
  - input: the raw text to analyse
  - expected: list of {entity_type, value} dicts expected to be found
  - description: human-readable label (used as the test ID)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

presidio_analyzer = pytest.importorskip("presidio_analyzer")  # skip if not installed

from presidio_analyzer import AnalyzerEngine  # noqa: E402  # type: ignore[import-untyped]

from presidio_sidecar.recognisers import (  # noqa: E402
    SGFINRecognizer,
    SGNRICRecognizer,
    SGPassportRecognizer,
    SGUENRecognizer,
)

_GOLDEN_DIR = Path(__file__).parent / "golden"


def _load_golden_cases() -> list[tuple[str, dict[str, Any]]]:
    """Return list of (file_stem, data) for all golden JSON files."""
    cases = []
    for path in sorted(_GOLDEN_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        cases.append((path.stem, data))
    return cases


_GOLDEN_CASES = _load_golden_cases()
_GOLDEN_IDS = [stem for stem, _ in _GOLDEN_CASES]


@pytest.fixture(scope="module")
def engine() -> AnalyzerEngine:
    """Build an AnalyzerEngine with Singapore recognisers registered."""
    analyzer = AnalyzerEngine()
    for rec in [SGNRICRecognizer(), SGFINRecognizer(), SGUENRecognizer(), SGPassportRecognizer()]:
        analyzer.registry.add_recognizer(rec)
    return analyzer


@pytest.mark.parametrize("_stem,case", _GOLDEN_CASES, ids=_GOLDEN_IDS)
def test_golden_file(engine: AnalyzerEngine, _stem: str, case: dict[str, Any]) -> None:
    """Each expected entity must be found in the analyzer results."""
    input_text: str = case["input"]
    expected: list[dict[str, str]] = case["expected"]

    sg_entities = ["SG_NRIC", "SG_FIN", "SG_UEN", "SG_PASSPORT"]
    results = engine.analyze(text=input_text, entities=sg_entities, language="en")

    # Build a set of (entity_type, value) tuples from the results
    found = {
        (r.entity_type, input_text[r.start : r.end])
        for r in results
    }

    for exp in expected:
        assert (exp["entity_type"], exp["value"]) in found, (
            f"[{case['description']}] expected {exp!r} but found: {found}"
        )


def test_no_false_positives(engine: AnalyzerEngine) -> None:
    """Strings that look similar to SG IDs must not trigger recognisers."""
    golden_path = _GOLDEN_DIR / "no_false_positives.json"
    with golden_path.open(encoding="utf-8") as fh:
        case = json.load(fh)

    input_text: str = case["input"]
    sg_entities = ["SG_NRIC", "SG_FIN", "SG_UEN", "SG_PASSPORT"]
    results = engine.analyze(text=input_text, entities=sg_entities, language="en")

    assert results == [], (
        f"[{case['description']}] expected no matches but got: {results}"
    )
