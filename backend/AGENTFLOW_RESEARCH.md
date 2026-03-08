# DataFlow 和 AgentFlow 项目调研报告

## 项目概述

根据探索，OpenDCAI 提供了两个相关的项目：

### 1. **DataFlow** - 通用数据准备框架
- **GitHub**: https://github.com/OpenDCAI/DataFlow
- **文档**: https://opendcai.github.io/DataFlow-Doc/
- **论文**: https://arxiv.org/html/2512.16676v1

**定位**: LLM 驱动的统一数据准备框架，用于数据清洗、处理、生成和评估。

**主要功能**:
- 从 noisy 源（PDF、纯文本、低质量 QA）解析、生成、处理、评估高质量数据
- 支持预训练、SFT、RL训练
- 支持 RAG 知识库清洗
- 基于 Operator 的架构，将规则、深度学习模型、LLMs 集成为 pipelines

### 2. **AgentFlow** - Agent 训练数据合成框架 ⭐ **最相关**
- **GitHub**: https://github.com/OpenDCAI/AgentFlow
- **类型**: 第一个统一的 Agent 数据合成框架

**定位**: 专门为 Agent/Tool Use 生成训练数据的框架。

---

## AgentFlow 深度分析（最适合我们项目）

### 核心特点

1. **专注 Agent 和 Tool Use**
   - 生成 agent trajectories（智能体轨迹）
   - 生成 reasoning traces（推理痕迹）
   - 生成 tool interactions（工具交互）
   - 生成 environment feedback（环境反馈）

2. **三阶段数据合成流程**

   ```
   ┌─────────────────────────────────────────────────────────┐
   │  Stage 1: Trajectory Sampling (轨迹采样)                  │
   │  LLM Agent 在沙盒环境中探索                                │
   │  - 从种子输入开始                                          │
   │  - 每步提议一个工具调用                                     │
   │  - 执行工具并记录观察                                       │
   │  - 构建分支轨迹树                                          │
   │  - 并发扩展 + 动作去重                                      │
   └─────────────────────────────────────────────────────────┘
                           ↓
   ┌─────────────────────────────────────────────────────────┐
   │  Stage 2: Trajectory Selection (轨迹筛选)                 │
   │  根据质量指标筛选轨迹                                       │
   │  - 深度评分                                               │
   │  - 信息丰富度                                             │
   │  - 工具多样性                                             │
   │  - 选择高质量路径                                          │
   └─────────────────────────────────────────────────────────┘
                           ↓
   ┌─────────────────────────────────────────────────────────┐
   │  Stage 3: QA Synthesis (QA对生成)                         │
   │  为每条选中路径生成QA对                                      │
   │  - 基于观察生成多跳、事实性QA                                │
   │  - 内置质量检查                                            │
   │  - 确保问答与工具调用轨迹对齐                                │
   └─────────────────────────────────────────────────────────┘
   ```

3. **模块化后端设计**
   - 易于扩展到新环境
   - 提供统一抽象层
   - 支持异构 agent 环境

4. **开箱即用**
   - 仅需几行代码即可合成复杂 agent 训练数据
   - 包含示例环境（如 WebAgent）

---

## 适合我们项目的原因

### ✅ 完美匹配

1. **解决我们的核心需求**
   - 我们需要：让模型在多轮对话中正确使用 MCP skill 工具
   - AgentFlow 专门生成：工具调用轨迹 + 多轮推理过程

2. **工具生态对齐**
   - 我们有：14个 MCP Tools（market_data、financial_analysis、risk_assessment）
   - AgentFlow 支持：自定义环境和工具集

3. **数据形式匹配**
   - 我们需要：多轮对话 + function calling 数据
   - AgentFlow 生成：
     - 用户问题 → LLM 思考 → 工具调用 → 工具结果 → LLM 回答
     - 完整的轨迹链路

4. **质量保证**
   - 三阶段筛选机制确保数据质量
   - 内置评分系统（深度、丰富度、多样性）

---

## 应用到我们项目的方案

### 方案 A: 使用 AgentFlow 生成训练数据

