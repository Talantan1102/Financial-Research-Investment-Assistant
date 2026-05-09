---
name: financial_analysis
description: |
  财务报表分析，计算ROE、ROA、毛利率、净利率等财务指标。
  
  Use this skill when:
  - User asks about company financial reports or statements
  - User wants to calculate financial ratios (ROE, ROA, margins, debt ratios)
  - User asks about profitability, solvency, or growth analysis
  - User wants income statement, balance sheet, or cash flow data
  - User needs financial indicator time series
  
  Data Source: Tushare Pro API
version: "1.0"
tool_count: 7
---

# FinancialAnalysis Skill

## Overview

提供A股上市公司财务报表分析能力，支持三张报表查询、核心财务指标计算、盈利能力和偿债能力分析。

**Data Source**: Tushare Pro API  
**Markets**: A-shares (Shanghai, Shenzhen)  
**Report Types**: Income Statement, Balance Sheet, Cash Flow Statement  
**Update Frequency**: Quarterly (Q1, Q2/Q3, Annual)  
**Total Tools**: 7

---

## Available Tools

### 1. calculate_financial_ratios - 计算财务比率

**Purpose**: 计算ROE、ROA、毛利率、净利率、资产负债率等核心财务指标。

**When to use**:
- User asks "What's the ROE of this company?"
- User wants quick financial health overview
- Need key ratios in one call

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码，如'600519'或'600519.SH' |
| period | string | No | null | 报告期，如'20231231'，不填则取最新 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "period": "20231231",
    "roe": 32.58,
    "roe_dt": 31.2,
    "roa": 22.45,
    "gross_margin": 91.23,
    "net_profit_margin": 53.56,
    "debt_to_assets": 25.34,
    "current_ratio": 4.52,
    "quick_ratio": 4.21,
    "inventory_turnover": 0.32,
    "receivables_turnover": 85.5,
    "assets_turnover": 0.42
  }
}
```

**Examples**:
- Latest ratios: `calculate_financial_ratios(symbol="600519")`
- Specific period: `calculate_financial_ratios(symbol="600519", period="20231231")`

---

### 2. get_income_statement - 获取利润表

**Purpose**: 获取利润表数据，包括营收、成本、利润等。

**When to use**:
- User asks for income statement data
- User wants revenue and profit details
- Analyzing cost structure

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| start_date | string | No | null | 开始日期，格式YYYYMMDD |
| end_date | string | No | null | 结束日期，格式YYYYMMDD |

**Returns**:
```json
{
  "success": true,
  "data": [
    {
      "ts_code": "600519.SH",
      "end_date": "20231231",
      "total_revenue": 15173000.0,
      "revenue": 15173000.0,
      "operate_profit": 9521000.0,
      "total_profit": 9628000.0,
      "n_income": 8127000.0,
      "n_income_attr_p": 8127000.0,
      "basic_eps": 6.47,
      "diluted_eps": 6.47
    }
  ],
  "meta": {"count": 1}
}
```

**Examples**:
- Latest: `get_income_statement(symbol="600519")`
- Date range: `get_income_statement(symbol="600519", start_date="20230101", end_date="20231231")`

---

### 3. get_balance_sheet - 获取资产负债表

**Purpose**: 获取资产负债表数据，包括资产、负债、股东权益等。

**When to use**:
- User asks for balance sheet data
- User wants assets and liabilities breakdown
- Analyzing financial structure

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| start_date | string | No | null | 开始日期，格式YYYYMMDD |
| end_date | string | No | null | 结束日期，格式YYYYMMDD |

**Returns**:
```json
{
  "success": true,
  "data": [
    {
      "ts_code": "600519.SH",
      "end_date": "20231231",
      "total_assets": 28000000.0,
      "total_cur_assets": 20000000.0,
      "total_nca": 8000000.0,
      "total_liab": 7000000.0,
      "total_cur_liab": 4500000.0,
      "total_ncl": 2500000.0,
      "total_hldr_eqy_exc_min_int": 21000000.0
    }
  ],
  "meta": {"count": 1}
}
```

**Examples**:
- Latest: `get_balance_sheet(symbol="600519")`
- Date range: `get_balance_sheet(symbol="600519", start_date="20230101", end_date="20231231")`

---

### 4. get_cash_flow - 获取现金流量表

**Purpose**: 获取现金流量表数据，包括经营、投资、筹资活动现金流。

**When to use**:
- User asks for cash flow statement
- User wants to analyze cash generation ability
- Checking operating cash flow health

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| start_date | string | No | null | 开始日期，格式YYYYMMDD |
| end_date | string | No | null | 结束日期，格式YYYYMMDD |

**Returns**:
```json
{
  "success": true,
  "data": [
    {
      "ts_code": "600519.SH",
      "end_date": "20231231",
      "n_cashflow_act": 6500000.0,
      "n_cashflow_inv_act": -500000.0,
      "n_cashflow_fnc_act": -2000000.0,
      "c_cash_equ_end_period": 60000000.0,
      "c_cash_equ_beg_period": 55500000.0
    }
  ],
  "meta": {"count": 1}
}
```

**Key Fields**:
| Field | Description | Unit |
|-------|-------------|------|
| n_cashflow_act | 经营活动现金流净额 | 10k CNY |
| n_cashflow_inv_act | 投资活动现金流净额 | 10k CNY |
| n_cashflow_fnc_act | 筹资活动现金流净额 | 10k CNY |

**Examples**:
- Latest: `get_cash_flow(symbol="600519")`
- Date range: `get_cash_flow(symbol="600519", start_date="20230101", end_date="20231231")`

---

### 5. get_fina_indicator - 获取财务指标

**Purpose**: 获取一站式财务指标数据，包含ROE、ROA、毛利率等100+指标。

**When to use**:
- User wants comprehensive financial indicators
- User needs time series of financial metrics
- Quick access to all key ratios

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| start_date | string | No | null | 开始日期，格式YYYYMMDD |
| end_date | string | No | null | 结束日期，格式YYYYMMDD |

**Returns**:
```json
{
  "success": true,
  "data": [
    {
      "ts_code": "600519.SH",
      "end_date": "20231231",
      "roe": 32.58,
      "roa": 22.45,
      "gross_margin": 91.23,
      "netprofit_margin": 53.56,
      "debt_to_assets": 25.34,
      "current_ratio": 4.52,
      "quick_ratio": 4.21,
      "cash_ratio": 3.85,
      "ar_turn": 85.5,
      "inv_turn": 0.32,
      "assets_turn": 0.42
    }
  ],
  "meta": {"count": 1}
}
```

**Examples**:
- Latest: `get_fina_indicator(symbol="600519")`
- Time series: `get_fina_indicator(symbol="600519", start_date="20200101", end_date="20231231")`

---

### 6. analyze_profitability - 分析盈利能力

**Purpose**: 分析公司盈利能力，包括毛利率、净利率、ROE趋势等。

**When to use**:
- User asks about profitability trends
- User wants multi-period profit analysis
- Analyzing earnings quality

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| periods | integer | No | 8 | 分析期数（季度），默认8个季度 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "avg_roe": 31.2,
    "avg_gross_margin": 90.8,
    "roe_trend": "up",
    "trends": [
      {"period": "20231231", "roe": 32.58, "gross_margin": 91.23},
      {"period": "20230930", "roe": 31.8, "gross_margin": 91.1}
    ],
    "assessment": "优秀"
  }
}
```

