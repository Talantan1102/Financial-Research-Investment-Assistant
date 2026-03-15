# AgentFlow 金融研投助手 Backend

> 将金融研投助手工具集成到 AgentFlow 框架，用于 GRPO 训练数据合成

---

## 📋 项目概述

本项目实现了**方案A**：AgentFlow 适配金融研投助手的工具调用方式，确保训练数据和实际部署的数据分布完全一致。

### 核心特点

- **完全复用现有工具**：直接调用金融研投助手的 `ToolExecutor`，无需重新实现
- **接口格式一致**：工具名、参数、返回值与金融研投助手完全一致
- **即插即用**：AgentFlow 生成的数据可直接用于 GRPO 训练

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────────┐
│                    AgentFlow 数据合成                         │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │      AgentFlowFinanceBackend (本实现)                    │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │      FinanceResearchBackend (包装层)              │  │ │
│  │  │  ┌──────────────────────────────────────────┐   │  │ │
│  │  │  │   复用金融研投助手的 ToolExecutor          │   │  │ │
│  │  │  │   - web_search                           │   │  │ │
│  │  │  │   - knowledge_search                     │   │  │ │
│  │  │  │   - stock_query                          │   │  │ │
│  │  │  │   - text2sql                             │   │  │ │
│  │  │  │   - data_analyzer                        │   │  │ │
│  │  │  │   - chart_generator                      │   │  │ │
│  │  │  │   - bidding_search                       │   │  │ │
│  │  │  │   - finish                               │   │  │ │
│  │  │  └──────────────────────────────────────────┘   │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ↓ 生成的 trajectory 数据（格式完全一致）
┌─────────────────────────────────────────────────────────────┐
│                    GRPO 训练                                 │
│  数据格式: tool_name, params, result 与金融研投助手完全一致    │
└─────────────────────────────────────────────────────────────┘
                              ↓ 部署
┌─────────────────────────────────────────────────────────────┐
│                    金融研投助手 (生产环境)                     │
│  使用相同的 ToolExecutor，无缝接收训练好的模型                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 文件结构

```
AgentFlow/
├── sandbox/server/backends/resources/
│   └── finance_research.py          # Backend 实现（核心）
├── configs/sandbox-server/
│   └── finance_research_config.json # Sandbox 配置
├── configs/synthesis/
│   └── finance_research_config.json # 合成配置
├── seeds/finance_research/
│   └── seeds.jsonl                  # 种子数据
└── docs/
    └── finance_research_backend.md  # 本文档
```

---

## 🚀 快速开始

### 1. 环境准备

确保 deepresearch 环境已激活：

```bash
source ~/.bash_profile
conda activate deepresearch
```

### 2. 设置环境变量

```bash
# API Keys
export SEARCH_API_KEY="your_search_api_key"
export LLM_API_KEY="your_llm_api_key"
export LLM_BASE_URL="https://api.openai.com/v1"  # 或其他兼容端点

# 可选：数据库和 RAG 配置
export DB_CONNECTION_STRING="postgresql://..."
export RAG_KB_NAME="default"

# 金融研投助手路径（自动检测，如失败可手动设置）
export FRA_BACKEND_PATH="/Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend"
```

### 3. 启动 Sandbox Server

```bash
cd ~/.openclaw/workspace-dev/external/AgentFlow

python -m sandbox.server \
  configs/sandbox-server/finance_research_config.json
```

Server 将在 `http://127.0.0.1:18890` 启动。

### 4. 运行数据合成

```bash
# 另开终端，同样激活环境
source ~/.bash_profile
conda activate deepresearch

cd ~/.openclaw/workspace-dev/external/AgentFlow

python -m synthesis.run \
  configs/synthesis/finance_research_config.json
```

### 5. 查看结果

合成完成后，结果保存在：
- Trajectories: `results/finance_research/trajectories/`
- QA Pairs: `results/finance_research/qa/`

---

## 🛠️ 工具列表

