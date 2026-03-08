# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MCP Server 主入口（Claude Skills 架构）

基于Claude Skills架构重构：
- 工具定义在 SKILL.md 文件中
- MCP Server 仅暴露单一的 `skill` 工具用于加载 Skills
- Python Skill类仅作为后端工具实现的容器
- Token消耗从 ~17,000 降低到 ~200 (启动) + ~2,000 (调用时)
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

# 本地导入（Skills仅用于后端实现，不再用于MCP工具注册）
from app.mcp_server.skills import (
    MarketDataSkill,
    BaseSkill,
    FinancialAnalysisSkill,
    RiskAssessmentSkill
)
from app.mcp_server.skills.deep_research_split import DeepResearchSkillSplit
from app.mcp_server.config import get_config


# 配置日志 - 只输出到文件，避免干扰 STDIO 通信
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'mcp_server.log'))
        # 移除 StreamHandler(sys.stderr) 以避免干扰 MCP STDIO 通信
    ]
)
logger = logging.getLogger("MCP Server")


class FinancialMCPServer:
    """
    金融研投助手 MCP Server（Claude Skills 架构）

    改造要点：
    1. Skills目录: backend/claude_skills/
    2. 启动时加载所有SKILL.md的frontmatter (~200 tokens)
    3. 调用时按需加载完整的SKILL.md (~2,000 tokens)
    4. Python Skill类仅用于后端工具实现，不再注册MCP工具
    """

    def __init__(self):
        self.config = get_config()
        self.skills: Dict[str, BaseSkill] = {}  # Python Skills (后端实现)
        self.skill_metadata: Dict[str, Dict] = {}  # SKILL.md frontmatter
        self.skills_dir = Path(_backend_dir) / "claude_skills"
        self.server = Server(self.config.server_name)
        self._register_handlers()

    def register_skill(self, skill: BaseSkill):
        """
        注册 Skill (保留用于后端实现)

        Args:
            skill: Skill 实例
        """
        self.skills[skill.name] = skill
        logger.info(f"已注册后端 Skill: {skill.name} ({skill.tool_count} 个工具实现)")

    def _load_skill_metadata(self) -> Dict[str, Dict]:
        """
        加载所有 Skills 的 frontmatter (Level 1加载)

        遍历 claude_skills/ 目录，读取每个 SKILL.md 的 YAML frontmatter

        Returns:
            {skill_name: {name, description, allowed_tools}}
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

                # 解析 YAML frontmatter
                if content.startswith("---"):
                    yaml_end = content.find("---", 3)
                    if yaml_end > 0:
                        yaml_content = content[3:yaml_end].strip()

                        # 简单解析YAML (生产环境应使用yaml库)
                        yaml_data = {}
                        for line in yaml_content.split('\n'):
                            if ':' in line:
                                key, value = line.split(':', 1)
                                key = key.strip()
                                value = value.strip()

                                # 处理数组
                                if value.startswith('[') and value.endswith(']'):
                                    value = [v.strip() for v in value[1:-1].split(',')]

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
            列出所有可用的工具（Claude Skills 架构）

            仅返回单一的 `skill` 工具，用于加载 Skills
            """
            # 加载 Skill metadata
            self.skill_metadata = self._load_skill_metadata()

            # 构建可用 skills 列表描述
            available_skills = list(self.skill_metadata.keys())
            skills_desc = ", ".join(available_skills) if available_skills else "无"

            # 返回单一的 skill 工具
            tools = [
                Tool(
                    name="skill",
                    description=f"Load and execute a Claude Skill. Available skills: {skills_desc}",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "enum": available_skills,
                                "description": f"Skill name to load. Available: {skills_desc}"
                            }
                        },
                        "required": ["name"]
                    }
                )
            ]

            logger.info(f"返回 skill 工具，可用 Skills: {available_skills}")
            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """调用指定工具（Claude Skills 架构）"""
            logger.info(f"调用工具: {name}, 参数: {arguments}")

            # 仅处理 skill 工具
            if name == "skill":
                skill_name = arguments.get("name")

                if not skill_name:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": "缺少必需参数: name"
                        }, ensure_ascii=False)
                    )]

                # 检查 Skill 是否存在
                skill_path = self.skills_dir / skill_name / "SKILL.md"
                if not skill_path.exists():
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "success": False,
                            "error": f"Skill '{skill_name}' 不存在"
                        }, ensure_ascii=False)
                    )]

                # 读取并返回完整的 SKILL.md 内容 (Level 2 加载)
                try:
                    skill_content = skill_path.read_text(encoding='utf-8')

                    # 返回 SKILL.md 内容（这会被 Claude 解析为指令）
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

            else:
                # 不再支持旧的 skill_name.tool_name 格式
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "success": False,
                        "error": f"未知工具: {name}。请使用 'skill' 工具加载 Skills。"
                    }, ensure_ascii=False)
                )]
    
    async def run(self):
        """运行 MCP Server"""
        logger.info(f"启动 MCP Server: {self.config.server_name} v{self.config.server_version}")
        logger.info(f"Claude Skills 架构 - Skills目录: {self.skills_dir}")
        logger.info(f"已注册 {len(self.skills)} 个后端 Skill 实现")

        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


def create_server() -> FinancialMCPServer:
    """
    创建并配置 MCP Server（Claude Skills 架构）

    注意：Skills 现在通过 SKILL.md 定义，这里注册的 Python Skill
    仅用于后端工具实现，不再用于 MCP 工具注册。

    Returns:
        配置好的 FinancialMCPServer 实例
    """
    server = FinancialMCPServer()

    # 注册后端 Skills（用于工具实现，不暴露为MCP工具）
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

    logger.info(f"✅ MCP Server 创建完成 (Claude Skills 架构)")
    logger.info(f"📊 Token 优化: ~17,000 → ~200 (启动) + ~2,000 (调用时)")

    return server


async def main():
    """主入口"""
    server = create_server()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
