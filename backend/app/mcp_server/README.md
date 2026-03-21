# 金融研投助手 MCP Server v2.0

## 架构概述

金融研投助手 MCP Server 实现了完整的3轮交互流程，支持6种控制流模式，提供透明的错误处理机制。

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户请求                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  ROUND 1: Skill选择                                              │
│  ─────────────────────                                           │
│  Input:  系统提示 + 7个Skill描述                                  │
│  Output: selected_skills[] + execution_strategy                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  ROUND 2: 工具调用 (支持控制流)                                   │
│  ─────────────────────────────                                   │
│  Input:  选中Skills的工具列表 + 用户请求                          │
│  Output: tool_calls[] / 控制流执行结果                            │
│  支持:   顺序/循环/分支/并行                                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  ROUND 3: 生成回复                                               │
│  ─────────────────                                               │
│  Input:  所有工具返回结果 + 执行日志                              │
│  Output: 结构化分析报告                                           │
└─────────────────────────────────────────────────────────────────┘
```

## 项目结构

```
backend/app/mcp_server/
├── __init__.py                    # MCP Server 初始化
├── server.py                      # 主Server实现
├── skills/                        # Skills目录
│   ├── __init__.py
│   ├── base.py                    # Skill基类
│   ├── market_data.py             # 市场行情数据 (11 tools)
│   ├── financial_analysis.py      # 财务分析 (7 tools)
│   ├── sector_analysis.py         # 行业板块分析 (7 tools)
│   ├── risk_assessment.py         # 风险评估 (5 tools)
│   ├── deep_research.py           # 深度研报 (3 tools)
│   ├── web_research.py            # 网络搜索 (4 tools)
│   └── data_analysis.py           # 数据分析可视化 (6 tools)
├── control_flow/                  # 控制流引擎
│   ├── __init__.py
│   └── engine.py                  # 6种控制流实现
├── error_handler/                 # 错误处理
│   └── __init__.py                # 错误分类和处理逻辑
└── tests/                         # 单元测试
    ├── __init__.py
    └── test_mcp_server.py         # 完整测试套件
