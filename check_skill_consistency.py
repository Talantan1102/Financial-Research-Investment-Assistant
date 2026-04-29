#!/usr/bin/env python3
"""
Skill 一致性检查脚本 - 基于最新渐进式披露架构

验证内容：
1. Skill 文档一致性（SKILL.md vs 代码实现）
2. 渐进式披露架构一致性
3. 参数一致性
4. 返回结果一致性

作者: V
更新: 2026-03-19
"""

import contextlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Parameter:
    """参数定义"""

    name: str
    type: str
    required: bool
    description: str = ""
    default: Any = None
    enum: list[str] | None = None

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, Parameter):
            return self.name == other.name
        return False


@dataclass
class Tool:
    """工具定义"""

    name: str
    description: str = ""
    parameters: list[Parameter] = field(default_factory=list)
    returns: dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, Tool):
            return self.name == other.name
        return False


@dataclass
class SkillMetadata:
    """Skill 元数据（from frontmatter）"""

    name: str
    description: str
    version: str
    tool_count: int


@dataclass
class CheckResult:
    """检查结果"""

    status: str  # '✅', '⚠️', '❌'
    message: str
    details: list[str] = field(default_factory=list)


class SkillDocParser:
    """解析 SKILL.md 文件"""

    def __init__(self, content: str):
        self.content = content
        self.tools: dict[str, Tool] = {}
        self.metadata: SkillMetadata | None = None

    def parse(self) -> tuple[dict[str, Tool], SkillMetadata | None]:
        """解析文档，提取工具和元数据"""
        self.metadata = self._parse_frontmatter()
        self.tools = self._parse_tools()
        return self.tools, self.metadata

    def _parse_frontmatter(self) -> SkillMetadata | None:
        """解析 YAML frontmatter"""
        if not self.content.startswith("---"):
            return None

        yaml_end = self.content.find("---", 3)
        if yaml_end < 0:
            return None

        yaml_content = self.content[3:yaml_end].strip()

        metadata = {}
        current_key = None
        current_value_lines = []

        for line in yaml_content.split("\n"):
            if ":" in line and not line.strip().startswith("-"):
                # 保存之前的 key-value
                if current_key:
                    metadata[current_key] = "\n".join(current_value_lines).strip()

                key, value = line.split(":", 1)
                current_key = key.strip()
                current_value_lines = [value.strip()]
            else:
                if current_key:
                    current_value_lines.append(line.strip())

        # 保存最后一个 key-value
        if current_key:
            metadata[current_key] = "\n".join(current_value_lines).strip()

        # 清理值
        for key in metadata:
            value = metadata[key]
            if (
                value.startswith('"')
                and value.endswith('"')
                or value.startswith("'")
                and value.endswith("'")
            ):
                metadata[key] = value[1:-1]

        try:
            return SkillMetadata(
                name=metadata.get("name", ""),
                description=metadata.get("description", ""),
                version=metadata.get("version", "1.0"),
                tool_count=int(metadata.get("tool_count", 0)),
            )
        except (ValueError, TypeError):
            return None

    def _parse_tools(self) -> dict[str, Tool]:
        """解析工具定义"""
        tools = {}

        # 找到所有工具定义 (### N. tool_name - description 或 ### tool_name - description)
        tool_pattern = r"###\s*(?:\d+\.\s*)?(\w+)\s*[-\u2013-\u2014]\s*(.+?)(?=###|\Z)"
        tool_matches = list(re.finditer(tool_pattern, self.content, re.DOTALL))

        for match in tool_matches:
            tool_name = match.group(1).strip()
            tool_section = match.group(0)

            # 过滤非工具名称（如 Auto-Invoked）
            if "-" in tool_name or tool_name.lower() in [
                "auto",
                "invoked",
                "example",
                "note",
                "warning",
                "tip",
                "hint",
            ]:
                continue

            tool = Tool(name=tool_name)
            tool.description = self._extract_description(tool_section)
            tool.parameters = self._parse_parameters(tool_section)
            tool.returns = self._parse_returns(tool_section)

            tools[tool_name] = tool

        return tools

    def _extract_description(self, section: str) -> str:
        """提取工具描述"""
        # 查找 **Purpose**: 或描述段落
        purpose_match = re.search(r"\*\*Purpose\*\*[:：]?\s*(.+?)(?=\*\*|$)", section, re.DOTALL)
        if purpose_match:
            return purpose_match.group(1).strip().replace("\n", " ")

        # 尝试第一行描述
        lines = section.split("\n")
        for line in lines[1:]:  # 跳过标题行
            line = line.strip()
            if line and not line.startswith("|") and not line.startswith("**"):
                return line

        return ""

    def _parse_parameters(self, section: str) -> list[Parameter]:
        """解析参数表格"""
        params = []

        # 查找参数表格 - 支持多种格式
        param_table_patterns = [
            r"\*\*Parameters\*\*[:：]?\s*\n\|(.+?)\|\n\|[-:\s|]+\|\n((?:\|.+?\|\n)+)",
            r"\*\*参数\*\*[:：]?\s*\n\|(.+?)\|\n\|[-:\s|]+\|\n((?:\|.+?\|\n)+)",
        ]

        match = None
        for pattern in param_table_patterns:
            match = re.search(pattern, section, re.DOTALL)
            if match:
                break

        if match:
            header_line = match.group(1)
            rows = match.group(2).strip().split("\n")

            # 解析表头
            headers = [h.strip().lower() for h in header_line.split("|") if h.strip()]

            for row in rows:
                cells = [c.strip() for c in row.split("|") if c.strip()]
                if len(cells) >= 3:
                    param_dict = {}
                    for i, header in enumerate(headers):
                        if i < len(cells):
                            param_dict[header] = cells[i]

                    # 创建参数对象
                    name = param_dict.get("name", "")
                    if not name:
                        continue

                    param_type = self._normalize_type(param_dict.get("type", "string"))
                    required = self._parse_required(param_dict.get("required", "Yes"))
                    description = param_dict.get("description", "")
                    default = self._parse_default(param_dict.get("default", "null"))

                    param = Parameter(
                        name=name,
                        type=param_type,
                        required=required,
                        description=description,
                        default=default,
                    )
                    params.append(param)

        return params

    def _parse_returns(self, section: str) -> dict[str, Any]:
        """解析返回结果定义"""
        returns = {}

        # 查找 Returns 部分
        returns_match = re.search(r"\*\*Returns\*\*[:：]?\s*(.+?)(?=\*\*|$)", section, re.DOTALL)
        if returns_match:
            returns_text = returns_match.group(1).strip()
            # 尝试提取 JSON 示例
            json_match = re.search(r"```json\s*(.+?)```", returns_text, re.DOTALL)
            if json_match:
                with contextlib.suppress(json.JSONDecodeError):
                    returns["example"] = json.loads(json_match.group(1))

        return returns

    def _normalize_type(self, type_str: str) -> str:
        """规范化类型名称"""
        type_map = {
            "string": "string",
            "str": "string",
            "integer": "integer",
            "int": "integer",
            "number": "number",
            "float": "number",
            "boolean": "boolean",
            "bool": "boolean",
            "array": "array",
            "list": "array",
            "object": "object",
            "dict": "object",
        }
        return type_map.get(type_str.lower(), type_str.lower())

    def _parse_required(self, required_str: str) -> bool:
        """解析 required 字段"""
        if not required_str:
            return True
        required_str = required_str.lower().strip()
        return required_str in ["yes", "是", "true", "required", "必需", "必填"]

    def _parse_default(self, default_str: str) -> Any:
        """解析默认值"""
        if not default_str:
            return None

        default_str = default_str.strip()
        lower_str = default_str.lower()

        # 处理 Markdown 反引号包裹的值
        if default_str.startswith("`") and default_str.endswith("`"):
            default_str = default_str[1:-1]
            lower_str = default_str.lower()

        if lower_str in ["null", "-", "none", "", "n/a", "nil"]:
            return None
        if lower_str == "true":
            return True
        if lower_str == "false":
            return False

        # 尝试转换为数字
        try:
            if "." in default_str:
                return float(default_str)
            return int(default_str)
        except ValueError:
            pass

        # 去除引号
        if (default_str.startswith('"') and default_str.endswith('"')) or (
            default_str.startswith("'") and default_str.endswith("'")
        ):
            return default_str[1:-1]

        return default_str


