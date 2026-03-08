# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""DeepResearch Skill - 增强版（双模式支持）

新增拆分工具，支持 LLM 逐步调用各个 Agent
"""

from typing import Dict, Any, Optional, List
from app.mcp_server.skills.deep_research import DeepResearchSkill
from app.mcp_server.skills.base import ToolParameter


class DeepResearchSkillEnhanced(DeepResearchSkill):
    """
    DeepResearch Skill 增强版

    在原有基础上新增细粒度工具，支持：
    1. 完整流程（原有）- execute_research
    2. 分步执行（新增）- plan → research_section → write_section → review
    3. 状态查询（新增）- get_status, get_outline
    """

    def _register_tools(self):
        """注册所有工具（包含原有 + 新增）"""

        # ========== 原有工具 ==========
        super()._register_tools()

        # ========== 新增：分步执行工具 ==========

        # 1. 规划研究大纲
        self.register_tool(
            name="plan_outline",
            handler=self.plan_outline,
            description="第1步：规划研究大纲。让 Architect Agent 分析查询，生成结构化的研究大纲（章节+假设）。返回大纲供后续使用。",
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
                    description="会话ID（可选，不提供则自动生成）",
                    required=False
                )
            ]
        )

        # 2. 研究单个章节
        self.register_tool(
            name="research_section",
            handler=self.research_section,
            description="第2步：研究指定章节。让 Scout + Wizard Agent 搜索信息并分析数据。返回该章节的研究成果（事实+洞察+来源）。",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID（必需，用于获取大纲）",
                    required=True
                ),
                ToolParameter(
                    name="section_id",
                    type="string",
                    description="章节ID，例如：'section_1'、'section_2'",
                    required=True
                ),
                ToolParameter(
                    name="search_web",
                    type="boolean",
                    description="是否启用网络搜索（默认True）",
                    required=False,
                    default=True
                )
            ]
        )

        # 3. 撰写章节内容
        self.register_tool(
            name="write_section",
            handler=self.write_section,
            description="第3步：撰写章节内容。让 Writer Agent 基于研究数据撰写该章节。返回章节草稿。",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID（必需）",
                    required=True
                ),
                ToolParameter(
                    name="section_id",
                    type="string",
                    description="章节ID",
                    required=True
                )
            ]
        )

        # 4. 生成完整报告
        self.register_tool(
            name="generate_full_report",
            handler=self.generate_full_report,
            description="第4步：生成完整报告。让 Writer Agent 整合所有章节，生成完整的研究报告（含摘要、结论、参考文献）。",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID（必需）",
                    required=True
                )
            ]
        )

        # 5. 质量评审
        self.register_tool(
            name="review_report",
            handler=self.review_report,
            description="第5步：质量评审。让 Critic Agent 评审完整报告，指出问题并给出改进建议。返回评分和修改意见。",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID（必需）",
                    required=True
                )
            ]
        )

        # 6. 获取研究状态
        self.register_tool(
            name="get_status",
            handler=self.get_status,
            description="查询研究状态。返回当前阶段、已完成的章节、进度百分比等信息。",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID",
                    required=True
                )
            ]
        )

        # 7. 获取大纲
        self.register_tool(
            name="get_outline",
            handler=self.get_outline,
            description="获取研究大纲。返回所有章节的标题、描述和ID，供后续调用使用。",
            parameters=[
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="会话ID",
                    required=True
                )
            ]
        )

    # ========== 新增工具实现 ==========

    async def plan_outline(
        self,
        query: str,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        规划研究大纲

        调用 Architect Agent 生成研究大纲
        """
        try:
            from app.service.deep_research_v2.state import create_initial_state

            service = self.get_service()

            # 生成 session_id
            if not session_id:
                import uuid
                session_id = str(uuid.uuid4())

            # 创建初始状态
            state = create_initial_state(query, session_id)

            # 只执行 Architect 阶段
            result_state = await service.graph.architect.process(state)

            # 保存状态到检查点服务
            from app.service.checkpoint_service import get_checkpoint_service
            checkpoint_service = get_checkpoint_service()
            if checkpoint_service:
                await checkpoint_service.save_checkpoint(session_id, result_state)

            # 返回大纲
            outline = result_state.get("outline", {})

            return {
                "success": True,
                "data": {
                    "session_id": session_id,
                    "query": query,
                    "outline": outline,
                    "sections": outline.get("sections", []),
                    "hypotheses": outline.get("hypotheses", []),
                    "total_sections": len(outline.get("sections", []))
                }
            }

        except Exception as e:
            self._logger.error(f"Plan outline error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    async def research_section(
        self,
        session_id: str,
        section_id: str,
        search_web: bool = True
    ) -> Dict[str, Any]:
        """
        研究单个章节

        调用 Scout + Wizard Agent 进行搜索和分析
        """
        try:
            # 加载状态
            from app.service.checkpoint_service import get_checkpoint_service
            checkpoint_service = get_checkpoint_service()

            if not checkpoint_service:
                return {
                    "success": False,
                    "error": "检查点服务不可用"
                }

            state = await checkpoint_service.load_checkpoint(session_id)
            if not state:
                return {
                    "success": False,
                    "error": f"未找到会话: {session_id}，请先调用 plan_outline"
                }

            # 找到目标章节
            outline = state.get("outline", {})
            sections = outline.get("sections", [])

            target_section = None
            for section in sections:
                if section.get("id") == section_id:
                    target_section = section
                    break

            if not target_section:
                return {
                    "success": False,
                    "error": f"章节 {section_id} 不存在"
                }

            # 设置当前章节
            state["current_section"] = target_section
            state["search_web"] = search_web

            service = self.get_service()

            # 执行 Scout（搜索）
            state = await service.graph.scout.process(state)

            # 执行 Wizard（分析）
            state = await service.graph.wizard.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, state)

            # 提取该章节的研究结果
            section_data = state.get("sections", {}).get(section_id, {})

            return {
                "success": True,
                "data": {
                    "section_id": section_id,
                    "section_title": target_section.get("title", ""),
                    "facts": section_data.get("facts", []),
                    "insights": section_data.get("insights", []),
                    "sources": section_data.get("sources", []),
                    "data_analysis": section_data.get("analysis", {})
                }
            }

        except Exception as e:
            self._logger.error(f"Research section error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    async def write_section(
        self,
        session_id: str,
        section_id: str
    ) -> Dict[str, Any]:
        """
        撰写章节内容

        调用 Writer Agent 基于研究数据撰写章节
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service
            checkpoint_service = get_checkpoint_service()

            state = await checkpoint_service.load_checkpoint(session_id)
            if not state:
                return {
                    "success": False,
                    "error": f"未找到会话: {session_id}"
                }

            # 找到目标章节
            outline = state.get("outline", {})
            sections = outline.get("sections", [])

            target_section = None
            for section in sections:
                if section.get("id") == section_id:
                    target_section = section
                    break

            if not target_section:
                return {
                    "success": False,
                    "error": f"章节 {section_id} 不存在"
                }

            # 检查是否已研究
            section_data = state.get("sections", {}).get(section_id, {})
            if not section_data.get("facts"):
                return {
                    "success": False,
                    "error": f"章节 {section_id} 尚未研究，请先调用 research_section"
                }

            state["current_section"] = target_section

            service = self.get_service()

            # 执行 Writer 撰写该章节
            state = await service.graph.writer.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, state)

            # 提取章节草稿
            draft = section_data.get("draft", "")

            return {
                "success": True,
                "data": {
                    "section_id": section_id,
                    "section_title": target_section.get("title", ""),
                    "content": draft,
                    "word_count": len(draft)
                }
            }

        except Exception as e:
            self._logger.error(f"Write section error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    async def generate_full_report(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        生成完整报告

        整合所有章节，生成最终报告
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service
            checkpoint_service = get_checkpoint_service()

            state = await checkpoint_service.load_checkpoint(session_id)
            if not state:
                return {
                    "success": False,
                    "error": f"未找到会话: {session_id}"
                }

            service = self.get_service()

            # 执行 Writer 生成完整报告
            state = await service.graph.writer.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, state)

            # 提取报告
            report = state.get("final_report", "")

            return {
                "success": True,
                "data": {
                    "report": report,
                    "word_count": len(report),
                    "sections_count": len(state.get("outline", {}).get("sections", []))
                }
            }

        except Exception as e:
            self._logger.error(f"Generate report error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    async def review_report(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        质量评审

        调用 Critic Agent 评审报告
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service
            checkpoint_service = get_checkpoint_service()

            state = await checkpoint_service.load_checkpoint(session_id)
            if not state:
                return {
                    "success": False,
                    "error": f"未找到会话: {session_id}"
                }

            if not state.get("final_report"):
                return {
                    "success": False,
                    "error": "尚未生成完整报告，请先调用 generate_full_report"
                }

            service = self.get_service()

            # 执行 Critic 评审
            state = await service.graph.critic.process(state)

            # 保存状态
            await checkpoint_service.save_checkpoint(session_id, state)

            # 提取评审结果
            review = state.get("review", {})

            return {
                "success": True,
                "data": {
                    "quality_score": review.get("score", 0),
                    "approved": review.get("approved", False),
                    "strengths": review.get("strengths", []),
                    "weaknesses": review.get("weaknesses", []),
                    "suggestions": review.get("suggestions", [])
                }
            }

        except Exception as e:
            self._logger.error(f"Review report error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }

    async def get_status(
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
                return {
                    "success": False,
                    "error": f"未找到会话: {session_id}"
                }

            outline = state.get("outline", {})
            sections = outline.get("sections", [])

            # 统计进度
            completed_sections = 0
            for section in sections:
                section_id = section.get("id")
                section_data = state.get("sections", {}).get(section_id, {})
                if section_data.get("draft"):
                    completed_sections += 1

            total_sections = len(sections)
            progress = (completed_sections / total_sections * 100) if total_sections > 0 else 0

            return {
                "success": True,
                "data": {
                    "session_id": session_id,
                    "query": state.get("query", ""),
                    "phase": state.get("phase", ""),
                    "progress": round(progress, 1),
                    "completed_sections": completed_sections,
                    "total_sections": total_sections,
                    "has_outline": bool(outline),
                    "has_final_report": bool(state.get("final_report")),
                    "has_review": bool(state.get("review"))
                }
            }

        except Exception as e:
            self._logger.error(f"Get status error: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_outline(
        self,
        session_id: str
    ) -> Dict[str, Any]:
        """
        获取研究大纲
        """
        try:
            from app.service.checkpoint_service import get_checkpoint_service
            checkpoint_service = get_checkpoint_service()

            state = await checkpoint_service.load_checkpoint(session_id)
            if not state:
                return {
                    "success": False,
                    "error": f"未找到会话: {session_id}"
                }

            outline = state.get("outline", {})

            return {
                "success": True,
                "data": {
                    "query": state.get("query", ""),
                    "outline": outline,
                    "sections": outline.get("sections", []),
                    "hypotheses": outline.get("hypotheses", [])
                }
            }

        except Exception as e:
            self._logger.error(f"Get outline error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
