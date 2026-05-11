#!/usr/bin/env python3
"""CI check: forbid direct vendor SDK imports.

Per docs/adr/0001-bedrock-only.md and CLAUDE.md §3 non-negotiable #1, all
LLM calls go through Bedrock. Direct imports of the Anthropic, OpenAI, or
Google generative-ai SDKs are not permitted in production code.

This check fails the build if any of these imports appear outside `tests/`.

Why a regex-grep style check rather than AST: it's robust against the
sneaky variants (importlib, __import__, conditional imports) which all
still leave a textual trace, and it's fast enough to run on every PR.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Patterns that indicate a forbidden vendor SDK is being pulled in.
FORBIDDEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic SDK", re.compile(r"^\s*(?:from|import)\s+anthropic\b", re.MULTILINE)),
    ("openai SDK", re.compile(r"^\s*(?:from|import)\s+openai\b", re.MULTILINE)),
    (
        "google.generativeai SDK",
        re.compile(r"^\s*(?:from|import)\s+google\.generativeai\b", re.MULTILINE),
    ),
    # Sneaky paths
    ("anthropic via importlib", re.compile(r"""importlib\.import_module\(\s*["']anthropic""")),
    ("openai via importlib", re.compile(r"""importlib\.import_module\(\s*["']openai""")),
    ("anthropic via __import__", re.compile(r"""__import__\(\s*["']anthropic""")),
    ("openai via __import__", re.compile(r"""__import__\(\s*["']openai""")),
]

# Directories to skip
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "tests",
    "docs",
    "infra",
}


def check_file(path: Path) -> list[tuple[str, int, str]]:
    """Return a list of (pattern_name, line_number, line_text) violations."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    violations: list[tuple[str, int, str]] = []
    for name, pattern in FORBIDDEN_PATTERNS:
        for match in pattern.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            line = text.splitlines()[line_no - 1] if line_no <= len(text.splitlines()) else ""
            violations.append((name, line_no, line.strip()))
    return violations


def iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        # Also skip this script itself
        if path.name == "check_forbidden_imports.py":
            continue
        yield path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    all_violations: list[tuple[Path, str, int, str]] = []

    for py_file in iter_python_files(root):
        for name, line_no, line in check_file(py_file):
            all_violations.append((py_file.relative_to(root), name, line_no, line))

    if all_violations:
        print("❌ Forbidden vendor SDK imports detected:")
        print()
        for path, name, line_no, line in all_violations:
            print(f"  {path}:{line_no}  — {name}")
            print(f"    {line}")
            print()
        print("Per docs/adr/0001-bedrock-only.md, all LLM calls go through Bedrock.")
        print("Use LiteLLM (configured against Bedrock) or boto3 bedrock-runtime directly.")
        return 1

    print("✓ No forbidden vendor SDK imports found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
