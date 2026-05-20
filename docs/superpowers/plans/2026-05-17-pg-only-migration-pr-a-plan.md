# PG-only Migration PR-A — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删主 ORM 33+ 处 `with_variant(String(36), "sqlite")` / `JSONB().with_variant(JSON, "sqlite")` fallback,L0/L1 测试 fixture 切到真 PG instance(复用 `pg_test_container`),CI unit/integration job 加 `services: postgres`。

**Architecture:** 复用已有 `pg_test_container` session-scoped fixture(`backend/tests/conftest.py:243`),新增 `db_session` function-scoped fixture 走 SQLAlchemy `connection.begin()` + 测试结束 rollback。Model 层删 `with_variant`,纯 PG 类型。L0/L1 在线 test 文件原先 `create_engine("sqlite:///:memory:")` 模式改成接受 `db_session` fixture。xdist per-worker db isolation 留独立 follow-up(本 PR 不装 pytest-xdist)。

**Tech Stack:** SQLAlchemy 2.x + PostgreSQL 14+ + pytest + uv + ruff + mypy strict。

---

## Spec 锚点

- Spec: `docs/superpowers/specs/2026-05-17-pg-only-migration-design.md` § 4 PR-A
- Spec § 6 决策 1 备注:本 PR 只实现 fallback(单 db + transaction rollback);per-worker db 留独立 follow-up

## File Structure

**修改**:
- `backend/app/memory/models.py` — 删 `_UUID` / `_JSONB` 的 `with_variant` 后缀(L7-8 注释 + L45-46 定义)
- `backend/app/models/monitoring.py` — 3 处 `with_variant(String(36), "sqlite")`
- `backend/app/models/chat.py` — 3 处 `with_variant(JSON, "sqlite")`
- `backend/app/models/trade.py` — 1 处 + docstring
- `backend/app/models/research_report.py` — 3 处 + docstring
- `backend/app/models/user.py` — 1 处 + 注释
- `backend/app/models/escalation_record.py` — 5 处
- `backend/app/models/tool_result_cache.py` — 2 处
- `backend/app/models/position.py` — 1 处
- `backend/app/services/trace_models.py` — 2 处(`_UUID_COL` + `_JSONB_COL` 定义)
- `backend/app/router/persona_router.py` — L40 注释提到 with_variant(只改注释)
- `backend/app/router/reports.py` — L209 注释提到 with_variant(只改注释)
- `backend/tests/conftest.py` — 加 `pg_test_engine` + `db_session` 两个 fixture;删 `tmp_eval_db`(只 PR-B 用,但 PR-A 暂留;实际 PR-A 不动它)
- `backend/tests/unit/conftest.py` — 不动(autouse 跟 db 无关)
- **40 个 unit test 文件** — 改 `create_engine("sqlite:///:memory:")` 局部 setup 用 `db_session` fixture
- `backend/tests/unit/memory/test_models.py` — 删除 `test_sqlite_create_all_works` test(PG-only 不需要)
- `.github/workflows/pr.yml` — `services: postgres` 扩到 unit + integration job
- `.github/workflows/nightly.yml` — 同
- `docs/claude-context/test-db-layered-strategy.md` — 重写为全 PG 策略
- `CLAUDE.md` — index 卡片同步

**创建**:
- `docs/claude-context/pg-only-migration-pr-a-landed.md` — PR-A 收尾卡(Task 14)

---

## Task 1 — Scope sanity + worktree 准备

**Files:**
- Test: 无(scope check)

- [ ] **Step 1:进 PR-A worktree(从 main 起)**

```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
git worktree add .worktrees/pg-only-pr-a -b feat/pg-only-pr-a main
cd .worktrees/pg-only-pr-a
```

- [ ] **Step 2:grep 当前 with_variant 全量**

```bash
grep -rn "with_variant" backend/app --include="*.py" | wc -l
```

Expected:`33`(±5,基线数;后面 Task 14 verify = 0)

