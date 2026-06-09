---
name: financial_research
description: |
  A 股个股投资研究 SOP 包 — 11 维方法论 + 行业 benchmark 查询。
  Analyst 在 evidence 阶段引用 methodology 查阈值, 并用 lookup_industry_benchmark
  查行业基准; Writer 在 narrative 阶段引用 SOP 组织综合研判。
  去推荐改造(2026-06-04): 评级/仓位决策助手已下线, 报告不再产出买卖评级与仓位。
version: 0.8.5
trigger:
  - investment_due_diligence
loaded_by:
  - Analyst.build_prompt
  - Writer.build_prompt
component_count: 13
---

# Financial Research Skill Bundle

本 skill 把"个股投资研究"工作流的领域知识从 Agent prompt 中抽出, 集中沉淀为可独立
维护的方法论 + 数据 + 脚本三件套。Analyst / Writer 通过 `load_skill()` 一次性拿到
`SkillBundle`, 在 prompt 组装阶段按需注入。

> 去推荐改造(2026-06-04): 评级/仓位推荐引擎(classify_recommendation /
> compute_position_size_pct + recommendation_rules.yaml / position_size_rules.yaml)
> 已整体下线。报告 § 6 从"投资建议"改为"综合研判"(多空两面 + 估值背景 + 关键判断变量,
> 不下买卖结论), 见 `methodology/decision_framework.md`。

## Components (13 件)

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
| 综合研判框架 | `decision_framework.md` | (综合, 无买卖结论) |

### 2. References (1 file, `references/*`)

- `industry_benchmarks.json` — 7 行业 (白酒/公用事业/科技互联网/银行金融/房地产/医药生物/`DEFAULT`) × 5 指标
  (`ROE_行业平均`, `ROE_行业领先`, `资产负债率_健康`, `资产负债率_警戒`, `PE_行业中位`).

### 3. Scripts (1 helper, `scripts/__init__.py` re-export)

- `lookup_industry_benchmark(*, industry, indicator) -> float` — 行业 benchmark 查询 + DEFAULT 兜底.

合计 11 + 1 + 1 = 13 件。

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
```

## 设计契约

- **数据 = 契约**: methodology markdown 中提到的"判断阈值"必须跟 `references/`
  数值一致, 不能私改; 如果有冲突, references 为准.
- **Python 决定论 vs LLM 自由度**: 数值类数据查询 (行业 benchmark) 走 scripts 保可复现;
  narrative 写作与综合研判走 LLM. 去推荐后不再有 Python 决定论的评级/仓位计算.
- **行业差异**: 银行金融的资产负债率 schema 不直接适用 (见 `industry_benchmarks.json._note`),
  请参考 CAR 等监管指标 — methodology 里在相关位置提示读者.
