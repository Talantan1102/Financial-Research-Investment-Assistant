---
name: sector_analysis
description: |
  行业与概念板块分析，支持行业对比、龙头识别、估值对比。
  
  Use this skill when:
  - User asks about industry analysis or sector performance
  - User wants to compare different industries (e.g., banking vs healthcare)
  - User asks about concept stocks or thematic investing (e.g., AI, EV, chips)
  - User wants to identify leading stocks in an industry
  - User asks about industry valuation (PE, PB comparison)
  - User wants to track market hotspots or sector rotation
  
  Data Source: Tushare Pro API
version: "1.0"
tool_count: 7
---

# SectorAnalysis Skill

## Overview

提供 A 股市场行业分类和概念板块的深度分析能力，包括行业列表、概念板块、成分股查询、行业对比、龙头股识别等。

**Data Source**: Tushare Pro API  
**Coverage**: A-shares industries and concept sectors  
**Update Frequency**: Daily after market close  
**Total Tools**: 7

---

## Available Tools

### 1. get_industry_list - 获取行业列表

**Purpose**: 获取所有行业分类列表。

**When to use**:
- User asks "A股有哪些行业？"
- User wants to see all industry categories
- Starting a research project

**Parameters**: None (no parameters required)

**Returns**:
```json
{
  "success": true,
  "data": [
    {"code": "L72", "name": "白酒"},
    {"code": "J66", "name": "银行"},
    {"code": "C27", "name": "医药制造"}
  ],
  "meta": {"count": 109}
}
```

**Examples**:
- Get all industries: `get_industry_list()`

---

### 2. get_industry_performance - 获取行业表现

**Purpose**: 获取各行业涨跌幅排名。

**When to use**:
- User asks "今天哪个行业表现最好？"
- User wants to track recent sector performance
- Identifying market trends and capital flows

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| period | string | No | 1d | 周期：1d(日), 5d(周), 20d(月) |

**Returns**:
```json
{
  "success": true,
  "data": [
    {"industry": "半导体", "avg_change": 5.2, "stock_count": 67, "rank": 1},
    {"industry": "人工智能", "avg_change": 3.8, "stock_count": 45, "rank": 2},
    {"industry": "白酒", "avg_change": -1.2, "stock_count": 18, "rank": 45}
  ],
  "meta": {"period": "1d", "date": "20260308"}
}
```

**Examples**:
- Daily: `get_industry_performance(period="1d")`
- Weekly: `get_industry_performance(period="5d")`
- Monthly: `get_industry_performance(period="20d")`

---

### 3. get_industry_leaders - 获取行业龙头股

**Purpose**: 获取指定行业的龙头股。

**When to use**:
- User asks "白酒行业龙头股有哪些？"
- User wants to find the biggest players in a sector
- Building a portfolio of industry leaders

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| industry | string | Yes | - | 行业名称，如'白酒'、'银行' |
| by | string | No | market_cap | 排序依据：market_cap(市值), revenue(营收), profit(利润) |
| limit | integer | No | 10 | 返回数量 |

**Returns**:
```json
{
  "success": true,
  "data": [
    {"ts_code": "600519.SH", "name": "贵州茅台", "total_mv": 2325000000000, "rank": 1},
    {"ts_code": "000858.SZ", "name": "五粮液", "total_mv": 850000000000, "rank": 2},
    {"ts_code": "000568.SZ", "name": "泸州老窖", "total_mv": 420000000000, "rank": 3}
  ],
  "meta": {"industry": "白酒", "sort_by": "market_cap", "count": 3}
}
```

**Examples**:
- By market cap: `get_industry_leaders(industry="白酒", by="market_cap")`
- By profit: `get_industry_leaders(industry="银行", by="profit")`
- Top 5: `get_industry_leaders(industry="半导体", limit=5)`

---

### 4. compare_industry_metrics - 对比行业财务指标

**Purpose**: 对比不同行业的财务指标。

**When to use**:
- User asks "银行和保险哪个ROE更高？"
- User wants to find industries with strongest profitability
- Comparing operational efficiency

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| industries | array | No | null | 行业列表，如['白酒', '银行', '医药']，null对比所有行业 |
| metric | string | No | roe | 对比指标：roe, gross_margin, net_margin, debt_ratio |

**Returns**:
```json
{
  "success": true,
  "data": [
    {"industry": "白酒", "avg_value": 25.5, "stock_count": 18, "rank": 1},
    {"industry": "医药", "avg_value": 18.2, "stock_count": 156, "rank": 2},
    {"industry": "新能源", "avg_value": 15.3, "stock_count": 89, "rank": 3},
    {"industry": "银行", "avg_value": 12.1, "stock_count": 42, "rank": 4}
  ],
  "meta": {"metric": "roe", "metric_name": "净资产收益率"}
}
```

**Examples**:
- Compare ROE: `compare_industry_metrics(industries=["白酒", "银行", "医药"], metric="roe")`
- Compare margins: `compare_industry_metrics(metric="gross_margin")`
- All industries: `compare_industry_metrics()`

---

### 5. compare_industry_valuation - 对比行业估值

**Purpose**: 对比不同行业的估值水平(PE、PB、PS)。

