#!/usr/bin/env python3
"""Validate commit message contains layer marker for fix commits.

Per spec §13 rule 3 (WORKING_AGREEMENT.md):
- Commits starting with `fix` (or `fix(scope):`) MUST contain a line
  `原因 layer: <impl|plan|spec>`.
- Other commit types (feat, chore, docs, test, refactor, etc.) are exempt.

Usage (pre-commit commit-msg hook):
    check_commit_msg.py <path-to-commit-msg-file>

Exit codes:
    0 — valid
    1 — invalid (prints reason to stderr)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

VALID_LAYERS = ("impl", "plan", "spec")
LAYER_PATTERN = re.compile(r"^原因 layer:\s*(\w+)\s*$", re.MULTILINE)
FIX_PATTERN = re.compile(r"^fix(\(.+?\))?:", re.MULTILINE)


def validate(commit_msg: str) -> tuple[bool, str]:
    """Returns (is_valid, error_message)."""
    if not FIX_PATTERN.search(commit_msg):
        return True, ""  # not a fix commit, no marker required

    match = LAYER_PATTERN.search(commit_msg)
    if not match:
        return False, (
            "fix commits must include a layer marker line:\n"
            "    原因 layer: impl    (implementation bug)\n"
            "    原因 layer: plan    (plan missed something, change plan first)\n"
            "    原因 layer: spec    (spec design wrong, run full spec revision)\n"
            "See WORKING_AGREEMENT.md rule 3."
        )

    layer = match.group(1)
    if layer not in VALID_LAYERS:
        return False, (
            f"invalid 原因 layer '{layer}'. Must be one of: {', '.join(VALID_LAYERS)}.\n"
            "See WORKING_AGREEMENT.md rule 3."
        )

    return True, ""


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <commit-msg-file>", file=sys.stderr)
        return 2

    commit_msg = Path(sys.argv[1]).read_text(encoding="utf-8")
    is_valid, error = validate(commit_msg)
    if not is_valid:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