class CodeParser:
    """解析 Python 代码文件"""

    def __init__(self, content: str):
        self.content = content
        self.tools: dict[str, Tool] = {}

    def parse(self) -> dict[str, Tool]:
        """解析代码，提取工具注册"""
        tools = {}

        # 查找所有 register_tool 调用
        register_starts = [m.start() for m in re.finditer(r"self\.register_tool\(", self.content)]

        for i, start_pos in enumerate(register_starts):
            # 确定这个 register_tool 调用的结束位置
            if i + 1 < len(register_starts):
                end_pos = register_starts[i + 1]
            else:
                # 找到下一个方法定义或类定义的结束
                next_def = re.search(
                    r"\n\s+(?:async\s+)?def\s+|\n\s+class\s+|\n\s+#\s*=+", self.content[start_pos:]
                )
                end_pos = start_pos + next_def.start() if next_def else len(self.content)

            block = self.content[start_pos:end_pos]
            tool = self._parse_tool_block(block)
            if tool:
                tools[tool.name] = tool

        return tools

    def _parse_tool_block(self, block: str) -> Tool | None:
        """解析单个工具注册块"""
        # 提取工具名
        name_match = re.search(r'name\s*=\s*["\'](\w+)["\']', block)
        if not name_match:
            return None

        tool_name = name_match.group(1)
        tool = Tool(name=tool_name)

        # 提取描述
        desc_match = re.search(r'description\s*=\s*["\']([^"\']*)["\']', block)
        if desc_match:
            tool.description = desc_match.group(1)

        # 提取参数部分
        params_match = re.search(r"parameters\s*=\s*\[(.*)\]", block, re.DOTALL)
        if params_match:
            params_content = params_match.group(1)
            tool.parameters = self._parse_parameters(params_content)

        return tool

    def _parse_parameters(self, params_content: str) -> list[Parameter]:
        """解析 ToolParameter 定义"""
        params = []
        param_blocks = self._extract_param_blocks(params_content)

        for block in param_blocks:
            param = self._parse_single_param(block)
            if param:
                params.append(param)

        return params

    def _extract_param_blocks(self, content: str) -> list[str]:
        """提取每个 ToolParameter(...) 块"""
        blocks = []
        i = 0
        while i < len(content):
            match = re.search(r"ToolParameter\(", content[i:])
            if not match:
                break

            start = i + match.start()
            depth = 1
            j = start + len("ToolParameter(")
            while j < len(content) and depth > 0:
                if content[j] == "(":
                    depth += 1
                elif content[j] == ")":
                    depth -= 1
                j += 1

            if depth == 0:
                blocks.append(content[start:j])
            i = j

        return blocks

    def _parse_single_param(self, block: str) -> Parameter | None:
        """解析单个参数定义"""
        name_match = re.search(r'name\s*=\s*["\'](\w+)["\']', block)
        if not name_match:
            return None

        name = name_match.group(1)

        type_match = re.search(r'type\s*=\s*["\'](\w+)["\']', block)
        param_type = type_match.group(1) if type_match else "string"

        desc_match = re.search(r'description\s*=\s*["\']([^"\']*)["\']', block)
        description = desc_match.group(1) if desc_match else ""

        required_match = re.search(r"required\s*=\s*(True|False)", block)
        required = True if required_match is None else (required_match.group(1) == "True")

        default_match = re.search(r"default\s*=\s*([^,\n\)]+)", block)
        default = self._parse_default_value(default_match.group(1) if default_match else None)

        return Parameter(
            name=name, type=param_type, required=required, description=description, default=default
        )

    def _parse_default_value(self, default_str: str | None) -> Any:
        """解析默认值"""
        if default_str is None:
            return None

        default_str = default_str.strip()

        if default_str in ["None", "null", ""]:
            return None
        if default_str == "True":
            return True
        if default_str == "False":
            return False

        # 字符串
        if (default_str.startswith('"') and default_str.endswith('"')) or (
            default_str.startswith("'") and default_str.endswith("'")
        ):
            return default_str[1:-1]

        # 数字
        try:
            if "." in default_str:
                return float(default_str)
            return int(default_str)
        except ValueError:
            pass

        return default_str


