# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""DeepResearch Skill - 完全拆分版

将 DeepResearch 拆分为 6 个独立工具，对应 5 个 Agent：
1. plan - ChiefArchitect（规划大纲）
2. search - DeepScout（搜索信息）
3. analyze - CodeWizard（数据分析）
4. write - LeadWriter（撰写报告）
5. review - CriticMaster（质量评审）
6. revise - LeadWriter（修订改进）
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.base import BaseSkill, ToolParameter
import uuid
import json


class DeepResearchSkillSplit(BaseSkill):
    """
    DeepResearch Skill 完全拆分版

    提供 6 个独立工具，LLM 可以完全控制研究流程：
    - deep_research.plan - 规划研究大纲
    - deep_research.search - 搜索信息
    - deep_research.analyze - 分析数据
    - deep_research.write - 撰写报告
    - deep_research.review - 质量评审
    - deep_research.revise - 修订改进
    - deep_research.get_state - 查看状态
    """

    name = "deep_research"
    description = "深度研究服务（分步执行版），提供6个独立工具对应5个Agent，支持LLM完全控制研究流程"

    def __init__(self):
        self._service = None
        super().__init__()

    def get_service(self):
        """获取 DeepResearch 服务实例"""
        if self._service is None:
            from app.service.deep_research_v2 import DeepResearchV2Service
            self._service = DeepResearchV2Service()
            self._logger.info("DeepResearch V2 Service initialized")
        return self._service

    def _register_tools(self):
        """注册 6 个独立工具"""

        # 1. 规划大纲 - Architect Agent
        self.register_tool(
            name="plan",
            handler=self.plan,
            description="【步骤1】规划研究大纲。Architect Agent 分析问题，生成结构化研究计划（章节+假设）。返回：session_id, sections[], hypotheses[]",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="研究问题，例如：'小米汽车2024年市场竞争力分析'",
                    required=True
                ),
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID（可选，不提供则自动生成新会话）",
                    required=False
                )
            ]
        )

        # 2. 搜索信息 - Scout Agent
        self.register_tool(
            name="search",
            handler=self.search,
            description="【步骤2】搜索信息。Scout Agent 根据大纲章节搜索网络/知识库，收集相关资料。返回：facts[], sources[], search_results[]",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID（必需，由 plan 返回）",
                    required=True
                ),
                ToolParameter(
                    name="section_id",
                    type="string",
                    description="章节ID，例如：'section_1'。不提供则搜索所有章节",
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

        # 3. 分析数据 - Wizard Agent
        self.register_tool(
            name="analyze",
            handler=self.analyze,
            description="【步骤3】分析数据。Wizard Agent 对搜索结果进行深度分析，生成洞察和可视化。返回：insights[], charts[], statistics{}",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID",
                    required=True
                ),
                ToolParameter(
                    name="section_id",
                    type="string",
                    description="章节ID。不提供则分析所有章节",
                    required=False
                )
            ]
        )

        # 4. 撰写报告 - Writer Agent
        self.register_tool(
            name="write",
            handler=self.write,
            description="【步骤4】撰写报告。Writer Agent 基于研究数据撰写完整报告（含摘要、正文、结论、参考文献）。返回：report, word_count",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID",
                    required=True
                ),
                ToolParameter(
                    name="section_id",
                    type="string",
                    description="章节ID。不提供则撰写完整报告",
                    required=False
                )
            ]
        )

        # 5. 质量评审 - Critic Agent
        self.register_tool(
            name="review",
            handler=self.review,
            description="【步骤5】质量评审。Critic Agent 评审报告质量，指出问题并给出改进建议。返回：score, approved, strengths[], weaknesses[], suggestions[]",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID",
                    required=True
                )
            ]
        )

        # 6. 修订改进 - Writer Agent (基于 Critic 反馈)
        self.register_tool(
            name="revise",
            handler=self.revise,
            description="【步骤6】修订改进。Writer Agent 根据 Critic 的反馈修订报告。返回：revised_report, improvements[]",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID",
                    required=True
                )
            ]
        )

        # 7. 获取状态（辅助工具）
        self.register_tool(
            name="get_state",
            handler=self.get_state,
            description="【辅助】获取研究状态。返回当前进度、已完成步骤、大纲、中间结果等。用于查看研究进展。",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID",
                    required=True
                )
            ]
        )

    # ========== 工具实现 ==========

    async def plan(
        self,
        query: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        步骤1：规划大纲
        调用 Architect Agent
        """
        try:
            from app.service.deep_research_v2.state import create_initial_state
            from app.service.checkpoint_service import get_checkpoint_service

            service = self.get_service()

            # 生成或使用提供的 session_id
            if not session_id:
                session_id = str(uuid.uuid4())
                self._logger.info(f"Generated new session_id: {session_id}")

            # 创建初始状态
            state = create_initial_state(query, session_id)

            # 执行 Architect
            self._logger.info(f"Executing Architect for session {session_id}")
            result_state = await service.graph.architect.process(state)

            # 保存状态
            checkpoint_service = get_checkpoint_service()
            if checkpoint_service:
                await checkpoint_service.save_checkpoint(session_id, result_state)

            outline = result_state.get("outline", {})
            sections = outline.get("sections", [])
            hypotheses = outline.get("hypotheses", [])

            return {
                "success": True,
                "data": {
                    "session_id": session_id,
                    "query": query,
                    "outline": outline,
                    "sections": sections,
                    "hypotheses": hypotheses,
                    "next_step": "调用 search 搜索信息",
                    "usage": f"deep_research.search(session_id='{session_id}', search_web=True)"
                }
            }

        except Exception as e:
            self._logger.error(f"Plan error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def search(
        self,
        session_id: str,
        section_id: Optional[str] = None,
        search_web: bool = True,
        search_local: bool = False
    ) -> Dict[str, Any]:
        """
        步骤2：搜索信息
        调用 Scout Agent
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service

            checkpoint_service = get_checkpoint_service()
            state = await checkpoint_service.load_checkpoint(session_id)

            if not state:
                return {"success": False, "error": f"会话不存在: {session_id}。请先调用 plan"}

            # 设置搜索参数
            state["search_web"] = search_web
            state["search_local"] = search_local

            service = self.get_service()

            # 如果指定了 section_id，只搜索该章节
            if section_id:
                outline = state.get("outline", {})
                sections = outline.get("sections", [])
                target_section = next((s for s in sections if s.get("id") == section_id), None)

                if not target_section:
                    return {"success": False, "error": f"章节不存在: {section_id}"}

                state["current_section"] = target_section
                self._logger.info(f"Searching for section: {section_id}")

            # 执行 Scout
            result_state = await service.graph.scout.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, result_state)

            # 提取搜索结果
            if section_id:
                section_data = result_state.get("sections", {}).get(section_id, {})
                facts = section_data.get("facts", [])
                sources = section_data.get("sources", [])
            else:
                # 所有章节的结果
                all_sections = result_state.get("sections", {})
                facts = []
                sources = []
                for sec_data in all_sections.values():
                    facts.extend(sec_data.get("facts", []))
                    sources.extend(sec_data.get("sources", []))

            return {
                "success": True,
                "data": {
                    "section_id": section_id or "all",
                    "facts_count": len(facts),
                    "sources_count": len(sources),
                    "facts": facts[:20],  # 最多返回20条
                    "sources": sources[:20],
                    "next_step": "调用 analyze 分析数据",
                    "usage": f"deep_research.analyze(session_id='{session_id}')"
                }
            }

        except Exception as e:
            self._logger.error(f"Search error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def analyze(
        self,
        session_id: str,
        section_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        步骤3：分析数据
        调用 Wizard Agent
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service

            checkpoint_service = get_checkpoint_service()
            state = await checkpoint_service.load_checkpoint(session_id)

            if not state:
                return {"success": False, "error": f"会话不存在: {session_id}"}

            service = self.get_service()

            if section_id:
                outline = state.get("outline", {})
                sections = outline.get("sections", [])
                target_section = next((s for s in sections if s.get("id") == section_id), None)

                if not target_section:
                    return {"success": False, "error": f"章节不存在: {section_id}"}

                state["current_section"] = target_section

            # 执行 Wizard
            result_state = await service.graph.wizard.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, result_state)

            # 提取分析结果
            if section_id:
                section_data = result_state.get("sections", {}).get(section_id, {})
                insights = section_data.get("insights", [])
                analysis = section_data.get("analysis", {})
            else:
                all_sections = result_state.get("sections", {})
                insights = []
                analysis = {}
                for sec_data in all_sections.values():
                    insights.extend(sec_data.get("insights", []))

            return {
                "success": True,
                "data": {
                    "section_id": section_id or "all",
                    "insights_count": len(insights),
                    "insights": insights,
                    "analysis": analysis,
                    "next_step": "调用 write 撰写报告",
                    "usage": f"deep_research.write(session_id='{session_id}')"
                }
            }

        except Exception as e:
            self._logger.error(f"Analyze error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def write(
        self,
        session_id: str,
        section_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        步骤4：撰写报告
        调用 Writer Agent
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service

            checkpoint_service = get_checkpoint_service()
            state = await checkpoint_service.load_checkpoint(session_id)

            if not state:
                return {"success": False, "error": f"会话不存在: {session_id}"}

            service = self.get_service()

            if section_id:
                outline = state.get("outline", {})
                sections = outline.get("sections", [])
                target_section = next((s for s in sections if s.get("id") == section_id), None)

                if not target_section:
                    return {"success": False, "error": f"章节不存在: {section_id}"}

                state["current_section"] = target_section

            # 执行 Writer
            result_state = await service.graph.writer.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, result_state)

            # 提取报告
            if section_id:
                section_data = result_state.get("sections", {}).get(section_id, {})
                content = section_data.get("draft", "")
            else:
                content = result_state.get("final_report", "")

            return {
                "success": True,
                "data": {
                    "section_id": section_id or "full_report",
                    "content": content,
                    "word_count": len(content),
                    "next_step": "调用 review 评审质量",
                    "usage": f"deep_research.review(session_id='{session_id}')"
                }
            }

        except Exception as e:
            self._logger.error(f"Write error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def review(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        步骤5：质量评审
        调用 Critic Agent
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service

            checkpoint_service = get_checkpoint_service()
            state = await checkpoint_service.load_checkpoint(session_id)

            if not state:
                return {"success": False, "error": f"会话不存在: {session_id}"}

            if not state.get("final_report"):
                return {"success": False, "error": "尚未生成完整报告，请先调用 write"}

            service = self.get_service()

            # 执行 Critic
            result_state = await service.graph.critic.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, result_state)

            # 提取评审结果
            review = result_state.get("review", {})
            score = review.get("score", 0)
            approved = review.get("approved", False)

            return {
                "success": True,
                "data": {
                    "score": score,
                    "approved": approved,
                    "strengths": review.get("strengths", []),
                    "weaknesses": review.get("weaknesses", []),
                    "suggestions": review.get("suggestions", []),
                    "next_step": "如需修订，调用 revise；否则研究完成",
                    "usage": f"deep_research.revise(session_id='{session_id}') if not approved else '完成'"
                }
            }

        except Exception as e:
            self._logger.error(f"Review error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def revise(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        步骤6：修订改进
        调用 Writer Agent（基于 Critic 反馈）
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service

            checkpoint_service = get_checkpoint_service()
            state = await checkpoint_service.load_checkpoint(session_id)

            if not state:
                return {"success": False, "error": f"会话不存在: {session_id}"}

            if not state.get("review"):
                return {"success": False, "error": "尚未评审，请先调用 review"}

            service = self.get_service()

            # 执行 Writer 修订
            state["phase"] = "revising"
            result_state = await service.graph.writer.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, result_state)

            # 提取修订后的报告
            revised_report = result_state.get("final_report", "")

            return {
                "success": True,
                "data": {
                    "revised_report": revised_report,
                    "word_count": len(revised_report),
                    "improvements": result_state.get("improvements", []),
                    "next_step": "可再次调用 review 确认质量"
                }
            }

        except Exception as e:
            self._logger.error(f"Revise error: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

    async def get_state(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        获取研究状态
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service

            checkpoint_service = get_checkpoint_service()
            state = await checkpoint_service.load_checkpoint(session_id)

            if not state:
                return {"success": False, "error": f"会话不存在: {session_id}"}

            outline = state.get("outline", {})
            sections = outline.get("sections", [])

            # 统计进度
            completed_steps = []
            if outline:
                completed_steps.append("plan")
            if state.get("sections"):
                completed_steps.append("search")
            if any(s.get("insights") for s in state.get("sections", {}).values()):
                completed_steps.append("analyze")
            if state.get("final_report"):
                completed_steps.append("write")
            if state.get("review"):
                completed_steps.append("review")

            return {
                "success": True,
                "data": {
                    "session_id": session_id,
                    "query": state.get("query", ""),
                    "current_phase": state.get("phase", ""),
                    "completed_steps": completed_steps,
                    "progress": f"{len(completed_steps)}/5",
                    "outline": {
                        "sections_count": len(sections),
                        "sections": sections
                    },
                    "has_report": bool(state.get("final_report")),
                    "has_review": bool(state.get("review")),
                    "review_approved": state.get("review", {}).get("approved", False)
                }
            }

        except Exception as e:
            self._logger.error(f"Get state error: {e}")
            return {"success": False, "error": str(e)}
