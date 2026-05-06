## § 2.1 估值水平 (Valuation)

**关键指标** (来自 `get_daily_basic`, `get_pe_history`):
- PE_TTM = 当前股价 / 滚动 12 个月每股净利润 (`GetDailyBasicTool.pe_ttm`).
- PB = 当前股价 / 每股净资产 (`GetDailyBasicTool.pb`).
- 股息率 = 近 12 个月股息 / 当前股价 (`GetDailyBasicTool.dv_ratio`).
- PE 历史分位 (`GetPeHistoryTool.pe_percentile`): 当前 PE 在历史 N 年中的分位数 (0..1).
- 估值带 (`GetPeHistoryTool.valuation_band`): 派生 Literal, 取值 `"underpriced" | "neutral" | "overpriced"`, 来自 PE 分位的离散化 (< 30% / 30–70% / > 70%).

**判断阈值** (通用 sanity 基准):

| 指标 | 低估 | 合理 | 偏贵 | 高估 |
|---|---|---|---|---|
| PE 历史分位 (5 年/3 年) | < 30% | 30–50% | 50–70% | > 70% |
| 当前 PE vs 行业中位 | < 行业中位 | 行业中位 ± 20% | 高 20–50% | > 行业中位 1.5x |
| PB | < 1 (破净) | 1–3 | 3–5 | > 5 |
| 股息率 | > 4% | 2–4% | 1–2% | < 1% |

**行业差异提醒** (`industry_benchmarks.json.PE_行业中位`):
- **白酒**: PE 行业中位 35.0 (高品牌溢价), 16–25 算低估.
- **公用事业 / 银行金融**: PE 行业中位 12.0 / 6.0 (确定性强, 增速低), PE > 15 已偏贵.
- **科技互联网**: PE 行业中位 50.0 (成长期估值高, 看 PEG 比 PE 更有效).
- **医药生物**: PE 行业中位 35.0 (创新药 vs 仿制药差距大, 必须看子赛道).
- **房地产**: PE 行业中位 8.0 (周期 + 政策双重压制, 低 PE 不等于低估).

注意: `recommendation_rules.yaml` 中 `recommend_buy` 触发条件之一是 "PE 历史分位 < 0.30", 触发 `recommend_sell` 之一是 "> 0.90" — 这是 Python 侧硬规则, narrative 不需重复阈值, 只需引用 `valuation_band`.

**评估流程**:
1. 先看 PE 历史分位 (`pe_percentile`) — 同一只股票纵向比, 排除"行业整体贵 / 便宜"的扰动.
2. 再调 `lookup_industry_benchmark(industry, "PE_行业中位")` 拿行业中位, 横向比较.
3. 看 PB + 股息率作为辅助 — 周期股 (银行 / 房地产) 看 PB 比 PE 更稳定, 公用事业看股息率.
4. 别用单一估值指标下判断 — PE 分位 < 30% 但行业整体景气下行时, "低估"也可能继续杀.

**写入 narrative 的标准句式**:
- "{target_name} 当前 PE_TTM = {X}, 处于近 5 年 {Y}% 分位 ({underpriced/neutral/overpriced})."
- "对标行业中位 {Z} (来自 industry_benchmarks.json), {高于/低于/接近}行业 {N}%."
