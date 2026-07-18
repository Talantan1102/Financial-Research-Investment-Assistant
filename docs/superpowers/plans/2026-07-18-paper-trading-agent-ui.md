# Paper Trading Agent and UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能在 Chat 中用自然语言准备模拟买卖、撤单和重置，经可编辑确认卡确认后执行，并在模拟账户页查看持久化终态。

**Architecture:** 新增有副作用的 `PaperTradeTool`，它只创建 awaiting-confirmation 资源并发出 `approval_request`，没有 confirm 能力。审批卡作为 `ChatMessage.tool_call_data` 持久化；前端通过 REST 预览/确认，并按 order id 轮询终态。模拟账户页复用同一 API 展示资金、可卖数量、订单、成交和流水。

**Tech Stack:** Python/FastAPI/SQLAlchemy/ChatLoop、TypeScript/React 19/Valtio/Ant Design/Vitest/MSW/Playwright

---

## 前置条件与文件边界

前置：完成 foundation 与 order/matching 两份计划。

- Create: `backend/app/chatloop/paper_trade_tool.py` — Agent 查询和 prepare 工具，无 confirm action。
- Modify: `backend/app/chatloop/worker_wiring.py` — 注册工具并注入 async session factory、时钟/行情/规则 factory。
- Modify: `backend/app/chatloop/tool_docs.py` — 放入核心工具文档。
- Modify: `backend/app/chatloop/system_prompt.py` — 明确研究/交易意图区分和不得自主交易。
- Modify: `backend/app/services/chat_session_repo.py` — 持久化 approval card helper。
- Modify: `backend/app/router/chats.py` — 历史消息返回 `tool_call_data`。
- Modify: `backend/app/tasks/chat_runner.py` — 将工具结果中的 approval payload 发 SSE 并持久化卡片。
- Create: `backend/eval/chatloop/golden/paper_trading.jsonl` — 意图与终态 cases。
- Create: `frontend/src/types/paper-trading.ts`、`frontend/src/api/paperTrading.ts`。
- Create: `frontend/src/store/paper-trading.ts` — 审批卡和轮询状态。
- Create: `frontend/src/components/chat/PaperApprovalCard.tsx` — 可编辑确认卡。
- Modify: `frontend/src/types/chat.ts`、`frontend/src/hooks/useChatSSE.ts`、`frontend/src/store/current-chat.ts`、`frontend/src/components/chat/MessageList.tsx` — 事件与持久卡片。
- Create: `frontend/src/pages/paper-trading/index.tsx` — 模拟账户页。
- Modify: `frontend/src/router/routes.tsx`、`frontend/src/components/sidebar/nav-links.ts` — 页面入口。
- Create: 对应 backend unit/integration/eval 与 frontend Vitest/Playwright 测试。

### Task 1: 定义 Agent 工具参数并确保没有 confirm 动作

**Files:**
- Create: `backend/app/chatloop/paper_trade_tool.py`
- Test: `backend/tests/unit/chatloop/test_paper_trade_tool.py`

- [ ] **Step 1: 写工具 schema 和权限边界失败测试**

```python
def test_schema_exposes_prepare_but_not_confirm() -> None:
    schema = PaperTradeTool(fake_dependencies()).schema_for_llm()["function"]["parameters"]
    actions = schema["properties"]["action"]["enum"]
    assert actions == ["get_account", "list_orders", "get_order", "prepare_order", "prepare_cancel", "prepare_reset"]
    assert "confirm" not in actions

@pytest.mark.asyncio
async def test_prepare_order_returns_approval_without_changing_cash(state, fake_dependencies) -> None:
    before = await fake_dependencies.account_balance(state.user_id)
    result = await PaperTradeTool(fake_dependencies).run_with_state(
        PaperTradeArgs(action="prepare_order", side="buy", ts_code="600519.SH", name="贵州茅台", quantity=100, order_type="limit", limit_price=Decimal("1500")), state,
    )
    assert result["approval"]["approval_type"] == "paper_order"
    assert await fake_dependencies.account_balance(state.user_id) == before
```

