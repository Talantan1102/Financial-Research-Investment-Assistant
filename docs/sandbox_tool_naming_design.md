# AgentFlow Sandbox 工具命名对齐设计文档

## 1. 问题背景

### 1.1 现状
- **AgentFlow 期望的工具名**: `skill`, `market_data.get_quote` 等
- **Sandbox 实际注册的工具名**: `finance_research:skill`, `market_data.get_quote`

### 1.2 对齐目标
统一使用**金融研投助手的命名规范**（系统编排两轮架构）：
- **对 LLM 暴露**:
  - `skill(name)` — 选择 Skill
  - `market_data.get_quote`, `market_data.search_stock` 等 — 直接调用具体工具
- **系统内部调用**（不对 LLM 暴露）:
  - `get_skill_tools` — 获取 Skill 的工具列表
  - `execute_skill_tool` — 执行具体工具

### 1.3 架构说明
```
┌─────────────────────────────────────────────────────────────┐
│  LLM 可见层 (2轮)                                            │
│  ─────────────────                                           │
│  Round 1: skill(name='market_data')                          │
│  Round 2: market_data.get_quote(ts_code='600519.SH')         │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
┌────────────────────┐      ┌──────────────────────────────┐
│ 系统自动调用:       │      │ 系统自动转换:                 │
│ get_skill_tools()  │      │ execute_skill_tool()         │
└────────────────────┘      └──────────────────────────────┘
```

---

## 2. 设计方案

### 方案: 修改 Sandbox 工具注册逻辑

**思路**: 让 Sandbox 正确注册金融研投助手模式的工具

**修改点**:
1. `sandbox/server/app.py`:
   - 修改 `load_mcp_backend()` 方法，注册 `skill` 工具
   - 添加具体工具（如 `market_data.get_quote`）的路由

2. `sandbox/server/backends/mcp_native_base.py`:
   - 系统内部调用 `get_skill_tools` 和 `execute_skill_tool`
   - 对外暴露 `skill` 和具体工具名

**工具注册**:
| 工具名 | 可见性 | 说明 |
|--------|--------|------|
| `skill` | LLM 可见 | 选择 Skill |
| `market_data.get_quote` | LLM 可见 | 获取实时行情 |
| `market_data.search_stock` | LLM 可见 | 搜索股票 |
| ... | ... | 其他具体工具 |
| `get_skill_tools` | 系统内部 | 获取工具列表 |
| `execute_skill_tool` | 系统内部 | 执行工具 |
