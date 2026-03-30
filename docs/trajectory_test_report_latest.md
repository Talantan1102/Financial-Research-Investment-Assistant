# GRPO 轨迹生成测试报告 (2026-03-29)

## 测试配置

- **模型**: qwen-turbo
- **种子数量**: 3
- **最大深度**: 5
- **分支因子**: 2
- **最小深度要求**: 3

## 关键发现

### 🔴 严重问题: LLM 工具调用格式错误

LLM **完全误解了工具调用格式**，导致所有轨迹生成失败。

#### 错误示例

**期望的调用**:
```json
{
  "tool_name": "skill",
  "parameters": {"name": "deep_research"}
}
```

**实际的调用**:
```json
{
  "tool_name": "deep_research",
  "parameters": {"name": "deep_research"}
}
```

#### 日志中的错误

```
[#=2 Id=node_41b1576c Depth=1 deep_research]:
选择Skill: deep_research
[params]: {"name": "deep_research"}
[output]: ❌ ERROR: Tool 'deep_research' is not available.
```

### 🔧 服务器工具列表

服务器返回了 **47 个工具**，包括：
- ✅ 正确的工具: `skill`, `market_data.get_quote`, `financial_analysis.calculate_financial_ratios` 等
- ❌ 不应暴露的工具: `select_skill`, `get_skill_tools`, `execute_skill_tool`

完整列表:
```
['skill', 'select_skill', 'get_skill_tools', 'execute_skill_tool',
 'market_data.get_quote', 'market_data.search_stock', ...,
 'deep_research.generate_stock_report', ...]
```

### 📉 轨迹生成结果

| 种子 | 生成状态 | 原因 |
|------|---------|------|
| 分析贵州茅台(600519)的投资价值 | ❌ 失败 | 工具调用格式错误 |
| 宁德时代(300750)的财务状况如何？ | ❌ 失败 | 工具调用格式错误 |
| 比较白酒行业龙头股的估值水平... | ❌ 失败 | 工具调用格式错误 |

**所有 3 个种子均失败**，没有生成任何有效轨迹。

## 问题根因分析

### 1. LLM 混淆工具名称

LLM 似乎将 **skill 名称** 与 **工具名称** 混淆了：
- 它试图直接调用 `deep_research`（skill 名称）作为工具
- 而不是调用 `skill` 工具，参数为 `{"name": "deep_research"}`

### 2. Prompt 或工具定义不清晰

可能的原因:
- `sampling_tips` 中的示例不够清晰
- 工具 schemas 中的 `skill` 工具定义可能让 LLM 困惑
- LLM 没有理解 "skill" 是一个工具，而不是一个类别

### 3. 旧格式残留

日志中可以看到 `select_skill` 工具仍然存在，可能导致 LLM 混淆新旧格式。

## 对比分析

### 之前的轨迹 (grpo_sample_test)

在之前的轨迹文件中，LLM 使用的是 **错误但有效的调用**：
```
- unified_finance:skill (✅ 正确)
- unified_finance:get_skill_tools (❌ 不应直接调用)
- unified_finance:execute_skill_tool (❌ 不应直接调用)
```

### 当前测试

当前测试中 LLM 使用的是 **完全错误的调用**：
```
- deep_research (❌ 工具不存在)
- financial_analysis (❌ 工具不存在)
- sector_analysis (❌ 工具不存在)
```

## 建议修复措施

### 1. 立即修复 (高优先级)

**修改工具定义**，让 LLM 更清楚如何调用:

```python
# 当前定义可能过于复杂，需要简化
{
  "name": "skill",
  "description": "【第一步】选择要使用的 Skill。调用方式: skill(name='market_data')",
  "parameters": {
    "name": {
      "type": "string",
      "enum": ["market_data", "financial_analysis", "sector_analysis", ...],
      "description": "Skill 名称"
    }
  }
}
```

### 2. 简化工具命名 (中优先级)

考虑将工具命名从 `market_data.get_quote` 改为更清晰的格式:
- `market_data:get_quote`
- 或保持当前格式，但加强示例

### 3. 移除旧工具 (高优先级)

从服务器工具列表中移除:
- `select_skill` (旧格式)
- `get_skill_tools` (不应暴露)
- `execute_skill_tool` (不应暴露)

### 4. 增强错误提示 (中优先级)

当 LLM 调用不存在的工具时，返回更清晰的错误提示:
```
❌ Tool 'deep_research' not found.
   Did you mean: skill(name="deep_research")?
   Available skills: market_data, financial_analysis, sector_analysis, ...
```

## 结论

**当前系统无法生成有效的 GRPO 训练数据。**

主要问题:
1. LLM 完全误解了工具调用格式
2. 后端暴露了不应暴露的内部工具
3. 新旧格式混用导致混淆

**建议**: 在修复工具定义和 Prompt 后重新测试。
