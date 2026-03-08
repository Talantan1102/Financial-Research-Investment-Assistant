# 基于 AgentFlow 的金融研投助手数据构造方案

> **核心思路**：利用 AgentFlow 框架自动化生成高质量的多工具调用轨迹数据
>
> **框架选择**：AgentFlow - 首个统一的 Agent 数据合成框架
>
> **目标**：生成 3,000-5,000 条 GRPO 训练数据

---

## 一、AgentFlow 简介

### 1.1 什么是 AgentFlow？

AgentFlow 是一个**统一的 Agent 数据合成框架**，专门用于生成高质量的训练和评估数据。它提供：

- 📊 **轨迹采样（Trajectory Sampling）**：自动探索工具调用空间
- 🎯 **轨迹筛选（Trajectory Selection）**：选出高质量轨迹
- 💬 **QA 合成（QA Synthesis）**：生成问答对
- 🔧 **All-in-One 沙盒**：统一的工具执行环境

### 1.2 AgentFlow 的三阶段流程

```
┌──────────────────────────────────────────────────────────┐
│                   AgentFlow Pipeline                      │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  阶段1: Trajectory Sampling (轨迹采样)                     │
│  ┌─────────┐    ┌──────────────┐    ┌────────────────┐   │
│  │  Seed   │───▶│ LLM Agent    │───▶│ Trajectory Tree│   │
│  │ (种子)  │    │ (探索工具)   │    │  (轨迹树)      │   │
│  └─────────┘    └──────────────┘    └────────────────┘   │
│       │                                                   │
│       ▼                                                   │
│  阶段2: Trajectory Selection (轨迹筛选)                    │
│  ┌────────────────┐    ┌──────────────────────────────┐   │
│  │ Trajectory Tree│───▶│ 评分 + 去重 + 多样性筛选     │   │
│  └────────────────┘    └──────────────────────────────┘   │
│       │                            │                      │
│       ▼                            ▼                      │
│  阶段3: QA Synthesis (问答合成)                            │
│  ┌────────────────┐    ┌──────────┐    ┌─────────────┐   │
│  │ Selected Paths │───▶│   LLM    │───▶│  QA Pairs   │   │
│  │  (筛选路径)    │    │ (生成QA) │    │ + Trajectory│   │
│  └────────────────┘    └──────────┘    └─────────────┘   │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

---

## 二、为什么选择 AgentFlow？

### 2.1 解决的核心问题

传统的模板生成方式存在问题：
- ❌ **人工设计模板工作量大**：每个场景都要手写
- ❌ **覆盖度有限**：难以覆盖所有工具组合
- ❌ **缺乏真实性**：模板化数据可能过于机械

AgentFlow 的优势：
- ✅ **自动探索**：LLM 自动探索工具调用空间
- ✅ **高覆盖度**：通过树形扩展覆盖多种路径
- ✅ **质量保证**：自动筛选和评分机制
- ✅ **可扩展**：易于添加新工具

### 2.2 与训练计划的匹配

| GRPO 训练需求 | AgentFlow 如何满足 |
|--------------|-------------------|
| 多轮对话数据 | Trajectory 自动记录多轮工具调用 |
| 工具调用轨迹 | TrajectorySampler 生成完整轨迹树 |
| 高质量数据 | TrajectorySelector 筛选 + 评分 |
| 数据多样性 | 树形扩展 + branching_factor |
| 大规模生成 | 批量处理 seeds |

---

## 三、适配金融研投助手

### 3.1 架构对比

**AgentFlow RAGAgent 示例：**
```
工具: rag_search
环境: RAG Backend (E5 + Faiss)
流程: Seed → 检索 → QA生成
```

**金融研投助手：**
```
工具: market_data.*, financial_analysis.*, risk_assessment.*, deep_research.*
环境: Financial Sandbox (MCP Tools)
流程: Seed → 多工具调用 → QA生成
```

### 3.2 需要适配的组件

| 组件 | AgentFlow 原实现 | 金融助手适配 |
|------|-----------------|-------------|
| **Sandbox Backend** | RAG Backend | FinancialBackend (基于 MCP) |
| **Tools** | `rag_search` | `market_data.*`, `financial_analysis.*` 等 17 个工具 |
| **Seeds** | 知识库话题 | 股票代码、财务分析场景等 |
| **QA Examples** | RAG 问答示例 | 金融分析问答示例 |

---

## 四、实施方案

### 4.1 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│         Financial Research Assistant × AgentFlow            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: 启动 Financial Sandbox Server                       │
│  ┌──────────────────────────┐                               │
│  │ financial_sandbox_config │──▶ MCP Tools as Sandbox Tools  │
│  └──────────────────────────┘                               │
│           │                                                 │
│           ▼                                                 │
│  Step 2: Trajectory Sampling (轨迹采样)                       │
│  ┌────────────┐    ┌─────────────┐    ┌────────────────┐    │
│  │  Seeds     │───▶│ LLM Agent   │───▶│ Trajectory Tree│    │
│  │ (股票/场景) │    │ (调用工具)  │    │  (多轮轨迹)    │    │
│  └────────────┘    └─────────────┘    └────────────────┘    │
│           │                                                 │
│           ▼                                                 │
│  Step 3: Trajectory Selection (轨迹筛选)                      │
│  ┌────────────────┐    ┌──────────────────────┐             │
│  │ Trajectory Tree│───▶│ 按深度/工具数/多样性  │             │
│  └────────────────┘    │    筛选最优路径      │             │
│                       └──────────────────────┘             │
│           │                                                 │
│           ▼                                                 │
│  Step 4: QA Synthesis (问答合成)                              │
│  ┌────────────────┐    ┌──────────┐    ┌──────────────┐     │
│  │ Selected Paths │───▶│   LLM    │───▶│  QA + Traj   │     │
│  └────────────────┘    └──────────┘    └──────────────┘     │
│                                               │             │
│                                               ▼             │
│                                      GRPO 训练数据集         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 目录结构

```
financial-research-assistant/
├── agentflow_integration/          # AgentFlow 集成
│   ├── sandbox/                    # 金融沙盒实现
│   │   ├── financial_backend.py    # Financial Sandbox Backend
│   │   └── server_config.json      # 沙盒服务配置
│   ├── configs/                    # 配置文件
│   │   ├── synthesis/
│   │   │   └── financial_config.json  # 数据合成配置
│   │   └── trajectory/
│   │       └── financial_trajectory.json  # 轨迹生成配置
│   ├── seeds/                      # 种子数据
│   │   ├── stock_seeds.jsonl       # 股票种子
│   │   ├── scenario_seeds.jsonl    # 场景种子
│   │   └── mixed_seeds.jsonl       # 混合种子
│   └── scripts/                    # 脚本
│       ├── run_synthesis.py        # 运行数据合成
│       └── convert_to_grpo.py      # 转换为 GRPO 格式
└── data/                           # 输出数据
    ├── synthesized/                # AgentFlow 原始输出
    │   ├── synthesized_qa.jsonl
    │   └── trajectories.jsonl
    └── grpo_format/                # GRPO 训练格式
        ├── train_3000.jsonl
        ├── val_300.jsonl
        └── test_300.jsonl
