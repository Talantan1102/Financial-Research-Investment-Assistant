---
name: financial-analysis
description: 三大财务报表查询 + 核心比率(ROE/ROA/毛利率/资产负债率)计算的 L2 分析计算层。当用户问"财务状况""盈利能力""偿债能力""ROE 趋势"时使用。基于 Tushare Pro 财务数据。
---

# financial-analysis Skill

## 层级位置

**L2 分析计算层** — 回答"多少/怎么变",是 `market-data` 原始财报字段之上的**比率化/趋势化**处理。与 `data-analysis` 并列(前者面向基本面,后者面向量价)。

- **上游依赖**:`market-data`(拉三表原始字段);也可直接调 Tushare 的比率接口。
- **被下游调用**:`risk-assessment`(财务风险维度)、`sector-analysis`(行业财务对比)、`deep-research`(综合研报的财务段落)。

## 何时使用

- 用户询问 ROE/ROA/毛利率/净利率/资产负债率
- 用户要看利润表/资产负债表/现金流量表
- 用户询问盈利能力/偿债能力趋势
- 用户要多期财务指标时间序列

不适用于:技术面指标(用 `data-analysis`)、实时估值 PE/PB(用 `market-data` 的 `get_daily_basic`)、风险综合打分(用 `risk-assessment`)。

## 工具清单(7)

| 工具 | 一句话 |
|---|---|
| `calculate_financial_ratios` | 一次算核心比率(ROE/ROA/毛利率/负债率等) |
| `get_income_statement` | 利润表(支持日期范围) |
| `get_balance_sheet` | 资产负债表 |
| `get_cash_flow` | 现金流量表 |
| `get_fina_indicator` | 一站式 100+ 财务指标,支持时间序列 |
| `analyze_profitability` | 盈利能力趋势分析(多期 ROE + 评级) |
| `analyze_solvency` | 偿债能力评估(流动比/速动比/负债率 + 评级) |

完整参数、评级标准、基准值:见 `references/tools.md`。

## 关键约定

- 报告期格式 `YYYYMMDD`;季度映射:Q1=0331, Q2=0630, Q3=0930, Q4=1231
- 报表数据单位为**万元**;比率为百分数或小数(字段说明中标注)
- ROE 评级:>20% 优秀 / 15-20% 良好 / 10-15% 一般 / <10% 较弱
- 偿债评级:流动比率 >2 且负债率 <50% 为"优秀"
