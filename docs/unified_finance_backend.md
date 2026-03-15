# 统一版金融研投助手 Backend

## 概述

统一版 Backend (`unified_finance.py`) 提供与金融研投助手 MCP Server **完全一致**的调用方式：

```python
# 统一接口
await backend.execute_skill_tool(
    skill_name='market_data',
    tool_name='get_quote',
    arguments={'symbol': '600519'}
)
```

## 支持的 Skills

| Skill | 工具数 | 功能 |
|-------|--------|------|
| **market_data** | 11 | 市场行情数据（行情、K线、龙虎榜等） |
| **financial_analysis** | 7 | 财务分析（财报、财务比率等） |
| **sector_analysis** | 7 | 行业分析（行业列表、概念股等） |
| **risk_assessment** | 3 | 风险评估（组合风险、风险指标等） |
| **data_analysis** | 4 | 数据分析（分析、图表、SQL等） |
| **web_research** | 5 | 网络研究（搜索、知识库等） |
| **deep_research** | 7 | 深度研究（研报生成，分步执行） |

**总计：7个 Skill，40个工具**

## 使用方式

### 1. 启动 Sandbox

```bash
cd ~/.openclaw/workspace-dev/external/AgentFlow

# 激活环境
source ~/.bash_profile
conda activate deepresearch

# 启动统一版 Backend
/opt/miniconda3/envs/deepresearch/bin/python -m sandbox.server \
  configs/sandbox-server/unified_finance_config.json
```

### 2. 运行数据合成

```bash
# 另开终端
/opt/miniconda3/envs/deepresearch/bin/python -m synthesis.run \
  configs/synthesis/unified_finance_config.json
```

## 工具调用示例

### 市场行情数据

```python
# 获取实时行情
await backend.execute_skill_tool(
    skill_name='market_data',
    tool_name='get_quote',
    arguments={'symbol': '600519'}
)

# 搜索股票
await backend.execute_skill_tool(
    skill_name='market_data',
    tool_name='search_stock',
    arguments={'keyword': '茅台'}
)

# 获取历史K线
await backend.execute_skill_tool(
    skill_name='market_data',
    tool_name='get_history',
    arguments={'symbol': '600519', 'period': 'daily', 'limit': 100}
)
```

### 财务分析

```python
# 获取财务报表
await backend.execute_skill_tool(
    skill_name='financial_analysis',
    tool_name='get_financial_report',
    arguments={'symbol': '600519', 'report_type': 'income'}
)

# 计算财务比率
await backend.execute_skill_tool(
    skill_name='financial_analysis',
    tool_name='calculate_financial_ratios',
    arguments={'symbol': '600519', 'ratios': ['roe', 'roa']}
)
```

### 行业分析

```python
# 获取行业列表
await backend.execute_skill_tool(
    skill_name='sector_analysis',
    tool_name='get_industry_list',
    arguments={}
)

# 对比行业估值
await backend.execute_skill_tool(
    skill_name='sector_analysis',
    tool_name='compare_industry_valuation',
    arguments={'industries': ['银行', '保险', '证券']}
)
```

### 深度研究

```python
# 规划研究大纲
result = await backend.execute_skill_tool(
    skill_name='deep_research',
    tool_name='plan',
    arguments={'query': '茅台投资价值分析'}
)
session_id = result['result']['session_id']

# 搜索信息
await backend.execute_skill_tool(
    skill_name='deep_research',
    tool_name='search',
    arguments={'session_id': session_id, 'section_id': 'section_1'}
)

# 分析数据
await backend.execute_skill_tool(
    skill_name='deep_research',
    tool_name='analyze',
    arguments={'session_id': session_id}
)

# 撰写报告
await backend.execute_skill_tool(
    skill_name='deep_research',
    tool_name='write',
    arguments={'session_id': session_id}
)
```

## 与旧版对比

| 特性 | 基础版 (finance_research) | MCP增强版 (mcp_enhanced) | **统一版 (unified)** |
|------|--------------------------|-------------------------|-------------------|
| **调用方式** | 独立方法 `action_*` | 独立方法 `action_*` | **统一接口 `execute_skill_tool`** |
| **Skill数量** | 0（ToolExecutor） | 3 | **7** |
| **工具数量** | 8 | 16 | **40** |
| **与MCP Server一致性** | ❌ | ⚠️ 部分 | ✅ **完全一致** |
| **适用场景** | 简单查询 | 增强查询 | **完整研究** |

## 配置文件

### 合成配置

`configs/synthesis/unified_finance_config.json`:

```json
{
  "available_tools": ["unified_finance:execute_skill_tool"],
  "skill_tools_mapping": {
    "market_data": ["get_quote", "search_stock", ...],
    "financial_analysis": ["get_financial_report", ...],
    ...
  }
}
```

### 沙盒配置

`configs/sandbox-server/unified_finance_config.json`:

```json
{
  "backend": "sandbox.server.backends.resources.unified_finance.AgentFlowUnifiedFinanceBackend",
  "name": "unified_finance"
}
```

## 注意事项

1. **Tushare Token**：使用 market_data 等需要 Tushare 的 Skill 时，需要设置环境变量
   ```bash
   export TUSHARE_API_TOKEN="your_token"
   export TUSHARE_API_URL="http://lianghua.nanyangqiankun.top"
   ```

2. **Deep Research**：deep_research Skill 需要多步调用（plan → search → analyze → write）

3. **参数格式**：arguments 必须是字典，即使某些工具不需要参数也要传 `{}`

## 测试

```bash
# 快速测试
/opt/miniconda3/envs/deepresearch/bin/python \
  sandbox/server/backends/resources/unified_finance.py
```