```

## 7个Skill (43个Tools)

### 1. market_data - 市场行情数据 (11 tools)
| 工具名 | 描述 |
|--------|------|
| get_quote | 获取实时股价、涨跌幅 |
| search_stock | 搜索股票信息 |
| get_history | 获取历史K线数据 |
| get_stock_basic_info | 获取股票基础信息 |
| get_top_list | 获取龙虎榜数据 |
| get_money_flow | 获取资金流向 |
| get_limit_list | 获取涨跌停统计 |
| get_company_info | 获取公司详细信息 |
| get_daily_basic | 获取PE/PB/市值等估值指标 |
| get_north_money | 获取北向资金流向 |
| get_margin | 获取融资融券数据 |

### 2. financial_analysis - 财务分析 (7 tools)
| 工具名 | 描述 |
|--------|------|
| calculate_financial_ratios | 计算ROE、ROA、毛利率等 |
| get_income_statement | 获取利润表 |
| get_balance_sheet | 获取资产负债表 |
| get_cash_flow | 获取现金流量表 |
| get_fina_indicator | 获取财务指标 |
| analyze_profitability | 分析盈利能力 |
| analyze_solvency | 分析偿债能力 |

### 3. sector_analysis - 行业板块分析 (7 tools)
| 工具名 | 描述 |
|--------|------|
| get_industry_list | 获取行业列表 |
| get_industry_performance | 获取行业表现 |
| get_industry_leaders | 获取行业龙头股 |
| compare_industry_metrics | 对比行业财务指标 |
| compare_industry_valuation | 对比行业估值 |
| get_concept_list | 获取概念列表 |
| get_concept_stocks | 获取概念成分股 |

### 4. risk_assessment - 风险评估 (5 tools)
| 工具名 | 描述 |
|--------|------|
| assess_stock_risk | 综合风险评估 |
| assess_valuation_risk | 估值风险评估 |
| assess_financial_risk | 财务风险评估 |
| assess_volatility_risk | 波动率风险评估 |
| check_risk_warnings | 风险预警检查 |

### 5. deep_research - 深度研报 (3 tools)
| 工具名 | 描述 |
|--------|------|
| generate_stock_report | 生成个股深度研报 |
| generate_industry_report | 生成行业深度研报 |
| generate_comparison_report | 生成对比分析报告 |

### 6. web_research - 网络搜索 (4 tools)
| 工具名 | 描述 |
|--------|------|
| search_stock_news | 搜索股票新闻 |
| search_company_announcements | 搜索公司公告 |
| search_industry_news | 搜索行业新闻 |
| search_research_reports | 搜索研究报告 |

### 7. data_analysis - 数据分析可视化 (6 tools)
| 工具名 | 描述 |
|--------|------|
| calculate_statistics | 计算统计指标 |
| analyze_price_trend | 价格趋势分析 |
| calculate_correlation | 相关性分析 |
| calculate_technical_indicators | 技术指标计算 |
| normalize_data | 数据标准化 |
| generate_chart_data | 生成图表数据 |

## 6种控制流模式

### 1. 顺序执行 (sequential)
```python
config = {
    "calls": [
        {"skill": "market_data", "tool": "get_quote", "arguments": {"symbol": "600519"}},
        {"skill": "market_data", "tool": "get_daily_basic", "arguments": {"symbol": "600519"}},
    ]
}
```

### 2. FOR-EACH 循环
```python
config = {
    "items": ["600519", "000858", "600809"],
    "template": {
        "skill": "market_data",
        "tool": "get_quote",
        "arguments": {"symbol": "{item}"}
    },
    "parallel": True,
    "max_concurrent": 10
}
```

### 3. WHILE 循环
```python
config = {
    "condition": "qualified.count < 3",
    "max_iterations": 20,
    "template": {
        "skill": "market_data",
        "tool": "get_daily_basic",
        "arguments": {"symbol": "{candidate_symbol}"}
    },
    "condition_checker": lambda ctx: ctx.variables.get("qualified_count", 0) < 3
}
```

### 4. IF-ELSE 分支
```python
config = {
    "condition": "pe < 15",
    "condition_evaluator": lambda ctx: ctx.variables.get("pe", 0) < 15,
    "if_branch": {
        "calls": [{"skill": "financial_analysis", "tool": "get_income_statement", ...}]
    },
    "else_branch": {
        "calls": [{"skill": "market_data", "tool": "get_daily_basic", ...}]
    }
}
```

### 5. SWITCH 分支
```python
config = {
    "variable": "industry_type",
    "cases": [
        {"value": "金融", "calls": [...]},
        {"value": "科技", "calls": [...]},
    ],
    "default": {"calls": [...]}
}
```

### 6. FILTER 筛选
```python
config = {
    "source": "industry_performance.results",
    "condition": "change > 5",
    "filter_func": lambda item: item.get("change", 0) > 5
}
```

## 错误处理原则

### 核心原则：**不猜测、不假设、不搪塞**

- **API_ERROR (限流/超时)**: 停止执行，告知用户，提供重试建议
- **DATA_NOT_AVAILABLE**: 停止执行，告知用户数据不存在
- **DATA_INCOMPLETE**: 继续分析，但标注缺失数据
- **VALIDATION_ERROR**: 告知用户参数错误，建议修正
- **SYSTEM_ERROR**: 记录日志，告知用户联系技术支持

### 错误响应格式
```json
{
  "status": "ERROR",
  "error": {
    "type": "rate_limit",
    "code": "TUSHARE_RATE_LIMIT",
    "message": "API 调用频率超限，请稍后再试",
    "is_critical": true
  },
  "user_options": [
    {"action": "retry", "description": "等待60秒后重试", "recommended": true},
    {"action": "abort", "description": "终止当前查询"}
  ]
}
```

## 使用方法

### 基本使用
```python
from app.mcp_server import get_mcp_server

# 获取Server实例
server = get_mcp_server()

# 获取可用Skills
skills = server.get_available_skills()

# 获取Skills的工具列表
tools = server.get_tools_for_skills(["market_data", "financial_analysis"])

# 执行工具调用
result = await server.execute_tools([
    {"skill": "market_data", "tool": "get_quote", "arguments": {"symbol": "600519"}},
])

# 执行控制流
result = await server.execute_control_flow("for_each", {
    "items": ["600519", "000858"],
    "template": {"skill": "market_data", "tool": "get_quote", "arguments": {"symbol": "{item}"}},
    "parallel": True
})
```

### 便捷分析股票
```python
# 综合分析
result = await server.analyze_stock("600519", "comprehensive")

# 仅市场数据
result = await server.analyze_stock("600519", "market")

# 仅财务数据
result = await server.analyze_stock("600519", "financial")
```

## 运行测试

```bash
# 运行所有测试
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
pytest app/mcp_server/tests/test_mcp_server.py -v

# 运行特定测试类
pytest app/mcp_server/tests/test_mcp_server.py::TestFinancialResearchMCPServer -v

# 运行特定测试方法
pytest app/mcp_server/tests/test_mcp_server.py::TestFinancialResearchMCPServer::test_server_initialization -v
```

## 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 单次查询耗时 | < 2秒 | 简单查询(3-5次调用) |
| 复杂查询耗时 | < 5秒 | 含循环/分支(10-20次调用) |
| 并行度 | 10 | 单轮最大并行调用数 |
| WHILE最大迭代 | 20 | 防止无限循环 |
| 总调用上限 | 50 | 单次请求最大调用数 |

## 版本信息

- **版本**: v2.0.0
- **日期**: 2026-03-20
- **状态**: ✅ 已实现
