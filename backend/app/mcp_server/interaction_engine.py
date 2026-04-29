# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""交互引擎 - 3轮交互流程实现

Round 1: Skill选择 → LLM根据意图选Skills
Round 2: 工具调用 → 支持控制流
Round 3: 生成回复 → 结构化报告
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from app.mcp_server.control_flow import (
    ControlFlowDefinition,
    ControlFlowExecutor,
    ExecutionContext,
    ToolCall,
    create_sequential_flow,
)
from app.mcp_server.error_handler import (
    ErrorClassifier,
    ErrorHandler,
    ErrorReport,
    handle_exception,
)

logger = logging.getLogger("InteractionEngine")


class RoundType(Enum):
    """轮次类型"""

    ROUND_1_SKILL_SELECTION = 1
    ROUND_2_TOOL_EXECUTION = 2
    ROUND_3_RESPONSE_GENERATION = 3


@dataclass
class SkillSelection:
    """Skill选择结果"""

    selected_skills: list[str]
    execution_strategy: dict[str, Any]
    reasoning: str
    direct_response: str | None = None  # 如果不需要调用工具，直接返回回复

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected_skills": self.selected_skills,
            "execution_strategy": self.execution_strategy,
            "reasoning": self.reasoning,
            "direct_response": self.direct_response,
        }


@dataclass
class ToolExecutionPlan:
    """工具执行计划"""

    tool_calls: list[ToolCall]
    execution_mode: str  # "sequential", "parallel", "for_each", "while", "conditional"
    control_flow: ControlFlowDefinition | None = None
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "execution_mode": self.execution_mode,
            "reasoning": self.reasoning,
            "has_control_flow": self.control_flow is not None,
        }


@dataclass
class ExecutionResult:
    """执行结果"""

    success: bool
    results: dict[str, Any]
    execution_log: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    execution_time_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "results": self.results,
            "execution_log": self.execution_log,
            "errors": self.errors,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class InteractionSession:
    """交互会话"""

    session_id: str
    user_message: str
    target_stock: dict[str, str] | None = None
    round_1_result: SkillSelection | None = None
    round_2_result: ExecutionResult | None = None
    round_3_result: str | None = None
    error_report: ErrorReport | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_message": self.user_message,
            "target_stock": self.target_stock,
            "round_1": self.round_1_result.to_dict() if self.round_1_result else None,
            "round_2": self.round_2_result.to_dict() if self.round_2_result else None,
            "round_3": self.round_3_result,
            "has_error": self.error_report is not None,
            "created_at": self.created_at,
        }


