# Watchlist and Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加可由 Agent 直接增删改的自选股，并用默认关闭的 `monitoring_enabled` 与现有持仓共同决定监控范围。

**Architecture:** `WatchlistItem` 是正式数据源，REST 和 `ManageWatchlistTool` 共用同一个服务。自选写入不走确认卡，但必须审计；监控 scope 查询 `Position` 与启用监控的 watchlist 后按 `(user_id, ts_code)` 去重。Memory 只在独立 cold-start/rebuild 流程中派生，失败不回滚自选事务。

**Tech Stack:** Python/FastAPI/SQLAlchemy/PostgreSQL/ChatLoop、React/TypeScript/Ant Design、pytest/Vitest/Playwright

---

## 前置条件与文件边界

本计划可在 foundation 后实施；若与 Agent/UI 计划顺序执行，则复用已有 ChatLoop 和前端卡片基础设施，但自选写入不产生 approval。

- Create: `backend/app/models/watchlist.py` — 自选股与变更审计。
- Modify: `backend/app/models/__init__.py` — 注册模型。
- Create: `backend/app/services/watchlist_service.py` — CRUD、幂等和审计。
- Create: `backend/app/schemas/watchlist.py` — REST schema。
- Create: `backend/app/router/watchlist_router.py` — `/api/v0/watchlist`。
- Modify: `backend/app/app_main.py` — 注册 router。
- Create: `backend/app/chatloop/manage_watchlist_tool.py` — 直接执行的 in-process 工具。
- Modify: `backend/app/chatloop/worker_wiring.py`、`tool_docs.py`、`system_prompt.py` — 工具注册与权限说明。
- Modify: `backend/app/services/monitoring/scope.py` — Position + Watchlist union。
- Create: `frontend/src/api/watchlist.ts`、`frontend/src/pages/watchlist/index.tsx` — 自选页和可编辑开关。
- Modify: `frontend/src/router/routes.tsx`、`frontend/src/components/sidebar/nav-links.ts` — 页面入口。
- Create: backend/unit/integration/eval 与 frontend/Vitest/Playwright 测试。

### Task 1: 建立自选股和审计模型

**Files:**
- Create: `backend/app/models/watchlist.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/integration/watchlist/test_watchlist_models.py`

- [ ] **Step 1: 写默认关闭和用户内唯一测试**

```python
def test_monitoring_defaults_off_and_symbol_is_unique_per_user(db_session, user) -> None:
    item = WatchlistItem(user_id=user.id, ts_code="600519.SH", name="贵州茅台")
    db_session.add(item)
    db_session.flush()
    assert item.monitoring_enabled is False
    db_session.add(WatchlistItem(user_id=user.id, ts_code="600519.SH", name="贵州茅台"))
    with pytest.raises(IntegrityError):
        db_session.flush()
```

- [ ] **Step 2: 运行并确认缺模型**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/watchlist/test_watchlist_models.py -q`

Expected: FAIL，缺少 `WatchlistItem`。

- [ ] **Step 3: 实现模型**

```python
class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    ts_code = Column(String(10), nullable=False)
    name = Column(String(50), nullable=False)
    note = Column(Text, nullable=True)
    monitoring_enabled = Column(Boolean, nullable=False, default=False, server_default=false())
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    __table_args__ = (UniqueConstraint("user_id", "ts_code", name="uq_watchlist_user_tscode"),)
```

`WatchlistAudit` 保存 `item_id` 可空、`user_id`、`action`、`before_json`、`after_json`、`source_session_id`、`source_tool_call_id` 和时间戳。删除后 audit 仍保留，因此 `item_id` 使用 `ON DELETE SET NULL`。

- [ ] **Step 4: 导出并运行模型测试**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/watchlist/test_watchlist_models.py -q`

Expected: PASS。

- [ ] **Step 5: 提交模型**

```bash
git add backend/app/models/watchlist.py backend/app/models/__init__.py backend/tests/integration/watchlist/test_watchlist_models.py
git commit -m "feat(watchlist): add items and audit model"
```

### Task 2: 实现 CRUD、幂等和人话结果

**Files:**
- Create: `backend/app/services/watchlist_service.py`
- Test: `backend/tests/integration/watchlist/test_watchlist_service.py`

