# AgentFlow 测试与集成计划

## 📋 AgentFlow 核心概念理解

根据调研，AgentFlow 的工作流程如下：

```
┌─────────────────────────────────────────────────┐
│  Step 1: 启动 Sandbox Server                      │
│  - 提供工具执行环境                                │
│  - 监听端口（如 18890）                            │
│  - 加载环境配置                                    │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 2: Trajectory Sampling (轨迹采样)           │
│  - LLM Agent 探索环境                             │
│  - 从种子输入开始                                  │
│  - 每步提议工具调用                                │
│  - 执行工具并记录观察                              │
│  - 构建轨迹树                                     │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 3: Trajectory Selection (轨迹筛选)          │
│  - 评估轨迹质量                                   │
│  - 深度、丰富度、工具多样性                         │
│  - 选择高质量路径                                  │
└─────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────┐
│  Step 4: QA Synthesis (QA生成)                    │
│  - 生成问答对                                     │
│  - 基于轨迹的观察                                  │
│  - 质量检查                                       │
└─────────────────────────────────────────────────┘
```

## 🎯 我们的适配策略

### 方案 1: 轻量级模拟（不依赖 AgentFlow）

**核心思路**: 基于 AgentFlow 的设计理念，手动实现简化版的数据采集流程。

#### 1.1 创建 Sandbox Server（基于我们现有的 MCP Server）

```python
# financial_sandbox_server.py
"""
金融分析 Sandbox Server
模拟 AgentFlow 的 sandbox-server 功能
"""

import asyncio
import json
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.mcp_client.client import MCPClient

app = FastAPI(title="Financial Sandbox Server")

# 全局 MCP Client
mcp_client: MCPClient = None


class ToolCallRequest(BaseModel):
    """工具调用请求"""
    tool_name: str
    arguments: Dict[str, Any]


class ToolCallResponse(BaseModel):
    """工具调用响应"""
    success: bool
    result: Any
    error: str = None


@app.on_event("startup")
async def startup():
    """启动时连接 MCP Server"""
    global mcp_client
    import os
    server_path = os.path.join(
        os.path.dirname(__file__),
        "backend/app/mcp_server/server.py"
    )
    mcp_client = MCPClient(server_script_path=server_path)
    await mcp_client.connect()
    print("✅ MCP Client 已连接")


@app.on_event("shutdown")
async def shutdown():
    """关闭时断开连接"""
    if mcp_client:
        await mcp_client.disconnect()


@app.get("/tools")
async def list_tools():
    """列出所有可用工具"""
    result = await mcp_client.list_tools()
    if result.get("success"):
        return {
            "success": True,
            "tools": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["inputSchema"]
                }
                for tool in result["tools"]
            ]
        }
    else:
        raise HTTPException(status_code=500, detail=result.get("error"))


@app.post("/execute", response_model=ToolCallResponse)
async def execute_tool(request: ToolCallRequest):
    """执行工具调用"""
    result = await mcp_client.call_tool(request.tool_name, request.arguments)

    return ToolCallResponse(
        success=result.get("success", False),
        result=result.get("data"),
        error=result.get("error")
    )


@app.get("/reset")
async def reset_environment():
    """重置环境（可选）"""
    return {"success": True, "message": "Environment reset"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=18890)
```

#### 1.2 创建 Trajectory Sampler（轨迹采样器）

