---
name: Agent 模拟交易 Plan 1 foundation ship 完
description: 严格交易类型、时钟、版本化规则与费率、五档行情、默认模拟账户及 PG 账本底座已落地；买卖工具和自选股写操作仍待后续计划
type: project
---

**结论**:Agent 模拟交易 Plan 1 底座已落地。系统现在有严格且冻结的交易领域类型、
上海交易时段时钟、带生效日与官方来源的 A 股交易规则/费率 fixture、Tushare 实时
五档行情适配，以及每用户一个默认模拟账户。账户默认初始资金为 100 万元，PG 中保存
generation 化账户、现金流水、持仓 lot 和重置审计；服务层支持经确认的幂等重置，API
已提供 `GET /api/v0/paper-trading/account` 和仅能在任何账户活动前执行一次的
`PATCH /api/v0/paper-trading/account/initial-cash`。

**Why**:后续 Agent 的“买入/卖出”不能直接改余额或把行情字段当成可信输入。这个阶段
先固定可复现的市场时钟、交易规则、费率与行情边界，再把资金变化做成有前后余额和唯一
业务键的追加式账本。每用户仅允许一个 active 账户，账户 generation、外键和约束隔离
重置前后历史；账户行锁、确认键/业务键锁、唯一约束和 SQLAlchemy version 列共同处理
并发创建、重复流水、并发修改和重置重放。外部行情缺失、停牌、过期、五档不完整或规则
不支持时统一 fail closed，并通过稳定 `PaperTradingError.code` 返回可判断的业务错误。

**How to apply**:

- 账户创建、现金变更和重置统一走 `PaperAccountService`；不要绕过账本直接更新余额，也不要
  复用旧 generation 的账户、流水或 lot。重试时复用原 business key；重置重试复用原
  `source_session_id + confirmation_id`。
- 委托准备必须复用 active account 行锁契约，并从 `TradingClock`、`RuleBook`、
  `FeeSchedule`、`TushareRealtimeQuoteProvider` 取得时段、手数/涨跌停、费用和五档行情；
  不要在 Agent prompt 或工具里复制另一套规则。
- 本阶段证据：隔离 PostgreSQL 15 上 Plan 1 的 210 个测试全部通过、无 xfail；既有成交/
  持仓/监控范围回归 16 个全部通过；Ruff format 检查 19 个文件、Ruff check 和 mypy
  10 个源文件均通过。输出仅有仓库既有的 SQLAlchemy/Pydantic/`utcnow()` 弃用警告。
- 边界必须保留：Plan 2 的委托撮合与买卖执行、Plan 3 的 Agent 买卖工具/确认/UI、Plan 4
  的自选股增删改与 `monitoring_enabled` 仍未实现；当前没有可调用的买入/卖出工具，也没有
  自选股写操作。
