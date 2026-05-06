---
name: financial_research
description: |
  A 股个股投资研究 SOP 包 — 11 维方法论 + 行业 benchmark + 评级/仓位决策助手。
  Analyst 在 evidence 阶段引用 methodology 查阈值, Writer 在 narrative 阶段调
  scripts.classify_recommendation / compute_position_size_pct 决定评级与仓位
  (确定性 Python helper, 不让 LLM 自己算数).
version: 0.8.5
trigger:
  - investment_due_diligence
loaded_by:
  - Analyst.build_prompt
  - Writer.build_prompt
component_count: 17
---

# Financial Research Skill Bundle (v0.8.5)

本 skill 把"个股投资研究"工作流的领域知识和决策规则从 Agent prompt 中抽出,
集中沉淀为可独立维护的方法论 + 数据 + 脚本三件套。Analyst / Writer 通过
`load_skill()` 一次性拿到 `SkillBundle`, 在 prompt 组装阶段按需注入。

## Components (17 件)

### 1. Methodology (11 maps, `methodology/*.md`)

| 维度 | 文件 | 关键 tool |
|---|---|---|
| 偿债能力 | `solvency.md` | `get_balance_sheet`, `get_cashflow` |
| 盈利能力 | `profitability.md` | `get_financials` |
| 成长性 | `growth.md` | `get_financials`, `get_forecast` |
| 现金流质量 | `cashflow_quality.md` | `get_cashflow`, `get_financials` (cross-tool) |
| 估值水平 | `valuation.md` | `get_daily_basic`, `get_pe_history` |
| 行业景气 | `industry.md` | `web_search` |
| 股东结构与治理 | `shareholder_governance.md` | `get_holder_change` |
| 短期资金流 | `short_term_capital_flow.md` | `get_money_flow` |
| 事件驱动 | `event_driven.md` | `get_forecast`, `get_dividend_history` |
| 风险因子 | `risk_factors.md` | (综合) |
| 决策框架 | `decision_framework.md` | (综合 + scripts) |

### 2. References (3 files, `references/*`)

- `industry_benchmarks.json` — 7 行业 (白酒/公用事业/科技互联网/银行金融/房地产/医药生物/`DEFAULT`) × 5 指标
  (`ROE_行业平均`, `ROE_行业领先`, `资产负债率_健康`, `资产负债率_警戒`, `PE_行业中位`).
- `recommendation_rules.yaml` — 5 档评级 DSL (`recommend_sell` / `recommend_buy` /
  `recommend_overweight` / `recommend_underweight` / `recommend_hold`),
  Python 侧 hard-coded `_PRIORITY` 控评估顺序.
- `position_size_rules.yaml` — 仓位计算公式参数 (`base_pct` × `risk_multiplier` ×
  `small_cap_haircut`, 上限 `max_position_pct=30%`).

### 3. Scripts (3 helpers, `scripts/__init__.py` re-export)

- `classify_recommendation(metrics) -> Recommendation` — YAML DSL 引擎, 5 档评级.
- `compute_position_size_pct(*, recommendation, risk_tolerance, market_cap_cny) -> float` — 仓位百分比.
- `lookup_industry_benchmark(*, industry, indicator) -> float` — 行业 benchmark 查询 + DEFAULT 兜底.

合计 11 + 3 + 3 = 17 件。

## Loader Usage

```python
from app.skills.financial_research import load_skill

bundle = load_skill()

# Analyst 在 build_prompt 注入 SOP 给 LLM
sop_text = bundle.composed_sop()  # 11 markdown 按固定顺序 concat
prompt = f"<methodology>\n{sop_text}\n</methodology>\n..."

# Analyst 想查行业 benchmark
roe_avg = bundle.scripts.lookup_industry_benchmark(
    industry="白酒", indicator="ROE_行业平均"
)

# Writer 决定最终评级 + 仓位 (LLM 不算数)
rec = bundle.scripts.classify_recommendation(metrics)
pct = bundle.scripts.compute_position_size_pct(
    recommendation=rec, risk_tolerance="moderate", market_cap_cny=8e10
)
```

## 设计契约

- **数据 = 契约**: methodology markdown 中提到的"判断阈值"必须跟 `references/`
  数值一致, 不能私改; 如果有冲突, references 为准.
- **Python 决定论 vs LLM 自由度**: 数值类决策 (评级 / 仓位 / benchmark 查询) 走
  scripts, narrative 写作走 LLM. 可复现性优先.
- **行业差异**: 银行金融的资产负债率 schema 不直接适用 (见 `industry_benchmarks.json._note`),
  请参考 CAR 等监管指标 — methodology 里在相关位置提示读者.
