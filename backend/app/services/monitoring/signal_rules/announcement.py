"""AnnouncementRule — uses LLM to classify recent announcements as 重大/可疑/普通."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.services.monitoring.signal_rules.base import (
    MonitoringSubject,
    SignalLevel,
    SignalResult,
    SignalRule,
)

if TYPE_CHECKING:
    from app.services.bocha_factory import BochaService
    from app.services.llm_service import LLMService
    from app.services.tushare_service import TushareService


class AnnouncementClassification(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="负面程度 0-1")
    summary: str


_PROMPT = """以下是 A 股上市公司{name}({ts_code})最近 7 天的公告标题和摘要,请判断这些公告整体上对公司是否构成负面信号。

公告列表:
{anns_text}

输出 JSON: {{"score": float 0~1, "summary": "一句话原因"}}
0.0 = 完全无影响(常规公告);0.5 = 有一定关注价值;0.8+ = 重大负面(立案/处罚/退市/造假/重大诉讼/巨额减持等)
"""


class AnnouncementRule(SignalRule):
    name = "announcement"
    description = "LLM 分类最近 7 天公告负面程度"

    async def evaluate(
        self,
        subject: MonitoringSubject,
        tushare: TushareService,
        bocha: BochaService,
        llm: LLMService,
        thresholds: dict[str, float],
    ) -> SignalResult:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        df = await tushare.get_anns(ts_code=subject.ts_code, start=start, end=end)
        if df.empty:
            return SignalResult(
                rule_name=self.name, level=SignalLevel.GREEN, explanation="近 7 天无公告"
            )

        anns_text = "\n".join(
            f"- {row.get('title', '')}: {(row.get('content', '') or '')[:200]}"
            for _, row in df.iterrows()
        )
        prompt = _PROMPT.format(
            name=subject.name,
            ts_code=subject.ts_code,
            anns_text=anns_text,
        )

        response = llm.chat(prompt=prompt, tier="fast", schema=AnnouncementClassification)
        raw_parsed = response.parsed
        if not isinstance(raw_parsed, AnnouncementClassification):
            return SignalResult(
                rule_name=self.name, level=SignalLevel.GREEN, explanation="LLM 解析失败"
            )

        parsed: AnnouncementClassification = raw_parsed
        score = float(parsed.score)
        if score >= thresholds["red_threshold"]:
            level = SignalLevel.RED
        elif score >= thresholds["yellow_lower"]:
            level = SignalLevel.YELLOW
        else:
            level = SignalLevel.GREEN

        return SignalResult(
            rule_name=self.name,
            level=level,
            detected_value=score,
            threshold=thresholds["red_threshold"],
            explanation=f"LLM 评分 {score:.2f}: {parsed.summary}",
            raw_data_ref={"ts_code": subject.ts_code, "anns_count": len(df)},
        )