#### 步骤 1: 环境配置
```python
# 1. 安装 AgentFlow
pip install agentflow  # (假设名称)

# 2. 定义我们的 MCP 工具环境
class FinancialAgentEnv:
    """金融分析 Agent 环境"""

    def __init__(self):
        self.tools = [
            "market_data.get_quote",
            "market_data.get_history",
            "financial_analysis.calculate_financial_ratios",
            "risk_assessment.calculate_risk_metrics",
            # ... 其他14个工具
        ]
        self.mcp_client = MCPClient()

    def execute_tool(self, tool_name, arguments):
        """执行工具调用"""
        return self.mcp_client.call_tool(tool_name, arguments)

    def get_state(self):
        """获取当前环境状态"""
        return {
            "available_tools": self.tools,
            "conversation_history": []
        }
```

#### 步骤 2: 准备种子问题
```python
seed_questions = [
    "查一下茅台近期的股市表现，值不值得买",
    "分析一下平安银行的财务状况",
    "比较腾讯和阿里巴巴的财务指标",
    "评估投资组合：茅台40%，平安30%，招商30%",
    # ... 更多种子问题
]
```

#### 步骤 3: 运行数据合成
```python
from agentflow import AgentFlowPipeline

# 创建 pipeline
pipeline = AgentFlowPipeline(
    environment=FinancialAgentEnv(),
    seed_inputs=seed_questions,
    sampling_config={
        "max_depth": 10,  # 最大工具调用深度
        "branching_factor": 3,  # 分支因子
        "exploration_temperature": 0.8
    },
    selection_config={
        "min_depth": 3,  # 至少3步工具调用
        "min_tool_diversity": 2,  # 至少用2个不同工具
        "top_k": 100  # 选择前100条轨迹
    }
)

# 运行合成
trajectories = pipeline.run()

# 输出格式示例
for traj in trajectories:
    print(traj)
    # {
    #   "question": "查一下茅台近期的股市表现",
    #   "trajectory": [
    #     {"step": 1, "tool": "market_data.get_quote", "args": {"symbol": "600519"}, "result": {...}},
    #     {"step": 2, "tool": "market_data.get_history", "args": {"symbol": "600519"}, "result": {...}},
    #     {"step": 3, "tool": "financial_analysis.calculate_financial_ratios", "args": {...}, "result": {...}}
    #   ],
    #   "answer": "根据数据分析，茅台...",
    #   "quality_score": 0.92
    # }
```

#### 步骤 4: 转换为训练格式
```python
def convert_to_training_format(trajectory):
    """转换为 qwen function calling 训练格式"""
    messages = [
        {"role": "user", "content": trajectory["question"]}
    ]

    for step in trajectory["trajectory"]:
        # Assistant 工具调用
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "function": {
                    "name": step["tool"],
                    "arguments": json.dumps(step["args"])
                }
            }]
        })

        # Tool 返回结果
        messages.append({
            "role": "tool",
            "content": json.dumps(step["result"])
        })

    # 最终回答
    messages.append({
        "role": "assistant",
        "content": trajectory["answer"]
    })

    return {"messages": messages}

# 转换所有轨迹
training_data = [convert_to_training_format(t) for t in trajectories]

# 保存为 jsonl
with open("financial_agent_training_data.jsonl", "w") as f:
    for item in training_data:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
```

---

### 方案 B: 手动记录真实对话生成训练数据

如果 AgentFlow 集成复杂，可以先手动记录：

```python
# 1. 修改 MCPChatService，记录所有轨迹
class MCPChatServiceWithLogging(MCPChatService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trajectory = []

    async def call_mcp_tool(self, tool_name, arguments):
        result = await super().call_mcp_tool(tool_name, arguments)

        # 记录轨迹
        self.trajectory.append({
            "tool": tool_name,
            "arguments": arguments,
            "result": result,
            "timestamp": datetime.now().isoformat()
        })

        return result

    async def chat(self, user_question, *args, **kwargs):
        self.trajectory = []
        answer = await super().chat(user_question, *args, **kwargs)

        # 保存轨迹
        self.save_trajectory(user_question, answer)

        return answer

    def save_trajectory(self, question, answer):
        """保存为训练数据格式"""
        data = {
            "question": question,
            "trajectory": self.trajectory,
            "answer": answer,
            "timestamp": datetime.now().isoformat()
        }

        with open("trajectories.jsonl", "a") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
```

---

## 数据质量提升策略

### 1. 多样性保证
- 覆盖所有14个工具
- 不同复杂度的问题（1-10步工具调用）
- 不同类型的查询（行情、财务、风险）

### 2. 真实性保证
- 使用真实的 Tushare 数据
- 基于真实股票代码
- 基于真实市场场景

