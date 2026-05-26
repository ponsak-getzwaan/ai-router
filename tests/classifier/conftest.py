"""Shared fixtures and accuracy-report hook for classifier tests.

The accuracy store is attached to the pytest Config object in
pytest_configure so it can be accessed both from session fixtures
(injected into tests) and from the pytest_terminal_summary hook.

An HTML report is written to reports/classifier-accuracy.html at session end.
"""

from __future__ import annotations

import html
import pathlib
from datetime import UTC, datetime
from typing import Any

import pytest

_REPORT_PATH = pathlib.Path("reports/classifier-accuracy.html")


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

    # ------------------------------------------------------------------
    # HTML report
    # ------------------------------------------------------------------

    def render_html(self, generated_at: str) -> str:
        fast_table = self._html_fast_table()
        fps_section = self._html_false_positives()
        full_section = self._html_full_section()

        total = len(self.fast)
        hits_zero = sum(1 for r in self.fast if r["hit_at_zero"])
        correct_zero = sum(1 for r in self.fast if r.get("correct"))
        hits_prod = sum(1 for r in self.fast if r["hit_production"])
        fp_count = hits_zero - correct_zero

        cov_zero = f"{hits_zero / total * 100:.1f}%" if total else "—"
        prec_zero = f"{correct_zero / hits_zero * 100:.1f}%" if hits_zero else "—"
        cov_prod = f"{hits_prod / total * 100:.1f}%" if total else "—"

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Classifier Accuracy Report — Evidor.ai</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', system-ui, sans-serif;
      background: #FAFAF7;
      color: #1A1F2E;
      padding: 2rem;
      line-height: 1.5;
    }}
    header {{
      background: #0E3B2A;
      color: #FAFAF7;
      border-radius: 0.75rem;
      padding: 1.5rem 2rem;
      margin-bottom: 1.5rem;
      display: flex;
      align-items: baseline;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}
    header h1 {{ font-size: 1.25rem; font-weight: 600; }}
    header h1 span {{ opacity: 0.6; font-weight: 400; }}
    header .meta {{
      margin-left: auto;
      font-size: 0.75rem;
      opacity: 0.6;
      white-space: nowrap;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }}
    .kpi {{
      background: #F5F2EB;
      border: 1px solid #E5E2D8;
      border-radius: 0.5rem;
      padding: 1rem 1.25rem;
    }}
    .kpi .label {{
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #5a6b64;
      margin-bottom: 0.35rem;
    }}
    .kpi .value {{
      font-size: 1.5rem;
      font-weight: 600;
      color: #0E3B2A;
    }}
    .kpi .sub {{ font-size: 0.75rem; color: #5a6b64; margin-top: 0.15rem; }}
    .kpi.warn .value {{ color: #C76E3A; }}
    section {{
      background: #F5F2EB;
      border: 1px solid #E5E2D8;
      border-radius: 0.5rem;
      margin-bottom: 1.5rem;
      overflow: hidden;
    }}
    section h2 {{
      font-size: 0.8rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #5a6b64;
      padding: 0.75rem 1.25rem;
      border-bottom: 1px solid #E5E2D8;
      background: #F5F2EB;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
    }}
    th {{
      background: #0E3B2A;
      color: #FAFAF7;
      font-weight: 500;
      font-size: 0.75rem;
      text-align: left;
      padding: 0.6rem 1rem;
    }}
    td {{
      padding: 0.6rem 1rem;
      border-bottom: 1px solid #E5E2D8;
      vertical-align: middle;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #ede9df; }}
    .badge {{
      display: inline-block;
      border-radius: 999px;
      padding: 0.15rem 0.55rem;
      font-size: 0.72rem;
      font-weight: 500;
    }}
    .badge-green  {{ background: #dcfce7; color: #166534; }}
    .badge-amber  {{ background: #ffedd5; color: #9a3412; }}
    .badge-red    {{ background: #fee2e2; color: #991b1b; }}
    .badge-slate  {{ background: #f1f5f9; color: #475569; }}
    .badge-forest {{ background: #d1fae5; color: #065f46; }}
    .fp-list {{ padding: 1rem 1.25rem; display: flex; flex-direction: column; gap: 0.6rem; }}
    .fp-card {{
      background: #fff7ed;
      border: 1px solid #fed7aa;
      border-radius: 0.375rem;
      padding: 0.75rem 1rem;
      font-size: 0.83rem;
    }}
    .fp-card .arrow {{ color: #C76E3A; font-weight: 600; margin: 0 0.3rem; }}
    .fp-card .msg {{ color: #5a6b64; margin-top: 0.25rem; font-size: 0.78rem; font-style: italic; }}
    .no-data {{ padding: 2rem; text-align: center; color: #5a6b64; font-size: 0.85rem; }}
    footer {{
      text-align: center;
      font-size: 0.72rem;
      color: #5a6b64;
      margin-top: 2rem;
    }}
    .right {{ text-align: right; }}
    .center {{ text-align: center; }}
  </style>
</head>
<body>

<header>
  <h1>Evidor<span>.ai</span> &nbsp;·&nbsp; Classifier Accuracy Report</h1>
  <div class="meta">Generated {generated_at}</div>
</header>

<div class="summary-grid">
  <div class="kpi">
    <div class="label">Total samples</div>
    <div class="value">{total}</div>
    <div class="sub">31 labelled messages, 5 intents</div>
  </div>
  <div class="kpi">
    <div class="label">Fast-path coverage (threshold=0.0)</div>
    <div class="value">{cov_zero}</div>
    <div class="sub">{hits_zero} of {total} triggered a rule</div>
  </div>
  <div class="kpi">
    <div class="label">Fast-path precision (threshold=0.0)</div>
    <div class="value">{prec_zero}</div>
    <div class="sub">{correct_zero} of {hits_zero} correct</div>
  </div>
  <div class="kpi{'  warn' if fp_count > 0 else ''}">
    <div class="label">False positives</div>
    <div class="value">{fp_count}</div>
    <div class="sub">wrong intent from fast-path rule</div>
  </div>
  <div class="kpi">
    <div class="label">Production hit rate</div>
    <div class="value">{cov_prod}</div>
    <div class="sub">{hits_prod} of {total} hit fast path at prod threshold</div>
  </div>
</div>

{fast_table}
{fps_section}
{full_section}

<footer>
  Evidor.ai &mdash; Classifier Accuracy Report &mdash; {generated_at}<br>
  Run: <code>uv run pytest tests/classifier/test_accuracy.py -v -m "not aws"</code>
</footer>

</body>
</html>"""

    def _html_fast_table(self) -> str:
        if not self.fast:
            return ""

        intents = sorted({r["expected"] for r in self.fast})
        rows_html = ""
        for intent in intents:
            rows = [r for r in self.fast if r["expected"] == intent]
            n = len(rows)
            hits = [r for r in rows if r["hit_at_zero"]]
            h = len(hits)
            correct = [r for r in hits if r["correct"]]
            c = len(correct)
            prod = sum(1 for r in rows if r["hit_production"])

            precision_val = c / h * 100 if h else None
            recall_val = c / n * 100 if n else None

            precision_str = f"{precision_val:.1f}%" if precision_val is not None else "—"
            recall_str = f"{recall_val:.1f}%" if recall_val is not None else "—"

            def _pct_badge(val: float | None, text: str) -> str:
                if val is None:
                    return f'<span class="badge badge-slate">—</span>'
                cls = "badge-green" if val >= 90 else "badge-amber" if val >= 70 else "badge-red"
                return f'<span class="badge {cls}">{text}</span>'

            prod_badge = (
                f'<span class="badge badge-forest">{prod}</span>'
                if prod > 0
                else f'<span class="badge badge-slate">0</span>'
            )

            rows_html += f"""
        <tr>
          <td><code>{html.escape(intent)}</code></td>
          <td class="center">{n}</td>
          <td class="center">{h}</td>
          <td class="center">{c}</td>
          <td class="center">{_pct_badge(precision_val, precision_str)}</td>
          <td class="center">{_pct_badge(recall_val, recall_str)}</td>
          <td class="center">{prod_badge}</td>
        </tr>"""

        return f"""
<section>
  <h2>Fast-path accuracy &mdash; keyword heuristics, no Bedrock</h2>
  <table>
    <thead>
      <tr>
        <th>Intent</th>
        <th class="center">Samples</th>
        <th class="center">Hit @ 0.0</th>
        <th class="center">Correct</th>
        <th class="center">Precision</th>
        <th class="center">Recall</th>
        <th class="center">Prod hit</th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>
</section>"""

    def _html_false_positives(self) -> str:
        fps = [r for r in self.fast if r["hit_at_zero"] and not r.get("correct")]
        if not fps:
            return ""

        cards = ""
        for r in fps:
            cards += f"""
      <div class="fp-card">
        <span class="badge badge-slate">{html.escape(r['expected'])}</span>
        <span class="arrow">→</span>
        <span class="badge badge-amber">{html.escape(str(r['predicted']))}</span>
        <div class="msg">&ldquo;{html.escape(r['message'])}&rdquo;</div>
      </div>"""

        return f"""
<section>
  <h2>False positives &mdash; fast-path rule fired with wrong intent</h2>
  <div class="fp-list">{cards}
  </div>
</section>"""

    def _html_full_section(self) -> str:
        if not self.full:
            return """
<section>
  <h2>Full classifier accuracy &mdash; real Bedrock (@pytest.mark.aws)</h2>
  <p class="no-data">No data — run with <code>-m aws</code> against a real Bedrock endpoint.</p>
</section>"""

        total = len(self.full)
        correct_all = sum(1 for r in self.full if r["correct"])
        fast_n = sum(1 for r in self.full if r["path"] == "fast")
        deep_n = total - fast_n

        intents = sorted({r["expected"] for r in self.full})
        rows_html = ""
        for intent in intents:
            rows = [r for r in self.full if r["expected"] == intent]
            n = len(rows)
            c = sum(1 for r in rows if r["correct"])
            esc = sum(1 for r in rows if r["escalated"])
            acc_val = c / n * 100 if n else None
            acc_str = f"{acc_val:.1f}%" if acc_val is not None else "—"
            cls = "badge-green" if (acc_val or 0) >= 90 else "badge-amber" if (acc_val or 0) >= 70 else "badge-red"
            rows_html += f"""
        <tr>
          <td><code>{html.escape(intent)}</code></td>
          <td class="center">{n}</td>
          <td class="center">{c}</td>
          <td class="center"><span class="badge {cls}">{acc_str}</span></td>
          <td class="center">{esc}</td>
        </tr>"""

        wrong = [r for r in self.full if not r["correct"]]
        misclass_html = ""
        if wrong:
            cards = ""
            for r in wrong:
                cards += f"""
      <div class="fp-card">
        <span class="badge badge-slate">{html.escape(r['expected'])}</span>
        <span class="arrow">→</span>
        <span class="badge badge-red">{html.escape(r['predicted'])}</span>
        <div class="msg">&ldquo;{html.escape(r['message'])}&rdquo;</div>
      </div>"""
            misclass_html = f"""
  <h2 style="margin-top:1rem;">Misclassified samples</h2>
  <div class="fp-list">{cards}
  </div>"""

        return f"""
<section>
  <h2>Full classifier accuracy &mdash; real Bedrock (@pytest.mark.aws)</h2>
  <div class="summary-grid" style="padding:1rem 1.25rem; background:transparent; border:none; margin-bottom:0;">
    <div class="kpi">
      <div class="label">Overall accuracy</div>
      <div class="value">{correct_all / total * 100:.1f}%</div>
      <div class="sub">{correct_all} of {total} correct</div>
    </div>
    <div class="kpi">
      <div class="label">Fast path</div>
      <div class="value">{fast_n / total * 100:.1f}%</div>
      <div class="sub">{fast_n} samples</div>
    </div>
    <div class="kpi">
      <div class="label">Deep path (Sonnet)</div>
      <div class="value">{deep_n / total * 100:.1f}%</div>
      <div class="sub">{deep_n} samples</div>
    </div>
  </div>
  <table>
    <thead>
      <tr>
        <th>Intent</th>
        <th class="center">Samples</th>
        <th class="center">Correct</th>
        <th class="center">Accuracy</th>
        <th class="center">Escalated</th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>{misclass_html}
</section>"""


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


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    store: _AccuracyStore | None = getattr(session.config, "_classifier_accuracy", None)
    if not store or not store.has_data():
        return

    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(store.render_html(generated_at), encoding="utf-8")
    print(f"\n  HTML report -> {_REPORT_PATH.resolve()}")
