# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MCP Server 主入口（渐进式披露 + MCP 执行架构）

三轮架构：
- Round 1: Skill 选择 — LLM 通过 `skill` 工具选择 skill，获取 SKILL.md
- Round 2: 工具调用 — 编排层通过 `get_skill_tools` 获取工具定义，LLM 调用具体工具
- Round 3: 最终回答 — LLM 基于工具返回数据生成回答

MCP Server 暴露 3 个元工具：
1. `skill` — 返回 SKILL.md 内容（业务指导）
2. `get_skill_tools` — 返回该 skill 下的工具 JSON Schema
3. `execute_skill_tool` — 执行具体工具
"""

import sys
import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

# 添加项目根目录到 Python 路径
_current_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(os.path.dirname(_current_dir))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# MCP SDK
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# 本地导入
from app.mcp_server.skills import (
    MarketDataSkill,
    BaseSkill,
    FinancialAnalysisSkill,
    RiskAssessmentSkill,
    DeepResearchSkillSplit,
    WebResearchSkill,
    DataAnalysisSkill,
    SectorAnalysisSkill
)
from app.mcp_server.config import get_config


# 配置日志 - 只输出到文件，避免干扰 STDIO 通信
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'mcp_server.log'))
    ]
)
logger = logging.getLogger("MCP Server")


class FinancialMCPServer:
    """
    金融研投助手 MCP Server（渐进式披露 + MCP 执行架构）

    三个元工具:
    1. skill — 返回 SKILL.md 内容
    2. get_skill_tools — 返回 skill 的工具 JSON Schema
    3. execute_skill_tool — 执行具体工具
    """

    def __init__(self):
        self.config = get_config()
        self.skills: Dict[str, BaseSkill] = {}
        self.skill_metadata: Dict[str, Dict] = {}
        self.skills_dir = Path(_backend_dir) / "claude_skills"
        self.server = Server(self.config.server_name)
        self._register_handlers()

    def register_skill(self, skill: BaseSkill):
        """注册 Skill 实例"""
        self.skills[skill.name] = skill
        logger.info(f"已注册 Skill: {skill.name} ({skill.tool_count} 个工具)")

    def _load_skill_metadata(self) -> Dict[str, Dict]:
        """
        加载所有 Skills 的 frontmatter

        Returns:
            {skill_name: {name, description, ...}}
        """
        metadata = {}

        if not self.skills_dir.exists():
            logger.warning(f"Skills目录不存在: {self.skills_dir}")
            return metadata

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            try:
                content = skill_md.read_text(encoding='utf-8')

                if content.startswith("---"):
                    yaml_end = content.find("---", 3)
                    if yaml_end > 0:
                        yaml_content = content[3:yaml_end].strip()

                        yaml_data = {}
                        for line in yaml_content.split('\n'):
                            if ':' in line:
                                key, value = line.split(':', 1)
                                key = key.strip()
                                value = value.strip()

                                if value.startswith('[') and value.endswith(']'):
                                    value = [v.strip() for v in value[1:-1].split(',')]
                                # 去掉引号
                                elif value.startswith('"') and value.endswith('"'):
                                    value = value[1:-1]

                                yaml_data[key] = value

                        metadata[skill_dir.name] = yaml_data
                        logger.info(f"已加载 Skill metadata: {skill_dir.name}")

            except Exception as e:
                logger.error(f"加载 {skill_dir.name}/SKILL.md 失败: {e}")

        return metadata

    def _register_handlers(self):
        """注册 MCP Server 处理器"""

        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            """
            返回 3 个元工具: skill, get_skill_tools, execute_skill_tool
            """
            self.skill_metadata = self._load_skill_metadata()

            available_skills = list(self.skill_metadata.keys())
            skills_desc = ", ".join(available_skills) if available_skills else "无"

            # 构建 skill 描述信息（包含每个 skill 的摘要）
            skill_descriptions = []
            for name, meta in self.skill_metadata.items():
                desc = meta.get('description', '无描述')
                skill_descriptions.append(f"- {name}: {desc}")
            skills_detail = "\n".join(skill_descriptions) if skill_descriptions else "无可用 skill"

            tools = [
                # 1. skill — 加载 SKILL.md 内容
                Tool(
                    name="skill",
                    description=f"加载指定 Skill 的详细说明文档（SKILL.md）。可用 skills:\n{skills_detail}",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": available_skills,
                                "description": f"Skill 名称。可用: {skills_desc}"
                            }
                        },
                        "required": ["name"]
                    }
                ),
                # 2. get_skill_tools — 获取 skill 的工具 JSON Schema
                Tool(
                    name="get_skill_tools",
                    description=f"获取指定 Skill 下所有工具的 JSON Schema 定义，用于构建 function calling 工具列表。可用 skills: {skills_desc}",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": available_skills,
                                "description": f"Skill 名称。可用: {skills_desc}"
                            }
                        },
                        "required": ["name"]
                    }
                ),
                # 3. execute_skill_tool — 执行具体工具
                Tool(
                    name="execute_skill_tool",
                    description="执行指定 Skill 下的具体工具。工具名格式为 skill_name.tool_name",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "description": "Skill 名称"
                            },
                            "tool_name": {
                                "type": "string",
                                "description": "工具名称（不含 skill 前缀）"
                            },
                            "arguments": {
                                "type": "object",
                                "description": "工具参数",
                                "default": {}
                            }
                        },
                        "required": ["skill_name", "tool_name"]
                    }
                )
            ]

            logger.info(f"返回 3 个元工具，可用 Skills: {available_skills}")
            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """调用工具"""
            logger.info(f"调用工具: {name}, 参数: {arguments}")

            if name == "skill":
                return await self._handle_skill(arguments)
            elif name == "get_skill_tools":
                return await self._handle_get_skill_tools(arguments)
            elif name == "execute_skill_tool":
                return await self._handle_execute_skill_tool(arguments)
            else:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"未知工具: {name}。可用工具: skill, get_skill_tools, execute_skill_tool"
                    }, ensure_ascii=False)
                )]

    async def _handle_skill(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """处理 skill 工具调用 — 返回 SKILL.md 内容"""
        skill_name = arguments.get("name")

        if not skill_name:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "缺少必需参数: name"
                }, ensure_ascii=False)
            )]

        skill_path = self.skills_dir / skill_name / "SKILL.md"
        if not skill_path.exists():
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Skill '{skill_name}' 不存在"
                }, ensure_ascii=False)
            )]

        try:
            skill_content = skill_path.read_text(encoding='utf-8')
            return [TextContent(
                type="text",
                text=skill_content
            )]
        except Exception as e:
            logger.error(f"加载 Skill '{skill_name}' 失败: {e}")
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"加载 Skill 失败: {str(e)}"
                }, ensure_ascii=False)
            )]

    async def _handle_get_skill_tools(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """处理 get_skill_tools 调用 — 返回工具 JSON Schema 列表"""
        skill_name = arguments.get("name")

        if not skill_name:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "缺少必需参数: name"
                }, ensure_ascii=False)
            )]

        if skill_name not in self.skills:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Skill '{skill_name}' 未注册（后端实现不存在）"
                }, ensure_ascii=False)
            )]

        skill = self.skills[skill_name]
        tools_json = skill.discover_tools_json()

        # 给每个工具名添加 skill 前缀: {skill_name}.{tool_name}
        for tool in tools_json:
            tool["name"] = f"{skill_name}.{tool['name']}"

        return [TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "skill_name": skill_name,
                "tool_count": len(tools_json),
                "tools": tools_json
            }, ensure_ascii=False)
        )]

    async def _handle_execute_skill_tool(self, arguments: Dict[str, Any]) -> List[TextContent]:
        """处理 execute_skill_tool 调用 — 执行具体工具"""
        skill_name = arguments.get("skill_name")
        tool_name = arguments.get("tool_name")
        tool_arguments = arguments.get("arguments", {})

        if not skill_name or not tool_name:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": "缺少必需参数: skill_name 和 tool_name"
                }, ensure_ascii=False)
            )]

        if skill_name not in self.skills:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Skill '{skill_name}' 未注册"
                }, ensure_ascii=False)
            )]

        skill = self.skills[skill_name]

        if not skill.has_tool(tool_name):
            available = [t.name for t in skill.discover_tools()]
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"工具 '{tool_name}' 不存在于 Skill '{skill_name}'。可用工具: {available}"
                }, ensure_ascii=False)
            )]

        try:
            result = await skill.execute_tool(tool_name, tool_arguments)
            return [TextContent(
                type="text",
                text=json.dumps(result.to_dict(), ensure_ascii=False)
            )]
        except Exception as e:
            logger.error(f"执行工具 {skill_name}.{tool_name} 失败: {e}")
            return [TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"工具执行失败: {str(e)}"
                }, ensure_ascii=False)
            )]

    async def run(self):
        """运行 MCP Server"""
        logger.info(f"启动 MCP Server: {self.config.server_name} v{self.config.server_version}")
        logger.info(f"渐进式披露架构 - Skills目录: {self.skills_dir}")
        logger.info(f"已注册 {len(self.skills)} 个 Skill 实现")

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def create_server() -> FinancialMCPServer:
    """
    创建并配置 MCP Server

    Returns:
        配置好的 FinancialMCPServer 实例
    """
    server = FinancialMCPServer()

    # 注册 Skills
    try:
        market_data_skill = MarketDataSkill()
        server.register_skill(market_data_skill)
    except Exception as e:
        logger.warning(f"MarketData Skill 注册失败: {e}")

    try:
        financial_analysis_skill = FinancialAnalysisSkill()
        server.register_skill(financial_analysis_skill)
    except Exception as e:
        logger.warning(f"FinancialAnalysis Skill 注册失败: {e}")

    try:
        risk_assessment_skill = RiskAssessmentSkill()
        server.register_skill(risk_assessment_skill)
    except Exception as e:
        logger.warning(f"RiskAssessment Skill 注册失败: {e}")

    try:
        deep_research_skill = DeepResearchSkillSplit()
        server.register_skill(deep_research_skill)
        logger.info("DeepResearch Skill registered successfully")
    except Exception as e:
        logger.warning(f"DeepResearch Skill 注册失败: {e}")

    # 注册 WebResearch Skill
    try:
        web_research_skill = WebResearchSkill()
        server.register_skill(web_research_skill)
        logger.info("WebResearch Skill registered successfully")
    except Exception as e:
        logger.warning(f"WebResearch Skill 注册失败: {e}")

    # 注册 DataAnalysis Skill
    try:
        data_analysis_skill = DataAnalysisSkill()
        server.register_skill(data_analysis_skill)
        logger.info("DataAnalysis Skill registered successfully")
    except Exception as e:
        logger.warning(f"DataAnalysis Skill 注册失败: {e}")

    # 注册 SectorAnalysis Skill
    try:
        sector_analysis_skill = SectorAnalysisSkill()
        server.register_skill(sector_analysis_skill)
        logger.info("SectorAnalysis Skill registered successfully")
    except Exception as e:
        logger.warning(f"SectorAnalysis Skill 注册失败: {e}")

    logger.info(f"MCP Server 创建完成（渐进式披露架构）")
    logger.info(f"元工具: skill, get_skill_tools, execute_skill_tool")

    return server


async def main():
    """主入口"""
    server = create_server()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
