# AgentFlow 金融研投助手集成方案 v2

> 基于调整后金融研投助手架构
> 更新日期：2026-03-15

---

## 📋 背景

金融研投助手代码已调整，架构发生变化：
- **调整前**: ToolExecutor 为主，MCP 为辅
- **调整后**: **MCP Server Skills 为主**，ToolExecutor 为备用

---

## 🏗️ 新架构对比

### 调整前架构
```
ToolExecutor (8个工具)
├── web_search
├── knowledge_search
├── stock_query
├── bidding_search
├── text2sql
├── data_analyzer
├── chart_generator
└── finish

MCP Server (辅助)
└── 部分专业工具
```

### 调整后架构
```
MCP Server Skills (25+ 个工具) ← 主要
├── web_research (4个工具)
│   ├── web_search
│   ├── knowledge_search
│   ├── deep_search
│   └── extract_webpage
├── market_data (4个工具)
│   ├── get_quote
│   ├── search_stock
│   ├── get_history
│   └── get_financial_data
├── financial_analysis (5个工具)
│   ├── get_financial_report
│   ├── calculate_financial_ratios
│   ├── compare_financials
│   ├── analyze_revenue
│   └── analyze_profitability
├── risk_assessment (3个工具)
│   ├── assess_risk
│   ├── analyze_volatility
│   └── check_abnormal_signals
├── data_analysis (4个工具)
│   ├── analyze_data
│   ├── generate_chart
│   ├── calculate_statistics
│   └── trend_analysis
└── deep_research (3个工具)
    ├── research_plan
    ├── execute_research
    └── generate_report

ToolExecutor (8个工具) ← 备用/独立
└── 原有工具保持不变
```

---

## 🔄 工具调用方式变化

### 调整前
```python
# 通过 ToolExecutor
tool_executor.execute("web_search", params, context)

# 参数格式
{
    "tool": "web_search",
    "params": {"query": "...", "count": 5}
}
```

### 调整后
```python
# 通过 ToolAdapter (MCP Client)
tool_adapter.web_search(query="...", count=5)

# 或直接调用 MCP
mcp_client.call_tool("execute_skill_tool", {
    "skill_name": "web_research",
    "tool_name": "web_search",
    "arguments": {"query": "...", "count": 5}
})

# 新格式: skill_name.tool_name
"web_research.web_search"
"market_data.get_quote"
"financial_analysis.get_financial_report"
```

---

## 📦 创建的文件

### Backend 实现
| 文件 | 路径 | 说明 |
|------|------|------|
| MCP Backend v2 | `sandbox/server/backends/resources/finance_research_mcp_v2.py` | 支持调整后架构 |
| Sandbox 配置 | `configs/sandbox-server/finance_research_mcp_v2_config.json` | v2 配置 |
| Synthesis 配置 | `configs/synthesis/finance_research_mcp_v2_config.json` | 数据合成配置 |

### 文档
| 文件 | 路径 | 说明 |
|------|------|------|
| 架构分析 | `docs/finance_research_architecture_v2.md` | 详细架构分析 |
| 集成方案 | 本文档 | 完整集成指南 |

---

## 🚀 使用方式

### 前置条件
1. 启动金融研投助手 MCP Server
2. 确保 MCP Client 可以连接到 Server

### 启动步骤

```bash
# 1. 启动金融研投助手 MCP Server
# (在金融研投助手目录)
python -m app.mcp_server.server

# 2. 启动 AgentFlow Sandbox
cd ~/.openclaw/workspace-dev/external/AgentFlow
/opt/miniconda3/envs/deepresearch/bin/python -m sandbox.server \
  configs/sandbox-server/finance_research_mcp_v2_config.json

# 3. 运行数据合成
/opt/miniconda3/envs/deepresearch/bin/python -m synthesis.run \
  configs/synthesis/finance_research_mcp_v2_config.json
```

---

## 📊 工具映射表

| 原 ToolExecutor 工具 | 新 MCP Skill 工具 | 说明 |
|---------------------|-------------------|------|
| `web_search` | `web_research.web_search` | 相同功能 |
| `knowledge_search` | `web_research.knowledge_search` | 相同功能 |
| `stock_query` | `market_data.get_quote` | 更精确 |
| `bidding_search` | - | MCP 中暂无 |
| `text2sql` | - | MCP 中暂无 |
| `data_analyzer` | `data_analysis.analyze_data` | 功能增强 |
| `chart_generator` | `data_analysis.generate_chart` | 功能增强 |
| `finish` | - | AgentFlow 内置 |

**新增专业工具**:
- `market_data.get_history` - 历史K线
- `market_data.get_financial_data` - 每日指标
- `financial_analysis.get_financial_report` - 详细财报
- `financial_analysis.calculate_financial_ratios` - 财务比率
- `financial_analysis.compare_financials` - 公司对比
- `risk_assessment.assess_risk` - 风险评估
- `deep_research.research_plan` - 研究规划

---

## 💡 关键变化

### 1. 工具数量
- 调整前: ~8 个工具
- 调整后: **25+ 个工具**

### 2. 数据精度
- 调整前: 聚合数据 API（基础）
- 调整后: **Tushare 专业数据**（精确）

### 3. 财务分析能力
- 调整前: 基础股票查询
- 调整后: **完整财务分析**（三大报表、财务比率、公司对比）

### 4. 风险评估
- 调整前: ❌ 无
- 调整后: **✅ 专业风险评估**

### 5. 深度研究
- 调整前: ❌ 无
- 调整后: **✅ 自动研究规划与执行**

---

## ⚠️ 注意事项

### 1. MCP Server 必须启动
AgentFlow 依赖金融研投助手的 MCP Server，必须先启动：
```bash
python -m app.mcp_server.server
```

### 2. 工具名格式变化
- 旧格式: `web_search`
- 新格式: `web_research.web_search` (skill.tool)

### 3. 部分工具暂不可用
以下 ToolExecutor 工具 MCP 中暂无：
- `bidding_search` (招投标搜索)
- `text2sql` (SQL查询)

如需使用，可：
- 继续使用 ToolExecutor 版本
- 或扩展 MCP Skills 添加

---

## 🎯 推荐使用场景

### 场景1: 基础金融查询
```
工具链: market_data.get_quote → web_research.web_search
用途: 查股价 + 查相关新闻
```

### 场景2: 深度财务分析
```
工具链: 
  market_data.get_quote
  → financial_analysis.get_financial_report
  → financial_analysis.calculate_financial_ratios
  → financial_analysis.compare_financials
用途: 全面分析一家公司
```

### 场景3: 投资研究
```
工具链:
  deep_research.research_plan
  → web_research.deep_search
  → data_analysis.analyze_data
  → risk_assessment.assess_risk
用途: 生成投资建议报告
```

---

## ✅ 验证清单

- [x] 分析调整后架构
- [x] 创建 MCP Backend v2
- [x] 实现所有 Skills 工具
- [x] 创建配置文件
- [ ] 启动 MCP Server 测试
- [ ] 运行数据合成验证
- [ ] 生成 GRPO 训练数据

---

## 📝 总结

金融研投助手调整后：
- **工具更丰富**: 25+ 个专业工具
- **数据更精确**: Tushare 专业数据源
- **分析更深入**: 完整财务 + 风险评估
- **研究更智能**: 自动规划 + 深度搜索

AgentFlow 集成方案已更新，支持新架构的所有功能！

---

*更新日期: 2026-03-15*