```

---

## 五、详细实施步骤

### Step 1: 实现 Financial Sandbox Backend

#### 1.1 创建 FinancialBackend 类

**文件：`agentflow_integration/sandbox/financial_backend.py`**

```python
"""
Financial Sandbox Backend
将金融研投助手的 MCP Tools 适配为 AgentFlow Sandbox Backend
"""

import asyncio
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

# 假设我们已经有 MCPChatService
from financial_research_assistant.services.mcp_chat_service import MCPChatService


class FinancialBackend:
    """
    金融沙盒后端
    将 MCP Tools 包装为 AgentFlow 可用的工具
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化金融沙盒

        Args:
            config: 配置字典，包含：
                - mcp_config_path: MCP 配置文件路径
                - available_skills: 可用的 skills 列表
        """
        self.config = config
        self.mcp_service = None
        self.available_skills = config.get("available_skills", [
            "market_data",
            "financial_analysis",
            "risk_assessment",
            "deep_research"
        ])

    async def initialize(self, session_config: Optional[Dict[str, Any]] = None):
        """初始化 MCP 服务"""
        print(f"🔧 Initializing Financial Backend...")
        print(f"   Available skills: {self.available_skills}")

        # 初始化 MCPChatService
        self.mcp_service = MCPChatService(
            mcp_config_path=self.config.get("mcp_config_path"),
            skills=self.available_skills
        )

        await self.mcp_service.initialize()
        print("✅ Financial Backend initialized")

    async def cleanup(self):
        """清理资源"""
        if self.mcp_service:
            await self.mcp_service.cleanup()

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具调用

        Args:
            tool_name: 工具名称，格式为 "skill_name.tool_name"
                      例如: "market_data.get_quote"
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        if not self.mcp_service:
            raise RuntimeError("Backend not initialized")

        try:
            # 解析工具名
            if "." in tool_name:
                skill, tool = tool_name.split(".", 1)
            else:
                # 如果没有指定 skill，尝试自动匹配
                skill, tool = self._match_tool(tool_name)

            # 调用 MCP 工具
            result = await self.mcp_service.call_mcp_tool(
                tool_name=f"{skill}/{tool}",
                arguments=arguments
            )

            return {
                "success": True,
                "result": result,
                "tool": tool_name,
                "arguments": arguments
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "tool": tool_name,
                "arguments": arguments
            }

    def _match_tool(self, tool_name: str) -> tuple[str, str]:
        """
        自动匹配工具所属的 skill

        Args:
            tool_name: 工具名称

        Returns:
            (skill_name, tool_name)
        """
        # 工具映射表（根据实际 MCP 配置调整）
        tool_mapping = {
            # market_data skill
            "get_quote": "market_data",
            "search_stock": "market_data",
            "get_history": "market_data",
            "get_stock_basic_info": "market_data",
            "get_top_list": "market_data",
            "get_money_flow": "market_data",
            "get_limit_list": "market_data",
            "get_company_info": "market_data",

            # financial_analysis skill
            "get_financial_report": "financial_analysis",
            "calculate_financial_ratios": "financial_analysis",
            "compare_financial_data": "financial_analysis",

            # risk_assessment skill
            "assess_portfolio_risk": "risk_assessment",
            "calculate_risk_metrics": "risk_assessment",
            "generate_risk_report": "risk_assessment",

            # deep_research skill
            "research_stream": "deep_research",
            "research_sync": "deep_research",
            "quick_research": "deep_research",
        }

        skill = tool_mapping.get(tool_name)
        if not skill:
            raise ValueError(f"Unknown tool: {tool_name}")

        return skill, tool_name

    def get_available_tools(self) -> List[str]:
        """获取所有可用工具列表"""
        # 根据 available_skills 返回工具列表
        tools = []

        skill_tools = {
            "market_data": [
                "get_quote", "search_stock", "get_history",
                "get_stock_basic_info", "get_top_list",
                "get_money_flow", "get_limit_list", "get_company_info"
            ],
            "financial_analysis": [
                "get_financial_report", "calculate_financial_ratios",
                "compare_financial_data"
            ],
            "risk_assessment": [
                "assess_portfolio_risk", "calculate_risk_metrics",
                "generate_risk_report"
            ],
            "deep_research": [
                "research_stream", "research_sync", "quick_research"
            ]
        }

        for skill in self.available_skills:
            for tool in skill_tools.get(skill, []):
                tools.append(f"{skill}.{tool}")

        return tools