```python
# trajectory_sampler.py
"""
轨迹采样器 - 模拟 AgentFlow 的轨迹采样功能
"""

import asyncio
import json
import httpx
from typing import Dict, Any, List
from datetime import datetime

import dashscope
from dashscope import Generation


class TrajectorySampler:
    """轨迹采样器"""

    def __init__(
        self,
        sandbox_url: str = "http://localhost:18890",
        model: str = "qwen-max",
        max_depth: int = 10,
        branching_factor: int = 3
    ):
        self.sandbox_url = sandbox_url
        self.model = model
        self.max_depth = max_depth
        self.branching_factor = branching_factor
        self.tools = []

        # 配置 qwen
        dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

    async def initialize(self):
        """初始化：获取工具列表"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.sandbox_url}/tools")
            data = response.json()
            if data.get("success"):
                self.tools = data["tools"]
                print(f"✅ 发现 {len(self.tools)} 个工具")

    async def execute_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """执行工具"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.sandbox_url}/execute",
                json={
                    "tool_name": tool_name,
                    "arguments": arguments
                }
            )
            return response.json()

    def convert_tools_to_qwen_format(self) -> List[Dict]:
        """转换工具为 qwen function calling 格式"""
        qwen_tools = []
        for tool in self.tools:
            qwen_name = tool["name"].replace(".", "__")
            qwen_tools.append({
                "type": "function",
                "function": {
                    "name": qwen_name,
                    "description": tool["description"],
                    "parameters": tool["parameters"]
                }
            })
        return qwen_tools

    async def sample_trajectory(self, seed_question: str) -> Dict:
        """
        采样一条轨迹

        Args:
            seed_question: 种子问题

        Returns:
            轨迹数据
        """
        print(f"\n{'='*60}")
        print(f"🌱 种子问题: {seed_question}")
        print(f"{'='*60}")

        trajectory = {
            "seed_question": seed_question,
            "steps": [],
            "depth": 0,
            "timestamp": datetime.now().isoformat()
        }

        # 准备消息
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的金融分析师。使用提供的工具来回答用户问题。"
            },
            {
                "role": "user",
                "content": seed_question
            }
        ]

        qwen_tools = self.convert_tools_to_qwen_format()

        # 采样循环
        depth = 0
        while depth < self.max_depth:
            depth += 1
            print(f"\n🔄 深度 {depth}: 调用 qwen...")

            # 调用 qwen
            response = Generation.call(
                model=self.model,
                messages=messages,
                tools=qwen_tools,
                result_format='message'
            )

            if response.status_code != 200:
                print(f"❌ qwen 调用失败: {response.message}")
                break

            assistant_message = response.output.choices[0].message

            # 检查 tool_calls
            tool_calls = None
            if hasattr(assistant_message, 'get'):
                tool_calls = assistant_message.get('tool_calls')
            elif hasattr(assistant_message, 'tool_calls'):
                try:
                    tool_calls = assistant_message.tool_calls
                except (AttributeError, KeyError):
                    tool_calls = None

            # 将 assistant 消息加入历史
            messages.append({
                "role": "assistant",
                "content": assistant_message.get('content', '') if hasattr(assistant_message, 'get') else (assistant_message.content or ''),
                "tool_calls": tool_calls
            })

            if tool_calls:
                print(f"📞 qwen 请求调用 {len(tool_calls)} 个工具")

                for tool_call in tool_calls:
                    # 解析 tool_call
                    if isinstance(tool_call, dict):
                        function_name = tool_call['function']['name']
                        function_args = json.loads(tool_call['function']['arguments'])
                    else:
                        function_name = tool_call.function.name
                        function_args = json.loads(tool_call.function.arguments)

                    # 转换回 MCP tool name
                    mcp_tool_name = function_name.replace("__", ".")

                    print(f"  🔧 {mcp_tool_name}")
                    print(f"     参数: {json.dumps(function_args, ensure_ascii=False)}")

                    # 执行工具
                    tool_result = await self.execute_tool(mcp_tool_name, function_args)

                    # 记录轨迹
                    trajectory["steps"].append({
                        "depth": depth,
                        "tool": mcp_tool_name,
                        "arguments": function_args,
                        "result": tool_result.get("result"),
                        "success": tool_result.get("success", False)
                    })

                    # 将工具结果加入消息历史
                    messages.append({
                        "role": "tool",
                        "name": function_name,
                        "content": json.dumps(tool_result.get("result"), ensure_ascii=False)
                    })

                # 继续下一轮
                continue

            else:
                # 没有 tool_calls，生成了最终回答
                final_answer = assistant_message.get('content', '') if hasattr(assistant_message, 'get') else (assistant_message.content or '')
                trajectory["final_answer"] = final_answer
                trajectory["depth"] = depth
                print(f"\n✅ 完成采样 (深度: {depth})")
                break

        return trajectory

    async def sample_multiple(self, seed_questions: List[str]) -> List[Dict]:
        """采样多条轨迹"""
        trajectories = []
        for question in seed_questions:
            trajectory = await self.sample_trajectory(question)
            trajectories.append(trajectory)
        return trajectories


async def main():
    """主函数"""
    # 种子问题
    seed_questions = [
        "查一下茅台近期的股市表现，值不值得买",
        "分析一下平安银行的财务状况",
        "比较腾讯和阿里巴巴近一年的财务指标"
    ]

    # 创建采样器
    sampler = TrajectorySampler()
    await sampler.initialize()

    # 采样轨迹
    trajectories = await sampler.sample_multiple(seed_questions)

    # 保存轨迹
    with open("trajectories.jsonl", "w") as f:
        for traj in trajectories:
            f.write(json.dumps(traj, ensure_ascii=False) + "\n")

    print(f"\n{'='*60}")
    print(f"✅ 采样完成！共 {len(trajectories)} 条轨迹")
    print(f"保存至: trajectories.jsonl")
    print(f"{'='*60}")


if __name__ == "__main__":
    import os
    asyncio.run(main())
```

#### 1.3 创建 Trajectory Selector（轨迹筛选器）

