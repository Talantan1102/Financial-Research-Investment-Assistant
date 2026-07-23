# Paper Trading Runtime Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在最新主线上恢复模拟交易和自选股能力，并让所有 Agent 写操作使用统一安全工具运行时、RunPause、持久化执行账本和 Run SSE。

**Architecture:** 领域代码从 `codex/agent-paper-trading-spec@60b0e0f2` 选择性迁移；旧 Chat Router、`chat_runner` 和 `useChatSSE` 不迁移。自选股使用低风险幂等直接写工具；模拟交易按静态风险拆成读工具和高风险写工具，高风险调用先由 Run 控制面暂停，用户可编辑参数后续跑同一调用。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy/PostgreSQL、Celery/Redis、React、TypeScript、Valtio、Vitest、Playwright。

---

## 文件结构

### 直接迁移并适配主线的领域文件

- `backend/app/models/paper_account.py`：模拟账户、资金流水、持股批次和重置审计。
- `backend/app/models/paper_order.py`：订单、成交和撮合水位。
- `backend/app/models/watchlist.py`：自选股与 append-only 审计。
- `backend/app/services/paper_trading/`：时钟、行情、规则、费用、账户、订单、撮合、结算和对账。
- `backend/app/services/watchlist_service.py`：自选股幂等 CRUD。
- `backend/app/router/paper_trading_router.py`：账户、订单、预览等 REST 接口。
- `backend/app/router/watchlist_router.py`：自选股 REST 接口。
- `backend/app/tasks/paper_trading.py`：撮合与对账任务。

### 必须按新架构重写的文件

- `backend/app/chatloop/paper_trade_tools.py`：三个只读工具和三个高风险写工具。
- `backend/app/chatloop/manage_watchlist_tool.py`：低风险幂等直接写工具。
- `backend/app/chatloop/approval_edits.py`：审批编辑值的闭合 schema、校验和 diff。
- `backend/app/chatloop/run_executor.py`：续跑时把已校验编辑值应用到待执行调用。
- `backend/app/chatloop/continuation.py`：在审批 request 中声明可编辑调用和字段。
- `backend/app/services/run_service.py`：解除 RunPause 前校验 `edited_arguments`。
- `backend/app/services/run_chat_worker.py`：静态风险目录、批准调用和持久化账本适配。
- `frontend/src/components/chat/PaperApprovalCard.tsx`：直接消费 `useRunSSE` 的 RunPause。
- `frontend/src/components/chat/ChatPane.tsx`：交易审批卡和通用审批卡分流。

### 明确不创建或恢复

- `backend/app/router/chats.py`
- `backend/app/services/chat_session_repo.py`
- `backend/app/tasks/chat_runner.py`
- `frontend/src/hooks/useChatSSE.ts`

---

### Task 1: 迁移模拟账户和交易规则基础

