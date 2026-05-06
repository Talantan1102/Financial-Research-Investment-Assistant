## § 1.3 成长性 (Growth)

**关键指标** (来自 `get_financials`, `get_forecast`):
- 营收 yoy = `(本期营业收入 - 去年同期) / 去年同期` (`GetFinancialsTool.revenue_yoy`).
- 净利润 yoy = `(本期净利润 - 去年同期) / 去年同期` (`GetFinancialsTool.net_profit_yoy`).
- 业绩预告 (`GetForecastTool.forecast_signal`): `"positive"` (预增/扭亏/略增) / `"negative"` (预减/亏损/略减) / `"neutral"`.
- 持续增长能力: 连续 3 年/4 个季度营收 + 净利双升 = 强成长信号.

**判断阈值** (通用 sanity 标准, 个股以行业 benchmark 为准):

| 指标 | 健康 | 一般 | 警戒 | 高风险 |
|---|---|---|---|---|
| 营收 yoy | > 20% | 5–20% | 0–5% | < 0 (下滑) |
| 净利润 yoy | > 25% | 10–25% | 0–10% | < 0 |
| 业绩预告 | `positive` | `neutral` | — | `negative` |

注: "营收 + 净利双升" 是 `recommendation_rules.yaml` 中 `recommend_buy` 触发条件之一 — Writer 计算评级时 Python 侧自动套用, 不需 narrative 重复阈值判断.

**行业差异提醒**:
- **科技互联网 / 医药生物**: 高成长是基线, < 15% 就属"失速"; PEG (= PE / 净利 yoy) 超过 1.5 通常已偏贵.
- **白酒 / 公用事业**: 增长率天花板低 (10–15% 就算优秀), 但确定性高, 可承受更高 PE.
- **房地产 / 周期股**: 营收 yoy 高度依赖周期位置, 单年 +50% 不能外推 — 看 3 年滚动均值更可靠.

**评估流程**:
1. 先看历史 yoy 趋势 (取 4–8 期数据), 判断是单期波动还是持续趋势.
2. 再看营收 vs 净利双指标是否同向, 营收涨净利跌 = 利润率被侵蚀, 警惕.
3. 调 `get_forecast` 看下期预告信号, 跟历史趋势是否一致.
4. 最后跟行业景气度 (见 `industry.md`) 对照, 区分公司 alpha 还是行业 beta.

**写入 narrative 的标准句式**:
- "{target_name} 近 4 季营收 yoy 均值 {X}% / 净利 yoy 均值 {Y}%, {双升/单升/双降}."
- "下期业绩预告 {positive/neutral/negative}, 跟历史趋势{一致/背离}."
