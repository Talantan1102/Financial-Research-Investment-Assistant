#!/usr/bin/env python3
"""
7个Skill全面优化脚本
基于 Anthropic MCP 最佳实践
"""

import os
import re
from pathlib import Path

# 优化后的 MarketData SKILL.md
MARKET_DATA_SKILL = '''---
name: market_data
description: |
  股票市场行情数据查询 Skill，提供A股实时行情、历史K线、资金流向等数据查询能力。
  
  Use this skill when:
  - User asks about stock prices, market data, or trading information
  - User wants to analyze stock trends or historical performance
  - User needs to look up stock codes or company information
  - User asks about market sentiment (money flow, top gainers/losers)
  
  Data Source: Tushare Pro API
  Coverage: A-shares (Shanghai, Shenzhen), Hong Kong stocks
  Delay: ~15 minutes for real-time data
version: "1.0"
tool_count: 11
---

# MarketData Skill

## Overview

提供全面的股票市场行情数据查询能力，基于 Tushare Pro API。支持实时行情、历史K线、龙虎榜、资金流向、涨跌停统计等数据。

**Data Source**: Tushare Pro API  
**Markets**: A-shares (Shanghai/Shenzhen), Hong Kong stocks  
**Update Frequency**: Near real-time (~15 min delay)  
**Total Tools**: 11

---

## Available Tools

### 1. get_quote - Get Real-time Stock Quote

**Purpose**: Query real-time stock price, change percentage, trading volume, and other market data.

**When to use**:
- User asks "What's the price of 贵州茅台?"
- User wants current stock price and daily change
- User asks about trading volume or turnover

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | Stock symbol. Formats: `'600519'` (6 digits), `'600519.SH'` (Tushare format), `'1810.HK'` (Hong Kong). **Invalid**: `'sh600519'` (don't add prefix) |

**Returns**:
```json
{
  "gid": "sh600519",
  "ts_code": "600519.SH",
  "name": "贵州茅台",
  "nowPri": "1850.50",      // Current price (CNY)
  "increase": "25.30",       // Price change amount
  "increPer": "1.39",        // Change percentage (%)
  "todayStartPri": "1840.00", // Opening price
  "todayMax": "1865.00",     // Day's high
  "todayMin": "1835.00",     // Day's low
  "traAmount": "125000",     // Trading volume (shares)
  "traNumber": "231250000",  // Trading turnover (CNY)
  "update_time": "20260308"
}
```

**Examples**:
- Query Kweichow Moutai: `get_quote(symbol="600519")`
- Query Xiaomi HK: `get_quote(symbol="1810.HK")`

---

### 2. search_stock - Search Stock by Code or Name

**Purpose**: Search for stock information using stock code or company name keywords.

**When to use**:
- User asks about a company but doesn't know the stock code
- User mentions company name like "茅台" or "贵州茅台"

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| keyword | string | Yes | Search term. Can be stock code (`'600519'`) or company name (`'茅台'`, `'贵州茅台'`). Partial name matching supported for popular stocks. |

**Returns**: Same format as `get_quote`, returns list of matching stocks.

**Examples**:
- Search by code: `search_stock(keyword="600519")`
- Search by name: `search_stock(keyword="贵州茅台")`

---

### 3. get_history - Get Historical K-line Data

**Purpose**: Retrieve historical stock price data (daily, weekly, monthly).

**When to use**:
- User asks "What's the trend of 茅台 over the past month?"
- User wants historical prices for technical analysis
- User asks about stock performance in a specific period

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code (e.g., `'600519'`) |
| period | string | No | `"daily"` | Time period: `"daily"` (日线), `"weekly"` (周线), `"monthly"` (月线) |
| start_date | string | No | null | Start date in format `YYYYMMDD` (e.g., `"20240101"`) |
| end_date | string | No | null | End date in format `YYYYMMDD` (e.g., `"20241231"`) |
| limit | integer | No | 100 | Maximum number of records to return (1-1000) |

**Returns**:
```json
{
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
```

**Examples**:
- Last 30 days daily data: `get_history(symbol="600519", limit=30)`
- Specific date range: `get_history(symbol="600519", start_date="20240101", end_date="20240301")`
- Weekly data: `get_history(symbol="600519", period="weekly", limit=52)`

---

### 4. get_stock_basic_info - Get Stock Basic Information

**Purpose**: Retrieve basic company information including industry, listing date, market, etc.

**When to use**:
- User asks "What industry is 茅台 in?"
- User wants to know when a company went public
- User asks about company's region or market

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | Stock code (e.g., `'600519'`) |

**Returns**:
```json
{
  "ts_code": "600519.SH",
  "name": "贵州茅台",
  "industry": "白酒",        // Industry classification
  "area": "贵州",            // Province/Region
  "list_date": "20010827",   // Listing date (YYYYMMDD)
  "market": "主板",          // Market board
  "exchange": "SSE"          // Exchange code
}
```

---

### 5. get_daily_basic - Get Daily Valuation Metrics

**Purpose**: Get daily valuation metrics including PE, PB, market cap, turnover rate.

**When to use**:
- User asks "What's the PE ratio of 茅台?"
- User wants market cap or valuation information
- User asks about turnover rate or liquidity

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | No | null | Stock code. If null, returns data for all stocks (large dataset). |
| trade_date | string | No | null | Trade date in format `YYYYMMDD`. If null, returns latest available data. |

**Returns**:
```json
{
  "ts_code": "600519.SH",
  "name": "贵州茅台",
  "pe": 28.74,               // Price-to-Earnings ratio (TTM)
  "pb": 8.56,                // Price-to-Book ratio
  "ps": 12.34,               // Price-to-Sales ratio
  "total_mv": 2325000000000, // Total market cap (CNY)
  "circ_mv": 2325000000000,  // Circulating market cap (CNY)
  "turnover_rate": 0.52      // Turnover rate (%)
}
```

**Examples**:
- Get specific stock: `get_daily_basic(symbol="600519")`
- Get all stocks for a date: `get_daily_basic(trade_date="20240308")`

---

### 6. get_money_flow - Get Money Flow Data

**Purpose**: Get capital flow data (institutional vs retail, inflow vs outflow).

**When to use**:
- User asks "What's the money flow of 茅台 today?"
- User wants to know if institutions are buying or selling
- User asks about main force (主力) movements

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | Stock code |
| trade_date | string | No | null | Specific trade date `YYYYMMDD` |
| start_date | string | No | null | Start date for date range |
| end_date | string | No | null | End date for date range |

**Returns**:
```json
{
  "records": [
    {
      "trade_date": "20260308",
      "ts_code": "600519.SH",
      "net_mf_amount": 231250000,  // Net main force inflow (CNY)
      "buy_lg_vol": 8000.0,        // Large order buy volume
      "sell_lg_vol": 5000.0        // Large order sell volume
    }
  ]
}
```

**Examples**:
- Single day: `get_money_flow(symbol="600519", trade_date="20240308")`
- Date range: `get_money_flow(symbol="600519", start_date="20240301", end_date="20240308")`

---

### 7. get_top_list - Get Dragon Tiger List (机构龙虎榜)

**Purpose**: Get daily top performing stocks with institutional trading data.

**When to use**:
- User asks "Which stocks hit the top gainers list today?"
- User wants to know institutional activity on hot stocks

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| trade_date | string | No | null | Trade date `YYYYMMDD`. Defaults to latest trading day. |
| limit | integer | No | 50 | Maximum number of records to return |

**Returns**: List of stocks with price change, turnover rate, and reasons for listing.

---

### 8. get_limit_list - Get Limit Up/Down Statistics

**Purpose**: Get daily statistics of stocks hitting limit up or limit down.

**When to use**:
- User asks "How many stocks hit limit up today?"
- User wants market sentiment overview

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| trade_date | string | No | null | Trade date `YYYYMMDD` |
| limit_type | string | No | null | Filter by type: `"U"` (limit up only), `"D"` (limit down only). Null returns all. |

---

### 9. get_company_info - Get Company Detailed Information

**Purpose**: Get detailed company profile including business description, contact info.

**When to use**:
- User asks "What does 茅台 company do?"
- User wants company background or contact information

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | Stock code |

**Returns**: Company profile, business scope, website, email, office address.

---

### 10. get_north_money - Get Northbound Capital Flow (北向资金)

**Purpose**: Get Hong Kong Stock Connect (Northbound) capital flow data.

**When to use**:
- User asks "What's the northbound capital flow today?"
- User wants to track foreign institutional investment in A-shares

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| start_date | string | No | null | Start date `YYYYMMDD` |
| end_date | string | No | null | End date `YYYYMMDD` |

---

### 11. get_margin - Get Margin Trading Data (融资融券)

**Purpose**: Get margin trading (融资) and short selling (融券) data.

**When to use**:
- User asks about margin balance or leverage data
- User wants to understand market leverage sentiment

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | No | null | Stock code. Null returns market-wide data. |
| start_date | string | No | null | Start date `YYYYMMDD` |
| end_date | string | No | null | End date `YYYYMMDD` |

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
→ search_stock(keyword="茅台")  // Verify code
→ get_quote(symbol="600519")
```

### Workflow 3: Historical Trend Analysis
```
User: "茅台最近一个月走势如何？"
→ Calculate date range (today - 30 days)
→ get_history(symbol="600519", start_date="20240208", end_date="20240308")
→ Analyze trend (up/down/volatile)
```

### Workflow 4: Comprehensive Stock Analysis
```
User: "分析一下茅台"
→ get_quote(symbol="600519")              // Current price
→ get_stock_basic_info(symbol="600519")   // Industry, listing date
→ get_daily_basic(symbol="600519")        // PE, PB, market cap
→ get_money_flow(symbol="600519")         // Capital flow
→ get_company_info(symbol="600519")       // Company profile
→ Synthesize analysis
```

---

## Important Notes

### 1. Stock Symbol Format
- **Recommended**: Pure 6-digit code (`'600519'`)
- **Also supported**: Tushare format (`'600519.SH'`)
- **Not supported**: Prefixed format (`'sh600519'`)
- **HK stocks**: Must use suffix (`'1810.HK'`)

### 2. Date Format
- **Standard**: `YYYYMMDD` (e.g., `'20260308'`)
- **No separators**: Do NOT use `'2026-03-08'` or `'2026/03/08'`

### 3. Data Timeliness
- Real-time data: ~15 minutes delay
- Daily metrics: Updated after market close
- Historical data: Available for all trading days

### 4. API Rate Limits
- Tushare API has rate limits based on account level
- Cache enabled: Same queries within 1 hour return cached results
- For bulk data, consider using `limit` parameter

### 5. Error Handling
All tools return standardized response:
```json
{"success": true, "data": {...}}    // Success
{"success": false, "error": "..."}   // Failure
```

### 6. Best Practices
- Always check `success` field before using data
- For user queries, extract and highlight key metrics
- Format numbers with thousand separators and appropriate decimals
- Example: "贵州茅台 ¥1,850.50 (+1.39%) 成交量 12.5万手"

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-18  
**Compatible with**: AgentFlow v1.0, MCP Protocol
'''

