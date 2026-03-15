# ✅ AgentFlow 金融研投助手 Backend - 完成总结

> 方案A实现完成：AgentFlow 适配金融研投助手工具调用方式
> 
> **新增：统一版 Backend，与金融研投助手 MCP Server 完全一致**
> 
> 创建时间：2026-03-15

---

## 📦 三个版本文件清单

### 版本1：基础版（8个工具）

| 文件 | 路径 | 用途 |
|------|------|------|
| **Backend 实现** | `sandbox/server/backends/resources/finance_research.py` | 复用 ToolExecutor，8个基础工具 |
| **Sandbox 配置** | `configs/sandbox-server/finance_research_config.json` | 基础版 Server 配置 |
| **合成配置** | `configs/synthesis/finance_research_config.json` | 基础版合成配置 |

### 版本2：MCP增强版（16个工具）

| 文件 | 路径 | 用途 |
|------|------|------|
| **Backend 实现** | `sandbox/server/backends/resources/mcp_enhanced_finance.py` | 整合 ToolExecutor + 3个 MCP Skill |
| **Sandbox 配置** | `configs/sandbox-server/mcp_enhanced_finance_config.json` | MCP增强版 Server 配置 |
| **合成配置** | `configs/synthesis/mcp_enhanced_finance_config.json` | MCP增强版合成配置 |

### 版本3：统一版（40个工具）⭐ 推荐

| 文件 | 路径 | 用途 |
|------|------|------|
| **Backend 实现** | `sandbox/server/backends/resources/unified_finance.py` | **统一接口，支持所有7个Skill** |
| **Sandbox 配置** | `configs/sandbox-server/unified_finance_config.json` | 统一版 Server 配置 |
| **合成配置** | `configs/synthesis/unified_finance_config.json` | 统一版合成配置 |
| **使用文档** | `docs/unified_finance_backend.md` | 统一版完整文档 |

### 共用文件

| 文件 | 路径 | 用途 |
|------|------|------|
| **种子数据** | `seeds/finance_research/seeds.jsonl` | 金融研究主题种子 |
| **测试脚本** | `test_finance_backend.py` | 快速验证脚本 |

---

## 🎯 统一版核心特性

### 调用方式（与金融研投助手 MCP Server 完全一致）

```python
# 统一接口
await backend.execute_skill_tool(
    skill_name='market_data',
    tool_name='get_quote',
    arguments={'symbol': '600519'}
)
```

### 支持的 7 个 Skill（共40个工具）

| Skill | 工具数 | 功能 |
|-------|--------|------|
| **market_data** | 11 | 市场行情数据 |
| **financial_analysis** | 7 | 财务分析 |
| **sector_analysis** | 7 | 行业分析 |
| **risk_assessment** | 3 | 风险评估 |
| **data_analysis** | 4 | 数据分析 |
| **web_research** | 5 | 网络研究 |
| **deep_research** | 7 | 深度研究 |

---

## 🚀 快速使用指南（统一版）

### 1. 环境准备

```bash
# 激活 deepresearch 环境
source ~/.bash_profile
conda activate deepresearch

# 设置 API Keys
export SEARCH_API_KEY="your_key"
export LLM_API_KEY="your_key"
export LLM_BASE_URL="https://api.openai.com/v1"

# Tushare Token（使用 market_data Skill 时需要）
export TUSHARE_API_TOKEN="your_token"
export TUSHARE_API_URL="http://lianghua.nanyangqiankun.top"
```

### 2. 启动 Sandbox（统一版）

```bash
cd ~/.openclaw/workspace-dev/external/AgentFlow

/opt/miniconda3/envs/deepresearch/bin/python -m sandbox.server \
  configs/sandbox-server/unified_finance_config.json
```

### 3. 运行数据合成（统一版）

```bash
# 另开终端
/opt/miniconda3/envs/deepresearch/bin/python -m synthesis.run \
  configs/synthesis/unified_finance_config.json
```

### 4. 查看结果

```bash
ls results/unified_finance/
# trajectories/  - 完整工具调用轨迹
# qa/            - QA 对数据
```

---

## 📊 三个版本对比