class ProgressiveDisclosureChecker:
    """渐进式披露架构检查器"""

    def __init__(self, base_path: str, skills: list[str]):
        self.base_path = Path(base_path)
        self.skills = skills
        self.results: list[CheckResult] = []

    def check(self) -> list[CheckResult]:
        """执行渐进式披露架构检查"""
        self._check_list_resources()
        self._check_read_resource()
        self._check_list_tools()
        self._check_call_tool()
        return self.results

    def _check_list_resources(self):
        """检查 list_resources 配置"""
        server_path = self.base_path / "backend/app/mcp_server/server.py"
        if not server_path.exists():
            self.results.append(CheckResult("❌", "server.py 不存在"))
            return

        content = server_path.read_text(encoding="utf-8")

        # 检查是否有 list_resources 方法
        if "list_resources" not in content:
            self.results.append(CheckResult("❌", "list_resources 未实现"))
            return

        # 检查是否有 skill:// URI 格式
        if "skill://" not in content:
            self.results.append(CheckResult("❌", "skill:// URI 格式未使用"))
            return

        # 检查是否加载了所有 7 个 skills
        skills_dir = self.base_path / "backend/claude_skills"
        found_skills = set()
        if skills_dir.exists():
            for skill_dir in skills_dir.iterdir():
                if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                    found_skills.add(skill_dir.name)

        expected_skills = set(self.skills)
        if found_skills == expected_skills:
            self.results.append(
                CheckResult("✅", f"list_resources: 返回 {len(found_skills)} 个 Skill")
            )
        else:
            missing = expected_skills - found_skills
            extra = found_skills - expected_skills
            details = []
            if missing:
                details.append(f"缺少 Skills: {missing}")
            if extra:
                details.append(f"额外 Skills: {extra}")
            self.results.append(CheckResult("⚠️", "list_resources: Skill 数量不匹配", details))

    def _check_read_resource(self):
        """检查 read_resource 配置"""
        server_path = self.base_path / "backend/app/mcp_server/server.py"
        content = server_path.read_text(encoding="utf-8")

        if "read_resource" not in content:
            self.results.append(CheckResult("❌", "read_resource 未实现"))
            return

        if "_mark_skill_discovered" not in content:
            self.results.append(CheckResult("⚠️", "read_resource: 未标记 discovered skills"))
            return

        # 检查是否能读取所有 SKILL.md
        skills_dir = self.base_path / "backend/claude_skills"
        missing_skills = []
        for skill_name in self.skills:
            skill_md = skills_dir / skill_name / "SKILL.md"
            if not skill_md.exists():
                missing_skills.append(skill_name)

        if missing_skills:
            self.results.append(CheckResult("❌", "read_resource: SKILL.md 缺失", missing_skills))
        else:
            self.results.append(CheckResult("✅", "read_resource: SKILL.md 完整"))

    def _check_list_tools(self):
        """检查 list_tools 配置"""
        server_path = self.base_path / "backend/app/mcp_server/server.py"
        content = server_path.read_text(encoding="utf-8")

        if "list_tools" not in content:
            self.results.append(CheckResult("❌", "list_tools 未实现"))
            return

        if "_get_discovered_skills" not in content:
            self.results.append(CheckResult("❌", "list_tools: 未使用 discovered_skills"))
            return

        # 检查工具名格式 skill_name.tool_name
        if 'f"{skill_name}.{tool_json' in content or 'skill_name + "." + tool' in content:
            self.results.append(CheckResult("✅", "list_tools: 动态返回正确"))
        else:
            self.results.append(CheckResult("⚠️", "list_tools: 工具名格式可能不正确"))

    def _check_call_tool(self):
        """检查 call_tool 配置"""
        server_path = self.base_path / "backend/app/mcp_server/server.py"
        content = server_path.read_text(encoding="utf-8")

        if "call_tool" not in content:
            self.results.append(CheckResult("❌", "call_tool 未实现"))
            return

        # 检查是否解析 skill_name.tool_name 格式
        if 'split(".", 1)' in content or "split('.', 1)" in content:
            self.results.append(CheckResult("✅", "call_tool: 执行逻辑正确"))
        else:
            self.results.append(CheckResult("⚠️", "call_tool: 工具名解析可能不正确"))