- [ ] **Step 1: 写重复 add、显式 update 和删除审计测试**

```python
def test_duplicate_add_is_idempotent_without_overwriting(db_session, user) -> None:
    service = WatchlistService(db_session)
    first = service.add(user_id=user.id, ts_code="600519.SH", name="贵州茅台", note="长期看", monitoring_enabled=False, source=SOURCE)
    second = service.add(user_id=user.id, ts_code="600519.SH", name="贵州茅台", note="覆盖尝试", monitoring_enabled=True, source=SOURCE)
    assert second.created is False
    assert second.item.id == first.item.id
    assert second.item.note == "长期看"
    assert second.item.monitoring_enabled is False

def test_remove_writes_before_snapshot(db_session, user) -> None:
    service = WatchlistService(db_session)
    service.add(user_id=user.id, ts_code="600519.SH", name="贵州茅台", note="长期看", source=SOURCE)
    service.remove(user_id=user.id, ts_code="600519.SH", source=SOURCE)
    audit = db_session.query(WatchlistAudit).filter_by(action="remove").one()
    assert audit.before_json["ts_code"] == "600519.SH"
```

- [ ] **Step 2: 运行并确认缺服务**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/watchlist/test_watchlist_service.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现清晰方法签名**

```python
class ChangeSource(BaseModel):
    session_id: str | None = None
    tool_call_id: str | None = None

class AddResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    item: WatchlistItem
    created: bool

class WatchlistService:
    """实现以下 public 接口，所有写方法同时写 WatchlistAudit 并 flush。"""
```

精确接口为 `list(*, user_id: UUID) -> list[WatchlistItem]`、`add(*, user_id: UUID, ts_code: str, name: str, note: str | None, monitoring_enabled: bool = False, source: ChangeSource) -> AddResult`、`update(*, user_id: UUID, ts_code: str, changes: dict[str, object], source: ChangeSource) -> WatchlistItem`、`remove(*, user_id: UUID, ts_code: str, source: ChangeSource) -> None`。

`update()` 仅允许 `name/note/monitoring_enabled`，空 changes 返回原值；不存在资源抛 `NoResultFound`。所有方法只 flush，不 commit。

- [ ] **Step 4: 运行服务测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/watchlist/test_watchlist_service.py -q`

Expected: PASS。

```bash
git add backend/app/services/watchlist_service.py backend/tests/integration/watchlist/test_watchlist_service.py
git commit -m "feat(watchlist): add audited CRUD service"
```

### Task 3: 暴露直接写入 REST API

**Files:**
- Create: `backend/app/schemas/watchlist.py`
- Create: `backend/app/router/watchlist_router.py`
- Modify: `backend/app/app_main.py`
- Test: `backend/tests/integration/watchlist/test_watchlist_endpoints.py`

- [ ] **Step 1: 写 CRUD、默认开关和 404 隔离测试**

```python
def test_post_watchlist_executes_immediately_without_approval(client) -> None:
    response = client.post("/api/v0/watchlist", json={"ts_code": "600519.SH", "name": "贵州茅台"})
    assert response.status_code == 201
    assert response.json()["monitoring_enabled"] is False
    assert "approval" not in response.json()
```

- [ ] **Step 2: 运行并确认 404**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/watchlist/test_watchlist_endpoints.py -q`

Expected: FAIL，路由不存在。

- [ ] **Step 3: 实现 schema 和四个端点**

```python
class WatchlistCreate(BaseModel):
    ts_code: str
    name: str
    note: str | None = None
    monitoring_enabled: bool = False

class WatchlistUpdate(BaseModel):
    name: str | None = None
    note: str | None = None
    monitoring_enabled: bool | None = None

class WatchlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    ts_code: str
    name: str
    note: str | None
    monitoring_enabled: bool
```

Router prefix `/api/v0/watchlist`：GET list、POST add、PATCH `/{ts_code}`、DELETE `/{ts_code}`。每个写端点直接 commit；跨用户和不存在统一 404；重复 POST 返回 200 与既有记录，不覆盖字段。