**When to use**:
- User asks "哪些行业目前估值较低？"
- User wants to know if a sector is expensive
- Comparing valuation multiples

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| industries | array | No | null | 行业列表，null对比所有行业 |

**Returns**:
```json
{
  "success": true,
  "data": [
    {"industry": "银行", "pe_ttm": 5.2, "pb": 0.8, "ps": 2.1, "stock_count": 42},
    {"industry": "医药", "pe_ttm": 28.5, "pb": 3.2, "ps": 4.5, "stock_count": 156},
    {"industry": "白酒", "pe_ttm": 35.8, "pb": 8.5, "ps": 12.3, "stock_count": 18}
  ],
  "meta": {"count": 3, "date": "20260308"}
}
```

**Examples**:
- Specific industries: `compare_industry_valuation(industries=["银行", "保险", "白酒"])`
- All industries: `compare_industry_valuation()`

---

### 6. get_concept_list - 获取概念列表

**Purpose**: 获取所有概念分类列表。

**When to use**:
- User asks about concept sectors
- User wants to find hot themes like "AI", "new energy"
- Researching market hotspots

**Parameters**: None (no parameters required)

**Returns**:
```json
{
  "success": true,
  "data": [
    {"code": "TS0", "name": "国产芯片"},
    {"code": "TS1", "name": "人工智能"},
    {"code": "TS2", "name": "新能源汽车"}
  ],
  "meta": {"count": 385}
}
```

**Examples**:
- Get all concepts: `get_concept_list()`

---

### 7. get_concept_stocks - 获取概念成分股

**Purpose**: 获取指定概念的成分股。

**When to use**:
- User asks "人工智能板块有哪些股票？"
- User wants to find all stocks related to a theme
- Building a thematic portfolio

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| concept_code | string | No | null | 概念代码 |
| concept_name | string | No | null | 概念名称，如'人工智能'、'新能源汽车' |

**Note**: Provide either `concept_code` or `concept_name`, not both.

**Returns**:
```json
{
  "success": true,
  "data": [
    {"ts_code": "603986.SH", "name": "兆易创新"},
    {"ts_code": "688981.SH", "name": "中芯国际"}
  ],
  "meta": {"concept": "国产芯片", "code": "TS0", "count": 67}
}
```

**Examples**:
- By code: `get_concept_stocks(concept_code="TS0")`
- By name: `get_concept_stocks(concept_name="国产芯片")`
- By name: `get_concept_stocks(concept_name="人工智能")`

---

## Common Workflows

### Workflow 1: Find Undervalued Quality Industries
```
User: "哪些行业目前估值较低？"

→ Step 1: compare_industry_metrics(metric="roe")
   → Identify industries with highest ROE

→ Step 2: compare_industry_valuation(industries=["白酒", "医药", "银行"])
   → Compare PE/PB ratios

→ Conclusion: "银行PE 5.2倍（最低），白酒PE 35.8倍（最高）"
```

### Workflow 2: Track Market Hotspots
```
User: "最近市场热点是什么？"

→ get_industry_performance(period="5d")
   → Find: 半导体 +8.5%, 人工智能 +6.2%

→ get_concept_stocks(concept_name="半导体")
   → Get constituent stocks

→ Response: Report on trending sectors
```

### Workflow 3: Industry Comparison Analysis
```
User: "对比银行和保险行业"

→ Step 1: compare_industry_metrics(industries=["银行", "保险"], metric="roe")
→ Step 2: compare_industry_valuation(industries=["银行", "保险"])
→ Step 3: get_industry_leaders(industry="银行")
→ Step 4: get_industry_leaders(industry="保险")

→ Synthesize comparison
```

### Workflow 4: Concept Stock Research
```
User: "人工智能板块有哪些股票？"

→ get_concept_list()
   → Find concept code

→ get_concept_stocks(concept_name="人工智能")
   → Get full list

→ Response: List AI concept stocks
```

---

## Important Notes

### 1. Metric Definitions
| Metric | Full Name | Description |
|--------|-----------|-------------|
| ROE | 净资产收益率 | Return on Equity |
| Gross Margin | 毛利率 | (Revenue - COGS) / Revenue |
| Net Margin | 净利率 | Net Income / Revenue |
| PE | 市盈率 | Price / Earnings |
| PB | 市净率 | Price / Book Value |

### 2. Valuation Interpretation
- **PE < 10**: Typically undervalued (e.g., banking)
- **PE 10-25**: Fair valuation
- **PE 25-40**: Premium valuation
- **PE > 40**: Expensive valuation

### 3. Sort Options for Leaders
| Sort By | Description |
|---------|-------------|
| market_cap | 市值 |
| revenue | 营收 |
| profit | 利润 |

### 4. Error Handling
All tools return standardized response:
```json
{"success": true, "data": {...}}    // Success
{"success": false, "error": "行业名称不能为空"}   // Missing industry
{"success": false, "error": "请提供概念代码或概念名称"}   // Missing concept
```

### 5. Best Practices
- Start with `get_industry_list()` or `get_concept_list()` if unsure of names
- Use specific industry lists for faster results
- Combine with `market_data` skill for detailed analysis

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-20  
**Compatible with**: AgentFlow v1.0, MCP Protocol
