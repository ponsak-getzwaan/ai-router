"""Shared fixtures, helpers, and accuracy-report hook for Bouncer tests.

The accuracy store is attached to the pytest Config object in pytest_configure
so it can be shared between session fixtures (injected into tests) and the
pytest_terminal_summary / pytest_sessionfinish hooks.

An HTML report is written to reports/bouncer-accuracy.html at session end.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import pathlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import fakeredis.aioredis  # type: ignore[import-untyped]
import pytest

from bouncer.config import BouncerConfig
from bouncer.llm_classifier import MetricPublisher
from shared.models import PipelineEnvelope

_REPORT_PATH = pathlib.Path("reports/bouncer-accuracy.html")


class NoOpMetrics:
    """MetricPublisher that discards all metrics. Used in unit tests."""

    async def put_count(self, metric_name: str, dimensions: dict[str, str] | None = None) -> None:
        pass


assert isinstance(NoOpMetrics(), MetricPublisher), (
    "NoOpMetrics must satisfy MetricPublisher protocol"
)


@pytest.fixture
def config() -> BouncerConfig:
    return BouncerConfig(
        total_budget_ms=200.0,
        haiku_model_id="apac.test.fake-haiku:0",
        haiku_max_tokens=50,
        confidence_threshold=0.7,
        max_message_length=100,
        rate_limit_per_minute=5,
        redis_url="redis://localhost:6379",
        bedrock_region="ap-southeast-1",
        cloudwatch_namespace="AIRouter/Test",
    )


@pytest.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:  # type: ignore[misc]
    r: fakeredis.aioredis.FakeRedis = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


def make_envelope(
    message: str = "Hello, can you help me?",
    user_sub: str = "user-abc-123",
    source_ip: str = "1.2.3.4",
) -> PipelineEnvelope:
    """Build a valid PipelineEnvelope for testing."""
    raw_hash = hashlib.sha256(message.encode()).hexdigest()
    return PipelineEnvelope(
        correlation_id=uuid4(),
        user_sub=user_sub,
        session_id="session-abc-123",
        redacted_message=message,
        raw_message_hash=raw_hash,
        entity_types_redacted=(),
        entity_count=0,
        was_redacted=False,
        timestamp=datetime.now(UTC),
        bedrock_region="ap-southeast-1",
        source_ip=source_ip,
    )


# ---------------------------------------------------------------------------
# Accuracy store — plain dicts, no external deps
# ---------------------------------------------------------------------------
# Expected outcomes (see test_accuracy.py ACCURACY_SAMPLES):
#   "pass"            → rule gate passes, Haiku safe   (allowed=True,  escalate=False)
#   "block_injection" → rule gate blocks injection      (allowed=False, reason="prompt_injection_detected")
#   "block_length"    → rule gate blocks long message   (allowed=False, reason="message_too_long")
#   "escalate"        → rule gate passes, Haiku unsafe  (allowed=True,  escalate=True)
#
# Each rule-gate result dict:
#   message, expected, rule_gate_passed, rule_gate_reason, correct
#
# Each full-bouncer result dict:
#   message, expected, allowed, escalated, reason, timed_out, correct


class _BouncerAccuracyStore:
    def __init__(self) -> None:
        self.rule_gate: list[dict[str, Any]] = []
        self.full: list[dict[str, Any]] = []

    def has_data(self) -> bool:
        return bool(self.rule_gate or self.full)

    # ------------------------------------------------------------------
    # Terminal rendering
    # ------------------------------------------------------------------

    def render(self) -> list[str]:
        lines: list[str] = []
        if self.rule_gate:
            lines.extend(self._render_rule_gate())
        if self.full:
            lines.append("")
            lines.extend(self._render_full())
        return lines

    def _render_rule_gate(self) -> list[str]:
        sep = "─" * 74
        lines = ["", "RULE-GATE ACCURACY  (deterministic checks, no Bedrock)", sep]
        lines.append(
            f"  {'Outcome':<20} {'Samples':>7} {'Correct':>8} {'Accuracy':>9}"
        )
        lines.append("  " + "─" * 48)

        outcomes = sorted({r["expected"] for r in self.rule_gate})
        for outcome in outcomes:
            rows = [r for r in self.rule_gate if r["expected"] == outcome]
            n = len(rows)
            c = sum(1 for r in rows if r["correct"])
            acc = f"{c / n * 100:.1f}%" if n else "—"
            lines.append(f"  {outcome:<20} {n:>7} {c:>8} {acc:>9}")

        total = len(self.rule_gate)
        correct = sum(1 for r in self.rule_gate if r["correct"])
        lines.append("  " + "─" * 48)
        lines.append(f"  TOTAL {total} samples")
        overall = f"{correct / total * 100:.1f}%" if total else "—"
        lines.append(f"  Overall accuracy: {correct}/{total} ({overall})")

        wrong = [r for r in self.rule_gate if not r["correct"]]
        if wrong:
            lines.append("")
            lines.append("  WRONG (rule gate mis-classification):")
            for r in wrong:
                short = r["message"][:60] + "…" if len(r["message"]) > 60 else r["message"]
                lines.append(
                    f"    expected [{r['expected']:>16}] got pass={r['rule_gate_passed']}"
                    f" reason={r['rule_gate_reason']}: \"{short}\""
                )
        return lines

    def _render_full(self) -> list[str]:
        sep = "─" * 74
        lines = ["FULL BOUNCER ACCURACY  (@pytest.mark.aws — real Haiku)", sep]
        total = len(self.full)
        if total == 0:
            lines.append("  No results collected.")
            return lines

        correct = sum(1 for r in self.full if r["correct"])
        lines.append(f"  Overall accuracy: {correct}/{total} ({correct / total * 100:.1f}%)")
        lines.append("")
        lines.append(
            f"  {'Outcome':<20} {'Samples':>7} {'Correct':>8} {'Accuracy':>9} {'Escalated':>10}"
        )
        lines.append("  " + "─" * 58)

        for outcome in sorted({r["expected"] for r in self.full}):
            rows = [r for r in self.full if r["expected"] == outcome]
            n = len(rows)
            c = sum(1 for r in rows if r["correct"])
            esc = sum(1 for r in rows if r["escalated"])
            acc = f"{c / n * 100:.1f}%" if n else "—"
            lines.append(f"  {outcome:<20} {n:>7} {c:>8} {acc:>9} {esc:>10}")

        fn = [r for r in self.full if r["expected"] == "escalate" and not r["escalated"] and r["allowed"]]
        fp = [r for r in self.full if r["expected"] == "pass" and r["escalated"]]
        lines.append("  " + "─" * 58)
        lines.append(f"  False negatives (harmful not escalated): {len(fn)}")
        lines.append(f"  False positives (safe message escalated): {len(fp)}")

        wrong = [r for r in self.full if not r["correct"]]
        if wrong:
            lines.append("")
            lines.append("  WRONG:")
            for r in wrong:
                short = r["message"][:56] + "…" if len(r["message"]) > 56 else r["message"]
                lines.append(
                    f"    expected [{r['expected']:>16}] allowed={r['allowed']} "
                    f"escalated={r['escalated']}: \"{short}\""
                )
        return lines

    # ------------------------------------------------------------------
    # HTML rendering
    # ------------------------------------------------------------------

    def render_html(self, generated_at: str) -> str:
        rg_table = self._html_rg_table()
        rg_detail = self._html_rg_detail()
        full_section = self._html_full_section()
        full_detail = self._html_full_detail()

        total = len(self.rule_gate)
        correct = sum(1 for r in self.rule_gate if r["correct"])
        wrong_n = total - correct

        overall_rg = f"{correct / total * 100:.1f}%" if total else "—"

        full_total = len(self.full)
        fn_n = len([r for r in self.full if r["expected"] == "escalate" and not r["escalated"] and r["allowed"]])
        fp_n = len([r for r in self.full if r["expected"] == "pass" and r["escalated"]])

        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Bouncer Accuracy Report — Evidor.ai</title>
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
    header .meta {{ margin-left: auto; font-size: 0.75rem; opacity: 0.6; white-space: nowrap; }}
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
    .kpi .label {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.06em; color: #5a6b64; margin-bottom: 0.35rem; }}
    .kpi .value {{ font-size: 1.5rem; font-weight: 600; color: #0E3B2A; }}
    .kpi .sub {{ font-size: 0.75rem; color: #5a6b64; margin-top: 0.15rem; }}
    .kpi.warn .value {{ color: #C76E3A; }}
    .kpi.good .value {{ color: #0E3B2A; }}
    section {{
      background: #F5F2EB;
      border: 1px solid #E5E2D8;
      border-radius: 0.5rem;
      margin-bottom: 1.5rem;
      overflow: hidden;
    }}
    section h2 {{
      font-size: 0.8rem; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.06em; color: #5a6b64;
      padding: 0.75rem 1.25rem; border-bottom: 1px solid #E5E2D8;
    }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
    th {{
      background: #0E3B2A; color: #FAFAF7;
      font-weight: 500; font-size: 0.75rem;
      text-align: left; padding: 0.6rem 1rem;
    }}
    td {{ padding: 0.6rem 1rem; border-bottom: 1px solid #E5E2D8; vertical-align: middle; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #ede9df; }}
    .badge {{
      display: inline-block; border-radius: 999px;
      padding: 0.15rem 0.55rem; font-size: 0.72rem; font-weight: 500;
    }}
    .badge-green  {{ background: #dcfce7; color: #166534; }}
    .badge-amber  {{ background: #ffedd5; color: #9a3412; }}
    .badge-red    {{ background: #fee2e2; color: #991b1b; }}
    .badge-slate  {{ background: #f1f5f9; color: #475569; }}
    .badge-forest {{ background: #d1fae5; color: #065f46; }}
    .badge-blue   {{ background: #dbeafe; color: #1e40af; }}
    .no-data {{ padding: 2rem; text-align: center; color: #5a6b64; font-size: 0.85rem; }}
    footer {{ text-align: center; font-size: 0.72rem; color: #5a6b64; margin-top: 2rem; }}
    .right {{ text-align: right; }}
    .center {{ text-align: center; }}
    .msg-cell {{ max-width: 400px; word-break: break-word; font-size: 0.82rem; }}
    tr.row-ok td   {{ background: #f0fdf4; }}
    tr.row-ok:hover td {{ background: #bbf7d055; }}
    tr.row-bad td  {{ background: #fff7ed; }}
    tr.row-bad:hover td {{ background: #fed7aa55; }}
    tr.row-err td  {{ background: #fef2f2; }}
    tr.row-err:hover td {{ background: #fecaca55; }}
    tr.row-neutral td {{ background: #f8fafc; }}
  </style>
</head>
<body>

<header>
  <h1>Evidor<span>.ai</span> &nbsp;·&nbsp; Bouncer Accuracy Report</h1>
  <div class="meta">Generated {generated_at}</div>
</header>

<div class="summary-grid">
  <div class="kpi">
    <div class="label">Rule-gate samples</div>
    <div class="value">{total}</div>
    <div class="sub">pass · block_injection · block_length · escalate</div>
  </div>
  <div class="kpi good">
    <div class="label">Rule-gate accuracy</div>
    <div class="value">{overall_rg}</div>
    <div class="sub">{correct} of {total} correct</div>
  </div>
  <div class="kpi{'  warn' if wrong_n > 0 else ''}">
    <div class="label">Rule-gate errors</div>
    <div class="value">{wrong_n}</div>
    <div class="sub">mis-classified by rule checks</div>
  </div>
  <div class="kpi{'  warn' if fn_n > 0 else ''}">
    <div class="label">False negatives (Haiku)</div>
    <div class="value">{fn_n}</div>
    <div class="sub">harmful not escalated — populated by @aws tests</div>
  </div>
  <div class="kpi{'  warn' if fp_n > 0 else ''}">
    <div class="label">False positives (Haiku)</div>
    <div class="value">{fp_n}</div>
    <div class="sub">safe message escalated — populated by @aws tests</div>
  </div>
</div>

{rg_table}
{rg_detail}
{full_section}
{full_detail}

<footer>
  Evidor.ai &mdash; Bouncer Accuracy Report &mdash; {generated_at}<br>
  Run: <code>uv run pytest tests/bouncer/test_accuracy.py -v -m "not aws"</code>
</footer>

</body>
</html>"""

    # -- HTML sub-sections --------------------------------------------------

    def _outcome_badge(self, outcome: str) -> str:
        mapping = {
            "pass":            ("badge-green",  "pass"),
            "block_injection": ("badge-red",    "block · injection"),
            "block_length":    ("badge-red",    "block · too long"),
            "escalate":        ("badge-amber",  "escalate"),
        }
        cls, label = mapping.get(outcome, ("badge-slate", outcome))
        return f'<span class="badge {cls}">{html_mod.escape(label)}</span>'

    def _html_rg_table(self) -> str:
        if not self.rule_gate:
            return ""
        outcomes = sorted({r["expected"] for r in self.rule_gate})
        rows_html = ""
        for outcome in outcomes:
            rows = [r for r in self.rule_gate if r["expected"] == outcome]
            n = len(rows)
            c = sum(1 for r in rows if r["correct"])
            acc_val = c / n * 100 if n else None
            acc_str = f"{acc_val:.1f}%" if acc_val is not None else "—"
            cls = "badge-green" if (acc_val or 0) >= 100 else "badge-amber" if (acc_val or 0) >= 80 else "badge-red"
            rows_html += f"""
        <tr>
          <td>{self._outcome_badge(outcome)}</td>
          <td class="center">{n}</td>
          <td class="center">{c}</td>
          <td class="center"><span class="badge {cls}">{acc_str}</span></td>
        </tr>"""
        return f"""
<section>
  <h2>Rule-gate accuracy &mdash; deterministic, no Bedrock</h2>
  <table>
    <thead><tr>
      <th>Expected outcome</th>
      <th class="center">Samples</th>
      <th class="center">Correct</th>
      <th class="center">Accuracy</th>
    </tr></thead>
    <tbody>{rows_html}
    </tbody>
  </table>
</section>"""

    def _html_rg_detail(self) -> str:
        if not self.rule_gate:
            return ""
        rows_html = ""
        for r in self.rule_gate:
            row_cls = "row-ok" if r["correct"] else "row-err"
            result_badge = (
                '<span class="badge badge-green">correct</span>'
                if r["correct"]
                else '<span class="badge badge-red">wrong</span>'
            )
            passed_badge = (
                '<span class="badge badge-green">passed</span>'
                if r["rule_gate_passed"]
                else '<span class="badge badge-red">blocked</span>'
            )
            reason_html = (
                f'<code>{html_mod.escape(str(r["rule_gate_reason"]))}</code>'
                if r["rule_gate_reason"]
                else '<span class="badge badge-slate">—</span>'
            )
            msg = r["message"]
            display = html_mod.escape(msg[:120] + "…" if len(msg) > 120 else msg)
            rows_html += f"""
        <tr class="{row_cls}">
          <td class="msg-cell">{display}</td>
          <td>{self._outcome_badge(r['expected'])}</td>
          <td class="center">{passed_badge}</td>
          <td>{reason_html}</td>
          <td class="center">{result_badge}</td>
        </tr>"""
        return f"""
<section>
  <h2>Rule-gate sample detail &mdash; all {len(self.rule_gate)} inputs</h2>
  <table>
    <thead><tr>
      <th>Input message</th>
      <th>Expected outcome</th>
      <th class="center">Rule gate</th>
      <th>Reason</th>
      <th class="center">Result</th>
    </tr></thead>
    <tbody>{rows_html}
    </tbody>
  </table>
</section>"""

    def _html_full_section(self) -> str:
        if not self.full:
            return """
<section>
  <h2>Full bouncer accuracy &mdash; real Haiku (@pytest.mark.aws)</h2>
  <p class="no-data">No data &mdash; run with <code>-m aws</code> against a real Bedrock endpoint.</p>
</section>"""
        total = len(self.full)
        correct = sum(1 for r in self.full if r["correct"])
        fn = [r for r in self.full if r["expected"] == "escalate" and not r["escalated"] and r["allowed"]]
        fp = [r for r in self.full if r["expected"] == "pass" and r["escalated"]]
        rows_html = ""
        for outcome in sorted({r["expected"] for r in self.full}):
            rows = [r for r in self.full if r["expected"] == outcome]
            n = len(rows)
            c = sum(1 for r in rows if r["correct"])
            esc = sum(1 for r in rows if r["escalated"])
            acc_val = c / n * 100 if n else None
            acc_str = f"{acc_val:.1f}%" if acc_val is not None else "—"
            cls = "badge-green" if (acc_val or 0) >= 90 else "badge-amber" if (acc_val or 0) >= 70 else "badge-red"
            rows_html += f"""
        <tr>
          <td>{self._outcome_badge(outcome)}</td>
          <td class="center">{n}</td>
          <td class="center">{c}</td>
          <td class="center"><span class="badge {cls}">{acc_str}</span></td>
          <td class="center">{esc}</td>
        </tr>"""
        return f"""
<section>
  <h2>Full bouncer accuracy &mdash; real Haiku (@pytest.mark.aws)</h2>
  <div style="padding:1rem 1.25rem; display:flex; gap:1.5rem; font-size:0.85rem; border-bottom:1px solid #E5E2D8;">
    <span>Overall: <strong>{correct}/{total} ({correct/total*100:.1f}%)</strong></span>
    <span>False negatives: <strong style="color:{'#C76E3A' if fn else 'inherit'}">{len(fn)}</strong></span>
    <span>False positives: <strong style="color:{'#C76E3A' if fp else 'inherit'}">{len(fp)}</strong></span>
  </div>
  <table>
    <thead><tr>
      <th>Expected outcome</th>
      <th class="center">Samples</th>
      <th class="center">Correct</th>
      <th class="center">Accuracy</th>
      <th class="center">Escalated</th>
    </tr></thead>
    <tbody>{rows_html}
    </tbody>
  </table>
</section>"""

    def _html_full_detail(self) -> str:
        if not self.full:
            return ""
        rows_html = ""
        for r in self.full:
            is_wrong = not r["correct"]
            row_cls = "row-err" if is_wrong else "row-ok"
            result_badge = (
                '<span class="badge badge-red">wrong</span>'
                if is_wrong
                else '<span class="badge badge-green">correct</span>'
            )
            allowed_badge = (
                '<span class="badge badge-green">allowed</span>'
                if r["allowed"]
                else '<span class="badge badge-red">blocked</span>'
            )
            esc_badge = (
                '<span class="badge badge-amber">escalated</span>'
                if r["escalated"] else ""
            )
            reason_html = f'<code>{html_mod.escape(str(r["reason"]))}</code>' if r.get("reason") else "—"
            msg = r["message"]
            display = html_mod.escape(msg[:120] + "…" if len(msg) > 120 else msg)
            rows_html += f"""
        <tr class="{row_cls}">
          <td class="msg-cell">{display}</td>
          <td>{self._outcome_badge(r['expected'])}</td>
          <td class="center">{allowed_badge}</td>
          <td class="center">{esc_badge}</td>
          <td>{reason_html}</td>
          <td class="center">{result_badge}</td>
        </tr>"""
        return f"""
<section>
  <h2>Full bouncer sample detail &mdash; all {len(self.full)} inputs (@pytest.mark.aws)</h2>
  <table>
    <thead><tr>
      <th>Input message</th>
      <th>Expected outcome</th>
      <th class="center">Allowed</th>
      <th class="center">Escalated</th>
      <th>Reason</th>
      <th class="center">Result</th>
    </tr></thead>
    <tbody>{rows_html}
    </tbody>
  </table>
</section>"""


# ---------------------------------------------------------------------------
# Pytest integration
# ---------------------------------------------------------------------------


def pytest_configure(config: Any) -> None:
    config._bouncer_accuracy = _BouncerAccuracyStore()


@pytest.fixture(scope="session")
def bouncer_accuracy_store(pytestconfig: Any) -> _BouncerAccuracyStore:
    return pytestconfig._bouncer_accuracy  # type: ignore[attr-defined, no-any-return]


def pytest_terminal_summary(
    terminalreporter: Any,
    exitstatus: Any,
    config: Any,
) -> None:
    store: _BouncerAccuracyStore | None = getattr(config, "_bouncer_accuracy", None)
    if store and store.has_data():
        terminalreporter.write_sep("=", "BOUNCER ACCURACY REPORT")
        for line in store.render():
            terminalreporter.write_line(line)
        terminalreporter.write_sep("=", "")


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    store: _BouncerAccuracyStore | None = getattr(
        session.config, "_bouncer_accuracy", None
    )
    if not store or not store.has_data():
        return
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH.write_text(store.render_html(generated_at), encoding="utf-8")
    print(f"\n  HTML report -> {_REPORT_PATH.resolve()}")