```

#### 1.2 配置沙盒服务器

**文件：`agentflow_integration/sandbox/server_config.json`**

```json
{
  "server": {
    "url": "http://127.0.0.1:18890",
    "port": 18890,
    "session_ttl": 600
  },
  "resources": {
    "financial": {
      "enabled": true,
      "description": "Financial Research Assistant Tools (MCP-based)",
      "backend_class": "agentflow_integration.sandbox.financial_backend.FinancialBackend",
      "config": {
        "mcp_config_path": "configs/mcp_config.json",
        "available_skills": [
          "market_data",
          "financial_analysis",
          "risk_assessment",
          "deep_research"
        ]
      }
    }
  },
  "warmup": {
    "enabled": true,
    "resources": ["financial"]
  }
}
```

---

### Step 2: 准备 Seeds（种子数据）

#### 2.1 Seed 的作用

Seed 是 AgentFlow 探索的起点。对于金融助手，一个好的 seed 应该：
- ✅ 触发有意义的工具调用序列
- ✅ 覆盖不同的使用场景
- ✅ 涵盖各种股票/行业

#### 2.2 三类 Seeds 设计

**A. 股票种子（Stock Seeds）**

**文件：`agentflow_integration/seeds/stock_seeds.jsonl`**

```jsonl
{"content": "贵州茅台 600519", "kwargs": {"focus": "comprehensive_analysis"}}
{"content": "平安银行 000001", "kwargs": {"focus": "comprehensive_analysis"}}
{"content": "比亚迪 002594", "kwargs": {"focus": "comprehensive_analysis"}}
{"content": "宁德时代 300750", "kwargs": {"focus": "comprehensive_analysis"}}
{"content": "中国平安 601318", "kwargs": {"focus": "comprehensive_analysis"}}
{"content": "五粮液 000858", "kwargs": {"focus": "comprehensive_analysis"}}
{"content": "招商银行 600036", "kwargs": {"focus": "comprehensive_analysis"}}
{"content": "隆基绿能 601012", "kwargs": {"focus": "comprehensive_analysis"}}
```

**B. 场景种子（Scenario Seeds）**

**文件：`agentflow_integration/seeds/scenario_seeds.jsonl`**

```jsonl
{"content": "分析白酒行业龙头股的投资价值", "kwargs": {"industry": "白酒"}}
{"content": "评估新能源汽车板块的风险", "kwargs": {"industry": "新能源汽车"}}
{"content": "对比银行股的财务指标", "kwargs": {"industry": "银行"}}
{"content": "寻找高ROE的消费股", "kwargs": {"criteria": "high_roe"}}
{"content": "评估科创板龙头的成长性", "kwargs": {"board": "科创板"}}
{"content": "分析半导体行业的投资机会", "kwargs": {"industry": "半导体"}}
{"content": "筛选低估值高股息的蓝筹股", "kwargs": {"criteria": "value_dividend"}}
{"content": "评估医药股的长期投资价值", "kwargs": {"industry": "医药"}}
```

**C. 任务种子（Task Seeds）**

**文件：`agentflow_integration/seeds/task_seeds.jsonl`**

```jsonl
{"content": "构建一个均衡的投资组合", "kwargs": {"task_type": "portfolio_construction"}}
{"content": "找出近期资金流入最多的股票", "kwargs": {"task_type": "money_flow_analysis"}}
{"content": "分析今天的涨停股有哪些共同特征", "kwargs": {"task_type": "pattern_analysis"}}
{"content": "评估茅台和五粮液哪个更值得投资", "kwargs": {"task_type": "comparative_analysis"}}
{"content": "深度研究比亚迪的竞争优势", "kwargs": {"task_type": "deep_research"}}
```

#### 2.3 Seeds 生成策略

**数量分配（总 1000 个 seeds）：**

| Seed 类型 | 数量 | 目的 |
|----------|-----|------|
| 股票种子 | 500 | 覆盖不同股票的分析场景 |
| 场景种子 | 300 | 覆盖不同投资策略和行业 |
| 任务种子 | 200 | 覆盖复杂多步骤任务 |

**生成脚本：`agentflow_integration/scripts/generate_seeds.py`**

```python
"""生成大量 seeds 的脚本"""

