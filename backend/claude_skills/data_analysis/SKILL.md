---
name: data_analysis
description: |
  数据分析与可视化，支持统计分析、趋势预测、图表生成。
  
  Use this skill when:
  - User wants to calculate statistics on data
  - User wants to analyze price trends
  - User needs to calculate correlation between stocks
  - User wants technical indicators (MA, RSI, MACD, Bollinger)
  - User needs data normalization
  - User wants to generate chart data
  
  Data Source: Tushare Pro API (for stock data)
version: "1.0"
tool_count: 6
---

# DataAnalysis Skill

## Overview

提供数据分析与可视化能力，支持统计分析、价格趋势分析、相关性分析、技术指标计算、数据标准化和图表数据生成。

**Capabilities**: Statistical analysis, trend analysis, correlation analysis, technical indicators, data normalization  
**Supported Data**: Stock price data, time series data  
**Output Formats**: Analysis reports, chart data  
**Total Tools**: 6

---

## Available Tools

### 1. calculate_statistics - 计算统计指标

**Purpose**: 计算数据的统计指标（均值、标准差、最大值、最小值等）。

**When to use**:
- User wants statistical summary of data
- Need mean, std dev, min, max, median calculations
- Analyzing data distribution

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| data | array | Yes | - | 数值数组 |
| metrics | array | No | null | 需要计算的指标：mean(均值), std(标准差), min(最小值), max(最大值), median(中位数) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "mean": 125.5,
    "std": 45.2,
    "min": 80,
    "max": 200,
    "median": 122,
    "count": 12
  }
}
```

**Examples**:
- All metrics: `calculate_statistics(data=[100, 120, 130, 110, 140])`
- Specific metrics: `calculate_statistics(data=prices, metrics=["mean", "std"])`

---

### 2. analyze_price_trend - 价格趋势分析

**Purpose**: 分析股票价格趋势。

**When to use**:
- User asks "这个股票走势如何？"
- User wants trend direction and strength
- Need price change analysis

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| period | string | No | 60d | 分析周期：20d(20日), 60d(60日), 120d(120日) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "period": "60d",
    "current_price": 1850.50,
    "period_high": 1920.00,
    "period_low": 1680.00,
    "price_change": 120.50,
    "price_change_percent": 6.97,
    "trend_direction": "up",
    "trend_strength": 78.5,
    "volatility": 28.45,
    "avg_volume": 125000
  }
}
```

**Trend Directions**:
| Direction | Description |
|-----------|-------------|
| up | 上升趋势 |
| down | 下降趋势 |
| sideways | 横盘整理 |

**Examples**:
- Default 60 days: `analyze_price_trend(symbol="600519")`
- Short term: `analyze_price_trend(symbol="600519", period="20d")`
- Long term: `analyze_price_trend(symbol="600519", period="120d")`

---

### 3. calculate_correlation - 相关性分析

**Purpose**: 计算两只股票的相关性。

**When to use**:
- User asks "茅台和五粮液走势相关吗？"
- User wants to analyze portfolio diversification
- Checking how two stocks move together

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol1 | string | Yes | - | 第一只股票代码 |
| symbol2 | string | Yes | - | 第二只股票代码 |
| period | string | No | 60d | 分析周期 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol1": "600519",
    "symbol2": "000858",
    "period": "60d",
    "correlation": 0.85,
    "interpretation": "强相关"
  }
}
```

**Correlation Interpretation**:
| Correlation | Description |
|-------------|-------------|
| >= 0.8 | 强相关 |
| 0.5 - 0.8 | 中等相关 |
| 0.3 - 0.5 | 弱相关 |
| < 0.3 | 几乎无关 |
| Negative | 负相关 (反向走势) |

**Examples**:
- Default: `calculate_correlation(symbol1="600519", symbol2="000858")`
- Longer period: `calculate_correlation(symbol1="300750", symbol2="002594", period="120d")`

---

### 4. calculate_technical_indicators - 技术指标计算

**Purpose**: 计算技术指标（MA、RSI、MACD等）。

**When to use**:
- User asks for technical analysis
- Need moving averages, RSI, MACD, Bollinger Bands
- Technical trading signals

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| indicators | array | No | null | 指标列表：ma(移动平均线), rsi(相对强弱指标), macd, boll(布林带) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "ma": {
      "ma5": 1840.50,
      "ma10": 1830.20,
      "ma20": 1810.80,
      "ma60": 1750.30
    },
    "rsi": {
      "rsi": 62.5
    },
    "macd": {
      "macd": 2.35,
      "signal": 1.80,
      "histogram": 0.55
    },
    "boll": {
      "upper": 1920.50,
      "middle": 1810.80,
      "lower": 1701.10
    }
  }
}
```

**Technical Indicators**:
| Indicator | Description | Use Case |
|-----------|-------------|----------|
| ma | 移动平均线 | Trend direction |
| rsi | 相对强弱指标 | Overbought/oversold (70+, 30-) |
| macd | MACD指标 | Trend changes |
| boll | 布林带 | Volatility, support/resistance |

**Examples**:
- All indicators: `calculate_technical_indicators(symbol="600519")`
- MA only: `calculate_technical_indicators(symbol="600519", indicators=["ma"])`
- RSI + MACD: `calculate_technical_indicators(symbol="600519", indicators=["rsi", "macd"])`

---

### 5. normalize_data - 数据标准化

**Purpose**: 对数据进行标准化处理（Min-Max或Z-Score）。