- [ ] **Step 4: 注册 router、运行测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/integration/watchlist/test_watchlist_endpoints.py -q`

Expected: PASS。

```bash
git add backend/app/schemas/watchlist.py backend/app/router/watchlist_router.py backend/app/app_main.py backend/tests/integration/watchlist/test_watchlist_endpoints.py
git commit -m "feat(watchlist): expose direct CRUD APIs"
```

### Task 4: 实现 Agent 直接写工具

**Files:**
- Create: `backend/app/chatloop/manage_watchlist_tool.py`
- Modify: `backend/app/chatloop/worker_wiring.py`
- Modify: `backend/app/chatloop/tool_docs.py`
- Modify: `backend/app/chatloop/system_prompt.py`
- Test: `backend/tests/unit/chatloop/test_manage_watchlist_tool.py`
- Test: `backend/tests/unit/chatloop/test_worker_wiring_watchlist.py`

- [ ] **Step 1: 写直接执行、默认 false 和无 approval 测试**

```python
@pytest.mark.asyncio
async def test_add_executes_immediately_and_returns_no_approval(state, deps) -> None:
    result = await ManageWatchlistTool(deps).run_with_state(
        ManageWatchlistArgs(action="add", ts_code="600519.SH", name="贵州茅台"), state,
    )
    assert result["changed"] is True
    assert result["item"]["monitoring_enabled"] is False
    assert "approval" not in result
```

- [ ] **Step 2: 运行并确认工具缺失**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/chatloop/test_manage_watchlist_tool.py backend/tests/unit/chatloop/test_worker_wiring_watchlist.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 action schema**

```python
class ManageWatchlistArgs(BaseModel):
    action: Literal["list", "add", "update", "remove"]
    ts_code: str | None = None
    name: str | None = None
    note: str | None = None
    monitoring_enabled: bool | None = None

class ManageWatchlistTool(InProcessTool):
    name = "manage_watchlist"
    description = "直接查询、添加、修改或删除用户自选股；写入立即执行，不需要确认。"
    args_schema = ManageWatchlistArgs
```

工具从 state 注入 user/session/request id，使用 async session，并在成功写入后 commit。add 未传 monitoring 时明确使用 false；remove 后若仍有 Position，返回 `monitoring_note="自选监控已关闭，但持仓监控仍在运行"`。

- [ ] **Step 4: 注册为 core 工具并写 prompt**

prompt 明确：自选 CRUD 可直接执行；模拟买卖仍必须 paper_trade + 确认卡，两者不得混淆。`ToolHub` 对 InProcessTool 已绕过缓存/同 turn 去重，不额外增加缓存。

- [ ] **Step 5: 运行测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/chatloop/test_manage_watchlist_tool.py backend/tests/unit/chatloop/test_worker_wiring_watchlist.py -q`

Expected: PASS。

```bash
git add backend/app/chatloop/manage_watchlist_tool.py backend/app/chatloop/worker_wiring.py backend/app/chatloop/tool_docs.py backend/app/chatloop/system_prompt.py backend/tests/unit/chatloop/test_manage_watchlist_tool.py backend/tests/unit/chatloop/test_worker_wiring_watchlist.py
git commit -m "feat(chat): manage watchlist directly through agent"
```

### Task 5: 合并监控范围并去重

**Files:**
- Modify: `backend/app/services/monitoring/scope.py`
- Modify: `backend/tests/unit/services/test_monitoring_scope.py`
- Test: `backend/tests/integration/watchlist/test_monitoring_scope_union.py`

- [ ] **Step 1: 写四种 scope 组合测试**

```python
def test_scope_is_union_of_positions_and_enabled_watchlist(db_session, user) -> None:
    add_position(user, "600519.SH", quantity=100, silenced=False)
    add_watchlist(user, "600519.SH", monitoring=True)
    add_watchlist(user, "000001.SZ", monitoring=True)
    add_watchlist(user, "300750.SZ", monitoring=False)
    subjects = load_active_subjects(db_session)
    assert [(s.ts_code, s.sources) for s in subjects] == [
        ("000001.SZ", {"watchlist"}),
        ("600519.SH", {"position", "watchlist"}),
    ]
```

