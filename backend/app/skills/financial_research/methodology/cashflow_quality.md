## § 1.4 现金流质量 (Cashflow Quality)

**关键指标** (来自 `get_cashflow` + `get_financials` — **必须 cross-tool**):
- 经营现金流 (OCF) = `n_cashflow_act` (来自 `GetCashflowTool`).
- 投资现金流 (ICF) = `n_cashflow_inv_act`.
- 筹资现金流 (FCF_funding) = `n_cash_flows_fnc_act`.
- `positive_ocf`: bool (来自 `GetCashflowTool`, **binary signal only**, 不含比率).
- 净利润 = `net_profit` (来自 `GetFinancialsTool`).
- **OCF / NI 比率 (现金流真实度)** = `n_cashflow_act / net_profit` — **必须 Analyst 跨 tool 算**.

**Cross-tool 约定 (重要)**:
- `GetCashflowTool` 单 tool 只暴露 `positive_ocf` 这个 binary 信号 (避免在单 tool 内做跨 endpoint 的财务比率, 保 tool 纯净).
- 真 OCF/NI 比率需 Analyst 在 evidence 阶段从两个 tool 结果中抽数 self-compute:
  ```
  ratio = GetCashflowTool.n_cashflow_act / GetFinancialsTool.net_profit
  ```
- 见 Task 2 `app/tools/get_cashflow.py` TODO 注释 — 这个约定 v0.8.5 之后稳定.

**判断阈值** (通用 sanity 标准):

| 指标 | 健康 | 一般 | 警戒 | 高风险 |
|---|---|---|---|---|
| OCF / NI 比率 | > 0.8 (利润真实) | 0.5–0.8 | 0.2–0.5 | < 0.2 (利润纸面化) |
| 经营现金流 (持续性) | 连续 3 年 + | 偶尔正 | 主要为负 | 持续负 |
| FCF 自由现金流 = OCF + ICF | 持续 > 0 (能自我造血) | 接近 0 | 持续 < 0 | < 0 + 筹资为正 (借钱填窟窿) |

**行业差异提醒**:
- **白酒 / 公用事业 / 高端制造**: OCF / NI > 1 是常态 (预收款多 / 折旧大).
- **房地产 / 重资产周期股**: OCF 短期可能为负 (拿地投入), 看 3–5 年滚动 OCF 比单期更可靠.
- **科技互联网 (SaaS)**: 早期 ICF 大额为负是合理的, 但 OCF 必须转正; 持续 OCF 为负 + 高股权融资 = 烧钱模式, 警惕.

**评估流程**:
1. 先看 `positive_ocf` 是否为 `true` — 一票否决项, 持续为负直接降级.
2. 跨 tool 算 OCF / NI 比率, < 0.5 时即使 ROE 高也要 narrative 中标"利润含金量低".
3. 看 OCF + ICF 是否能覆盖 FCF_funding (筹资) 缺口, 否则属"借钱发展" — 适合早期成长但成熟期警惕.
4. 跟同行业 OCF / NI 中枢对比, 单纯绝对值无意义.

**写入 narrative 的标准句式**:
- "{target_name} OCF / 净利润 = {X} ({与利润高度匹配/有一定背离/利润纸面化}), 经营现金流连续 {N} 期为正."
- "自由现金流 ({OCF + ICF}) {能/不能}覆盖筹资活动, 反映{自我造血能力强/需依赖外部融资}."
