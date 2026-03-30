# MCP 工具 Result Formatter 技术方案

## 1. 问题背景

### 1.1 什么是 Result Formatter

Result Formatter 是 AgentFlow 中用于**将工具返回的原始数据格式化成适合 Agent 消费的字符串**的组件。

**工作流程**:
```
工具执行结果 (JSON) → ResultFormatter.format() → 格式化字符串 (用于 Agent Prompt)
```

### 1.2 当前问题

执行 `skill` 等 MCP 工具时报错：
```
No formatter found for tool 'skill' (resource_type='None', tool_type='skill')
```

**原因**:
- `ResultFormatter.FORMATTER_MAP` 中没有注册 `skill` 和具体工具的 formatter
- 工具返回的 JSON 数据需要转换成人类可读的字符串供 LLM 理解

---

## 2. 技术方案

### 方案A: 为工具类型注册 Formatter（推荐）

**思路**: 为金融研投助手的工具类型分别实现 formatter

**实现位置**: `sandbox/result_formatter.py`

```python
# ============================================================================
# MCP Skill Tool Result Formatters
# ============================================================================

class SkillResult(ToolResult):
    """Round 1: skill 结果格式化"""

    def to_str(self, verbose: bool = False) -> str:
        if not self.success:
            return f"[Error] {self.metadata.get('message', 'Skill selection failed')}"

        skill_name = self.raw_data.get('skill_name', 'unknown')
        description = self.raw_data.get('description', '')
        use_when = self.raw_data.get('use_when', '')

        lines = [
            f"Selected Skill: {skill_name}",
            f"Description: {description}",
            f"Use When: {use_when}",
        ]
        return '\n'.join(lines)


class SkillToolResult(ToolResult):
    """Round 2: 具体工具调用结果格式化"""

    def to_str(self, verbose: bool = False) -> str:
        if not self.success:
            return f"[Error] {self.metadata.get('message', 'Tool execution failed')}"

        # 提取实际数据内容
        result_data = self.raw_data

        # 如果 data 字段存在，使用它
        if 'data' in result_data:
            result_data = result_data['data']

        # 格式化输出
        result_str = json.dumps(result_data, ensure_ascii=False, indent=2)

        if verbose:
            tool_name = self.metadata.get('tool', 'unknown')
            return f"[{tool_name}]\n{result_str}"
        else:
            # 截断长输出
            if len(result_str) > 2000:
                result_str = result_str[:2000] + "\n... (truncated)"
            return result_str


# 注册 formatters
ResultFormatter.register_formatter("skill", SkillResult)
ResultFormatter.register_formatter("market_data", SkillToolResult)
ResultFormatter.register_formatter("financial_analysis", SkillToolResult)
# ... 其他 skill 类型
```

### 方案B: 统一 MCP Skill Result Formatter

**思路**: 所有工具共用一个 formatter，根据 tool 名区分

```python
class MCPSkillResult(ToolResult):
    """MCP Skill 工具统一结果格式化"""

    def to_str(self, verbose: bool = False) -> str:
        tool_name = self.metadata.get('tool', '')

        if not self.success:
            return f"[Error] {self.metadata.get('message', 'Tool failed')}"

        # skill 类型工具
        if tool_name == 'skill':
            return self._format_skill()
        else:
            # 具体工具调用结果
            return self._format_tool_result()

    def _format_skill(self) -> str:
        skill_name = self.raw_data.get('skill_name', 'unknown')
        description = self.raw_data.get('description', '')
        return f"Selected Skill: {skill_name}\nDescription: {description}"

    def _format_tool_result(self) -> str:
        result_data = self.raw_data.get('data', self.raw_data)
        return json.dumps(result_data, ensure_ascii=False, indent=2)[:2000]


# 统一注册
ResultFormatter.register_formatter("skill", MCPSkillResult)
ResultFormatter.register_formatter("market_data", MCPSkillResult)
# ... 其他 skill 类型
```

---

## 3. 推荐方案: 方案A

### 理由
1. **职责清晰**: 每个 formatter 只处理一种工具，便于维护
2. **易于扩展**: 后续添加新工具只需新增 class
3. **可定制性强**: 每个工具可有自己的格式化逻辑

### 修改范围

**文件**: `sandbox/result_formatter.py`

**添加位置**: 在文件末尾（`UnifiedFinanceResult` 之后）

**内容**: 三个 formatter class + 三个 register_formatter 调用

---

## 4. 验证计划

### 4.1 单元测试
```python
# 测试 select_skill formatter
result = {
    "code": 0,
    "message": "success",
    "data": {
        "skill_name": "market_data",
        "description": "股票市场行情数据查询",
        "use_when": "股价、行情查询"
    },
    "meta": {"tool": "select_skill", "resource_type": None}
}
formatted = ResultFormatter.format_to_str(result)
assert "market_data" in formatted
assert "股票市场行情数据查询" in formatted
```

### 4.2 集成测试
1. 重启 Sandbox Server
2. 调用 `select_skill` 验证无 formatter 错误
3. 查看格式化输出是否符合预期

---

## 5. 时间估计

- 代码实现: 30分钟
- 测试验证: 20分钟
- 总计: 50分钟

---

## 6. 决策点

**请磊总确认**:
1. 采用方案A（独立 formatter）还是方案B（统一 formatter）？
2. 是否需要 V 来实现，还是我先实现？
3. 输出格式是否需要调整（如截断长度、字段选择等）？

---

**文档版本**: v1.0  
**编写日期**: 2026-03-21  
**编写人**: 卤蛋 🐤