**Files:**
- Create: `backend/app/models/paper_account.py`
- Create: `backend/app/services/paper_trading/__init__.py`
- Create: `backend/app/services/paper_trading/types.py`
- Create: `backend/app/services/paper_trading/errors.py`
- Create: `backend/app/services/paper_trading/clock.py`
- Create: `backend/app/services/paper_trading/rulebook.py`
- Create: `backend/app/services/paper_trading/fee_schedule.py`
- Create: `backend/app/services/paper_trading/quote_provider.py`
- Create: `backend/app/services/paper_trading/account_service.py`
- Create: `backend/app/services/paper_trading/rules/a_share_20260706.json`
- Create: `backend/app/services/paper_trading/rules/fees_cn_a_20230828.json`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/unit/services/paper_trading/`
- Test: `backend/tests/integration/paper_trading/test_account_models.py`
- Test: `backend/tests/integration/paper_trading/test_account_service.py`

- [ ] **Step 1: 先迁移旧分支的测试并确认失败**

以 `codex/agent-paper-trading-spec@60b0e0f2` 中以下测试为唯一迁移来源：

```text
backend/tests/unit/services/paper_trading/test_types.py
backend/tests/unit/services/paper_trading/test_clock.py
backend/tests/unit/services/paper_trading/test_rulebook.py
backend/tests/unit/services/paper_trading/test_fee_schedule.py
backend/tests/unit/services/paper_trading/test_quote_provider.py
backend/tests/integration/paper_trading/test_account_models.py
backend/tests/integration/paper_trading/test_account_service.py
```

Run:

```powershell
uv run pytest backend/tests/unit/services/paper_trading backend/tests/integration/paper_trading/test_account_models.py backend/tests/integration/paper_trading/test_account_service.py -q
```

Expected: collection fails because the paper-trading models and services do not exist.

- [ ] **Step 2: 迁移领域实现并只改主线兼容点**

从同一旧提交迁移本任务列出的领域文件。只允许以下适配：

```python
# backend/app/models/__init__.py
from app.models.paper_account import (
    PaperAccount,
    PaperAccountResetAudit,
    PaperCashLedger,
    PaperHoldingLot,
)
```

- 使用主线现有 `Base` 和 PostgreSQL 类型；
- 不引入旧 Router、旧 ChatSession 或旧 Celery chat runner；
- 金额继续使用 `Decimal/Numeric`；
- 每个用户只允许一个 active 账户。

- [ ] **Step 3: 运行定向测试**

Run: 与 Step 1 相同。  
Expected: PASS。

- [ ] **Step 4: 提交**

```powershell
git add backend/app/models backend/app/services/paper_trading backend/tests/unit/services/paper_trading backend/tests/integration/paper_trading
git commit -m "feat(paper): restore account and rule foundation"
```

---

### Task 2: 迁移订单、撮合、结算和 Worker 任务

**Files:**
- Create: `backend/app/models/paper_order.py`
- Create: `backend/app/services/paper_trading/order_service.py`
- Create: `backend/app/services/paper_trading/matcher.py`
- Create: `backend/app/services/paper_trading/settlement.py`
- Create: `backend/app/services/paper_trading/reconciliation.py`
- Create: `backend/app/services/paper_trading/observability.py`
- Create: `backend/app/tasks/paper_trading.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/tasks/celery_app.py`
- Modify: `backend/app/tasks/celery_beat_schedule.py`
- Modify: `backend/app/tasks/portfolio_snapshot.py`
- Test: `backend/tests/unit/services/paper_trading/test_matcher.py`
- Test: `backend/tests/integration/paper_trading/`
- Test: `backend/tests/unit/tasks/test_paper_trading_tasks.py`
- Test: `backend/tests/e2e/test_paper_order_worker.py`

- [ ] **Step 1: 迁移订单和 Worker 测试并确认失败**

从旧提交迁移 `backend/tests/integration/paper_trading/` 中订单、结算、对账和性质测试，以及：

```text
backend/tests/unit/services/paper_trading/test_matcher.py
backend/tests/unit/tasks/test_paper_trading_tasks.py
backend/tests/e2e/test_paper_order_worker.py
backend/tests/fixtures/paper_trading_worker_quote.json
backend/tests/worker_paper_trading_fixture.py
```

Run:

```powershell
uv run pytest backend/tests/unit/services/paper_trading/test_matcher.py backend/tests/integration/paper_trading -q
```

Expected: FAIL because order/matching implementation is absent.

- [ ] **Step 2: 迁移订单领域代码**

从 `60b0e0f2` 迁移本任务列出的模型和 service。保留以下恒等式：

```python
assert account.available_cash >= 0
assert account.frozen_cash >= 0
assert order.filled_quantity <= order.quantity
assert holding.remaining_quantity >= 0
assert holding.frozen_quantity >= 0
```

成交必须在一个 PostgreSQL 事务里写 `PaperFill`、资金流水、持股批次、`Trade` 并重算 `Position`。

- [ ] **Step 3: 按主线 Celery 注册方式接入任务**

只把 `paper_trading` 任务加入主线已有 include/import 和 beat schedule；不得覆盖 `b93e5e38` 引入的 Run worker 配置。

```python
imports = (
    # existing mainline tasks stay unchanged
    "app.tasks.paper_trading",
)
```

- [ ] **Step 4: 运行领域和任务测试**

Run:

```powershell
uv run pytest backend/tests/unit/services/paper_trading backend/tests/integration/paper_trading backend/tests/unit/tasks/test_paper_trading_tasks.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/models backend/app/services/paper_trading backend/app/tasks backend/tests
git commit -m "feat(paper): restore order matching and settlement"
```

---

### Task 3: 迁移 REST API 并保持用户隔离

**Files:**
- Create: `backend/app/schemas/paper_trading.py`
- Create: `backend/app/router/paper_trading_router.py`
- Modify: `backend/app/app_main.py`
- Test: `backend/tests/integration/paper_trading/test_account_endpoint.py`
- Test: `backend/tests/integration/paper_trading/test_order_endpoints.py`

- [ ] **Step 1: 迁移 API 测试并确认 404**

Run:

```powershell
uv run pytest backend/tests/integration/paper_trading/test_account_endpoint.py backend/tests/integration/paper_trading/test_order_endpoints.py -q
```

Expected: FAIL/404 because router is not registered.

- [ ] **Step 2: 迁移 schema 和 router**

保留读取、预览和页面使用接口；删除旧的“Chat 工具先 prepare、独立 confirm API 再执行”耦合。Agent 写工具将直接调用领域 service。

```python
# backend/app/app_main.py
app.include_router(paper_trading_router)
```

所有资源查询必须同时约束当前认证用户；访问别人的订单返回 404。

- [ ] **Step 3: 运行 API 测试**

Run: 与 Step 1 相同。  
Expected: PASS。

- [ ] **Step 4: 提交**

```powershell
git add backend/app/schemas/paper_trading.py backend/app/router/paper_trading_router.py backend/app/app_main.py backend/tests/integration/paper_trading
git commit -m "feat(paper): expose tenant-safe paper trading API"
```

---

### Task 4: 迁移自选股、审计和监控范围

**Files:**
- Create: `backend/app/models/watchlist.py`
- Create: `backend/app/services/watchlist_service.py`
- Create: `backend/app/schemas/watchlist.py`
- Create: `backend/app/router/watchlist_router.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/app_main.py`
- Modify: `backend/app/services/monitoring/scope.py`
- Test: `backend/tests/integration/watchlist/`
- Test: `backend/tests/unit/services/monitoring/test_scope_watchlist.py`

- [ ] **Step 1: 迁移自选股测试并确认失败**

Run:

```powershell
uv run pytest backend/tests/integration/watchlist backend/tests/unit/services/monitoring/test_scope_watchlist.py -q
```

Expected: collection fails because watchlist implementation is absent.

- [ ] **Step 2: 迁移模型、service、schema 和 router**

`WatchlistItem` 继续使用 `(user_id, ts_code)` 唯一约束，`monitoring_enabled` 的数据库和 Pydantic 默认值都必须为 `False`。

幂等规则：

```text
add existing       -> return existing, do not overwrite note/switch
update same values -> return current, do not append duplicate audit
remove missing     -> return removed=false, do not fail the Run
```

- [ ] **Step 3: 合并监控范围**

监控范围是：

```python
positions_with_quantity | watchlist_with_monitoring_enabled
```

按 `(user_id, ts_code)` 去重；关闭自选监控不能关闭同股票的持仓监控。

- [ ] **Step 4: 运行测试**

Run: 与 Step 1 相同。  
Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/models backend/app/services/watchlist_service.py backend/app/schemas/watchlist.py backend/app/router/watchlist_router.py backend/app/services/monitoring backend/app/app_main.py backend/tests
git commit -m "feat(watchlist): restore audited CRUD and monitoring scope"
```

