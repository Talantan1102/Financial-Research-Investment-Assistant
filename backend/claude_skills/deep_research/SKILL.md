---
name: deep_research
description: |
  深度研报生成，综合多维度数据生成研究报告。
  
  Use this skill when:
  - User asks for comprehensive research report on a stock
  - User wants industry analysis report
  - User needs comparison report between multiple stocks
  - User wants in-depth analysis combining market, financial, and valuation data
  
  Data Source: Tushare Pro API
version: "1.0"
tool_count: 3
---

# DeepResearch Skill

## Overview

提供深度研究报告生成能力，综合股票基础信息、行情数据、财务指标、行业数据等多维度信息，生成专业的研究报告。

**Data Source**: Tushare Pro API  
**Coverage**: A-shares (Shanghai, Shenzhen)  
**Report Types**: Stock research, industry analysis, comparison reports  
**Total Tools**: 3

---

## Available Tools

### 1. generate_stock_report - 生成个股深度研报

**Purpose**: 生成个股深度研究报告，综合财务、估值、行业等多维度数据。

**When to use**:
- User asks "分析一下茅台"
- User wants comprehensive stock research report
- Need valuation, financial, and market data synthesis

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| report_type | string | No | comprehensive | 报告类型：comprehensive(综合), valuation(估值), financial(财务) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "report_type": "comprehensive",
    "generated_at": "2026-03-20",
    "sections": {
      "company_overview": {
        "name": "贵州茅台",
        "fullname": "贵州茅台酒股份有限公司",
        "industry": "白酒",
        "area": "贵州",
        "list_date": "20010827",
        "introduction": "公司是国内白酒行业的龙头企业..."
      },
      "valuation": {
        "pe": 28.74,
        "pe_ttm": 27.5,
        "pb": 8.56,
        "ps": 12.34,
        "total_mv": 2325000000000,
        "assessment": "合理"
      },
      "financial": {
        "roe": 32.58,
        "roa": 22.45,
        "gross_margin": 91.23,
        "debt_to_assets": 25.34,
        "trend_roe": [32.58, 31.2, 30.5, 29.8]
      },
      "market": {
        "current_price": "1850.50",
        "change_percent": "1.39",
        "volume": "125000"
      }
    }
  }
}
```

**Examples**:
- Comprehensive report: `generate_stock_report(symbol="600519")`
- Valuation focus: `generate_stock_report(symbol="600519", report_type="valuation")`
- Financial focus: `generate_stock_report(symbol="000858", report_type="financial")`

---

### 2. generate_industry_report - 生成行业深度研报

**Purpose**: 生成行业深度研究报告。

**When to use**:
- User asks "分析一下白酒行业"
- User wants industry investment research
- Need industry leaders and valuation comparison

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| industry | string | Yes | - | 行业名称 (e.g., '白酒', '银行') |
| focus | string | No | overview | 分析重点：overview(全景), leaders(龙头), valuation(估值), trend(趋势) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "industry": "白酒",
    "focus": "overview",
    "generated_at": "2026-03-20",
    "sections": {
      "leaders": {
        "top_companies": [
          {"ts_code": "600519.SH", "name": "贵州茅台"},
          {"ts_code": "000858.SZ", "name": "五粮液"}
        ],
        "leader_count": 18
      },
      "valuation": {
        "industry": "白酒",
        "pe_ttm": 35.8,
        "pb": 8.5,
        "ps": 12.3,
        "stock_count": 18
      },
      "performance": {
        "industry": "白酒",
        "avg_change": -1.2,
        "rank": 45
      }
    }
  }
}
```

**Examples**:
- Industry overview: `generate_industry_report(industry="白酒")`
- Focus on leaders: `generate_industry_report(industry="银行", focus="leaders")`
- Valuation analysis: `generate_industry_report(industry="半导体", focus="valuation")`

---

### 3. generate_comparison_report - 生成对比分析报告

**Purpose**: 生成股票对比分析报告。