**Assessment Levels**:
| Level | Criteria |
|-------|----------|
| 优秀 | ROE > 20% |
| 良好 | ROE 15-20% |
| 一般 | ROE 10-15% |
| 较弱 | ROE < 10% |

**Examples**:
- Default 8 quarters: `analyze_profitability(symbol="600519")`
- More periods: `analyze_profitability(symbol="600519", periods=12)`

---

### 7. analyze_solvency - 分析偿债能力

**Purpose**: 分析公司偿债能力，包括流动比率、速动比率、资产负债率等。

**When to use**:
- User asks about financial health and debt levels
- User wants solvency analysis
- Checking debt repayment ability

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| period | string | No | null | 报告期，如'20231231'，不填则取最新 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "period": "20231231",
    "current_ratio": 4.52,
    "quick_ratio": 4.21,
    "cash_ratio": 3.85,
    "debt_to_assets": 25.34,
    "debt_to_equity": 0.34,
    "equity_to_debt": 2.94,
    "interest_coverage": 85.5,
    "assessment": "优秀"
  }
}
```

**Assessment Levels**:
| Level | Criteria |
|-------|----------|
| 优秀 | Current ratio > 2 AND debt ratio < 0.5 |
| 良好 | Current ratio > 1.5 AND debt ratio < 0.6 |
| 一般 | Current ratio > 1 AND debt ratio < 0.7 |
| 较弱 | Current ratio < 1 OR debt ratio > 0.7 |

**Examples**:
- Latest: `analyze_solvency(symbol="600519")`
- Specific period: `analyze_solvency(symbol="600519", period="20231231")`

---

## Common Workflows

### Workflow 1: Quick Financial Health Check
```
User: "茅台的财务状况怎么样？"

