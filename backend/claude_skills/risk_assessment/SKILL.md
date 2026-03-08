---
name: risk_assessment
description: 投资组合风险评估，支持风险指标计算、投资组合分析、风险报告生成
allowed_tools: [Bash, Read]
---

# RiskAssessment Skill

## 📊 概述

提供专业的投资组合风险评估能力，基于历史数据计算各类风险指标。支持单一资产和投资组合的风险分析、风险等级评定、投资建议生成。

**数据源**: Tushare API 历史行情数据
**支持市场**: A股（上海、深圳）
**分析方法**: 现代投资组合理论（MPT）、VaR、CVaR等

---

## 🛠️ 可用工具

### 1. calculate_risk_metrics - 计算单项资产风险指标

**功能**: 计算单项资产的风险指标（波动率、Beta、最大回撤、VaR、CVaR等）

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
from app.data.tushare_client import get_tushare_client
from datetime import datetime, timedelta
import numpy as np

client = get_tushare_client()
ts_code = client._normalize_stock_code('600519')

# 获取历史数据（252个交易日）
end_date = datetime.now()
start_date = end_date - timedelta(days=int(252 * 1.5))

df = client.get_api().daily(
    ts_code=ts_code,
    start_date=start_date.strftime('%Y%m%d'),
    end_date=end_date.strftime('%Y%m%d')
)

df = df.sort_values('trade_date').tail(252)
prices = df['close'].values

# 计算日收益率
returns = []
for i in range(1, len(prices)):
    ret = (prices[i] - prices[i-1]) / prices[i-1]
    returns.append(ret)

# 计算年化收益率
annual_return = (np.prod(1 + np.array(returns)) ** (252/len(returns)) - 1) * 100

# 计算年化波动率
daily_vol = np.std(returns, ddof=1)
annual_vol = daily_vol * np.sqrt(252) * 100

# 计算夏普比率
risk_free_rate = 0.03
sharpe = (annual_return/100 - risk_free_rate) / (annual_vol/100)

# 计算最大回撤
cummax = np.maximum.accumulate(prices)
drawdowns = (prices - cummax) / cummax
max_dd = np.min(drawdowns) * 100

print(f'''风险指标分析 (252个交易日):
预期年化收益率: {annual_return:.2f}%
年化波动率: {annual_vol:.2f}%
夏普比率: {sharpe:.2f}
最大回撤: {max_dd:.2f}%
''')
"
```

**参数**:
- `symbol` (必需): 股票代码
- `days` (可选): 历史数据天数，默认 `252`（一个交易年）
- `benchmark` (可选): 基准指数代码（如 `'000001'` 上证指数），用于计算Beta

**返回示例**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "name": "贵州茅台",
    "data_period": "252天",
    "data_points": 252,
    "metrics": {
      "expected_return": 0.1523,
      "volatility": 0.2845,
      "sharpe_ratio": 0.4298,
      "max_drawdown": -0.1856,
      "var_95": -0.0234,
      "cvar_95": -0.0312,
      "downside_deviation": 0.1923,
      "beta": 0.87,
      "correlation": 0.65,
      "alpha": 0.0234,
      "benchmark": {
        "name": "上证指数",
        "return": 0.0823,
        "volatility": 0.1923
      }
    },
    "risk_assessment": {
      "level": "中等风险",
      "score": 45.23,
      "description": "资产存在一定波动，需要风险承受能力"
    }
  }
}
```

**关键指标说明**:

1. **预期年化收益率 (expected_return)**: 基于历史数据预测的年化收益
2. **波动率 (volatility)**: 年化标准差，衡量价格波动程度
3. **夏普比率 (sharpe_ratio)**: 风险调整后收益
   - `> 1`: 优秀
   - `0.5-1`: 良好
   - `< 0.5`: 一般
