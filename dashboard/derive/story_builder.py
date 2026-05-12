"""V4 故事时间线 — 三段式卡片数据构造。spec § 5.4。"""

from __future__ import annotations

from dataclasses import dataclass

from dashboard.derive.deep_card_types import DeepCard
from dashboard.derive.types import Capability


@dataclass(frozen=True)
class StoryCard:
    cap_id: str
    name_cn: str
    dimension: str
    sort_time: str | None  # ISO timestamp,None 表示无时间归属
    in_no_time_group: bool
    problem: str  # from why
    decision: str  # from tradeoff
    outcome: str  # from lessons_learned (可能为空)
    linked_specs: list[str]
    linked_decisions: list[str]


def build_story_cards(
    capabilities: list[Capability],
    deep_cards: list[DeepCard],
    *,
    commit_times: dict[str, str],
    filter_dimensions: set[str] | None = None,
    time_after: str | None = None,
    time_before: str | None = None,
    order: str = "asc",
) -> list[StoryCard]:
    """从 cap + deep_card + commit_times 构造按时间排序的三段式卡片。

    时间归属顺序(spec § 5.4):
    1. commit_times[cap_id](git log 首个 commit)
    2. DeepCard.prefill_at(LLM prefill 时间)
    3. None → in_no_time_group=True,排在末尾
    """
    cards_by_id = {c.cap_id: c for c in deep_cards}

    out: list[StoryCard] = []
    for cap in capabilities:
        if filter_dimensions and cap.dimension not in filter_dimensions:
            continue
        dc = cards_by_id.get(cap.id)
        if dc is None or (dc.why is None and dc.tradeoff is None):
            continue  # 没内容的不渲染

        # 时间归属
        sort_time: str | None = commit_times.get(cap.id)
        in_no_time = False
        if sort_time is None and dc.prefill_at:
            sort_time = dc.prefill_at.isoformat()
        if sort_time is None:
            in_no_time = True

        # 时间窗筛选(仅对有时间的)
        if sort_time is not None:
            if time_after and sort_time < time_after:
                continue
            if time_before and sort_time > time_before:
                continue

        out.append(
            StoryCard(
                cap_id=cap.id,
                name_cn=cap.name_cn,
                dimension=cap.dimension,
                sort_time=sort_time,
                in_no_time_group=in_no_time,
                problem=dc.why or "",
                decision=dc.tradeoff or "",
                outcome=dc.lessons_learned or "",
                linked_specs=list(dc.linked_specs),
                linked_decisions=list(dc.linked_decisions),
            )
        )

    # 排序:有时间的在前(按时间),无时间的在后
    def _key(sc: StoryCard) -> tuple[int, str]:
        if sc.in_no_time_group:
            return (1, "")
        return (0, sc.sort_time or "")

    out.sort(key=_key, reverse=(order == "desc"))
    return out
