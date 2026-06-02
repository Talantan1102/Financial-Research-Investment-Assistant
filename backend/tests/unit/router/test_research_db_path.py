"""C40 regression: _RESEARCH_DB_PATH is __file__-relative, not CWD-relative.

The old code used Path('backend/data/research.sqlite'), which resolves
relative to the process CWD. When uvicorn is started from a directory other
than the repo root (or from inside backend/) the path silently fails to exist
and list_research_runs falls back to hardcoded mock data.

Fix: _RESEARCH_DB_PATH is computed at module-import time from __file__.resolve()
so it is always absolute and CWD-independent.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch


def _get_research_module() -> Any:
    """Return the already-imported app.router.research module."""
    import app.router.research as mod

    return mod


# ---------------------------------------------------------------------------
# C40 — path is absolute and CWD-independent
# ---------------------------------------------------------------------------


def test_research_db_path_is_absolute() -> None:
    """_RESEARCH_DB_PATH must be an absolute Path regardless of CWD."""
    mod = _get_research_module()
    assert mod._RESEARCH_DB_PATH.is_absolute(), (
        f"_RESEARCH_DB_PATH should be absolute, got {mod._RESEARCH_DB_PATH!r}"
    )


def test_research_db_path_ends_with_expected_suffix() -> None:
    """_RESEARCH_DB_PATH should resolve to backend/data/research.sqlite."""
    mod = _get_research_module()
    p = mod._RESEARCH_DB_PATH
    # The last two parts must be data/research.sqlite
    assert p.parts[-1] == "research.sqlite"
    assert p.parts[-2] == "data"
    # The directory two levels up from the router file is backend/
    router_file = Path(mod.__file__).resolve()
    expected_backend_dir = router_file.parents[2]
    assert p == expected_backend_dir / "data" / "research.sqlite", (
        f"Expected {expected_backend_dir / 'data' / 'research.sqlite'}, got {p}"
    )


def test_research_db_path_stable_under_different_cwd(tmp_path: Path) -> None:
    """_RESEARCH_DB_PATH value is unchanged after os.chdir to an unrelated directory.

    C40: the old Path('backend/data/research.sqlite') would resolve differently
    depending on the working directory at call time.  The new constant is
    evaluated once at import time from __file__, so changing cwd afterwards
    has no effect.
    """
    mod = _get_research_module()
    original_path = mod._RESEARCH_DB_PATH

    original_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        # After chdir the constant must still equal the original absolute path
        assert original_path == mod._RESEARCH_DB_PATH
        assert mod._RESEARCH_DB_PATH.is_absolute()
    finally:
        os.chdir(original_cwd)


# ---------------------------------------------------------------------------
# C40 — list_research_runs surfaces real runs (not mock) when the reader finds them
# ---------------------------------------------------------------------------


def test_list_research_runs_reads_real_db_when_present() -> None:
    """When the reader returns real runs, list_research_runs surfaces them — NOT the
    _MOCK_RUNS fallback.

    The absolute __file__-relative path itself is covered by the path tests above.
    Here we pin the list_research_runs branch that uses the reader's result. We patch
    _read_research_runs_from_sqlite rather than hand-build a langgraph SqliteSaver
    checkpoint blob (whose on-disk serde is an internal, brittle detail).
    """
    mod = _get_research_module()
    sentinel = mod.ResearchRunSummary(
        id="real-run-c40",
        target_name="C40TestStock",
        target_ts_code="000001.SZ",
        generated_at="2026-01-01T00:00:00",
        tldr="C40 regression: real run read from the DB",
        recommendation="recommend_hold",
    )

    with patch.object(mod, "_read_research_runs_from_sqlite", return_value=[sentinel]):
        result = asyncio.run(mod.list_research_runs(limit=10))

    real_ids = {r.id for r in result}
    mock_ids = {r.id for r in mod._MOCK_RUNS}
    assert "real-run-c40" in real_ids, "list_research_runs must surface the real run"
    assert real_ids.isdisjoint(mock_ids), "must not fall back to mock when real runs exist"


def test_list_research_runs_falls_back_to_mock_when_db_absent(tmp_path: Path) -> None:
    """When _RESEARCH_DB_PATH does not exist, mock data is returned (sentinel behaviour).

    This is the documented fallback for dev/demo environments with no prior runs.
    """
    mod = _get_research_module()
    absent_path = tmp_path / "nonexistent.sqlite"

    with patch.object(mod, "_RESEARCH_DB_PATH", absent_path):
        result = asyncio.run(mod.list_research_runs(limit=10))

    mock_ids = {r.id for r in mod._MOCK_RUNS}
    result_ids = {r.id for r in result}
    assert result_ids == mock_ids, (
        f"Expected mock fallback when DB is absent, got {result_ids!r} vs mock {mock_ids!r}"
    )