- [ ] **Step 2: 运行并确认缺少工具**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/chatloop/test_paper_trade_tool.py -q`

Expected: FAIL，缺少 `PaperTradeTool`。

- [ ] **Step 3: 实现单一 action schema 和 state 归属注入**

```python
class PaperTradeArgs(BaseModel):
    action: Literal["get_account", "list_orders", "get_order", "prepare_order", "prepare_cancel", "prepare_reset"]
    order_id: UUID | None = None
    side: OrderSide | None = None
    ts_code: str | None = None
    name: str | None = None
    quantity: int | None = Field(default=None, gt=0)
    order_type: OrderType | None = None
    limit_price: Decimal | None = None
    initial_cash: Decimal | None = Field(default=None, gt=0)


class PaperTradeTool(InProcessTool):
    name = "paper_trade"
    description = "查询模拟账户/订单，或在用户明确要求买卖、撤单、重置时准备确认卡；本工具不能确认。"
    args_schema = PaperTradeArgs

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        parsed = PaperTradeArgs.model_validate(args.model_dump())
        return await self._dependencies.dispatch(parsed, user_id=state.user_id, session_id=state.session_id, request_id=state.request_id)
```

工具从 `state.user_id/session_id/request_id` 取归属，不允许模型传 user id。缺股票、方向、数量返回 `missing_order_field` 和明确 `missing_fields`；“买一万块”必须先解析为金额语义并在换算后把股数写入 approval preview。

- [ ] **Step 4: 运行工具测试**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/chatloop/test_paper_trade_tool.py -q`

Expected: PASS。

- [ ] **Step 5: 提交工具**

```bash
git add backend/app/chatloop/paper_trade_tool.py backend/tests/unit/chatloop/test_paper_trade_tool.py
git commit -m "feat(chat): prepare paper trades through agent tool"
```

### Task 2: 注册工具、文档和模型纪律

**Files:**
- Modify: `backend/app/chatloop/worker_wiring.py`
- Modify: `backend/app/chatloop/tool_docs.py`
- Modify: `backend/app/chatloop/system_prompt.py`
- Test: `backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py`
- Test: `backend/tests/unit/chatloop/test_tool_docs.py`

- [ ] **Step 1: 写注册、渐进披露和 prompt 红线测试**

```python
def test_turn_hub_registers_paper_trade(singletons) -> None:
    names = [s["function"]["name"] for s in build_turn_components(singletons, emit=noop_emit, seq_counter=SeqCounter()).tool_hub.schemas_for_llm()]
    assert "paper_trade" in names

def test_prompt_forbids_autonomous_trade() -> None:
    assert "只在用户明确提出买入、卖出、撤单或重置时" in CHAT_SYSTEM_PROMPT
    assert "不得主动替用户决定" in CHAT_SYSTEM_PROMPT
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py backend/tests/unit/chatloop/test_tool_docs.py -q`

Expected: FAIL，工具尚未注册。

- [ ] **Step 3: 在 HeavySingletons 增加明确依赖并注册**

```python
@dataclass
class HeavySingletons:
    # 保留现有 llm/registry/memory/loader/executor/cache 等字段
    paper_dependencies: PaperTradeDependencies | None = None

# build_turn_components
if singletons.paper_dependencies is not None:
    inprocess_tools.append(PaperTradeTool(singletons.paper_dependencies))
hub.register_inprocess(inprocess_tools)
```

生产 `PaperTradeDependencies` 使用 async session factory；测试传 fake。不得在工具内创建全局同步 Session。

- [ ] **Step 4: 将 paper_trade 放入核心组并写完整文档**

文档列出六个 action、必填字段和反例：研究问句不得 prepare；金额和股数必须区分；prepare 之后必须等待卡片；工具没有 confirm。

- [ ] **Step 5: 在 prompt 添加四条纪律**

```text
- 只在用户明确提出买入、卖出、撤单或重置时调用 paper_trade 的 prepare 动作。
- 用户只问“怎么看/风险/行情/研究”时不得准备订单。
- 缺股票身份、买卖方向或数量时先追问，不得替用户补决定。
- prepare 只生成确认卡；不得声称已经成交，最终结果以账户和订单状态为准。
```

