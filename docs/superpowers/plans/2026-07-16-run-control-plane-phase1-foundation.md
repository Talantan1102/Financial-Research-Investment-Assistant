# Run Control Plane Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 Tenant、Session、Run、Attempt、Pause、Event 的 PostgreSQL 数据骨架和六个 `/api/v1` Run API，使请求能可靠创建、查询、取消和恢复，但本卷不执行模型。

**Architecture:** 新控制面使用独立 `run_*` 表，不读写旧 `chat_tasks`。FastAPI 只调用 `RunService`；服务使用一个 AsyncSession 事务完成鉴权、配额、消息、Run 和 Event 写入。PostgreSQL 唯一约束、部分索引和事务锁守住幂等创建与同 Session 单非终态 Run。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2.x async、PostgreSQL、pytest、Docker Compose、ruff、mypy。

## Global Constraints

- PostgreSQL 是唯一事实源；本卷不引入 Redis、Scheduler、Dispatcher 或 Worker 行为。
- 只有 `run_type="chat"`；Run 输入创建后不可修改。
- 同一 Session 最多一个非终态 Run：`queued/assigned/running/waiting_approval/waiting_input/cancel_requested`。
- `POST /runs` 必须携带 `Idempotency-Key`；同一 Tenant、用户、key 和请求摘要返回同一个 Run；同 key 不同请求返回 409。
- Prompt 修订创建新 Run；`replaces_run_id` 只指向直接上一版本。
- `resume` 只接受 waiting 状态；Prompt 修改不能走 resume。
- 查询同时过滤 `tenant_id` 和成员权限；越权资源返回 404，避免 IDOR 探测。
- 固定角色只有 `owner/admin/member`；owner/admin 可看租户范围，member 只看自己的 Run。
- 第一卷不删除旧 ChatTask 路径；第三卷切换时一次删除。
- 新 schema 只增加新表，通过现有 `Base.metadata.create_all()` 注册；本卷不引入 Alembic。
- 测试使用现有真 PostgreSQL fixture；命令先设置 `$env:POSTGRES_PASSWORD='postgres123'`。

## Plan Boundary

总设计拆为四卷：本卷 Run 数据骨架；第二卷调度控制面；第三卷真实 Chat 接入和旧路径删除；第四卷人工交互与故障收束。本卷验收时 Run 停留在 `queued`；测试 FakeRunExecutor 只走正式 service，不进入 production app。

明确延期边界：Worker/lease/outbox 表属于第二卷；usage_records 和真实 trace 写入属于第三卷；本卷先建立 RunPause 表和 resume 契约，真实 Chat Loop 暂停点接线属于第四卷。

## File Structure

- Create `backend/app/run_control/types.py`：状态、角色、转换和领域异常。
- Create `backend/app/models/tenant.py`、`backend/app/models/run.py`：新控制面 ORM。
- Create `backend/app/services/tenant_service.py`、`backend/app/services/run_service.py`：事务边界。
- Create `backend/app/core/async_database.py`：共享 async engine/session factory，不再让 Run API 依赖 ChatSessionRepo 初始化副作用。
- Create `backend/app/schemas/tenant.py`、`backend/app/schemas/run.py`：固定契约。
- Create `backend/app/router/tenants.py`、`backend/app/router/runs.py`：Tenant API 和六个 Run API。
- Create `backend/app/scripts/bootstrap_default_tenants.py`：既有用户 bootstrap。
- Create focused tests under `backend/tests/unit/run_control/`, `backend/tests/unit/models/`, `backend/tests/unit/services/`, `backend/tests/integration/`。
- Modify `backend/app/models/__init__.py`、`backend/app/router/auth_router.py:110-135`、`backend/app/app_main.py:18-30`、`backend/app/app_main.py:371-383`。

---

### Task 1: Run 状态与领域错误

**Files:**
- Create: `backend/app/run_control/__init__.py`
- Create: `backend/app/run_control/types.py`
- Test: `backend/tests/unit/run_control/test_types.py`

