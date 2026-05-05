## § 1.1 偿债能力 (Solvency)

**关键指标** (来自 `get_balance_sheet`, `get_cashflow`):
- 资产负债率 = `total_liab / total_assets` (来自 `GetBalanceSheetTool`, 派生字段 `asset_liability_ratio`).
- 流动比率 = `total_cur_assets / total_cur_liab` (短期偿债能力).
- 速动比率 = `(total_cur_assets - inventories) / total_cur_liab` (剔除存货后短期偿债能力).
- 经营现金流为正 = `n_cashflow_act > 0` (来自 `GetCashflowTool.positive_ocf`, binary signal).

**判断阈值** (引用 `references/industry_benchmarks.json`, **行业差异极大** — 必须查 `lookup_industry_benchmark`):

| 指标 | 健康 (DEFAULT) | 一般 | 警戒 | 高风险 |
|---|---|---|---|---|
| 资产负债率 | < 0.50 | 0.50–0.60 | 0.60–0.70 | > 0.70 |
| 流动比率 | > 2.0 | 1.5–2.0 | 1.0–1.5 | < 1.0 |
| 速动比率 | > 1.0 | 0.7–1.0 | 0.5–0.7 | < 0.5 |

**行业差异提醒** (关键 — DEFAULT 阈值不可机械套用):
- **白酒**: 健康 < 0.30 (低杠杆经营, 现金流强), 警戒 > 0.50.
- **公用事业 / 房地产**: 健康 < 0.65, 警戒 > 0.80 (重资产 + 长周期, 高杠杆是常态).
- **银行金融**: 资产负债率通常 > 0.92 (吸收存款本身就是负债), 本框架**不适用**, 请参考资本充足率 (CAR) / 核心一级资本充足率等监管指标 — 见 `industry_benchmarks.json._note`.
- **科技互联网 / 医药生物**: 健康 < 0.40, 警戒 > 0.60 (轻资产, 高杠杆通常意味着扩张失控).

**评估流程**:
1. 先查行业 — 调 `bundle.scripts.lookup_industry_benchmark(industry=..., indicator="资产负债率_健康")` 拿行业基准.
2. 再算公司当前资产负债率, 跟行业基准对比 (而非 DEFAULT 50%).
3. 看流动 / 速动比率判断短期支付能力, 二者背离 (流动 > 2 但速动 < 0.7) 通常意味存货积压.
4. 最后看经营现金流是否为正, 即使指标好但 OCF 持续为负, 仍属"账面健康 + 实际窟窿"红灯.

**写入 narrative 的标准句式**:
- "{target_name} 资产负债率 {X}% (行业平均 {Y}%, 来自 industry_benchmarks.json), 处于{健康/一般/警戒/高风险}水平."
- "经营现金流连续 {N} 年为正, 偿债基础{扎实/脆弱}."