### 3. 质量筛选
- 工具调用逻辑正确
- 工具选择合理
- 回答与数据对齐
- 移除冗余或错误的轨迹

---

## 训练数据示例

### 示例 1: 简单查询（2步）
```json
{
  "messages": [
    {"role": "user", "content": "查一下茅台的股价"},
    {"role": "assistant", "tool_calls": [{"function": {"name": "market_data__get_quote", "arguments": "{\"symbol\": \"600519\"}"}}]},
    {"role": "tool", "content": "{\"price\": 1402.00, \"change\": 0.21}"},
    {"role": "assistant", "content": "茅台当前股价为1402.00元，涨幅0.21%"}
  ]
}
```

### 示例 2: 复杂分析（5步）
```json
{
  "messages": [
    {"role": "user", "content": "茅台值不值得买？"},
    {"role": "assistant", "tool_calls": [{"function": {"name": "market_data__get_quote", ...}}]},
    {"role": "tool", "content": "..."},
    {"role": "assistant", "tool_calls": [{"function": {"name": "market_data__get_history", ...}}]},
    {"role": "tool", "content": "..."},
    {"role": "assistant", "tool_calls": [{"function": {"name": "financial_analysis__calculate_financial_ratios", ...}}]},
    {"role": "tool", "content": "..."},
    {"role": "assistant", "tool_calls": [{"function": {"name": "risk_assessment__calculate_risk_metrics", ...}}]},
    {"role": "tool", "content": "..."},
    {"role": "assistant", "content": "综合分析，茅台...（完整分析报告）"}
  ]
}
```

---

## 推荐方案

### 🎯 **短期方案（1-2周）**
1. **手动记录 + 方案B**
   - 修改 MCPChatService 添加轨迹记录
   - 通过 API 收集100-200条真实对话轨迹
   - 人工筛选和清洗数据
   - 转换为训练格式

### 🚀 **中期方案（2-4周）**
2. **集成 AgentFlow**
   - 研究 AgentFlow 的 API 和使用方式
   - 实现 FinancialAgentEnv 环境适配器
   - 准备100个高质量种子问题
   - 运行 AgentFlow 生成1000-5000条训练数据
   - 质量筛选 + 人工审核

### 💎 **长期方案（1-2月）**
3. **持续数据收集 + 迭代训练**
   - 线上收集用户真实对话
   - 定期运行 AgentFlow 生成新数据
   - 基于反馈优化数据生成策略
   - 迭代微调模型

---

## 预期效果

### 训练前
- ❌ 模型可能不知道何时调用工具
- ❌ 可能调用错误的工具
- ❌ 参数格式不正确
- ❌ 工具调用顺序混乱

### 训练后
- ✅ 准确理解用户意图
- ✅ 智能选择合适工具
- ✅ 正确构造工具参数
- ✅ 合理的工具调用链
- ✅ 基于真实数据生成专业回答

---

## 技术栈

### 现有
- qwen-max (LLM)
- MCP Server (14 tools)
- Tushare (数据源)

### 新增
- **AgentFlow** (数据合成) ⭐
- 或 **DataFlow** (数据处理)
- 训练数据管理系统
- 质量评估工具

---

## 后续行动

1. ⭐ **立即**: 克隆 AgentFlow 仓库，研究 README 和示例
2. **本周**: 实现方案B（手动记录），开始收集数据
3. **下周**: 评估 AgentFlow 是否适合，尝试简单集成
4. **2周后**: 决定最终方案，开始大规模数据生成

---

## 参考资源

- **AgentFlow GitHub**: https://github.com/OpenDCAI/AgentFlow
- **DataFlow GitHub**: https://github.com/OpenDCAI/DataFlow
- **DataFlow 文档**: https://opendcai.github.io/DataFlow-Doc/
- **论文**: https://arxiv.org/html/2512.16676v1
- **Agent-Data Governance**: https://opendcai.github.io/DataFlow-Doc/en/guide/agent/agent_for_data/

---

## 总结

**AgentFlow 是目前最适合我们项目的工具**，它专门为 Agent 和 Tool Use 设计，能够自动生成高质量的多轮对话 + function calling 训练数据。建议：

1. 先实现方案B快速收集数据
2. 并行研究 AgentFlow 的集成方案
3. 评估后选择最优路径
4. 目标：生成1000-5000条高质量训练数据用于模型微调