class InteractionEngine:
    """交互引擎"""

    def __init__(self, skill_registry: dict[str, Any]):
        """
        初始化交互引擎

        Args:
            skill_registry: Skill 注册表
        """
        self.skill_registry = skill_registry
        self.control_flow_executor = ControlFlowExecutor(skill_registry)
        self.error_handler = ErrorHandler()
        self.sessions: dict[str, InteractionSession] = {}

        # 所有可用 Skills 的描述
        self.skill_catalog = self._build_skill_catalog()

    def _build_skill_catalog(self) -> list[dict[str, Any]]:
        """构建 Skill 目录"""
        return [
            {
                "name": "market_data",
                "description": "股票市场行情数据查询，提供实时股价、PE/PB估值、历史K线、资金流向等",
                "tools_count": 11,
                "use_when": "用户询问股价、估值、行情数据、历史走势等",
            },
            {
                "name": "financial_analysis",
                "description": "财务报表分析，计算ROE、ROA、毛利率、净利率等财务指标",
                "tools_count": 7,
                "use_when": "用户询问财务状况、盈利能力、三张报表等",
            },
            {
                "name": "sector_analysis",
                "description": "行业与概念板块分析，支持行业对比、龙头识别、估值对比",
                "tools_count": 7,
                "use_when": "用户询问行业分析、板块对比、龙头股票等",
            },
            {
                "name": "risk_assessment",
                "description": "投资风险评估，评估个股风险等级、提供预警",
                "tools_count": 5,
                "use_when": "用户关注风险、需要风险评估时",
            },
            {
                "name": "deep_research",
                "description": "深度研究报告生成，综合多维度数据生成研报",
                "tools_count": 3,
                "use_when": "用户需要深度研报、综合分析时使用",
            },
            {
                "name": "web_research",
                "description": "网络信息搜索，获取新闻、公告、研报等外部信息",
                "tools_count": 4,
                "use_when": "用户需要最新资讯、新闻、公告时使用",
            },
            {
                "name": "data_analysis",
                "description": "数据分析与可视化，支持统计分析、趋势预测、图表生成",
                "tools_count": 6,
                "use_when": "用户需要数据分析、图表展示时使用",
            },
        ]

    def get_skill_catalog_for_llm(self) -> str:
        """
        获取用于LLM的Skill目录描述

        Returns:
            JSON格式的Skill目录
        """
        return json.dumps(
            {
                "available_skills": self.skill_catalog,
                "instruction": "分析用户需求，选择合适的Skill(s)。可以单选、多选或不选（直接回答）。",
            },
            ensure_ascii=False,
            indent=2,
        )

    def process_round_1(self, user_message: str, session_id: str) -> InteractionSession:
        """
        处理 Round 1: Skill选择

        此函数返回会话信息和LLM需要的上下文，由LLM决定选择哪些Skills

        Args:
            user_message: 用户消息
            session_id: 会话ID

        Returns:
            InteractionSession 会话对象（等待LLM填充selected_skills）
        """
        session = InteractionSession(session_id=session_id, user_message=user_message)
        self.sessions[session_id] = session

        logger.info(f"Round 1 started: session_id={session_id}")

        return session

    def set_round_1_result(
        self,
        session_id: str,
        selected_skills: list[str],
        execution_strategy: dict[str, Any],
        reasoning: str,
        direct_response: str | None = None,
    ) -> InteractionSession:
        """
        设置 Round 1 结果（由LLM调用）

        Args:
            session_id: 会话ID
            selected_skills: 选中的Skills
            execution_strategy: 执行策略
            reasoning: 选择理由
            direct_response: 直接回复（如果不需要调用工具）

        Returns:
            更新后的会话
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")

        session.round_1_result = SkillSelection(
            selected_skills=selected_skills,
            execution_strategy=execution_strategy,
            reasoning=reasoning,
            direct_response=direct_response,
        )

        logger.info(
            f"Round 1 completed: session_id={session_id}, selected_skills={selected_skills}"
        )

        return session

    def get_tools_for_round_2(self, session_id: str) -> dict[str, Any]:
        """
        获取 Round 2 需要的工具列表

        Args:
            session_id: 会话ID

        Returns:
            选中Skills的工具列表
        """
        session = self.sessions.get(session_id)
        if not session or not session.round_1_result:
            raise ValueError(f"Round 1 尚未完成: {session_id}")

        selected_skills = session.round_1_result.selected_skills

        tools_by_skill = {}
        for skill_name in selected_skills:
            skill = self.skill_registry.get(skill_name)
            if skill:
                tools_by_skill[skill_name] = {
                    "description": skill.description,
                    "tools": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": [
                                {
                                    "name": p.name,
                                    "type": p.type,
                                    "description": p.description,
                                    "required": p.required,
                                }
                                for p in t.parameters
                            ],
                        }
                        for t in skill.discover_tools()
                    ],
                }

        return {
            "selected_skills": tools_by_skill,
            "user_message": session.user_message,
            "instruction": "请调用合适的工具完成分析。支持顺序执行、并行执行、循环、分支等控制流。",
        }

    async def execute_round_2(
        self, session_id: str, tool_plan: ToolExecutionPlan
    ) -> InteractionSession:
        """
        执行 Round 2: 工具调用

        Args:
            session_id: 会话ID
            tool_plan: 工具执行计划

        Returns:
            更新后的会话
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")

        if not session.round_1_result:
            raise ValueError(f"Round 1 尚未完成: {session_id}")

        logger.info(f"Round 2 started: session_id={session_id}, mode={tool_plan.execution_mode}")

        start_time = datetime.now()

        try:
            # 创建执行上下文
            context = ExecutionContext()

            # 如果有控制流定义，使用控制流执行
            if tool_plan.control_flow:
                flow_result = await self.control_flow_executor.execute(
                    tool_plan.control_flow, context
                )

                execution_result = ExecutionResult(
                    success=True,
                    results=flow_result,
                    execution_log=context.execution_log,
                    errors=context.errors,
                    execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                )
            else:
                # 直接执行工具调用
                results = []
                for call in tool_plan.tool_calls:
                    skill = self.skill_registry.get(call.skill)
                    if not skill:
                        results.append(
                            {
                                "call_id": call.call_id,
                                "success": False,
                                "error": f"Skill '{call.skill}' 不存在",
                            }
                        )
                        continue

                    try:
                        result = await skill.execute_tool(call.tool, call.arguments)
                        results.append(
                            {
                                "call_id": call.call_id,
                                "skill": call.skill,
                                "tool": call.tool,
                                "success": result.success,
                                "data": result.data if result.success else None,
                                "error": result.error if not result.success else None,
                            }
                        )
                    except Exception as e:
                        results.append(
                            {
                                "call_id": call.call_id,
                                "skill": call.skill,
                                "tool": call.tool,
                                "success": False,
                                "error": str(e),
                            }
                        )

                execution_result = ExecutionResult(
                    success=all(r.get("success", False) for r in results),
                    results={"tool_results": results},
                    execution_log=context.execution_log,
                    errors=[r for r in results if not r.get("success", False)],
                    execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
                )

            session.round_2_result = execution_result

            # 检查是否有错误
            if execution_result.errors:
                # 生成错误报告
                error_infos = []
                for error in execution_result.errors:
                    error_info = ErrorClassifier.classify(
                        Exception(error.get("error", "Unknown error")),
                        tool=error.get("tool"),
                        skill=error.get("skill"),
                    )
                    error_infos.append(error_info)

                session.error_report = self.error_handler.handle_multiple_errors(error_infos)

            logger.info(
                f"Round 2 completed: session_id={session_id}, success={execution_result.success}"
            )

        except Exception as e:
            logger.error(f"Round 2 failed: session_id={session_id}, error={e}")
            session.error_report = handle_exception(e)
            session.round_2_result = ExecutionResult(
                success=False,
                results={},
                execution_log=[],
                errors=[{"error": str(e)}],
                execution_time_ms=int((datetime.now() - start_time).total_seconds() * 1000),
            )

        return session

    def get_data_for_round_3(self, session_id: str) -> dict[str, Any]:
        """
        获取 Round 3 需要的数据

        Args:
            session_id: 会话ID

        Returns:
            用于生成回复的数据
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")

        if not session.round_2_result:
            raise ValueError(f"Round 2 尚未完成: {session_id}")

        execution_summary = {
            "total_api_calls": session.round_2_result.results.get("total_calls", 0),
            "success_count": len(
                [
                    r
                    for r in session.round_2_result.results.get("tool_results", [])
                    if r.get("success", False)
                ]
            ),
            "failure_count": len(session.round_2_result.errors),
            "execution_time_ms": session.round_2_result.execution_time_ms,
        }

        tool_results = {}
        for skill_name in session.round_1_result.selected_skills if session.round_1_result else []:
            skill_results = []
            for result in session.round_2_result.results.get("tool_results", []):
                if result.get("skill") == skill_name and result.get("success"):
                    skill_results.append(result.get("data"))
            if skill_results:
                tool_results[skill_name] = skill_results

        return {
            "user_message": session.user_message,
            "execution_summary": execution_summary,
            "tool_results": tool_results,
            "errors": [e.to_dict() for e in session.error_report.errors]
            if session.error_report
            else [],
            "instruction": "基于工具返回的数据，生成结构化的分析报告。包含成功/失败数据标注和风险提示。",
        }

    def set_round_3_result(self, session_id: str, response: str) -> InteractionSession:
        """
        设置 Round 3 结果（由LLM调用）

        Args:
            session_id: 会话ID
            response: 生成的回复

        Returns:
            更新后的会话
        """
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"会话不存在: {session_id}")

        session.round_3_result = response

        logger.info(f"Round 3 completed: session_id={session_id}")

        return session

    def get_session(self, session_id: str) -> InteractionSession | None:
        """获取会话"""
        return self.sessions.get(session_id)

    def cleanup_session(self, session_id: str):
        """清理会话"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Session cleaned up: {session_id}")

    def get_all_sessions(self) -> list[dict[str, Any]]:
        """获取所有会话摘要"""
        return [
            {
                "session_id": s.session_id,
                "user_message": s.user_message[:50] + "..."
                if len(s.user_message) > 50
                else s.user_message,
                "round_completed": sum(
                    [
                        1 if s.round_1_result else 0,
                        1 if s.round_2_result else 0,
                        1 if s.round_3_result else 0,
                    ]
                ),
                "has_error": s.error_report is not None,
                "created_at": s.created_at,
            }
            for s in self.sessions.values()
        ]


