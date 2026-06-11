"""L0 — subagent_dispatch_runs 审计表 roundtrip + 注册守卫。"""

from __future__ import annotations

import contextlib


def test_table_registered_in_metadata() -> None:
    import app.models  # noqa: F401 — barrel 触发注册
    from app.core.database import Base

    assert "subagent_dispatch_runs" in set(Base.metadata.tables.keys())


def test_roundtrip(db_session) -> None:
    from app.models import SubagentDispatchRun

    row = SubagentDispatchRun(
        id="row-1",
        batch_id="batch-1",
        parent_request_id="r1",
        turn_id="t1",
        scenario_type="multi_compare",
        subtask_id="sub-0",
        goal_packet={"goal": "查茅台", "target": "600519.SH"},
        tool_scope=["get_stock_quote", "get_news"],
        result_summary="茅台 1700。",
        result_refs=[],
        status="ok",
        gap_note=None,
        tokens=1200,
        cost_cny=0.003,
        steps_used=2,
        duration_ms=850,
        tier="fast",
    )
    db_session.add(row)
    db_session.flush()

    fetched = db_session.query(SubagentDispatchRun).filter_by(id="row-1").one()
    assert fetched.status == "ok"
    assert fetched.goal_packet["target"] == "600519.SH"
    assert fetched.tool_scope == ["get_stock_quote", "get_news"]


def test_audit_repo_record_batch_writes_one_row_per_child(db_session) -> None:
    from app.chatloop.state import ChatLoopState
    from app.chatloop.subagent import SubagentResult, SubtaskRequest
    from app.models import SubagentDispatchRun
    from app.services.subagent_audit import SubagentAuditRepo

    repo = SubagentAuditRepo(session_factory=lambda: contextlib.nullcontext(db_session))
    parent = ChatLoopState(
        user_id="u1", session_id="s1", request_id="r1", messages=[{"role": "user", "content": "比"}]
    )
    subtasks = [
        SubtaskRequest(goal="查茅台", target="600519.SH"),
        SubtaskRequest(goal="查五粮液", target="000858.SZ"),
    ]
    results = [
        SubagentResult(
            subtask_id="sub-0",
            target="600519.SH",
            summary="a",
            evidence_refs=[],
            status="ok",
            gap_note=None,
            tokens_spent=100,
            cost_cny=0.001,
            steps_used=2,
            tier="fast",
        ),
        SubagentResult(
            subtask_id="sub-1",
            target="000858.SZ",
            summary="b",
            evidence_refs=[],
            status="partial",
            gap_note="超步",
            tokens_spent=200,
            cost_cny=0.002,
            steps_used=4,
            tier="fast",
        ),
    ]
    repo.record_batch(
        parent=parent, subtasks=subtasks, results=results, scenario_type="multi_compare"
    )
    db_session.flush()

    rows = db_session.query(SubagentDispatchRun).filter_by(parent_request_id="r1").all()
    assert len(rows) == 2
    assert {r.status for r in rows} == {"ok", "partial"}
    assert all(r.batch_id == rows[0].batch_id for r in rows)  # 同批共享 batch_id
