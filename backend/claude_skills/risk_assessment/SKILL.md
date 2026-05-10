---
name: risk_assessment
description: |
  投资风险评估，评估个股风险等级、提供预警。
  
  Use this skill when:
  - User asks about investment risk of a specific stock
  - User wants to assess valuation risk (PE/PB too high)
  - User asks about financial risk (debt, cash flow)
  - User wants to analyze price volatility
  - User needs risk warnings and alerts
  
  Data Source: Tushare Pro API
version: "1.0"
tool_count: 5
---

# RiskAssessment Skill

## Overview

提供专业的投资风险评估能力，从估值、财务、波动率等多维度评估个股风险等级。

**Data Source**: Tushare Pro API  
**Coverage**: A-shares (Shanghai, Shenzhen)  
**Risk Assessment Dimensions**: Valuation, Financial, Volatility  
**Risk Score Range**: 0-100 (0=lowest risk, 100=highest risk)  
**Total Tools**: 5

---

## Available Tools

### 1. assess_stock_risk - 综合风险评估

**Purpose**: 综合评估股票风险等级，包括市场风险、财务风险、估值风险等。

**When to use**:
- User asks "How risky is this stock?"
- User wants a comprehensive risk assessment
- Need overall risk score and risk factors

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | 股票代码 (e.g., '600519') |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "risk_score": 45.2,
    "risk_level": "中风险",
    "risk_factors": ["PE超过30，估值略高", "资产负债率超过40%"],
    "components": {
      "valuation": {...},
      "financial": {...},
      "volatility": {...}
    }
  }
}
```

**Risk Level Classification**:
| Score Range | Level | Description |
|-------------|-------|-------------|
| 0-30 | 低风险 | Conservative, suitable for risk-averse investors |
| 30-50 | 中低风险 | Moderate-low, balanced risk-return |
| 50-70 | 中风险 | Moderate, suitable for most investors |
| 70-85 | 中高风险 | Moderate-high, requires risk tolerance |
| 85-100 | 高风险 | Aggressive, suitable for risk-seekers |

**Examples**:
- Basic: `assess_stock_risk(symbol="600519")`

---

### 2. assess_valuation_risk - 估值风险评估

**Purpose**: 评估估值风险，分析PE/PB是否过高。

**When to use**:
- User asks "Is this stock overvalued?"
- User wants to know PE/PB risk
- Comparing valuation against industry average

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| industry_pe_avg | number | No | null | 行业平均PE，用于对比 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "pe": 28.74,
    "pe_ttm": 27.5,
    "pb": 8.56,
    "risk_score": 25,
    "risk_factors": ["PE超过30，估值略高"],
    "assessment": "估值合理"
  }
}
```

**Examples**:
- Basic: `assess_valuation_risk(symbol="600519")`
- With industry comparison: `assess_valuation_risk(symbol="600519", industry_pe_avg=25.0)`

---

### 3. assess_financial_risk - 财务风险评估

**Purpose**: 评估财务风险，分析资产负债率、现金流等。

**When to use**:
- User asks about financial health risks
- User wants to analyze debt levels
- Checking solvency risks

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | 股票代码 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "debt_to_assets": 0.25,
    "current_ratio": 4.52,
    "quick_ratio": 4.21,
    "risk_score": 15,
    "risk_factors": [],
    "assessment": "财务状况良好"
  }
}
```

**Examples**:
- Basic: `assess_financial_risk(symbol="600519")`

---

### 4. assess_volatility_risk - 波动率风险评估

**Purpose**: 评估股价波动风险，分析历史波动率。

**When to use**:
- User asks about price volatility
- User wants to know maximum drawdown
- Analyzing price stability

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| period | string | No | 60d | 计算周期：20d(20日), 60d(60日), 120d(120日) |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "annual_volatility": 28.45,
    "max_drawdown": 18.56,
    "risk_score": 35,
    "risk_factors": ["年化波动率超过30%"],
    "assessment": "波动适中"
  }
}
```

**Examples**:
- Default 60 days: `assess_volatility_risk(symbol="600519")`
- 120 days: `assess_volatility_risk(symbol="600519", period="120d")`

---

### 5. check_risk_warnings - 风险预警检查

**Purpose**: 检查股票的风险预警信号。

**When to use**:
- User wants risk alerts and warnings
- Checking multiple risk factors at once
- Getting high-level risk overview

