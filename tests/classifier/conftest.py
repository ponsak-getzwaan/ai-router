"""Shared fixtures and accuracy-report hook for classifier tests.

The accuracy store is attached to the pytest Config object in
pytest_configure so it can be accessed both from session fixtures
(injected into tests) and from the pytest_terminal_summary hook.
"""

from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Store — plain dicts, no external deps
# ---------------------------------------------------------------------------
# Each fast-path result dict:
#   message, expected, hit_at_zero, predicted, correct, hit_production
#
# Each full-classifier result dict:
#   message, expected, predicted, correct, path, escalated


class _AccuracyStore:
    def __init__(self) -> None:
        self.fast: list[dict[str, Any]] = []
        self.full: list[dict[str, Any]] = []

    def has_data(self) -> bool:
        return bool(self.fast or self.full)

    # ------------------------------------------------------------------
    # Report rendering
    # ------------------------------------------------------------------

    def render(self) -> list[str]:
        lines: list[str] = []
        if self.fast:
            lines.extend(self._render_fast())
        if self.full:
            lines.append("")
            lines.extend(self._render_full())
        return lines

    def _render_fast(self) -> list[str]:
        sep = "─" * 76
        lines = ["", "FAST-PATH ACCURACY  (keyword heuristics, no Bedrock)", sep]

        intents = sorted({r["expected"] for r in self.fast})

        lines.append(
            f"  {'Intent':<26} {'Samples':>7} {'Hit@0':>6} "
            f"{'Correct':>8} {'Precision':>10} {'Recall':>7} {'Prod-hit':>9}"
        )
        lines.append("  " + "─" * 72)

        for intent in intents:
            rows = [r for r in self.fast if r["expected"] == intent]
            n = len(rows)
            hits = [r for r in rows if r["hit_at_zero"]]
            h = len(hits)
            correct = [r for r in hits if r["correct"]]
            c = len(correct)
            prod = sum(1 for r in rows if r["hit_production"])

            precision = f"{c / h * 100:.1f}%" if h else "   —  "
            recall = f"{c / n * 100:.1f}%" if n else "  —  "
            lines.append(
                f"  {intent:<26} {n:>7} {h:>6} {c:>8} "
                f"{precision:>10} {recall:>7} {prod:>9}"
            )

        lines.append("  " + "─" * 72)
        total = len(self.fast)
        hits_zero = sum(1 for r in self.fast if r["hit_at_zero"])
        correct_zero = sum(1 for r in self.fast if r.get("correct"))
        hits_prod = sum(1 for r in self.fast if r["hit_production"])
        fp = hits_zero - correct_zero

        lines.append(f"  TOTAL {total} samples")
        cov_zero = f"{hits_zero / total * 100:.1f}%" if total else "—"
        prec_zero = f"{correct_zero / hits_zero * 100:.1f}%" if hits_zero else "—"
        cov_prod = f"{hits_prod / total * 100:.1f}%" if total else "—"
        lines.append(f"  Coverage  at threshold=0.0  : {hits_zero}/{total} ({cov_zero})")
        lines.append(f"  Precision at threshold=0.0  : {correct_zero}/{hits_zero} ({prec_zero})")
        lines.append(f"  False positives             : {fp}")
        lines.append(f"  Coverage  at prod threshold : {hits_prod}/{total} ({cov_prod})")

        fps = [r for r in self.fast if r["hit_at_zero"] and not r.get("correct")]
        if fps:
            lines.append("")
            lines.append("  FALSE POSITIVES (fast-path mis-classification):")
            for r in fps:
                msg = r["message"]
                short = msg[:58] + "…" if len(msg) > 58 else msg
                lines.append(
                    f"    expected [{r['expected']:>20}] → predicted [{r['predicted']}]: \"{short}\""
                )

        return lines

    def _render_full(self) -> list[str]:
        sep = "─" * 76
        lines = ["FULL CLASSIFIER ACCURACY  (@pytest.mark.aws — real Bedrock)", sep]

        total = len(self.full)
        if total == 0:
            lines.append("  No results collected.")
            return lines

        correct_all = sum(1 for r in self.full if r["correct"])
        overall = f"{correct_all / total * 100:.1f}%"
        lines.append(f"  Overall accuracy: {correct_all}/{total} ({overall})")
        lines.append("")

        intents = sorted({r["expected"] for r in self.full})
        lines.append(
            f"  {'Intent':<26} {'Samples':>7} {'Correct':>8} {'Accuracy':>9} {'Escalated':>10}"
        )
        lines.append("  " + "─" * 62)

        for intent in intents:
            rows = [r for r in self.full if r["expected"] == intent]
            n = len(rows)
            c = sum(1 for r in rows if r["correct"])
            esc = sum(1 for r in rows if r["escalated"])
            acc = f"{c / n * 100:.1f}%" if n else "—"
            lines.append(f"  {intent:<26} {n:>7} {c:>8} {acc:>9} {esc:>10}")

        fast_n = sum(1 for r in self.full if r["path"] == "fast")
        deep_n = total - fast_n
        lines.append("  " + "─" * 62)
        lines.append(
            f"  Path split: fast={fast_n} ({fast_n / total * 100:.1f}%)  "
            f"deep={deep_n} ({deep_n / total * 100:.1f}%)"
        )

        wrong = [r for r in self.full if not r["correct"]]
        if wrong:
            lines.append("")
            lines.append("  MISCLASSIFIED:")
            for r in wrong:
                msg = r["message"]
                short = msg[:52] + "…" if len(msg) > 52 else msg
                lines.append(
                    f"    expected [{r['expected']:>20}] → got [{r['predicted']}]: \"{short}\""
                )

        return lines


# ---------------------------------------------------------------------------
# Pytest integration
# ---------------------------------------------------------------------------


def pytest_configure(config: Any) -> None:
    config._classifier_accuracy = _AccuracyStore()


@pytest.fixture(scope="session")
def accuracy_store(pytestconfig: Any) -> _AccuracyStore:
    return pytestconfig._classifier_accuracy  # type: ignore[attr-defined, no-any-return]


def pytest_terminal_summary(
    terminalreporter: Any,
    exitstatus: Any,
    config: Any,
) -> None:
    store: _AccuracyStore | None = getattr(config, "_classifier_accuracy", None)
    if store and store.has_data():
        terminalreporter.write_sep("=", "CLASSIFIER ACCURACY REPORT")
        for line in store.render():
            terminalreporter.write_line(line)
        terminalreporter.write_sep("=", "")