---

### Task 5: 扩展 RunPause 支持可编辑工具参数

**Files:**
- Create: `backend/app/chatloop/approval_edits.py`
- Modify: `backend/app/chatloop/continuation.py`
- Modify: `backend/app/chatloop/state.py`
- Modify: `backend/app/chatloop/inprocess.py`
- Modify: `backend/app/chatloop/tool_runtime_adapter.py`
- Modify: `backend/app/chatloop/run_executor.py`
- Modify: `backend/app/runtime/models.py`
- Modify: `backend/app/services/run_service.py`
- Modify: `backend/app/services/attempt_service.py`
- Modify: `backend/app/services/run_chat_worker.py`
- Test: `backend/tests/unit/chatloop/test_approval_edits.py`
- Test: `backend/tests/unit/chatloop/test_run_executor.py`
- Test: `backend/tests/unit/services/test_run_service.py`
- Test: `backend/tests/unit/services/test_run_chat_worker.py`

- [ ] **Step 1: 写审批编辑失败测试**

测试必须覆盖：

```python
def test_approved_edit_replaces_only_named_call_arguments():
    calls = (
        StepToolCall(id="trade-1", name="place_paper_order", arguments='{"quantity":100}'),
        StepToolCall(id="read-1", name="get_paper_account", arguments="{}"),
    )
    effective = apply_approved_edits(calls, {"trade-1": {"quantity": 200}})
    assert effective[0].parsed_args == {"quantity": 200}
    assert effective[1] == calls[1]


def test_edit_for_unknown_call_id_is_rejected():
    with pytest.raises(ValueError, match="unknown tool call"):
        validate_edit_ids(
            requested_ids={"trade-1"},
            editable_ids={"trade-1"},
            edited_arguments={"other": {"quantity": 200}},
        )


def test_rejected_approval_cannot_carry_edits():
    with pytest.raises(ValidationError, match="cannot edit"):
        ApprovalEditResponse.model_validate(
            {"approved": False, "edited_arguments": {"trade-1": {"quantity": 200}}}
        )


async def test_invalid_edited_arguments_do_not_resolve_pause(run_service, pause_row):
    with pytest.raises(ResumeNotAllowed, match="invalid edited arguments"):
        await run_service.resume_run(
            pause_row.tenant_id,
            pause_row.run_id,
            pause_row.actor_id,
            response={
                "approved": True,
                "edited_arguments": {"trade-1": {"quantity": 0}},
            },
        )
    await run_service.session.refresh(pause_row)
    assert pause_row.resolved_at is None


def test_original_and_effective_arguments_are_both_auditable():
    approved = build_approved_inputs(
        (
            StepToolCall(
                id="trade-1",
                name="place_paper_order",
                arguments='{"quantity":100}',
            ),
        ),
        {"trade-1": {"quantity": 200}},
    )
    assert approved["trade-1"].original == {"quantity": 100}
    assert approved["trade-1"].effective == {"quantity": 200}
```

