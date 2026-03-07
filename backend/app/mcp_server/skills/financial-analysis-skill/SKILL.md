---
name: financial-analysis-skill
description: A股上市公司财务分析，支持财报查询、财务指标计算、财报对比分析
author: 深圳市深维智见教育科技有限公司
version: 1.0.0
license: Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
---

# Financial Analysis Skill

## 简介

财务分析 Skill，提供A股上市公司财务报表查询和分析功能，基于 Tushare 数据源。支持财报数据获取、财务指标计算、财报对比分析。

## 功能特性

- **财务报表查询**：获取利润表、资产负债表、现金流量表
- **财务比率计算**：计算ROE、ROA、毛利率、净利率等关键指标
- **财报对比分析**：支持同比/环比财务数据对比

## 注册的工具

### get_financial_report

获取指定公司的财务报表数据，包括利润表、资产负债表、现金流量表。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码，支持多种格式 |
| report_type | string | 是 | 报表类型：income(利润表)、balance(资产负债表)、cashflow(现金流量表) |
| period | string | 否 | 报告期，格式YYYYMMDD，如20231231 |
| report_count | integer | 否 | 返回报告期数量，默认1，最多10期 |

**返回数据（利润表）：**
```json
{
  "symbol": "600519.SH",
  "report_type": "利润表",
  "reports": [{
    "total_revenue": "1505.60",
    "net_income": "747.34",
    "basic_eps": "59.49"
  }]
}
```

**返回数据（资产负债表）：**
```json
{
  "total_assets": "2727.00",
  "total_liabilities": "490.66",
  "total_equity": "2236.34"
}
```

**返回数据（现金流量表）：**
```json
{
  "operating_cashflow": "665.93",
  "investing_cashflow": "-35.28",
  "financing_cashflow": "-573.64"
}
```

### calculate_financial_ratios

计算关键财务指标和比率，包括盈利能力、偿债能力、增长能力、现金流指标。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码 |
| period | string | 否 | 报告期，格式YYYYMMDD |

**计算指标：**
- **盈利能力**：EPS、ROE、ROA、毛利率、净利率
- **偿债能力**：资产负债率、流动比率、速动比率
- **增长能力**：营收增长率、净利润增长率
- **现金流**：经营活动现金流/营收比

**返回示例：**
```json
{
  "symbol": "600519.SH",
  "ratios": {
    "roe": "25.36%",
    "gross_profit_margin": "91.96%",
    "net_profit_margin": "52.49%",
    "debt_to_assets": "17.99%"
  },
  "summary": "ROE 25.36%（优秀）；毛利率 91.96%；净利率 52.49%；资产负债率 17.99%（低风险）"
}
```

### compare_financial_data

对比分析财务数据的同比/环比变化，支持营收、净利润、ROE、ROA等指标对比。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码 |
| indicator | string | 是 | 对比指标：revenue(营收)、net_profit(净利润)、roe(ROE)、roa(ROA) |
| periods | integer | 否 | 对比期数，默认4，用于计算同比/环比 |

**返回示例：**
```json
{
  "indicator": "营业总收入",
  "data_points": [
    {"end_date": "20241231", "value": 15056000},
    {"end_date": "20240930", "value": 12076000}
  ],
  "qoq_comparisons": [
    {
      "current_period": "20241231",
      "previous_period": "20240930",
      "change": "24.68%",
      "trend": "上升"
    }
  ],
  "yoy_comparisons": [...],
  "summary": "营业总收入最新值为1505.60万元，环比上升24.68%"
}
```

## 使用示例

```python
from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill

skill = FinancialAnalysisSkill()

# 获取利润表
result = await skill.get_financial_report(
    symbol="600519",
    report_type="income",
    report_count=4
)

# 计算财务比率
result = await skill.calculate_financial_ratios("600519")

# 对比营收数据
result = await skill.compare_financial_data(
    symbol="600519",
    indicator="revenue",
    periods=8
)
```

## 依赖

- Tushare API
- `TUSHARE_API_TOKEN` 环境变量
- pandas（数据处理）

## 目录结构

```
financial-analysis-skill/
├── SKILL.md              # 本文件
├── scripts/              # 可选：脚本文件
├── references/           # 可选：参考文档
└── assets/              # 可选：静态资源
```

## 源码位置

实际代码位于：`../financial_analysis.py`
