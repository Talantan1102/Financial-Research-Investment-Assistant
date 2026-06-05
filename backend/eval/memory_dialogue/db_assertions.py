"""数据库断言引擎 — 对话流评估的写管线层判分。确定性,零 LLM。

每种断言类型一个私有方法;run_check 收集红绿不抛异常,失败带可读 detail
(差分思想:红灯要能直接指出库里实际长什么样)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.memory.models import ChatMemoryEdge, ChatMemoryNode
from sqlalchemy import select
from sqlalchemy.orm import Session

from eval.memory_dialogue.script_schema import DbCheck


@dataclass(frozen=True)
class CheckResult:
    check_type: str
    passed: bool
    detail: str


class DbAssertionEngine:
    """绑定一个 user 的断言执行器。snapshot_counts 供"数量不得增加"类断言记基线。"""

    def __init__(self, session: Session, user_id: UUID) -> None:
        self._s = session
        self._user_id = user_id
        self._count_snapshots: dict[tuple[str, str | tuple[str, ...] | None], int] = {}

    # ---- 查询基元 ----------------------------------------------------------

    def _edges(
        self,
        rel_type: str | None = None,
        target_label: str | list[str] | None = None,
    ) -> list[ChatMemoryEdge]:
        # target_label 支持候选列表(2026-06-05 批量合写审稿发现):抽取器把
        # Stock 规整成 ts_code(宁德时代→300750.SZ)、Industry 偶发漂移(白酒/白酒II),
        # 脚本用人话写候选,匹配任一即视为同一实体。
        stmt = select(ChatMemoryEdge).where(ChatMemoryEdge.user_id == self._user_id)
        if rel_type:
            stmt = stmt.where(ChatMemoryEdge.rel_type == rel_type)
        if target_label:
            labels = [target_label] if isinstance(target_label, str) else list(target_label)
            stmt = stmt.join(
                ChatMemoryNode, ChatMemoryEdge.target_node_id == ChatMemoryNode.node_id
            ).where(ChatMemoryNode.entity_label.in_(labels))
        return list(self._s.execute(stmt).scalars())

    @staticmethod
    def _is_active(e: ChatMemoryEdge) -> bool:
        return e.valid_to is None and e.invalidated_at is None

    @staticmethod
    def _props_text(e: ChatMemoryEdge) -> str:
        return " ".join(str(v) for v in (e.properties or {}).values())

    # ---- 分发 --------------------------------------------------------------

    def run_check(self, check: DbCheck) -> CheckResult:
        handler = getattr(self, f"_check_{check.type}", None)
        if handler is None:
            return CheckResult(check.type, False, f"未知断言类型: {check.type}")
        result: CheckResult = handler(**check.params)
        return result

    # ---- 断言类型 ----------------------------------------------------------

    def _check_fact_active(
        self,
        rel_type: str,
        target_label: str,
        value_contains: list[str] | None = None,
    ) -> CheckResult:
        active = [e for e in self._edges(rel_type, target_label) if self._is_active(e)]
        if not active:
            return CheckResult(
                "fact_active", False, f"无 active 的 {rel_type}→{target_label} 边"
            )
        if value_contains:
            texts = [self._props_text(e) for e in active]
            missing = [v for v in value_contains if not any(v in t for t in texts)]
            if missing:
                return CheckResult(
                    "fact_active",
                    False,
                    f"active 边存在但缺关键值 {missing};实际 properties: {texts}",
                )
        return CheckResult("fact_active", True, f"{len(active)} 条 active")

    def _check_old_invalidated(
        self, rel_type: str, target_label: str, min_count: int = 1
    ) -> CheckResult:
        ended = [
            e
            for e in self._edges(rel_type, target_label)
            if e.valid_to is not None or e.invalidated_at is not None
        ]
        ok = len(ended) >= min_count
        return CheckResult(
            "old_invalidated", ok, f"已作废 {len(ended)} 条(要求 ≥{min_count})"
        )

    @staticmethod
    def _label_key(target_label: str | list[str] | None) -> str | tuple[str, ...] | None:
        return tuple(target_label) if isinstance(target_label, list) else target_label

    def snapshot_counts(
        self, rel_type: str, target_label: str | list[str] | None = None
    ) -> None:
        self._count_snapshots[(rel_type, self._label_key(target_label))] = len(
            self._edges(rel_type, target_label)
        )

    def _check_fact_count_no_increase(
        self, rel_type: str, target_label: str | list[str] | None = None
    ) -> CheckResult:
        key = (rel_type, self._label_key(target_label))
        if key not in self._count_snapshots:
            return CheckResult(
                "fact_count_no_increase", False, "未先 snapshot_counts,无基线"
            )
        before = self._count_snapshots[key]
        now = len(self._edges(rel_type, target_label))
        return CheckResult(
            "fact_count_no_increase", now <= before, f"基线 {before} 条 → 现在 {now} 条"
        )

    def _check_invalidated_chain_intact(
        self, rel_type: str, target_label: str, expected_versions: int
    ) -> CheckResult:
        all_edges = self._edges(rel_type, target_label)
        ok = len(all_edges) >= expected_versions
        return CheckResult(
            "invalidated_chain_intact",
            ok,
            f"链上共 {len(all_edges)} 个版本(要求 ≥{expected_versions};作废≠删除,历史必须可溯)",
        )

    def _check_valid_from_is_event_time(
        self,
        rel_type: str,
        target_label: str,
        expected_date: str,
        tolerance_days: int = 14,
    ) -> CheckResult:
        active = [e for e in self._edges(rel_type, target_label) if self._is_active(e)]
        if not active:
            return CheckResult("valid_from_is_event_time", False, "无 active 边可校验")
        expected = datetime.fromisoformat(expected_date)
        tol = timedelta(days=tolerance_days)
        for e in active:
            vf = e.valid_from.replace(tzinfo=None)
            if abs(vf - expected) <= tol:
                return CheckResult(
                    "valid_from_is_event_time",
                    True,
                    f"valid_from={vf.date()} ≈ {expected_date}",
                )
        actual = [e.valid_from.date().isoformat() for e in active]
        return CheckResult(
            "valid_from_is_event_time",
            False,
            f"valid_from 实为 {actual},期望 ≈{expected_date}(±{tolerance_days}天)——疑似打成录入时间",
        )

    def _check_no_fact_written(self, rel_type: str) -> CheckResult:
        edges = self._edges(rel_type)
        return CheckResult(
            "no_fact_written",
            not edges,
            f"{rel_type} 边 {len(edges)} 条(要求 0——该信息不归记忆管)",
        )
