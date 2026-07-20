# Paper Order and Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在模拟账户底座上实现可确认订单、资金/股份冻结、五档部分成交、撤单、T+1、费用结算和 `Fill → Trade → Position` 原子投影。

**Architecture:** `PaperOrderService` 管订单状态和冻结，`PaperMatcher` 只消费 `open/partially_filled` 订单，`PaperSettlementService` 在一个 PostgreSQL 事务内写 Fill、流水、批次、Trade 和 Position。REST API 负责用户归属、预览、确认和撤单；Celery 只负责重试安全的撮合调度。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy/PostgreSQL 行锁、Celery/Redis、Pydantic v2、pytest、Hypothesis

---

## 前置条件与文件边界

前置：完成 `2026-07-18-paper-trading-foundation.md`，已有 `PaperAccountService`、`RuleBook`、`TradingClock`、`RealtimeQuoteProvider` 和账户 ORM。

- Create: `backend/app/models/paper_order.py` — 订单、成交、撮合水位与确认记录。
- Modify: `backend/app/models/__init__.py` — 注册新模型。
- Create: `backend/app/services/paper_trading/order_service.py` — prepare/preview/confirm/cancel 状态机。
- Create: `backend/app/services/paper_trading/matcher.py` — 五档撮合纯算法与 worker 编排。
- Create: `backend/app/services/paper_trading/settlement.py` — 原子结算和 Trade 投影。
- Create: `backend/app/services/paper_trading/reconciliation.py` — 账目恒等式和挂单恢复。
- Modify: `backend/app/services/trade_service.py` — 允许调用方提供稳定 trade id。
- Modify: `backend/app/schemas/paper_trading.py` — 订单/成交/预览 schema。
- Modify: `backend/app/router/paper_trading_router.py` — 订单、确认、撤单和重置确认 API。
- Create: `backend/app/tasks/paper_trading.py` — 撮合、开市转单、收盘失效、T+1 释放和 reconciliation。
- Modify: `backend/app/tasks/celery_app.py`、`backend/app/tasks/celery_beat_schedule.py` — 注册任务与调度。
- Create: `backend/tests/unit/services/paper_trading/test_matcher.py` — 纯五档算法。
- Create: `backend/tests/integration/paper_trading/test_order_lifecycle.py` — 真 PG 生命周期。
- Create: `backend/tests/e2e/test_paper_order_worker.py` — Redis/Celery 重投与恢复。

### Task 1: 建立订单、成交和状态约束

**Files:**
- Create: `backend/app/models/paper_order.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/integration/paper_trading/test_order_models.py`

- [ ] **Step 1: 写终态、唯一键和跨 generation 测试**

```python
def test_order_idempotency_and_fill_sequence_are_unique(db_session, account, user) -> None:
    order = make_order(db_session, account=account, user=user, client_request_id="req-1")
    db_session.flush()
    db_session.add(make_order(account=account, user=user, client_request_id="req-1"))
    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()
    db_session.add(PaperFill(order_id=order.id, fill_seq=1, quantity=100, price=Decimal("10.00"), gross_amount=Decimal("1000"), trade_id=uuid4()))
    db_session.flush()
    db_session.add(PaperFill(order_id=order.id, fill_seq=1, quantity=100, price=Decimal("10.00"), gross_amount=Decimal("1000"), trade_id=uuid4()))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: 运行并确认缺模型失败**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_models.py -q`

Expected: FAIL，缺少 `paper_order`。

- [ ] **Step 3: 实现枚举和 ORM**

```python
class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"

class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"

class OrderStatus(StrEnum):
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    QUEUED = "queued"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"
```

`PaperOrder` 使用 spec §6.3 的全部字段；`client_request_id` 在 prepare 阶段允许空，在 confirm 时写入并建立条件唯一索引；`CHECK filled_quantity BETWEEN 0 AND quantity`；`limit_price` 与 order_type 使用 check constraint 保证 limit 必填、market 为空。

`PaperFill` 使用 `(order_id, fill_seq)` 和 `trade_id` 唯一约束。`PaperMatchPass` 使用 `(order_id, quote_timestamp, match_pass)` 唯一约束，记录本次已消费的五档快照摘要。

