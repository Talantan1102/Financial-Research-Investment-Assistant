---
name: market_data
description: |
  股票市场行情数据查询，支持A股实时行情获取。
  
  Use this skill when:
  - User asks about stock prices, market data, or trading information
  - User wants to analyze stock trends or historical performance
  - User needs to look up stock codes or company information
  - User asks about market sentiment (money flow, top gainers/losers)
  - User wants daily valuation metrics (PE, PB, market cap)
  - User asks about northbound capital flow or margin trading
  
  Data Source: Tushare Pro API
version: "1.0"
tool_count: 11
---

# MarketData Skill

## Overview

提供全面的股票市场行情数据查询能力，基于 Tushare Pro API。支持实时行情、历史K线、龙虎榜、资金流向、涨跌停统计、北向资金、融资融券等数据。

**Data Source**: Tushare Pro API  
**Markets**: A-shares (Shanghai/Shenzhen)  
**Update Frequency**: Near real-time (~15 min delay)  
**Total Tools**: 11

---

## Available Tools

### 1. get_quote - 获取股票实时行情

**Purpose**: 获取指定股票的实时行情数据，包括当前价格、涨跌幅、成交量等信息。

**When to use**:
- User asks "茅台股价多少？"
- User wants current stock price and daily change
- User asks about trading volume or turnover

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | 股票代码，支持多种格式：'600519'(纯数字)、'sh600519'(带市场前缀)、'600519.SH'(Tushare格式) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "gid": "sh600519",
    "ts_code": "600519.SH",
    "name": "贵州茅台",
    "nowPri": "1850.50",
    "increase": "25.30",
    "increPer": "1.39",
    "todayStartPri": "1840.00",
    "yestodEndPri": "1825.20",
    "todayMax": "1865.00",
    "todayMin": "1835.00",
    "traAmount": "125000",
    "traNumber": "231250000",
    "update_time": "20260308"
  }
}
```

**Examples**:
- Query Kweichow Moutai: `get_quote(symbol="600519")`
- With prefix: `get_quote(symbol="sh600519")`

---

### 2. search_stock - 搜索股票

**Purpose**: 根据股票代码或名称关键词搜索股票信息。

**When to use**:
- User asks about a company but doesn't know the stock code
- User mentions company name like "茅台" or "贵州茅台"
- Searching for stocks

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| keyword | string | Yes | 搜索关键词，可以是股票代码（如'600519'）或股票名称（如'贵州茅台'） |

**Returns**:
```json
{
  "success": true,
  "data": {
    "results": [{...}],
    "count": 1
  }
}
```

**Examples**:
- Search by code: `search_stock(keyword="600519")`
- Search by name: `search_stock(keyword="贵州茅台")`

---

### 3. get_history - 获取历史K线数据

**Purpose**: 获取股票历史K线数据，支持日线、周线、月线。

**When to use**:
- User asks "茅台最近一个月走势如何？"
- User wants historical prices for technical analysis
- User asks about stock performance in a specific period

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码，如'600519'或'600519.SH' |
| period | string | No | daily | 周期类型：daily(日线)、weekly(周线)、monthly(月线) |
| start_date | string | No | null | 开始日期，格式YYYYMMDD |
| end_date | string | No | null | 结束日期，格式YYYYMMDD |
| limit | integer | No | 100 | 返回数据条数限制 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "records": [
      {
        "trade_date": "20260308",
        "open": "1840.00",
        "high": "1865.00",
        "low": "1835.00",
        "close": "1850.50",
        "volume": "125000",
        "amount": "231250000"
      }
    ],
    "meta": {
      "count": 1,
      "period": "daily"
    }
  }
}
```

**Examples**:
- Last 30 days: `get_history(symbol="600519", limit=30)`
- Weekly: `get_history(symbol="600519", period="weekly", limit=52)`
- Date range: `get_history(symbol="600519", start_date="20240101", end_date="20240301")`

---

### 4. get_stock_basic_info - 获取股票基础信息

**Purpose**: 获取股票基础信息（行业、地区、上市日期等）。

