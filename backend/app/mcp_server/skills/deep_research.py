# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""DeepResearch Skill - 深度研究工具

将 deep_research_v2 服务封装为 MCP Skill，提供深度研究能力。
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter, ToolResult
import asyncio
import json


class DeepResearchSkill(BaseSkill):
    """
    深度研究 Skill

    提供基于多智能体协作的深度研究能力，包括：
    - 架构师（Architect）：规划研究大纲
    - 侦探（Scout）：搜索和收集信息
    - 极客（Wizard）：数据分析和可视化
    - 评论家（Critic）：质量评审
    - 笔杆（Writer）：报告撰写
    """

    name = "deep_research"
    description = "深度研究服务，基于多智能体协作生成高质量研究报告"

    def __init__(self):
        # 延迟导入避免循环依赖
        self._service = None
        super().__init__()

    def get_service(self):
        """
        获取 DeepResearch 服务实例（延迟初始化）

        Returns:
            DeepResearchV2Service 实例
        """
        if self._service is None:
            from app.service.deep_research_v2 import DeepResearchV2Service
            self._service = DeepResearchV2Service()
            self._logger.info("DeepResearch V2 Service initialized")
        return self._service

    def _register_tools(self):
        """注册 DeepResearch 相关工具"""

        # 1. 执行深度研究（流式）
        self.register_tool(
            name="research_stream",
            handler=self.research_stream,
            description="执行深度研究任务，返回流式事件。适用于需要实时反馈的场景。包含5个Agent协作：规划大纲→搜索信息→数据分析→撰写报告→质量评审",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="研究问题或主题，例如：'中国AI芯片市场分析'、'茅台近期投资价值分析'",
                    required=True
                ),
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID，用于标识和恢复研究任务（可选，不提供则自动生成）",
                    required=False
                ),
                ToolParameter(
                    name="search_web",
                    type="boolean",
                    description="是否启用网络搜索（默认True）",
                    required=False,
                    default=True
                ),
                ToolParameter(
                    name="search_local",
                    type="boolean",
                    description="是否启用本地知识库搜索（默认False）",
                    required=False,
                    default=False
                ),
                ToolParameter(
                    name="resume",
                    type="boolean",
                    description="是否从检查点恢复之前的研究（默认False）",
                    required=False,
                    default=False
                )
            ]
        )

        # 2. 执行深度研究（同步）
        self.register_tool(
            name="research_sync",
            handler=self.research_sync,
            description="执行深度研究任务，返回完整结果（非流式）。适用于批处理场景。",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="研究问题或主题",
                    required=True
                ),
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID（可选）",
                    required=False
                ),
                ToolParameter(
                    name="search_web",
                    type="boolean",
                    description="是否启用网络搜索（默认True）",
                    required=False,
                    default=True
                ),
                ToolParameter(
                    name="search_local",
                    type="boolean",
                    description="是否启用本地知识库搜索（默认False）",
                    required=False,
                    default=False
                )
            ]
        )

        # 3. 快速研究（简化版）
        self.register_tool(
            name="quick_research",
            handler=self.quick_research,
            description="执行快速研究，返回核心发现和简要报告。适用于快速了解某个主题的场景。",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="研究问题",
                    required=True
                ),
                ToolParameter(
                    name="max_iterations",
                    type="integer",
                    description="最大迭代次数（默认3次，快速模式）",
                    required=False,
                    default=3
                )
            ]
        )

    async def research_stream(
        self,
        query: str,
        session_id: Optional[str] = None,
        search_web: bool = True,
        search_local: bool = False,
        resume: bool = False
    ) -> Dict[str, Any]:
        """
        执行深度研究（流式）

        Args:
            query: 研究问题
            session_id: 会话ID
            search_web: 是否启用网络搜索
            search_local: 是否启用本地知识库搜索
            resume: 是否恢复之前的研究

        Returns:
            包含流式事件列表的结果
        """
        try:
            service = self.get_service()
            events = []

            # 收集所有流式事件
            async for event_str in service.research(
                query=query,
                session_id=session_id,
                search_web=search_web,
                search_local=search_local,
                resume=resume
            ):
                # 解析 SSE 格式的事件
                if event_str.startswith("data: "):
                    data = event_str[6:].strip()
                    if data and data != "[DONE]":
                        try:
                            event = json.loads(data)
                            events.append(event)
                        except json.JSONDecodeError:
                            pass

            # 提取最终结果
            final_report = ""
            quality_score = 0.0
            phase = ""

            for event in reversed(events):
                if event.get("type") == "final_report":
                    final_report = event.get("content", "")
                    quality_score = event.get("quality_score", 0.0)
                    break
                elif event.get("type") == "phase":
                    phase = event.get("content", "")

            return {
                "success": True,
                "data": {
                    "session_id": session_id,
                    "query": query,
                    "final_report": final_report,
                    "quality_score": quality_score,
                    "phase": phase,
                    "total_events": len(events),
                    "events": events[:10]  # 只返回前10个事件作为示例
                }
            }

        except Exception as e:
            self._logger.error(f"Research stream failed: {e}")
            return {
                "success": False,
                "error": f"深度研究失败: {str(e)}"
            }

    async def research_sync(
        self,
        query: str,
        session_id: Optional[str] = None,
        search_web: bool = True,
        search_local: bool = False
    ) -> Dict[str, Any]:
        """
        执行深度研究（同步）

        Args:
            query: 研究问题
            session_id: 会话ID
            search_web: 是否启用网络搜索
            search_local: 是否启用本地知识库搜索

        Returns:
            完整的研究结果
        """
        try:
            service = self.get_service()

            # 运行同步研究
            result = await service.research_sync(query, session_id)

            return {
                "success": True,
                "data": {
                    "session_id": result["session_id"],
                    "query": result["query"],
                    "final_report": result["final_report"],
                    "quality_score": result["quality_score"],
                    "outline": result.get("outline", []),
                    "facts": result.get("facts", []),
                    "data_points": result.get("data_points", []),
                    "charts": result.get("charts", []),
                    "references": result.get("references", []),
                    "insights": result.get("insights", []),
                    "iterations": result.get("iterations", 0),
                    "phase": result.get("phase", "")
                }
            }

        except Exception as e:
            self._logger.error(f"Research sync failed: {e}")
            return {
                "success": False,
                "error": f"深度研究失败: {str(e)}"
            }

    async def quick_research(
        self,
        query: str,
        max_iterations: int = 3
    ) -> Dict[str, Any]:
        """
        快速研究模式

        Args:
            query: 研究问题
            max_iterations: 最大迭代次数

        Returns:
            简要研究结果
        """
        try:
            from app.service.deep_research_v2 import DeepResearchV2Service

            # 创建快速模式服务（限制迭代次数）
            service = DeepResearchV2Service(max_iterations=max_iterations)

            result = await service.research_sync(query)

            # 提取核心信息
            return {
                "success": True,
                "data": {
                    "query": query,
                    "summary": result["final_report"][:500] + "..." if len(result["final_report"]) > 500 else result["final_report"],
                    "key_facts": result.get("facts", [])[:5],  # 前5个关键事实
                    "key_insights": result.get("insights", [])[:3],  # 前3个洞察
                    "quality_score": result["quality_score"],
                    "iterations": result.get("iterations", 0)
                }
            }

        except Exception as e:
            self._logger.error(f"Quick research failed: {e}")
            return {
                "success": False,
                "error": f"快速研究失败: {str(e)}"
            }