- [ ] **Step 4: 导出模型并运行测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_models.py -q`

Expected: PASS。

- [ ] **Step 5: 提交订单模型**

```bash
git add backend/app/models/paper_order.py backend/app/models/__init__.py backend/tests/integration/paper_trading/test_order_models.py
git commit -m "feat(paper): add order fill and match models"
```

### Task 2: 实现 prepare 与服务端预览

**Files:**
- Create: `backend/app/services/paper_trading/order_service.py`
- Modify: `backend/app/schemas/paper_trading.py`
- Test: `backend/tests/integration/paper_trading/test_order_prepare.py`

- [ ] **Step 1: 写“prepare 不改账”和编辑后重算测试**

```python
def test_prepare_order_only_persists_proposal(db_session, user, quote_provider, clock, rulebook) -> None:
    account = PaperAccountService(db_session).get_or_create(user_id=user.id)
    before = (account.available_cash, account.frozen_cash)
    service = PaperOrderService(db_session, quote_provider=quote_provider, clock=clock, rulebook=rulebook)
    order, preview = service.prepare_order(
        user_id=user.id, session_id="s1", message_id="m1", side="buy",
        ts_code="600519.SH", name="贵州茅台", quantity=100,
        order_type="limit", limit_price=Decimal("1500"),
    )
    assert order.status == OrderStatus.AWAITING_CONFIRMATION
    assert (account.available_cash, account.frozen_cash) == before
    assert preview.estimated_gross == Decimal("150000.00")
```

同一任务必须增加真实 PostgreSQL 双 session 竞态测试：一个 session 执行
`prepare_order()`，另一个 session 同时执行首次资金编辑 PATCH。测试必须证明两条路径都先
`SELECT ... FOR UPDATE` 锁定同一 active `PaperAccount` 行，因此串行后的合法终态只能是：
资金编辑先完成后 prepare 读取新资金状态，或者 prepare 先插入 proposal/activity 后 PATCH
稳定返回 `initial_cash_edit_not_allowed`。禁止出现 proposal 绑定旧资金快照而 PATCH 又同时
成功的跨阶段 TOCTOU 终态。

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_prepare.py -q`

Expected: FAIL，缺少 `PaperOrderService`。

- [ ] **Step 3: 实现明确签名和 preview schema**

```python
class OrderDraft(BaseModel):
    side: OrderSide
    ts_code: str
    name: str
    quantity: int = Field(gt=0)
    order_type: OrderType
    limit_price: Decimal | None = None

class OrderPreview(BaseModel):
    order_id: UUID
    draft: OrderDraft
    quote: RealtimeQuote
    estimated_gross: Decimal
    estimated_fees: FeeBreakdown
    estimated_cash_required: Decimal
    available_cash: Decimal
    sellable_quantity: int
    market_phase: MarketPhase
    rules_version: str
```

`PaperOrderService` 必须暴露精确接口 `prepare_order(*, user_id: UUID, session_id: str, message_id: str, side: str, ts_code: str, name: str, quantity: int, order_type: str, limit_price: Decimal | None) -> tuple[PaperOrder, OrderPreview]` 和 `preview(*, user_id: UUID, order_id: UUID, draft: OrderDraft) -> OrderPreview`。

preview 每次重新获取行情、规则和账户；只做计算，不冻结资源。买入估算包含最坏可接受成交金额与费用；卖出展示批次汇总出的 `sellable_quantity`。

`prepare_order()` 在写入 `PaperOrder` proposal 或任何可被首次资金编辑视为 activity 的记录之前，
必须调用 `PaperAccountService.get_active(user_id=user_id, for_update=True)`，并将账户行锁保持到
调用方事务提交或回滚。该锁与 `edit_initial_cash_once()` 使用同一行锁，是 prepare/PATCH
跨阶段互斥的公共契约；只读 `preview()` 不得制造 activity。

- [ ] **Step 4: 运行 prepare 测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_prepare.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 prepare 流程**

```bash
git add backend/app/services/paper_trading/order_service.py backend/app/schemas/paper_trading.py backend/tests/integration/paper_trading/test_order_prepare.py
git commit -m "feat(paper): prepare and preview paper orders"
```

### Task 3: 实现确认、行锁、冻结和幂等

**Files:**
- Modify: `backend/app/services/paper_trading/order_service.py`
- Test: `backend/tests/integration/paper_trading/test_order_confirm.py`

