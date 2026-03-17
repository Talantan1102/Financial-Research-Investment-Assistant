"""
Tool schemas for LLM agent prompts — 金融研投助手渐进式披露架构

三轮流程：
1. skill(name) — 获取 SKILL.md 业务文档
2. get_skill_tools(name) — 获取 Skill 的工具 JSON Schema
3. execute_skill_tool(skill_name, tool_name, arguments) — 执行具体工具

与金融研投助手 MCP Server 完全一致。
"""

from typing import Optional, List, Dict, Any


def get_tool_schemas(allowed_tools: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Get tool schemas for unified_finance backend.
    
    返回 3 个元工具，对应渐进式披露的三轮流程。

    Args:
        allowed_tools: 工具过滤列表，支持通配符（如 "unified_finance:*"）
                     如果为 None 或空列表，返回所有工具

    Returns:
        符合条件的元工具 schema 列表
    """
    all_tools = [
        # ============ Round 1: Skill 选择 ============
        {
            "type": "function",
            "function": {
                "name": "unified_finance:skill",
                "description": "加载指定 Skill 的详细说明文档（SKILL.md）。可用 skills: market_data(市场数据), financial_analysis(财务分析), sector_analysis(行业分析), risk_assessment(风险评估), data_analysis(数据分析), web_research(网络研究), deep_research(深度研究)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Skill 名称",
                            "enum": [
                                "market_data",
                                "financial_analysis",
                                "sector_analysis",
                                "risk_assessment",
                                "data_analysis",
                                "web_research",
                                "deep_research"
                            ]
                        }
                    },
                    "required": ["name"]
                }
            }
        },
        # ============ Round 2: 工具发现 ============
        {
            "type": "function",
            "function": {
                "name": "unified_finance:get_skill_tools",
                "description": "获取指定 Skill 下所有工具的 JSON Schema 定义，用于构建 function calling 工具列表。建议先调用 skill 了解业务，再调用此工具获取具体工具",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Skill 名称",
                            "enum": [
                                "market_data",
                                "financial_analysis",
                                "sector_analysis",
                                "risk_assessment",
                                "data_analysis",
                                "web_research",
                                "deep_research"
                            ]
                        }
                    },
                    "required": ["name"]
                }
            }
        },
        # ============ Round 3: 工具执行 ============
        {
            "type": "function",
            "function": {
                "name": "unified_finance:execute_skill_tool",
                "description": "执行指定 Skill 下的具体工具。工具名格式为 skill_name.tool_name。建议先调用 skill 和 get_skill_tools 了解可用工具后再执行",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "Skill 名称，如 'market_data', 'financial_analysis'",
                            "enum": [
                                "market_data",
                                "financial_analysis",
                                "sector_analysis",
                                "risk_assessment",
                                "data_analysis",
                                "web_research",
                                "deep_research"
                            ]
                        },
                        "tool_name": {
                            "type": "string",
                            "description": "工具名称（不含 skill 前缀），如 'get_quote', 'calculate_financial_ratios'"
                        },
                        "arguments": {
                            "type": "object",
                            "description": "工具参数，如股票代码、查询条件等",
                            "default": {}
                        }
                    },
                    "required": ["skill_name", "tool_name"]
                }
            }
        }
    ]
    
    # 如果没有指定过滤条件，返回所有工具
    if not allowed_tools:
        return all_tools
    
    # 支持通配符过滤
    filtered_tools = []
    for tool in all_tools:
        tool_name = tool.get("function", {}).get("name", "")
        for pattern in allowed_tools:
            # 支持通配符匹配，如 "unified_finance:*"
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                if tool_name.startswith(prefix):
                    filtered_tools.append(tool)
                    break
            # 精确匹配
            elif tool_name == pattern:
                filtered_tools.append(tool)
                break
    
    return filtered_tools


def get_all_tool_names() -> List[str]:
    """Get all available tool names"""
    return [
        "unified_finance:skill",
        "unified_finance:get_skill_tools", 
        "unified_finance:execute_skill_tool"
    ]


def get_tools_by_resource(resource_type: str) -> List[Dict[str, Any]]:
    """
    Get tools for a specific resource type.
    """
    if resource_type == "unified_finance":
        return get_tool_schemas()
    return []


# 兼容旧代码的别名
get_finance_research_tool_schemas = get_tool_schemas


__all__ = [
    "get_tool_schemas",
    "get_all_tool_names",
    "get_tools_by_resource",
    "get_finance_research_tool_schemas",
]