class SkillConsistencyChecker:
    """Skill 文档与代码一致性检查器"""

    def __init__(
        self,
        skill_name: str,
        doc_tools: dict[str, Tool],
        code_tools: dict[str, Tool],
        doc_metadata: SkillMetadata | None,
        code_tool_count: int,
    ):
        self.skill_name = skill_name
        self.doc_tools = doc_tools
        self.code_tools = code_tools
        self.doc_metadata = doc_metadata
        self.code_tool_count = code_tool_count
        self.results: list[CheckResult] = []

    def check(self) -> list[CheckResult]:
        """执行所有检查"""
        self._check_metadata()
        self._check_tool_names()
        self._check_parameters()
        return self.results

    def _check_metadata(self):
        """检查元数据一致性"""
        if not self.doc_metadata:
            self.results.append(CheckResult("⚠️", "元数据缺失: 无法解析 frontmatter"))
            return

        # 检查 tool_count
        if self.doc_metadata.tool_count != len(self.code_tools):
            self.results.append(
                CheckResult(
                    "⚠️",
                    f"工具数量不匹配: 文档声明 {self.doc_metadata.tool_count}, 代码实现 {len(self.code_tools)}",
                )
            )
        else:
            self.results.append(CheckResult("✅", f"工具数量一致: {len(self.code_tools)} 个"))

    def _check_tool_names(self):
        """检查工具名一致性"""
        doc_names = set(self.doc_tools.keys())
        code_names = set(self.code_tools.keys())

        matched = doc_names & code_names
        only_in_doc = doc_names - code_names
        only_in_code = code_names - doc_names

        total = len(doc_names | code_names)
        matched_count = len(matched)

        if not only_in_doc and not only_in_code:
            self.results.append(CheckResult("✅", f"工具名一致: {matched_count}/{matched_count}"))
        else:
            self.results.append(CheckResult("⚠️", f"工具名部分一致: {matched_count}/{total}"))

            for name in sorted(only_in_doc):
                self.results.append(CheckResult("❌", f"工具缺失: 文档中有 {name}, 代码中没有"))

            for name in sorted(only_in_code):
                self.results.append(CheckResult("❌", f"工具缺失: 代码中有 {name}, 文档中没有"))

    def _check_parameters(self):
        """检查参数一致性"""
        common_tools = set(self.doc_tools.keys()) & set(self.code_tools.keys())

        for tool_name in sorted(common_tools):
            doc_tool = self.doc_tools[tool_name]
            code_tool = self.code_tools[tool_name]

            doc_params = {p.name: p for p in doc_tool.parameters}
            code_params = {p.name: p for p in code_tool.parameters}

            doc_names = set(doc_params.keys())
            code_names = set(code_params.keys())

            only_in_doc = doc_names - code_names
            only_in_code = code_names - doc_names
            common_params = doc_names & code_names

            if not only_in_doc and not only_in_code:
                # 检查参数细节
                param_issues = []
                for param_name in sorted(common_params):
                    doc_param = doc_params[param_name]
                    code_param = code_params[param_name]

                    issues = self._check_param_details(doc_param, code_param, tool_name)
                    param_issues.extend(issues)

                if param_issues:
                    result = CheckResult(
                        status="⚠️", message=f"参数不一致: {tool_name}", details=param_issues
                    )
                else:
                    result = CheckResult(status="✅", message=f"参数一致: {tool_name}")
            else:
                issues = []
                for name in sorted(only_in_doc):
                    issues.append(f"  文档有但代码缺少参数: {name}")
                for name in sorted(only_in_code):
                    issues.append(f"  代码有但文档缺少参数: {name}")

                result = CheckResult(
                    status="❌", message=f"参数不一致: {tool_name}", details=issues
                )

            self.results.append(result)

    def _check_param_details(
        self, doc_param: Parameter, code_param: Parameter, tool_name: str
    ) -> list[str]:
        """检查单个参数的细节"""
        issues = []

        # 检查类型
        if doc_param.type != code_param.type:
            issues.append(
                f"  {doc_param.name}: 类型不一致 - 文档: {doc_param.type}, 代码: {code_param.type}"
            )

        # 检查 required
        if doc_param.required != code_param.required:
            doc_req = "必需" if doc_param.required else "可选"
            code_req = "必需" if code_param.required else "可选"
            issues.append(
                f"  {doc_param.name}: required 不一致 - 文档: {doc_req}, 代码: {code_req}"
            )

        # 检查默认值（处理引号和类型差异）
        doc_default = self._normalize_default(doc_param.default)
        code_default = self._normalize_default(code_param.default)

        if doc_default is not None and code_default is not None:
            if doc_default != code_default:
                issues.append(
                    f"  {doc_param.name}: 默认值不一致 - 文档: {doc_param.default}, 代码: {code_param.default}"
                )
        elif doc_default is not None and code_default is None:
            if not doc_param.required:
                issues.append(f"  {doc_param.name}: 文档有默认值 {doc_param.default}, 代码没有")
        elif doc_default is None and code_default is not None and not code_param.required:
            issues.append(f"  {doc_param.name}: 代码有默认值 {code_param.default}, 文档没有")

        return issues

    def _normalize_default(self, value: Any) -> Any:
        """规范化默认值以便比较（处理引号差异）"""
        if value is None:
            return None
        if isinstance(value, str):
            # 去除引号进行比较
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            # 空字符串视为 None（统一处理）
            if value == "":
                return None
            # 特殊值转换
            if value.lower() in ["null", "none", "nil", "(empty)", "empty"]:
                return None
            if value.lower() == "true":
                return True
            if value.lower() == "false":
                return False
            # 尝试转换为数字
            try:
                if "." in value:
                    return float(value)
                return int(value)
            except ValueError:
                pass
            return value
        return value


