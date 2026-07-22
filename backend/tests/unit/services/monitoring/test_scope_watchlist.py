from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.monitoring.scope import load_active_subjects


def test_scope_unions_and_deduplicates_position_and_enabled_watchlist() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.all.side_effect = [
        [SimpleNamespace(user_id="u1", ts_code="600000.SH", name="浦发")],
        [SimpleNamespace(user_id="u1", ts_code="600000.SH", name="浦发"), SimpleNamespace(user_id="u1", ts_code="000001.SZ", name="平安")],
    ]
    subjects = load_active_subjects(session)
    assert {(s.user_id, s.ts_code) for s in subjects} == {("u1", "600000.SH"), ("u1", "000001.SZ")}
    assert set(next(s for s in subjects if s.ts_code == "600000.SH").sources) == {"position", "watchlist"}