- [ ] **Step 3:grep 当前 sqlite-related test 文件数**

```bash
grep -rln "sqlite" backend/tests | wc -l
```

Expected:`40`(基线;最终 Task 14 期望 ≤ 5,仅 trace_service/eval_recorder 测试还在用 sqlite — 这部分留 PR-B)

- [ ] **Step 4:跑 baseline unit test,记录通过数**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/ --tb=no -q --ignore=backend/tests/unit/memory 2>&1 | tail -3
```

Expected:`1111 passed, 11 failed`(对照 P0 PR 的 verify 数据)。**记录到 commit message:'PR-A baseline = 1111 passed / 11 failed'**

- [ ] **Step 5:确认 docker compose postgres 起着**

```bash
docker compose ps postgres 2>&1 | head -3
```

Expected:`postgres` 服务 `Up`;没起就 `docker compose up -d postgres`。

---

## Task 2 — 加 PG db_session fixture(TDD)

**Files:**
- Modify: `backend/tests/conftest.py`(加 2 个 fixture)
- Create: `backend/tests/unit/test_db_session_fixture.py`(fixture self-test)

- [ ] **Step 1:写 fixture self-test(先 fail)**

`backend/tests/unit/test_db_session_fixture.py`:

```python
"""L0 fixture sanity — db_session 是真 PG + 每 test rollback isolation."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def test_db_session_is_postgres(db_session: Session) -> None:
    """fixture 提供的 session 连的是真 PG,不是 sqlite。"""
    dialect = db_session.bind.dialect.name
    assert dialect == "postgresql", f"db_session expected postgresql, got {dialect}"


def test_db_session_create_all_already_ran(db_session: Session) -> None:
    """fixture 启动时 create_all 已跑过,users 表存在。"""
    result = db_session.execute(
        text("SELECT to_regclass('public.users')")
    ).scalar()
    assert result == "users"


def test_db_session_rolls_back_between_tests_step1(db_session: Session) -> None:
    """前置 test:插一行 sentinel。Step 2 用同 fixture 应该看不到这一行。"""
    db_session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS _fixture_rollback_probe "
            "(id INT PRIMARY KEY, marker TEXT)"
        )
    )
    db_session.execute(
        text("INSERT INTO _fixture_rollback_probe (id, marker) VALUES (1, 'step1')")
    )


def test_db_session_rolls_back_between_tests_step2(db_session: Session) -> None:
    """后置 test:跨 fixture rollback 后,上一 test 插的 sentinel 不可见。"""
    # 这里要么表不存在(纯 rollback),要么存在但空表
    result = db_session.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = '_fixture_rollback_probe'"
        )
    ).scalar()
    if result == 1:
        rows = db_session.execute(
            text("SELECT COUNT(*) FROM _fixture_rollback_probe")
        ).scalar()
        assert rows == 0, "rollback failed — sentinel from prior test leaked"
```

- [ ] **Step 2:跑 fail**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/test_db_session_fixture.py -v 2>&1 | tail -10
```

Expected:`FAILED` 全部 4 个 — fixture `db_session` 还没定义。

- [ ] **Step 3:在 `backend/tests/conftest.py` 加 fixture(放在 `pg_test_container` 下方)**

```python
# ---------------------------------------------------------------------------
# PG fixture — L0/L1/L2.5 共用(取代 sqlite-override)
# spec: docs/superpowers/specs/2026-05-17-pg-only-migration-design.md § 4 PR-A
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pg_test_engine(pg_test_container: dict[str, object]):
    """session-scoped SQLAlchemy engine bound to industry_assistant_test;
    create_all 跑一次(覆盖所有注册的 metadata)。

    Replaces 全部 in-memory sqlite engines used by L0/L1 tests.
    """
    from sqlalchemy import create_engine

    import app.models  # noqa: F401 — barrel registers all metadata
    import app.services.trace_models  # noqa: F401 — trace/eval metadata
    from app.core.database import Base

    url = str(pg_test_container["url"])
    engine = create_engine(url, future=True, pool_pre_ping=True)

    # idempotent — 跨 worktree session 复用 db 时不破坏
    Base.metadata.create_all(bind=engine)

    yield engine
    engine.dispose()


@pytest.fixture
def db_session(pg_test_engine):
    """function-scoped Session with savepoint rollback.

    每个 test 起一个 outer transaction,test 完 rollback,
    所有 INSERT/UPDATE/DELETE 跨 test 不可见。
    """
    from sqlalchemy.orm import sessionmaker

    connection = pg_test_engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
```

- [ ] **Step 4:跑 fixture self-test pass**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/test_db_session_fixture.py -v 2>&1 | tail -10
```

Expected:`4 passed`。

- [ ] **Step 5:commit fixture**

```bash
git add backend/tests/conftest.py backend/tests/unit/test_db_session_fixture.py
git commit -m "test(pg-only): 加 pg_test_engine + db_session 共用 fixture

为 PR-A 把 L0/L1 测试从 sqlite-override 切到真 PG,fixture 走
session-scoped engine + create_all once + function-scoped session
+ transaction rollback isolation。新加 4 个 self-test 守护 rollback
跨 test 不泄漏。

原因 layer: impl"
```

---

## Task 3 — 删 `memory/models.py` 的 `_UUID` / `_JSONB` with_variant

**Files:**
- Modify: `backend/app/memory/models.py:7-8, 45-46`

- [ ] **Step 1:read 当前定义**

```bash
sed -n '40,50p' backend/app/memory/models.py
```

Expected:
```
_UUID = PgUUID(as_uuid=True).with_variant(String(36), "sqlite")
_JSONB = JSONB().with_variant(JSON, "sqlite")
```

- [ ] **Step 2:Edit 删 with_variant 后缀**

```python
# 旧:
_UUID = PgUUID(as_uuid=True).with_variant(String(36), "sqlite")
_JSONB = JSONB().with_variant(JSON, "sqlite")

# 新:
_UUID = PgUUID(as_uuid=True)
_JSONB = JSONB()
```

同时改 file header docstring(L7-8):
```
- PgUUID + with_variant(String(36), "sqlite") — L0 unit test sqlite override 友好
- JSONB + with_variant(JSON, "sqlite") — 同上
```

→

```
- PgUUID — PG-only,L0/L1 测试走真 PG fixture (db_session)
- JSONB — 同上
```

- [ ] **Step 3:跑 memory unit + integration test 验证**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/memory/ --tb=line -q 2>&1 | tail -5
```

Expected:可能有 fail(`test_sqlite_create_all_works` 等显式测 sqlite override 的 test)。**记录 fail 列表,留 Task 11 处理**。其它 test 应该过。

- [ ] **Step 4:commit**

```bash
git add backend/app/memory/models.py
git commit -m "refactor(pg-only): memory/models.py 删 _UUID/_JSONB with_variant"
```

---

## Task 4 — 删 9 个 model 文件的 with_variant(机械式)

**Files:**
- Modify: `backend/app/models/{monitoring,chat,trade,research_report,user,escalation_record,tool_result_cache,position}.py`

- [ ] **Step 1:批量 sed 替换 + 手工 verify**

每个文件做 2 类替换(用 Edit 工具,**不**用 sed 自动跑,因为有 docstring 注释要一起改):

A 类:`UUID(as_uuid=True).with_variant(String(36), "sqlite")` → `UUID(as_uuid=True)`
B 类:`JSONB().with_variant(JSON, "sqlite")` → `JSONB()`(注意有的写 `JSON()`,统一)

- [ ] **Step 2:逐文件改**

**`models/monitoring.py`**:3 处 A 类(L42, L68, L93)。Edit 各处。

**`models/chat.py`**:3 处 B 类(L86, L87, L99)。Edit 各处。

**`models/trade.py`**:1 处 A 类(L49) + L7 docstring `单元测试 = sqlite in-memory,通过 with_variant 降级 String(36)` 删掉。

**`models/research_report.py`**:3 处(L37 A, L49 B, L64 A) + L11 docstring `单元测试 = sqlite in-memory,通过 with_variant 降级为 JSON / String(36)` 删掉。

**`models/user.py`**:1 处 A(L24) + L21 注释 `with_variant 让 SQLite 把 column 当 String(36) 处理` 删掉。

**`models/escalation_record.py`**:5 处(L17, L22 A;L28, L29, L30 B)。

**`models/tool_result_cache.py`**:2 处 B(L17, L18)。

**`models/position.py`**:1 处 A(L39)。

- [ ] **Step 3:每个文件改完跑 import smoke**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -c "
import app.models
print('all model imports OK')
print('registered tables:', len(app.models.Base.metadata.tables))
"
```

Expected:`all model imports OK` + 表数量 ≥ 30。

- [ ] **Step 4:grep 守护**

```bash
grep -rn "with_variant" backend/app/models/ --include="*.py"
```

Expected:`(empty)`。

- [ ] **Step 5:commit**

```bash
git add backend/app/models/
git commit -m "refactor(pg-only): models/ 9 文件删 with_variant,纯 PG 类型"
```

---

## Task 5 — 删 `services/trace_models.py` 的 with_variant

**Files:**
- Modify: `backend/app/services/trace_models.py:106-107`

- [ ] **Step 1:Edit**

```python
# 旧:
_UUID_COL = PgUUID(as_uuid=True).with_variant(String(36), "sqlite")
_JSONB_COL = JSONB().with_variant(JSON, "sqlite")

# 新:
_UUID_COL = PgUUID(as_uuid=True)
_JSONB_COL = JSONB()
```

- [ ] **Step 2:跑 trace_service smoke import**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -c "from app.services.trace_models import _UUID_COL, _JSONB_COL; print('OK')"
```

Expected:`OK`。

- [ ] **Step 3:全仓 grep 守护**

```bash
grep -rn "with_variant" backend/app --include="*.py"
```

Expected:`(empty)`(已无任何 with_variant)。

- [ ] **Step 4:commit**

```bash
git add backend/app/services/trace_models.py
git commit -m "refactor(pg-only): trace_models.py 删 with_variant"
```

---

## Task 6 — 迁移 `unit/models/` 测试到 db_session fixture

**Files:**
- Modify: `backend/tests/unit/models/test_position_model.py`、`test_monitoring_models.py`、`test_research_report.py`、`test_trade_model.py`

- [ ] **Step 1:read 一个 file 看模式**

```bash
head -30 backend/tests/unit/models/test_position_model.py
```

确认是 `create_engine("sqlite:///:memory:") + Table.__table__.create(engine)` 模式。

- [ ] **Step 2:迁移模板**

旧模式:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

def test_position_minimal():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Position.__table__.create(engine)
    with Session(engine) as s:
        # ... test code
```

新模式:
```python
def test_position_minimal(db_session):
    # 表已经 create_all 跑过(pg_test_engine 启动时),直接用 session
    # db_session 是 SQLAlchemy Session, 跨 test rollback isolation
    # ... test code(用 db_session 替换 s)
```

注意点:
1. 删 `create_engine` / `Session` / `engine.dispose()` 调用 — fixture 全管
2. test 函数签名加 `db_session` 参数
3. 直接用 `db_session` 替原 `s` / `session`
4. **不**手动 `User.__table__.create()` — fixture 启动时已经 create_all

- [ ] **Step 3:test_position_model.py**(逐文件)

Edit 后跑:
```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/models/test_position_model.py -v 2>&1 | tail -5
```

Expected:全 passed。

- [ ] **Step 4:test_monitoring_models.py、test_research_report.py、test_trade_model.py** 同样迁移 + 跑 pass

- [ ] **Step 5:grep 验证 sqlite 引用清除**

```bash
grep -n "sqlite\|create_engine" backend/tests/unit/models/*.py
```

Expected:`(empty)`。

- [ ] **Step 6:commit**

```bash
git add backend/tests/unit/models/
git commit -m "test(pg-only): unit/models/ 迁 sqlite → db_session fixture"
```

---

## Task 7 — 迁移 `unit/memory/test_models.py`

**Files:**
- Modify: `backend/tests/unit/memory/test_models.py`

- [ ] **Step 1:迁移 + 删 sqlite-specific test**

`test_models.py` 有 `def sqlite_session():` fixture(L168-206)和 `test_sqlite_create_all_works`(L212-)等显式测 sqlite 的 test。

操作:
1. 删 `sqlite_session` fixture 定义
2. 删 `test_sqlite_create_all_works`(已不适用)
3. 其它 test 把 `sqlite_session` 参数改成 `db_session`
4. Edit 各 test 函数体里 `sqlite_session.bind` → `db_session.bind`,`sqlite_session.execute(...)` → `db_session.execute(...)`

- [ ] **Step 2:跑 verify**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/memory/test_models.py -v 2>&1 | tail -5
```

Expected:全 passed(或剩余 fail 跟我们改的不相关 — main 上也 fail,记录)。

- [ ] **Step 3:commit**

```bash
git add backend/tests/unit/memory/test_models.py
git commit -m "test(pg-only): unit/memory/test_models.py 迁 db_session;删 sqlite-only 测试"
```

---

## Task 8 — 迁移 `unit/services/`(trade_service、position_service、monitoring_scope)

**Files:**
- Modify: `backend/tests/unit/services/test_trade_service.py`、`test_position_service.py`、`test_monitoring_scope.py`

- [ ] **Step 1:逐文件 grep + Edit 同 Task 6 模板**

```bash
grep -n "sqlite\|create_engine" backend/tests/unit/services/test_trade_service.py
```

按模板改。

- [ ] **Step 2:跑测试**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/services/test_trade_service.py backend/tests/unit/services/test_position_service.py backend/tests/unit/services/test_monitoring_scope.py -v 2>&1 | tail -10
```

Expected:全 passed。

- [ ] **Step 3:commit**

```bash
git add backend/tests/unit/services/
git commit -m "test(pg-only): unit/services/ 3 文件迁 db_session"
```

---

## Task 9 — 迁移 `unit/router/`(test_auth_register、test_reports_endpoints、test_reports_stream)

**Files:**
- Modify: `backend/tests/unit/router/test_auth_register.py`、`test_reports_endpoints.py`、`test_reports_stream.py`

- [ ] **Step 1:同 Task 6 模板 + 处理 FastAPI TestClient 注入**

特别注意:router test 用 FastAPI `TestClient` + dependency override:
```python
app.dependency_overrides[get_db] = lambda: db_session
```

注意 `get_db` 是 generator,override 要返回 db_session 或包成 generator。

模板:
```python
def test_register_user(db_session, client):
    def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    try:
        resp = client.post("/auth/register", json={...})
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2:跑测试**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/router/test_auth_register.py backend/tests/unit/router/test_reports_endpoints.py backend/tests/unit/router/test_reports_stream.py -v 2>&1 | tail -10
```

Expected:全 passed。

- [ ] **Step 3:commit**

```bash
git add backend/tests/unit/router/
git commit -m "test(pg-only): unit/router/ 3 文件迁 db_session + override get_db"
```

---

## Task 10 — 迁移剩余 unit test(tasks + chat_persistence 系列)

**Files:**
- Modify: `backend/tests/unit/test_chat_stale_scanner.py`、`test_chat_runner.py`、`test_chat_task_repo.py`、`test_chat_session_repo_extensions.py`、`tasks/test_detection_cycle.py`、`tasks/test_generate_detail_card.py`、`tasks/test_daily_and_cleanup.py`

- [ ] **Step 1:grep 找到具体 sqlite 用法**

```bash
for f in backend/tests/unit/test_chat_stale_scanner.py backend/tests/unit/test_chat_runner.py backend/tests/unit/test_chat_task_repo.py backend/tests/unit/test_chat_session_repo_extensions.py; do
  echo "=== $f ==="
  grep -n "sqlite\|create_engine" "$f"
done
```

按模板逐一改。Tasks 子目录 3 文件同样处理。

- [ ] **Step 2:跑测试**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/test_chat_stale_scanner.py backend/tests/unit/test_chat_runner.py backend/tests/unit/test_chat_task_repo.py backend/tests/unit/test_chat_session_repo_extensions.py backend/tests/unit/tasks/ -v 2>&1 | tail -10
```

Expected:全 passed。

- [ ] **Step 3:commit**

```bash
git add backend/tests/unit/test_chat_*.py backend/tests/unit/tasks/
git commit -m "test(pg-only): unit/test_chat_*.py + unit/tasks/ 迁 db_session"
```

---

## Task 11 — 剩余 sqlite 用法 final sweep

**Files:**
- Modify: 任意 `grep -rln "sqlite" backend/tests/unit/` 仍然命中的文件(除 trace_service / eval_recorder 相关,后者归 PR-B)

- [ ] **Step 1:列剩余 sqlite refs**

```bash
grep -rln "sqlite\|create_engine.*memory" backend/tests/unit/
```

Expected:可能还有 5-10 个文件。对每个文件:
- 如果是 `tushare_cache` / `chunk_embed_cache` / `ingest_state` / `monitoring_email_notifier` / `reliable_bocha_service` 这种**测**功能性 sqlite 的 — 留到对应 PR(PR-B 或 PR-C)。**本 task skip**,在 plan 末尾的 verify 命令里 explicitly allow these files.
- 如果是其他 model/router/service 测试 — 按 Task 6 模板迁移。

- [ ] **Step 2:跑全量 unit 测试**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/ --tb=line -q 2>&1 | tail -5
```

Expected:`X passed, Y failed`,Y ≤ 11(原 baseline 11 个 pre-existing fail)。**新增 fail 一律先 debug**。

- [ ] **Step 3:commit(若有改动)**

```bash
git add backend/tests/unit/
git commit -m "test(pg-only): final sweep — 剩余 sqlite 迁 db_session(留 PR-B/C 范围的不动)"
```

---

## Task 12 — CI workflow `services: postgres` 扩到 unit + integration job

**Files:**
- Modify: `.github/workflows/pr.yml`、`.github/workflows/nightly.yml`

- [ ] **Step 1:read 现状**

```bash
cat .github/workflows/pr.yml
```

找到 e2e job 的 `services: postgres` 块,看现有写法。

- [ ] **Step 2:把 services 块加到 unit 和 integration job(如果它们是独立 job 的话)**

如果 unit + integration 已经合并在一个 job,只需要确认 `services: postgres` 已经在该 job 下。

模板(每个 job 加):
```yaml
services:
  postgres:
    image: postgres:14
    env:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres123
      POSTGRES_DB: industry_assistant_test
    ports:
      - 5432:5432
    options: >-
      --health-cmd pg_isready
      --health-interval 10s
      --health-timeout 5s
      --health-retries 5
```

- [ ] **Step 3:跑 yaml 语法 lint**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -c "import yaml; yaml.safe_load(open('.github/workflows/pr.yml')); print('OK')"
```

Expected:`OK`。

- [ ] **Step 4:commit + push,让 CI 跑**

```bash
git add .github/workflows/
git commit -m "ci(pg-only): unit + integration job 加 services: postgres"
git push -u origin feat/pg-only-pr-a
```

确认 GitHub Actions 跑过 — 看 PR check status。

---

## Task 13 — 文档同步

**Files:**
- Modify: `docs/claude-context/test-db-layered-strategy.md`(重写)
- Modify: `CLAUDE.md`(index 卡同步)
- Create: `docs/claude-context/pg-only-migration-pr-a-landed.md`(收尾卡)

- [ ] **Step 1:重写 test-db-layered-strategy.md**

新内容(总结):
```markdown
# 测试 DB 策略 — 全 PG (2026-05-17 起)

**结论**:测试统一连真 PG,L0/L1/L2.5 共用 `pg_test_container` fixture。

**Why**:消除 sqlite-override 与生产 PG 的双套维护(UUID/JSONB 类型差异 / 索引设计 / 并发行为)。

**How to apply**:
- 所有需要 DB 的 unit test 接受 `db_session` fixture(SQLAlchemy Session,session 末 rollback)
- `pg_test_engine` (session-scoped) 启动时 `create_all` 跑一次
- 启动 PG: 本地 `docker compose up -d postgres`(fixture 自动起,但 dev 一次性起着更快)
- xdist per-worker db 留 follow-up plan(目前单 db + transaction rollback)
```

- [ ] **Step 2:CLAUDE.md 同步**

把 `[测试 DB 分层策略]` 卡片描述从 "L0/L1 sqlite-override,L2.5 真 PG fixture" 改成 "全 PG,统一 db_session + transaction rollback"。

- [ ] **Step 3:写 pg-only-migration-pr-a-landed.md 收尾卡**

```markdown
# PG-only Migration PR-A 落地

**结论**:删主 ORM 33+ with_variant + L0/L1 切真 PG fixture,CI services: postgres 扩 unit + integration。

**Why**:运维/部署收敛(spec § 1)。

**How to apply**:测试需 DB → 用 `db_session` fixture。本地 dev 必须 `docker compose up -d postgres`。

**Wall time**:~1.5 天(实际)。

**Verify**:
- `grep -rn with_variant backend/app` = 0
- 全量 unit + integration 测试 pass(0 regression)
- xdist 留独立 follow-up
```

- [ ] **Step 4:commit**

```bash
git add docs/claude-context/test-db-layered-strategy.md docs/claude-context/pg-only-migration-pr-a-landed.md CLAUDE.md
git commit -m "docs(pg-only): PR-A 文档同步 + 收尾卡"
```

---

## Task 14 — 整体验收 + grep 守护 + PR

**Files:**
- 无新文件;跑全量 verify + 提 PR

- [ ] **Step 1:grep 守护:0 个 with_variant**

```bash
grep -rn "with_variant" backend/app --include="*.py" | wc -l
```

Expected:`0`。

- [ ] **Step 2:grep 守护:0 个 model 文件 sqlite refs**

```bash
grep -rn "sqlite" backend/app/models backend/app/memory/models.py 2>&1 | wc -l
```

Expected:`0`。

- [ ] **Step 3:跑 backend unit 全量**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/unit/ --tb=no -q 2>&1 | grep -E "[0-9]+ passed|[0-9]+ failed" | tail -2
```

Expected:`X passed, Y failed` 其中 Y ≤ 11(baseline)。

- [ ] **Step 4:跑 backend integration**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m pytest backend/tests/integration/ --tb=no -q 2>&1 | grep -E "passed|failed" | tail -2
```

Expected:全绿(无新 regression)。

- [ ] **Step 5:跑 ruff + mypy**

```bash
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m ruff check backend/app backend/tests 2>&1 | tail -3 && \
PATH=/Users/talantan/.openclaw/workspace-main/financial-research-assistant/.venv/bin:$PATH \
  python -m mypy backend/app 2>&1 | tail -3
```

Expected:`All checks passed!` + `Success: no issues found`。

- [ ] **Step 6:push + 提 PR**

```bash
git push origin feat/pg-only-pr-a
unset all_proxy https_proxy http_proxy HTTPS_PROXY HTTP_PROXY ALL_PROXY
gh pr create --title "feat(pg-only): PR-A 删 with_variant + L0/L1 切真 PG fixture" \
  --base main --head feat/pg-only-pr-a \
  --body "$(cat <<'EOF'
## Summary

PG-only migration 4-PR roadmap 的 PR-A(共 ~4 天 wall time 主题第 1 步)。

Spec: \`docs/superpowers/specs/2026-05-17-pg-only-migration-design.md\` § 4 PR-A

### 改动

- 删主 ORM 33+ 处 \`.with_variant(String(36), "sqlite")\` / \`.with_variant(JSON, "sqlite")\` fallback,10 个 model 文件(含 \`memory/models.py\` 的 \`_UUID\`/\`_JSONB\` 定义 + \`services/trace_models.py\` 的 \`_UUID_COL\`/\`_JSONB_COL\`)
- 加 \`pg_test_engine\` (session-scoped) + \`db_session\` (function-scoped + transaction rollback) 共用 fixture,替代 ~10 个 L0/L1 test 文件原先各自的 \`create_engine("sqlite:///:memory:")\` setup
- 删 \`test_sqlite_create_all_works\` 等显式测 sqlite override 的 test
- CI \`.github/workflows/{pr,nightly}.yml\` unit + integration job 加 \`services: postgres\`
- 文档:重写 \`docs/claude-context/test-db-layered-strategy.md\`、CLAUDE.md 同步、加 \`pg-only-migration-pr-a-landed.md\` 收尾卡

### Out of scope(下个 PR)

- TraceService + EvalRecorder 业务逻辑迁 PG(留 PR-B)
- ingest cache / state 迁 PG(留 PR-C)
- LangGraph SqliteSaver 残留(留 PR-D)
- xdist per-worker db isolation(留独立 follow-up plan)

## Test plan

- [x] \`grep -rn with_variant backend/app\` = 0
- [x] \`grep -rn sqlite backend/app/models backend/app/memory/models.py\` = 0
- [x] backend unit:\`X passed, Y failed\` (Y ≤ 11 baseline)
- [x] backend integration:0 regression
- [x] ruff + mypy clean
- [x] CI services: postgres 跑通

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 7:更新 PR-A landed 卡 + 告诉 user PR URL**

报告:`PR-A 完成,URL: <PR url>;baseline = 1111 passed / 11 failed → PR-A 后 X passed / Y failed (Y ≤ 11)`。

---

## Self-Review(plan 写完后 check)

### 1. Spec coverage 检查

- ✅ Spec § 4 PR-A "删 with_variant" → Task 3/4/5
- ✅ Spec § 4 PR-A "L0/L1 fixture 切 PG" → Task 2 + Task 6-10 迁测试
- ✅ Spec § 4 PR-A "CI services: postgres 扩 unit + integration" → Task 12
- ✅ Spec § 4 PR-A 验收 `grep with_variant = 0` → Task 14 Step 1
- ✅ Spec § 6 决策 1 fallback 单 db + transaction rollback → Task 2 fixture 实现
- ⚠️ Spec § 6 决策 1 xdist per-worker db → **deferred 到独立 follow-up plan**(plan header 已说明)

### 2. Placeholder scan

- ✅ 无 "TBD"、"TODO"、"implement later"
- ✅ 每个 task 有具体代码块或具体命令
- ⚠️ Task 11 "其他 model/router/service 测试 — 按 Task 6 模板迁移" — 这里需要 executor 现场判断哪些文件留 PR-B/C 范围、哪些迁。**可接受**(plan 给了 grep 命令 + 判断规则)。

### 3. Type / API 一致性

- ✅ Task 2 定义 `db_session` fixture → Task 6-10 一致使用 `db_session` 参数名
- ✅ Task 2 fixture 返回 SQLAlchemy `Session` → Task 6/8/9 直接当 Session 用
- ✅ Task 9 router test 模板 override `get_db` → 跟现有 router 代码的 `Depends(get_db)` 模式一致

### 4. Risk

- PR-A 总改 ~15 个 model + ~13 个 test 文件 + 2 个 workflow + 3 个 docs = ~33 文件改动。diff 大,但每个 task 1 commit,reviewer 可按 commit 看。
- 总测试时间预估 unit ~20s → ~45-60s(单 db transaction rollback)— spec § 7 标注 acceptable。
