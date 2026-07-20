# Run Control Plane Phase 4 Observability 口径

## 结论

`runs.waiting` 是当前状态快照：按 `Run.status IN (waiting_approval, waiting_input)` 直接计数，并以 `Run.created_at <= as_of` 排除快照时点之后才创建的 Run。它不要求 `run.paused` 事件落在查询窗口内，因此长期等待的 Run 不会因为窗口滚动而消失；同一个 Run 多次 pause/resume 也只计一次。

## Why

指标接口同时提供两类口径。等待中的数量回答“此刻还有多少 Run 需要人工动作”，属于 current-state projection；`queue.no_slot` 等 scheduler 阻塞原因回答“窗口内发生过多少次阻塞”，属于 historical fact window。两者不能用同一条事件窗口条件，否则长期 waiting 会被错误计为零。

## How to apply

- `as_of` 用于重放或校验快照；未来创建的 Run 不纳入 current-state projection。
- `window` 只约束 latency、no-slot、usage、duration 等历史事实，以及单独计算的 waiting 时长。
- 查询保持 tenant scope、只读事务，不 join pause 事件来推导当前 waiting 数量。