**When to use**:
- User asks "茅台属于什么行业？"
- User wants to know when a company went public
- User asks about company's region or market

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | 股票代码 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "ts_code": "600519.SH",
    "name": "贵州茅台",
    "industry": "白酒",
    "area": "贵州",
    "list_date": "20010827",
    "market": "主板",
    "exchange": "SSE"
  }
}
```

**Examples**:
- Basic info: `get_stock_basic_info(symbol="600519")`

---

### 5. get_top_list - 获取龙虎榜数据

**Purpose**: 获取龙虎榜每日明细，包含机构买卖数据。

**When to use**:
- User asks "今天有哪些股票上了龙虎榜？"
- User wants to know institutional activity on hot stocks

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| trade_date | string | No | null | 交易日期，格式YYYYMMDD，默认最近交易日 |
| limit | integer | No | 50 | 返回条数限制 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "records": [...],
    "meta": {"count": 50, "trade_date": "20260308"}
  }
}
```

**Examples**:
- Latest: `get_top_list()`
- Specific date: `get_top_list(trade_date="20260308")`

---

### 6. get_money_flow - 获取资金流向

**Purpose**: 获取个股资金流向数据（主力、散户净流入等）。

**When to use**:
- User asks "茅台今天的资金流向如何？"
- User wants to know if institutions are buying or selling
- User asks about main force (主力) movements

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| trade_date | string | No | null | 交易日期，格式YYYYMMDD |
| start_date | string | No | null | 开始日期，格式YYYYMMDD |
| end_date | string | No | null | 结束日期，格式YYYYMMDD |

**Returns**:
```json
{
  "success": true,
  "data": {
    "records": [
      {
        "trade_date": "20260308",
        "ts_code": "600519.SH",
        "net_mf_amount": 231250000,
        "buy_lg_vol": 8000.0,
        "sell_lg_vol": 5000.0
      }
    ],
    "meta": {"symbol": "600519"}
  }
}
```

**Examples**:
- Single day: `get_money_flow(symbol="600519")`
- Date range: `get_money_flow(symbol="600519", start_date="20240301", end_date="20240308")`

---

### 7. get_limit_list - 获取涨跌停统计

**Purpose**: 获取每日涨跌停统计。

**When to use**:
- User asks "今天有多少只股票涨停？"
- User wants market sentiment overview

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| trade_date | string | No | null | 交易日期，格式YYYYMMDD，默认最近交易日 |
| limit_type | string | No | null | 涨跌停类型：U(涨停)、D(跌停)，默认全部 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "records": [...],
    "meta": {"count": 100, "trade_date": "20260308"}
  }
}
```

**Examples**:
- All: `get_limit_list()`
- Limit up only: `get_limit_list(limit_type="U")`
- Limit down only: `get_limit_list(limit_type="D")`

---

### 8. get_company_info - 获取公司详细信息

**Purpose**: 获取上市公司详细信息（公司简介、联系方式、办公地址等）。

**When to use**:
- User asks "茅台公司是做什么的？"
- User wants company background or contact information

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | 股票代码 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "ts_code": "600519.SH",
    "name": "贵州茅台",
    "fullname": "贵州茅台酒股份有限公司",
    "industry": "白酒",
    "area": "贵州",
    "list_date": "20010827",
    "introduction": "公司是国内白酒行业的龙头企业...",
    "website": "www.moutaichina.com",
    "email": "ir@moutaichina.com",
    "address": "贵州省仁怀市茅台镇"
  }
}
```

**Examples**:
- Company info: `get_company_info(symbol="600519")`

---

### 9. get_daily_basic - 获取每日指标

**Purpose**: 获取每日指标数据，包括PE、PB、PS、换手率、总市值、流通市值等估值指标。

**When to use**:
- User asks "茅台的PE是多少？"
- User wants market cap or valuation information
- User asks about turnover rate or liquidity

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | No | null | 股票代码，不填写则返回全市场数据 |
| trade_date | string | No | null | 交易日期，格式YYYYMMDD，默认最近交易日 |

