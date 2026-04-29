"""MCP Server - 金融研投助手主入口

实现3轮交互流程：
- Round 1: Skill选择 → LLM根据意图选Skills
- Round 2: 工具调用 → 支持控制流
- Round 3: 生成回复 → 结构化报告
"""

import json
from dataclasses import dataclass
from typing import Any

from app.mcp_server.control_flow.engine import (
    ControlFlowEngine,
    ControlFlowType,
)
from app.mcp_server.error_handler import get_error_handler
from app.mcp_server.skills.base import BaseSkill
from app.mcp_server.skills.data_analysis import DataAnalysisSkill
from app.mcp_server.skills.deep_research import DeepResearchSkill
from app.mcp_server.skills.financial_analysis import FinancialAnalysisSkill
from app.mcp_server.skills.market_data import MarketDataSkill
from app.mcp_server.skills.risk_assessment import RiskAssessmentSkill
from app.mcp_server.skills.sector_analysis import SectorAnalysisSkill
from app.mcp_server.skills.web_research import WebResearchSkill


@dataclass
class SkillInfo:
    """Skill信息"""

    name: str
    description: str
    tools_count: int
    use_when: str
    skill_class: type


class FinancialResearchMCPServer:
    """金融研投助手 MCP Server"""

    # 7个Skill定义
    SKILLS = {
        "market_data": SkillInfo(
            name="market_data",
            description="股票市场行情数据查询，提供实时股价、PE/PB估值、历史K线、资金流向等",
            tools_count=11,
            use_when="用户询问股价、估值、行情数据、历史走势等",
            skill_class=MarketDataSkill,
        ),
        "financial_analysis": SkillInfo(
            name="financial_analysis",
            description="财务报表分析，计算ROE、ROA、毛利率、净利率等财务指标",
            tools_count=7,
            use_when="用户询问财务状况、盈利能力、三张报表等",
            skill_class=FinancialAnalysisSkill,
        ),
        "sector_analysis": SkillInfo(
            name="sector_analysis",
            description="行业与概念板块分析，支持行业对比、龙头识别、估值对比",
            tools_count=7,
            use_when="用户询问行业分析、板块对比、龙头股票等",
            skill_class=SectorAnalysisSkill,
        ),
        "risk_assessment": SkillInfo(
            name="risk_assessment",
            description="投资风险评估，评估个股风险等级、提供预警",
            tools_count=5,
            use_when="用户关注风险、需要风险评估时",
            skill_class=RiskAssessmentSkill,
        ),
        "deep_research": SkillInfo(
            name="deep_research",
            description="深度研究报告生成，综合多维度数据生成研报",
            tools_count=3,
            use_when="用户需要深度研报、综合分析时使用",
            skill_class=DeepResearchSkill,
        ),
        "web_research": SkillInfo(
            name="web_research",
            description="网络信息搜索，获取新闻、公告、研报等外部信息",
            tools_count=4,
            use_when="用户需要最新资讯、新闻、公告时使用",
            skill_class=WebResearchSkill,
        ),
        "data_analysis": SkillInfo(
            name="data_analysis",
            description="数据分析与可视化，支持统计分析、趋势预测、图表生成",
            tools_count=6,
            use_when="用户需要数据分析、图表展示时使用",
            skill_class=DataAnalysisSkill,
        ),
    }

    def __init__(self):
        self.skill_instances: dict[str, BaseSkill] = {}
        self.control_flow_engine: ControlFlowEngine | None = None
        self.error_handler = get_error_handler()
        self._init_skills()
        self._init_control_flow()

    def _init_skills(self):
        """初始化所有Skill实例"""
        for name, info in self.SKILLS.items():
            self.skill_instances[name] = info.skill_class()

    def _init_control_flow(self):
        """初始化控制流引擎"""
        self.control_flow_engine = ControlFlowEngine(self._execute_skill_tool)

    async def _execute_skill_tool(
        self, skill_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """执行Skill工具"""
        if skill_name not in self.skill_instances:
            return {"success": False, "error": f"Skill '{skill_name}' 不存在"}

        skill = self.skill_instances[skill_name]

        if not skill.has_tool(tool_name):
            return {"success": False, "error": f"工具 '{tool_name}' 不存在于 Skill '{skill_name}'"}

        try:
            result = await skill.execute_tool(tool_name, arguments)
            return result.to_dict()
        except Exception as e:
            error_info = self.error_handler.handle_error(e, f"{skill_name}.{tool_name}")
            return {
                "success": False,
                "error": error_info.message,
                "error_type": error_info.error_type.value,
                "error_code": error_info.error_code,
            }

    # ==================== Round 1: Skill选择 ====================

    def get_available_skills(self) -> list[dict[str, Any]]:
        """获取可用的Skills列表（供LLM选择）"""
        return [
            {
                "name": name,
                "description": info.description,
                "tools_count": info.tools_count,
                "use_when": info.use_when,
            }
            for name, info in self.SKILLS.items()
        ]

    def get_skill_selection_prompt(self, user_message: str) -> str:
        """生成Skill选择的Prompt"""
        skills_info = json.dumps(self.get_available_skills(), ensure_ascii=False, indent=2)

        prompt = f"""你是一个金融研究助手，通过调用MCP工具帮助用户分析股票。

你可以使用以下Skills:
{skills_info}

用户消息: "{user_message}"

分析用户需求，选择合适的Skill(s)。可以单选、多选或不选（直接回答）。

请以JSON格式输出：
{{
    "selected_skills": ["skill_name1", "skill_name2"],
    "execution_strategy": {{
        "type": "complex_chain",
        "description": "执行策略描述",
        "estimated_steps": 3
    }},
    "reasoning": "选择这些Skills的理由"
}}

如果不需要使用任何Skill，输出：
{{
    "selected_skills": [],
    "direct_response": "直接回答用户的内容",
    "reasoning": "为什么不需要使用工具"
}}
"""
        return prompt

    # ==================== Round 2: 工具调用 ====================

    def get_tools_for_skills(self, skill_names: list[str]) -> dict[str, Any]:
        """获取指定Skills的工具列表"""
        result = {}
        for name in skill_names:
            if name in self.skill_instances:
                skill = self.skill_instances[name]
                result[name] = {
                    "tools": [
                        {
                            "name": tool_name,
                            "description": skill._tool_definitions[tool_name].description,
                            "parameters": [
                                {
                                    "name": param.name,
                                    "type": param.type,
                                    "required": param.required,
                                    "description": param.description,
                                }
                                for param in skill._tool_definitions[tool_name].parameters
                            ],
                        }
                        for tool_name in skill._tools
                    ]
                }
        return result

    def get_tool_execution_prompt(
        self,
        user_message: str,
        selected_skills: list[str],
        target_stock: dict[str, str] | None = None,
    ) -> str:
        """生成工具执行的Prompt"""
        tools_info = json.dumps(
            self.get_tools_for_skills(selected_skills), ensure_ascii=False, indent=2
        )

        stock_info = ""
        if target_stock:
            stock_info = f"\n目标股票: {json.dumps(target_stock, ensure_ascii=False)}\n"

        prompt = f"""你是一个金融研究助手。用户已选择使用以下Skills，请调用合适的工具完成分析。

可用工具:
{tools_info}
{stock_info}
用户消息: "{user_message}"

请以JSON格式输出需要调用的工具：
{{
    "tool_calls": [
        {{
            "skill": "skill_name",
            "tool": "tool_name",
            "arguments": {{"param1": "value1"}},
            "call_id": "call_001"
        }}
    ],
    "execution_mode": "parallel|sequential",
    "reasoning": "为什么选择这些工具以及执行方式"
}}

如果需要使用控制流，请使用以下格式：
{{
    "control_flow": {{
        "type": "for_each|while|if_else|switch|filter",
        "config": {{}}
    }}
}}
"""
        return prompt

    async def execute_tools(
        self, tool_calls: list[dict[str, Any]], execution_mode: str = "parallel"
    ) -> dict[str, Any]:
        """执行工具调用"""
        from app.mcp_server.control_flow.engine import ToolCall as TCToolCall

        calls = [
            TCToolCall(
                skill=call["skill"],
                tool=call["tool"],
                arguments=call.get("arguments", {}),
                call_id=call.get("call_id", f"call_{i}"),
                depends_on=call.get("depends_on"),
            )
            for i, call in enumerate(tool_calls)
        ]

        if execution_mode == "parallel":
            results = await self.control_flow_engine.executors[
                ControlFlowType.SEQUENTIAL
            ].execute_parallel(calls)
        else:
            results = await self.control_flow_engine.executors[
                ControlFlowType.SEQUENTIAL
            ].execute_sequential(calls)

        return {
            "success": all(r.success for r in results),
            "results": [
                {"call_id": r.call_id, "success": r.success, "data": r.data, "error": r.error}
                for r in results
            ],
        }

    async def execute_control_flow(self, flow_type: str, config: dict[str, Any]) -> dict[str, Any]:
        """执行控制流"""
        return await self.control_flow_engine.execute(flow_type, config)

    # ==================== Round 3: 生成回复 ====================

    def get_response_generation_prompt(
        self, user_message: str, tool_results: dict[str, Any], execution_summary: dict[str, Any]
    ) -> str:
        """生成回复生成的Prompt"""
        results_info = json.dumps(tool_results, ensure_ascii=False, indent=2, default=str)
        summary_info = json.dumps(execution_summary, ensure_ascii=False, indent=2, default=str)

        prompt = f"""你是一个专业的金融分析师。基于工具返回的数据，生成结构化的分析报告。

用户消息: "{user_message}"

执行摘要:
{summary_info}

工具执行结果:
{results_info}

请生成结构化的分析报告，包含：
1. 行情概况（如果有市场数据）
2. 财务状况（如果有财务数据）
3. 估值分析（如果有估值数据）
4. 风险评估（如果有风险数据）
5. 投资建议

如果有部分数据获取失败，请明确标注：
- ✅ 成功获取的数据
- ❌ 失败的数据及原因
- ⚠️ 风险提示
- 🔄 用户可选择的操作
"""
        return prompt

    # ==================== 错误处理 ====================

    def handle_error(self, error: Exception, context: dict[str, Any] = None) -> dict[str, Any]:
        """处理错误"""
        error_info = self.error_handler.handle_error(
            error, context.get("tool") if context else None
        )

        if self.error_handler.should_stop_execution(error_info):
            return self.error_handler.format_error_response(error_info)

        return {
            "status": "CONTINUE_WITH_WARNING",
            "error": {
                "type": error_info.error_type.value,
                "message": error_info.message,
                "is_critical": error_info.is_critical,
            },
        }

    # ==================== 便捷方法 ====================

    async def analyze_stock(
        self, symbol: str, analysis_type: str = "comprehensive"
    ) -> dict[str, Any]:
        """便捷方法：分析股票"""
        tool_calls = []

        if analysis_type in ["comprehensive", "market"]:
            tool_calls.extend(
                [
                    {
                        "skill": "market_data",
                        "tool": "get_quote",
                        "arguments": {"symbol": symbol},
                        "call_id": "quote",
                    },
                    {
                        "skill": "market_data",
                        "tool": "get_daily_basic",
                        "arguments": {"symbol": symbol},
                        "call_id": "valuation",
                    },
                ]
            )

        if analysis_type in ["comprehensive", "financial"]:
            tool_calls.extend(
                [
                    {
                        "skill": "financial_analysis",
                        "tool": "calculate_financial_ratios",
                        "arguments": {"symbol": symbol},
                        "call_id": "ratios",
                    },
                ]
            )

        if analysis_type == "comprehensive":
            tool_calls.extend(
                [
                    {
                        "skill": "risk_assessment",
                        "tool": "assess_stock_risk",
                        "arguments": {"symbol": symbol},
                        "call_id": "risk",
                    },
                ]
            )

        return await self.execute_tools(tool_calls, execution_mode="parallel")

    def get_server_info(self) -> dict[str, Any]:
        """获取服务器信息"""
        return {
            "name": "金融研投助手 MCP Server",
            "version": "2.0.0",
            "skills": [
                {"name": name, "description": info.description, "tools_count": info.tools_count}
                for name, info in self.SKILLS.items()
            ],
            "control_flows": ["sequential", "for_each", "while", "if_else", "switch", "filter"],
            "total_tools": sum(info.tools_count for info in self.SKILLS.values()),
        }


# 全局Server实例
_server_instance: FinancialResearchMCPServer | None = None


def get_mcp_server() -> FinancialResearchMCPServer:
    """获取MCP Server单例"""
    global _server_instance
    if _server_instance is None:
        _server_instance = FinancialResearchMCPServer()
    return _server_instance


# ==================== FastMCP MCP Server 入口 ====================

# 导入 FastMCP
try:
    from mcp.server import FastMCP

    MCP_SDK_AVAILABLE = True
except ImportError:
    MCP_SDK_AVAILABLE = False
    FastMCP = None

if MCP_SDK_AVAILABLE:
    # 创建 FastMCP 实例
    mcp = FastMCP("financial_research_assistant")

    # 全局 discovered skills（用于渐进式披露）
    _discovered_skills: set = set()
    _mcp_server_instance: FinancialResearchMCPServer | None = None

    def _get_server() -> FinancialResearchMCPServer:
        """获取或创建 Server 实例"""
        global _mcp_server_instance
        if _mcp_server_instance is None:
            _mcp_server_instance = FinancialResearchMCPServer()
        return _mcp_server_instance

    @mcp.resource("skill://{skill_name}")
    async def get_skill_resource(skill_name: str) -> str:
        """
        获取 Skill 的 SKILL.md 内容

        URI 格式: skill://{skill_name}
        例如: skill://market_data
        """
        server = _get_server()

        # 检查 skill 是否存在
        if skill_name not in server.SKILLS:
            return f"# 错误\n\nSkill '{skill_name}' 不存在。\n\n可用 Skills: {list(server.SKILLS.keys())}"

        # 标记为已发现
        _discovered_skills.add(skill_name)

        # 获取 skill 实例
        skill = server.skill_instances.get(skill_name)
        if not skill:
            return f"# 错误\n\nSkill '{skill_name}' 未初始化。"

        # 返回 SKILL.md 内容
        return skill.get_skill_md()

    @mcp.resource("config://skills")
    async def get_skills_config() -> str:
        """获取所有 Skill 的配置信息"""
        server = _get_server()
        skills_info = []

        for name, info in server.SKILLS.items():
            skills_info.append(
                {
                    "name": name,
                    "description": info.description,
                    "tools_count": info.tools_count,
                    "use_when": info.use_when,
                }
            )

        return json.dumps(skills_info, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def skill(name: str) -> str:
        """
        获取指定 Skill 的 SKILL.md 内容

        Args:
            name: Skill 名称，可选值: market_data, financial_analysis, risk_assessment,
                  deep_research, web_research, data_analysis, sector_analysis

        Returns:
            SKILL.md 文档内容（Markdown 格式）
        """
        return await get_skill_resource(name)

    @mcp.tool()
    async def get_skill_tools(name: str) -> dict[str, Any]:
        """
        获取指定 Skill 的工具列表

        Args:
            name: Skill 名称

        Returns:
            包含 tools 列表的字典
        """
        server = _get_server()

        if name not in server.SKILLS:
            return {"success": False, "error": f"Skill '{name}' 不存在"}

        tools = server.get_tools_for_skills([name])

        return {"success": True, "skill": name, "tools": tools.get(name, {}).get("tools", [])}

    @mcp.tool()
    async def execute_skill_tool(
        skill_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """
        执行指定 Skill 的工具

        Args:
            skill_name: Skill 名称
            tool_name: 工具名称（不含 skill 前缀）
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        server = _get_server()
        return await server._execute_skill_tool(skill_name, tool_name, arguments)

    @mcp.tool()
    async def execute_control_flow(flow_type: str, config: dict[str, Any]) -> dict[str, Any]:
        """
        执行控制流

        Args:
            flow_type: 控制流类型 (sequential, for_each, while, if_else, switch, filter)
            config: 控制流配置

        Returns:
            执行结果
        """
        server = _get_server()

        from app.mcp_server.control_flow.engine import ControlFlowType

        try:
            cf_type = ControlFlowType(flow_type)
        except ValueError:
            return {"success": False, "error": f"未知的控制流类型: {flow_type}"}

        return await server.control_flow_engine.execute(cf_type, config)

    def _convert_to_mcp_tools(self, skill_tools: dict[str, Any]) -> list:
        """将 skill 工具转换为 MCP 工具格式"""
        mcp_tools = []

        for skill_name, skill_info in skill_tools.items():
            for tool in skill_info.get("tools", []):
                # MCP 工具名格式: skill_name.tool_name
                tool_name = f"{skill_name}.{tool['name']}"
                mcp_tools.append(
                    {
                        "name": tool_name,
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    }
                )

        return mcp_tools


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import sys

    # 检查 MCP SDK 是否可用
    if not MCP_SDK_AVAILABLE:
        print("错误: MCP SDK 未安装。请运行: pip install mcp", file=sys.stderr)
        sys.exit(1)

    # 运行 FastMCP Server
    print("🚀 启动 Financial Research MCP Server...")
    print("📊 可用 Skills: market_data, financial_analysis, risk_assessment,")
    print("               deep_research, web_research, data_analysis, sector_analysis")
    print("📡 使用 stdio 传输协议")
    print("-" * 60)

    mcp.run(transport="stdio")
