---
name: data-analysis
description: 统计量、相关性、技术指标(MA/RSI/MACD/布林)、标准化、图表数据生成的 L2 分析计算层。当用户问"走势怎么样""技术面""相关性""给我 K 线数据"时使用。
---

# data-analysis Skill

## 层级位置

**L2 分析计算层** — 回答"多少/怎么变/什么信号",是量价数据之上的**数值计算与信号提取**。与 `financial-analysis` 并列(前者量价,后者基本面)。

- **上游依赖**:`market-data`(取 K 线、价格序列)
- **被下游调用**:`risk-assessment`(波动率)、`deep-research`(技术面段落)、前端图表(`generate_chart_data`)

## 何时使用

- 用户询问技术指标(MA/RSI/MACD/布林带)
- 用户询问价格趋势、波动率
- 用户询问两只股票相关性 / 组合分散效果
- 需要对数据做标准化(Min-Max / Z-Score)
- 前端要 K 线/折线/柱状/面积图数据

不适用于:财务比率(用 `financial-analysis`)、估值对比(用 `market-data` + `sector-analysis`)。

## 工具清单(6)

| 工具 | 一句话 |
|---|---|
| `calculate_statistics` | 均值/标准差/最值/中位数 |
| `analyze_price_trend` | 价格趋势方向 + 强度 + 波动率 |
| `calculate_correlation` | 两只股票相关性 + 分散性解读 |
| `calculate_technical_indicators` | MA/RSI/MACD/布林带 |
| `normalize_data` | Min-Max 或 Z-Score 标准化 |
| `generate_chart_data` | 生成前端图表数据(K 线/折线/柱/面积) |

完整参数、技术指标信号解读、最小数据量要求:见 `references/tools.md`。

## 关键约定

- 技术指标最小数据量:MA60 需 60 日,MACD 需 26 日,RSI 需 14 日,布林需 20 日
- 相关性解读:≥0.8 强相关 / 0.5-0.8 中等 / <0.3 几乎无关;**相关 ≠ 因果**
- RSI 信号:>70 超买,<30 超卖;MACD 金叉买/死叉卖(非绝对)
- 趋势方向:up/down/sideways 三档