4. **最大回撤 (max_drawdown)**: 历史最大亏损幅度
5. **VaR (95%)**: 95%置信度下的单日最大损失
6. **CVaR (95%)**: 超过VaR的平均损失（尾部风险）
7. **下行标准差**: 仅考虑负收益的波动率
8. **Beta**: 相对于基准的系统性风险
   - `> 1`: 高于市场波动
   - `< 1`: 低于市场波动
9. **Alpha**: 超额收益（相对CAPM模型）

---

### 2. assess_portfolio_risk - 评估投资组合风险

**功能**: 评估投资组合的整体风险，基于历史数据计算预期收益、波动率、夏普比率等

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
# 示例：评估包含3只股票的投资组合
# 600519 (茅台) 40%
# 000001 (平安银行) 30%
# 600036 (招商银行) 30%

portfolio = '600519:0.4,000001:0.3,600036:0.3'

# 解析投资组合
holdings = {}
for item in portfolio.split(','):
    symbol, weight = item.split(':')
    holdings[symbol.strip()] = float(weight.strip())

print('投资组合:')
for symbol, weight in holdings.items():
    print(f'  {symbol}: {weight*100:.1f}%')

# 验证权重和
total_weight = sum(holdings.values())
print(f'\\n权重合计: {total_weight:.2f}')
assert abs(total_weight - 1.0) < 0.01, '权重和必须为1'
"
```

**参数**:
- `portfolio` (必需): 投资组合描述，格式: `'代码1:权重1,代码2:权重2,...'`
  - 示例: `'600519:0.4,000001:0.3,600036:0.3'`
  - 权重和必须为 `1.0`
- `days` (可选): 历史数据天数，默认 `252`
- `benchmark` (可选): 基准指数代码，用于计算组合Beta

**返回示例**:
```json
{
  "success": true,
  "data": {
    "portfolio": {
      "holdings": [
        {"symbol": "600519", "name": "贵州茅台", "weight": "40.00%"},
        {"symbol": "000001", "name": "平安银行", "weight": "30.00%"},
        {"symbol": "600036", "name": "招商银行", "weight": "30.00%"}
      ],
      "data_period": "252天",
      "data_points": 252
    },
    "metrics": {
      "expected_return": 0.1234,
      "volatility": 0.2156,
      "sharpe_ratio": 0.4321,
      "max_drawdown": -0.1523,
      "var_95": -0.0189,
      "cvar_95": -0.0267,
      "downside_deviation": 0.1678,
      "asset_contributions": {
        "600519": {
          "weight": "40.00%",
          "return": "15.23%",
          "contribution": "6.09%"
        },
        "000001": {
          "weight": "30.00%",
          "return": "8.45%",
          "contribution": "2.54%"
        },
        "600036": {
          "weight": "30.00%",
          "return": "11.23%",
          "contribution": "3.37%"
        }
      },
      "beta": 0.95,
      "benchmark": {
        "name": "上证指数",
        "return": 0.0823,
        "volatility": 0.1923
      }
    },
    "risk_assessment": {
      "level": "中低风险",
      "score": 38.56,
      "description": "资产波动适中，风险可控"
    }
  }
}
```

**投资组合指标**:
- **资产贡献度**: 各资产对组合收益的贡献
- **分散效应**: 组合波动率 < 各资产波动率加权平均（说明分散有效）

---

### 3. generate_risk_report - 生成风险报告

**功能**: 生成详细的风险评估报告，包括风险等级、投资建议、风险提示

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
# 对于单一股票
print('生成单一股票风险报告...')
print('参数: symbol=600519, days=252, is_portfolio=False')

# 对于投资组合
print('\\n生成投资组合风险报告...')
print('参数: symbol=\"600519:0.4,000001:0.3,600036:0.3\", days=252, is_portfolio=True')
"
```

