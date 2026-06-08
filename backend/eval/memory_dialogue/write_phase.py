"""写阶段执行器 — 把脚本 session 流灌进库、触发抽取、逐 session 跑断言。

时间可控的关键:episode 用裸 INSERT 显式给 created_at=脚本 session 日期,
绕过 server default(沿用 bi_temporal_differential 测试的模式)。
抽取器依赖注入:live_deps 接真实批量抽取,测试给假实现。
"""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from eval.memory_dialogue.db_assertions import CheckResult, DbAssertionEngine
from eval.memory_dialogue.script_schema import Script, ScriptSession


class ExtractSessionFn(Protocol):
    def __call__(
        self, user_id: UUID, chat_session_id: UUID, ss: ScriptSession
    ) -> Awaitable[None]: ...


@dataclass(frozen=True)
class SessionCheckResult:
    after_session: int
    check_type: str
    passed: bool
    detail: str


@dataclass
class WritePhaseReport:
    results: list[SessionCheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)


class WritePhaseRunner:
    def __init__(
        self,
        session: Session,
        user_id: UUID,
        chat_session_id: UUID,
        extract_session: ExtractSessionFn,
    ) -> None:
        self._s = session
        self._user_id = user_id
        self._chat_session_id = chat_session_id
        self._extract = extract_session
        self._engine = DbAssertionEngine(session=session, user_id=user_id)

    def _insert_episodes(self, ss: ScriptSession) -> None:
        """把一个 session 的轮次按 (用户消息, 助手回复) 对写成 episode,created_at=脚本日期。"""
        created = datetime.combine(ss.date, datetime.min.time(), tzinfo=UTC)
        pairs: list[tuple[str, str]] = []
        pending_user: str | None = None
        for t in ss.turns:
            if t.role == "u":
                if pending_user is not None:
                    pairs.append((pending_user, ""))
                pending_user = t.text
            else:
                pairs.append((pending_user or "", t.text))
                pending_user = None
        if pending_user is not None:
            pairs.append((pending_user, ""))
        for idx, (u_msg, a_msg) in enumerate(pairs):
            self._s.execute(
                text(
                    "INSERT INTO chat_memory_episodes "
                    "(episode_id, user_id, session_id, episode_index, "
                    " user_message_text, agent_response_text, source_kind, created_at) "
                    "VALUES (:eid, :uid, :sid, :idx, :u, :a, 'chat_turn', :created)"
                ),
                {
                    "eid": str(uuid4()),
                    "uid": str(self._user_id),
                    "sid": str(self._chat_session_id),
                    "idx": ss.n * 1000 + idx,  # session 内有序且全局不撞
                    "u": u_msg,
                    "a": a_msg,
                    "created": created,
                },
            )
        self._s.commit()

    async def run(self, script: Script) -> WritePhaseReport:
        report = WritePhaseReport()
        groups_by_after = {g.after_session: g for g in script.db_assertions}
        for ss in script.sessions:
            group = groups_by_after.get(ss.n)
            # "数量不得增加"类断言需要基线:在该 session 喂入之前快照
            if group:
                for c in group.checks:
                    if c.type == "fact_count_no_increase":
                        # target_label 可能是候选列表(实体规整对策)。直接传原值,
                        # 由 snapshot_counts 内部 _label_key 统一规范化 key——
                        # 此前用 str(list) 强转,与 run_check 的 tuple key 永不相等,
                        # 误报"无基线"(2026-06-08 四族冒烟发现的 harness bug)。
                        tl = c.params.get("target_label")
                        self._engine.snapshot_counts(
                            rel_type=str(c.params["rel_type"]),
                            target_label=tl,  # type: ignore[arg-type]
                        )
            self._insert_episodes(ss)
            await self._extract(self._user_id, self._chat_session_id, ss)
            if group:
                for c in group.checks:
                    r: CheckResult = self._engine.run_check(c)
                    report.results.append(
                        SessionCheckResult(
                            after_session=ss.n,
                            check_type=r.check_type,
                            passed=r.passed,
                            detail=r.detail,
                        )
                    )
        return report