另测：静默 Position + enabled watchlist 仍由 watchlist 进入；删除 watchlist 但有非静默 Position 仍保留；两者都无则退出。

- [ ] **Step 2: 运行并确认现有实现只返回 Position**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/test_monitoring_scope.py backend/tests/integration/watchlist/test_monitoring_scope_union.py -q`

Expected: 新 union case FAIL。

- [ ] **Step 3: 扩展 subject 来源并用 SQL union 去重**

```python
class MonitoringSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    ts_code: str
    name: str
    sources: frozenset[Literal["position", "watchlist"]]
```

实现可以用两个小查询后在 Python dict 合并，key 为 `(str(user_id), ts_code)`；Position 条件 `quantity > 0 AND is_silenced = false`，Watchlist 条件 `monitoring_enabled = true`。同 key 名称优先 Position，sources 合并。

- [ ] **Step 4: 运行 scope 与 monitoring e2e**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/services/test_monitoring_scope.py backend/tests/integration/watchlist/test_monitoring_scope_union.py backend/tests/e2e/test_monitoring_engine_e2e.py -q`

Expected: PASS，每只股票一个 detection run。

- [ ] **Step 5: 提交 scope**

```bash
git add backend/app/services/monitoring/scope.py backend/tests/unit/services/test_monitoring_scope.py backend/tests/integration/watchlist/test_monitoring_scope_union.py
git commit -m "feat(monitoring): union positions and enabled watchlist"
```

### Task 6: 派生 Memory WATCHES 关系但不阻塞事务

**Files:**
- Modify: `backend/app/memory/cold_start.py`
- Test: `backend/tests/unit/memory/test_cold_start_watchlist.py`

- [ ] **Step 1: 写 memory 失败不回滚自选测试**

```python
def test_watchlist_write_does_not_call_memory(db_session, user, monkeypatch) -> None:
    memory_call = Mock(side_effect=RuntimeError("memory down"))
    monkeypatch.setattr("app.memory.cold_start.seed_user_graph", memory_call)
    WatchlistService(db_session).add(user_id=user.id, ts_code="600519.SH", name="贵州茅台", note=None, source=ChangeSource(session_id="s1"))
    db_session.commit()
    assert db_session.query(WatchlistItem).count() == 1
    memory_call.assert_not_called()
```

