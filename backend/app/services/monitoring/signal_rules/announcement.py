"""AnnouncementRule — LLM 分类 5 类公告(spec § 5.2 + decision 1)."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

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


class AnnouncementType(StrEnum):
    """5 类公告(spec § 5.2)+ 其他兜底."""
    EARNINGS_DISCLOSURE = "财报披露"        # 季报/半年报/年报
    PERFORMANCE_FORECAST = "业绩预告"       # 预增/预减/预亏
    ST_DELISTING = "ST/退市风险警示"
    MAJOR_RESTRUCTURING = "重大资产重组/并购"
    REGULATORY_PENALTY = "重大监管处罚/立案调查"
    OTHER = "其他"  # 不在 5 类(减持/回购/高管变动等)


class AnnouncementClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: AnnouncementType
    score: float = Field(ge=0.0, le=1.0)
    reasoning: str


_SYSTEM_PROMPT = """你是 A 股公告分类器,只判定以下 5 类:
1. 财报披露(季报/半年报/年报)
2. 业绩预告(预增/预减/预亏)
3. ST / 退市风险警示
4. 重大资产重组 / 并购
5. 重大监管处罚 / 立案调查

如果不属于这 5 类(如减持/回购/高管变动/股东大会决议/大宗交易),type 必须是 "其他"。
"""

_USER_PROMPT_TEMPLATE = """公告标题:{title}
摘要:{summary}

公司:{name}({ts_code})

输出 JSON:
{{"type": "<5类之一 or 其他>", "score": <0-1>, "reasoning": "<一句话>"}}

score 含义:
- 0.0 = 中性披露(常规季报无大幅变化)
- 0.5 = 中等关注(业绩预减/重组初步意向)
- 0.8+ = 重大利空(财报巨亏/ST/立案调查/并购终止)
"""


class AnnouncementRule(SignalRule):
    name = "announcement"
    description = "LLM 分类 5 类重大公告(spec § 5.2)"

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

        # 取最近一条公告分类(spec § 5.2:LLM 决策 5 类 + score)
        first = df.iloc[0]
        title = first.get("title", "")
        content = (first.get("content", "") or "")[:500]

        prompt = _SYSTEM_PROMPT + "\n\n" + _USER_PROMPT_TEMPLATE.format(
            title=title, summary=content, name=subject.name, ts_code=subject.ts_code,
        )

        response = llm.chat(prompt=prompt, tier="fast", schema=AnnouncementClassification)
        parsed = response.parsed
        if not isinstance(parsed, AnnouncementClassification):
            return SignalResult(
                rule_name=self.name, level=SignalLevel.GREEN, explanation="LLM 解析失败"
            )

        # spec § 5.2 + decision 1:type=='其他' → GREEN
        if parsed.type == AnnouncementType.OTHER:
            return SignalResult(
                rule_name=self.name,
                level=SignalLevel.GREEN,
                detected_value=parsed.score,
                explanation=f"非 5 类公告:{parsed.reasoning}",
            )

        score = float(parsed.score)
        red_th = thresholds.get("red_threshold", 0.8)
        yellow_th = thresholds.get("yellow_lower", 0.5)

        if score >= red_th:
            level = SignalLevel.RED
        elif score >= yellow_th:
            level = SignalLevel.YELLOW
        else:
            level = SignalLevel.GREEN

        return SignalResult(
            rule_name=self.name,
            level=level,
            detected_value=score,
            threshold=red_th,
            explanation=f"{parsed.type.value} score={score:.2f}: {parsed.reasoning}",
            raw_data_ref={"ts_code": subject.ts_code, "anns_count": len(df), "type": parsed.type.value},
        )
