# 金融研投助手调整后架构分析

> 分析日期：2026-03-15
> 分析对象：调整后的金融研投助手代码

---

## 🏗️ 新架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                     金融研投助手 (调整后)                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────┐      ┌──────────────────────────┐     │
│  │   MCP Server Layer   │      │    ToolExecutor Layer    │     │
│  │   (主要工具层)        │      │    (备用/独立工具层)      │     │
│  ├──────────────────────┤      ├──────────────────────────┤     │
│  │                      │      │                          │     │
│  │  web_research        │      │  web_search              │     │
│  │  ├── web_search      │      │  knowledge_search        │     │
│  │  ├── knowledge_search│      │  text2sql                │     │
│  │  ├── deep_search     │      │  data_analyzer           │     │
│  │  └── extract_webpage │      │  chart_generator         │     │
│  │                      │      │  stock_query             │     │
│  │  market_data         │      │  bidding_search          │     │
│  │  ├── get_quote       │      │  finish                  │     │
│  │  ├── search_stock    │      │                          │     │
│  │  ├── get_history     │      └──────────────────────────┘     │
│  │  └── get_financial_data                                   │
│  │                                                           │
│  │  financial_analysis                                       │
│  │  ├── get_financial_report                                 │
│  │  ├── calculate_financial_ratios                           │
│  │  └── compare_financials                                   │
│  │                                                           │
│  │  risk_assessment                                          │
│  │  └── assess_risk                                          │
│  │                                                           │
│  │  data_analysis                                            │
│  │  ├── analyze_data                                         │
│  │  ├── generate_chart                                       │
│  │  └── calculate_statistics                                 │
│  │                                                           │
│  │  deep_research                                            │
│  │  ├── research_plan                                        │
│  │  ├── execute_research                                     │
│  │  └── generate_report                                      │
│  │                                                           │
│  └──────────────────────┘                                    │
│           ↑                                                  │
│           │                                                  │
│  ┌────────┴────────────────┐                                 │
│  │    ToolAdapter          │                                 │
│  │  (MCP Client 封装)       │                                 │
│  │                         │                                 │
│  │  • 统一工具调用接口      │                                 │
│  │  • 渐进式披露机制        │                                 │
│  │  • 格式: skill.tool      │                                 │
│  └─────────────────────────┘                                 │
│           ↑                                                  │
│           │                                                  │
│  ┌────────┴────────────────┐                                 │
│  │   MCP Client/Server     │                                 │
│  │   (三层渐进式披露)       │                                 │
│  └─────────────────────────┘                                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Skills 详细清单

### 1. WebResearchSkill (`web_research`)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `web_search` | 网络搜索 | query, count, freshness |
| `knowledge_search` | 知识库搜索 | query, kb_name, top_k |
| `deep_search` | 深度搜索 | query, sub_queries, max_depth |
| `extract_webpage` | 网页内容提取 | url, extract_type |
| `batch_search` | 批量搜索 | queries, search_type |

### 2. MarketDataSkill (`market_data`)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `get_quote` | 获取股票行情 | symbol |
| `search_stock` | 搜索股票 | keyword |
| `get_history` | 获取历史K线 | symbol, period, start_date, end_date |
| `get_financial_data` | 获取财务数据 | symbol, data_type |

### 3. FinancialAnalysisSkill (`financial_analysis`)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `get_financial_report` | 获取财务报表 | symbol, report_type, period, report_count |
| `calculate_financial_ratios` | 计算财务比率 | symbol, ratios |
| `compare_financials` | 对比财务指标 | symbols, metrics |
| `analyze_revenue` | 营收分析 | symbol, period |
| `analyze_profitability` | 盈利能力分析 | symbol |

### 4. RiskAssessmentSkill (`risk_assessment`)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `assess_risk` | 风险评估 | symbol, risk_types |
| `analyze_volatility` | 波动率分析 | symbol, period |
| `check_abnormal_signals` | 异常信号检测 | symbol |

### 5. DataAnalysisSkill (`data_analysis`)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `analyze_data` | 数据分析 | data, analysis_type |
| `generate_chart` | 生成图表 | data, chart_type, title |
| `calculate_statistics` | 计算统计指标 | data, metrics |
| `trend_analysis` | 趋势分析 | data, trend_type |

### 6. DeepResearchSkill (`deep_research`)
| 工具名 | 功能 | 参数 |
|--------|------|------|
| `research_plan` | 研究规划 | topic, depth, focus_areas |
| `execute_research` | 执行研究 | plan_id, steps |
| `generate_report` | 生成报告 | research_id, report_type |

---

## 🔌 工具调用方式

### 方式1：通过 ToolAdapter (推荐)
```python
from app.mcp_client.adapter import ToolAdapter

adapter = ToolAdapter(mcp_client=mcp_client)

# 调用工具
result = await adapter.get_stock_by_code("600519")
result = await adapter.web_search("新能源汽车")
result = await adapter.analyze_data(data_list)
```

### 方式2：直接通过 MCP Client
```python
from app.mcp_client.client import MCPClient

client = MCPClient()
await client.connect()

# 调用工具
result = await client.call_tool(
    "execute_skill_tool",
    {
        "skill_name": "market_data",
        "tool_name": "get_quote",
        "arguments": {"symbol": "600519"}
    }
)
```

### 方式3：ToolExecutor (备用)
```python
from app.service.tool_executor import ToolExecutor

executor = ToolExecutor(...)
result = await executor.execute("web_search", {"query": "..."}, context)
```

---

## 🎯 AgentFlow 集成建议

### 方案选择

**方案A：直接集成 MCP Server Skills (推荐)**
- 优点：工具最全、最新、统一
- 缺点：需要启动 MCP Server
- 适用：生产环境

**方案B：集成 ToolAdapter**
- 优点：封装完善、易于使用
- 缺点：依赖 MCP Client 连接
- 适用：生产环境

**方案C：混合方案**
- MCP Skills 为主
- ToolExecutor 为备用
- 适用：需要高可用性

---

## 📝 关键结论

### 1. 工具数量
- **MCP Server Skills**: 约 25+ 个工具
- **ToolExecutor**: 8 个工具
- **总计**: 约 30+ 个工具

### 2. 架构变化
- 调整前：ToolExecutor 为主，MCP 为辅助
- 调整后：**MCP Server Skills 为主**，ToolExecutor 为备用/独立

### 3. AgentFlow 集成影响
- 需要支持 **skill.tool** 格式（如 `market_data.get_quote`）
- 需要处理 **渐进式披露** 机制
- 建议直接使用 **ToolAdapter** 简化调用

### 4. GRPO 训练数据生成
- 使用 MCP 工具格式生成 trajectory
- 确保工具名、参数、返回值与实际一致
- 支持多轮对话和工具链调用

---

## 🚀 下一步行动

1. **更新 AgentFlow Backend** 支持 MCP Skills 调用
2. **实现渐进式披露机制**（如需要）
3. **生成测试数据** 验证工具调用流程
4. **批量生成 GRPO 训练数据**
