"""L0: persona populator — spec § 5 末尾 + § 7."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.memory.persona_populator import (
    PERSONA_BLOCK_NAME,
    PERSONA_MAX_TOKENS,
    _truncate_to_token_budget,
    format_persona_markdown,
    populate_persona_on_session_start,
)


class TestFormatPersonaMarkdown:
    def test_4_categories_in_output(self) -> None:
        holdings = [
            {
                "ts_code": "600519.SH",
                "qty": 500,
                "since": "2024-08",
                "thesis": "cash flow 稳",
            }
        ]
        prefs = [{"label": "DCF", "priority": 0.9}, {"label": "价值投资", "priority": 0.8}]
        avoids = [{"label": "新能源 sector", "reason": "政策不确定 + 估值贵"}]
        watches = [{"ts_code": "000858.SZ"}, {"label": "AI 大模型 concept"}]
        md = format_persona_markdown(holdings, prefs, avoids, watches)
        assert "## 用户画像" in md
        assert "### 当前持仓" in md
        assert "600519.SH" in md
        assert "DCF" in md
        assert "新能源" in md
        assert "000858.SZ" in md or "AI" in md

    def test_empty_graph_returns_placeholder(self) -> None:
        md = format_persona_markdown([], [], [], [])
        assert "用户画像" in md
        # 空 graph 应有"暂无"提示或长度短
        assert "暂无" in md or len(md) < 300

    def test_holdings_with_qty_only(self) -> None:
        holdings = [{"ts_code": "600519.SH", "qty": 500}]
        md = format_persona_markdown(holdings, [], [], [])
        assert "600519.SH" in md
        assert "500" in md


class TestTruncateToTokenBudget:
    def test_under_budget_unchanged(self) -> None:
        s = "短 markdown"
        out = _truncate_to_token_budget(s, max_tokens=500)
        assert out == s

    def test_over_budget_truncated_with_marker(self) -> None:
        # 中文 1.4 tokens/char, 500 tokens ≈ 357 chars
        s = "茅 " * 1000  # 远超 500 tokens
        out = _truncate_to_token_budget(s, max_tokens=500)
        assert "[truncated]" in out or "..." in out
        assert len(out) < len(s)


class TestConstants:
    def test_persona_block_name(self) -> None:
        assert PERSONA_BLOCK_NAME == "persona"

    def test_persona_max_tokens(self) -> None:
        assert PERSONA_MAX_TOKENS == 500


class TestPopulatePersonaOnSessionStart:
    def _make_cold_start_session(self) -> MagicMock:
        """Build a mock session with item_count=0 (cold-start user, no items)."""
        sess = MagicMock()
        # Guard check: session.query(...).filter_by(...).count() → 0 (no items)
        sess.query.return_value.filter_by.return_value.count.return_value = 0
        # 4 graph edge queries return empty; 1 upsert
        empty_result = MagicMock()
        empty_result.fetchall = MagicMock(return_value=[])
        sess.execute = MagicMock(return_value=empty_result)
        return sess

    def test_writes_markdown_to_working_block(self) -> None:
        """mock session (cold-start, item_count=0): assert 4 query + 1 UPSERT working_blocks.

        C1 guard: factory called twice — once for item_count check (returns 0),
        once for the main graph-edge queries + UPSERT.
        """
        sess = self._make_cold_start_session()
        factory = MagicMock(return_value=sess)
        populate_persona_on_session_start(factory, user_id=uuid4())

        # factory called twice: once for guard count, once for main queries
        assert factory.call_count == 2
        # 4 fetch + 1 upsert = 5 execute calls on the second session
        assert sess.execute.call_count >= 5
        # last call should be UPSERT working_blocks
        last_sql = str(sess.execute.call_args_list[-1].args[0])
        assert "chat_memory_working_blocks" in last_sql
        assert "INSERT" in last_sql.upper()
        sess.commit.assert_called_once()
        # close called twice: once for guard session, once for main session
        assert sess.close.call_count == 2

    def test_rollback_on_exception(self) -> None:
        """C1 guard session opens and closes cleanly; main session rolls back on error."""
        import contextlib

        # First session: guard check (item_count=0, closes ok)
        guard_sess = MagicMock()
        guard_sess.query.return_value.filter_by.return_value.count.return_value = 0

        # Second session: raises on execute
        main_sess = MagicMock()
        main_sess.execute = MagicMock(side_effect=RuntimeError("PG down"))

        factory = MagicMock(side_effect=[guard_sess, main_sess])
        with contextlib.suppress(RuntimeError):
            populate_persona_on_session_start(factory, user_id=uuid4())

        guard_sess.close.assert_called_once()
        main_sess.rollback.assert_called_once()
        main_sess.close.assert_called_once()

    def test_skips_when_items_present(self) -> None:
        """C1 guard: populator returns early when item_count > 0 (items table is SoT)."""
        sess = MagicMock()
        # item_count = 3 → should skip
        sess.query.return_value.filter_by.return_value.count.return_value = 3
        factory = MagicMock(return_value=sess)

        populate_persona_on_session_start(factory, user_id=uuid4())

        # Only the guard session was opened (and closed); no execute calls
        factory.assert_called_once()
        sess.close.assert_called_once()
        sess.execute.assert_not_called()