```python
# trajectory_selector.py
"""
轨迹筛选器 - 评估和筛选高质量轨迹
"""

import json
from typing import Dict, Any, List


class TrajectorySelector:
    """轨迹筛选器"""

    def __init__(
        self,
        min_depth: int = 2,
        min_tool_diversity: int = 2,
        top_k: int = 100
    ):
        self.min_depth = min_depth
        self.min_tool_diversity = min_tool_diversity
        self.top_k = top_k

    def calculate_score(self, trajectory: Dict) -> float:
        """
        计算轨迹质量得分

        评估指标：
        1. 深度得分 (Depth Score): 工具调用步数
        2. 信息丰富度 (Information Richness): 结果数据量
        3. 工具多样性 (Tool Diversity): 不同工具数量
        """
        steps = trajectory.get("steps", [])

        # 1. 深度得分（归一化到 0-1）
        depth = trajectory.get("depth", 0)
        depth_score = min(depth / 10.0, 1.0)  # 最多10步

        # 2. 工具多样性
        unique_tools = len(set(step["tool"] for step in steps))
        diversity_score = min(unique_tools / 5.0, 1.0)  # 最多5个不同工具

        # 3. 成功率
        success_count = sum(1 for step in steps if step.get("success"))
        success_rate = success_count / len(steps) if steps else 0

        # 4. 信息丰富度（基于结果长度）
        total_info = sum(
            len(json.dumps(step.get("result", {})))
            for step in steps
        )
        info_score = min(total_info / 10000.0, 1.0)  # 归一化

        # 综合得分
        score = (
            0.3 * depth_score +
            0.3 * diversity_score +
            0.2 * success_rate +
            0.2 * info_score
        )

        return score

    def select(self, trajectories: List[Dict]) -> List[Dict]:
        """筛选轨迹"""
        print(f"\n{'='*60}")
        print(f"📊 轨迹筛选")
        print(f"{'='*60}")
        print(f"输入轨迹数: {len(trajectories)}")

        # 1. 过滤最小要求
        filtered = []
        for traj in trajectories:
            steps = traj.get("steps", [])
            unique_tools = len(set(step["tool"] for step in steps))

            if traj.get("depth", 0) >= self.min_depth and \
               unique_tools >= self.min_tool_diversity:
                filtered.append(traj)

        print(f"过滤后: {len(filtered)} 条 (深度≥{self.min_depth}, 工具多样性≥{self.min_tool_diversity})")

        # 2. 计算得分
        for traj in filtered:
            traj["quality_score"] = self.calculate_score(traj)

        # 3. 排序并选择 top-k
        sorted_traj = sorted(
            filtered,
            key=lambda t: t["quality_score"],
            reverse=True
        )
        selected = sorted_traj[:self.top_k]

        print(f"选择 top-{self.top_k}: {len(selected)} 条")
        print(f"\n得分分布:")
        if selected:
            print(f"  最高分: {selected[0]['quality_score']:.3f}")
            print(f"  最低分: {selected[-1]['quality_score']:.3f}")
            print(f"  平均分: {sum(t['quality_score'] for t in selected) / len(selected):.3f}")

        return selected


def main():
    """主函数"""
    # 读取轨迹
    trajectories = []
    with open("trajectories.jsonl", "r") as f:
        for line in f:
            trajectories.append(json.loads(line))

    # 筛选
    selector = TrajectorySelector(
        min_depth=2,
        min_tool_diversity=2,
        top_k=100
    )
    selected = selector.select(trajectories)

    # 保存
    with open("selected_trajectories.jsonl", "w") as f:
        for traj in selected:
            f.write(json.dumps(traj, ensure_ascii=False) + "\n")

    print(f"\n✅ 筛选完成！")
    print(f"保存至: selected_trajectories.jsonl")


if __name__ == "__main__":
    main()
```

#### 1.4 创建 QA Synthesizer（QA生成器）

