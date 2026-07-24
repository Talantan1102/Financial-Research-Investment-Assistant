---
name: Paper trading runtime adaptation completion
description: 自选股直接写与模拟交易审批写已接入 Run 控制面，并记录跨平台和端到端验收边界。
type: project
---

# 模拟交易运行时适配完成卡

## 结论

自选股和模拟交易已从只读 Agent 扩展为可审计的环境写入能力：

- 自选股新增、修改、删除由 `manage_watchlist` 直接执行，`monitoring_enabled` 默认关闭。
- 模拟账户读取直接执行；下单、撤单和重置账户必须先进入 Run 审批暂停。
- 审批卡允许用户编辑参数并预览；恢复执行时后端重新校验最终参数，审计同时保留原始提案和最终生效参数。
- 每个用户只有一个默认模拟账户；订单、成交、资金流水和持仓沿用领域服务写入，`Trade` 仍是持仓事实来源。
- 旧 Chat Router、`chat_runner`、`chat_session_repo` 和 `useChatSSE` 没有被迁回，新增能力适配现有 Run 控制面。

## Why

产品不连接真实券商账户，但交互应接近真实交易产品：用户说“买入某股票”时，Agent 应调用交易工具，而不是要求用户事后手工登记成交。模拟交易仍会改变资金和持仓，因此必须由用户确认；自选股操作风险较低且可撤销，直接执行更自然。

Run 审批绑定 Run、执行、工具调用和最终参数，能防止旧审批或被篡改参数绕过确认。确认后的订单进入既有模拟撮合、结算、T+1、撤单、过期和对账链路，不由 Agent 直接改写持仓。

## How to apply

运行时约束：

- `manage_watchlist` 是低风险直接写工具。
- `place_paper_order`、`cancel_paper_order`、`reset_paper_account` 是高风险审批工具。
- 审批恢复必须使用卡片最终编辑后的参数，并再次经过 schema、权限和领域规则校验。
- Windows 不支持 POSIX `resource`/`fork`/`killpg`；SkillExecutor 在 Windows 先启动只等待 gate 的可信 bootstrap，再创建并绑定带 `PROCESS_MEMORY` 与 `KILL_ON_JOB_CLOSE` 的 Job Object，绑定成功后才允许用户代码运行。Job 建立失败会 fail closed；POSIX rlimit/killpg 行为保持不变。

2026-07-24 本地验收：

```powershell
uv run pytest backend/tests/unit/chatloop backend/tests/unit/services backend/tests/integration/paper_trading backend/tests/integration/watchlist backend/tests/unit/tasks/test_paper_trading_tasks.py -q
# 1358 passed, exit 0, 876.7s

$env:REDIS_URL='redis://127.0.0.1:6379/15'
uv run pytest backend/tests/e2e/test_paper_order_worker.py -q
# 14 passed, exit 0；运行前后清空隔离 Redis DB 15

uv run ruff check backend/app backend/tests
# exit 0
uv run mypy backend/app
# 437 source files, exit 0
uv run python -m compileall -q backend/app
# exit 0

cd frontend
npm ci
# 837 packages, exit 0
npx vitest run
# 73 files, 347 tests passed
npx tsc -p tsconfig.json --noEmit
# exit 0
npm run build
# 4085 modules transformed, exit 0
npx playwright test --project=chromium tests/e2e/paper-trading.spec.ts tests/e2e/watchlist.spec.ts
# 3 passed

cd ..
uv run pytest backend/tests/unit/skills backend/tests/integration/test_skill_sandbox_escape_attempts.py backend/tests/unit/chatloop/test_code_interpreter_tool.py backend/tests/unit/chatloop/test_code_interpreter_data_refs.py backend/tests/unit/chatloop/test_worker_wiring_run_python.py --ignore=backend/tests/unit/skills/test_skill_loader_l1.py --ignore=backend/tests/unit/skills/test_skill_loader_l3a.py --ignore=backend/tests/unit/skills/test_skill_loader_l3b.py -q
# 106 passed, 2 skipped, exit 0
```

Playwright 使用真实 Chromium 和真实 React 页面交互，API 边界按仓库现有 E2E 约定由 `page.route` 提供确定性状态机；preview 必须收到用户编辑后的完整 draft，批准恢复必须与同一调用已成功 preview 的 canonical 参数完全一致，未知 `/api/` 请求会返回 500 并使测试末尾断言失败。7 个只读 handler 还同时约束 GET，负向测试逐一验证 POST/DELETE 不会误命中成功响应。链路验证 Run 等待审批、编辑预览、批准恢复、会话重载、账户页订单/资金终态，以及自选股无确认增改删。真实 PostgreSQL 领域终态和真实 Celery/Redis Worker 由上述后端集成与 Worker E2E 覆盖。

Windows Job Object focused 测试还实际验证了：小程序在限制内成功、512MB 分配在 256MB 限制下稳定返回 `memory_limit`、Job setup mock 失败时用户 marker 不生成、Job handle 关闭，以及 timeout 后子进程树没有遗留 marker。

未声称运行远端 CI。完整 `backend/tests/unit/skills` 扩大组合曾运行 140 条，其中 127 passed、2 skipped、11 failed；11 条失败均来自三个 SkillLoader 文件在 Windows 用默认 CP936 写 fixture、生产按 UTF-8 读，以及 CRLF 磁盘大小与解码后内容大小不一致。它们不属于此前 1358 条 paper-trading 定向套件，也未计入上述 106 passed。前端构建仍有既有 `%VITE_TITLE%`、ECharts 分包和大 chunk 警告；后端仍有既有 SQLAlchemy、Pydantic 和 `datetime.utcnow()` 弃用警告。

设计与实施锚点：

- `docs/superpowers/specs/2026-07-23-paper-trading-runtime-adaptation-design.md`
- `docs/superpowers/plans/2026-07-23-paper-trading-runtime-adaptation.md`
