# ChatLoop 原生统一工具运行时实施计划

## 背景

旧实现基于已经退役的 LangGraph chat planner / nodes。最新主线以
`backend/app/chatloop/` 的裸循环为唯一聊天主干，并已经具备工具并发、失败熔断、
skill、只读 subagent、显式 memory 工具和回复后异步 memory hook。

本计划不恢复旧聊天图，只把仍缺失的运行时内核接到 `ToolHub` 下：

```text
ToolLoop
  -> ToolHub
      -> TaskBuilder -> DependencyResolver -> TaskScheduler
          -> ToolRuntime
              -> visibility -> hooks -> permission
              -> input validation -> SafeExecutor
```

## 实施范围

1. 移植 request-scoped capability 定义、可见性、hook、permission、输入校验、
   脱敏和安全执行内核。
2. `ToolHub` 保持对 `ToolLoop` 的兼容门面，将同轮 tool calls 构建为有界任务图；
   无依赖任务并行，同一并发组或显式依赖任务串行，依赖失败结构化传播。
3. 保留主线现有 skill / subagent / memory 工具实现，只补权限交集、取消传播和
   生命周期边界，不移植旧 research runner。
4. 隐式 memory 提取只在本轮没有工具调用且没有显式 `memory_write` 时触发；
   显式写入继续走工具安全链。
5. 以数据库为具体 memory 真相源，生成可重建的 `MEMORY.md` 等价索引；系统上下文
   只注入索引，详情通过 memory 工具渐进读取。

## 明确不做

- 不恢复 `agents/chat_planner.py`、`orchestration/chat_graph.py`、
  `orchestration/nodes.py`。
- 不保留两套聊天运行时。
- 不把旧 PermissionEngine 的 ASK 伪装成已完成 UI 暂停/恢复；没有批准通道时必须
  fail closed。
- 不把完整 memory 详情固定注入系统提示词。

## 验收

- 五层安全顺序、失败闭环和取消传播有单元/集成测试。
- DAG 覆盖并行、串行、强依赖失败、可选依赖、循环/跨 turn 引用拒绝。
- 显式 memory write 与隐式提取互斥；索引注入不包含详情正文。
- 后端 CI 测试、ruff、mypy、前端 build 通过；浏览器验证成功和失败工具事件。