| 特性 | 基础版 | MCP增强版 | **统一版** |
|------|--------|-----------|-----------|
| **调用方式** | `action_tool_name()` | `action_skill_tool()` | **`execute_skill_tool()`** |
| **Skill数量** | 0 | 3 | **7** |
| **工具数量** | 8 | 16 | **40** |
| **与MCP Server一致性** | ❌ | ⚠️ 部分 | ✅ **完全一致** |
| **代码复杂度** | 低 | 中 | **低（统一接口）** |
| **适用场景** | 简单查询 | 专业数据查询 | **完整研究** |

**推荐：使用统一版进行 GRPO 训练数据生成**

---

## 🔧 统一版工具调用示例

### 市场行情数据

```python
# 获取实时行情
await backend.execute_skill_tool(
    skill_name='market_data',
    tool_name='get_quote',
    arguments={'symbol': '600519'}
)

# 获取历史K线
await backend.execute_skill_tool(
    skill_name='market_data',
    tool_name='get_history',
    arguments={'symbol': '600519', 'period': 'daily'}
)
```

### 财务分析

```python
# 获取财务报表
await backend.execute_skill_tool(
    skill_name='financial_analysis',
    tool_name='get_financial_report',
    arguments={'symbol': '600519', 'report_type': 'income'}
)

# 计算财务比率
await backend.execute_skill_tool(
    skill_name='financial_analysis',
    tool_name='calculate_financial_ratios',
    arguments={'symbol': '600519', 'ratios': ['roe', 'roa']}
)
```

### 深度研究（多步调用）

```python
# 1. 规划大纲
result = await backend.execute_skill_tool(
    skill_name='deep_research',
    tool_name='plan',
    arguments={'query': '茅台投资价值分析'}
)
session_id = result['result']['session_id']

# 2. 搜索信息
await backend.execute_skill_tool(
    skill_name='deep_research',
    tool_name='search',
    arguments={'session_id': session_id}
)

# 3. 分析数据
await backend.execute_skill_tool(
    skill_name='deep_research',
    tool_name='analyze',
    arguments={'session_id': session_id}
)

# 4. 撰写报告
await backend.execute_skill_tool(
    skill_name='deep_research',
    tool_name='write',
    arguments={'session_id': session_id}
)
```

---

## ✅ 验证清单

- [x] 基础版 Backend（8个工具）
- [x] MCP增强版 Backend（16个工具）
- [x] **统一版 Backend（40个工具）** ⭐
- [x] 统一接口 `execute_skill_tool()` 实现
- [x] 所有 7 个 Skill 集成完成
- [x] 配置文件创建
- [x] 使用文档编写
- [x] 与金融研投助手 MCP Server 接口对齐

---

## 🔧 自定义扩展

### 添加新的 Skill

1. 在金融研投助手项目中添加新的 Skill 类
2. 统一版 Backend 会自动加载（通过 `UnifiedSkillClient`）
3. 无需修改 AgentFlow 代码

### 添加新的工具

1. 在对应 Skill 的 `_register_tools()` 方法中添加
2. 统一版 Backend 会自动识别

---

## 📚 相关文档

- [统一版使用文档](./docs/unified_finance_backend.md)
- [基础版文档](./docs/finance_research_backend.md)
- [改造方案](./金融研投助手改造方案.md)
- [AgentFlow README](../README.md)

---

## 🤝 后续步骤

1. **测试统一版工具调用**：验证所有 40 个工具正常工作
2. **小规模合成测试**：用 2-3 个 seed 测试完整流程
3. **质量检查**：检查生成的 trajectory 是否符合预期
4. **批量合成**：调整参数后批量生成 GRPO 训练数据
5. **模型训练**：使用生成的数据进行 GRPO 训练

---

## 💡 关键要点

### 统一版优势
- 🎯 **与金融研投助手完全一致**的调用方式
- 🎯 **40个工具**覆盖完整金融研究场景
- 🎯 **统一接口**简化 AgentFlow 集成
- 🎯 **直接复用**金融研投助手的 Skill 实现
- 🎯 **训练数据**可直接用于生产环境

### 数据分布对齐
- ✅ 工具名与金融研投助手完全一致
- ✅ 参数格式完全一致
- ✅ 返回值结构完全一致
- ✅ Skill:Tool 命名规范统一

---

**🎉 统一版 Backend 完成！现在可以使用与金融研投助手完全一致的接口进行 GRPO 训练数据生成了！**