**Returns**:
```json
{
  "success": true,
  "data": [
    {
      "ts_code": "600519.SH",
      "trade_date": "20260308",
      "pe": 28.74,
      "pe_ttm": 27.5,
      "pb": 8.56,
      "ps": 12.34,
      "total_mv": 2325000000000,
      "circ_mv": 2325000000000,
      "turnover_rate": 0.52
    }
  ],
  "meta": {"count": 1}
}
```

**Examples**:
- Single stock: `get_daily_basic(symbol="600519")`
- All stocks: `get_daily_basic(trade_date="20260308")`

---

### 10. get_north_money - 获取北向资金

**Purpose**: 获取沪深港通资金流向（北向资金），追踪外资流入流出情况。

**When to use**:
- User asks "北向资金今天流入了多少？"
- User wants to track foreign institutional investment in A-shares

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| start_date | string | No | null | 开始日期，格式YYYYMMDD |
| end_date | string | No | null | 结束日期，格式YYYYMMDD |

**Returns**:
```json
{
  "success": true,
  "data": [
    {
      "trade_date": "20260308",
      "north_money": 521250000,
      "south_money": -123450000
    }
  ],
  "meta": {"count": 1}
}
```

**Examples**:
- Latest: `get_north_money()`
- Date range: `get_north_money(start_date="20240301", end_date="20240308")`

---

### 11. get_margin - 获取融资融券

**Purpose**: 获取融资融券数据，包括融资余额、融券余额、融资买入额等。

**When to use**:
- User asks about margin balance or leverage data
- User wants to understand market leverage sentiment

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | No | null | 股票代码，不填写则返回全市场数据 |
| start_date | string | No | null | 开始日期，格式YYYYMMDD |
| end_date | string | No | null | 结束日期，格式YYYYMMDD |

**Returns**:
```json
{
  "success": true,
  "data": [
    {
      "trade_date": "20260308",
      "ts_code": "600519.SH",
      "rzye": 1250000000,
      "rqye": 85000000,
      "rzmre": 125000000
    }
  ],
  "meta": {"count": 1}
}
```

**Examples**:
- Single stock: `get_margin(symbol="600519")`
- Market-wide: `get_margin()`

---

## Common Workflows

### Workflow 1: Quick Stock Price Check
```
User: "茅台股价多少？"
→ get_quote(symbol="600519")
→ Response: "贵州茅台 (600519.SH) 当前价格 ¥1,850.50，今日上涨 1.39%"
```

### Workflow 2: Stock Search → Price Check
```
User: "茅台今天的股价"
→ search_stock(keyword="茅台")
→ get_quote(symbol="600519")
```

### Workflow 3: Historical Trend Analysis
```
User: "茅台最近一个月走势如何？"
→ get_history(symbol="600519", limit=30)
→ Analyze trend
```

### Workflow 4: Comprehensive Stock Analysis
```
User: "分析一下茅台"
→ get_quote(symbol="600519")
→ get_stock_basic_info(symbol="600519")
→ get_daily_basic(symbol="600519")
→ get_money_flow(symbol="600519")
→ get_company_info(symbol="600519")
→ Synthesize analysis
```

---

## Important Notes

### 1. Stock Symbol Format
- **Recommended**: Pure 6-digit code ('600519')
- **Also supported**: Tushare format ('600519.SH')
- **Also supported**: Prefixed format ('sh600519')

### 2. Date Format
- **Standard**: `YYYYMMDD` (e.g., '20260308')
- **No separators**: Do NOT use '2026-03-08' or '2026/03/08'

### 3. Data Timeliness
- Real-time data: ~15 minutes delay
- Daily metrics: Updated after market close
- Historical data: Available for all trading days

### 4. Error Handling
All tools return standardized response:
```json
{"success": true, "data": {...}}    // Success
{"success": false, "error": "股票代码不能为空"}   // Failure
```

### 5. Best Practices
- Always check `success` field before using data
- Use pure 6-digit code for simplicity
- Format numbers with thousand separators for display

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-20  
**Compatible with**: AgentFlow v1.0, MCP Protocol
