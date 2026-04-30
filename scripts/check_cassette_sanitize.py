#!/usr/bin/env python3
"""Scan cassette YAML files for leaked credentials before commit.

Only files under ``backend/tests/fixtures/cassettes/`` are scanned;
all other paths are silently skipped so pre-commit can pass any YAML
file without false positives.

Usage (pre-commit passes filenames positionally):
    check_cassette_sanitize.py <file1> [<file2> ...]

Exit codes:
    0 — no leaks found (or no cassette files passed)
    1 — at least one leak pattern detected

Manual verification examples
------------------------------
Positive case (should exit 1)::

    mkdir -p backend/tests/fixtures/cassettes/_test_dummy
    echo "Authorization: Bearer sk-test123" > backend/tests/fixtures/cassettes/_test_dummy/leak.yaml
    uv run python scripts/check_cassette_sanitize.py backend/tests/fixtures/cassettes/_test_dummy/leak.yaml
    echo "exit=$?"
    rm -rf backend/tests/fixtures/cassettes/_test_dummy

Negative case (should exit 0)::

    mkdir -p backend/tests/fixtures/cassettes/_test_dummy
    echo "Authorization: <REDACTED>" > backend/tests/fixtures/cassettes/_test_dummy/clean.yaml
    uv run python scripts/check_cassette_sanitize.py backend/tests/fixtures/cassettes/_test_dummy/clean.yaml
    echo "exit=$?"
    rm -rf backend/tests/fixtures/cassettes/_test_dummy
"""

from __future__ import annotations

import sys
from pathlib import Path

CASSETTE_DIR = Path("backend/tests/fixtures/cassettes")

# Case-insensitive substrings that indicate a live credential in a cassette.
LEAK_PATTERNS: tuple[str, ...] = (
    "dashscope-",
    "sk-",
    "bearer ",
    "x-api-key:",
)


def _is_cassette_path(path: Path) -> bool:
    """Return True if *path* is (or lives under) the cassette fixture directory."""
    try:
        path.resolve().relative_to(CASSETTE_DIR.resolve())
        return True
    except ValueError:
        pass
    # Also accept relative paths whose string form starts with the cassette dir.
    try:
        path.relative_to(CASSETTE_DIR)
        return True
    except ValueError:
        return False


def scan(path: Path) -> list[str]:
    """Scan *path* for leak patterns.

    Returns a list of formatted hit strings ``"<path>:<lineno>: leaked credential
    pattern: <pattern>"`` — one entry per matching line.  Returns an empty list
    if the file is clean or is not under the cassette directory.
    """
    if not _is_cassette_path(path):
        return []

    hits: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        print(f"{path}: error reading file: {exc}", file=sys.stderr)
        return []

    for lineno, line in enumerate(lines, start=1):
        lower = line.lower()
        for pattern in LEAK_PATTERNS:
            if pattern in lower:
                hits.append(f"{path}:{lineno}: leaked credential pattern: {pattern!r}")
                break  # one report per line is enough

    return hits


def main() -> int:
    if len(sys.argv) < 2:
        # No files passed — nothing to check.
        return 0

    found_any = False
    for arg in sys.argv[1:]:
        path = Path(arg)
        hits = scan(path)
        for hit in hits:
            print(hit, file=sys.stderr)
        if hits:
            found_any = True

    return 1 if found_any else 0


if __name__ == "__main__":
    sys.exit(main())
