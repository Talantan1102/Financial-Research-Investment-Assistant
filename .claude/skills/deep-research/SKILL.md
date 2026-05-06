---
name: deep-research
description: 深度研报生成的 L4 综合产出层,编排 L1-L3 多 skill 产出个股/行业/对比研报。当用户问"深度分析 X""生成研报""X vs Y 哪个更好""给我一个投资建议"时使用。
---

# deep-research Skill

## 层级位置

**L4 综合产出层** — 回答"怎么办/可投资性",是整套 skill 体系的**唯一 orchestrator**,把 L1-L3 的原子能力组合成完整研报。

- **上游依赖(全部)**:`market-data`、`web-research`、`financial-analysis`、`data-analysis`、`risk-assessment`、`sector-analysis`
- **不被调用**:L4 是顶层,没有更高层。

## 何时使用

- 用户要"深度分析"/"研究报告"/"全面分析"某只股票
- 用户要对比多只股票(茅台 vs 五粮液)
- 用户要某个行业的投资研究报告
- 用户问"XXX 值得买吗/怎么看 XXX"—— 需要综合多维度结论

不适用于:单点事实查询(用 L1)、单项指标计算(用 L2)、单维度风险评估(用 L3)。**用户问的如果不需要综合多维信息,别越级调本 skill。**

## 工具清单(3)

| 工具 | 一句话 |
|---|---|
| `generate_stock_report` | 个股深度研报(综合/估值/财务 三种 report_type) |
| `generate_industry_report` | 行业深度研报(全景/龙头/估值/趋势 四种 focus) |
| `generate_comparison_report` | 多股对比研报(估值/盈利/成长/风险 四维度) |

完整参数、报告结构、维度定义:见 `references/tools.md`。典型编排流程:见 `references/orchestration.md`。

## 编排模式(关键)

`deep-research` 的三个工具不是新逻辑,而是**把 L1-L3 的调用序列封装起来**,避免模型每次都要自己规划:

```
generate_stock_report(symbol)
  = market-data.get_stock_basic_info
  + market-data.get_daily_basic           (估值 PE/PB)
  + market-data.get_quote                  (当前行情)
  + financial-analysis.calculate_financial_ratios
  + financial-analysis.analyze_profitability
  + sector-analysis 的行业对标  (可选)
```

所以当用户说"分析茅台",模型应该调 `generate_stock_report` 而不是挨个调 6 个底层工具。

## 关键约定

- report_type:comprehensive(默认,全维度) / valuation(聚焦估值) / financial(聚焦财务)
- focus:overview(默认) / leaders / valuation / trend
- 对比维度 dimensions:valuation / profitability / growth / risk(默认全选)
- 数据缺失时对应 section 可能为 null,消费前检查