工具名和调用 id 没有出现在 `edited_arguments` 的值结构中，因此客户端没有修改入口；`validate_edit_ids` 还必须拒绝非 editable call id。

Run:

```powershell
uv run pytest backend/tests/unit/chatloop/test_approval_edits.py backend/tests/unit/services/test_run_service.py -q
```

Expected: FAIL because `edited_arguments` is not accepted.

- [ ] **Step 2: 定义闭合审批编辑结构**

```python
# backend/app/chatloop/approval_edits.py
class ApprovalEditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    text: str | None = None
    edited_arguments: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_edits_without_approval(self) -> "ApprovalEditResponse":
        if not self.approved and self.edited_arguments:
            raise ValueError("rejected approval cannot edit arguments")
        return self
```

`PauseRequestV1` 增加 `editable_tool_call_ids`，且必须是 `tool_calls` 的子集。

`RunService` 接受一个服务端注入的 `EditableApprovalValidator`。默认 validator 不允许编辑任何工具，现有调用方行为不变；生产 Router 在 Task 6 注入模拟交易工具的闭合 schema。测试使用假 schema，不依赖尚未创建的交易工具。

```python
class EditableApprovalValidator(Protocol):
    def validate(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]: ...
```

- [ ] **Step 3: 在 RunService 解除 pause 前校验**

