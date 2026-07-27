# Agent Market Permission Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the chat Agent enforce market permissions before paper-trading writes, return a durable `action_required` result when permission is missing, and safely continue only in a new Run.

**Architecture:** Add read-only in-process tools over the suitability service and a local control tool that records a validated required action in chat state. Enforce permission again inside the paper-order service so tool-selection mistakes cannot bypass it. Finalization copies the local action into the completed Run outcome; evaluations assert both the tool trajectory and durable database outcome.

**Tech Stack:** Existing Python chat loop, unified tool runtime, SQLAlchemy/PostgreSQL, pytest, golden-case eval harness, React Run client from the preceding plan.

---

## Prerequisites

Complete and verify these plans first:

1. `docs/superpowers/plans/2026-07-27-investor-suitability-foundation.md`
2. `docs/superpowers/plans/2026-07-27-action-required-run-outcome.md`

## File map

- Create `backend/app/chatloop/market_permission_tools.py`: read-only permission query, order eligibility, and application-link tools.
- Modify `backend/app/chatloop/state.py`: local validated required-action field.
- Modify `backend/app/chatloop/run_executor.py`: copy required action into terminal outcome.
- Modify `backend/app/chatloop/worker_wiring.py`: register tools with user/account-scoped backends.
- Modify `backend/app/chatloop/tool_docs.py` and `system_prompt.py`: discovery and behavior guidance.
- Modify `backend/app/chatloop/tool_runtime_policy.py`: mark all three tools low-risk/read-only.
- Modify `backend/app/services/paper_trading/order_service.py`: fail-closed entitlement enforcement before preview/confirm.
- Extend unit, integration, e2e and golden-case tests.

### Task 1: Classify stock boards deterministically

**Files:**
- Create: `backend/app/services/investor_suitability/instruments.py`
- Modify: `backend/app/services/paper_trading/order_service.py`
- Modify: `backend/app/services/paper_trading/quote_provider.py`
- Modify: `backend/app/services/paper_trading/rules/a_share_20260706.json`
- Modify: `backend/app/router/paper_trading_router.py`
- Test: `backend/tests/unit/services/investor_suitability/test_instruments.py`
- Test: `backend/tests/unit/services/paper_trading/test_rulebook.py`
- Test: `backend/tests/unit/services/paper_trading/test_quote_provider.py`

- [ ] **Step 1: Write failing classification tests**

```python
@pytest.mark.parametrize(
    ("ts_code", "market"),
    [
        ("600000.SH", Market.MAIN),
        ("000001.SZ", Market.MAIN),
        ("300750.SZ", Market.CHINEXT),
        ("688981.SH", Market.STAR),
        ("920001.BJ", Market.BSE),
    ],
)
def test_classify_supported_a_share_boards(ts_code, market):
    assert classify_market(ts_code) is market
```

Add rejection tests for unknown suffixes and ambiguous/non-stock codes. Use the repository's actual Tushare/BSE code format; if current data uses a different BSE suffix, update the fixture and tests together before implementation.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/unit/services/investor_suitability/test_instruments.py -q`

Expected: FAIL because `classify_market` does not exist.

- [ ] **Step 3: Implement a pure classifier**

```python
def classify_market(ts_code: str) -> Market:
    code, suffix = ts_code.split(".", maxsplit=1)
    if suffix == "SH" and code.startswith("688"):
        return Market.STAR
    if suffix == "SZ" and code.startswith(("300", "301")):
        return Market.CHINEXT
    if suffix == "BJ":
        return Market.BSE
    if suffix in {"SH", "SZ"} and len(code) == 6 and code.isascii() and code.isdecimal():
        return Market.MAIN
    raise SuitabilityError("unsupported_instrument_market", "无法识别证券所属交易市场")
```

Use this classifier from the existing paper-order `_board` path rather than maintaining a second prefix table. Widen validated stock-code patterns from `SH|SZ` to `SH|SZ|BJ`, add a `bse` board to the versioned paper-trading rule fixture with a 30% normal price limit, 0.01 price tick and minimum 100-share order, and add the current official BSE rule URL to the fixture sources. Split the existing global `buy_lot_size` into `minimum_order_quantity` and `quantity_increment`:沪深普通股票 use `100/100`, while BSE uses `100/1`; preserve the existing “sell the entire odd-lot remainder” rule. Keep unsupported no-price-limit listing-day regimes fail-closed.

Add this BSE quantity test before implementation:

```python
def test_bse_accepts_101_shares_but_rejects_below_100(rulebook):
    rules = rulebook.resolve(ts_code="920001.BJ", board="bse", risk_warning=False, side="buy", on=DATE)
    rulebook.validate_quantity(rules, 101)
    with pytest.raises(PaperTradingError) as exc:
        rulebook.validate_quantity(rules, 99)
    assert exc.value.code == "invalid_lot_size"
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest backend/tests/unit/services/investor_suitability/test_instruments.py backend/tests/unit/services/paper_trading/test_rulebook.py backend/tests/unit/services/paper_trading/test_quote_provider.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/investor_suitability/instruments.py backend/app/services/paper_trading/order_service.py backend/app/services/paper_trading/quote_provider.py backend/app/services/paper_trading/rules/a_share_20260706.json backend/app/router/paper_trading_router.py backend/tests/unit/services/investor_suitability/test_instruments.py backend/tests/unit/services/paper_trading/test_rulebook.py backend/tests/unit/services/paper_trading/test_quote_provider.py
git commit -m "feat(suitability): classify A-share market permissions"
```

### Task 2: Enforce entitlements inside paper-order services

**Files:**
- Modify: `backend/app/services/paper_trading/order_service.py`
- Modify: `backend/app/services/paper_trading/errors.py`
- Test: `backend/tests/integration/paper_trading/test_order_permission_gate.py`

- [ ] **Step 1: Write failing service-level bypass tests**

```python
def test_preview_rejects_buy_without_required_market_permission(order_service, star_quote, user_id):
    with pytest.raises(PaperTradingError) as exc:
        order_service.preview_draft(user_id=user_id, draft=buy_draft("688981.SH"))
    assert exc.value.code == "market_permission_required"


def test_restricted_permission_allows_sell_but_blocks_buy(order_service, restricted_star_entitlement, star_holding):
    assert order_service.preview_draft(user_id=star_holding.user_id, draft=sell_draft("688981.SH"))
    with pytest.raises(PaperTradingError, match="market permission"):
        order_service.preview_draft(user_id=star_holding.user_id, draft=buy_draft("688981.SH"))
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/integration/paper_trading/test_order_permission_gate.py -q`

Expected: FAIL because direct service calls bypass market permissions.

- [ ] **Step 3: Add a fail-closed eligibility dependency**

```python
class PaperOrderService:
    def __init__(..., entitlement_reader: EntitlementReader, ...):
        self.entitlement_reader = entitlement_reader

    def _require_market_permission(self, *, user_id: UUID, draft: OrderDraft) -> None:
        market = classify_market(draft.ts_code)
        permission = self.entitlement_reader.current(user_id=user_id, market=market)
        allowed = permission.can_buy if draft.side is OrderSide.BUY else permission.can_sell
        if not allowed:
            raise PaperTradingError(
                "market_permission_required",
                f"{market.value} permission is required for this order",
            )
```

Call the gate in both preview and confirmation under the same account lock. Missing records, reader failures and unknown markets must reject. Existing holdings can still be sold when `can_sell=True` and `can_buy=False`.

- [ ] **Step 4: Run all paper-order suites**

Run: `uv run pytest backend/tests/integration/paper_trading backend/tests/unit/chatloop/test_paper_trade_tools.py -q`

Expected: PASS after fixtures explicitly seed main-board permissions where needed; do not add a permissive production default to keep old tests green.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/paper_trading/order_service.py backend/app/services/paper_trading/errors.py backend/tests/integration/paper_trading/test_order_permission_gate.py
git commit -m "feat(paper): enforce market permissions before orders"
```

### Task 3: Add read-only Agent permission tools

**Files:**
- Create: `backend/app/chatloop/market_permission_tools.py`
- Modify: `backend/app/chatloop/worker_wiring.py`
- Modify: `backend/app/chatloop/tool_runtime_policy.py`
- Test: `backend/tests/unit/chatloop/test_market_permission_tools.py`

- [ ] **Step 1: Write failing tool tests**

```python
async def test_check_order_eligibility_returns_action_without_mutating_db(tool, state, context):
    result = await tool.run_with_context(
        CheckOrderEligibilityArgs(ts_code="688981.SH", side="buy"), state, context
    )
    assert result["allowed"] is False
    assert result["required_permission"] == "star"
    assert result["application_url"] == "/market-permissions/star/apply"
    assert database_writes() == []
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/unit/chatloop/test_market_permission_tools.py -q`

Expected: FAIL because the tools do not exist.

- [ ] **Step 3: Implement three context-bound tools**

```python
class GetMarketEntitlementsTool(InProcessTool):
    name = "get_market_entitlements"
    args_schema = EmptyArgs

