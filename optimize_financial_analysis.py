#!/usr/bin/env python3
"""
7个Skill全面优化 - Part 2: Financial Analysis
"""

from pathlib import Path

FINANCIAL_ANALYSIS_SKILL = """---
name: financial_analysis
description: |
  A股上市公司财务分析 Skill，提供财务报表查询、财务指标计算、财务数据对比分析能力。
  
  Use this skill when:
  - User asks about company financial reports (income statement, balance sheet, cash flow)
  - User wants to calculate financial ratios (ROE, ROA, profit margins, etc.)
  - User asks to compare financial performance over time or between companies
  - User needs to assess company's financial health or profitability
  
  Data Source: Tushare Pro API
  Coverage: A-shares (Shanghai, Shenzhen)
  Report Types: Income statement, Balance sheet, Cash flow statement
version: "1.0"
tool_count: 7
---

# FinancialAnalysis Skill

## Overview

提供A股上市公司全面的财务分析能力，基于Tushare Pro API。支持三张财务报表查询、关键财务指标计算、多期财务数据对比分析。

**Data Source**: Tushare Pro API  
**Coverage**: A-shares (Shanghai, Shenzhen)  
**Report Types**: Income statement, Balance sheet, Cash flow statement  
**Total Tools**: 7

---

## Available Tools

### 1. get_financial_report - Get Financial Report

**Purpose**: Retrieve financial statements (income, balance, cash flow) for a specific company and period.

**When to use**:
- User asks "Show me 茅台's income statement"
- User wants to see balance sheet or cash flow data
- User asks about revenue, profit, or assets for a specific period

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code. Formats: `'600519'`, `'600519.SH'` |
| report_type | string | Yes | - | Report type: `"income"` (利润表), `"balance"` (资产负债表), `"cashflow"` (现金流量表) |
| period | string | No | null | Report period in format `YYYYMMDD` (e.g., `"20231231"`). If null, returns latest report. |
| report_count | integer | No | 1 | Number of report periods to return (1-10). Default 1 returns latest only. |

**Returns** (Income Statement Example):
```json
{
  "symbol": "600519.SH",
  "report_type": "利润表",
  "report_count": 1,
  "reports": [
    {
      "ts_code": "600519.SH",
      "end_date": "20231231",
      "ann_date": "20240328",
      "report_type": "年报",
      "total_revenue": "15173000.00",     // Total revenue (10k CNY)
      "revenue": "15173000.00",           // Operating revenue
      "operate_profit": "9521000.00",     // Operating profit
      "total_profit": "9628000.00",       // Total profit
      "net_income": "8127000.00",         // Net income
      "net_income_parent": "8127000.00",  // Net income attributable to parent
      "basic_eps": "6.4700",              // EPS (CNY)
      "diluted_eps": "6.4700"
    }
  ]
}
```

**Key Fields by Report Type**:

**Income Statement (利润表)**:
- `total_revenue`: Total revenue (万元)
- `operate_profit`: Operating profit (万元)
- `net_income_parent`: Net income to parent (万元)
- `basic_eps`: Basic EPS (元)

**Balance Sheet (资产负债表)**:
- `total_assets`: Total assets (万元)
- `total_liabilities`: Total liabilities (万元)
- `total_equity`: Total equity (万元)

**Cash Flow Statement (现金流量表)**:
- `operating_cashflow`: Operating cash flow (万元)
- `investing_cashflow`: Investing cash flow (万元)
- `financing_cashflow`: Financing cash flow (万元)

**Examples**:
- Latest income statement: `get_financial_report(symbol="600519", report_type="income")`
- Last 4 quarters: `get_financial_report(symbol="600519", report_type="income", report_count=4)`
- Specific period: `get_financial_report(symbol="600519", report_type="balance", period="20231231")`

---

### 2. get_income_statement - Get Income Statement (Convenience Tool)

**Purpose**: Quick access to income statement data. Same as `get_financial_report` with `report_type="income"`.

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code |
| start_date | string | No | null | Start date `YYYYMMDD` for date range query |
| end_date | string | No | null | End date `YYYYMMDD` |

---

### 3. get_balance_sheet - Get Balance Sheet (Convenience Tool)

**Purpose**: Quick access to balance sheet data.

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code |
| start_date | string | No | null | Start date `YYYYMMDD` |
| end_date | string | No | null | End date `YYYYMMDD` |

---

### 4. get_cash_flow - Get Cash Flow Statement (Convenience Tool)

**Purpose**: Quick access to cash flow statement data.

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code |
| start_date | string | No | null | Start date `YYYYMMDD` |
| end_date | string | No | null | End date `YYYYMMDD` |

---

### 5. calculate_financial_ratios - Calculate Financial Ratios

**Purpose**: Calculate key financial ratios including ROE, ROA, profit margins, debt ratios.

**When to use**:
- User asks "What's the ROE of 茅台?"
- User wants profitability or leverage analysis
- User asks about financial health metrics

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code |
| period | string | No | null | Report period `YYYYMMDD`. Null returns latest. |

**Returns**:
```json
{
  "symbol": "600519.SH",
  "ratios": {
    "eps": "6.4700",
    "roe": "32.58%",              // Return on Equity (>15% excellent)
    "roa": "22.45%",              // Return on Assets
    "gross_profit_margin": "91.23%",  // Gross margin
    "net_profit_margin": "53.56%",    // Net margin
    "debt_to_assets": "25.34%",   // Debt ratio (<40% low risk)
    "current_ratio": "4.52",      // Current ratio (>2 good)
    "revenue_yoy": "18.20%",      // Revenue YoY growth
    "net_profit_yoy": "15.89%"    // Profit YoY growth
  },
  "summary": "ROE 32.58% (Excellent); Gross margin 91.23%; Net margin 53.56%; Debt ratio 25.34% (Low risk)"
}
```

**Ratio Interpretation**:

**Profitability Ratios**:
- `roe` (ROE): Return on equity. **>15% excellent**, 10-15% good, <10% average
- `roa` (ROA): Return on assets. Higher is better
- `gross_profit_margin`: Gross margin. **>30% good** for most industries
- `net_profit_margin`: Net margin. **>15% excellent** for most industries

**Solvency Ratios**:
- `debt_to_assets`: Debt ratio. **<40% low risk**, 40-60% medium, >60% high risk
- `current_ratio`: Current ratio. **>2 healthy**, 1.5-2 adequate, <1.5 weak

**Growth Ratios**:
- `revenue_yoy`: Revenue year-over-year growth. **>20% high growth**
- `net_profit_yoy`: Profit YoY growth. **>20% high growth**

**Examples**:
- Latest ratios: `calculate_financial_ratios(symbol="600519")`
- Specific period: `calculate_financial_ratios(symbol="600519", period="20231231")`

---

### 6. compare_financial_data - Compare Financial Data Over Time

**Purpose**: Analyze financial trends by comparing data across multiple periods (QoQ, YoY).

**When to use**:
- User asks "How has 茅台's revenue grown over the past year?"
- User wants trend analysis for a specific metric

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code |
| indicator | string | Yes | - | Metric to compare: `"revenue"`, `"net_profit"`, `"roe"`, `"roa"` |
| periods | integer | No | 4 | Number of periods to compare (2-20). Default 4 gives ~1 year of quarterly data. |

**Returns**:
```json
{
  "symbol": "600519.SH",
  "indicator": "营业总收入",
  "unit": "万元",
  "data_points": [
    {"end_date": "20231231", "value": 15173000.0},
    {"end_date": "20230930", "value": 11245000.0},
    {"end_date": "20230630", "value": 7568000.0},
    {"end_date": "20230331", "value": 3856000.0}
  ],
  "qoq_comparisons": [
    {
      "current_period": "20231231",
      "previous_period": "20230930",
      "change_rate": "34.93%",
      "trend": "上升"
    }
  ],
  "summary": "营业总收入最新值为 15173000.00，环比上升 34.93%。近4期平均增长率为 28.54%"
}
```

**Examples**:
- Revenue trend (4 quarters): `compare_financial_data(symbol="600519", indicator="revenue")`
- ROE trend (8 quarters): `compare_financial_data(symbol="600519", indicator="roe", periods=8)`

---

### 7. get_fina_indicator - Get Financial Indicators (Tushare API)

**Purpose**: Access raw financial indicator data directly from Tushare API.

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code |
| start_date | string | No | null | Start date `YYYYMMDD` |
| end_date | string | No | null | End date `YYYYMMDD` |

---

## Common Workflows

### Workflow 1: Quick Financial Health Check
```
User: "茅台财务状况怎么样？"
→ calculate_financial_ratios(symbol="600519")
→ Response: Summary of ROE, margins, and debt ratio
```

### Workflow 2: Deep Financial Analysis
```
User: "分析茅台的盈利能力"
→ get_financial_report(symbol="600519", report_type="income", report_count=4)
→ calculate_financial_ratios(symbol="600519")
→ Synthesize profitability analysis
```

### Workflow 3: Trend Analysis
```
User: "茅台近一年营收增长如何？"
→ compare_financial_data(symbol="600519", indicator="revenue", periods=4)
→ Show QoQ and YoY growth rates
```

### Workflow 4: Compare Two Companies
```
User: "对比茅台和五粮液的盈利能力"
→ calculate_financial_ratios(symbol="600519")  // 茅台
→ calculate_financial_ratios(symbol="000858")  // 五粮液
→ Compare ROE, gross margin, net margin
```

---

## Important Notes

### 1. Report Period Format
- **Format**: `YYYYMMDD` (e.g., `"20231231"`)
- **Quarter Mapping**:
  - Q1: `0331`
  - Q2: `0630`
  - Q3: `0930`
  - Q4: `1231`

### 2. Financial Ratio Benchmarks

**ROE (净资产收益率)**:
- **>15%**: Excellent
- **10-15%**: Good
- **<10%**: Average

**Debt-to-Assets (资产负债率)**:
- **<40%**: Low risk
- **40-60%**: Medium risk
- **>60%**: High risk

**Current Ratio (流动比率)**:
- **>2**: Healthy
- **1.5-2**: Adequate
- **<1.5**: Weak liquidity

### 3. Unit Conversions
- Financial data in reports: **万元** (10,000 CNY)
- Market cap in market_data: **元** (CNY)
- Be careful when comparing across different data sources

### 4. Data Timing
- Annual reports: Released within 4 months after year-end
- Quarterly reports: Released within 1 month after quarter-end
- Financial ratios: Calculated from latest available data

### 5. Best Practices for Output
```
【财务分析】贵州茅台 (600519) - 2023年报

【盈利能力】优秀
- ROE: 32.58% (行业领先)
- 毛利率: 91.23% (极高)
- 净利率: 53.56% (优秀)

【财务稳健性】极佳
- 资产负债率: 25.34% (低风险)
- 流动比率: 4.52 (充足)

【成长性】良好
- 营收同比: +18.20%
- 净利润同比: +15.89%
```

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-18  
**Compatible with**: AgentFlow v1.0, MCP Protocol
"""


# 保存优化后的 Financial Analysis SKILL.md
def save_skill(skill_name, content):
    skill_dir = Path(
        f"~/.openclaw/workspace-dev/external/financial-research-assistant/backend/claude_skills/{skill_name}"
    ).expanduser()
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"

    # 备份
    if skill_file.exists() and not (skill_dir / "SKILL.md.backup").exists():
        skill_file.rename(skill_dir / "SKILL.md.backup")
        print(f"✅ Backed up {skill_name}/SKILL.md")

    skill_file.write_text(content, encoding="utf-8")
    print(f"✅ Saved optimized {skill_name}/SKILL.md")


if __name__ == "__main__":
    print("=" * 80)
    print("优化 Financial Analysis Skill")
    print("=" * 80)
    save_skill("financial_analysis", FINANCIAL_ANALYSIS_SKILL)
    print("\n优化完成！")