| 工具名 | 功能 | 示例参数 |
|--------|------|---------|
| `web_search` | 网络搜索 | `{"query": "保险行业 2024", "count": 5}` |
| `knowledge_search` | 知识库搜索 | `{"query": "平安银行", "top_k": 5}` |
| `stock_query` | 股票查询 | `{"stock_code": "000001.SZ"}` |
| `bidding_search` | 招投标搜索 | `{"keyword": "保险系统", "category": "招标"}` |
| `text2sql` | SQL 查询 | `{"question": "查询总资产前10的公司"}` |
| `data_analyzer` | 数据分析 | `{"analysis_type": "trend"}` |
| `chart_generator` | 图表生成 | `{"chart_type": "bar", "title": "营收对比"}` |
| `finish` | 完成任务 | `{"summary": "..."}` |

---

## 🔧 高级配置

### 自定义 Seeds

编辑 `seeds/finance_research/seeds.jsonl`，每行一个 JSON：

```json
{"topic": "研究主题", "description": "研究描述"}
```

### 调整合成参数

编辑 `configs/synthesis/finance_research_config.json`：

```json
{
  "max_depth": 15,          // 最大搜索深度
  "branching_factor": 3,    // 每步分支数
  "max_selected_traj": 3,   // 选择的最佳轨迹数
  "sandbox_timeout": 120    // 工具调用超时时间
}
```

### 添加自定义工具

如需添加新工具，编辑 `finance_research.py`：

1. 在 `ToolExecutor` 中添加 handler
2. 在 Backend 中添加 action 方法
3. 更新 `get_tool_definitions()`

---

## 📊 数据格式

### Trajectory 示例

```json
{
  "trajectory_id": "traj_001",
  "seed": "保险行业发展趋势",
  "steps": [
    {
      "step": 1,
      "thought": {
        "reasoning": "需要了解保险行业最新动态...",
        "next_action": {
          "tool": "web_search",
          "params": {"query": "保险行业 2024年发展趋势", "count": 5}
        }
      },
      "observation": {
        "tool": "web_search",
        "success": true,
        "result": [...]
      }
    },
    {
      "step": 2,
      "thought": {
        "reasoning": "需要查询头部保险公司股价...",
        "next_action": {
          "tool": "stock_query",
          "params": {"stock_code": "601318.SH"}
        }
      },
      "observation": {
        "tool": "stock_query",
        "success": true,
        "result": {...}
      }
    }
  ]
}
```

### QA Pair 示例

```json
{
  "question": "分析保险行业2024年发展趋势...",
  "answer": "根据搜索数据，保险行业2024年...",
  "trajectory_id": "traj_001",
  "tools_used": ["web_search", "stock_query", "data_analyzer"]
}
```

---

## 🔄 与 GRPO 训练集成

### 数据转换

```python
from agentflow.synthesis import load_trajectories

# 加载生成的轨迹
trajectories = load_trajectories("results/finance_research/trajectories/")

# 转换为 GRPO 格式
for traj in trajectories:
    for step in traj.steps:
        grpo_sample = {
            "query": traj.seed,
            "tool_calls": [
                {
                    "tool": step.action.tool,
                    "params": step.action.params,
                    "result": step.observation.result
                }
            ]
        }
        # 保存或送入 GRPO 训练
```

### 直接使用

生成的数据格式与金融研投助手完全一致，可直接用于：
- SFT (Supervised Fine-Tuning)
- GRPO (Group Relative Policy Optimization)
- DPO (Direct Preference Optimization)

---

## 🐛 常见问题

### Q: 导入金融研投助手模块失败？

A: 检查 `FRA_BACKEND_PATH` 环境变量是否正确设置。

### Q: API Key 无效？

A: 确保 `SEARCH_API_KEY` 和 `LLM_API_KEY` 已正确设置。

### Q: RAG 搜索返回空结果？

A: 检查 `RAG_KB_NAME` 和知识库配置是否正确。

### Q: 如何调试单个工具？

A: 使用 `finance_research.py` 中的测试代码：

```python
async def test():
    backend = FinanceResearchBackend()
    await backend.initialize({...})
    result = await backend.action_web_search(query="测试")
    print(result)

asyncio.run(test())
```

---

## 📚 相关文档

- [金融研投助手改造方案](./金融研投助手改造方案.md)
- [AgentFlow README](../README.md)
- [金融研投助手原项目](../../financial-research-assistant/README.md)

---

## 🤝 贡献

如需扩展功能或修复问题，请修改：
- `sandbox/server/backends/resources/finance_research.py`
- `configs/synthesis/finance_research_config.json`

---

**最后更新**: 2026-03-15
