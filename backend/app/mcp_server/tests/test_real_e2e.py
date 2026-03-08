#!/usr/bin/env python3
"""
真实端到端测试脚本 - 真实调用 qwen LLM

测试场景：用户提问"查一下茅台近期的股市表现，值不值得买"
完整流程：
1. 启动 MCP Server，加载三个 skill，获取工具列表
2. 将 MCP 工具转换为 qwen function calling 格式
3. 调用 qwen 模型，传入用户问题和工具列表
4. qwen 模型自主决定调用哪些 skill 工具
5. 通过 MCP Client 执行 qwen 请求的工具调用
6. 将工具返回结果发送回 qwen
7. qwen 基于真实数据生成投资分析报告
8. 输出完整回答

配置：
- TUSHARE_API_TOKEN（从环境变量读取）
- TUSHARE_API_URL（从环境变量读取）
- DASHSCOPE_API_KEY（从环境变量读取）
"""

import os
import sys
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(PROJECT_ROOT)))
sys.path.insert(0, BACKEND_DIR)
print(f"添加路径: {BACKEND_DIR}")

# 设置环境变量
os.environ["TUSHARE_API_TOKEN"] = "9e4123cf56aaa553b06556e64b05e9d8d004340d82897eb1704ccd91c088"
os.environ["TUSHARE_API_URL"] = "http://lianghua.nanyangqiankun.top"
os.environ["DASHSCOPE_API_KEY"] = "sk-946dc6cdc78b40829f826a0ca3fb7382"
# MCP Client
from app.mcp_client.client import MCPClient

# DashScope (Qwen)
try:
    import dashscope
    from dashscope import Generation
    DASHSCOPE_AVAILABLE = True

    # 检查 API Key
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        print("❌ 错误: 未设置 DASHSCOPE_API_KEY 环境变量")
        print("请设置: export DASHSCOPE_API_KEY=your_api_key")
        DASHSCOPE_AVAILABLE = False
    else:
        dashscope.api_key = api_key
        print(f"✅ DashScope API Key 已配置: {api_key[:20]}...")

except ImportError:
    DASHSCOPE_AVAILABLE = False
    print("❌ 警告: dashscope 未安装")
    print("安装命令: pip install dashscope")