```python
# qa_synthesizer.py
"""
QA 生成器 - 从轨迹生成训练数据
"""

import json
from typing import Dict, Any, List


class QASynthesizer:
    """QA 合成器"""

    def convert_to_training_format(self, trajectory: Dict) -> Dict:
        """
        将轨迹转换为训练格式

        格式：
        {
            "messages": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "tool_calls": [...]},
                {"role": "tool", "content": "..."},
                ...
                {"role": "assistant", "content": "..."}
            ]
        }
        """
        messages = [
            {"role": "user", "content": trajectory["seed_question"]}
        ]

        # 添加工具调用步骤
        for step in trajectory["steps"]:
            # Assistant 工具调用
            tool_name_qwen = step["tool"].replace(".", "__")
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "function": {
                        "name": tool_name_qwen,
                        "arguments": json.dumps(step["arguments"], ensure_ascii=False)
                    }
                }]
            })

            # Tool 返回结果
            messages.append({
                "role": "tool",
                "content": json.dumps(step["result"], ensure_ascii=False)
            })

        # 最终回答
        if "final_answer" in trajectory:
            messages.append({
                "role": "assistant",
                "content": trajectory["final_answer"]
            })

        return {
            "messages": messages,
            "quality_score": trajectory.get("quality_score", 0),
            "depth": trajectory.get("depth", 0)
        }

    def synthesize(self, trajectories: List[Dict]) -> List[Dict]:
        """批量生成训练数据"""
        training_data = []
        for traj in trajectories:
            training_data.append(self.convert_to_training_format(traj))
        return training_data


def main():
    """主函数"""
    # 读取筛选后的轨迹
    trajectories = []
    with open("selected_trajectories.jsonl", "r") as f:
        for line in f:
            trajectories.append(json.loads(line))

    # 生成训练数据
    synthesizer = QASynthesizer()
    training_data = synthesizer.synthesize(trajectories)

    # 保存
    with open("financial_agent_training_data.jsonl", "w") as f:
        for item in training_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"✅ 生成 {len(training_data)} 条训练数据")
    print(f"保存至: financial_agent_training_data.jsonl")


if __name__ == "__main__":
    main()
```

### 1.5 完整流程脚本

```bash
#!/bin/bash
# run_agentflow_pipeline.sh

echo "🚀 AgentFlow 数据合成流程"
echo "================================"

# Step 1: 启动 Sandbox Server
echo "Step 1: 启动 Sandbox Server..."
python financial_sandbox_server.py &
SANDBOX_PID=$!
sleep 5

# Step 2: 轨迹采样
echo "Step 2: 轨迹采样..."
python trajectory_sampler.py

# Step 3: 轨迹筛选
echo "Step 3: 轨迹筛选..."
python trajectory_selector.py

# Step 4: QA 生成
echo "Step 4: QA 生成..."
python qa_synthesizer.py

# 关闭 Sandbox Server
echo "清理..."
kill $SANDBOX_PID

echo "✅ 完成！"
echo "训练数据已保存至: financial_agent_training_data.jsonl"
```

---

## 🧪 测试计划

### Phase 1: 单步测试（本周）

1. **测试 Sandbox Server**
   ```bash
   python financial_sandbox_server.py
   # 访问 http://localhost:18890/docs 查看 API
   ```

2. **测试单条轨迹采样**
   ```python
   sampler = TrajectorySampler()
   await sampler.initialize()
   trajectory = await sampler.sample_trajectory("查一下茅台的股价")
   ```

3. **测试轨迹筛选**
   ```python
   selector = TrajectorySelector()
   selected = selector.select([trajectory])
   ```

### Phase 2: 小规模测试（下周）

1. 准备 10 个种子问题
2. 采样 10 条轨迹
3. 筛选和生成训练数据
4. 人工审核质量

### Phase 3: 大规模生成（2周后）

1. 准备 100 个种子问题
2. 采样 100-200 条轨迹
3. 筛选出 50-100 条高质量轨迹
4. 生成最终训练数据集

---

## 📊 预期输出

### 轨迹文件 (trajectories.jsonl)
```json
{
  "seed_question": "查一下茅台近期的股市表现",
  "steps": [
    {
      "depth": 1,
      "tool": "market_data.get_quote",
      "arguments": {"symbol": "600519"},
      "result": {...},
      "success": true
    },
    ...
  ],
  "final_answer": "...",
  "depth": 3
}
```

### 训练数据 (financial_agent_training_data.jsonl)
```json
{
  "messages": [
    {"role": "user", "content": "查一下茅台近期的股市表现"},
    {"role": "assistant", "tool_calls": [...]},
    {"role": "tool", "content": "..."},
    ...
  ],
  "quality_score": 0.85,
  "depth": 3
}
```

---

## 🎯 下一步

1. ⭐ **今天**: 实现 `financial_sandbox_server.py`
2. **明天**: 实现 `trajectory_sampler.py`
3. **后天**: 实现筛选和 QA 生成
4. **3天后**: 运行第一次完整测试
5. **1周后**: 生成第一批训练数据

---

## 💡 优势

相比直接使用 AgentFlow：

✅ **完全控制**: 了解每个步骤的细节
✅ **易于调试**: 可以打印和检查中间结果
✅ **灵活定制**: 可以针对金融场景优化
✅ **无依赖**: 不需要额外安装 AgentFlow
✅ **学习价值**: 理解 Agent 数据合成原理

---

## 📝 总结

这个方案基于 AgentFlow 的设计理念，但使用我们现有的技术栈实现。核心组件：

1. **Sandbox Server** - 基于 MCP Server
2. **Trajectory Sampler** - 基于 qwen + MCP Client
3. **Trajectory Selector** - 质量评估和筛选
4. **QA Synthesizer** - 转换为训练格式

这样既能学习 AgentFlow 的思想，又能完全控制数据生成过程。
