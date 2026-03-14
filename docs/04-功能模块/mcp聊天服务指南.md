# MCP Chat Service 使用指南

## 概述

MCP Chat Service 是基于 MCP (Model Context Protocol) Tools 的聊天服务，它将 MCP Server 提供的金融分析工具与 qwen LLM 的 function calling 能力结合在一起，提供智能的金融投资分析。

## 架构

```
用户问题
  ↓
MCPChatService
  ├─→ 连接 MCP Server (获取14个工具)
  │   ├─ MarketDataSkill (8个工具): 行情、历史数据、公司信息、资金流向等
  │   ├─ FinancialAnalysisSkill (3个工具): 财报、财务指标、财报对比
  │   └─ RiskAssessmentSkill (3个工具): 风险评估、投资组合分析
  │
  ├─→ 转换为 qwen function calling 格式
  │
  ├─→ 调用 qwen-max LLM
  │   ├─ qwen 自主决定调用哪些工具
  │   ├─ 执行工具调用（获取真实 Tushare 数据）
  │   └─ 基于真实数据生成分析报告
  │
  └─→ 返回最终回答
```

## 快速开始

### 1. 作为独立服务使用

```python
from app.service.mcp_chat_service import MCPChatService

async def example():
    # 方式1: 使用上下文管理器（推荐）
    async with MCPChatService(model="qwen-max") as service:
        answer = await service.chat("查一下茅台近期的股市表现，值不值得买")
        print(answer)
```

### 2. 使用便捷函数

```python
from app.service.mcp_chat_service import mcp_chat

async def example():
    answer = await mcp_chat("分析一下平安银行的财务状况")
    print(answer)
```

### 3. 通过 API 调用

```bash
# 发送 POST 请求到 /chat/mcp
curl -X POST http://localhost:8000/chat/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "question": "查一下茅台近期的股市表现，值不值得买",
    "model": "qwen-max"
  }'
```

## API 端点

### POST /chat/mcp

使用 MCP Tools + qwen LLM 进行智能对话。

**请求体**:
```json
{
  "question": "用户问题",
  "session_id": "会话ID（可选）",
  "system_prompt": "系统提示词（可选）",
  "model": "qwen-max"
}
```

**响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "answer": "qwen 生成的回答",
    "session_id": "会话ID",
    "model": "qwen-max",
    "tools_available": 14,
    "tools_used": "由 qwen 自主决定"
  }
}
```

## 可用工具列表

### MarketDataSkill (市场数据)

1. **market_data.get_quote** - 获取实时行情
2. **market_data.search_stock** - 搜索股票
3. **market_data.get_history** - 获取历史K线
4. **market_data.get_stock_basic_info** - 获取基本信息
5. **market_data.get_top_list** - 获取龙虎榜
6. **market_data.get_money_flow** - 获取资金流向
7. **market_data.get_limit_list** - 获取涨跌停
8. **market_data.get_company_info** - 获取公司详情

### FinancialAnalysisSkill (财务分析)

1. **financial_analysis.get_financial_report** - 获取财报
2. **financial_analysis.calculate_financial_ratios** - 计算财务指标
3. **financial_analysis.compare_financial_data** - 对比财务数据

### RiskAssessmentSkill (风险评估)

1. **risk_assessment.assess_portfolio_risk** - 评估投资组合风险
2. **risk_assessment.calculate_risk_metrics** - 计算风险指标
3. **risk_assessment.generate_risk_report** - 生成风险报告

## 示例问题

### 股票分析
```
查一下茅台近期的股市表现，值不值得买
分析一下平安银行的财务状况
比较一下腾讯和阿里巴巴的财务指标
```

### 风险评估
```
帮我评估一下投资组合：茅台40%，平安30%，招商银行30%
计算一下宁德时代的风险指标
```

### 市场数据
```
查询今天的涨停股票有哪些
最近茅台的资金流向情况怎么样
```

## 工作流程

1. **用户提问**: 用户输入问题
2. **MCP 连接**: 服务连接到 MCP Server，获取14个工具
3. **工具转换**: 将 MCP 工具转换为 qwen function calling 格式
4. **LLM 决策**: qwen 根据问题自主决定调用哪些工具
5. **工具执行**: 通过 MCP Client 调用工具，获取真实数据
6. **结果返回**: 将工具结果返回给 qwen
7. **生成回答**: qwen 基于真实数据生成投资分析报告

## 核心优势

✅ **真实数据**: 所有数据来自 Tushare，保证准确性
✅ **智能决策**: qwen 自主决定调用哪些工具，无需硬编码
✅ **专业分析**: 基于真实数据生成专业的投资分析报告
✅ **易于扩展**: 新增工具只需在 MCP Server 注册即可
✅ **解耦架构**: MCP Server、LLM、后端服务完全解耦

## 技术栈

- **LLM**: qwen-max (阿里云 DashScope)
- **Tools**: MCP Server (MarketData, FinancialAnalysis, RiskAssessment)
- **Data Source**: Tushare (真实股票数据)
- **Protocol**: MCP (Model Context Protocol)
- **Architecture**: Function Calling

## 配置要求

### 环境变量

```bash
# DashScope API Key (qwen)
export DASHSCOPE_API_KEY="your_api_key"

# Tushare 配置
export TUSHARE_API_TOKEN="your_token"
export TUSHARE_API_URL="http://lianghua.nanyangqiankun.top"
```

### Python 依赖

```bash
pip install dashscope
pip install mcp
```

## 参考实现

- **测试脚本**: `backend/app/mcp_server/tests/test_real_e2e.py`
- **服务实现**: `backend/app/service/mcp_chat_service.py`
- **API 端点**: `backend/app/router/chat_router.py` (POST /chat/mcp)

## 注意事项

1. **API Key**: 确保配置了 DASHSCOPE_API_KEY
2. **网络**: MCP Server 需要能访问 Tushare API
3. **并发**: 同一时间只能有一个 MCP Client 连接
4. **超时**: 默认连接超时30秒，可通过参数调整
5. **迭代限制**: 最大 function calling 迭代次数为10次

## 故障排查

### 1. MCP Client 连接失败
- 检查 MCP Server 路径是否正确
- 检查 PYTHONPATH 是否包含 backend 目录
- 查看 `backend/app/mcp_server/mcp_server.log` 日志

### 2. qwen API 调用失败
- 检查 DASHSCOPE_API_KEY 是否正确
- 检查网络连接是否正常
- 查看 qwen API 配额是否充足

### 3. 工具调用失败
- 检查 Tushare Token 是否有效
- 检查 Tushare API URL 是否正常
- 查看工具参数是否正确

## 后续扩展

### 添加新工具
1. 在 MCP Server 的 Skill 中注册新工具
2. 无需修改 MCPChatService 代码
3. qwen 会自动发现并使用新工具

### 支持流式输出
目前 qwen 的 function calling 不支持流式输出，未来可考虑：
- 在每次工具调用后输出中间结果
- 最终回答使用流式输出

### 添加对话历史
```python
async with MCPChatService() as service:
    # 第一轮对话
    answer1 = await service.chat("查一下茅台的股价")

    # 第二轮对话（带历史）
    history = [
        {"role": "user", "content": "查一下茅台的股价"},
        {"role": "assistant", "content": answer1}
    ]
    answer2 = await service.chat(
        "那它值得买吗？",
        conversation_history=history
    )
```
