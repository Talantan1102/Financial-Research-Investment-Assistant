# Run Control Plane Phase 3 Chat Integration 完成卡

## 结论

Phase 3 已在本地完成 Run Chat 主链路接线和验收：HTTP `POST Run` 进入 PostgreSQL，经过 Scheduler、Dispatcher、Redis Stream 和 capacity=1 Worker，最终持久化 completed Run、assistant final message、Attempt、usage 与 trace；SSE 终态快照能返回最终正文。React 主执行路径已切到 v1 Run API。

## Why

Phase 2 只证明控制面的排队、租约与故障恢复。Phase 3 补齐真实 Chat 语义和浏览器入口，重点不是再造一个执行器，而是保证临时 token 可丢、最终事实不可丢，并让 UI 只依赖 Run/Session 资源边界。

Task 7 的验收由三层组成：

- PG + 真 Redis 集成测试同时创建两个 Session/Run，经真实 `RunScheduler`、`RunDispatcher` 与两个 `RunWorker(capacity=1)` 完成，并断言两个不同 Worker ID。
- cassette 离线回放已提交的真实 DashScope `deepseek-v4-flash` 工具调用，验证生产 ChatLoop 的模型边界和非空回答。
- Compose L2.5 运行真实独立 Scheduler/Dispatcher/Worker/API/PG/Redis 进程，并完成 crash、Redis/PostgreSQL restart、cancel、capacity 与 lease recovery 场景。

## How to apply

本地确定性验证（2026-07-20）：

```powershell
$env:REDIS_URL='redis://127.0.0.1:6379/15'
uv run pytest backend/tests/unit/models/test_run_execution_models.py backend/tests/unit/chatloop/test_run_executor.py backend/tests/integration/chatloop/test_run_executor_tools.py backend/tests/unit/services/test_run_chat_worker.py backend/tests/unit/services/test_run_stream_bus.py backend/tests/integration/test_run_events_live_sse.py backend/tests/integration/test_run_chat_full_path.py backend/tests/e2e/test_run_chat_cassette.py -q
# 190 passed

uv run pytest backend/tests/integration/test_run_chat_worker_pg.py -q
# 24 passed

uv run pytest backend/tests/integration/test_run_sessions_v1_router.py -q
# 13 passed

$env:RUN_CONTROL_COMPOSE_SELF_BOOTSTRAP='1'
$env:RUN_CONTROL_ACCEPTANCE_IMAGE='financial-research-run-control:review4'
uv run pytest backend/tests/integration/test_run_control_multi_process.py::test_compose_l25_self_bootstraps_all_failure_scenarios -v -s
# 1 passed in 143.13s; harness also verified bounded cleanup
```

Phase 3 前端门禁：

```powershell
cd frontend
npm test -- --run src/api/__tests__/runApi.test.ts src/hooks/__tests__/useRunSSE.test.tsx src/components/chat/__tests__/ChatPane.test.tsx
# 26 passed

npm test -- --run src/pages/chat/__tests__/session.test.tsx src/pages/chat/__tests__/session.route-integration.test.tsx
# 4 passed

npm run build
# 4214 modules transformed, exit 0

npx eslint src/api/runApi.ts src/hooks/useRunSSE.ts src/components/chat/ChatPane.tsx src/store/current-chat.ts src/store/chat-sessions.ts src/pages/chat/session.tsx src/api/__tests__/runApi.test.ts src/hooks/__tests__/useRunSSE.test.tsx src/components/chat/__tests__/ChatPane.test.tsx src/pages/chat/__tests__/session.test.tsx src/pages/chat/__tests__/session.route-integration.test.tsx
# exit 0
```

全量前端基线仍不是全绿：`npm test -- --run` 为 309 passed / 4 failed，失败位于既有 markdown、CostMeter、MemoryOnboardingModal、EscalationConfirmDialog 测试；另有 3 个既有 memory UI unhandled rejection。`npm run lint` 为 32 errors / 6 warnings，Phase 3 涉及文件的定向 ESLint 为 0。十个 Phase 3 后端模块单进程合跑会触发既有 async PG fixture 的跨模块数据污染/死锁；将两个 PG-heavy 模块独立运行时分别 24/24 和 13/13 通过。

活体脚本：

```powershell
$env:RUN_CHAT_BASE_URL='http://127.0.0.1:18080'
$env:RUN_CHAT_TENANT_ID='<tenant uuid>'
$env:RUN_CHAT_AUTH_TOKEN='<bearer token>'
$env:RUN_CHAT_MODEL_ROUTE='<provider/model>'
uv run python backend/scripts/smoke_run_chat.py
```

脚本有总超时，只输出 Run ID、Session ID、status、耗时和 model route；不会输出 API key、Bearer token、完整 prompt、最终回答或 trace payload。本次环境没有 Tenant/Auth/模型凭据，因此没有伪造 live smoke 结果；使用的是上述 cassette 离线回放证据。
