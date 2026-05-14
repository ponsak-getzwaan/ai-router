#!/usr/bin/env python3
"""Per-module coverage gate: redactor/ must be 100%.

The global 85% gate is enforced by [tool.coverage.report] fail_under = 85 in
pyproject.toml — pytest-cov exits non-zero if that threshold is unmet. This
script adds the stricter per-module gate on top of that.

Usage (after pytest --cov has written .coverage):
    uv run python scripts/check_coverage.py
"""
from __future__ import annotations

import subprocess
import sys

# (pattern, required_pct) — add rows here for additional strict gates
GATES: list[tuple[str, int]] = [
    ("redactor/*", 100),
]


def main() -> None:
    failed = False
    for pattern, threshold in GATES:
        result = subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "coverage",
                "report",
                f"--include={pattern}",
                f"--fail-under={threshold}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(f"FAIL: {pattern!r} is below {threshold}%", file=sys.stderr)
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            failed = True
        else:
            print(f"OK:   {pattern!r} >= {threshold}%")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