def check_skill(
    skill_name: str, base_path: str
) -> tuple[str, list[CheckResult], SkillMetadata | None]:
    """检查单个 skill"""
    doc_path = Path(base_path) / f"backend/claude_skills/{skill_name}/SKILL.md"

    # 处理文件名映射（skill_name 与文件名可能不同）
    code_filename = skill_name
    if skill_name == "deep_research":
        code_filename = "deep_research_split"  # 特殊映射

    code_path = Path(base_path) / f"backend/app/mcp_server/skills/{code_filename}.py"

    if not doc_path.exists():
        return skill_name, [CheckResult("❌", f"SKILL.md 不存在: {doc_path}")], None

    if not code_path.exists():
        return skill_name, [CheckResult("❌", f"代码文件不存在: {code_path}")], None

    # 解析文档
    doc_content = doc_path.read_text(encoding="utf-8")
    doc_parser = SkillDocParser(doc_content)
    doc_tools, doc_metadata = doc_parser.parse()

    # 解析代码
    code_content = code_path.read_text(encoding="utf-8")
    code_parser = CodeParser(code_content)
    code_tools = code_parser.parse()

    # 执行检查
    checker = SkillConsistencyChecker(
        skill_name, doc_tools, code_tools, doc_metadata, len(code_tools)
    )
    results = checker.check()

    return skill_name, results, doc_metadata


