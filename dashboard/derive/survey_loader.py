"""external_agent_survey.jsonl 加载器 — server 启动时读一次缓存。

每条记录是某个外部 agent 项目里抽出的"harness 工程 trick",按 8 维度分组。
schema 见 dashboard/data/external_agent_survey.jsonl 头部 placeholder。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class SurveyTrick:
    id: str
    repo: str
    stars: int
    url: str
    dimension: str
    trick_title: str
    description: str
    source_anchor: str
    why_interesting: str
    linked_cap_id: str | None


@lru_cache(maxsize=1)
def load_survey(jsonl_path_str: str) -> tuple[SurveyTrick, ...]:
    path = Path(jsonl_path_str)
    out: list[SurveyTrick] = []
    if not path.is_file():
        return ()
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            d = json.loads(line)
            if d.get("id", "").startswith("_"):
                continue  # 跳过 placeholder
            out.append(
                SurveyTrick(
                    id=d["id"],
                    repo=d["repo"],
                    stars=int(d["stars"]),
                    url=d["url"],
                    dimension=d["dimension"],
                    trick_title=d["trick_title"],
                    description=d["description"],
                    source_anchor=d["source_anchor"],
                    why_interesting=d["why_interesting"],
                    linked_cap_id=d.get("linked_cap_id"),
                )
            )
    return tuple(out)


def group_by_dimension(
    tricks: tuple[SurveyTrick, ...],
) -> dict[str, list[SurveyTrick]]:
    out: dict[str, list[SurveyTrick]] = {}
    for t in tricks:
        out.setdefault(t.dimension, []).append(t)
    # 每组内按 stars 降序
    for dim in out:
        out[dim].sort(key=lambda t: -t.stars)
    return out


@dataclass(frozen=True)
class RepoSummary:
    repo: str
    stars: int
    url: str
    trick_count: int


def repo_summary(tricks: tuple[SurveyTrick, ...]) -> list[RepoSummary]:
    """按 repo 聚合 — 给页面顶部显示项目列表."""
    counts: dict[str, int] = {}
    meta: dict[str, tuple[int, str]] = {}
    for t in tricks:
        counts[t.repo] = counts.get(t.repo, 0) + 1
        meta[t.repo] = (t.stars, t.url)
    out = [
        RepoSummary(repo=r, stars=meta[r][0], url=meta[r][1], trick_count=counts[r]) for r in counts
    ]
    return sorted(out, key=lambda s: -s.stars)
