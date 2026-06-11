"""SubagentAuditRepo — 把每个子循环写进 subagent_dispatch_runs(best-effort)。

默认用 sync SessionLocal(与 TraceService 同款,留痕非致命);测试注入
nullcontext(db_session)。id/batch_id 由调用方不传时用 request_id+index 拼,
避免依赖 Math.random/uuid(可测)。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy.orm import Session

from app.chatloop.subagent import READONLY_SUBAGENT_TOOLS
from app.models import SubagentDispatchRun


def _default_session_factory() -> AbstractContextManager[Session]:
    from app.core.database import SessionLocal

    return SessionLocal()


class SubagentAuditRepo:
    def __init__(
        self,
        session_factory: Callable[[], AbstractContextManager[Session]] | None = None,
    ) -> None:
        self._session_factory = session_factory or _default_session_factory

    def record_batch(
        self, *, parent: Any, subtasks: list[Any], results: list[Any],
        scenario_type: str | None = None,
    ) -> None:
        batch_id = f"{parent.request_id}::batch"
        with self._session_factory() as session:
            for i, (req, res) in enumerate(zip(subtasks, results, strict=False)):
                session.add(
                    SubagentDispatchRun(
                        id=f"{parent.request_id}::sub::{i}",
                        batch_id=batch_id,
                        parent_request_id=parent.request_id,
                        turn_id=parent.session_id,
                        scenario_type=scenario_type,
                        subtask_id=res.subtask_id,
                        goal_packet={"goal": req.goal, "target": req.target,
                                     "output_hint": req.output_hint, "boundary": req.boundary},
                        tool_scope=list(getattr(res, "tool_scope", []))
                        or list(READONLY_SUBAGENT_TOOLS),
                        result_summary=res.summary,
                        result_refs=list(res.evidence_refs),
                        status=res.status,
                        gap_note=res.gap_note,
                        tokens=res.tokens_spent,
                        cost_cny=res.cost_cny,
                        steps_used=res.steps_used,
                        duration_ms=0,
                        tier=res.tier,
                    )
                )
            session.commit()