import json
from pathlib import Path

# A股常见股票池（按行业分类）
STOCK_POOL = {
    "白酒": [
        ("贵州茅台", "600519"),
        ("五粮液", "000858"),
        ("泸州老窖", "000568"),
        ("洋河股份", "002304"),
    ],
    "银行": [
        ("招商银行", "600036"),
        ("平安银行", "000001"),
        ("兴业银行", "601166"),
        ("宁波银行", "002142"),
    ],
    "新能源": [
        ("宁德时代", "300750"),
        ("比亚迪", "002594"),
        ("隆基绿能", "601012"),
        ("阳光电源", "300274"),
    ],
    # ... 更多行业
}

# 分析场景模板
SCENARIO_TEMPLATES = [
    "分析{industry}行业的投资机会",
    "评估{industry}板块的风险收益比",
    "对比{industry}龙头股的财务表现",
    "寻找{industry}中的价值洼地",
]

# 任务模板
TASK_TEMPLATES = [
    "构建一个{risk_level}风险的投资组合",
    "找出{metric}最高的10只股票",
    "分析{stock1}和{stock2}哪个更值得投资",
    "深度研究{company}的商业模式",
]

def generate_stock_seeds(output_path: str, count: int = 500):
    """生成股票种子"""
    seeds = []
    all_stocks = []

    for industry, stocks in STOCK_POOL.items():
        all_stocks.extend(stocks)

    # 循环生成直到达到目标数量
    for i in range(count):
        stock = all_stocks[i % len(all_stocks)]
        name, code = stock

        seeds.append({
            "content": f"{name} {code}",
            "kwargs": {"focus": "comprehensive_analysis"}
        })

    with open(output_path, "w", encoding="utf-8") as f:
        for seed in seeds:
            f.write(json.dumps(seed, ensure_ascii=False) + "\n")

    print(f"✅ Generated {len(seeds)} stock seeds → {output_path}")