**Parameters**:
| Name | Type | Required | Description |
|------|------|----------|-------------|
| symbol | string | Yes | 股票代码 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "warning_count": 2,
    "warnings": [
      {
        "level": "medium",
        "type": "估值风险",
        "message": "PE(28.74)偏高"
      },
      {
        "level": "medium",
        "type": "财务风险",
        "message": "资产负债率(25.34%)需关注"
      }
    ],
    "has_critical_warning": false
  }
}
```

**Examples**:
- Basic: `check_risk_warnings(symbol="600519")`

---

## Common Workflows

### Workflow 1: Quick Risk Check
```
User: "茅台风险如何？"

→ assess_stock_risk(symbol="600519")
   → Risk score: 45.2 (中等风险)
   → Risk factors identified

→ Response: "贵州茅台风险评级为中等(45.2分)，
   主要风险因素：PE估值略高。建议仓位控制在合理范围。"
```

### Workflow 2: Comprehensive Risk Analysis
```
User: "全面评估一下比亚迪的风险"

→ assess_stock_risk(symbol="002594")       // Overall assessment
→ assess_valuation_risk(symbol="002594")   // Valuation focus
→ assess_volatility_risk(symbol="002594")  // Volatility analysis
→ check_risk_warnings(symbol="002594")     // Risk alerts

→ Synthesize complete risk report
```

### Workflow 3: Compare Risk Between Stocks
```
User: "茅台和宁德时代哪个风险更高？"

→ assess_stock_risk(symbol="600519")
   → Risk score: 45.2

→ assess_stock_risk(symbol="300750")
   → Risk score: 62.5

→ Compare and present:
   "茅台风险评分45.2(中等)，宁德时代62.5(中高风险)。"
```

---

## Important Notes

### 1. Risk Score Interpretation
| Score Range | Level | Investment Suitability |
|-------------|-------|------------------------|
| 0-30 | 低风险 | Conservative investors |
| 30-50 | 中低风险 | Balanced investors |
| 50-70 | 中风险 | Moderate risk tolerance |
| 70-85 | 中高风险 | Higher risk tolerance |
| 85-100 | 高风险 | Risk-seeking investors |

### 2. Valuation Risk Factors
| PE Range | Risk Assessment |
|----------|-----------------|
| < 15 | Low risk, potentially undervalued |
| 15-30 | Fair valuation |
| 30-50 | High valuation risk |
| > 50 | Very high valuation risk |

### 3. Financial Risk Factors
| Debt-to-Assets | Risk Assessment |
|----------------|-----------------|
| < 40% | Low financial risk |
| 40-60% | Moderate risk |
| 60-80% | High risk |
| > 80% | Very high risk |

### 4. Volatility Risk Factors
| Annual Volatility | Risk Assessment |
|-------------------|-----------------|
| < 20% | Low volatility |
| 20-30% | Moderate volatility |
| 30-50% | High volatility |
| > 50% | Very high volatility |

### 5. Error Handling
All tools return standardized response:
```json
{"success": true, "data": {...}}    // Success
{"success": false, "error": "股票代码不能为空"}   // Missing symbol
{"success": false, "error": "未找到估值数据"}   // Data not available
```

### 6. Best Practices
- Use `assess_stock_risk` for quick overall assessment
- Use specific tools (`assess_valuation_risk`, `assess_financial_risk`, `assess_volatility_risk`) for detailed analysis
- Use `check_risk_warnings` for quick alerts
- Always check `success` field before using data
- Combine with other skills for comprehensive analysis

---

## Quantitative Thresholds

For the precise numeric cuts used by all tools (PE/PB/PS valuation cuts,
debt/liquidity ratios, volatility / drawdown cuts, score weights, and
risk-level boundaries), see [risk_thresholds](resources/risk_thresholds.yaml).

The thresholds file is loaded automatically as an L3a resource when this
skill is expanded. It can also be re-loaded standalone via
`{"action": "load_resource", "skill": "risk_assessment", "ref": "resources/risk_thresholds.yaml"}`
if the conversation has drifted out of context.

**When to consult the thresholds explicitly:**
- User asks "what's your cutoff for high PE?"
- User asks "how do you weight valuation vs. financial risk?"
- Disagreement between tool output and user intuition — re-read thresholds
  to explain the decision

**Sector caveats:** thresholds are A-share-anchored. Banking / insurance /
real-estate sectors naturally exceed `debt_to_assets` cuts (regulatory
norms); apply sector overlay before firing high-risk warnings.

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-20  
**Compatible with**: AgentFlow v1.0, MCP Protocol
