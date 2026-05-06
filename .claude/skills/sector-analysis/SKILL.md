---
name: sector-analysis
description: 行业/概念板块分析(列表、涨跌幅、龙头、估值对比、财务对比)的 L3 评估决策层。当用户问"哪个行业最好""某行业龙头是谁""行业估值贵不贵""某概念板块有哪些股"时使用。
---

# sector-analysis Skill

## 层级位置

**L3 评估决策层** — 回答"横向对比/同业对标",提供 `risk-assessment` 个股视角之外的**板块视角**。两者并列。

- **上游依赖**:`market-data`(行业成分股的估值)、`financial-analysis`(行业财务均值)
- **被下游调用**:`deep-research`(研报"行业地位"段落)
- **侧向依赖**:向 `risk-assessment` 提供行业 PE/PB 均值作为对标基线

## 何时使用

- 用户询问"哪些行业表现好/估值低"
- 用户询问某行业的龙头股
- 用户要对比多个行业(如 ROE、PE)
- 用户询问热门概念板块(AI、新能源、芯片)及其成分股
- 用户想追踪板块轮动

不适用于:个股风险打分(用 `risk-assessment`)、实时个股行情(用 `market-data`)。

## 工具清单(7)

| 工具 | 一句话 |
|---|---|
| `get_industry_list` | A 股全行业分类列表 |
| `get_industry_performance` | 行业涨跌幅排名(日/周/月) |
| `get_industry_leaders` | 行业龙头股(按市值/营收/利润) |
| `compare_industry_metrics` | 行业财务指标对比(ROE/毛利率/净利率/负债率) |
| `compare_industry_valuation` | 行业估值对比(PE_ttm/PB/PS) |
| `get_concept_list` | 全部概念板块列表 |
| `get_concept_stocks` | 概念板块成分股(支持代码或名称) |

完整参数、估值解读、排序选项:见 `references/tools.md`。

## 关键约定

- 行业估值参考:PE<10 低估 / 10-25 合理 / 25-40 偏高 / >40 昂贵
- 行业涨跌幅周期:1d/5d/20d(日/周/月)
- 龙头股排序:market_cap(默认)/revenue/profit
- `get_concept_stocks` 接受 `concept_code` 或 `concept_name` 二选一