class RealE2ETester:
    """真实端到端测试器 - 使用真实的 qwen LLM"""

    def __init__(self):
        self.mcp_client: MCPClient = None
        self.tools_list: List[Dict] = []
        self.conversation_messages: List[Dict] = []
        self.tool_call_count = 0

    def mcp_tool_to_qwen_function(self, mcp_tool: Dict) -> Dict:
        """
        将 MCP 工具格式转换为 qwen function calling 格式

        MCP 格式:
        {
            "name": "market_data.get_quote",
            "description": "...",
            "inputSchema": {"type": "object", "properties": {...}, "required": [...]}
        }

        Qwen 格式:
        {
            "type": "function",
            "function": {
                "name": "market_data__get_quote",
                "description": "...",
                "parameters": {"type": "object", "properties": {...}, "required": [...]}
            }
        }
        """
        # qwen 的 function name 不能有 "."，用 "__" 替代
        qwen_name = mcp_tool["name"].replace(".", "__")

        return {
            "type": "function",
            "function": {
                "name": qwen_name,
                "description": mcp_tool["description"],
                "parameters": mcp_tool["inputSchema"]
            }
        }

    def qwen_function_to_mcp_tool(self, qwen_name: str) -> str:
        """将 qwen function name 转回 MCP tool name"""
        return qwen_name.replace("__", ".")
        
    async def setup(self):
        """初始化 MCP Client 并获取工具列表"""
        print("=" * 80)
        print("🔌 步骤 1: 初始化 MCP Client")
        print("=" * 80)

        server_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "server.py"
        )

        print(f"MCP Server 路径: {server_path}")
        print(f"Tushare Token: {os.environ.get('TUSHARE_API_TOKEN', '未设置')[:20]}...")
        print(f"Tushare URL: {os.environ.get('TUSHARE_API_URL', '未设置')}")

        self.mcp_client = MCPClient(server_script_path=server_path)
        connected = await self.mcp_client.connect()

        if not connected:
            raise RuntimeError("❌ MCP Client 连接失败")

        print("✅ MCP Client 连接成功")

        # 获取 MCP 工具列表
        tools_result = await self.mcp_client.list_tools()
        if not tools_result.get("success"):
            raise RuntimeError(f"❌ 获取工具列表失败: {tools_result.get('error')}")

        self.tools_list = tools_result.get("tools", [])
        print(f"\n📋 从 MCP Server 获取到 {len(self.tools_list)} 个工具:")
        for tool in self.tools_list:
            print(f"  • {tool['name']}: {tool['description'][:60]}...")

        return True
    
    async def call_mcp_tool(self, tool_name: str, arguments: Dict) -> Any:
        """调用 MCP 工具并记录"""
        self.tool_call_count += 1
        print(f"\n🔧 [{self.tool_call_count}] 调用 MCP 工具: {tool_name}")
        print(f"   参数: {json.dumps(arguments, ensure_ascii=False, indent=2)}")

        result = await self.mcp_client.call_tool(tool_name, arguments)

        if result.get("success"):
            print(f"   ✅ 成功")
            # 只显示数据的简短预览
            if "data" in result:
                data_str = json.dumps(result["data"], ensure_ascii=False)
                preview = data_str[:150] + "..." if len(data_str) > 150 else data_str
                print(f"   数据预览: {preview}")
            return result["data"]
        else:
            error = result.get("error", "未知错误")
            print(f"   ❌ 失败: {error}")
            return {"error": error}

    async def run_qwen_with_tools(self, user_question: str, max_iterations: int = 10) -> str:
        """
        真实调用 qwen 模型，使用 function calling

        Args:
            user_question: 用户问题
            max_iterations: 最大迭代次数（防止无限循环）

        Returns:
            qwen 生成的最终回答
        """
        if not DASHSCOPE_AVAILABLE:
            raise RuntimeError("❌ DashScope 不可用，无法调用 qwen 模型")

        print("\n" + "=" * 80)
        print("🤖 步骤 2: 调用 qwen 模型（真实 LLM）")
        print("=" * 80)
        print(f"用户问题: {user_question}")
        print(f"模型: qwen-max")
        print(f"可用工具: {len(self.tools_list)} 个")
        print()

        # 转换 MCP 工具为 qwen function 格式
        qwen_tools = [self.mcp_tool_to_qwen_function(tool) for tool in self.tools_list]

        # 初始化对话
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的金融投资分析师。你可以使用提供的工具来查询股票数据、分析财务指标和评估风险。请基于真实数据给出专业、客观的投资建议。"
            },
            {
                "role": "user",
                "content": user_question
            }
        ]

        iteration = 0
        while iteration < max_iterations:
            iteration += 1
            print(f"\n{'─' * 80}")
            print(f"🔄 迭代 {iteration}: 调用 qwen...")
            print(f"{'─' * 80}")

            # 调用 qwen
            try:
                response = Generation.call(
                    model="qwen-max",
                    messages=messages,
                    tools=qwen_tools,
                    result_format='message'
                )

                if response.status_code != 200:
                    raise RuntimeError(f"qwen API 调用失败: {response.code} - {response.message}")

                assistant_message = response.output.choices[0].message

                # 检查是否有 tool_calls（使用 get 方法避免 KeyError）
                tool_calls = None
                if hasattr(assistant_message, 'get'):
                    # 字典格式
                    tool_calls = assistant_message.get('tool_calls')
                elif hasattr(assistant_message, 'tool_calls'):
                    # 对象格式
                    try:
                        tool_calls = assistant_message.tool_calls
                    except (AttributeError, KeyError):
                        tool_calls = None

                # 将 assistant 消息加入对话历史
                messages.append({
                    "role": assistant_message.get('role', 'assistant') if hasattr(assistant_message, 'get') else assistant_message.role,
                    "content": assistant_message.get('content', '') if hasattr(assistant_message, 'get') else (assistant_message.content or ''),
                    "tool_calls": tool_calls
                })

                # 检查是否有 tool_calls
                if tool_calls:
                    print(f"📞 qwen 请求调用 {len(tool_calls)} 个工具:")

                    # 执行所有 tool calls
                    for tool_call in tool_calls:
                        # DashScope 返回的是字典格式
                        if isinstance(tool_call, dict):
                            function_name = tool_call['function']['name']
                            function_args = json.loads(tool_call['function']['arguments'])
                            tool_call_id = tool_call.get('id', '')
                        else:
                            # 对象格式
                            function_name = tool_call.function.name
                            function_args = json.loads(tool_call.function.arguments)
                            tool_call_id = tool_call.id

                        # 转换回 MCP tool name
                        mcp_tool_name = self.qwen_function_to_mcp_tool(function_name)

                        print(f"\n   工具: {mcp_tool_name}")
                        print(f"   参数: {json.dumps(function_args, ensure_ascii=False)}")

                        # 调用 MCP 工具
                        tool_result = await self.call_mcp_tool(mcp_tool_name, function_args)

                        # 将工具结果加入消息历史
                        messages.append({
                            "role": "tool",
                            "name": function_name,
                            "content": json.dumps(tool_result, ensure_ascii=False)
                        })

                    # 继续下一轮迭代，让 qwen 处理工具结果
                    continue

                else:
                    # 没有 tool_calls，说明 qwen 生成了最终回答
                    final_content = assistant_message.get('content', '') if hasattr(assistant_message, 'get') else (assistant_message.content or '')
                    print(f"\n✅ qwen 生成最终回答 (迭代 {iteration} 次)")
                    print(f"{'═' * 80}\n")
                    return final_content

            except Exception as e:
                print(f"❌ 调用 qwen 时出错: {e}")
                import traceback
                traceback.print_exc()
                raise

        # 达到最大迭代次数
        print(f"⚠️ 达到最大迭代次数 {max_iterations}，停止")
        return "抱歉，分析过程超时，请稍后重试。"
    
    async def cleanup(self):
        """清理资源"""
        if self.mcp_client:
            await self.mcp_client.disconnect()
            print("\n✅ MCP Client 已断开连接")

    async def run_full_test(self):
        """运行完整测试"""
        print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                      真实端到端测试 (Real E2E Test)                           ║
║                   qwen-max 模型 + MCP Tools + Tushare 真实数据                ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")

        try:
            # 步骤 1: 初始化 MCP Client
            await self.setup()

            # 步骤 2: 真实调用 qwen 模型
            user_question = "查一下茅台近期的股市表现，值不值得买"
            final_answer = await self.run_qwen_with_tools(user_question)

            # 步骤 3: 输出最终回答
            print("\n" + "=" * 80)
            print("📄 qwen 生成的投资分析报告")
            print("=" * 80)
            print(final_answer)
            print("\n" + "=" * 80)

            # 输出统计
            print("\n" + "=" * 80)
            print("📊 测试统计")
            print("=" * 80)
            print(f"总共调用 MCP 工具: {self.tool_call_count} 次")
            print()
            print("=" * 80)
            print("✅ 端到端测试完成！")
            print("=" * 80)

        finally:
            await self.cleanup()


async def main():
    """主函数"""
    tester = RealE2ETester()
    await tester.run_full_test()


if __name__ == "__main__":
    asyncio.run(main())