校验顺序必须是：

```text
锁定 RunPause
-> 校验响应闭合结构
-> 校验 call id 属于本 pause
-> 校验 call id 声明可编辑
-> 用注册工具的 Pydantic schema 校验完整编辑参数
-> 保存 response_payload
-> 解除 pause
```

任何一步失败都不得设置 `resolved_at`。

- [ ] **Step 4: 续跑时生成不可变的有效调用**

```python
def apply_approved_edits(
    calls: tuple[StepToolCall, ...],
    edited_arguments: Mapping[str, Mapping[str, Any]],
) -> tuple[StepToolCall, ...]:
    return tuple(
        call.model_copy(
            update={
                "arguments": json.dumps(
                    edited_arguments[call.id],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            }
        )
        if call.id in edited_arguments
        else call
        for call in calls
    )
```

continuation 继续保存原始调用；执行账本保存有效调用。RunPause 的 request/response 可以重建字段差异。

同时把批准来源作为只存在于当前续跑 Attempt 的可信上下文：

```python
class ApprovedInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    original: dict[str, Any]
    effective: dict[str, Any]

class ChatLoopState(BaseModel):
    # existing fields stay unchanged
    approved_inputs: dict[str, ApprovedInput] = Field(default_factory=dict, exclude=True)
```

`ChatRunExecutor` 按 `tool_call_id` 填充 `approved_inputs`。`ToolHub` 把对应值放入 `ExecutionContext`；`ChatloopToolAdapter` 调用 `InProcessTool.run_with_context()`。基类默认实现继续委托现有 `run_with_state()`，因此 memory、skill 和控制工具无需改写：

```python
async def run_with_context(
    self,
    args: BaseModel,
    state: ChatLoopState,
    context: ExecutionContext,
) -> dict[str, Any]:
    return await self.run_with_state(args, state)
```

- [ ] **Step 5: 运行 Run 控制面定向测试**

Run:

```powershell
uv run pytest backend/tests/unit/chatloop/test_approval_edits.py backend/tests/unit/chatloop/test_run_executor.py backend/tests/unit/services/test_run_service.py backend/tests/unit/services/test_run_chat_worker.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add backend/app/chatloop backend/app/services backend/tests/unit/chatloop backend/tests/unit/services
git commit -m "feat(runs): support validated editable tool approvals"
```

---

### Task 6: 接入静态风险分级的 Agent 工具

**Files:**
- Create: `backend/app/chatloop/paper_trade_tools.py`
- Create: `backend/app/chatloop/paper_trade_schemas.py`
- Create: `backend/app/chatloop/manage_watchlist_tool.py`
- Modify: `backend/app/chatloop/tool_runtime_policy.py`
- Modify: `backend/app/services/run_chat_worker.py`
- Modify: `backend/app/chatloop/worker_wiring.py`
- Modify: `backend/app/chatloop/tool_docs.py`
- Modify: `backend/app/chatloop/system_prompt.py`
- Modify: `backend/app/router/runs.py`
- Test: `backend/tests/unit/chatloop/test_paper_trade_tools.py`
- Test: `backend/tests/unit/chatloop/test_manage_watchlist_tool.py`
- Test: `backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py`
- Test: `backend/tests/unit/services/test_run_chat_worker.py`

- [ ] **Step 1: 写风险分类和工具行为失败测试**

