# Tool Schema 优化完成总结

## 优化时间
2026-03-29

## 问题背景
在 GRPO 轨迹生成测试中发现 LLM 误解了工具调用格式：
- **期望调用**: `skill(name="deep_research")`
- **实际调用**: `deep_research(name="deep_research")` (工具不存在错误)

根本原因是服务器暴露了内部工具给 LLM，导致 LLM 混淆。

## 核心问题

### 1. 服务器暴露内部工具 (严重)
**位置**: `sandbox/server/app.py`

**问题**: `list_tools()` 返回了所有工具，包括系统内部工具：
- `get_skill_tools` — 应该由编排层自动调用
- `execute_skill_tool` — 应该由编排层自动调用
- `select_skill` — 向后兼容的别名，不应暴露

**影响**: LLM 看到这些工具后直接调用，破坏了系统编排架构。

### 2. Prompt 提示不够清晰 (中等)
**位置**: `synthesis/core/sampler.py`

**问题**: Round 1 和 Round 2 的提示没有明确指出：
- 哪些工具是 LLM 可以调用的
- 哪些工具是系统内部工具（不应直接调用）
- 正确的工具调用格式示例

### 3. 文档不够清晰 (轻微)
**位置**: `sandbox/tool_schemas/__init__.py`

**问题**: 模块注释和函数文档没有清晰说明系统编排架构。

## 优化内容

### 1. 隐藏系统内部工具
**文件**: `sandbox/server/app.py`

**修改**: `list_tools()` 方法现在过滤内部工具
```python
# 系统内部工具，不应暴露给 LLM
INTERNAL_TOOLS = {"get_skill_tools", "execute_skill_tool", "select_skill"}

for full_name, func in self._tools.items():
    # 过滤系统内部工具
    tool_base_name = full_name.split(":")[-1]
    if tool_base_name in INTERNAL_TOOLS:
        continue
```

**效果**: LLM 只能看到 `skill` 和 `skill_name.tool_name` 格式的工具。

### 2. 强化 Round 1 提示
**文件**: `synthesis/core/sampler.py`

**修改**: `_build_round1_prompt()` 添加了明确的调用格式示例
```python
⚠️  CRITICAL: 你必须使用 skill(name) 函数选择Skill。

正确示例:
  skill(name="market_data")

❌ 错误示例:
  - 直接写 "market_data"
  - 调用 "get_skill_tools"
  - 调用其他函数名称
```

### 3. 强化 Round 2 提示
**文件**: `synthesis/core/sampler.py`

**修改**: `_build_round2_prompt()` 添加了明确的调用格式示例
```python
⚠️  CRITICAL: 工具调用格式
正确格式: 直接调用 {skill_name}.<tool_name>
  示例: {skill_name}.get_quote({{"ts_code": "600519.SH"}})

❌ 错误示例:
  - 只写 "get_quote" (缺少 skill 前缀)
  - 调用 "get_skill_tools" (这是系统内部工具)
  - 调用 "execute_skill_tool" (这是系统内部工具)
```

### 4. 优化 tool_schemas 文档
**文件**: `sandbox/tool_schemas/__init__.py`

**修改**:
1. 模块注释更清晰，明确系统编排流程
2. `get_tool_schemas()` 函数文档详细说明调用流程
3. `skill` 工具描述更详细，强调这是 Round 1 的入口

## 系统编排架构 (优化后)

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM (可见工具)                            │
├─────────────────────────────────────────────────────────────┤
│  Round 1: skill(name)                                      │
│  Round 2: skill_name.tool_name                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  编排层 (自动处理)                           │
├─────────────────────────────────────────────────────────────┤
│  1. LLM 调用 skill(name="market_data")                     │
│     └── 编排层自动调用 get_skill_tools(name="market_data") │
│                                                            │
│  2. LLM 调用 market_data.get_quote({"ts_code": "..."})      │
│     └── 编排层自动调用 execute_skill_tool(                 │
│           skill_name="market_data",                        │
│           tool_name="get_quote",                           │
│           arguments={...}                                  │
│         )                                                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                 金融研投助手 MCP Server                      │
├─────────────────────────────────────────────────────────────┤
│  实际执行工具并返回结果                                       │
└─────────────────────────────────────────────────────────────┘
```

## 验证结果

运行验证脚本 `scripts/verify_tool_schema_optimization.py`：

```
================================================================================
验证 Tool Schemas
================================================================================

总工具数量: 44
✅ Round 1 工具 'skill' 存在
✅ 内部工具已正确隐藏

Round 2 工具数量: 43
✅ 所有 7 个 skills 都有工具

工具示例:
  - market_data.get_quote
  - market_data.search_stock
  - market_data.get_history
  - market_data.get_stock_basic_info
  - market_data.get_top_list
  ... 还有 38 个工具

================================================================================
验证服务器工具列表 (需要服务器运行)
================================================================================

服务器返回工具数量: 44
✅ 服务器正确隐藏了内部工具
✅ 服务器包含 'skill' 工具
✅ 服务器包含 43 个 Round 2 工具

================================================================================
✅ 所有验证通过!
================================================================================
```

## 修改的文件

1. `sandbox/server/app.py` - 隐藏内部工具
2. `synthesis/core/sampler.py` - 强化 Prompt 提示
3. `sandbox/tool_schemas/__init__.py` - 优化文档

## 新增的文件

1. `scripts/verify_tool_schema_optimization.py` - 验证脚本
2. `docs/tool_schema_optimization.md` - 优化文档

## 后续建议

1. **运行轨迹生成测试**
   ```bash
   conda activate deepresearch
   python scripts/pipeline/test_random_seeds.py --count 5
   ```

2. **监控轨迹生成质量**
   - 检查 LLM 是否正确使用 `skill()` 调用
   - 检查 LLM 是否直接使用 `skill_name.tool_name` 格式
   - 检查是否还有 LLM 直接调用内部工具的情况

3. **进一步优化（可选）**
   - 考虑在 sampler 中添加工具调用格式校验
   - 当检测到错误格式时，返回更清晰的错误提示
