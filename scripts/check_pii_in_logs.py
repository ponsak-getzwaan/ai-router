#!/usr/bin/env python3
"""CI check: forbid PII-shaped log calls.

Per CLAUDE.md §5 and §3 non-negotiable #6, application code uses `safe_log`
exclusively, and never f-strings or %-formatting that interpolate variables
named like message bodies.

This check uses Python's AST to find:

  1. Calls to logging.* / logger.* / print() with f-string or %-formatted
     arguments that interpolate names matching our PII allowlist.
  2. Direct calls to logger.exception(e) which echoes the exception message.

False positives can be suppressed with `# noqa: pii-log` on the line.

Run:  python scripts/check_pii_in_logs.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Variable names that strongly suggest user-supplied content.
# If a log call interpolates one of these, it's almost certainly a leak.
PII_NAMES: frozenset[str] = frozenset(
    {
        "message",
        "msg",
        "body",
        "content",
        "prompt",
        "text",
        "email",
        "phone",
        "name",
        "address",
        "response",
        "output",
        "input",
        "query",
        "question",
        "answer",
        "error_message",
        "error_msg",
        "exc_message",
        "exc_msg",
        "raw",
        "raw_message",
        "raw_input",
        "raw_text",
        "user_input",
        "user_message",
        "user_text",
    }
)

# Logger-like callable names. Includes plain `print` because it's a frequent
# debugging escape hatch.
LOGGING_NAMES: frozenset[str] = frozenset(
    {
        "log",
        "logger",
        "logging",
        "logs",
        "_log",
        "_logger",
        "print",
    }
)

LOGGING_METHODS: frozenset[str] = frozenset(
    {
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "critical",
        "exception",
        "log",
    }
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "docs",
    "infra",
    "tests",
}


def is_logging_call(node: ast.Call) -> bool:
    """Heuristic: is this a logging-style call?

    Matches:
      - print(...)
      - logger.info(...) / log.warning(...) / logging.error(...)
      - safe_log.info(...) — but we WANT safe_log; we filter that out below
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in LOGGING_NAMES
    if isinstance(func, ast.Attribute):
        if func.attr not in LOGGING_METHODS:
            return False
        if isinstance(func.value, ast.Name):
            # safe_log is the sanctioned escape hatch — don't flag it.
            if func.value.id == "safe_log":
                return False
            return func.value.id in LOGGING_NAMES
    return False


def is_safe_log_call(node: ast.Call) -> bool:
    """Calls on safe_log are allowed; the allowlist filter is in shared/logging.py."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id == "safe_log"
    return False


def fstring_uses_pii_name(node: ast.JoinedStr) -> list[str]:
    """Return the list of PII-shaped names interpolated in this f-string."""
    leaks: list[str] = []
    for part in node.values:
        if isinstance(part, ast.FormattedValue):
            if isinstance(part.value, ast.Name) and part.value.id in PII_NAMES:
                leaks.append(part.value.id)
            elif isinstance(part.value, ast.Attribute) and part.value.attr in PII_NAMES:
                leaks.append(part.value.attr)
    return leaks


def percent_uses_pii_name(node: ast.BinOp) -> list[str]:
    """Return PII-shaped names used on the RHS of a `% (...)` formatter."""
    if not isinstance(node.op, ast.Mod):
        return []
    leaks: list[str] = []
    rhs = node.right
    candidates: list[ast.AST] = []
    if isinstance(rhs, ast.Tuple):
        candidates.extend(rhs.elts)
    elif isinstance(rhs, ast.Dict):
        candidates.extend([v for v in rhs.values if v is not None])
    else:
        candidates.append(rhs)
    for c in candidates:
        if isinstance(c, ast.Name) and c.id in PII_NAMES:
            leaks.append(c.id)
        elif isinstance(c, ast.Attribute) and c.attr in PII_NAMES:
            leaks.append(c.attr)
    return leaks


def is_logger_exception_passing_exc(node: ast.Call) -> bool:
    """Match `logger.exception(e)` / `logger.error(e)` — these stringify the exception."""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in {"exception", "error"}:
        return False
    if not node.args:
        return False
    arg = node.args[0]
    # Exception is conventionally bound to `e`, `err`, `ex`, `exc`
    if isinstance(arg, ast.Name) and arg.id in {"e", "err", "ex", "exc", "exception"}:
        return True
    return False


# Suppress check
NOQA_RE = re.compile(r"#\s*noqa:\s*pii-log\b")


def line_is_suppressed(source_lines: list[str], lineno: int) -> bool:
    if 1 <= lineno <= len(source_lines):
        return bool(NOQA_RE.search(source_lines[lineno - 1]))
    return False


def _scan_logging_args(node: ast.Call) -> list[tuple[str, str]]:
    """Scan a logging-style call's args/kwargs for PII-shaped formatters.

    Returns a list of (kind, detail) tuples, one per violation.
    """
    found: list[tuple[str, str]] = []
    for arg in list(node.args) + [kw.value for kw in node.keywords]:
        if isinstance(arg, ast.JoinedStr):
            leaks = fstring_uses_pii_name(arg)
            if leaks:
                found.append(
                    (
                        "fstring-pii-name",
                        f"f-string interpolates suspicious name(s): {sorted(set(leaks))}",
                    )
                )
        elif isinstance(arg, ast.BinOp):
            leaks = percent_uses_pii_name(arg)
            if leaks:
                found.append(
                    (
                        "percent-pii-name",
                        f"%-format uses suspicious name(s): {sorted(set(leaks))}",
                    )
                )
    return found


def check_file(path: Path) -> list[tuple[int, str, str]]:
    """Return [(lineno, kind, detail), ...]"""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    source_lines = source.splitlines()

    violations: list[tuple[int, str, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if line_is_suppressed(source_lines, getattr(node, "lineno", 0)):
            continue
        if is_safe_log_call(node):
            continue

        # logger.exception(e) / logger.error(e)
        if is_logger_exception_passing_exc(node):
            violations.append(
                (
                    node.lineno,
                    "logger-passes-exception",
                    "logger.exception(e) stringifies the exception — "
                    "use safe_log.warning(..., error_type=type(e).__name__) instead",
                )
            )
            continue

        # Logging-shaped calls: scan argument list for PII-shaped interpolations
        if is_logging_call(node):
            for kind, detail in _scan_logging_args(node):
                violations.append((node.lineno, kind, detail))

    return violations


def iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in {"check_pii_in_logs.py", "check_forbidden_imports.py"}:
            continue
        yield path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    all_violations: list[tuple[Path, int, str, str]] = []

    for py_file in iter_python_files(root):
        for lineno, kind, detail in check_file(py_file):
            all_violations.append((py_file.relative_to(root), lineno, kind, detail))

    if all_violations:
        print("❌ Potential PII-in-logs violations detected:")
        print()
        for path, lineno, kind, detail in all_violations:
            print(f"  {path}:{lineno}  [{kind}]")
            print(f"    {detail}")
            print()
        print("Use safe_log from shared.logging — it filters fields against an allowlist.")
        print("If a flagged line is genuinely safe, suppress it with `# noqa: pii-log`.")
        return 1

    print("✓ No PII-shaped logging calls found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