# 类似地实现 generate_scenario_seeds 和 generate_task_seeds
# ...
```

---

### Step 3: 配置数据合成

**文件：`agentflow_integration/configs/synthesis/financial_config.json`**

```json
{
  "model_name": "gpt-4-turbo-2024-04-09",
  "api_key": "${OPENAI_API_KEY}",
  "base_url": "https://api.openai.com/v1",

  "max_depth": 8,
  "branching_factor": 2,
  "depth_threshold": 3,

  "min_depth": 3,
  "max_selected_traj": 3,
  "path_similarity_threshold": 0.7,

  "resource_types": ["financial"],
  "sandbox_server_url": "http://127.0.0.1:18890",
  "sandbox_auto_start": true,
  "sandbox_config_path": "agentflow_integration/sandbox/server_config.json",
  "sandbox_timeout": 120,

  "available_tools": [
    "market_data.get_quote",
    "market_data.search_stock",
    "market_data.get_history",
    "market_data.get_stock_basic_info",
    "market_data.get_top_list",
    "market_data.get_money_flow",
    "market_data.get_limit_list",
    "market_data.get_company_info",
    "financial_analysis.get_financial_report",
    "financial_analysis.calculate_financial_ratios",
    "financial_analysis.compare_financial_data",
    "risk_assessment.assess_portfolio_risk",
    "risk_assessment.calculate_risk_metrics",
    "risk_assessment.generate_risk_report",
    "deep_research.research_sync",
    "deep_research.quick_research"
  ],

  "sampling_tips": [
    "# Sampling Guidance for Financial Analysis",
    "",
    "## Your Role",
    "You are a professional financial research assistant helping investors analyze stocks and make investment decisions.",
    "",
    "## Available Tools",
    "- Market data tools: get stock quotes, historical prices, money flow, etc.",
    "- Financial analysis tools: get financial reports, calculate ratios, compare data",
    "- Risk assessment tools: evaluate portfolio risk, calculate risk metrics",
    "- Deep research tools: conduct comprehensive research on companies",
    "",
    "## Exploration Strategy",
    "1. Start with basic information (stock quote, basic info)",
    "2. Deep dive into fundamentals (financial reports, ratios)",
    "3. Assess risks (volatility, beta, max drawdown)",
    "4. Consider market factors (money flow, top list)",
    "5. Synthesize insights for investment decisions",
    "",
    "## Quality Guidelines",
    "- Use multiple tools to build comprehensive analysis",
    "- Ensure data accuracy (correct stock codes)",
    "- Build logical reasoning chains",
    "- Provide actionable investment insights"
  ],

  "synthesis_tips": [
    "# QA Synthesis Guidance",
    "",
    "## Question Types",
    "- Simple queries: \"What's the current price of Moutai?\"",
    "- Financial analysis: \"Is Moutai's financial health good?\"",
    "- Risk assessment: \"How risky is investing in Moutai?\"",
    "- Comparative analysis: \"Moutai vs Wuliangye, which is better?\"",
    "- Investment decisions: \"Should I buy Moutai now?\"",
    "",
    "## Answer Requirements",
    "- Grounded in retrieved data (no hallucination)",
    "- Include specific numbers and metrics",
    "- Provide clear reasoning",
    "- Give actionable recommendations",
    "",
    "## Multi-hop Reasoning",
    "Prefer questions that require multiple steps:",
    "- Step 1: Get current price",
    "- Step 2: Check financial ratios",
    "- Step 3: Assess risk",
    "- Conclusion: Investment recommendation"
  ],

  "qa_examples": [
    {
      "question": "茅台现在的股价是多少？",
      "answer": "根据最新行情数据，贵州茅台(600519)当前股价为1850.50元，今日上涨1.39%，成交量为5.2万手。"
    },
    {
      "question": "茅台的财务健康度如何？",
      "answer": "根据最新财报分析，茅台的财务状况非常健康：ROE为20.5%，毛利率高达91.3%，净利率为52.1%，资产负债率仅为15.2%。这表明公司盈利能力强，财务结构稳健。"
    },
    {
      "question": "投资茅台的风险大吗？",
      "answer": "根据过去一年的数据分析，茅台的年化波动率为28.5%，Beta为0.85，最大回撤为-15.3%。相比市场平均水平，茅台属于中等风险水平，但考虑到其稳定的基本面，风险收益比较为合理。"
    }
  ],

  "seed_description": "Stock ticker with company name (e.g., '贵州茅台 600519'), industry description, or investment task description",

  "seeds_file": "agentflow_integration/seeds/mixed_seeds.jsonl",
  "output_dir": "data/synthesized",

  "number_of_seed": null
}
```

---

### Step 4: 运行数据合成

**文件：`agentflow_integration/scripts/run_synthesis.py`**

```python
"""
运行 AgentFlow 数据合成
"""

