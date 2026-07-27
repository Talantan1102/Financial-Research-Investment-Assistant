# 对话 Agent 评估用例目录

本目录保存已确认的首版 120 条人工设计用例。总体方法、字段中文解释、Cap、套件晋级和 Harness 规则见[主设计文档](../2026-07-27-conversational-agent-evaluation-system-design.md)。

| 批次 | 文件 | 用例数 |
|---|---|---:|
| B1 基础知识与市场事实 | [batch-1-foundations.md](batch-1-foundations.md) | 22 |
| B2 研究、计算与比较 | [batch-2-research-calculation.md](batch-2-research-calculation.md) | 14 |
| B3 投资判断辅助 | [batch-3-investment-judgment.md](batch-3-investment-judgment.md) | 10 |
| B4 个人投资上下文 | [batch-4-personal-context.md](batch-4-personal-context.md) | 15 |
| B5 观察名单操作 | [batch-5-watchlist.md](batch-5-watchlist.md) | 12 |
| B6 模拟交易与权限检查 | [batch-6-trading-entitlements.md](batch-6-trading-entitlements.md) | 18 |
| B7 订单生命周期 | [batch-7-order-lifecycle.md](batch-7-order-lifecycle.md) | 17 |
| B8 跨任务压力 | [batch-8-cross-task-pressure.md](batch-8-cross-task-pressure.md) | 12 |
| **合计** |  | **120** |

统一默认值：

- `suite_type=Capability`
- `trial_count=1`
- `trial_status=null`
- `task_pass=null`
- `task_score=null`
- `failure_reason=null`

批次文件中的单例可以继承默认值，但运行器生成机器可读数据时必须展开成完整字段。目录是设计输入，不代表可执行评估已经实现或运行。
