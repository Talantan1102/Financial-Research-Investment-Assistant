## § 3.3 事件驱动 (Event-driven)

**关键指标** (来自 `get_forecast`, `get_dividend_history`):
- 业绩预告 (`GetForecastTool.forecast_signal`): `"positive"` (预增 / 扭亏 / 略增) / `"negative"` (预减 / 亏损 / 略减) / `"neutral"`.
- 业绩预告窗口期 (年报 1 月底 / 半年报 7 月中 / 三季报 10 月中).
- 现金分红 (`GetDividendHistoryTool`): 派生 `dividend_consistency_score` (近 5 年连续分红次数 / 5).
- 股息率近 5 年趋势 (上升 / 稳定 / 下降).
- 股票回购公告: 金额 / 占总市值比例 / 是否注销.
- 解禁公告: 解禁日期 / 解禁规模 / 解禁股东类型 (大股东 / 战投 / 高管).
- 重组 / 收购公告: 是否构成重大资产重组 + 标的资产质量.

**判断阈值** (通用基准):

| 事件 | 强利好 | 利好 | 中性 | 利空 | 强利空 |
|---|---|---|---|---|---|
| 业绩预告 | 扭亏 / 预增 > 50% | 略增 0–50% | 持平 | 略减 0–-30% | 预减 < -30% / 亏损 |
| 分红 | 连续 5 年 + 股息率 > 4% | 连续 3 年 + > 2% | 偶尔分红 | 不分红 | 取消分红 |
| 回购 | 注销式 (减少股本) | 增持式 + 已实施 | 公告但未实施 | 缩减回购 | — |
| 解禁 | 战投长期持有 | 中小规模 < 5% | 5–10% 流通股 | > 10% 流通股 | > 30% + 大股东解禁 |

注: `recommendation_rules.yaml` 中:
- `recommend_overweight` 触发: `forecast_signal == "positive"`.
- `recommend_sell` 触发: `forecast_signal == "negative"`.
narrative 不需重复阈值, 只需引用语义标签.

**行业差异提醒**:
- **白酒 / 公用事业**: 高分红行业, `dividend_consistency_score` 接近 1 是基线 (五粮液 / 长江电力 etc).
- **科技互联网 / 创业板**: 通常不分红, 看回购 + 增持; 有限售解禁压力.
- **房地产**: 重组 / 配股事件高频, 看是否纾困 (借新还旧 vs 战投入主).
- **医药生物**: 创新药 BD 公告 + 临床数据公告是主要催化, 跟业绩预告独立.

**评估流程**:
1. 先看业绩预告窗口是否将至, 临近预告期 (1 月 / 7 月 / 10 月) 风险更大 — 跟预期差捕捉.
2. 调 `get_forecast` 看预告语言, 落到 `forecast_signal` 三档.
3. 调 `get_dividend_history` 看 5 年连续性 + 股息率走向, 派生 `dividend_consistency_score`.
4. 检查近 90 日解禁 / 回购 / 重组公告 — 强利好 / 强利空可单独触发评级跳档.
5. 跟基本面信号汇总, 用 evidence 中标记 `event_signals` 喂给 Writer.

**写入 narrative 的标准句式**:
- "{target_name} 最新业绩预告 {positive/neutral/negative}, 近 5 年分红一致性 {score}/1.0."
- "近 90 日 {有/无} 解禁压力 ({日期} 解禁 {X}% 流通股), {有/无}回购公告."