- [ ] **Step 6: 运行测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py backend/tests/unit/chatloop/test_tool_docs.py -q`

Expected: PASS。

```bash
git add backend/app/chatloop/worker_wiring.py backend/app/chatloop/tool_docs.py backend/app/chatloop/system_prompt.py backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py backend/tests/unit/chatloop/test_tool_docs.py
git commit -m "feat(chat): register paper trade tool safely"
```

### Task 3: 持久化 approval card 并发出结构化 SSE

**Files:**
- Modify: `backend/app/services/chat_session_repo.py`
- Modify: `backend/app/router/chats.py`
- Modify: `backend/app/tasks/chat_runner.py`
- Test: `backend/tests/unit/services/test_chat_session_repo.py`
- Test: `backend/tests/unit/tasks/test_chat_runner_paper_approval.py`
- Test: `backend/tests/integration/test_chats_router.py`

- [ ] **Step 1: 写卡片落库、SSE 和历史恢复测试**

```python
def test_append_approval_message_persists_payload(repo, session_id) -> None:
    message = repo.append_message(
        session_id=session_id, role="assistant", content="请确认模拟订单",
        message_type="paper_approval", tool_call_data=APPROVAL_PAYLOAD,
    )
    assert message.tool_call_data["resource_id"] == APPROVAL_PAYLOAD["resource_id"]

def test_chat_detail_returns_tool_call_data(client, approval_message) -> None:
    body = client.get(f"/api/v0/chats/{approval_message.session_id}").json()
    assert body["messages"][-1]["message_type"] == "paper_approval"
    assert body["messages"][-1]["tool_call_data"]["approval_type"] == "paper_order"
```

- [ ] **Step 2: 运行并确认历史响应缺字段**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/tasks/test_chat_runner_paper_approval.py backend/tests/integration/test_chats_router.py -q`

Expected: FAIL，`tool_call_data` 未被序列化或事件未发出。

- [ ] **Step 3: 统一 approval payload**

```python
class ApprovalPayload(BaseModel):
    approval_id: str
    approval_type: Literal["paper_order", "paper_cancel", "paper_reset"]
    resource_id: str
    proposal: dict[str, Any]
    preview: dict[str, Any]
    expires_at: datetime
```

`PaperTradeTool` 成功 prepare 时返回 `{"approval": ApprovalPayload.model_dump(mode="json")}`。`chat_runner` 在工具结果 merge 后识别该键，调用 `ChatSessionRepo.append_message(session_id=session_id, role="assistant", content="请确认模拟操作", message_type="paper_approval", tool_call_data=payload, task_id=task_id)`，再通过 bus 发：

```python
{"type": "approval_request", "seq": seq.next(), **payload}
```

只持久化一次，以 `(session_id, approval_id)` 应用级查询防重。

- [ ] **Step 4: 让 chats router 返回完整卡片字段**

```python
{
    "id": str(m.id), "role": m.role, "content": m.content,
    "message_type": m.message_type, "tool_call_data": m.tool_call_data,
    "task_id": str(m.task_id) if m.task_id else None,
    "status": m.status, "created_at": m.created_at.isoformat() if m.created_at else "",
}
```

