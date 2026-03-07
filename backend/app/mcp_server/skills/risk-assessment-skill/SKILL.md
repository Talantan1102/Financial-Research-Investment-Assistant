---
name: risk-assessment-skill
description: 投资组合风险评估，支持风险指标计算、投资组合分析、风险报告生成
author: 深圳市深维智见教育科技有限公司
version: 1.0.0
license: Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
---

# Risk Assessment Skill

## 简介

投资组合风险评估 Skill，提供投资组合风险分析功能，基于历史数据计算各类风险指标。支持单项资产和组合资产的风险评估。

## 功能特性

- **投资组合风险评估**：基于历史数据计算预期收益、波动率、夏普比率等
- **单项资产风险指标**：计算波动率、Beta、最大回撤、VaR等
- **风险报告生成**：生成包含风险等级、投资建议、风险提示的详细报告

## 注册的工具

### assess_portfolio_risk

评估投资组合的整体风险，基于历史数据计算预期收益、波动率、夏普比率等指标。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| portfolio | string | 是 | 投资组合描述，格式：'代码1:权重1,代码2:权重2,...' |
| days | integer | 否 | 历史数据天数，默认252天（一个交易年） |
| benchmark | string | 否 | 基准指数代码，用于计算Beta值 |

**投资组合格式示例：**
- `"600519:0.4,000001:0.3,600036:0.3"` - 茅台40%、平安银行30%、招行30%

**返回示例：**
```json
{
  "portfolio": {
    "holdings": [
      {"symbol": "600519", "name": "贵州茅台", "weight": "40.00%"},
      {"symbol": "000001", "name": "平安银行", "weight": "30.00%"}
    ],
    "data_period": "252天"
  },
  "metrics": {
    "expected_return": 0.1523,
    "volatility": 0.2456,
    "sharpe_ratio": 0.62,
    "max_drawdown": -0.1856,
    "var_95": -0.0256,
    "cvar_95": -0.0389
  },
  "risk_assessment": {
    "level": "中等风险",
    "score": 52.3,
    "description": "资产存在一定波动，需要风险承受能力"
  }
}
```

### calculate_risk_metrics

计算单项资产的风险指标，包括波动率、Beta、最大回撤、VaR、CVaR等。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码 |
| days | integer | 否 | 历史数据天数，默认252天 |
| benchmark | string | 否 | 基准指数代码，用于计算Beta和Alpha |

**计算指标说明：**
| 指标 | 说明 | 用途 |
|------|------|------|
| expected_return | 预期年化收益率 | 收益预期 |
| volatility | 年化波动率 | 风险度量 |
| sharpe_ratio | 夏普比率 | 风险调整后收益 |
| max_drawdown | 最大回撤 | 极端风险 |
| var_95 | 95%置信度VaR | 单日最大可能损失 |
| cvar_95 | 95%置信度CVaR | 极端情况平均损失 |
| beta | Beta系数 | 系统性风险 |
| alpha | Alpha系数 | 超额收益 |
| correlation | 与基准相关性 | 分散化效果 |
| downside_deviation | 下行标准差 | 下行风险 |

**返回示例：**
```json
{
  "symbol": "600519",
  "name": "贵州茅台",
  "data_period": "252天",
  "metrics": {
    "expected_return": 0.1865,
    "volatility": 0.2890,
    "sharpe_ratio": 0.54,
    "max_drawdown": -0.2560,
    "var_95": -0.0289,
    "cvar_95": -0.0412,
    "beta": 0.89,
    "alpha": 0.0234
  },
  "risk_assessment": {
    "level": "中高风险",
    "score": 67.8
  }
}
```

### generate_risk_report

生成详细的风险评估报告，包括风险等级、投资建议、风险提示。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码或投资组合描述 |
| days | integer | 否 | 历史数据天数，默认252天 |
| is_portfolio | boolean | 否 | 是否为投资组合，默认False |

**报告内容：**
- 风险评级（低风险/中低风险/中等风险/中高风险/高风险）
- 关键风险指标汇总
- 个性化投资建议
- 风险提示和警告

**返回示例：**
```json
{
  "title": "资产风险评估报告",
  "generated_at": "2026-03-08 14:30:00",
  "subject": "600519",
  "risk_rating": {
    "level": "中等风险",
    "score": 52.3,
    "description": "资产存在一定波动，需要风险承受能力"
  },
  "key_metrics": {
    "预期年化收益率": "18.65%",
    "波动率(年化)": "28.90%",
    "夏普比率": "0.54",
    "最大回撤": "-25.60%"
  },
  "recommendations": [
    "夏普比率较高，风险调整后收益表现良好",
    "最大回撤达25.6%，需要较强的心理承受能力"
  ],
  "risk_warnings": [
    "⚠️ 95%置信度下单日最大损失可能达2.89%",
    "📌 历史数据不代表未来表现，投资有风险，入市需谨慎"
  ]
}
```

## 风险等级划分

| 风险等级 | 分数范围 | 描述 |
|---------|---------|------|
| 低风险 | < 20 | 资产波动较小，适合稳健型投资者 |
| 中低风险 | 20-40 | 资产波动适中，风险可控 |
| 中等风险 | 40-60 | 资产存在一定波动，需要风险承受能力 |
| 中高风险 | 60-80 | 资产波动较大，需谨慎投资 |
| 高风险 | ≥ 80 | 资产波动剧烈，不建议风险承受能力较低的投资者参与 |

## 使用示例

```python
from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill

skill = RiskAssessmentSkill()

# 评估投资组合风险
result = await skill.assess_portfolio_risk(
    portfolio="600519:0.5,000001:0.3,600036:0.2",
    days=252,
    benchmark="000001"
)

# 计算单项资产风险指标
result = await skill.calculate_risk_metrics(
    symbol="600519",
    days=252,
    benchmark="000001"
)

# 生成风险报告
result = await skill.generate_risk_report(
    symbol="600519",
    is_portfolio=False
)
```

## 依赖

- Tushare API
- NumPy（数值计算）
- pandas（数据处理）
- `TUSHARE_API_TOKEN` 环境变量

## 目录结构

```
risk-assessment-skill/
├── SKILL.md              # 本文件
├── scripts/              # 可选：脚本文件
├── references/           # 可选：参考文档
└── assets/              # 可选：静态资源
```

## 源码位置

实际代码位于：`../risk_assessment.py`