```python
@pytest.mark.parametrize(
    ("name", "risk", "read_only"),
    [
        ("get_paper_account", RiskLevel.LOW, True),
        ("list_paper_orders", RiskLevel.LOW, True),
        ("get_paper_order", RiskLevel.LOW, True),
        ("place_paper_order", RiskLevel.HIGH, False),
        ("cancel_paper_order", RiskLevel.HIGH, False),
        ("reset_paper_account", RiskLevel.HIGH, False),
        ("manage_watchlist", RiskLevel.LOW, False),
    ],
)
def test_paper_tool_risk_is_static(name, risk, read_only):
    metadata = TOOL_RISK_METADATA[name]
    assert metadata.risk is risk
    assert metadata.read_only is read_only
```

同时验证：

- 自选股调用不产生 `approval_request`；
- 买卖、撤单和重置在 dispatch 前暂停；
- 批准后只执行最终编辑参数；
- 用户 id、Run id、会话 id来自 `ChatLoopState`，不来自模型参数。

- [ ] **Step 2: 实现工具 schema**

```python
class PlacePaperOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    side: Literal["buy", "sell"]
    ts_code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    quantity: int = Field(strict=True, gt=0)
    order_type: Literal["market", "limit"]
    limit_price: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
```

写工具内部业务幂等键固定为：

```python
client_request_id = f"{state.request_id}:{execution_context.task_id}"
```

工具输出必须使用 `model_dump(mode="json")` 或等价 JSON-safe 转换。

`place_paper_order` 调用领域层新增的单一事务入口，不能复用旧的两段式 Chat confirm：

```python
order = service.execute_approved_order(
    user_id=UUID(state.user_id),
    client_request_id=client_request_id,
    confirmed=parsed,
    original_proposal=execution_context.approved_input.original,
    user_edits=diff_arguments(
        execution_context.approved_input.original,
        execution_context.approved_input.effective,
    ),
    source_run_id=UUID(state.request_id),
    source_tool_call_id=execution_context.task_id,
)
```

`cancel_paper_order` 和 `reset_paper_account` 使用同一 provenance 和幂等规则。

- [ ] **Step 3: 注册工具和静态风险**

`tool_runtime_policy.py` 明确列出七个工具；`run_chat_worker.py` 的安全自动重试目录只加入：

```python
"get_paper_account",
"list_paper_orders",
"get_paper_order",
"manage_watchlist",
```

三个高风险写工具不得加入安全目录。

`router/runs.py:get_run_service()` 注入只包含三个高风险写工具 schema 的 `EditableApprovalValidator`。自选股和只读工具不允许通过 resume 改参。

- [ ] **Step 4: 更新工具文档和模型纪律**

系统提示明确：

```text
研究和行情问题不得触发交易工具。
缺股票、方向或数量时先 ask_user。
不得替用户决定交易方向和数量。
只有用户明确要求时才调用 place/cancel/reset。
```

- [ ] **Step 5: 运行工具和 Worker 测试**

Run:

```powershell
uv run pytest backend/tests/unit/chatloop/test_paper_trade_tools.py backend/tests/unit/chatloop/test_manage_watchlist_tool.py backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py backend/tests/unit/services/test_run_chat_worker.py -q
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add backend/app/chatloop backend/app/services/run_chat_worker.py backend/tests/unit
git commit -m "feat(agent): add safe watchlist and approved paper trade tools"
```

---

### Task 7: 把可编辑交易卡接到 Run SSE

**Files:**
- Create: `frontend/src/types/paper-trading.ts`
- Create: `frontend/src/api/paperTrading.ts`
- Create: `frontend/src/components/chat/PaperApprovalCard.tsx`
- Create: `frontend/src/components/chat/PaperApprovalCard.module.scss`
- Modify: `frontend/src/components/chat/ChatPane.tsx`
- Modify: `frontend/src/hooks/useRunSSE.ts`
- Modify: `frontend/src/api/runApi.ts`
- Test: `frontend/src/components/chat/__tests__/PaperApprovalCard.test.tsx`
- Test: `frontend/src/components/chat/__tests__/ChatPane.test.tsx`
- Test: `frontend/src/hooks/__tests__/useRunSSE.test.tsx`