- [ ] **Step 5: 运行测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/tasks/test_chat_runner_paper_approval.py backend/tests/integration/test_chats_router.py -q`

Expected: PASS。

```bash
git add backend/app/services/chat_session_repo.py backend/app/router/chats.py backend/app/tasks/chat_runner.py backend/tests/unit/tasks/test_chat_runner_paper_approval.py backend/tests/integration/test_chats_router.py
git commit -m "feat(chat): persist paper approval cards"
```

### Task 4: 定义前端类型、API 和审批 store

**Files:**
- Create: `frontend/src/types/paper-trading.ts`
- Create: `frontend/src/api/paperTrading.ts`
- Create: `frontend/src/store/paper-trading.ts`
- Modify: `frontend/src/types/chat.ts`
- Test: `frontend/src/api/__tests__/paperTrading.test.ts`
- Test: `frontend/src/store/__tests__/paper-trading.test.ts`

- [ ] **Step 1: 写 API 路径、编辑稿和轮询状态测试**

```typescript
it('previews edited draft and confirms with a stable request id', async () => {
  server.use(http.post(`${API_BASE}/api/v0/paper-trading/orders/o1/confirm`, async ({ request }) => {
    const body = await request.json() as OrderConfirmRequest
    expect(body.client_request_id).toBe('approval-a1')
    expect(body.draft.quantity).toBe(200)
    return HttpResponse.json({ id: 'o1', status: 'open' })
  }))
  await confirmOrder('o1', { client_request_id: 'approval-a1', draft: editedDraft })
})
```

- [ ] **Step 2: 运行并确认模块缺失**

Run: `npm --prefix frontend test -- --run src/api/__tests__/paperTrading.test.ts src/store/__tests__/paper-trading.test.ts`

Expected: FAIL，缺少模块。

- [ ] **Step 3: 实现共享类型**

```typescript
export type OrderSide = 'buy' | 'sell'
export type OrderType = 'market' | 'limit'
export type OrderStatus = 'awaiting_confirmation' | 'queued' | 'open' | 'partially_filled' | 'filled' | 'cancelled' | 'expired' | 'rejected'
export interface OrderDraft { side: OrderSide; ts_code: string; name: string; quantity: number; order_type: OrderType; limit_price: string | null }
export interface ApprovalPayload { approval_id: string; approval_type: 'paper_order' | 'paper_cancel' | 'paper_reset'; resource_id: string; proposal: OrderDraft | Record<string, unknown>; preview: OrderPreview; expires_at: string }
export interface ApprovalRequestEvent extends BaseEvent, ApprovalPayload { type: 'approval_request' }
```

将 `MessageType` 加入 `paper_approval`，`ChatMessage.tool_call_data` 收窄为 `ApprovalPayload | Record<string, unknown> | null`，并把 `ApprovalRequestEvent` 加入 `SSEEvent`。

- [ ] **Step 4: 实现 API 与 Valtio store**

API 导出 `getAccount/listOrders/getOrder/previewOrder/confirmOrder/previewCancel/confirmCancel/previewReset/confirmReset`。store 用 `Record<approval_id, ApprovalCardState>` 保存 draft、preview、submitting、error；`upsert()` 以 approval id 幂等恢复。

- [ ] **Step 5: 运行测试并提交**

Run: `npm --prefix frontend test -- --run src/api/__tests__/paperTrading.test.ts src/store/__tests__/paper-trading.test.ts`

Expected: PASS。

```bash
git add frontend/src/types/paper-trading.ts frontend/src/types/chat.ts frontend/src/api/paperTrading.ts frontend/src/store/paper-trading.ts frontend/src/api/__tests__/paperTrading.test.ts frontend/src/store/__tests__/paper-trading.test.ts
git commit -m "feat(frontend): add paper trading client state"
```

### Task 5: 接收实时 approval 事件并恢复历史卡片

**Files:**
- Modify: `frontend/src/hooks/useChatSSE.ts`
- Modify: `frontend/src/store/current-chat.ts`
- Test: `frontend/src/hooks/__tests__/useChatSSE.test.tsx`
- Test: `frontend/src/store/__tests__/current-chat.test.ts`

- [ ] **Step 1: 写 SSE 与历史 setSession 测试**

```typescript
it('approval_request creates one approval card state', async () => {
  // stream the same approval twice with increasing seq
  expect(Object.keys(paperTradingState.approvals)).toEqual(['approval-a1'])
})

