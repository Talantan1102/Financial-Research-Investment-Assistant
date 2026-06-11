"""L0 — dispatch_subagents 子 agent 派发原语(契约/factory/tool/护栏)。"""

from __future__ import annotations

import pytest

from app.chatloop.subagent import SubagentResult, SubtaskRequest


def test_subtask_request_minimal() -> None:
    # LLM 只需填 goal;target/output_hint/boundary 可选
    req = SubtaskRequest(goal="查贵州茅台现价与近一年营收增速")
    assert req.goal == "查贵州茅台现价与近一年营收增速"
    assert req.target is None
    assert req.output_hint == ""
    assert req.boundary is None


def test_subtask_request_full() -> None:
    req = SubtaskRequest(
        goal="查五粮液财报要点",
        target="000858.SZ",
        output_hint="现价+营收增速+一句话风险",
        boundary="只看近一年",
    )
    assert req.target == "000858.SZ"
    assert req.boundary == "只看近一年"


def test_subagent_result_fields() -> None:
    r = SubagentResult(
        subtask_id="sub-0",
        target="600519.SH",
        summary="茅台现价 1700,营收增速 18%。",
        evidence_refs=["u1::cache:abc"],
        status="ok",
        gap_note=None,
        tokens_spent=1200,
        cost_cny=0.003,
        steps_used=2,
        tier="fast",
    )
    assert r.status == "ok"
    assert r.summary.startswith("茅台")
    assert r.tokens_spent == 1200


def test_subagent_result_status_literal() -> None:
    # 非法 status 被 Pydantic 拒
    with pytest.raises(ValueError):
        SubagentResult(
            subtask_id="x", target=None, summary="", evidence_refs=[],
            status="bogus", gap_note=None, tokens_spent=0, cost_cny=0.0,
            steps_used=0, tier="fast",
        )