def print_report(
    skill_results: dict[str, list[CheckResult]],
    progressive_results: list[CheckResult],
    skill_metadata: dict[str, SkillMetadata | None],
    export_json: str | None = None,
) -> bool:
    """打印检查报告"""

    # 收集统计信息
    total_checks = 0
    passed_checks = 0
    warning_checks = 0
    failed_checks = 0

    for results in skill_results.values():
        for result in results:
            total_checks += 1
            if result.status == "✅":
                passed_checks += 1
            elif result.status == "⚠️":
                warning_checks += 1
            else:
                failed_checks += 1

    for result in progressive_results:
        total_checks += 1
        if result.status == "✅":
            passed_checks += 1
        elif result.status == "⚠️":
            warning_checks += 1
        else:
            failed_checks += 1

    all_passed = failed_checks == 0

    # 导出 JSON 报告
    if export_json:
        report = {
            "summary": {
                "total_checks": total_checks,
                "passed": passed_checks,
                "warnings": warning_checks,
                "failed": failed_checks,
                "all_passed": all_passed and warning_checks == 0,
            },
            "skills": {},
            "progressive_disclosure": [
                {"status": r.status, "message": r.message, "details": r.details}
                for r in progressive_results
            ],
        }

        for skill_name, results in skill_results.items():
            report["skills"][skill_name] = {
                "metadata": {
                    "name": skill_metadata[skill_name].name if skill_metadata[skill_name] else None,
                    "version": skill_metadata[skill_name].version
                    if skill_metadata[skill_name]
                    else None,
                    "tool_count": skill_metadata[skill_name].tool_count
                    if skill_metadata[skill_name]
                    else 0,
                }
                if skill_metadata[skill_name]
                else None,
                "checks": [
                    {"status": r.status, "message": r.message, "details": r.details}
                    for r in results
                ],
            }

        with open(export_json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"📄 JSON 报告已导出: {export_json}")
        print()

    print("=" * 70)
    print("Skill 一致性检查报告")
    print("=" * 70)
    print()

    # 1. Skill 详细检查
    for skill_name in sorted(skill_results.keys()):
        results = skill_results[skill_name]

        print(f"=== Skill: {skill_name} ===")

        # 显示元数据
        metadata = skill_metadata.get(skill_name)
        if metadata:
            print(f"   版本: {metadata.version} | 文档声明工具数: {metadata.tool_count}")

        if not results:
            print("  ⚠️  未找到工具定义")
        else:
            for result in results:
                print(f"{result.status} {result.message}")
                for detail in result.details:
                    print(f"   {detail}")

        print()

    # 2. 渐进式披露架构检查
    print("=== 渐进式披露架构检查 ===")

    for result in progressive_results:
        print(f"{result.status} {result.message}")
        for detail in result.details:
            print(f"   {detail}")

    print()
    print("=" * 70)

    # 统计
    print(f"总计: {total_checks} 项检查")
    print(f"  ✅ 通过: {passed_checks}")
    print(f"  ⚠️  警告: {warning_checks}")
    print(f"  ❌ 失败: {failed_checks}")
    print()

    if all_passed and warning_checks == 0:
        print("✅ 所有检查通过")
    elif all_passed:
        print("⚠️  存在警告，建议查看详情")
    else:
        print("❌ 发现不一致，需要修复")

    print("=" * 70)

    return all_passed and warning_checks == 0


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Skill 一致性检查脚本")
    parser.add_argument("--json", "-j", dest="json_output", help="导出 JSON 格式报告到指定文件")
    parser.add_argument("--skill", "-s", dest="skill", help="只检查指定的 skill")
    args = parser.parse_args()

    # 确定基础路径 - 脚本在项目根目录
    script_path = Path(__file__).resolve()
    base_path = script_path.parent

    # 7个核心 Skills（按文档顺序）
    all_skills = [
        "market_data",
        "financial_analysis",
        "sector_analysis",
        "risk_assessment",
        "data_analysis",
        "web_research",
        "deep_research",
    ]

    # 如果只检查指定 skill
    skills = [args.skill] if args.skill else all_skills
    invalid_skills = [s for s in skills if s not in all_skills]
    if invalid_skills:
        print(f"错误: 无效的 skill 名称: {invalid_skills}")
        print(f"有效的 skills: {all_skills}")
        sys.exit(1)

    print("=" * 70)
    print("Skill 一致性检查脚本")
    print(f"基础路径: {base_path}")
    print(f"检查 Skills: {', '.join(skills)}")
    if args.json_output:
        print(f"JSON 导出: {args.json_output}")
    print("=" * 70)
    print()

    # 1. 检查每个 Skill 的一致性
    skill_results = {}
    skill_metadata = {}

    for skill_name in skills:
        name, results, metadata = check_skill(skill_name, str(base_path))
        skill_results[name] = results
        skill_metadata[name] = metadata

    # 2. 检查渐进式披露架构（只在检查所有 skills 时执行）
    if not args.skill:
        progressive_checker = ProgressiveDisclosureChecker(str(base_path), all_skills)
        progressive_results = progressive_checker.check()
    else:
        progressive_results = []

    # 3. 打印报告
    all_passed = print_report(skill_results, progressive_results, skill_metadata, args.json_output)

    # 返回退出码
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