import asyncio
import sys
from pathlib import Path

# 添加 AgentFlow 到 Python 路径
agentflow_path = Path(__file__).resolve().parents[3] / "AgentFlow"
sys.path.insert(0, str(agentflow_path))

from synthesis import synthesize

async def main():
    """运行数据合成"""
    config_path = "agentflow_integration/configs/synthesis/financial_config.json"

    print("="*80)
    print("🚀 Financial Research Assistant - Data Synthesis")
    print("="*80)

    # 运行合成
    await synthesize(config_path=config_path)

    print("\n✅ Synthesis completed!")

if __name__ == "__main__":
    asyncio.run(main())
```

**运行命令：**

```bash
# 1. 启动沙盒服务器（在单独的终端）
cd /path/to/AgentFlow
./start_sandbox_server.sh --config ../financial-research-assistant/agentflow_integration/sandbox/server_config.json

# 2. 运行数据合成（在另一个终端）
cd financial-research-assistant
python agentflow_integration/scripts/run_synthesis.py
```

---

### Step 5: 转换为 GRPO 格式

AgentFlow 输出的格式需要转换为 GRPO 训练所需的格式。

**文件：`agentflow_integration/scripts/convert_to_grpo.py`**

```python
"""
将 AgentFlow 输出转换为 GRPO 训练格式
"""

import json
from pathlib import Path
from typing import List, Dict, Any

def convert_agentflow_to_grpo(
    qa_file: str,
    traj_file: str,
    output_file: str
):
    """
    转换 AgentFlow 输出为 GRPO 格式

    Args:
        qa_file: synthesized_qa.jsonl
        traj_file: trajectories.jsonl
        output_file: GRPO 格式输出文件
    """

    # 加载轨迹数据（用于匹配）
    trajectories = {}
    with open(traj_file, "r", encoding="utf-8") as f:
        for line in f:
            traj = json.loads(line)
            # 假设 traj 有唯一ID
            traj_id = traj.get("trajectory_id") or traj.get("source_id")
            trajectories[traj_id] = traj

    # 转换 QA 数据
    grpo_samples = []

    with open(qa_file, "r", encoding="utf-8") as f:
        for line in f:
            qa_pair = json.loads(line)

            # 获取对应的轨迹
            traj_id = qa_pair.get("trajectory_id") or qa_pair.get("source_id")
            trajectory = trajectories.get(traj_id, {})

            # 构造 GRPO 格式
            grpo_sample = convert_single_sample(qa_pair, trajectory)
            grpo_samples.append(grpo_sample)

    # 保存
    with open(output_file, "w", encoding="utf-8") as f:
        for sample in grpo_samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"✅ Converted {len(grpo_samples)} samples → {output_file}")

def convert_single_sample(
    qa_pair: Dict[str, Any],
    trajectory: Dict[str, Any]
) -> Dict[str, Any]:
    """
    转换单个样本为 GRPO 格式

    Args:
        qa_pair: AgentFlow QA pair
        trajectory: AgentFlow trajectory

    Returns:
        GRPO 格式样本
    """

    # 提取 QA
    question = qa_pair.get("question", "")
    answer = qa_pair.get("answer", "")

    # 提取轨迹
    path = trajectory.get("path", [])

    # 构造 messages
    messages = []

    # 用户问题
    messages.append({
        "role": "user",
        "content": question
    })

    # 工具调用轨迹
    for step in path:
        tool_name = step.get("tool", "")
        arguments = step.get("arguments", {})
        result = step.get("result", "")

        # Assistant 调用工具
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{step.get('step_id', 0)}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments, ensure_ascii=False)
                }
            }]
        })

        # Tool 返回结果
        messages.append({
            "role": "tool",
            "tool_call_id": f"call_{step.get('step_id', 0)}",
            "content": json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
        })

    # 最终回答
    messages.append({
        "role": "assistant",
        "content": answer,
        "tool_calls": None
    })

    # 构造完整样本
    grpo_sample = {
        "id": qa_pair.get("id", ""),
        "task_type": classify_task_type(path),
        "difficulty": estimate_difficulty(path),
        "quality_tier": "SILVER",  # AgentFlow 生成的默认为 SILVER

        "messages": messages,

        "metadata": {
            "tools_used": [step.get("tool") for step in path],
            "tool_count": len(path),
            "verifiable": True,
            "source": "agentflow"
        }
    }

    return grpo_sample