- [ ] **Step 2: 运行并确认缺 task**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/memory/test_cold_start_watchlist.py -q`

Expected: FAIL。

- [ ] **Step 3: 在 cold start 中从正式表派生 WATCHES**

扩展现有 `seed_user_graph()`：查询 `WatchlistItem`，为每条记录幂等 get-or-create Stock node，并用现有 `pg_insert(ChatMemoryEdge).on_conflict_do_nothing(constraint="uq_edges_idempotency_key")` 插入 `WATCHES` edge。edge properties 保存 `monitoring_enabled`，reasoning 固定为 `cold start from watchlist_items table`。自选 CRUD 不调用 memory；派生只发生在独立 cold start/rebuild 流程，所以 memory 失败天然不会回滚自选事务。

- [ ] **Step 4: 运行测试并提交**

Run: `uv run --frozen --extra dev pytest backend/tests/unit/memory/test_cold_start_watchlist.py -q`

Expected: PASS。

```bash
git add backend/app/memory/cold_start.py backend/tests/unit/memory/test_cold_start_watchlist.py
git commit -m "feat(memory): seed WATCHES from watchlist source"
```

### Task 7: 实现自选股页面和可编辑监控开关

**Files:**
- Create: `frontend/src/api/watchlist.ts`
- Create: `frontend/src/pages/watchlist/index.tsx`
- Create: `frontend/src/pages/watchlist/index.module.scss`
- Modify: `frontend/src/router/routes.tsx`
- Modify: `frontend/src/components/sidebar/nav-links.ts`
- Test: `frontend/src/api/__tests__/watchlist.test.ts`
- Test: `frontend/src/pages/watchlist/__tests__/index.test.tsx`

- [ ] **Step 1: 写默认关闭、直接保存和持仓提示测试**

```typescript
it('adds with monitoring off and saves edits without confirmation', async () => {
  const user = userEvent.setup()
  render(<WatchlistPage />)
  await user.click(screen.getByRole('button', { name: '添加自选' }))
  expect(createWatchlistItem).toHaveBeenCalledWith(expect.objectContaining({ monitoring_enabled: false }))
  await user.click(screen.getByRole('switch', { name: '贵州茅台监控' }))
  expect(updateWatchlistItem).toHaveBeenCalledWith('600519.SH', { monitoring_enabled: true })
  expect(screen.queryByText('确认')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: 运行并确认模块缺失**

Run: `npm --prefix frontend test -- --run src/api/__tests__/watchlist.test.ts src/pages/watchlist/__tests__/index.test.tsx`

Expected: FAIL。

- [ ] **Step 3: 实现 API 和页面**

API 导出 `listWatchlist/createWatchlistItem/updateWatchlistItem/deleteWatchlistItem`。页面表格列：代码、名称、备注、监控 switch、最新状态、操作；名称和备注 inline edit，保存直接 PATCH；删除直接 DELETE。若响应带 `monitoring_note`，用 info alert 显示“自选监控已关闭，但持仓监控仍在运行”。

- [ ] **Step 4: 注册 `/watchlist` 路由和“自选股”导航**

```tsx
{ path: '/watchlist', Component: WatchlistPage }
```

- [ ] **Step 5: 运行测试并提交**

Run: `npm --prefix frontend test -- --run src/api/__tests__/watchlist.test.ts src/pages/watchlist/__tests__/index.test.tsx src/router/__tests__/routes.test.tsx`

Expected: PASS。

```bash
git add frontend/src/api/watchlist.ts frontend/src/pages/watchlist frontend/src/router/routes.tsx frontend/src/components/sidebar/nav-links.ts frontend/src/api/__tests__/watchlist.test.ts frontend/src/router/__tests__/routes.test.tsx
git commit -m "feat(frontend): add editable watchlist page"
```

### Task 8: Agent 评估、浏览器链路与完成验证

**Files:**
- Create: `backend/eval/chatloop/golden/watchlist.jsonl`
- Create: `backend/tests/eval/chatloop/test_watchlist_scenarios.py`
- Create: `frontend/tests/e2e/watchlist-monitoring.spec.ts`
- Modify: `docs/Codex-context/` 中新增本阶段完成卡片，仅在实现确实落地后执行。

- [ ] **Step 1: 写 Agent golden cases**

覆盖：添加直接执行且默认 false、显式“加入并监控”写 true、修改备注、关闭监控、删除、只问“这股票怎么样”不得写、自选与买入不得混淆、同 turn 重复 add 不覆盖备注。评分同时检查工具 trace 和数据库终态。

- [ ] **Step 2: 运行评估测试**

Run: `uv run --frozen --extra dev pytest backend/tests/eval/chatloop/test_watchlist_scenarios.py -q`

Expected: PASS。

- [ ] **Step 3: 写并运行浏览器链路**

Playwright：Chat 输入“把茅台加自选” → 不出现确认卡 → 打开自选页看到 switch 关闭 → 编辑备注 → 开启监控 → 监控页出现 subject → 关闭监控但保留模拟持仓 → 页面显示持仓监控仍运行 → 删除自选 → 持仓监控仍存在。

Run: `npm --prefix frontend run test:e2e -- watchlist-monitoring.spec.ts`

Expected: PASS。

- [ ] **Step 4: 运行全量质量门**

Run: `uv run --frozen --extra dev ruff format --check .`

Run: `uv run --frozen --extra dev ruff check .`

Run: `uv run --frozen --extra dev mypy backend`

Run: `uv run --frozen --extra dev pytest -q`

Run: `npm --prefix frontend test -- --run`

Run: `npm --prefix frontend run lint`

Run: `npm --prefix frontend run build`

Expected: 所有命令 exit 0，CI 对应检查真绿。

- [ ] **Step 5: 提交 e2e 与完成卡片**

```bash
git add backend/eval/chatloop/golden/watchlist.jsonl backend/tests/eval/chatloop/test_watchlist_scenarios.py frontend/tests/e2e/watchlist-monitoring.spec.ts docs/Codex-context
git commit -m "test(watchlist): verify monitoring integration"
```