**参数**:
- `symbol` (必需): 股票代码或投资组合描述
- `days` (可选): 历史数据天数，默认 `252`
- `is_portfolio` (可选): 是否为投资组合，默认 `False`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "title": "资产风险评估报告",
    "generated_at": "2026-03-08 14:30:00",
    "subject": "600519",
    "data_period": "252天",

    "risk_rating": {
      "level": "中等风险",
      "score": 45.23,
      "description": "资产存在一定波动，需要风险承受能力"
    },

    "key_metrics": {
      "预期年化收益率": "15.23%",
      "波动率(年化)": "28.45%",
      "夏普比率": "0.43",
      "最大回撤": "-18.56%",
      "95% VaR": "-2.34%",
      "95% CVaR": "-3.12%"
    },

    "recommendations": [
      "建议控制仓位，不宜重仓投资",
      "夏普比率为负，收益未能覆盖风险，建议谨慎投资",
      "最大回撤达18.6%，需要较强的心理承受能力"
    ],

    "risk_warnings": [
      "⚠️ 高风险资产，投资需谨慎",
      "⚠️ 95%置信度下单日最大损失可能达2.34%",
      "📌 历史数据不代表未来表现，投资有风险，入市需谨慎"
    ],

    "detailed_metrics": { ... }
  }
}
```

---

## 📋 工作流指导

### 典型分析流程

#### 1. 单一股票风险评估
```
用户: "评估一下茅台的投资风险"

步骤:
1. 使用 calculate_risk_metrics('600519', days=252)
2. 分析关键指标:
   - 波动率: 28.45% (中等)
   - 夏普比率: 0.43 (一般)
   - 最大回撤: -18.56%
3. 判断风险等级
4. 输出友好的风险评估
```

#### 2. 投资组合风险分析
```
用户: "我想配置一个投资组合：茅台40%，平安银行30%，招商银行30%，风险如何？"

步骤:
1. 解析投资组合: '600519:0.4,000001:0.3,600036:0.3'
2. 验证权重和为1
3. 使用 assess_portfolio_risk(portfolio, days=252)
4. 对比组合风险 vs 单一资产风险
5. 分析分散效应
```

#### 3. 生成完整风险报告
```
用户: "给我一份茅台的完整风险报告"

步骤:
1. 使用 generate_risk_report('600519', days=252, is_portfolio=False)
2. 格式化输出:
   - 标题和基本信息
   - 风险等级评定
   - 关键指标列表
   - 投资建议
   - 风险提示
```

#### 4. 对比不同持有期风险
```
用户: "对比茅台近1年和近2年的风险"

步骤:
1. 计算1年风险: calculate_risk_metrics('600519', days=252)
2. 计算2年风险: calculate_risk_metrics('600519', days=504)
3. 对比变化:
   - 波动率趋势
   - 夏普比率变化
   - 最大回撤差异
```

#### 5. 与基准对比
```
用户: "茅台相对于上证指数的风险如何？"

步骤:
1. 使用 calculate_risk_metrics('600519', days=252, benchmark='000001')
2. 分析相对指标:
   - Beta: 0.87 (低于市场波动)
   - Correlation: 0.65 (中等相关)
   - Alpha: 2.34% (正超额收益)
3. 解读Beta和Alpha的含义
```

---

## ⚠️ 注意事项

### 1. 数据要求
- **最少天数**: 30个交易日（约1.5个月）
- **推荐天数**: 252个交易日（1年）
- **长期分析**: 504个交易日（2年）

### 2. 投资组合格式
- **格式**: `'代码1:权重1,代码2:权重2,...'`
- **示例**: `'600519:0.4,000001:0.3,600036:0.3'`
- **要求**: 权重和必须为 `1.0`（允许±0.01误差）
- **最少资产**: 2个（单一资产用 `calculate_risk_metrics`）

### 3. 风险等级划分
```
风险分数 (0-100):
- 0-20: 低风险
- 20-40: 中低风险
- 40-60: 中等风险
- 60-80: 中高风险
- 80-100: 高风险