- [ ] **Step 1: 写前端失败测试**

测试场景：

```text
place_paper_order pause -> 渲染专用卡
编辑数量/限价 -> 必须重新 preview
preview 成功 -> resume({approved:true, edited_arguments:{callId: draft}})
拒绝 -> resume({approved:false})
页面刷新恢复 active_pause_request
普通高风险工具 -> 仍渲染通用审批卡
```

Run:

```powershell
cd frontend
npx vitest run src/components/chat/__tests__/PaperApprovalCard.test.tsx src/components/chat/__tests__/ChatPane.test.tsx src/hooks/__tests__/useRunSSE.test.tsx
```

Expected: FAIL because Run approval UI has no paper-trading specialization.

- [ ] **Step 2: 定义前端审批类型**

```typescript
export interface EditableApprovalRequest {
  tool_calls: Array<{ id: string; name: string; arguments: string | Record<string, unknown> }>
  editable_tool_call_ids?: string[]
}

export interface ApprovalResumeResponse {
  approved: boolean
  edited_arguments?: Record<string, Record<string, unknown>>
}
```

- [ ] **Step 3: 迁移确认卡并改用 Run resume**

从旧卡迁移字段、preview、过期和轮询逻辑，但删除旧 `confirmOrder`、`confirmCancel`、`confirmReset` 调用。批准入口统一为：

```typescript
onApprove({
  approved: true,
  edited_arguments: { [toolCallId]: draft },
})
```

- [ ] **Step 4: ChatPane 分流专用卡**

当 pause 中恰好有一个可编辑的模拟交易写工具时渲染 `PaperApprovalCard`；其他情况沿用通用审批 UI。

- [ ] **Step 5: 运行 Vitest**