- [ ] **Step 1: 写双击确认、余额竞争、闭市市价拒绝测试**

```python
def test_confirm_is_idempotent_and_freezes_once(db_session, prepared_order, service) -> None:
    first = service.confirm(user_id=prepared_order.user_id, order_id=prepared_order.id, draft=edited_draft, client_request_id="confirm-1")
    second = service.confirm(user_id=prepared_order.user_id, order_id=prepared_order.id, draft=edited_draft, client_request_id="confirm-1")
    assert first.id == second.id
    account = service.account_service.get_active(user_id=prepared_order.user_id)
    assert account.frozen_cash == first.reserved_cash
    assert db_session.query(PaperCashLedger).filter_by(business_key=f"order-freeze:{first.id}").count() == 1
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_confirm.py -q`

Expected: FAIL，缺少 `confirm()`。

- [ ] **Step 3: 实现确认事务**

```python
def confirm(self, *, user_id: UUID, order_id: UUID, draft: OrderDraft, client_request_id: str) -> PaperOrder:
    order = self._owned_order(user_id=user_id, order_id=order_id, for_update=True)
    account = self.account_service.get_active(user_id=user_id, for_update=True)
    if order.account_generation != account.generation:
        raise PaperTradingError("stale_account_generation", "账户已重置，请重新下单")
    existing = self._by_client_request_id(client_request_id)
    if existing is not None:
        return existing
    preview = self.preview(user_id=user_id, order_id=order_id, draft=draft)
    self._validate_market_phase(draft.order_type, preview.market_phase)
    self._reserve(account=account, order=order, preview=preview)
    order.client_request_id = client_request_id
    order.confirmed_payload = draft.model_dump(mode="json")
    order.user_edits = json_diff(order.original_proposal, order.confirmed_payload)
    order.status = OrderStatus.OPEN if preview.market_phase in {MarketPhase.MORNING, MarketPhase.AFTERNOON} else OrderStatus.QUEUED
    self._session.flush()
    return order
```

买单冻结“限价 × 数量 + 最大预计费用”；卖单按 FIFO 批次增加 `frozen_quantity`。账户和批次均在同一事务锁定；不足分别抛 `insufficient_cash` 和 `insufficient_sellable_quantity`。

- [ ] **Step 4: 运行确认与并发测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_confirm.py -q`

Expected: PASS，双击不重复冻结，两个独立 session 竞争同一余额时只有一个成功。

- [ ] **Step 5: 提交确认逻辑**

```bash
git add backend/app/services/paper_trading/order_service.py backend/tests/integration/paper_trading/test_order_confirm.py
git commit -m "feat(paper): confirm and reserve orders atomically"
```

### Task 4: 实现五档撮合纯算法

**Files:**
- Create: `backend/app/services/paper_trading/matcher.py`
- Test: `backend/tests/unit/services/paper_trading/test_matcher.py`

- [ ] **Step 1: 写限价、市价、部分成交和不可成交测试**

```python
def test_limit_buy_consumes_asks_best_first_and_partially_fills() -> None:
    quote = quote_fixture(asks=[("10.00", 100), ("10.01", 200), ("10.02", 300), ("10.03", 400), ("10.04", 500)])
    executions = match_visible_depth(side="buy", order_type="limit", remaining=500, limit_price=Decimal("10.01"), quote=quote)
    assert [(x.price, x.quantity) for x in executions] == [(Decimal("10.00"), 100), (Decimal("10.01"), 200)]
    assert sum(x.quantity for x in executions) == 300

def test_limit_sell_does_not_cross_below_limit() -> None:
    assert match_visible_depth(side="sell", order_type="limit", remaining=100, limit_price=Decimal("10.50"), quote=quote_fixture()) == []
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_matcher.py -q`

Expected: FAIL，缺少 matcher。

- [ ] **Step 3: 实现无数据库副作用的算法**

```python
class Execution(BaseModel):
    model_config = ConfigDict(frozen=True)
    price: Decimal
    quantity: int

