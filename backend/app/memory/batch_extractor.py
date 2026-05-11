"""Batch extractor(spec § 4 优化 #2).

End-of-session 把 ≤5 episode 拼一个 LLM call:
  - system prompt(~1K token)只发一次 → 平均 200 token/episode 摊薄
  - LLM 输出每 fact 必带 source_episode_id, 直接关联回原 episode

Plan 2 写入 path B(end-of-session)走本 extractor.
单 episode 退化: 仍走一次 LLM 调用(prompt 形态相同, 不切 codepath).

设计取舍 (vs Plan 2A LLMExtractor.extract_facts):
  - LLMExtractor.extract_facts 是跨 turn 滑动窗口语义合并 (1 chunk → 1 ExtractionOutput)
  - BatchExtractor.extract_batch 是 cost optimization layer (N episode → 1 LLM call,
    每 fact 标 source_episode_id 归属)
  - 两者输出 dataclass 不同: ExtractedFact 平铺 fact (本 plan), ExtractionOutput
    分 entities + edges (Plan 2A); 在 path b runner / archival_insert 入口处适配

类型选择: 输出 BatchExtractedFact (新 dataclass), 不复用 Plan 2A 的 ExtractionOutput
是因 ExtractionOutput 没有 source_episode_id 字段 + 不平铺 (entities/edges 分开).
契约 § 17 A2 (5) 提到统一 ExtractionOutput, 但 batch 场景需 source_episode_id 归属
key, 故引入 batch-specific dataclass; 真接 archival_insert 时 caller 做 adapter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.memory.models import ChatMemoryEpisode

_BATCH_SYSTEM_PROMPT = """\
你是金融对话事实抽取器. 输入是 1-5 个 chat episode (<episode id="..." index="..."> 包裹),
请从所有 episode 中抽取金融语义事实(持仓 / 偏好 / 观点 / 比较 / 关注),
输出 JSON {"facts": [...]}, 每条 fact 必须带:
  - source_episode_id (从 episode 标签复制)
  - source_label / target_label (实体规范化前的原文表述)
  - rel_type (HOLDS / WATCHES / PREFERS / AVOIDS / EXPRESSED_VIEW / SOLD / STUDIED / COMPARED 等)
  - reasoning (为何抽出)
  - importance (0.9 高 / 0.5 中 / 0.2 低 三档之一)
  - evidence_quote (原文 substring, 用户消息或 agent 回复中可定位)
  - valid_from (ISO 8601 时间戳, 事实生效时间)
注意: 同一 episode 可能产出多条 fact; 无金融语义的 episode 输出空 facts.
"""


class LLMLike(Protocol):
    async def chat_async(self, *, system_prompt: str, user_prompt: str, model: str) -> str: ...


@dataclass
class BatchExtractedFact:
    """Plan 5 batch 路径平铺 fact, 含 source_episode_id 归属 key.

    跟 Plan 2A 的 ExtractedEdge / ExtractionOutput 互补 (而非替代):
    Plan 2A 是单 episode 抽取无需归属, Plan 5 batch 跨 episode 需要 key 关联.
    """

    source_episode_id: UUID
    source_label: str
    target_label: str
    rel_type: str
    reasoning: str
    importance: float
    evidence_quote: str
    valid_from: datetime


class BatchExtractor:
    """End-of-session batch extraction(spec § 4 优化 #2)."""

    def __init__(self, llm: LLMLike, model: str = "qwen-plus") -> None:
        self._llm = llm
        self._model = model

    @property
    def system_prompt(self) -> str:
        return _BATCH_SYSTEM_PROMPT

    def _build_user_prompt(self, episodes: list[ChatMemoryEpisode]) -> str:
        parts: list[str] = []
        for ep in episodes:
            parts.append(
                f'<episode id="{ep.episode_id}" index="{ep.episode_index}">\n'
                f"user: {ep.user_message_text}\n"
                f"agent: {ep.agent_response_text or ''}\n"
                f"</episode>"
            )
        return "\n\n".join(parts)

    async def extract_batch(self, episodes: list[ChatMemoryEpisode]) -> list[BatchExtractedFact]:
        if not episodes:
            return []
        user_prompt = self._build_user_prompt(episodes)
        raw = await self._llm.chat_async(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
            model=self._model,
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # spec § 4 失败矩阵: invalid JSON → episode 不标 extracted_at, 下次 batch 重试
            return []

        facts_raw = payload.get("facts", []) if isinstance(payload, dict) else []
        out: list[BatchExtractedFact] = []
        valid_eids = {ep.episode_id for ep in episodes}
        for f in facts_raw:
            try:
                eid = UUID(str(f["source_episode_id"]))
                if eid not in valid_eids:
                    continue  # LLM 幻觉的 episode_id 丢弃
                out.append(
                    BatchExtractedFact(
                        source_episode_id=eid,
                        source_label=str(f["source_label"]),
                        target_label=str(f["target_label"]),
                        rel_type=str(f["rel_type"]),
                        reasoning=str(f.get("reasoning", "")),
                        importance=float(f.get("importance", 0.5)),
                        evidence_quote=str(f.get("evidence_quote", "")),
                        valid_from=datetime.fromisoformat(f["valid_from"]),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return out