# 保存优化后的 MarketData SKILL.md
def save_optimized_skill(skill_name, content):
    skill_dir = Path(f"~/.openclaw/workspace-dev/external/financial-research-assistant/backend/claude_skills/{skill_name}").expanduser()
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    skill_file = skill_dir / "SKILL.md"
    
    # 备份原文件
    if skill_file.exists():
        backup_file = skill_dir / "SKILL.md.backup"
        skill_file.rename(backup_file)
        print(f"✅ Backed up original {skill_name}/SKILL.md")
    
    # 写入新文件
    skill_file.write_text(content, encoding='utf-8')
    print(f"✅ Saved optimized {skill_name}/SKILL.md")

if __name__ == "__main__":
    print("="*80)
    print("开始优化 7 个 Skill 的 SKILL.md")
    print("="*80)
    
    # 先优化 MarketData 作为示例
    print("\n1. 优化 MarketData Skill...")
    save_optimized_skill("market_data", MARKET_DATA_SKILL)
    
    print("\n" + "="*80)
    print("MarketData Skill 优化完成！")
    print("="*80)
    print("\n优化要点：")
    print("1. 添加了 'Use this skill when' 部分，帮助LLM判断何时使用")
    print("2. 参数表格包含 Type、Required、Description，更清晰")
    print("3. 添加了 'When to use' 场景说明")
    print("4. 返回值包含字段说明和数据类型")
    print("5. 添加了 Common Workflows 典型工作流程")
    print("6. 错误处理和最佳实践单独成章")