**Interfaces:**
- Consumes: 无。
- Produces: `RunStatus`、`TenantRole`、`PauseType`、active/terminal sets、`assert_transition()` 和领域异常。

- [ ] **Step 1: 写失败测试**

```python
def test_waiting_is_nonterminal() -> None:
    assert RunStatus.WAITING_INPUT in ACTIVE_RUN_STATUSES
    assert RunStatus.COMPLETED not in ACTIVE_RUN_STATUSES


def test_terminal_state_cannot_move() -> None:
    with pytest.raises(InvalidRunTransition):
        assert_transition(RunStatus.COMPLETED, RunStatus.QUEUED)
```

- [ ] **Step 2: 确认红灯**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/run_control/test_types.py -q
```

Expected: FAIL，缺少 `app.run_control`。

- [ ] **Step 3: 实现最小状态核**

```python
class RunStatus(StrEnum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    CANCEL_REQUESTED = "cancel_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TenantRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"

class PauseType(StrEnum):
    APPROVAL = "approval"
    INPUT = "input"
```

完整转换表：queued→assigned/cancelled；assigned→running/queued/cancel_requested；running→completed/failed/queued/waiting_approval/waiting_input/cancel_requested；waiting→queued/cancelled；cancel_requested→cancelled；终态无出边。定义 `RunControlError`、`InvalidRunTransition`、`ResourceNotFound`、`SessionBusy`、`TenantQueueFull`、`IdempotencyConflict`、`ResumeNotAllowed`。

- [ ] **Step 4: 确认绿灯**

Run Step 2. Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add backend/app/run_control backend/tests/unit/run_control
git commit -m "feat(run): define run lifecycle types"
```

---

### Task 2: Tenant 模型与 RBAC 服务

**Files:**
- Create: `backend/app/models/tenant.py`
- Create: `backend/app/services/tenant_service.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/unit/models/test_tenant_models.py`
- Test: `backend/tests/unit/services/test_tenant_service.py`

**Interfaces:**
- Consumes: `TenantRole`。
- Produces: `Tenant`、`TenantMembership`、`TenantAuditLog`；`TenantService.create_with_owner/list_for_user/list_members/add_member/remove_member/require_role`。

- [ ] **Step 1: 写约束和权限失败测试**

```python
def test_membership_is_unique(db_session, tenant, owner) -> None:
    db_session.add(TenantMembership(tenant_id=tenant.id, user_id=owner.id, role="member"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_member_cannot_add_member(db_session, tenant_users) -> None:
    service, tenant, member, target = tenant_users
    with pytest.raises(PermissionError):
        service.add_member(tenant.id, member.id, target.email, TenantRole.MEMBER)
```

Also test positive quotas, fixed roles, final-owner protection and audit creation.

- [ ] **Step 2: 确认红灯**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/models/test_tenant_models.py backend/tests/unit/services/test_tenant_service.py -q
```

Expected: FAIL，缺少 `app.models.tenant`。

- [ ] **Step 3: 实现模型**

`Tenant`: UUID id, name, unique slug, is_personal, max_running_runs default 2, max_queued_runs default 100, created_at；两配额均有正数 CheckConstraint。

`TenantMembership`: `(tenant_id,user_id)` 复合主键，role CheckConstraint 限 owner/admin/member，joined_at。

`TenantAuditLog`: UUID id, tenant_id, actor_user_id, action, optional target_user_id, JSONB payload, created_at。所有 FK 写明确 ondelete。Export all three from `app.models.__init__`。

- [ ] **Step 4: 实现 TenantService**

Service uses caller-owned sync `Session`; methods `flush()` but never `commit()`。`create_with_owner` inserts tenant + owner membership + `tenant.created` audit。owner/admin may add member；only owner grants/removes admin；nobody removes final owner。Missing membership raises `LookupError`，role denied raises `PermissionError`。

- [ ] **Step 5: 运行并提交**

Run Step 2 and expect PASS, then:

```powershell
git add backend/app/models/tenant.py backend/app/models/__init__.py backend/app/services/tenant_service.py backend/tests/unit/models/test_tenant_models.py backend/tests/unit/services/test_tenant_service.py
git commit -m "feat(tenant): add tenant membership foundation"
```

---

### Task 3: 默认 Tenant 注册与 bootstrap

**Files:**
- Modify: `backend/app/router/auth_router.py:110-135`
- Create: `backend/app/scripts/bootstrap_default_tenants.py`
- Modify: `backend/tests/unit/router/test_auth_register.py`
- Test: `backend/tests/unit/scripts/test_bootstrap_default_tenants.py`

**Interfaces:**
- Consumes: `TenantService.create_with_owner()`。
- Produces: 新注册用户和既有用户恰好一个 personal Tenant owner membership。

- [ ] **Step 1: 扩展注册测试**

```python
def test_register_creates_personal_tenant(client, db_session) -> None:
    response = client.post("/auth/register", json={
        "username": "tenant_new", "password": "secret123", "email": "tenant_new@example.com"
    })
    user_id = response.json()["user"]["id"]
    rows = db_session.query(TenantMembership).filter_by(user_id=user_id).all()
    assert len(rows) == 1
    assert rows[0].role == "owner"
    assert db_session.get(Tenant, rows[0].tenant_id).is_personal is True
```

- [ ] **Step 2: 确认红灯**

Run the single test. Expected: FAIL，membership count is 0。

- [ ] **Step 3: 修改注册事务**

```python
db.add(user)
db.flush()
TenantService(db).create_with_owner(name=f"{user.username} 的工作区", owner=user, is_personal=True)
db.commit()
db.refresh(user)
```

User 与 Tenant 创建必须同成同败。

- [ ] **Step 4: 实现幂等 bootstrap**

`bootstrap_default_tenants(db) -> int` uses `~exists()` to select users without a membership joined to `Tenant.is_personal IS TRUE`，creates one personal tenant each，commits once，returns created count。已有企业 Tenant membership 不能阻止 personal Tenant bootstrap。Test first call returns missing count; second returns 0。CLI `main()` uses `SessionLocal`。

- [ ] **Step 5: 运行并提交**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/router/test_auth_register.py backend/tests/unit/scripts/test_bootstrap_default_tenants.py -q
git add backend/app/router/auth_router.py backend/app/scripts/bootstrap_default_tenants.py backend/tests/unit/router/test_auth_register.py backend/tests/unit/scripts/test_bootstrap_default_tenants.py
git commit -m "feat(tenant): bootstrap personal tenants"
```


---

### Task 4: Tenant 管理 API

**Files:**
- Create: `backend/app/schemas/tenant.py`
- Create: `backend/app/router/tenants.py`
- Test: `backend/tests/integration/test_tenants_v1_router.py`

**Interfaces:**
- Consumes: `TenantService`, `get_current_user_required`, `get_db`。
- Produces: Tenant list/create and member list/add/remove endpoints。

- [ ] **Step 1: 写权限失败测试**

Mount only the tenant router and override DB/auth dependencies。

```python
def test_member_cannot_add_existing_user(member_client, target_user, tenant) -> None:
    response = member_client.post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": target_user.email, "role": "member"},
    )
    assert response.status_code == 403

def test_owner_can_add_existing_user(owner_client, target_user, tenant) -> None:
    response = owner_client.post(
        f"/api/v1/tenants/{tenant.id}/members",
        json={"email": target_user.email, "role": "member"},
    )
    assert response.status_code == 201
```

Also cover unauthenticated 401, outsider 404, admin cannot grant owner, final owner cannot be removed, mutation creates audit。

- [ ] **Step 2: 确认红灯**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/integration/test_tenants_v1_router.py -q
```

Expected: FAIL，缺少 `app.router.tenants`。

- [ ] **Step 3: 定义 schemas**

`TenantCreate(name 1..120)`; `MemberAdd(email, role admin|member)`; `TenantResponse` includes limits and current actor role；`MemberResponse` includes UUID, username, email, role。Use Pydantic v2 `ConfigDict(from_attributes=True)`。

- [ ] **Step 4: 实现 endpoints**

```text
GET    /api/v1/tenants
POST   /api/v1/tenants
GET    /api/v1/tenants/{tenant_id}/members
POST   /api/v1/tenants/{tenant_id}/members
DELETE /api/v1/tenants/{tenant_id}/members/{user_id}
```

Map missing membership/target to 404, role denial to 403, duplicate membership/final owner removal to 409。Mutation commits once。

- [ ] **Step 5: 运行并提交**

Run Step 2 and expect PASS。

```powershell
git add backend/app/schemas/tenant.py backend/app/router/tenants.py backend/tests/integration/test_tenants_v1_router.py
git commit -m "feat(tenant): expose minimal membership API"
```

---

### Task 5: Run 持久模型与数据库约束

**Files:**
- Create: `backend/app/models/run.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/unit/models/test_run_models.py`

**Interfaces:**
- Consumes: Tenant/User foreign keys and Task 1 status strings。
- Produces: `RunSession`, `RunMessage`, `Run`, `RunAttempt`, `RunPause`, `RunEvent`。

- [ ] **Step 1: 写约束失败测试**

```python
def test_only_one_nonterminal_run_per_session(db_session, run_rows) -> None:
    first, second = run_rows(statuses=("queued", "running"))
    db_session.add(first)
    db_session.flush()
    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.flush()

def test_terminal_history_does_not_block_new_run(db_session, run_rows) -> None:
    completed, queued = run_rows(statuses=("completed", "queued"))
    db_session.add_all([completed, queued])
    db_session.flush()
```

Also test unique `(tenant_id, created_by_user_id, idempotency_key)`, run_type chat-only, retry_count 0..1, event seq and attempt_no uniqueness。

- [ ] **Step 2: 确认红灯**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/models/test_run_models.py -q
```

Expected: FAIL，缺少 `app.models.run`。

- [ ] **Step 3: 实现 Session、Message、Run**

Exact tables and critical columns:

```text
run_sessions: id, tenant_id, created_by_user_id, title, created_at, updated_at
run_messages: id, tenant_id, session_id, role, content, status, created_at
runs: id, tenant_id, session_id, created_by_user_id, run_type, status,
      idempotency_key, request_hash, input_message_id, final_message_id, replaces_run_id,
      retry_count, queue_reason, error_code, error_message,
      created_at, queued_at, assigned_at, started_at, finished_at, cancel_requested_at
```

Add:
- `UniqueConstraint(tenant_id, created_by_user_id, idempotency_key, name="uq_run_idempotency")`
- `CheckConstraint("run_type = 'chat'")`
- `CheckConstraint("retry_count BETWEEN 0 AND 1")`
- unique partial index `uq_run_one_nonterminal_per_session` on session_id where status is any active status
- index `(tenant_id,status,queued_at)`

- [ ] **Step 4: 实现 Attempt、Pause、Event**

```text
run_attempts: id, run_id, attempt_no, status, worker_id nullable,
              lease_expires_at, started_at, finished_at, error_code, error_message
run_pauses: id, run_id, pause_no, pause_type, request_payload JSONB,
            continuation_payload JSONB, response_payload JSONB nullable,
            resolved_at, created_at
run_events: id, tenant_id, run_id, attempt_id nullable, seq,
            event_type, payload JSONB, created_at
```

Add unique `(run_id,attempt_no)`, `(run_id,pause_no)`, `(run_id,seq)` and exact status/pause CheckConstraints。Export all models。

- [ ] **Step 5: 运行并提交**

Run Step 2 and expect PASS。

```powershell
git add backend/app/models/run.py backend/app/models/__init__.py backend/tests/unit/models/test_run_models.py
git commit -m "feat(run): add persistent run domain models"
```

---

### Task 6: 原子创建、幂等和查询服务

**Files:**
- Create: `backend/app/services/run_service.py`
- Test: `backend/tests/unit/services/test_run_service_create.py`

**Interfaces:**
- Consumes: `async_sessionmaker[AsyncSession]`, Tenant/Run models, domain exceptions。
- Produces: `CreateRunCommand`, `CreatedRun`, `RunService.create_run/get_run/list_events/get_trace`。

- [ ] **Step 1: 写四个关键失败测试**

```python
@pytest.mark.asyncio
async def test_create_is_atomic(run_service, command) -> None:
    result = await run_service.create_run(command)
    assert result.run.status == "queued"
    assert result.message.content == command.prompt
    assert [e.event_type for e in result.events] == ["run.created"]

@pytest.mark.asyncio
async def test_idempotency_returns_same_run(run_service, command) -> None:
    first = await run_service.create_run(command)
    second = await run_service.create_run(command)
    assert second.run.id == first.run.id

@pytest.mark.asyncio
async def test_session_busy(run_service, command) -> None:
    first = await run_service.create_run(command)
    with pytest.raises(SessionBusy):
        await run_service.create_run(replace(command, idempotency_key="request-2", session_id=first.run.session_id))

@pytest.mark.asyncio
async def test_outsider_get_is_404_domain_error(run_service, command, outsider_id) -> None:
    created = await run_service.create_run(command)
    with pytest.raises(ResourceNotFound):
        await run_service.get_run(command.tenant_id, created.run.id, outsider_id)
```

Also test queue quota and replaces_run validation。

Add an idempotency conflict case: reuse the same key with a different prompt and assert `IdempotencyConflict`。

- [ ] **Step 2: 确认红灯**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/services/test_run_service_create.py -q
```

Expected: FAIL，缺少 `RunService`。

- [ ] **Step 3: 定义接口**

```python
@dataclass(frozen=True)
class CreateRunCommand:
    tenant_id: UUID
    actor_id: UUID
    session_id: UUID | None
    prompt: str
    idempotency_key: str
    replaces_run_id: UUID | None

@dataclass(frozen=True)
class CreatedRun:
    run: Run
    message: RunMessage
    events: tuple[RunEvent, ...]
```

`RunService(session_factory)` owns all transactions。Member sees own Run; owner/admin sees tenant scope。Invisible and absent both raise `ResourceNotFound`。

- [ ] **Step 4: 实现 create_run 单事务顺序**

1. Compute SHA-256 over canonical JSON `{session_id,prompt,replaces_run_id}`. Query idempotency tuple; return existing Run only when `request_hash` matches, otherwise raise `IdempotencyConflict`。
2. Lock Tenant `FOR UPDATE`; verify membership and queued count below limit。
3. Create or validate RunSession。
4. Acquire `pg_advisory_xact_lock(hashtextextended('run-session:' || session_id, 0))`。
5. Recheck no active Run。
6. Validate replaces Run is terminal and same tenant/actor/session。
7. Insert immutable user message, queued Run and `run.created seq=1`。
8. Commit once; never call Redis/Celery。

Use `async with factory() as sess, sess.begin():`; helpers never commit。

- [ ] **Step 5: 查询、trace、运行并提交**

`list_events(after_seq)` orders by seq。`get_trace` queries existing `TraceSpanRow.request_id == str(run_id)` and returns empty tuple when absent。

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/services/test_run_service_create.py -q
git add backend/app/services/run_service.py backend/tests/unit/services/test_run_service_create.py
git commit -m "feat(run): create runs atomically"
```


---

### Task 7: 生命周期、事件、取消、暂停与恢复

**Files:**
- Modify: `backend/app/services/run_service.py`
- Create: `backend/tests/helpers/run_fake_executor.py`
- Test: `backend/tests/unit/services/test_run_service_lifecycle.py`

**Interfaces:**
- Consumes: `RunService`, `assert_transition()`, RunPause/RunEvent。
- Produces: `cancel_run()`, `record_pause()`, `resume_run()`, `transition_run()`, `get_pause()` and test FakeRunExecutor。

- [ ] **Step 1: 写生命周期失败测试**

```python
@pytest.mark.asyncio
async def test_cancel_queued_finishes_immediately(run_service, created_run) -> None:
    result = await run_service.cancel_run(
        created_run.tenant_id, created_run.id, created_run.created_by_user_id
    )
    assert result.status == "cancelled"

@pytest.mark.asyncio
async def test_resume_waiting_keeps_same_run(run_service, fake_executor, created_run) -> None:
    pause = await fake_executor.pause_for_input(
        created_run.id, {"question": "你的成本价是多少？"}
    )
    resumed = await run_service.resume_run(
        created_run.tenant_id,
        created_run.id,
        created_run.created_by_user_id,
        response={"text": "成本价 1500"},
    )
    assert resumed.id == created_run.id
    assert resumed.status == "queued"
    assert (await run_service.get_pause(pause.id)).resolved_at is not None
```

Also test running cancel→cancel_requested, terminal cancel idempotency, invalid resume→ResumeNotAllowed, monotonically increasing event seq。

- [ ] **Step 2: 确认红灯**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/services/test_run_service_lifecycle.py -q
```

Expected: FAIL，lifecycle methods missing。

- [ ] **Step 3: 实现统一锁和 event append**

```python
async def _lock_run(sess, tenant_id, run_id) -> Run:
    row = await sess.scalar(
        select(Run).where(Run.id == run_id, Run.tenant_id == tenant_id).with_for_update()
    )
    if row is None:
        raise ResourceNotFound("run not found")
    return row

async def _append_event(sess, run, event_type, payload, attempt_id=None) -> RunEvent:
    last_seq = await sess.scalar(
        select(func.coalesce(func.max(RunEvent.seq), 0)).where(RunEvent.run_id == run.id)
    )
    event = RunEvent(
        tenant_id=run.tenant_id, run_id=run.id, attempt_id=attempt_id,
        seq=int(last_seq) + 1, event_type=event_type, payload=payload,
    )
    sess.add(event)
    return event
```

Every mutation locks Run before transition, so two commands cannot allocate the same seq。

- [ ] **Step 4: 实现精确语义**

- queued/waiting cancel→cancelled and finished_at now。
- assigned/running cancel→cancel_requested and cancel_requested_at now。
- terminal cancel returns current state without new event。
- `record_pause` only accepts running, allocates pause_no, persists continuation, enters matching waiting state。
- `resume_run` locks unresolved latest pause, persists response/resolved_at, returns same Run to queued, sets `queue_reason="resume"`, appends `run.resumed`。
- repeated resume after first resolution returns current queued Run；other states raise `ResumeNotAllowed`。
- No Outbox in Phase 1；Phase 2 adds notifications in the same transaction。

- [ ] **Step 5: Fake executor、绿灯和提交**

FakeRunExecutor wraps only public service methods; it never updates ORM rows directly。

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/services/test_run_service_lifecycle.py -q
git add backend/app/services/run_service.py backend/tests/helpers/run_fake_executor.py backend/tests/unit/services/test_run_service_lifecycle.py
git commit -m "feat(run): add durable lifecycle commands"
```

---

### Task 8: 六个 Run API 与 SSE 契约

**Files:**
- Create: `backend/app/schemas/run.py`
- Create: `backend/app/router/runs.py`
- Test: `backend/tests/integration/test_runs_v1_router.py`

**Interfaces:**
- Consumes: RunService and JWT `get_current_user_required`。
- Produces: six fixed endpoints and `get_run_service` dependency。

- [ ] **Step 1: 写 API 失败测试**

```python
def test_post_requires_idempotency_key(client, tenant_id) -> None:
    response = client.post(
        f"/api/v1/tenants/{tenant_id}/runs", json={"prompt": "分析茅台"}
    )
    assert response.status_code == 422

def test_replay_returns_same_run(client, tenant_id) -> None:
    headers = {"Idempotency-Key": "web-1"}
    first = client.post(
        f"/api/v1/tenants/{tenant_id}/runs",
        headers=headers, json={"prompt": "分析茅台"},
    )
    second = client.post(
        f"/api/v1/tenants/{tenant_id}/runs",
        headers=headers, json={"prompt": "分析茅台"},
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
```

Also assert all six OpenAPI paths, unauthenticated 401, outsider 404, cancel, invalid resume 409, Last-Event-ID filtering and empty trace。

- [ ] **Step 2: 确认红灯**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/integration/test_runs_v1_router.py -q
```

Expected: FAIL，router missing。

- [ ] **Step 3: 定义 schemas**

```python
class RunCreateRequest(BaseModel):
    session_id: UUID | None = None
    prompt: str = Field(min_length=1, max_length=100_000)
    replaces_run_id: UUID | None = None

class RunResumeRequest(BaseModel):
    response: dict[str, object]

class RunResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    session_id: UUID
    created_by_user_id: UUID
    run_type: Literal["chat"]
    status: RunStatus
    replaces_run_id: UUID | None
    retry_count: int
    created_at: datetime
    queued_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    model_config = ConfigDict(from_attributes=True)
```

Define `TraceItem` and `RunTraceResponse(items: list[TraceItem])` using the existing TraceSpanRow shape。

- [ ] **Step 4: 实现 endpoints**

Exact prefix: `/api/v1/tenants/{tenant_id}/runs`。Paths: POST base; GET run; GET events; GET trace; POST cancel; POST resume。

`get_run_service(request)` reads `app.state.async_session_factory` and tests override it。Map ResourceNotFound→404；SessionBusy/TenantQueueFull/IdempotencyConflict/ResumeNotAllowed/InvalidRunTransition→409；missing, blank, or over-128-byte Idempotency-Key→422。

Events parses optional `Last-Event-ID` and returns durable SSE snapshot:

```python
for event in await service.list_events(tenant_id, run_id, actor_id, after_seq=after):
    data = json.dumps(event.payload, ensure_ascii=False, default=str)
    yield f"id: {event.seq}\nevent: {event.event_type}\ndata: {data}\n\n"
```

Phase 1 closes after durable snapshot；Phase 3 extends the same envelope with Redis token tailing。

- [ ] **Step 5: 运行并提交**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/integration/test_runs_v1_router.py -q
git add backend/app/schemas/run.py backend/app/router/runs.py backend/tests/integration/test_runs_v1_router.py
git commit -m "feat(run): expose v1 run API"
```

---

### Task 9: Production wiring、全链验收与 done card

**Files:**
- Create: `backend/app/core/async_database.py`
- Modify: `backend/app/app_main.py:18-30`
- Modify: `backend/app/app_main.py:194-206`
- Modify: `backend/app/app_main.py:371-383`
- Test: `backend/tests/integration/test_run_foundation_app_wiring.py`
- Create: `docs/claude-context/run-control-plane-phase1-foundation-done.md`

**Interfaces:**
- Consumes: Tasks 1-8。
- Produces: `build_async_database()` shared factory, production app v1 routes, metadata registration, verification evidence。

- [ ] **Step 1: 写 wiring 失败测试**

```python
def test_production_app_registers_routes() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/v1/tenants" in paths
    assert "/api/v1/tenants/{tenant_id}/runs" in paths
    assert "/api/v1/tenants/{tenant_id}/runs/{run_id}/events" in paths

def test_foundation_tables_registered() -> None:
    expected = {
        "tenants", "tenant_memberships", "tenant_audit_logs",
        "run_sessions", "run_messages", "runs",
        "run_attempts", "run_pauses", "run_events",
    }
    assert expected <= set(Base.metadata.tables)
```

- [ ] **Step 2: 确认红灯**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/integration/test_run_foundation_app_wiring.py -q
```

Expected: FAIL，v1 paths missing。

- [ ] **Step 3: 挂载 routers**

First extract shared async DB construction:

```python
def build_async_database() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
```

`_sqlalchemy_async_pg_url` moves with this function from `app_main.py`。Lifespan stores `app.state.db_async_engine` and `app.state.async_session_factory` before constructing ChatSessionRepo。ChatSessionRepo consumes the shared factory；RunService no longer depends on ChatSessionRepo setup succeeding。Shutdown disposes `db_async_engine`。

```python
from app.router.runs import router as runs_router
from app.router.tenants import router as tenants_router

app.include_router(tenants_router)
app.include_router(runs_router)
```

Place new includes before old v0 chat routes。Do not remove/redirect old routes。

- [ ] **Step 4: 运行分层验证**

```powershell
$env:POSTGRES_PASSWORD='postgres123'
uv run --frozen --extra dev pytest backend/tests/unit/run_control backend/tests/unit/models/test_tenant_models.py backend/tests/unit/models/test_run_models.py backend/tests/unit/services/test_tenant_service.py backend/tests/unit/services/test_run_service_create.py backend/tests/unit/services/test_run_service_lifecycle.py backend/tests/unit/router/test_auth_register.py backend/tests/unit/scripts/test_bootstrap_default_tenants.py -q
uv run --frozen --extra dev pytest backend/tests/integration/test_tenants_v1_router.py backend/tests/integration/test_runs_v1_router.py backend/tests/integration/test_run_foundation_app_wiring.py -q
uv run --frozen --extra dev ruff format --check backend/app/run_control backend/app/core/async_database.py backend/app/models/tenant.py backend/app/models/run.py backend/app/services/tenant_service.py backend/app/services/run_service.py backend/app/schemas/tenant.py backend/app/schemas/run.py backend/app/router/tenants.py backend/app/router/runs.py backend/tests
uv run --frozen --extra dev ruff check backend/app/run_control backend/app/core/async_database.py backend/app/models/tenant.py backend/app/models/run.py backend/app/services/tenant_service.py backend/app/services/run_service.py backend/app/schemas/tenant.py backend/app/schemas/run.py backend/app/router/tenants.py backend/app/router/runs.py backend/tests
uv run --frozen --extra dev mypy backend/app/run_control backend/app/core/async_database.py backend/app/services/tenant_service.py backend/app/services/run_service.py backend/app/router/tenants.py backend/app/router/runs.py
```

Expected: all exit 0。Record exact counts；do not call this full-repo verification。

- [ ] **Step 5: 写 done card 并提交**

Done card records shipped scope, exact commits/commands/counts, retained v0 boundary, Phase 2 entry interfaces and observed warnings。

```powershell
git add backend/app/core/async_database.py backend/app/app_main.py backend/tests/integration/test_run_foundation_app_wiring.py docs/claude-context/run-control-plane-phase1-foundation-done.md
git commit -m "feat(run): complete phase 1 foundation"
git status --short
```

Expected: commit succeeds and worktree is clean。

## Phase 1 Acceptance Checklist

- [ ] 注册用户与 personal Tenant 同事务创建；既有用户 bootstrap 幂等。
- [ ] Tenant API 固定三角色并写安全审计。
- [ ] 部分唯一索引阻止同 Session 两个非终态 Run。
- [ ] POST 原子写 message、queued Run、event，并受 queued 配额约束。
- [ ] Idempotency-Key 同请求 replay 返回同一 Run；不同请求返回 409。
- [ ] member 不能读其他 member Run；owner/admin 可租户级查看。
- [ ] replaces Run 只允许同 Tenant、同用户、同 Session 的终态 Run。
- [ ] cancel/resume 遵守状态机并写递增 durable event。
- [ ] 六个 Run API 出现在 production OpenAPI。
- [ ] 本卷不调用 LLM、Redis、Celery 或 Scheduler。
- [ ] 旧 v0 chat 与新表完全隔离。
- [ ] 指定 pytest、ruff、mypy 有真实 exit 0 证据。

## Phase 2 Handoff Contract

- Scheduler only reads `runs.status == "queued"` candidates。
- Scheduler creates RunAttempt/lease/Outbox through a new scheduling service and calls `RunService.transition_run()`。
- Worker claim is a Phase 2 atomic interface；workers never update Run directly。
- Scheduling/claim/recovery state changes reuse Run locks and durable event append。
- Phase 2 adds cancel/resume Outbox writes without changing Phase 1 API paths or response models。