def match_visible_depth(*, side: OrderSide, order_type: OrderType, remaining: int, limit_price: Decimal | None, quote: RealtimeQuote) -> list[Execution]:
    levels = quote.asks if side == OrderSide.BUY else quote.bids
    out: list[Execution] = []
    left = remaining
    for level in levels:
        acceptable = order_type == OrderType.MARKET or (side == OrderSide.BUY and level.price <= limit_price) or (side == OrderSide.SELL and level.price >= limit_price)
        if not acceptable or left == 0:
            break
        used = min(left, level.quantity)
        if used:
            out.append(Execution(price=level.price, quantity=used))
            left -= used
    return out
```

- [ ] **Step 4: 运行 matcher 测试**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading/test_matcher.py -q`

Expected: PASS。

- [ ] **Step 5: 提交算法**

```bash
git add backend/app/services/paper_trading/matcher.py backend/tests/unit/services/paper_trading/test_matcher.py
git commit -m "feat(paper): match orders against visible depth"
```

### Task 5: 实现原子结算和 Trade 投影

**Files:**
- Create: `backend/app/services/paper_trading/settlement.py`
- Modify: `backend/app/services/trade_service.py`
- Test: `backend/tests/integration/paper_trading/test_settlement.py`

- [ ] **Step 1: 写买入、卖出、费用、T+1 和回滚测试**

```python
def test_buy_fill_updates_every_projection_in_one_transaction(db_session, open_buy_order, settlement) -> None:
    fill = settlement.apply(order_id=open_buy_order.id, execution=Execution(price=Decimal("10"), quantity=100), quote_timestamp=QUOTE_TIME, match_pass=1)
    assert fill.trade_id is not None
    assert db_session.query(Trade).filter_by(id=str(fill.trade_id)).one().type == TradeType.BUY
    assert db_session.query(Position).filter_by(ts_code=open_buy_order.ts_code).one().quantity == 100
    lot = db_session.query(PaperHoldingLot).one()
    assert lot.available_on == date(2026, 7, 21)
    assert db_session.query(PaperCashLedger).filter_by(fill_id=fill.id).count() >= 1
```

同一文件还必须写两个归属负例：用账户 A 的 `PaperFill` 尝试为账户 B 创建
`PaperHoldingLot`，以及用旧 generation 的 Fill 尝试写入新 generation 的批次，均应在
同一事务内失败且不留下 Fill、HoldingLot、Trade、Position 或 ledger 的部分投影。单列
`PaperHoldingLot.source_fill_id` 外键只能证明 Fill 存在，不能证明账户三元组一致，因此这两项
必须由结算服务显式校验。

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_settlement.py -q`

Expected: FAIL，缺少 settlement。

- [ ] **Step 3: 让 TradeService 接受稳定 ID**

```python
def create(self, *, user_id: str, ts_code: str, name: str, ttype: TradeType, quantity: int, price: Decimal, trade_date: date, note: str | None = None, trade_id: str | None = None) -> Trade:
    trade = Trade(
        id=trade_id or str(uuid4()), user_id=user_id, ts_code=ts_code,
        name=name, type=ttype, quantity=quantity, price=price,
        trade_date=trade_date, note=note,
    )
```

保持现有调用全部兼容；新增测试验证传入 id 被原样使用。

- [ ] **Step 4: 实现 SettlementService**

`PaperSettlementService.apply(*, order_id: UUID, execution: Execution, quote_timestamp: datetime, match_pass: int) -> PaperFill` 是唯一 public 结算入口。

方法按顺序锁 order/account → 插入 `PaperMatchPass` → 计算分项费用 → 插入 fill → 结算/解冻资金或 FIFO 批次 → 写 ledger → 用 `trade_id=str(uuid4())` 调 `TradeService.create()` → 更新 filled quantity/avg price/status。任何一步异常由调用方 rollback，禁止在服务内部 commit。

创建 `PaperHoldingLot` 前必须在锁和当前事务内读取 source `PaperFill` 及其 `PaperOrder`，原子验证
`order.account_id == lot.account_id`、`order.user_id == account.user_id`、
`order.account_generation == lot.generation == account.generation`。任一不一致都应拒绝并由调用方
整体 rollback；不得仅依赖 `source_fill_id` 外键。

- [ ] **Step 5: 运行结算与既有 Trade 回归**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_settlement.py backend/tests/unit/services/test_trade_service.py -q`

Expected: PASS。

