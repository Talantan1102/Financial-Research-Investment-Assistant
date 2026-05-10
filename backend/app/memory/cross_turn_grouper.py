"""Cross-turn extraction grouper — 算法深度补丁 #4.

Spec § 11 末尾 #4: 按"关键词共指 + 时间间隔 < 5 分钟"合并相邻 episode 为 dialogue chunk;
每 chunk 取最近 5 turn 作 LLM extraction 输入,让 LLM 抽出跨 turn fact
(我刚买了 → 买什么 → 茅台 500 股).

决策树:
- 间隔 < 5 分钟          → 同 chunk
- 5-10 分钟 + 共指关键词  → 同 chunk
- 否则                  → 切新 chunk

简化关键词识别(ts_code / 14 个行业 + 策略关键词);完整白名单 / jieba pre-tokenize
留 Plan 5 / Plan 8 优化(spec § 11 #4 brainstorming 范围未要求穷尽).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

from app.memory.models import ChatMemoryEpisode

# 切 chunk 的时间阈值
TEMPORAL_THRESHOLD = timedelta(minutes=5)
# 关键词共指可以放宽到 10min (语义连续优先)
COREFERENCE_RELAX_THRESHOLD = timedelta(minutes=10)
# 滑动窗口默认 turn 数
DEFAULT_WINDOW = 5

# 简化关键词识别(ts_code / 行业关键词) — 完整白名单留 Plan 5 / 8 的 registry
TS_CODE_PATTERN = re.compile(r"\b\d{6}(?:\.SH|\.SZ|\.BJ)?\b")
KEYWORD_PATTERN = re.compile(
    r"(茅台|五粮液|宁德时代|比亚迪|医药|新能源|消费|科技|金融|策略|价值|成长|股息)"
)


@dataclass
class DialogueChunk:
    """合并后的 dialogue chunk — 一组语义连续 episode."""

    episodes: list[ChatMemoryEpisode] = field(default_factory=list)

    def keywords(self) -> set[str]:
        """合并 chunk 内所有 episode 抽出的 ts_code / 关键词."""
        kws: set[str] = set()
        for ep in self.episodes:
            user_text = cast(str, ep.user_message_text or "")
            agent_text = cast(str, ep.agent_response_text or "")
            text = user_text + " " + agent_text
            kws.update(TS_CODE_PATTERN.findall(text))
            kws.update(KEYWORD_PATTERN.findall(text))
        return kws


def _extract_keywords(text: str) -> set[str]:
    kws: set[str] = set(TS_CODE_PATTERN.findall(text))
    kws.update(KEYWORD_PATTERN.findall(text))
    return kws


def group_episodes(episodes: list[ChatMemoryEpisode]) -> list[DialogueChunk]:
    """按时间序合并 episode 为 dialogue chunk.

    决策树:
    - 间隔 < 5 分钟 → 同 chunk
    - 5-10 分钟 + 关键词共指(ts_code 或行业关键词) → 同 chunk
    - 否则 → 切新 chunk

    输入空 list 返回 [].
    """
    if not episodes:
        return []
    sorted_eps = sorted(episodes, key=lambda e: (e.created_at, e.episode_index))
    chunks: list[DialogueChunk] = [DialogueChunk(episodes=[sorted_eps[0]])]
    for ep in sorted_eps[1:]:
        last_chunk = chunks[-1]
        last_ep = last_chunk.episodes[-1]
        ep_ts = cast(datetime, ep.created_at)
        last_ts = cast(datetime, last_ep.created_at)
        delta: timedelta = ep_ts - last_ts
        if delta < TEMPORAL_THRESHOLD:
            last_chunk.episodes.append(ep)
            continue
        if delta < COREFERENCE_RELAX_THRESHOLD:
            user_text = cast(str, ep.user_message_text or "")
            agent_text = cast(str, ep.agent_response_text or "")
            ep_text = user_text + " " + agent_text
            ep_kws = _extract_keywords(ep_text)
            if ep_kws and ep_kws & last_chunk.keywords():
                last_chunk.episodes.append(ep)
                continue
        chunks.append(DialogueChunk(episodes=[ep]))
    return chunks


def build_sliding_window(
    chunk: DialogueChunk, window: int = DEFAULT_WINDOW
) -> list[dict[str, Any]]:
    """取 chunk 最近 N turn 作 LLM extraction prompt 输入.

    返回结构: [{episode_id, episode_index, user_message, agent_response, created_at}, ...]
    Plan 2A 的 LLMExtractor.extract_facts(turns=...) 接受此结构.
    """
    tail = chunk.episodes[-window:] if len(chunk.episodes) > window else list(chunk.episodes)
    out: list[dict[str, Any]] = []
    for ep in tail:
        ts = cast(datetime | None, ep.created_at)
        out.append(
            {
                "episode_id": str(ep.episode_id),
                "episode_index": ep.episode_index,
                "user_message": cast(str, ep.user_message_text or ""),
                "agent_response": cast(str, ep.agent_response_text or ""),
                "created_at": ts.isoformat() if ts else None,
            }
        )
    return out
