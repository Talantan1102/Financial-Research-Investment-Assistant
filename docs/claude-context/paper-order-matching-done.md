---
name: Agent 模拟交易 Plan 2 委托撮合 ship 完
description: 可确认委托、资金与持仓预占、五档撮合、原子结算、幂等重投、对账与可观测性已落地；Agent 买卖工具、确认卡 UI 和自选股写操作仍待后续计划
type: project
---

**结论**：Agent 模拟交易 Plan 2 的委托撮合后端已落地。系统现在支持准备、确认、撤单和关闭委托，按可见五档深度部分成交，并在同一事务中完成费用、T+1、现金、持仓 lot、`Fill → Trade → Position` 更新。撮合任务支持 Celery 延迟确认与重投幂等；重置或关户会收回未完成委托的预占；对账发现不变量破坏时暂停账户，不自动篡改账本。

**Why**：用户说“给我买入/卖出”后，Agent 不能直接改余额或持仓，也不能把重复投递变成重复成交。委托、预占、成交和结算被拆成可审计的状态机，最终事实仍写入 `Trade`，`Position` 只是由成交结算维护的快照。这样后续确认卡即使被用户编辑，后端仍能重新校验数量、价格、交易时段、费用和可用资产，并能在 worker 崩溃或消息重投后恢复到一致终态。

**How to apply**：

- 买卖执行统一走 `prepare → confirm → Celery match → settlement`，不要绕过委托服务直接更新账户、`Trade` 或 `Position`。重试必须复用原确认键和撮合键；相同市场快照重放只能返回已有成交。
- 查询和终态操作必须同时按当前用户、active account 与 generation 隔离。撤单、过期、重置和关户先释放预占，再进入终态；对账异常保留原始事实并暂停账户，交给显式恢复流程处理。
- 本阶段验证证据：paper trading 精确矩阵 625 个测试全部通过，无 xfail；既有成交、持仓和真 Celery 监控回归 22 个全部通过；Ruff format、Ruff check、mypy 1042 个源文件均通过。测试数据库使用独立 PostgreSQL，真 worker 使用独立 Redis DB。
- 边界必须保留：Plan 3 的 Agent 买入/卖出工具、可编辑确认卡与前端 UI 尚未实现；Plan 4 的自选股新增、修改、删除和每只股票默认关闭的 `monitoring_enabled` 尚未实现。