class CheckOrderEligibilityTool(InProcessTool):
    name = "check_order_eligibility"
    args_schema = CheckOrderEligibilityArgs

class GetEntitlementApplicationLinkTool(InProcessTool):
    name = "get_entitlement_application_link"
    args_schema = ApplicationLinkArgs
```

Each tool must derive the user from `ExecutionContext`, verify it matches `ChatLoopState.user_id`, use the active paper account from the database, and expose no method that updates profiles, signs disclosures or enables permissions. Register all three as `LOW`, `read_only=True`, `idempotent=True`.

- [ ] **Step 4: Run tool and wiring tests**

Run: `uv run pytest backend/tests/unit/chatloop/test_market_permission_tools.py backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/chatloop/market_permission_tools.py backend/app/chatloop/worker_wiring.py backend/app/chatloop/tool_runtime_policy.py backend/tests/unit/chatloop/test_market_permission_tools.py backend/tests/unit/chatloop/test_worker_wiring_paper_trade.py
git commit -m "feat(agent): add read-only market permission tools"
```

### Task 4: Convert missing permission into terminal action_required

**Files:**
- Modify: `backend/app/chatloop/state.py`
- Modify: `backend/app/chatloop/market_permission_tools.py`
- Modify: `backend/app/chatloop/run_executor.py`
- Test: `backend/tests/unit/chatloop/test_run_executor.py`

- [ ] **Step 1: Write failing executor tests**

```python
async def test_permission_link_finishes_with_action_required(scripted_executor):
    result = await scripted_executor.run(
        steps=[
            tool_call("check_order_eligibility", {"ts_code": "688981.SH", "side": "buy"}),
            tool_call("get_entitlement_application_link", {"market": "star", "intent_summary": "买入中芯国际 100 股"}),
            final("当前账户未开通科创板权限。"),
        ]
    )
    assert isinstance(result, CompletedResult)
    assert result.outcome is not None
    assert result.outcome.action_url == "/market-permissions/star/apply"
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/unit/chatloop/test_run_executor.py -k action_required -q`

Expected: FAIL because chat state cannot carry a required action.

- [ ] **Step 3: Add local control state and finalization**

```python
class ChatLoopState(BaseModel):
    # existing fields remain
    required_action: ActionRequiredOutcome | None = None
```

`GetEntitlementApplicationLinkTool.run_with_state` validates the market and sets `state.required_action`; it performs no external write. `RunExecutor` copies `state.required_action` into `CompletedResult.outcome`. Starting a new Run creates fresh state, so old actions cannot leak forward.

- [ ] **Step 4: Run executor tests**

Run: `uv run pytest backend/tests/unit/chatloop/test_run_executor.py backend/tests/integration/test_run_chat_worker_pg.py -q`

Expected: PASS; permission requests complete rather than pause.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/chatloop/state.py backend/app/chatloop/market_permission_tools.py backend/app/chatloop/run_executor.py backend/tests/unit/chatloop/test_run_executor.py
git commit -m "feat(agent): finish permission blocks with user action"
```

### Task 5: Teach progressive disclosure and the system prompt

**Files:**
- Modify: `backend/app/chatloop/tool_docs.py`
- Modify: `backend/app/chatloop/system_prompt.py`
- Test: `backend/tests/unit/chatloop/test_progressive_disclosure.py`

- [ ] **Step 1: Write failing discovery tests**

```python
def test_paper_order_flow_discovers_permission_tools_before_write():
    visible = discover_tools("帮我买 100 股中芯国际")
    assert "check_order_eligibility" in visible
    assert "place_paper_order" in visible
    assert "enable_market_entitlement" not in visible
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/unit/chatloop/test_progressive_disclosure.py -k permission -q`

Expected: FAIL because docs/catalog entries are absent.

- [ ] **Step 3: Add concise tool guidance**

```python
"check_order_eligibility": ToolDoc(
    name="check_order_eligibility",
    summary="下模拟订单前检查市场权限；结果由规则代码决定。",
    detail="权限不足时不要调用下单工具；获取申请链接并结束本轮。",
),
```

The system prompt must say: never claim to open permissions, never ask for approval to call a permission-writing tool, never auto-place the old order after external application, and always recheck on the user's new turn.

- [ ] **Step 4: Run disclosure and prompt tests**