def classify_task_type(path: List[Dict]) -> str:
    """根据工具调用路径分类任务类型"""
    tool_count = len(path)

    if tool_count <= 1:
        return "SIMPLE_QUERY"
    elif tool_count <= 3:
        return "MEDIUM_ANALYSIS"
    else:
        return "COMPLEX_RESEARCH"

def estimate_difficulty(path: List[Dict]) -> str:
    """估算难度"""
    tool_count = len(path)

    if tool_count <= 2:
        return "EASY"
    elif tool_count <= 4:
        return "MEDIUM"
    else:
        return "HARD"

if __name__ == "__main__":
    convert_agentflow_to_grpo(
        qa_file="data/synthesized/synthesized_qa.jsonl",
        traj_file="data/synthesized/trajectories.jsonl",
        output_file="data/grpo_format/train.jsonl"
    )
```

---

## 六、数据质量控制

### 6.1 AgentFlow 自动质量控制

AgentFlow 内置的质量控制机制：

| 机制 | 说明 |
|------|------|
| **深度筛选** | `min_depth=3` 确保至少3步工具调用 |
| **多样性控制** | `path_similarity_threshold=0.7` 去除相似路径 |
| **评分排序** | 按深度、信息丰富度、工具多样性评分 |
| **Top-K 选择** | `max_selected_traj=3` 每个 seed 最多选3条路径 |

### 6.2 人工质量检查

**抽检流程：**

```python
# 文件：agentflow_integration/scripts/quality_check.py

import json
import random

def sample_for_review(input_file: str, sample_size: int = 100):
    """随机抽样用于人工审核"""

    with open(input_file, "r") as f:
        all_samples = [json.loads(line) for line in f]

    # 随机抽样
    samples = random.sample(all_samples, min(sample_size, len(all_samples)))

    # 保存到审核文件
    with open("data/review/samples_for_review.jsonl", "w") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")

    print(f"✅ Sampled {len(samples)} for review")
```

**审核标准：**

| 维度 | 评分标准 (0-5分) |
|------|----------------|
| **工具调用正确性** | 工具选择是否合理？参数是否正确？ |
| **推理连贯性** | 工具调用顺序是否符合逻辑？ |
| **答案准确性** | 答案是否基于工具结果？有无幻觉？ |
| **答案完整性** | 是否回答了问题？是否遗漏关键信息？ |

**质量分级：**

```python
def grade_sample(scores: Dict[str, int]) -> str:
    """
    根据评分结果分级

    Returns:
        "GOLD" / "SILVER" / "BRONZE" / "REJECT"
    """
    avg_score = sum(scores.values()) / len(scores)

    if avg_score >= 4.5:
        return "GOLD"
    elif avg_score >= 3.5:
        return "SILVER"
    elif avg_score >= 2.5:
        return "BRONZE"
    else:
        return "REJECT"
```

---

## 七、数据规模规划

### 7.1 目标数据量

| 数据集 | 数量 | 用途 |
|--------|-----|------|
| 训练集 | 3,000 | GRPO 训练 |
| 验证集 | 300 | 超参数调优 |
| 测试集 | 300 | 最终评估 |
| **总计** | **3,600** | |

### 7.2 Seeds 到 Samples 的转换率

假设参数配置：
- `max_selected_traj = 3`：每个 seed 最多产生 3 条轨迹
- 质量筛选通过率：70%

计算：
```
需要的 Seeds 数 = 3,600 / (3 × 0.7) ≈ 1,715 seeds
```

**保守估计，准备 2,000 个 seeds**

### 7.3 Seeds 分配

| Seed 类型 | 数量 | 预期产出 |
|----------|-----|---------|
| 股票种子 | 1,000 | ~2,100 |
| 场景种子 | 600 | ~1,260 |
| 任务种子 | 400 | ~840 |
| **总计** | **2,000** | **~4,200** (筛选后 3,600) |

---

## 八、时间和成本估算

### 8.1 运行时间估算

假设：
- 平均每个 seed 需要采样 8 步（`max_depth=8`）
- 每步工具调用 + LLM 推理约 3 秒
- `branching_factor=2`，平均生成 12 个节点

**单个 seed 时间**：
```
12 nodes × 3 sec = 36 sec
加上 QA 合成（LLM 调用）：10 sec
总计：~50 sec/seed
```

**总时间**：
```
2,000 seeds × 50 sec = 100,000 sec ≈ 27.8 小时
```

**优化方案**：
- 使用并行处理（`max_workers=10`）
- 实际时间：~3-5 小时

### 8.2 成本估算

假设使用 GPT-4-Turbo：
- 输入：$10 / 1M tokens
- 输出：$30 / 1M tokens

**单个 seed 消耗**：
- 采样阶段：~20K tokens（输入 + 输出）
- QA 合成：~5K tokens
- 总计：~25K tokens/seed

**总成本**：
```
2,000 seeds × 25K tokens = 50M tokens
成本 ≈ $500 - $750
```

**降本方案**：
- 使用更便宜的模型（如 GPT-3.5、Qwen）进行采样
- 只用 GPT-4 进行 QA 合成和质量检查
- 预计成本可降至：**$200 - $300**

---

## 九、完整工作流总结

```bash
# === 准备阶段 ===