it('setSession restores paper approval messages', () => {
  currentChatActions.setSession('s1', [approvalMessage])
  expect(paperTradingState.approvals['approval-a1'].draft.quantity).toBe(100)
})
```

- [ ] **Step 2: 运行并确认 store 未接线**

Run: `npm --prefix frontend test -- --run src/hooks/__tests__/useChatSSE.test.tsx src/store/__tests__/current-chat.test.ts`

Expected: FAIL。

- [ ] **Step 3: 接入事件和历史恢复**

`useChatSSE` 在 `approval_request` 调 `paperTradingActions.upsert(ev)`；`currentChatActions.setSession()` 扫描 `message_type === 'paper_approval'` 且有 `tool_call_data` 的消息并 upsert。approval 事件仍交给 `currentChatActions.dispatchEvent()` 保持 seq 单调。

- [ ] **Step 4: 运行测试并提交**

Run: `npm --prefix frontend test -- --run src/hooks/__tests__/useChatSSE.test.tsx src/store/__tests__/current-chat.test.ts`

Expected: PASS。

```bash
git add frontend/src/hooks/useChatSSE.ts frontend/src/store/current-chat.ts frontend/src/hooks/__tests__/useChatSSE.test.tsx frontend/src/store/__tests__/current-chat.test.ts
git commit -m "feat(frontend): restore paper approvals from stream and history"
```

### Task 6: 实现可编辑确认卡

**Files:**
- Create: `frontend/src/components/chat/PaperApprovalCard.tsx`
- Create: `frontend/src/components/chat/PaperApprovalCard.module.scss`
- Modify: `frontend/src/components/chat/MessageList.tsx`
- Test: `frontend/src/components/chat/__tests__/PaperApprovalCard.test.tsx`
- Test: `frontend/src/components/chat/__tests__/MessageList.test.tsx`

- [ ] **Step 1: 写编辑重算、确认、取消和过期测试**

```typescript
it('edits quantity, refreshes preview, then confirms final values', async () => {
  const user = userEvent.setup()
  render(<PaperApprovalCard message={approvalMessage} />)
  await user.clear(screen.getByLabelText('数量'))
  await user.type(screen.getByLabelText('数量'), '200')
  await user.click(screen.getByRole('button', { name: '重新计算' }))
  expect(previewOrder).toHaveBeenCalledWith('o1', expect.objectContaining({ quantity: 200 }))
  await user.click(screen.getByRole('button', { name: '确认模拟买入' }))
  expect(confirmOrder).toHaveBeenCalledWith('o1', expect.objectContaining({ draft: expect.objectContaining({ quantity: 200 }) }))
})
```

- [ ] **Step 2: 运行并确认组件缺失**

Run: `npm --prefix frontend test -- --run src/components/chat/__tests__/PaperApprovalCard.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现订单卡**

订单卡使用受控 `Select/InputNumber` 编辑 side、股票、quantity、order_type、limit_price；任何字段变化将 `previewDirty=true` 并禁用确认，直到 preview 成功。展示行情时间、预计资金/费用、可用资金/可卖股份、市场阶段和模拟排队免责声明。

确认按钮生成稳定 `client_request_id = approval_id`；请求中禁用按钮；409 显示服务端人话错误；成功后按 `getOrder(resource_id)` 每 2 秒轮询，终态或组件卸载停止。

撤单卡和重置卡复用组件内按 `approval_type` 分支，但各自只展示相关字段；它们同样必须确认。

- [ ] **Step 4: 在 MessageList 路由卡片**

```tsx
case 'paper_approval':
  return <PaperApprovalCard message={message} />
```

- [ ] **Step 5: 运行组件测试并提交**

Run: `npm --prefix frontend test -- --run src/components/chat/__tests__/PaperApprovalCard.test.tsx src/components/chat/__tests__/MessageList.test.tsx`

Expected: PASS。

```bash
git add frontend/src/components/chat/PaperApprovalCard.tsx frontend/src/components/chat/PaperApprovalCard.module.scss frontend/src/components/chat/MessageList.tsx frontend/src/components/chat/__tests__/PaperApprovalCard.test.tsx frontend/src/components/chat/__tests__/MessageList.test.tsx
git commit -m "feat(frontend): render editable paper approval cards"
```

### Task 7: 实现模拟账户页面

**Files:**
- Create: `frontend/src/pages/paper-trading/index.tsx`
- Create: `frontend/src/pages/paper-trading/index.module.scss`
- Modify: `frontend/src/router/routes.tsx`
- Modify: `frontend/src/components/sidebar/nav-links.ts`
- Test: `frontend/src/pages/paper-trading/__tests__/index.test.tsx`
- Test: `frontend/src/router/__tests__/routes.test.tsx`

- [ ] **Step 1: 写资金、可卖、订单终态和重置入口测试**

```typescript
it('renders account balances and distinguishes total from sellable quantity', async () => {
  render(<PaperTradingPage />)
  expect(await screen.findByText('可用资金')).toBeInTheDocument()
  expect(screen.getByText('总持仓 200')).toBeInTheDocument()
  expect(screen.getByText('可卖 100')).toBeInTheDocument()
})
```

- [ ] **Step 2: 运行并确认页面缺失**