→ Step 1: calculate_financial_ratios(symbol="600519")
   → Get key ratios

→ Step 2: analyze_profitability(symbol="600519", periods=4)
   → Get profitability assessment

→ Step 3: analyze_solvency(symbol="600519")
   → Get solvency assessment

→ Response: "贵州茅台财务状况：
   【盈利能力】ROE 32.58%，优秀水平
   【偿债能力】资产负债率25.34%，财务状况稳健
   【综合评估】财务健康，盈利能力强"
```

### Workflow 2: Detailed Financial Statement Analysis
```
User: "给我看看茅台最新的三张报表"

→ Step 1: get_income_statement(symbol="600519")
   → Profit/Loss data

→ Step 2: get_balance_sheet(symbol="600519")
   → Assets/Liabilities

→ Step 3: get_cash_flow(symbol="600519")
   → Cash flows

→ Response: Present summarized financial statements
```

### Workflow 3: Trend Analysis
```
User: "茅台近两年的ROE趋势如何？"

→ Step 1: get_fina_indicator(symbol="600519", start_date="20220101")
   → Get historical indicators

→ Step 2: analyze_profitability(symbol="600519", periods=8)
   → Analyze trends

→ Response: "ROE趋势分析：
   - 近两年平均ROE: 31.2%
   - 趋势方向: 上升
   - 最新季度: 32.58%"
```

### Workflow 4: Compare Two Companies
```
User: "对比茅台和五粮液的盈利能力"

→ Step 1: calculate_financial_ratios(symbol="600519")
→ Step 2: calculate_financial_ratios(symbol="000858")
→ Step 3: analyze_profitability(symbol="600519")
→ Step 4: analyze_profitability(symbol="000858")

→ Response: "盈利能力对比：
   茅台ROE 32.58% vs 五粮液25.8%
   茅台毛利率91.23% vs 五粮液75.42%"
```

---

## Important Notes

### 1. Financial Ratio Benchmarks

| Indicator | Excellent | Good | Average | Poor |
|-----------|-----------|------|---------|------|
| ROE | > 20% | 15-20% | 10-15% | < 10% |
| Gross Margin | > 50% | 30-50% | 15-30% | < 15% |
| Net Margin | > 20% | 10-20% | 5-10% | < 5% |
| Debt-to-Assets | < 40% | 40-60% | 60-80% | > 80% |
| Current Ratio | > 2 | 1.5-2 | 1-1.5 | < 1 |

### 2. Report Period Format
- **Standard**: `YYYYMMDD` (e.g., `'20231231'`)
- **Quarter mapping**:
  - Q1: `0331`
  - Q2 (中报): `0630`
  - Q3: `0930`
  - Q4 (年报): `1231`

### 3. Data Units
- Income statement: 10k CNY (万元)
- Balance sheet: 10k CNY (万元)
- Cash flow: 10k CNY (万元)
- Ratios: Percentage or decimal as indicated

### 4. Error Handling
All tools return standardized response:
```json
{"success": true, "data": {...}}    // Success
{"success": false, "error": "股票代码不能为空"}   // Missing symbol
{"success": false, "error": "未找到财务指标数据"}   // No data available
```

### 5. Best Practices
- Use `calculate_financial_ratios` for quick ratio overview
- Use `get_fina_indicator` for comprehensive metrics
- Use `analyze_profitability` for earnings trends
- Use `analyze_solvency` for debt health check
- Use individual statement tools for detailed line items
- Always check `success` field before using data

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-20  
**Compatible with**: AgentFlow v1.0, MCP Protocol

## Available scripts

- `scripts/calculate_dcf.py` — 计算自由现金流贴现 (DCF) 估值, 输入 FCF 列表 + WACC + 永续增长率 + 总股本 + 净负债, 输出企业价值/股权价值/每股价值。
