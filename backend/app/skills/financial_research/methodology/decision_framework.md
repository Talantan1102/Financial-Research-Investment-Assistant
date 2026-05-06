## § 4 投资决策框架 (Decision Framework)

## § 4.1 5 档评级触发逻辑 (Recommendation)

**关键约定** — Writer 必须调 Python helper, **不要让 LLM 自己算评级**:

```python
from app.skills.financial_research import load_skill

bundle = load_skill()
recommendation = bundle.scripts.classify_recommendation(metrics_dict)
# returns Literal: "recommend_buy" | "recommend_overweight" | "recommend_hold" |
#                  "recommend_underweight" | "recommend_sell"
```

`metrics_dict` 字段 (Analyst 在 evidence 阶段填):
- `pe_percentile`: 0..1 (来自 `get_pe_history`).
- `roe`: e.g. 0.18 (来自 `get_financials`).
- `revenue_yoy`, `net_profit_yoy`: e.g. 0.12.
- `forecast_signal`: `"positive" | "neutral" | "negative"` (来自 `get_forecast`).
- `pledge_ratio`: 0..1 (来自 `get_holder_change`).
- `asset_liability_warning`: bool.

**5 档触发条件** (见 `references/recommendation_rules.yaml`, Python 侧 `_PRIORITY` hard-coded 评估顺序):

| 评级 | 触发逻辑 (any_of / all_of) |
|---|---|
| **recommend_sell** | PE 分位 > 0.90 OR forecast_signal == negative OR 质押比例 > 0.60 OR asset_liability_warning |
| **recommend_buy** | PE 分位 < 0.30 AND ROE > 0.15 AND 营收 / 净利双升 (双 yoy > 0) |
| **recommend_overweight** | forecast_signal == positive OR (4 项条件中 ≥ 3 项满足) |
| **recommend_underweight** | PE 分位 > 0.70 OR 营收 yoy < 0 OR 净利润 yoy < 0 |
| **recommend_hold** | fallback (估值合理 + 财务健康 + 无明显催化也无明显风险) |

优先级评估顺序 (Python `_PRIORITY` 列表, 不可被 YAML 改写): sell → buy → overweight → underweight → hold.

## § 4.2 仓位计算公式 (Position Sizing)

**关键约定** — Writer 必须调 helper, **不要让 LLM 算百分比**:

```python
position_pct = bundle.scripts.compute_position_size_pct(
    recommendation=recommendation,        # 来自 § 4.1 classify
    risk_tolerance="moderate",            # 来自 user persona
    market_cap_cny=8e10,                  # 来自 get_stock_quote / daily_basic
)
# returns float (e.g. 12.0 = 12% 仓位)
```

**公式** (见 `references/position_size_rules.yaml`):

```
position_pct = base_pct[rec] × risk_multiplier[tol] × small_cap_factor
其中 small_cap_factor = small_cap_haircut (0.7) if market_cap < 500 亿 else 1.0
最终 capped at max_position_pct (30%)
```

`base_pct` 表 (按评级):
- recommend_buy = 15%
- recommend_overweight = 10%
- recommend_hold = 5%
- recommend_underweight = 2%
- recommend_sell = 0%

`risk_multiplier` 表 (按 user persona):
- conservative = 0.5x
- moderate = 1.0x
- balanced = 1.2x
- aggressive = 1.6x
- very_aggressive = 2.0x

例: recommend_buy + moderate + 1000 亿大市值 → 15 × 1.0 × 1.0 = 15%.
例: recommend_overweight + aggressive + 200 亿小市值 → 10 × 1.6 × 0.7 = 11.2%.

## § 4.3 为什么用 Python helper 而不让 LLM 算

1. **可复现性**: 同一份 evidence 永远得同一份评级 / 仓位 — 不受 LLM temperature / sampling 影响.
2. **审计性**: YAML 规则是 spec 的一部分, 可 review / version / diff; LLM 自由发挥则黑箱.
3. **avoiding hallucination**: LLM 算百分比经常算错 (10% × 1.6 = 写成 18% 是常见错), Python 算保正确.
4. **行业 benchmark 引用**: `lookup_industry_benchmark(industry, indicator)` 保数据契约一致, methodology 阈值 = references 数值.

**写入 narrative 的标准句式**:
- "综合 {N} 维评估, 给出评级: **{recommendation}** (触发条件: [关键满足项列表])."
- "结合用户风险偏好 ({tolerance}) 与市值规模 ({market_cap_cny} 元), 建议仓位: **{position_pct}%**."
- "如 user 风险偏好 / 市值发生变化, 仓位将自动调整 (Python 决定论)."