**When to use**:
- User asks "茅台和五粮液哪个更好？"
- User wants to compare multiple stocks
- Need side-by-side valuation and profitability analysis

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbols | array | Yes | - | 股票代码列表，如['600519', '000858'] |
| dimensions | array | No | null | 对比维度：valuation(估值), profitability(盈利), growth(成长), risk(风险) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbols": ["600519", "000858"],
    "dimensions": ["valuation", "profitability", "risk"],
    "generated_at": "2026-03-20",
    "data": {
      "600519": {
        "name": "贵州茅台",
        "industry": "白酒",
        "valuation": {
          "pe": 28.74,
          "pb": 8.56,
          "total_mv": 2325000000000
        },
        "profitability": {
          "roe": 32.58,
          "gross_margin": 91.23,
          "net_margin": 53.56
        }
      },
      "000858": {
        "name": "五粮液",
        "industry": "白酒",
        "valuation": {
          "pe": 22.5,
          "pb": 6.2,
          "total_mv": 850000000000
        },
        "profitability": {
          "roe": 25.8,
          "gross_margin": 75.42,
          "net_margin": 38.5
        }
      }
    },
    "summary": {
      "lowest_pe": ["000858", 22.5],
      "highest_roe": ["600519", 32.58]
    }
  }
}
```

**Examples**:
- Two stocks: `generate_comparison_report(symbols=["600519", "000858"])`
- With dimensions: `generate_comparison_report(symbols=["600519", "000858", "000568"], dimensions=["valuation", "profitability"])`
- Multiple stocks: `generate_comparison_report(symbols=["300750", "002594", "601012"])`

---

## Common Workflows

### Workflow 1: Single Stock Research
```
User: "深度分析一下贵州茅台"

→ generate_stock_report(symbol="600519", report_type="comprehensive")
   → Get company overview, valuation, financial, market data

→ Response: "贵州茅台深度分析报告
   【公司概况】国内白酒行业龙头...
   【估值分析】当前PE 28.74倍，处于合理区间...
   【财务状况】ROE 32.58%，盈利能力优秀..."
```

### Workflow 2: Industry Analysis
```
User: "分析一下银行行业的投资机会"

→ generate_industry_report(industry="银行", focus="overview")
   → Get industry leaders, valuation, performance

→ Response: "银行行业分析报告
   【行业概况】A股上市银行42家...
   【估值水平】行业平均PE 5.2倍，处于历史低位...
   【龙头股】招商银行、平安银行..."
```

### Workflow 3: Stock Comparison
```
User: "对比一下茅台和五粮液"

→ generate_comparison_report(symbols=["600519", "000858"], dimensions=["valuation", "profitability"])
   → Side-by-side comparison

→ Response: "茅台 vs 五粮液 对比分析
   【估值】茅台PE 28.74倍 vs 五粮液22.5倍
   【盈利】茅台ROE 32.58% vs 五粮液25.8%
   【结论】茅台盈利能力更强，五粮液估值更低..."
```

### Workflow 4: Portfolio Research
```
User: "我想投资新能源赛道，分析一下"

→ Step 1: generate_industry_report(industry="新能源", focus="overview")
   → Understand industry landscape

→ Step 2: generate_comparison_report(symbols=["300750", "002594", "601012"])
   → Compare top stocks

→ Step 3: For selected stocks, call generate_stock_report()
   → Deep dive on finalists

→ Response: Comprehensive investment research report
```

---

## Important Notes

### 1. Report Types
| Type | Description | Best For |
|------|-------------|----------|
| comprehensive | 综合报告 | Complete overview |
| valuation | 估值分析 | Focus on PE/PB/PS |
| financial | 财务分析 | Focus on ROE, margins |

### 2. Focus Options
| Focus | Description |
|-------|-------------|
| overview | 全景分析 | Complete industry picture |
| leaders | 龙头股 | Focus on top companies |
| valuation | 估值分析 | Industry valuation metrics |
| trend | 趋势分析 | Performance trends |

### 3. Comparison Dimensions
| Dimension | Metrics Included |
|-----------|------------------|
| valuation | PE, PB, PS, market cap |
| profitability | ROE, gross margin, net margin |
| growth | Revenue growth, profit growth |
| risk | Volatility, debt ratio |

### 4. Data Completeness
- Reports may have null values if data is unavailable
- Some sections may be omitted if no data exists
- Financial data based on latest quarterly/annual reports
- Market data reflects most recent trading day

### 5. Error Handling
All tools return standardized response:
```json
{"success": true, "data": {...}}    // Success
{"success": false, "error": "股票代码不能为空"}   // Missing symbol
{"success": false, "error": "行业名称不能为空"}   // Missing industry
{"success": false, "error": "请提供至少2只股票进行对比"}   // Need 2+ stocks for comparison
```

### 6. Best Practices
- Use `generate_stock_report` for comprehensive single-stock analysis
- Use `generate_industry_report` to understand sector landscape
- Use `generate_comparison_report` for investment decision between options
- Combine with other skills (market_data, financial_analysis) for additional details
- Always check `success` field before using data

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-20  
**Compatible with**: AgentFlow v1.0, MCP Protocol