- [ ] **Step 6: 提交结算**

```bash
git add backend/app/services/paper_trading/settlement.py backend/app/services/trade_service.py backend/tests/integration/paper_trading/test_settlement.py backend/tests/unit/services/test_trade_service.py
git commit -m "feat(paper): settle fills into trades and positions"
```

### Task 6: 实现撤单、收盘失效、开市转单和重置确认

**Files:**
- Modify: `backend/app/services/paper_trading/order_service.py`
- Test: `backend/tests/integration/paper_trading/test_order_terminal_actions.py`

- [ ] **Step 1: 写部分成交撤单和重置隔离测试**

```python
def test_cancel_releases_only_unfilled_reservation(db_session, partially_filled_order, service) -> None:
    before_filled = partially_filled_order.filled_quantity
    service.cancel_confirmed(user_id=partially_filled_order.user_id, order_id=partially_filled_order.id, confirmation_id="cancel-1")
    assert partially_filled_order.status == OrderStatus.CANCELLED
    assert partially_filled_order.filled_quantity == before_filled
    assert partially_filled_order.reserved_cash == Decimal("0")
```

- [ ] **Step 2: 运行并确认失败**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_terminal_actions.py -q`

Expected: FAIL，缺少 terminal action。

- [ ] **Step 3: 实现明确方法**

新增四个精确接口：`cancel_confirmed(*, user_id: UUID, order_id: UUID, confirmation_id: str) -> PaperOrder`、`expire_open_orders(*, at: datetime) -> int`、`open_queued_orders(*, at: datetime) -> int`、`reset_account_confirmed(*, user_id: UUID, initial_cash: Decimal, session_id: str, confirmation_id: str) -> PaperAccount`。

撤单/过期共用 `_release_remaining_reservation()`；重置先锁 active account，并拒绝存在 `processing` match pass 的账户，随后调用 foundation 的 `reset_confirmed()`。

- [ ] **Step 4: 运行终态测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_terminal_actions.py -q`

Expected: PASS。

- [ ] **Step 5: 提交终态动作**

```bash
git add backend/app/services/paper_trading/order_service.py backend/tests/integration/paper_trading/test_order_terminal_actions.py
git commit -m "feat(paper): cancel expire and reset orders safely"
```

### Task 7: 暴露订单 REST API 和用户隔离

**Files:**
- Modify: `backend/app/router/paper_trading_router.py`
- Modify: `backend/app/schemas/paper_trading.py`
- Test: `backend/tests/integration/paper_trading/test_order_endpoints.py`

- [ ] **Step 1: 写完整 endpoint 表测试**

覆盖：`GET /orders`、`GET /orders/{id}`、`GET /holdings`、`GET /fills`、`GET /cash-ledger`、`POST /orders/{id}/preview`、`POST /orders/{id}/confirm`、`POST /orders/{id}/cancel-preview`、`POST /orders/{id}/cancel-confirm`、`POST /account/reset-preview`、`POST /account/reset-confirm`。他人资源和不存在资源均断言 404；业务错误断言 `409 {code,message}`。读取接口默认限定 active generation，并提供显式 `generation` 查询历史。

- [ ] **Step 2: 运行并确认 endpoint 缺失**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_endpoints.py -q`

Expected: FAIL，缺少路由。

- [ ] **Step 3: 实现错误映射与端点**

```python
def _paper_error(exc: PaperTradingError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})

@router.post("/orders/{order_id}/confirm", response_model=PaperOrderRead)
async def confirm_order(order_id: UUID, payload: OrderConfirmRequest, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user_required)]) -> PaperOrderRead:
    try:
        order = _services(db).orders.confirm(user_id=user.id, order_id=order_id, draft=payload.draft, client_request_id=payload.client_request_id)
        db.commit()
        return PaperOrderRead.model_validate(order)
    except NoResultFound as exc:
        db.rollback()
        raise HTTPException(404, "Order not found") from exc
    except PaperTradingError as exc:
        db.rollback()
        raise _paper_error(exc) from exc