**When to use**:
- User wants to normalize data for comparison
- Preparing data for machine learning
- Comparing metrics on different scales

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| data | array | Yes | - | 数值数组 |
| method | string | No | minmax | 标准化方法：minmax(最小-最大), zscore(Z-Score) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "method": "minmax",
    "original_range": {
      "min": 80,
      "max": 200
    },
    "normalized": [0.0, 0.25, 0.5, 0.75, 1.0]
  }
}
```

**Normalization Methods**:
| Method | Description | Output Range |
|--------|-------------|--------------|
| minmax | Min-Max标准化 | [0, 1] |
| zscore | Z-Score标准化 | Mean=0, Std=1 |

**Examples**:
- Min-Max: `normalize_data(data=[100, 120, 130, 110, 140], method="minmax")`
- Z-Score: `normalize_data(data=prices, method="zscore")`

---

### 6. generate_chart_data - 生成图表数据

**Purpose**: 生成图表数据（K线、折线图、柱状图等）。

**When to use**:
- User wants chart data for visualization
- Need formatted data for front-end charts
- Generating K-line, line, bar, or area chart data

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| chart_type | string | No | line | 图表类型：candlestick(K线), line(折线), bar(柱状), area(面积) |
| period | string | No | 60d | 数据周期 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "chart_type": "line",
    "period": "60d",
    "data": [
      {"date": "20260301", "value": 1820.50},
      {"date": "20260302", "value": 1830.20},
      {"date": "20260303", "value": 1840.80}
    ]
  }
}
```

**Chart Types**:
| Type | Description | Data Format |
|------|-------------|-------------|
| candlestick | K线图 | open, high, low, close, volume |
| line | 折线图 | date, value |
| bar | 柱状图 | date, value |
| area | 面积图 | date, value, volume |

**Examples**:
- Line chart: `generate_chart_data(symbol="600519", chart_type="line")`
- K-line: `generate_chart_data(symbol="600519", chart_type="candlestick", period="120d")`
- Volume bar: `generate_chart_data(symbol="600519", chart_type="bar")`

---

## Common Workflows

### Workflow 1: Technical Analysis
```
User: "分析一下茅台的技术面"

→ Step 1: calculate_technical_indicators(symbol="600519", indicators=["ma", "rsi", "macd"])
   → Get technical signals

→ Step 2: analyze_price_trend(symbol="600519", period="60d")
   → Get trend direction

→ Response: "技术面分析：
   - 趋势：上升，强度78.5%
   - MA：股价位于MA5/MA10之上
   - RSI：62.5（中性偏强）
   - MACD：金叉信号"
```

### Workflow 2: Stock Correlation Analysis
```
User: "茅台和五粮液走势相关吗？"

→ calculate_correlation(symbol1="600519", symbol2="000858", period="120d")
   → Correlation: 0.85

→ Response: "茅台和五粮液相关性0.85，属于强相关，
   两只股票走势高度一致，分散投资效果有限。"
```

### Workflow 3: Portfolio Analysis
```
User: "帮我分析一下这个股票组合的相关性"

→ Step 1: calculate_correlation(symbol1="600519", symbol2="300750")
   → Check liquor vs new energy

→ Step 2: calculate_correlation(symbol1="600519", symbol2="000001")
   → Check liquor vs banking

→ Step 3: calculate_correlation(symbol1="300750", symbol2="002594")
   → Check new energy correlation

→ Response: "组合相关性分析：
   白酒与新能源相关性低(0.2)，分散效果好
   白酒与银行相关性中等(0.4)"
```

### Workflow 4: Chart Data Generation
```
User: "给我生成茅台的K线数据"

→ generate_chart_data(symbol="600519", chart_type="candlestick", period="120d")
   → Get formatted K-line data

→ Response: Provide chart data for frontend rendering
```

---

## Important Notes

### 1. Technical Indicator Signals
| Indicator | Buy Signal | Sell Signal |
|-----------|------------|-------------|
| MA | Price > MA20 | Price < MA20 |
| RSI | RSI < 30 (oversold) | RSI > 70 (overbought) |
| MACD | MACD > Signal (golden cross) | MACD < Signal (death cross) |
| Bollinger | Price < Lower (oversold) | Price > Upper (overbought) |

### 2. Data Requirements
- Minimum data points required for each indicator
- MA: 60 days for MA60
- RSI: 14+ days
- MACD: 26+ days
- Bollinger: 20+ days

### 3. Correlation Notes
- Correlation ranges from -1 to +1
- +1 = perfect positive correlation
- -1 = perfect negative correlation
- 0 = no correlation
- High correlation doesn't imply causation

### 4. Normalization Use Cases
- **Min-Max**: When you need bounded [0,1] values
- **Z-Score**: When you need to handle outliers

### 5. Error Handling
All tools return standardized response:
```json
{"success": true, "data": {...}}    // Success
{"success": false, "error": "数据不能为空"}   // Empty data
{"success": false, "error": "股票代码不能为空"}   // Missing symbol
{"success": false, "error": "历史数据不足"}   // Insufficient data
```

### 6. Best Practices
- Use `calculate_technical_indicators` for technical analysis
- Use `calculate_correlation` for portfolio diversification analysis
- Use `normalize_data` before comparing metrics on different scales
- Use `generate_chart_data` for visualization preparation
- Always check `success` field before using data

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-20  
**Compatible with**: AgentFlow v1.0, MCP Protocol