Run: `uv run pytest backend/tests/unit/chatloop/test_progressive_disclosure.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/chatloop/tool_docs.py backend/app/chatloop/system_prompt.py backend/tests/unit/chatloop/test_progressive_disclosure.py
git commit -m "feat(agent): guide permission-aware order routing"
```

### Task 6: Add durable eval scenarios and outcome scoring

**Files:**
- Create: `backend/eval/chatloop/golden/market_permissions.jsonl`
- Modify: `backend/eval/chatloop/scenario.py`
- Modify: `backend/eval/chatloop/scorers.py`
- Modify: `backend/eval/chatloop/sut_runner.py`
- Test: `backend/tests/unit/eval/chatloop/test_market_permission_scenarios.py`
- Test: `backend/tests/integration/eval/chatloop/test_outcome_collector_pg.py`

- [ ] **Step 1: Add failing scenario tests**

```python
def test_missing_permission_requires_link_and_forbids_order_write(score_scenario):
    result = score_scenario("star_permission_missing")
    assert result.required_tools == {"check_order_eligibility", "get_entitlement_application_link"}
    assert "place_paper_order" in result.forbidden_tools
    assert result.expected_outcome == "action_required"
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest backend/tests/unit/eval/chatloop/test_market_permission_scenarios.py -q`

Expected: FAIL because the scenario and outcome scorer do not exist.

- [ ] **Step 3: Add five golden cases**

Include: main permission present; STAR missing; ChiNext missing; restricted buy with allowed sell; user returns after permission and must recheck. Score every durable tool call, forbidden writes, terminal Run outcome, action URL, and final database state.

```json
{"id":"star_permission_missing","input":"买入中芯国际100股","expected":{"required_tools":["check_order_eligibility","get_entitlement_application_link"],"forbidden_tools":["place_paper_order"],"run_status":"completed","outcome":"action_required","action_url":"/market-permissions/star/apply"}}
```

- [ ] **Step 4: Run eval unit and durable outcome tests**

Run: `uv run pytest backend/tests/unit/eval/chatloop/test_market_permission_scenarios.py backend/tests/integration/eval/chatloop/test_outcome_collector_pg.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/eval/chatloop/golden/market_permissions.jsonl backend/eval/chatloop/scenario.py backend/eval/chatloop/scorers.py backend/eval/chatloop/sut_runner.py backend/tests/unit/eval/chatloop/test_market_permission_scenarios.py backend/tests/integration/eval/chatloop/test_outcome_collector_pg.py
git commit -m "test(eval): cover market permission outcomes"
```

### Task 7: Verify the complete boundary end to end

**Files:**
- Create: `backend/tests/e2e/test_market_permission_agent.py`
- Modify: `frontend/tests/e2e/action-required.spec.ts`
- Modify: `docs/claude-context/paper-trading-runtime-adaptation-done.md`

- [ ] **Step 1: Add a real database end-to-end test**

```python
def test_agent_permission_link_application_and_new_run(client, worker, user):
    first = run_chat(client, user, "买入中芯国际100股")
    assert first.status == "completed"
    assert first.outcome.code == "action_required"
    assert paper_orders(user) == []

    complete_permission_application(client, user, market="star")
    second = run_chat(client, user, "我已完成申请，请重新检查并继续买入中芯国际100股")
    assert second.id != first.id
    assert second.pause_type == "approval"
```

- [ ] **Step 2: Run focused backend verification**

Run: `uv run pytest backend/tests/e2e/test_market_permission_agent.py backend/tests/integration/paper_trading/test_order_permission_gate.py backend/tests/unit/eval/chatloop/test_market_permission_scenarios.py -q`

Expected: PASS with no paper order before the second Run's explicit approval.

- [ ] **Step 3: Run frontend journey**

Run: `npx playwright test tests/e2e/action-required.spec.ts tests/e2e/market-permissions.spec.ts`

Workdir: `frontend`

Expected: PASS; if the Windows browser environment blocks execution, record the exact command and error.

- [ ] **Step 4: Run static gates**

Run: `uv run ruff check backend/app backend/tests && uv run mypy backend/app`

Run: `npm run lint && npm run build`

Workdir for npm commands: `frontend`

Expected: all PASS.

- [ ] **Step 5: Record only verified evidence and commit**

```powershell
git add backend/tests/e2e/test_market_permission_agent.py frontend/tests/e2e/action-required.spec.ts docs/claude-context/paper-trading-runtime-adaptation-done.md
git commit -m "test: verify permission-aware Agent trading"
```