计算公式:
风险分数 = 波动率×100×40% + (1-夏普比率)×20% + 最大回撤×100×40%
```

### 4. 指标解读标准

**夏普比率**:
- `> 1`: 优秀
- `0.5-1`: 良好
- `0-0.5`: 一般
- `< 0`: 差（收益不足以补偿风险）

**最大回撤**:
- `< 10%`: 低
- `10-20%`: 中等
- `20-30%`: 较高
- `> 30%`: 极高

**波动率**:
- `< 20%`: 低波动
- `20-40%`: 中等波动
- `> 40%`: 高波动

**Beta**:
- `> 1.2`: 高系统性风险
- `0.8-1.2`: 与市场同步
- `< 0.8`: 低系统性风险

### 5. VaR vs CVaR
- **VaR (Value at Risk)**: 正常情况下的最大损失
- **CVaR (Conditional VaR)**: 极端情况下的平均损失
- CVaR > VaR 说明尾部风险较大

### 6. 数据限制
- 非交易日无数据，实际天数可能少于指定天数
- 停牌期间数据缺失会影响计算
- 新上市股票历史数据不足

---

## 📚 参考资源

### 理论基础
- **现代投资组合理论 (MPT)**: Harry Markowitz
- **CAPM模型**: Capital Asset Pricing Model
- **VaR方法**: Historical Simulation

### 相关代码
- **MCP Skill**: `backend/app/mcp_server/skills/risk_assessment.py`
- **数据客户端**: `backend/app/data/tushare_client.py`

### 参数配置
- **无风险收益率**: 3% (中国国债收益率)
- **年化因子**: 252个交易日
- **VaR置信度**: 95%

---

## 🎯 最佳实践

### 1. 选择合适的分析周期
- **短期交易**: 60天（3个月）
- **中期持有**: 252天（1年）
- **长期投资**: 504-756天（2-3年）

### 2. 关注多个风险指标
不要只看单一指标，综合考虑：
- 收益 + 波动率 → 夏普比率
- 最大回撤 + VaR → 极端风险
- Beta + Alpha → 相对表现

### 3. 分散投资降低风险
- 不同行业的股票
- 相关性低的资产
- 目标：组合波动率 < 单一资产

### 4. 定期重新评估
- 市场环境变化 → 风险特征改变
- 建议每季度重新评估
- 重大事件后及时更新

### 5. 友好的输出格式
示例:
```
【风险评估报告】贵州茅台 (600519)

风险等级: ⚠️ 中等风险 (评分: 45.2)
数据周期: 2025-03-08 至 2026-03-08 (252个交易日)

【关键指标】
✓ 预期年化收益: 15.23%
✓ 年化波动率: 28.45%
⚠ 夏普比率: 0.43 (一般)
⚠ 最大回撤: -18.56%
✓ 95% VaR: -2.34% (单日)

【投资建议】
1. 建议控制仓位在20-30%，不宜重仓
2. 波动率较高，适合有一定风险承受能力的投资者
3. 建议设置止损点在-15%附近

【风险提示】
⚠️ 资产存在一定波动，需做好心理准备
⚠️ 95%置信度下单日最大损失可能达2.34%
📌 历史数据不代表未来，投资需谨慎
```

---

## 🔧 故障排查

### 常见问题

**1. "历史数据不足"**
- 检查股票是否为新上市
- 减少 `days` 参数
- 确认数据源是否正常

**2. "投资组合格式错误"**
- 检查格式: `'代码1:权重1,代码2:权重2'`
- 权重必须是0-1之间的小数
- 权重和必须为1.0

**3. "权重和不为1"**
- 当前权重和: `sum(weights)`
- 调整权重确保和为1.0
- 允许±0.01的误差

**4. "无法对齐数据"**
- 不同股票交易日可能不一致
- 系统会自动对齐到共同交易日
- 如果共同交易日<30天，会报错

**5. "Beta计算失败"**
- 检查基准代码是否正确
- 确认基准有足够历史数据
- 股票与基准数据周期需要重叠

**6. "VaR为0"**
- 数据不足（<30天）
- 价格完全不波动（罕见）
- 检查原始数据质量

---

**Skill 版本**: v1.0
**最后更新**: 2026-03-08
**维护者**: Financial Research Team