Run: 与 Step 1 相同。  
Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add frontend/src
git commit -m "feat(frontend): resume paper trades from editable Run approvals"
```

---

### Task 8: 迁移模拟账户页和自选股页

**Files:**
- Create: `frontend/src/pages/paper-trading/index.tsx`
- Create: `frontend/src/pages/paper-trading/index.module.scss`
- Create: `frontend/src/pages/watchlist/index.tsx`
- Create: `frontend/src/api/watchlist.ts`
- Modify: `frontend/src/router/routes.tsx`
- Modify: `frontend/src/components/sidebar/nav-links.ts`
- Test: `frontend/src/pages/paper-trading/__tests__/index.test.tsx`
- Test: `frontend/src/pages/watchlist/__tests__/index.test.tsx`
- Test: `frontend/src/router/__tests__/routes.test.tsx`

- [ ] **Step 1: 迁移页面测试并确认失败**

Run:

```powershell
cd frontend
npx vitest run src/pages/paper-trading/__tests__/index.test.tsx src/pages/watchlist/__tests__/index.test.tsx src/router/__tests__/routes.test.tsx
```

Expected: FAIL because pages and routes do not exist.

- [ ] **Step 2: 迁移页面并适配主线路由**

自选股页面必须允许直接编辑 `note` 和 `monitoring_enabled`；新增记录默认关闭监控。模拟账户页展示数据库返回的账户、订单和持仓，不从聊天 store 推断状态。

- [ ] **Step 3: 运行页面测试**

Run: 与 Step 1 相同。  
Expected: PASS。

- [ ] **Step 4: 提交**

```powershell
git add frontend/src
git commit -m "feat(frontend): restore paper account and watchlist pages"
```

---

### Task 9: 迁移 Agent 评估并验证数据库终态

**Files:**
- Create: `backend/eval/chatloop/golden/paper_trading.jsonl`
- Create: `backend/eval/chatloop/golden/watchlist_monitoring.jsonl`
- Modify: `backend/eval/chatloop/scorers.py`
- Create: `backend/tests/unit/eval/chatloop/test_paper_trading_scenarios.py`
- Create: `backend/tests/unit/eval/chatloop/test_watchlist_scenarios.py`

- [ ] **Step 1: 迁移评估测试并确认失败**

Run:

```powershell
uv run pytest backend/tests/unit/eval/chatloop/test_paper_trading_scenarios.py backend/tests/unit/eval/chatloop/test_watchlist_scenarios.py -q
```

Expected: FAIL until new tool names and Run approval轨迹 are reflected.

- [ ] **Step 2: 更新 golden 和 scorer**

至少覆盖：

```text
“茅台怎么样” -> 不调用交易写工具
“帮我买茅台” -> ask_user 追问数量
明确买入 -> place_paper_order + approval pause
编辑后批准 -> 数据库只出现最终数量和价格
拒绝 -> 无订单、无资金变化
自选股增改删 -> manage_watchlist 直接执行
monitoring_enabled 缺省 -> false
```

评分同时检查工具轨迹、RunPause 和数据库终态。

- [ ] **Step 3: 运行评估测试**

Run: 与 Step 1 相同。  
Expected: PASS。

- [ ] **Step 4: 提交**

```powershell
git add backend/eval backend/tests/unit/eval
git commit -m "test(eval): cover approved paper trades and watchlist writes"
```

---

### Task 10: 浏览器链路、回归验证和交付

**Files:**
- Create: `frontend/tests/e2e/paper-trading.spec.ts`
- Create: `frontend/tests/e2e/watchlist.spec.ts`
- Create: `docs/Codex-context/paper-trading-runtime-adaptation-done.md`

- [ ] **Step 1: 添加 Playwright 链路**

`paper-trading.spec.ts` 验证：

```text
聊天输入买入指令
-> Run waiting_approval
-> 编辑限价并 preview
-> 批准
-> Run 完成
-> 账户页出现同一订单和资金变化
```

`watchlist.spec.ts` 验证：

```text
新增自选股
-> 默认监控关闭
-> 编辑备注和开启监控
-> 删除
-> 无确认弹窗
```

- [ ] **Step 2: 后端完整定向验证**

```powershell
uv run pytest backend/tests/unit/chatloop backend/tests/unit/services backend/tests/integration/paper_trading backend/tests/integration/watchlist backend/tests/unit/tasks/test_paper_trading_tasks.py -q
uv run ruff check backend/app backend/tests
uv run mypy backend/app
python -m compileall -q backend/app
git diff --check origin/main...HEAD
```

Expected: all commands exit 0。

- [ ] **Step 3: 前端完整验证**

```powershell
cd frontend
npm ci
npx vitest run
npx tsc -p tsconfig.json --noEmit
npm run build
npx playwright test --project=chromium tests/e2e/paper-trading.spec.ts tests/e2e/watchlist.spec.ts
```

Expected: all commands exit 0。

- [ ] **Step 4: 运行 Worker E2E**

```powershell
uv run pytest backend/tests/e2e/test_paper_order_worker.py -q
```

Expected: PASS；若依赖容器不可用，先检查现有 Docker/Redis/PostgreSQL 状态，不重启 Windows。

- [ ] **Step 5: 写完成卡并提交**

完成卡只记录实际执行过的测试数量和命令，不写未运行的 CI。

```powershell
git add docs/Codex-context frontend/tests/e2e
git commit -m "docs: record paper trading runtime adaptation"
```

- [ ] **Step 6: 检查交付范围**

```powershell
git status --short
git log --oneline origin/main..HEAD
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD | rg "chats.py|chat_runner.py|chat_session_repo.py|useChatSSE"
```

Expected:

- worktree clean；
- 最后一条 `rg` 无输出；
- 所有改动都属于本设计范围。