Run: `npm --prefix frontend test -- --run src/pages/paper-trading/__tests__/index.test.tsx src/router/__tests__/routes.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现页面**

页面顶部三张卡：总资产、可用资金、冻结资金；tabs：持仓、订单、成交、资金流水。持仓表必须分列 `quantity` 与 `sellable_quantity`；订单显示 queued/open/partial/terminal 标签和更新时间。重置按钮调用 reset-preview 后打开同一 `PaperApprovalCard` 风格确认框，不得直接 reset-confirm。

- [ ] **Step 4: 注册路由和导航**

```tsx
{ path: '/paper-trading', Component: PaperTradingPage }
```

```typescript
{ to: '/paper-trading', label: '模拟账户', icon: 'chart' }
```

- [ ] **Step 5: 运行页面测试并提交**

Run: `npm --prefix frontend test -- --run src/pages/paper-trading/__tests__/index.test.tsx src/router/__tests__/routes.test.tsx`

Expected: PASS。

```bash
git add frontend/src/pages/paper-trading frontend/src/router/routes.tsx frontend/src/components/sidebar/nav-links.ts frontend/src/router/__tests__/routes.test.tsx
git commit -m "feat(frontend): add paper trading account page"
```

### Task 8: 添加 Agent 意图与数据库终态评估

**Files:**
- Create: `backend/eval/chatloop/golden/paper_trading.jsonl`
- Create: `backend/tests/eval/chatloop/test_paper_trading_scenarios.py`
- Modify: `backend/eval/chatloop/scorers.py`

- [ ] **Step 1: 写九类 golden case**

JSONL 必须包含：只分析不下单、缺数量追问、金额/股数区分、明确买入 prepare、明确卖出 prepare、卡片编辑后最终值、取消不改库、Agent 不建议数量、T+1/余额/行情过期解释。每条声明 `expected_tools`、`forbidden_tools`、`expected_approval_type` 和 `database_assertions`。

- [ ] **Step 2: 写 scorer 失败测试**

```python
def test_scorer_requires_both_tool_route_and_database_terminal_state() -> None:
    assert score_case(expected, trace_with_correct_tool, wrong_database_state).passed is False
    assert score_case(expected, trace_with_correct_tool, correct_database_state).passed is True
```

- [ ] **Step 3: 实现复合判分**

新增 `PaperTradingOutcomeScorer`：工具选择 30%、审批载荷 20%、禁止自主交易 20%、数据库终态 30%；任一 forbidden tool 或重复扣款为 hard fail。

- [ ] **Step 4: 运行评估测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/eval/chatloop/test_paper_trading_scenarios.py -q`

Expected: PASS。

```bash
git add backend/eval/chatloop/golden/paper_trading.jsonl backend/eval/chatloop/scorers.py backend/tests/eval/chatloop/test_paper_trading_scenarios.py
git commit -m "test(chat): evaluate paper trade intent and outcomes"
```

### Task 9: 浏览器全链路与完成验证

**Files:**
- Create: `frontend/tests/e2e/paper-trading.spec.ts`
- Modify: `docs/Codex-context/` 中新增本阶段完成卡片，仅在实现确实落地后执行。

- [ ] **Step 1: 写真实浏览器链路**

Playwright 脚本按顺序：登录 → Chat 输入明确限价买入 → 等审批卡 → 将数量 100 改 200 → 重新预览 → 确认 → 打开模拟账户页 → 看到冻结 → 注入第二档行情触发部分成交 → 页面刷新 → 看到 partial 和 Position → 撤销剩余 → 看到释放。每一步用 order id 断言，不用固定 sleep。

- [ ] **Step 2: 运行后端范围测试**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/chatloop/test_paper_trade_tool.py backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py backend/tests/unit/tasks/test_chat_runner_paper_approval.py backend/tests/eval/chatloop/test_paper_trading_scenarios.py -q`

Expected: 全部 PASS。

- [ ] **Step 3: 运行前端测试、lint 和 build**

Run: `npm --prefix frontend test -- --run`

Run: `npm --prefix frontend run lint`

Run: `npm --prefix frontend run build`

Expected: 三条命令 exit 0。

- [ ] **Step 4: 运行真实依赖 e2e**

Run: `npm --prefix frontend run test:e2e -- paper-trading.spec.ts`

Expected: PASS，录像/trace 中确认卡编辑、确认、部分成交、刷新恢复和撤单均可见。

- [ ] **Step 5: 提交 e2e 与完成卡片**

```bash
git add frontend/tests/e2e/paper-trading.spec.ts docs/Codex-context
git commit -m "test(paper): verify agent trading browser flow"
```
