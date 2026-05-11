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
    def test_writes_markdown_to_working_block(self) -> None:
        """mock session: assert 4 query 调用 + 1 UPSERT working_blocks."""
        sess = MagicMock()
        # 4 queries return empty; 1 upsert
        empty_result = MagicMock()
        empty_result.fetchall = MagicMock(return_value=[])
        sess.execute = MagicMock(return_value=empty_result)

        factory = MagicMock(return_value=sess)
        populate_persona_on_session_start(factory, user_id=uuid4())

        # 4 fetch + 1 upsert = 5 execute calls
        assert sess.execute.call_count >= 5
        # last call should be UPSERT working_blocks
        last_sql = str(sess.execute.call_args_list[-1].args[0])
        assert "chat_memory_working_blocks" in last_sql
        assert "INSERT" in last_sql.upper()
        sess.commit.assert_called_once()
        sess.close.assert_called_once()

    def test_rollback_on_exception(self) -> None:
        import contextlib

        sess = MagicMock()
        sess.execute = MagicMock(side_effect=RuntimeError("PG down"))

        factory = MagicMock(return_value=sess)
        with contextlib.suppress(RuntimeError):
            populate_persona_on_session_start(factory, user_id=uuid4())
        sess.rollback.assert_called_once()
        sess.close.assert_called_once()