# 1. 生成 seeds
python agentflow_integration/scripts/generate_seeds.py

# 2. 启动沙盒服务器
cd /path/to/AgentFlow
./start_sandbox_server.sh --config ../financial-research-assistant/agentflow_integration/sandbox/server_config.json

# === 数据合成阶段 ===

# 3. 运行 AgentFlow 合成
cd financial-research-assistant
python agentflow_integration/scripts/run_synthesis.py

# 输出：
#   - data/synthesized/synthesized_qa.jsonl
#   - data/synthesized/trajectories.jsonl

# === 质量控制阶段 ===

# 4. 抽样审核
python agentflow_integration/scripts/quality_check.py

# 5. 人工审核（在 review/ 目录）
# - 标记质量等级（GOLD/SILVER/BRONZE/REJECT）

# === 格式转换阶段 ===

# 6. 转换为 GRPO 格式
python agentflow_integration/scripts/convert_to_grpo.py

# 输出：
#   - data/grpo_format/train_3000.jsonl
#   - data/grpo_format/val_300.jsonl
#   - data/grpo_format/test_300.jsonl

# === 训练阶段 ===

# 7. GRPO 训练
# （参考 GRPO_TRAINING_PLAN.md）
```

---

## 十、优势总结

### 10.1 相比手工模板方法

| 维度 | 手工模板 | AgentFlow |
|------|---------|-----------|
| 开发成本 | 高（需设计大量模板） | 低（自动探索） |
| 覆盖度 | 有限（依赖模板设计） | 高（树形扩展） |
| 数据多样性 | 中（模板变体） | 高（自动发现新路径） |
| 真实性 | 低（机械化） | 高（LLM 自然推理） |
| 可扩展性 | 低（新工具需新模板） | 高（自动适配新工具） |

### 10.2 核心优势

1. **自动化**：无需手工设计每个场景的工具调用序列
2. **高质量**：内置多层质量控制（深度筛选、去重、评分）
3. **可控性**：通过 config 精确控制生成参数
4. **可追溯**：完整保留轨迹数据，便于分析和调试
5. **框架成熟**：AgentFlow 已在多个领域验证有效

---

## 十一、下一步行动

### Phase 1: 基础设施搭建（Week 1）

- [ ] 实现 FinancialBackend
- [ ] 配置沙盒服务器
- [ ] 测试 MCP 工具调用
- [ ] 生成初始 100 个 seeds
- [ ] 小规模测试（10 seeds）

### Phase 2: 数据生成（Week 2-3）

- [ ] 生成完整 2,000 seeds
- [ ] 运行完整合成流程
- [ ] 质量检查和筛选
- [ ] 转换为 GRPO 格式

### Phase 3: GRPO 训练（Week 4-6）

- [ ] 参考 `GRPO_TRAINING_PLAN.md`
- [ ] 配置训练环境
- [ ] 运行训练
- [ ] 评估模型

---

## 附录：配置文件参数详解

### A. Synthesis Config 关键参数

| 参数 | 默认值 | 说明 | 调优建议 |
|------|-------|------|---------|
| `max_depth` | 5 | 轨迹树最大深度 | 金融场景建议 8-10 |
| `branching_factor` | 2 | 每步扩展分支数 | 保持 2（平衡质量和成本） |
| `depth_threshold` | 3 | 开始分支的深度 | 建议 3（前期线性探索） |
| `min_depth` | 2 | 最小轨迹深度 | 建议 3（确保多步推理） |
| `max_selected_traj` | 3 | 每个 seed 最多选择轨迹数 | 建议 3（数据多样性） |
| `path_similarity_threshold` | 0.7 | 路径去重阈值 | 0.6-0.8 |

### B. Sampling Tips 模板

见配置文件中的 `sampling_tips` 字段，可根据实际需要调整，指导 LLM agent 如何探索工具空间。

---

**文档版本**：v1.0
**创建时间**：2026-03-08
**作者**：AI Training Team
**状态**：待评审
