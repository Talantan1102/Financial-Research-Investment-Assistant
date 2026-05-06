## § 3.4 风险因子 (Risk Factors)

**关键指标** (综合多 tool):
- 大股东减持公告 (来自 `get_holder_change`).
- 股权质押比例 (`pledge_ratio`, 来自 `get_holder_change` 派生).
- 行业政策红线 (来自 `web_search`, e.g. 反垄断 / 集采 / 限购).
- 财务异常项 (商誉 / 应收账款 / 存货 突增, 来自 `get_balance_sheet`, `get_financials`).
- 资产负债表警戒 (`asset_liability_warning`: bool, 派生 = 资产负债率 > 行业警戒线).
- 业绩负预告 (`forecast_signal == "negative"`).
- 监管处罚 / 诉讼 / 立案调查公告 (来自 `web_search`, `get_news`).

**判断阈值** (一票否决类红线):

| 风险 | 红线触发 | 影响 |
|---|---|---|
| 业绩负预告 | `forecast_signal == "negative"` | 直接 → recommend_sell (硬规则) |
| 质押比例过高 | `pledge_ratio > 0.60` | 直接 → recommend_sell |
| 资产负债表警戒 | `asset_liability_warning == True` | 直接 → recommend_sell |
| PE 历史分位极端 | `pe_percentile > 0.90` | 直接 → recommend_sell |
| 立案调查 / 退市风险警示 | 监管公告 | 退出研究, 不给推荐 |
| 大额商誉减值 | 单期减值 > 净资产 20% | 评级降 1–2 档 |

注: 上 4 条红线是 `recommendation_rules.yaml` 中 `recommend_sell` 的 `any_of` 触发条件, narrative 不需重复阈值, 只需如实标注事件.

**行业差异提醒**:
- **银行金融**: 不良率 + 资本充足率 (CAR) + 拨备覆盖率 是行业专用风险指标, 上述通用框架补充用.
- **房地产**: 三道红线 (剔除预收款资产负债率 > 70% / 净负债率 > 100% / 现金短债比 < 1) — 套用通用资产负债率不够, 需 narrative 中补丁.
- **医药生物**: 集采降价 / 临床失败 / FDA 拒批 — 单事件可造成 30%+ 跌幅, 需事件驱动维度交叉.
- **科技互联网**: 监管反垄断 / 数据安全 / 个保法 — 阶段性可冲击商业模式.

**评估流程**:
1. 先扫所有红线触发项, 任一中的就把 evidence 中 `red_flag` 设为 `true`, 评级 DSL 自动归到 sell.
2. 再看次级风险 (商誉 / 应收 / 存货 突增), 派生评级降档而非清零.
3. 跟行业专属风险指标对比 (银行 / 房地产 / 医药看专项).
4. 最后写 narrative — 风险章节必须明示 `red_flag` + 严重等级, 让阅读者一眼看到.

**写入 narrative 的标准句式**:
- "{target_name} 触发 {N} 项红线: {红线列表} — 评级强制下调至 sell."
- "{target_name} 无硬红线, 但需关注: [次级风险列表]."