```

其余写端点遵循同一 commit/rollback 和归属隐藏模式。

- [ ] **Step 4: 运行 endpoint 测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_order_endpoints.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 REST API**

```bash
git add backend/app/router/paper_trading_router.py backend/app/schemas/paper_trading.py backend/tests/integration/paper_trading/test_order_endpoints.py
git commit -m "feat(paper): expose order confirmation APIs"
```

### Task 8: 接入 Celery 撮合与恢复

**Files:**
- Create: `backend/app/tasks/paper_trading.py`
- Modify: `backend/app/tasks/celery_app.py`
- Modify: `backend/app/tasks/celery_beat_schedule.py`
- Test: `backend/tests/unit/tasks/test_paper_trading_tasks.py`
- Test: `backend/tests/e2e/test_paper_order_worker.py`

- [ ] **Step 1: 写任务重投 exactly-once 测试**

```python
def test_match_order_redelivery_does_not_duplicate_fill(celery_worker_subprocess, db_session, open_order) -> None:
    first = match_order.delay(str(open_order.id), quote_timestamp=QUOTE_TIME.isoformat(), match_pass=1).get(timeout=15)
    second = match_order.delay(str(open_order.id), quote_timestamp=QUOTE_TIME.isoformat(), match_pass=1).get(timeout=15)
    assert first["fill_ids"] == second["fill_ids"]
    assert db_session.query(PaperFill).count() == 1
```

- [ ] **Step 2: 运行并确认任务不存在**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/tasks/test_paper_trading_tasks.py backend/tests/e2e/test_paper_order_worker.py -q`

Expected: FAIL，缺少 task。

- [ ] **Step 3: 实现四个幂等任务**

任务签名固定为：

- `match_order(order_id: str, quote_timestamp: str | None = None, match_pass: int | None = None) -> dict[str, object]`，task name `app.tasks.paper_trading.match_order` 且 `acks_late=True`；
- `open_queued_orders() -> int`，task name `app.tasks.paper_trading.open_queued_orders`；
- `expire_day_orders() -> int`，task name `app.tasks.paper_trading.expire_day_orders`；
- `release_t1_lots() -> int`，task name `app.tasks.paper_trading.release_t1_lots`。

`match_order` 先检查稳定 match key，再获取新鲜行情；没有可成交档位返回空结果而不是制造 fill。任务内部使用 `SessionLocal()`，成功 commit，异常 rollback 后重抛。

- [ ] **Step 4: 注册 include 和 beat**

`celery_app.py` include `app.tasks.paper_trading`；beat 使用 Asia/Shanghai：开市转单 09:30/13:00，收盘失效 15:01，T+1 释放 09:20，reconciliation 每 5 分钟。所有任务内部再次检查真实交易日/阶段，beat 的周一至周五表达式不是最终正确性来源。

- [ ] **Step 5: 运行任务测试**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/tasks/test_paper_trading_tasks.py backend/tests/e2e/test_paper_order_worker.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 worker**

```bash
git add backend/app/tasks/paper_trading.py backend/app/tasks/celery_app.py backend/app/tasks/celery_beat_schedule.py backend/tests/unit/tasks/test_paper_trading_tasks.py backend/tests/e2e/test_paper_order_worker.py
git commit -m "feat(paper): run idempotent matching tasks"
```

### Task 9: 添加 reconciliation、性质测试和故障注入

**Files:**
- Create: `backend/app/services/paper_trading/reconciliation.py`
- Create: `backend/tests/integration/paper_trading/test_reconciliation.py`
- Create: `backend/tests/integration/paper_trading/test_account_properties.py`
- Create: `backend/tests/integration/paper_trading/test_settlement_faults.py`

- [ ] **Step 1: 写六条恒等式和 suspended 测试**

测试逐条构造 available/frozen 负数、fill 超量、批次负数、lot 与 fill 不符、Fill/Trade/Position 不符、ledger 汇总不符；`reconcile_account()` 返回稳定 violation code 并把账户改为 `suspended`。

- [ ] **Step 2: 运行并确认缺少 reconciler**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_reconciliation.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现检查结果**

```python
class ReconciliationViolation(BaseModel):
    code: str
    account_id: UUID
    details: dict[str, object]

def reconcile_account(session: Session, account_id: UUID) -> list[ReconciliationViolation]:
    checks = (
        check_cash_non_negative, check_fill_quantity, check_lot_quantities,
        check_lots_against_fills, check_trade_position_projection, check_ledger_balance,
    )
    violations = [violation for check in checks for violation in check(session, account_id)]
    if violations:
        account = session.get(PaperAccount, account_id, with_for_update=True)
        account.status = PaperAccountStatus.SUSPENDED
        session.flush()
    return violations
```