# 便捷函数
def create_simple_tool_plan(
    skill: str, tool: str, arguments: dict[str, Any], call_id: str = "call_001"
) -> ToolExecutionPlan:
    """创建简单的工具执行计划"""
    return ToolExecutionPlan(
        tool_calls=[ToolCall(skill=skill, tool=tool, arguments=arguments, call_id=call_id)],
        execution_mode="sequential",
        reasoning="单一工具调用",
    )


def create_parallel_tool_plan(
    calls: list[tuple[str, str, dict[str, Any], str]],
) -> ToolExecutionPlan:
    """
    创建并行工具执行计划

    Args:
        calls: [(skill, tool, arguments, call_id), ...]

    Returns:
        ToolExecutionPlan
    """
    tool_calls = [ToolCall(skill=s, tool=t, arguments=a, call_id=c) for s, t, a, c in calls]

    return ToolExecutionPlan(
        tool_calls=tool_calls,
        execution_mode="parallel",
        control_flow=create_sequential_flow(tool_calls, parallel=True),
        reasoning="并行执行多个独立工具调用",
    )


# 示例：构建完整的3轮交互流程
async def example_interaction_flow():
    """示例交互流程"""
    from app.mcp_server.skills import FinancialAnalysisSkill, MarketDataSkill

    # 创建 Skill 注册表
    skill_registry = {
        "market_data": MarketDataSkill(),
        "financial_analysis": FinancialAnalysisSkill(),
    }

    # 创建交互引擎
    engine = InteractionEngine(skill_registry)

    # ========== Round 1: Skill选择 ==========
    session = engine.process_round_1(
        user_message="帮我全面分析一下茅台这只股票", session_id="session_001"
    )

    # LLM 读取 Skill 目录并选择
    skill_catalog = engine.get_skill_catalog_for_llm()
    print("Round 1 - Skill Catalog:", skill_catalog)

    # LLM 返回选择结果
    engine.set_round_1_result(
        session_id="session_001",
        selected_skills=["market_data", "financial_analysis"],
        execution_strategy={
            "type": "complex_chain",
            "description": "全面分析需要市场数据和财务分析",
            "estimated_steps": 3,
        },
        reasoning="用户要求全面分析，需要获取行情数据和财务指标",
    )

    # ========== Round 2: 工具调用 ==========
    tools_info = engine.get_tools_for_round_2("session_001")
    print("Round 2 - Available Tools:", tools_info)

    # LLM 创建工具执行计划
    tool_plan = ToolExecutionPlan(
        tool_calls=[
            ToolCall(
                skill="market_data",
                tool="get_quote",
                arguments={"symbol": "600519"},
                call_id="call_001",
            ),
            ToolCall(
                skill="market_data",
                tool="get_daily_basic",
                arguments={"symbol": "600519"},
                call_id="call_002",
            ),
            ToolCall(
                skill="financial_analysis",
                tool="calculate_financial_ratios",
                arguments={"symbol": "600519"},
                call_id="call_003",
            ),
        ],
        execution_mode="parallel",
        control_flow=create_sequential_flow(
            [
                ToolCall(
                    skill="market_data",
                    tool="get_quote",
                    arguments={"symbol": "600519"},
                    call_id="call_001",
                ),
                ToolCall(
                    skill="market_data",
                    tool="get_daily_basic",
                    arguments={"symbol": "600519"},
                    call_id="call_002",
                ),
                ToolCall(
                    skill="financial_analysis",
                    tool="calculate_financial_ratios",
                    arguments={"symbol": "600519"},
                    call_id="call_003",
                ),
            ],
            parallel=True,
        ),
        reasoning="这三个工具调用相互独立，可以并行执行",
    )

    # 执行工具调用
    session = await engine.execute_round_2("session_001", tool_plan)

    # ========== Round 3: 生成回复 ==========
    response_data = engine.get_data_for_round_3("session_001")
    print("Round 3 - Response Data:", response_data)

    # LLM 生成回复
    engine.set_round_3_result(
        session_id="session_001",
        response="## 贵州茅台 (600519) 综合分析报告\n\n### 行情概况\n当前股价: ¥1,850.50...",
    )

    return session