只要 violations 非空，在同事务将 account.status 置 `suspended`；不得自动改账。

- [ ] **Step 4: 加 Hypothesis 序列性质测试**

生成 buy/sell/cancel/partial-fill 合法动作序列，固定 profile 和 seed；每一步调用 reconciler 并断言空 violations。失败输出动作序列。

- [ ] **Step 5: 加四个故障点回滚测试**

在冻结后、Fill insert 前、Trade create 前、commit 后回执前注入异常；前三者断言事务无半成品，最后一个重试断言幂等读取既有结果。

- [ ] **Step 6: 运行可靠性测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_reconciliation.py backend/tests/integration/paper_trading/test_account_properties.py backend/tests/integration/paper_trading/test_settlement_faults.py -q`

Expected: PASS。

- [ ] **Step 7: 提交可靠性守卫**

```bash
git add backend/app/services/paper_trading/reconciliation.py backend/tests/integration/paper_trading/test_reconciliation.py backend/tests/integration/paper_trading/test_account_properties.py backend/tests/integration/paper_trading/test_settlement_faults.py
git commit -m "test(paper): enforce account invariants and crash recovery"
```

### Task 9A: 增加订单链路 trace 和运行指标

**Files:**
- Create: `backend/app/services/paper_trading/observability.py`
- Modify: `backend/app/router/observability_router.py`
- Test: `backend/tests/integration/paper_trading/test_observability.py`

- [ ] **Step 1: 写 order id 串联和聚合指标测试**

构造 awaiting/queued/partial/rejected/stuck 订单后，断言聚合返回各状态数量、确认到首次处理耗时、确认到终态耗时、reject code 分布、幂等拦截次数和 reconciliation violation 数；trace spans 的 metadata 都含同一个 `order_id`。

- [ ] **Step 2: 运行并确认缺少聚合器**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_observability.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现无 PII 聚合和 span helper**

```python
def paper_order_span(*, order_id: UUID, name: str, started_at: datetime, ended_at: datetime, attrs: dict[str, object], error: str | None = None) -> Span:
    return Span(
        span_id=f"paper-{order_id}-{name}-{uuid4().hex[:8]}", request_id=str(order_id),
        parent_id=None, name=f"paper:{name}", inputs={}, outputs={},
        metadata={"order_id": str(order_id), **attrs},
        started_at=started_at, ended_at=ended_at, error=error,
    )
```

`GET /api/v0/observability/paper-trading` 只返回聚合数字，不返回 user id、股票或确认 payload。

- [ ] **Step 4: 运行测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/paper_trading/test_observability.py -q`

Expected: PASS。

```bash
git add backend/app/services/paper_trading/observability.py backend/app/router/observability_router.py backend/tests/integration/paper_trading/test_observability.py
git commit -m "feat(paper): trace order lifecycle and metrics"
```

### Task 10: 完成本计划验证

**Files:**
- Modify: `docs/Codex-context/` 中新增本阶段完成卡片，仅在实现确实落地后执行。

- [ ] **Step 1: 运行 paper trading 后端全套**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/paper_trading backend/tests/integration/paper_trading backend/tests/unit/tasks/test_paper_trading_tasks.py backend/tests/e2e/test_paper_order_worker.py -q`

Expected: 全部 PASS，无 xfail。

- [ ] **Step 2: 运行质量门**

Run: `uv run --frozen --extra dev ruff format --check backend/app backend/tests`

Run: `uv run --frozen --extra dev ruff check backend/app backend/tests`

Run: `uv run --frozen --extra dev mypy backend`

Expected: 三条命令 exit 0。

- [ ] **Step 3: 运行既有持仓和监控回归**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/test_trade_service.py backend/tests/unit/services/test_position_service.py backend/tests/unit/services/test_monitoring_scope.py backend/tests/e2e/test_monitoring_engine_e2e.py -q`

Expected: 全部 PASS。

- [ ] **Step 4: 提交阶段完成卡片**

```bash
git add docs/Codex-context
git commit -m "docs(context): record paper order matching"
```
