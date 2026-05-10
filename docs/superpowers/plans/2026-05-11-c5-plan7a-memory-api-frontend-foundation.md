# C.5 Plan 7A — Memory Page Backend API + Frontend Foundation

> **Plan 编号**: 7A(C.5 Plan 7 拆分上半:API + Foundation。可视化具体组件由 Plan 7B 完成)
> **工程量**: ~2.5 天 wall time
> **Spec 主责章节**: § 9 /memory Page UI(backend API + 路由部分)
> **Shared Contracts**: `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md`(严格遵守 § 1 文件结构 + § 10 REST endpoint)
> **算法深度补丁**: 无(#8 用户心智 onboarding 由 Plan 7B 收)
> **依赖前置**: Plan 1A/1B(schema + Memory Protocol)+ Plan 2A/2B(写入 pipeline + extractor)+ Plan 3(读取 + working memory injection)+ Plan 4(6 MCP tools + recall) ship
> **写作日期**: 2026-05-11

---

## 0. 前置说明 / 仓库适配

Shared contracts § 1 列的 frontend 路径为 Next.js 风格(`src/app/memory/page.tsx` / `src/lib/memory-api.ts`),但本仓库 frontend 实际是 **Vite + React + React Router**(已 ship,见 `frontend/src/router/routes.tsx` 与 `frontend/src/pages/monitoring/index.tsx` 等)。

**适配规则**:
- 契约 § 1 的 frontend 路径以 **逻辑路径** 解读;落地到本仓库时按现有 pages/ + api/ 结构对齐:
  - `src/app/memory/page.tsx` → `frontend/src/pages/memory/index.tsx`(对应 React Router 的 `/memory` 路由)
  - `src/components/memory/*.tsx` → `frontend/src/pages/memory/components/*.tsx`(Plan 7B 创建)
  - `src/lib/memory-api.ts` → `frontend/src/api/memoryApi.ts`(对应现有 `api/monitoring.ts` / `api/chatApi.ts` 模式)
- 契约 § 10 backend endpoint 路径(`/api/v0/memory/...`)**字面遵守**,这是真硬契约
- Plan 7B 收到契约 audit 时同步补"Vite/React adapter note"到 § 1 适配栏(由 Plan 8 收束)

**为什么这样适配**:
1. 契约 § 1 写的 Next.js 形态是设计期 placeholder,实际仓库形态没改造的 ROI;
2. 强行引 Next.js / app router 会跟现有 AuthGuard + AppShell 冲突,scope 远超 Plan 7;
3. backend endpoint 路径是 frontend / 后端解耦的真契约,这部分严格遵守。

---

## 1. Plan 范围

### 在范围(Plan 7A 完成)

- **Backend `memory_router.py`**: 5 个 REST endpoint(契约 § 10 全表)
  - `GET /api/v0/memory/graph`
  - `GET /api/v0/memory/timeline`
  - `GET /api/v0/memory/audit`
  - `POST /api/v0/memory/edges/{edge_id}/invalidate`
  - `GET /api/v0/memory/blocks`
- 注册到 `app_main.py include_router`
- L0 Pydantic schema test + L1 Integration test(in-memory sqlite override + fake_auth + 跨用户隔离 case)
- **Frontend Foundation**:
  - `frontend/src/api/memoryApi.ts`: 5 endpoint typed client + Vitest msw test
  - `frontend/src/pages/memory/index.tsx`: `/memory` 路由 + 三 tab 骨架(Graph / Timeline / Audit),tab 内容暂用 placeholder 占位(`<div>Graph view (Plan 7B)</div>` 等)
  - `frontend/src/pages/memory/components/MemoryWorkingBlocks.tsx`: working blocks 当前内容只读卡片(右栏 always-visible)
  - sidebar 接入: `frontend/src/components/sidebar/page-nav.tsx` 加 `Memory` 链接
  - React Router 接入: `frontend/src/router/routes.tsx` 加 `/memory` route
  - Playwright smoke: 进入 `/memory` 不报错 + 三 tab 可切换 + sidebar 链接可见

### 不在范围(Plan 7B 做)

- `MemoryGraph.tsx`(Cytoscape graph 可视化)
- `MemoryTimeline.tsx`(Timeline gantt 视图)
- `MemoryAuditLog.tsx`(audit log 列表组件)
- `MemoryOnboardingModal.tsx`(#8 用户心智 onboarding modal)
- Agent 在 chat 内显式提及 memory 来源(#8 chat-side 改造)
- 月度邮件模板 + `memory_email` service(#8 outbound digest)

Plan 7B 将复用 Plan 7A 的 API client + page shell, 把三个 placeholder 替换为真实可视化组件。

---

## 2. Spec Reference

| 落地点 | Spec 章节 | 契约引用 |
|---|---|---|
| 5 REST endpoint | spec § 9 行 965 / 972 / 978(三视图数据接口)+ § 9 行 957(/memory 路由) | shared § 10 全表 |
| user_id 防越权 | spec § 9 隐含(整 spec multi-tenant) | shared § 10 "user_id 从 auth context 取" |
| invalidate edge | spec § 14 P1 hooks #8 用户回路(行 1258 附近)+ § 9 audit log 链路 | shared § 10 第 4 endpoint |
| working blocks 显示 | spec § 7 working memory budget(行 853-872) | shared § 4 ChatMemoryWorkingBlock model |
| 路由集成到 sidebar | spec § 9 行 957"加 /memory 进 dashboard sidebar" | — |

---

## 3. File Structure(Plan 7A 创建/修改)

```
backend/app/router/
└── memory_router.py                     ← NEW(Plan 7A 主体)

backend/app/app_main.py                  ← MODIFY(include_router 加一行)

backend/tests/unit/router/
└── test_memory_router_schemas.py        ← NEW(L0: Pydantic schema 校验)

backend/tests/integration/router/
└── test_memory_router_endpoints.py      ← NEW(L1: 5 endpoint + 跨用户隔离)

frontend/src/api/
└── memoryApi.ts                         ← NEW(Plan 7A typed client)

frontend/src/api/__tests__/
└── memoryApi.test.ts                    ← NEW(L0 Vitest + msw)

frontend/src/types/
└── memory.ts                            ← NEW(MemoryNode / MemoryEdge / WorkingBlock TS 类型)

frontend/src/pages/memory/
├── index.tsx                            ← NEW(/memory page + 三 tab shell)
└── components/
    └── MemoryWorkingBlocks.tsx          ← NEW(working blocks 只读卡片)

frontend/src/pages/memory/__tests__/
└── index.test.tsx                       ← NEW(L0 Vitest + RTL: tab 切换)

frontend/src/router/routes.tsx           ← MODIFY(加 /memory route)
frontend/src/components/sidebar/page-nav.tsx ← MODIFY(加 Memory 链接)

frontend/tests/e2e/
└── memory-page.spec.ts                  ← NEW(Playwright smoke)
```

**严守契约**:
- Backend `memory_router.py` 路径严格按契约 § 1 行 47
- 5 endpoint 路径字面对应契约 § 10 行 719-723
- frontend 路径按 **§ 0 适配规则** 落地到 Vite/React 现有结构

---

## 4. Tasks(7 个 task,5-step TDD)

每 task 严格遵守:
1. 写测试(红)
2. 跑测试看红
3. 写实现
4. 跑测试看绿(含 lint / mypy)
5. git commit(不 push)

---

### Task 1 — Backend Pydantic Schemas + Empty Router 骨架

**目标**: 创建 `memory_router.py` 5 个 endpoint 的 Pydantic 输入/输出 schema + 空 router(每 endpoint 暂返 501),让 app_main 能 include_router 不报错,L0 schema test 绿。

**Spec ref**: shared § 10 全表 + spec § 9 三视图数据格式

#### Step 1.1 写 L0 schema test(红)

新建 `backend/tests/unit/router/test_memory_router_schemas.py`:

```python
"""L0: memory_router Pydantic schema validation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError


def test_graph_response_schema_round_trip():
    from app.router.memory_router import GraphResponse, GraphNodeOut, GraphEdgeOut

    node = GraphNodeOut(
        node_id=str(uuid4()),
        entity_type="Stock",
        entity_label="600519.SH",
        properties={"name": "茅台"},
    )
    edge = GraphEdgeOut(
        edge_id=str(uuid4()),
        source_node_id=node.node_id,
        target_node_id=str(uuid4()),
        rel_type="HOLDS",
        valid_from=datetime.now(timezone.utc).isoformat(),
        valid_to=None,
        importance=0.9,
        reasoning="user said hold",
    )
    body = GraphResponse(nodes=[node], edges=[edge])
    assert body.model_dump()["nodes"][0]["entity_type"] == "Stock"


def test_timeline_response_schema_round_trip():
    from app.router.memory_router import TimelineResponse, TimelineEdgeOut

    item = TimelineEdgeOut(
        edge_id=str(uuid4()),
        rel_type="HOLDS",
        source_label="User",
        target_label="600519.SH",
        valid_from=datetime.now(timezone.utc).isoformat(),
        valid_to=None,
        importance=0.5,
        invalidated_at=None,
    )
    body = TimelineResponse(items=[item], total=1, page=1, page_size=50)
    assert body.total == 1


def test_audit_response_schema_round_trip():
    from app.router.memory_router import AuditResponse, AuditEdgeOut

    item = AuditEdgeOut(
        edge_id=str(uuid4()),
        rel_type="HOLDS",
        source_label="User",
        target_label="600519.SH",
        invalidated_at=datetime.now(timezone.utc).isoformat(),
        invalidated_by_edge_id=str(uuid4()),
        original_reasoning="early extraction",
    )
    body = AuditResponse(items=[item], total=1)
    assert body.items[0].rel_type == "HOLDS"


def test_blocks_response_schema_round_trip():
    from app.router.memory_router import BlocksResponse, WorkingBlockOut

    block = WorkingBlockOut(
        block_name="persona",
        content="long-term value investor",
        token_count=12,
        max_tokens=500,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    body = BlocksResponse(blocks=[block])
    assert body.blocks[0].block_name == "persona"


def test_invalidate_response_schema_round_trip():
    from app.router.memory_router import InvalidateResponse

    body = InvalidateResponse(
        edge_id=str(uuid4()),
        invalidated_at=datetime.now(timezone.utc).isoformat(),
        status="invalidated",
    )
    assert body.status == "invalidated"


def test_invalid_importance_rejected():
    """importance 必须在 [0.2, 0.5, 0.9] 三档(契约 § 4 CHECK)."""
    from app.router.memory_router import GraphEdgeOut

    with pytest.raises(ValidationError):
        GraphEdgeOut(
            edge_id=str(uuid4()),
            source_node_id=str(uuid4()),
            target_node_id=str(uuid4()),
            rel_type="HOLDS",
            valid_from=datetime.now(timezone.utc).isoformat(),
            valid_to=None,
            importance=0.7,  # 非三档
            reasoning="x",
        )
```

跑红: `cd backend && uv run pytest tests/unit/router/test_memory_router_schemas.py -x` → ImportError(模块不存在)。

#### Step 1.2 写 router 骨架 + Pydantic schemas(实现)

新建 `backend/app/router/memory_router.py`:

```python
"""REST API for C.5 cross-session memory page.

Endpoints(契约 § 10):
  GET  /api/v0/memory/graph              graph viz nodes + edges 当前快照
  GET  /api/v0/memory/timeline           按 valid_from 排序的 edge 列表(分页 + 筛)
  GET  /api/v0/memory/audit              已 invalidate 的 edges(纠错史)
  POST /api/v0/memory/edges/{edge_id}/invalidate 用户一键否决
  GET  /api/v0/memory/blocks             working blocks 当前内容(persona / scratchpad)

Auth: 所有 endpoint 强制从 get_current_user_required 取 user_id,
path/query 不接受 user_id 参数(防越权,契约 § 10 末尾约定)。
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.router.auth_router import get_current_user_required

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v0/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Pydantic schemas — Graph view
# ---------------------------------------------------------------------------


class GraphNodeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    node_id: str
    entity_type: str   # 7 类: User / Stock / Industry / Sector / Metric / Strategy / Concept
    entity_label: str
    properties: dict


class GraphEdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str
    source_node_id: str
    target_node_id: str
    rel_type: str
    valid_from: str
    valid_to: str | None
    importance: float = Field(..., description="三档 0.9 / 0.5 / 0.2(契约 § 4)")
    reasoning: str | None

    @classmethod
    def model_validate(cls, *args, **kwargs):  # pragma: no cover (handled by validator)
        return super().model_validate(*args, **kwargs)


def _validate_importance(v: float) -> float:
    if v not in (0.2, 0.5, 0.9):
        raise ValueError(f"importance must be one of [0.2, 0.5, 0.9], got {v}")
    return v


# Re-write GraphEdgeOut with proper validator(避免上面占位):
class _GraphEdgeOutMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphEdgeOut(_GraphEdgeOutMeta):  # type: ignore[no-redef]
    edge_id: str
    source_node_id: str
    target_node_id: str
    rel_type: str
    valid_from: str
    valid_to: str | None
    importance: float
    reasoning: str | None

    @classmethod
    def __get_validators__(cls):
        yield super().model_validate

    def model_post_init(self, __context) -> None:
        if self.importance not in (0.2, 0.5, 0.9):
            raise ValueError(
                f"importance must be one of [0.2, 0.5, 0.9], got {self.importance}"
            )


class GraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


# ---------------------------------------------------------------------------
# Pydantic schemas — Timeline view
# ---------------------------------------------------------------------------


class TimelineEdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str
    rel_type: str
    source_label: str   # entity_label of source node
    target_label: str   # entity_label of target node
    valid_from: str
    valid_to: str | None
    importance: float
    invalidated_at: str | None


class TimelineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[TimelineEdgeOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Pydantic schemas — Audit view
# ---------------------------------------------------------------------------


class AuditEdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str
    rel_type: str
    source_label: str
    target_label: str
    invalidated_at: str
    invalidated_by_edge_id: str | None  # nullable: 用户手动 invalidate 时无替代 fact
    original_reasoning: str | None


class AuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AuditEdgeOut]
    total: int


# ---------------------------------------------------------------------------
# Pydantic schemas — Working Blocks
# ---------------------------------------------------------------------------


class WorkingBlockOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_name: str    # 'persona' / 'scratchpad'
    content: str
    token_count: int
    max_tokens: int
    updated_at: str


class BlocksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blocks: list[WorkingBlockOut]


# ---------------------------------------------------------------------------
# Pydantic schemas — Invalidate
# ---------------------------------------------------------------------------


class InvalidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str
    invalidated_at: str
    status: Literal["invalidated"]


# ---------------------------------------------------------------------------
# Endpoints — 暂返 501,Task 2-5 填实
# ---------------------------------------------------------------------------


@router.get("/graph", response_model=GraphResponse)
def get_graph(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> GraphResponse:
    raise HTTPException(status_code=501, detail="Task 2 implements")


@router.get("/timeline", response_model=TimelineResponse)
def get_timeline(
    rel_type: str | None = None,
    entity_label: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> TimelineResponse:
    raise HTTPException(status_code=501, detail="Task 3 implements")


@router.get("/audit", response_model=AuditResponse)
def get_audit(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> AuditResponse:
    raise HTTPException(status_code=501, detail="Task 4 implements")


@router.post("/edges/{edge_id}/invalidate", response_model=InvalidateResponse)
def invalidate_edge(
    edge_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> InvalidateResponse:
    raise HTTPException(status_code=501, detail="Task 5 implements")


@router.get("/blocks", response_model=BlocksResponse)
def get_blocks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> BlocksResponse:
    raise HTTPException(status_code=501, detail="Task 6 implements")
```

**注意**: 上面 `GraphEdgeOut` 的 importance validator 写法是 Pydantic v2 风格。实施期可改用更简洁的 `field_validator`:

```python
from pydantic import field_validator

class GraphEdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... 字段 ...

    @field_validator("importance")
    @classmethod
    def _check_importance(cls, v: float) -> float:
        if v not in (0.2, 0.5, 0.9):
            raise ValueError(f"importance must be one of [0.2, 0.5, 0.9], got {v}")
        return v
```

实施时直接用 `field_validator` 版本(更简洁,本仓库 Pydantic v2)。

#### Step 1.3 注册到 app_main

修改 `backend/app/app_main.py`,在 `monitoring_router` 那一行后加:

```python
from app.router.memory_router import router as memory_router  # noqa: E402

# ... 在 include_router 段落 ...
app.include_router(memory_router)  # C.5 — /api/v0/memory (cross-session memory page)
```

(具体行号: 当前 monitoring_router include 在第 244 行附近,memory_router 加在 chat_router_module 之前或之后均可。建议跟 chat_router_module 同段落)

#### Step 1.4 跑测试看绿 + lint

```bash
cd backend
uv run pytest tests/unit/router/test_memory_router_schemas.py -x -v
uv run ruff check app/router/memory_router.py
uv run mypy app/router/memory_router.py
```

全绿。

#### Step 1.5 commit

```bash
git add backend/app/router/memory_router.py backend/app/app_main.py \
  backend/tests/unit/router/test_memory_router_schemas.py
git commit -m "feat(c5-plan7a): memory_router skeleton + 5 Pydantic schemas + L0 test

5 endpoints stubbed with HTTP 501; schema round-trip + importance 三档校验绿.
契约 § 1 + § 10 对齐."
```

---

### Task 2 — `GET /memory/graph` 实现 + L1 Test

**目标**: graph endpoint 返当前快照(`valid_to IS NULL AND invalidated_at IS NULL`)的 nodes + edges,跨用户隔离。

**Spec ref**: spec § 9 行 965 + § 5 路径 3 graph 视图

#### Step 2.1 写 L1 integration test(红)

新建 `backend/tests/integration/router/test_memory_router_endpoints.py`(本 task 只写 graph 部分,后面 task 续加):

```python
"""L1: memory_router endpoints — in-memory sqlite + fake_auth.

Tables: User + chat_memory_episodes/nodes/edges/working_blocks.
跨用户隔离 + 防越权 case.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from app.memory.models import (
    ChatMemoryEdge,
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryWorkingBlock,
)
from app.models.user import User
from sqlalchemy.orm import Session


# Helpers ----------------------------------------------------------------


def _mk_user_node(session: Session, user_id: str) -> ChatMemoryNode:
    n = ChatMemoryNode(
        node_id=uuid4(),
        user_id=user_id,
        entity_type="User",
        entity_label="User",
        properties={},
    )
    session.add(n)
    session.flush()
    return n


def _mk_stock_node(session: Session, user_id: str, ts_code: str) -> ChatMemoryNode:
    n = ChatMemoryNode(
        node_id=uuid4(),
        user_id=user_id,
        entity_type="Stock",
        entity_label=ts_code,
        properties={"name": ts_code},
    )
    session.add(n)
    session.flush()
    return n


def _mk_episode(session: Session, user_id: str, session_id: str | None = None) -> ChatMemoryEpisode:
    ep = ChatMemoryEpisode(
        episode_id=uuid4(),
        user_id=user_id,
        session_id=session_id or uuid4(),
        episode_index=1,
        user_message_text="重仓茅台",
        agent_response_text="ok",
        source_kind="chat_turn",
    )
    session.add(ep)
    session.flush()
    return ep


def _mk_edge(
    session: Session,
    user_id: str,
    src: ChatMemoryNode,
    tgt: ChatMemoryNode,
    rel: str = "HOLDS",
    importance: float = 0.9,
    valid_to=None,
    invalidated_at=None,
    episode: ChatMemoryEpisode | None = None,
) -> ChatMemoryEdge:
    if episode is None:
        episode = _mk_episode(session, user_id)
    e = ChatMemoryEdge(
        edge_id=uuid4(),
        user_id=user_id,
        source_node_id=src.node_id,
        target_node_id=tgt.node_id,
        rel_type=rel,
        valid_from=datetime.now(timezone.utc) - timedelta(days=1),
        valid_to=valid_to,
        invalidated_at=invalidated_at,
        source_episode_id=episode.episode_id,
        importance=importance,
        reasoning="test",
        properties={},
    )
    session.add(e)
    session.commit()
    return e


# Tests --------------------------------------------------------------------


def test_get_graph_returns_current_snapshot_only(client, session, fake_auth):
    """current snapshot = valid_to IS NULL AND invalidated_at IS NULL."""
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")
    stock2 = _mk_stock_node(session, uid, "300750.SZ")

    # current
    _mk_edge(session, uid, user_node, stock, rel="HOLDS")
    # ended (valid_to set) — 不在快照
    _mk_edge(
        session, uid, user_node, stock2, rel="HOLDS",
        valid_to=datetime.now(timezone.utc),
    )
    # invalidated — 不在快照
    _mk_edge(
        session, uid, user_node, stock2, rel="WATCHES",
        invalidated_at=datetime.now(timezone.utc),
    )

    r = client.get("/api/v0/memory/graph", headers=fake_auth["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["edges"]) == 1
    assert body["edges"][0]["rel_type"] == "HOLDS"
    # nodes 包含被引用的(user + stock + stock2 — 因为 stock2 也被 ended/invalidated edge 引用,
    # 实施可选只返当前 edges 引用的节点; 这里测试约定 = 只返当前 edges 涉及的节点)
    node_labels = {n["entity_label"] for n in body["nodes"]}
    assert "600519.SH" in node_labels
    assert "User" in node_labels


def test_get_graph_does_not_leak_other_user(client, session, fake_auth):
    own = fake_auth["user_id"]
    other = User(
        id=str(uuid4()), username=f"o-{uuid4().hex[:6]}",
        email=f"o-{uuid4().hex[:6]}@x", hashed_password="x", is_active=True,
    )
    session.add(other)
    session.flush()

    own_user = _mk_user_node(session, own)
    own_stock = _mk_stock_node(session, own, "600519.SH")
    _mk_edge(session, own, own_user, own_stock)

    other_user = _mk_user_node(session, str(other.id))
    other_stock = _mk_stock_node(session, str(other.id), "300750.SZ")
    _mk_edge(session, str(other.id), other_user, other_stock)

    r = client.get("/api/v0/memory/graph", headers=fake_auth["headers"])
    assert r.status_code == 200
    body = r.json()
    labels = {n["entity_label"] for n in body["nodes"]}
    assert "300750.SZ" not in labels
```

**注意**: 本 test file 复用 `backend/tests/integration/router/conftest.py` 已 ship 的 `client` / `session` / `fake_auth` fixtures。但需要扩展 `session` fixture 让它创建 4 张 memory 表 — 由 Step 2.2 处理。

#### Step 2.2 扩展 conftest.py 加 memory 表

修改 `backend/tests/integration/router/conftest.py` 的 `session` fixture,在 `Notification.__table__.create(engine)` 后加:

```python
# C.5 memory 4 表(Plan 7A 起)— sqlite-compatible 字段 only;
# 真 PG 测试在 backend/tests/integration/memory/(由 Plan 1 创建,Plan 7A 不依赖)
from app.memory.models import (
    ChatMemoryEpisode,
    ChatMemoryNode,
    ChatMemoryEdge,
    ChatMemoryWorkingBlock,
)

ChatMemoryEpisode.__table__.create(engine)
ChatMemoryNode.__table__.create(engine)
ChatMemoryEdge.__table__.create(engine)
ChatMemoryWorkingBlock.__table__.create(engine)
```

**潜在坑**: Plan 1 ship 的 model 用 PG-only 类型(`PgUUID(as_uuid=True)` / `JSONB` / `TSVECTOR`)。sqlite override 时 `PgUUID` 通常 fallback 到 CHAR(32), `JSONB` 不行需要 `with_variant(JSON, "sqlite")`。Plan 1 ship 时若已加 variant 则直接可用; 若没加则本 task 的修复路径:

- 优先方案: 在 `app/memory/models.py` 加 `JSONB().with_variant(JSON, "sqlite")` + `TSVECTOR().with_variant(Text, "sqlite")`。**但这是 Plan 1 主责**,Plan 7A 不重新决策。
- 备选方案(如果 Plan 1 没加 variant): 本 test file 标记 `pytest.mark.requires_pg`,在 CI 用 real PG fixture。本 plan 假设 Plan 1 已加 variant(spec § 2 schema 实现期会注意 sqlite override)。

实施期撞实策略: 跑红 Step 2.1, 看到 sqlite create_all 报错就回 Plan 1 patch model variant; 没报错就直接进 Step 2.3。

跑红:

```bash
cd backend
uv run pytest tests/integration/router/test_memory_router_endpoints.py::test_get_graph_returns_current_snapshot_only -x
```

预期红(endpoint 返 501)。

#### Step 2.3 写 graph endpoint 实现

修改 `backend/app/router/memory_router.py` 的 `get_graph`:

```python
@router.get("/graph", response_model=GraphResponse)
def get_graph(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> GraphResponse:
    """Return current snapshot: edges with valid_to IS NULL AND invalidated_at IS NULL.

    Spec § 9 行 965, § 5 路径 3.
    """
    from app.memory.models import ChatMemoryEdge, ChatMemoryNode

    edges = (
        db.query(ChatMemoryEdge)
        .filter(
            ChatMemoryEdge.user_id == user.id,
            ChatMemoryEdge.valid_to.is_(None),
            ChatMemoryEdge.invalidated_at.is_(None),
        )
        .all()
    )

    # 收集涉及的 node ids
    node_ids: set = set()
    for e in edges:
        node_ids.add(e.source_node_id)
        node_ids.add(e.target_node_id)

    nodes_q = []
    if node_ids:
        nodes_q = (
            db.query(ChatMemoryNode)
            .filter(
                ChatMemoryNode.user_id == user.id,
                ChatMemoryNode.node_id.in_(node_ids),
            )
            .all()
        )

    return GraphResponse(
        nodes=[
            GraphNodeOut(
                node_id=str(n.node_id),
                entity_type=n.entity_type,
                entity_label=n.entity_label,
                properties=n.properties or {},
            )
            for n in nodes_q
        ],
        edges=[
            GraphEdgeOut(
                edge_id=str(e.edge_id),
                source_node_id=str(e.source_node_id),
                target_node_id=str(e.target_node_id),
                rel_type=e.rel_type,
                valid_from=e.valid_from.isoformat(),
                valid_to=e.valid_to.isoformat() if e.valid_to else None,
                importance=e.importance,
                reasoning=e.reasoning,
            )
            for e in edges
        ],
    )
```

#### Step 2.4 跑测试看绿

```bash
cd backend
uv run pytest tests/integration/router/test_memory_router_endpoints.py -x -v
uv run mypy app/router/memory_router.py
```

#### Step 2.5 commit

```bash
git add backend/app/router/memory_router.py \
  backend/tests/integration/router/test_memory_router_endpoints.py \
  backend/tests/integration/router/conftest.py
git commit -m "feat(c5-plan7a): GET /memory/graph 当前快照 + 跨用户隔离 L1 test

valid_to IS NULL AND invalidated_at IS NULL 过滤; 只返被引用 nodes."
```

---

### Task 3 — `GET /memory/timeline` 实现 + L1 Test

**目标**: timeline endpoint 返按 `valid_from DESC` 排序的 edge 列表,支持 `rel_type` / `entity_label` 筛 + 分页。

**Spec ref**: spec § 9 行 967-972

#### Step 3.1 写 L1 test(红)

追加到 `test_memory_router_endpoints.py`:

```python
def test_get_timeline_returns_paginated_sorted(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")

    # 创建 3 条 edge,valid_from 间隔 1 天
    base = datetime.now(timezone.utc) - timedelta(days=10)
    for i in range(3):
        e = ChatMemoryEdge(
            edge_id=uuid4(),
            user_id=uid,
            source_node_id=user_node.node_id,
            target_node_id=stock.node_id,
            rel_type="HOLDS",
            valid_from=base + timedelta(days=i),
            valid_to=None,
            invalidated_at=None,
            source_episode_id=_mk_episode(session, uid).episode_id,
            importance=0.9,
            reasoning=f"e{i}",
            properties={},
        )
        session.add(e)
    session.commit()

    r = client.get("/api/v0/memory/timeline", headers=fake_auth["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["page"] == 1
    # DESC: 最新的在前
    valid_froms = [item["valid_from"] for item in body["items"]]
    assert valid_froms == sorted(valid_froms, reverse=True)


def test_get_timeline_filters_by_rel_type(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")

    _mk_edge(session, uid, user_node, stock, rel="HOLDS")
    _mk_edge(session, uid, user_node, stock, rel="WATCHES")

    r = client.get(
        "/api/v0/memory/timeline?rel_type=HOLDS",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["rel_type"] == "HOLDS"


def test_get_timeline_filters_by_entity_label(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock_a = _mk_stock_node(session, uid, "600519.SH")
    stock_b = _mk_stock_node(session, uid, "300750.SZ")

    _mk_edge(session, uid, user_node, stock_a, rel="HOLDS")
    _mk_edge(session, uid, user_node, stock_b, rel="HOLDS")

    r = client.get(
        "/api/v0/memory/timeline?entity_label=600519.SH",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["target_label"] == "600519.SH"


def test_get_timeline_pagination(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")
    for _ in range(5):
        _mk_edge(session, uid, user_node, stock, rel="HOLDS")

    r = client.get(
        "/api/v0/memory/timeline?page=2&page_size=2",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert body["total"] == 5


def test_get_timeline_does_not_leak_other_user(client, session, fake_auth):
    own = fake_auth["user_id"]
    other = User(
        id=str(uuid4()), username=f"t-{uuid4().hex[:6]}",
        email=f"t-{uuid4().hex[:6]}@x", hashed_password="x", is_active=True,
    )
    session.add(other)
    session.flush()

    own_u = _mk_user_node(session, own)
    own_s = _mk_stock_node(session, own, "600519.SH")
    _mk_edge(session, own, own_u, own_s)

    o_u = _mk_user_node(session, str(other.id))
    o_s = _mk_stock_node(session, str(other.id), "300750.SZ")
    _mk_edge(session, str(other.id), o_u, o_s)

    r = client.get("/api/v0/memory/timeline", headers=fake_auth["headers"])
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(item["target_label"] != "300750.SZ" for item in items)
```

跑红: 501。

#### Step 3.2 写 timeline 实现

替换 `get_timeline`:

```python
@router.get("/timeline", response_model=TimelineResponse)
def get_timeline(
    rel_type: str | None = None,
    entity_label: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> TimelineResponse:
    """spec § 9 行 967 — 按 valid_from DESC 排序,支持 rel_type / entity_label 筛."""
    from sqlalchemy import or_
    from app.memory.models import ChatMemoryEdge, ChatMemoryNode

    q = db.query(ChatMemoryEdge).filter(ChatMemoryEdge.user_id == user.id)

    if rel_type:
        q = q.filter(ChatMemoryEdge.rel_type == rel_type)

    if entity_label:
        # join nodes 表查 entity_label 匹配 src 或 tgt
        matching_node_ids = [
            n.node_id
            for n in db.query(ChatMemoryNode)
            .filter(
                ChatMemoryNode.user_id == user.id,
                ChatMemoryNode.entity_label == entity_label,
            )
            .all()
        ]
        if not matching_node_ids:
            return TimelineResponse(items=[], total=0, page=page, page_size=page_size)
        q = q.filter(
            or_(
                ChatMemoryEdge.source_node_id.in_(matching_node_ids),
                ChatMemoryEdge.target_node_id.in_(matching_node_ids),
            )
        )

    total = q.count()
    edges = (
        q.order_by(ChatMemoryEdge.valid_from.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 反查 src / tgt label
    all_node_ids: set = set()
    for e in edges:
        all_node_ids.add(e.source_node_id)
        all_node_ids.add(e.target_node_id)
    label_map: dict = {}
    if all_node_ids:
        for n in (
            db.query(ChatMemoryNode)
            .filter(ChatMemoryNode.node_id.in_(all_node_ids))
            .all()
        ):
            label_map[n.node_id] = n.entity_label

    items = [
        TimelineEdgeOut(
            edge_id=str(e.edge_id),
            rel_type=e.rel_type,
            source_label=label_map.get(e.source_node_id, "?"),
            target_label=label_map.get(e.target_node_id, "?"),
            valid_from=e.valid_from.isoformat(),
            valid_to=e.valid_to.isoformat() if e.valid_to else None,
            importance=e.importance,
            invalidated_at=e.invalidated_at.isoformat() if e.invalidated_at else None,
        )
        for e in edges
    ]
    return TimelineResponse(items=items, total=total, page=page, page_size=page_size)
```

#### Step 3.3 跑测 + lint

```bash
uv run pytest tests/integration/router/test_memory_router_endpoints.py -x -v -k "timeline"
uv run mypy app/router/memory_router.py
```

#### Step 3.4 commit

```bash
git add backend/app/router/memory_router.py \
  backend/tests/integration/router/test_memory_router_endpoints.py
git commit -m "feat(c5-plan7a): GET /memory/timeline DESC 排序 + 筛 + 分页

rel_type / entity_label query 支持; 5 个 case 含跨用户隔离."
```

---

### Task 4 — `GET /memory/audit` 实现 + L1 Test

**目标**: audit endpoint 返 `invalidated_at IS NOT NULL` 的 edges,带 `invalidated_by_edge_id`(由 Plan 2 conflict_resolver 在 invalidate 时写入 properties JSONB,Plan 7A 从 properties 读)。

**Spec ref**: spec § 9 行 974-978

#### Step 4.1 测试(红)

追加:

```python
def test_get_audit_returns_only_invalidated(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")

    # current(不在 audit)
    _mk_edge(session, uid, user_node, stock, rel="HOLDS")
    # invalidated(在 audit)
    inv_eid = uuid4()
    e = ChatMemoryEdge(
        edge_id=inv_eid,
        user_id=uid,
        source_node_id=user_node.node_id,
        target_node_id=stock.node_id,
        rel_type="WATCHES",
        valid_from=datetime.now(timezone.utc) - timedelta(days=5),
        valid_to=None,
        invalidated_at=datetime.now(timezone.utc),
        source_episode_id=_mk_episode(session, uid).episode_id,
        importance=0.5,
        reasoning="bad early extraction",
        properties={"invalidated_by_edge_id": str(uuid4())},
    )
    session.add(e)
    session.commit()

    r = client.get("/api/v0/memory/audit", headers=fake_auth["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["edge_id"] == str(inv_eid)
    assert item["invalidated_by_edge_id"] is not None


def test_get_audit_does_not_leak_other_user(client, session, fake_auth):
    uid = fake_auth["user_id"]
    other = User(
        id=str(uuid4()), username=f"a-{uuid4().hex[:6]}",
        email=f"a-{uuid4().hex[:6]}@x", hashed_password="x", is_active=True,
    )
    session.add(other)
    session.flush()

    o_u = _mk_user_node(session, str(other.id))
    o_s = _mk_stock_node(session, str(other.id), "999999.SH")
    _mk_edge(
        session, str(other.id), o_u, o_s, rel="HOLDS",
        invalidated_at=datetime.now(timezone.utc),
    )

    r = client.get("/api/v0/memory/audit", headers=fake_auth["headers"])
    assert r.status_code == 200
    assert r.json()["total"] == 0
```

#### Step 4.2 实现

替换 `get_audit`:

```python
@router.get("/audit", response_model=AuditResponse)
def get_audit(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> AuditResponse:
    """spec § 9 行 974 — invalidated_at IS NOT NULL 的纠错史."""
    from app.memory.models import ChatMemoryEdge, ChatMemoryNode

    edges = (
        db.query(ChatMemoryEdge)
        .filter(
            ChatMemoryEdge.user_id == user.id,
            ChatMemoryEdge.invalidated_at.is_not(None),
        )
        .order_by(ChatMemoryEdge.invalidated_at.desc())
        .all()
    )

    all_node_ids: set = set()
    for e in edges:
        all_node_ids.add(e.source_node_id)
        all_node_ids.add(e.target_node_id)
    label_map: dict = {}
    if all_node_ids:
        for n in (
            db.query(ChatMemoryNode)
            .filter(ChatMemoryNode.node_id.in_(all_node_ids))
            .all()
        ):
            label_map[n.node_id] = n.entity_label

    items = [
        AuditEdgeOut(
            edge_id=str(e.edge_id),
            rel_type=e.rel_type,
            source_label=label_map.get(e.source_node_id, "?"),
            target_label=label_map.get(e.target_node_id, "?"),
            invalidated_at=e.invalidated_at.isoformat(),
            invalidated_by_edge_id=(e.properties or {}).get("invalidated_by_edge_id"),
            original_reasoning=e.reasoning,
        )
        for e in edges
    ]
    return AuditResponse(items=items, total=len(items))
```

#### Step 4.3 跑测 + commit

```bash
uv run pytest tests/integration/router/test_memory_router_endpoints.py -x -v -k "audit"
uv run mypy app/router/memory_router.py
```

```bash
git add backend/app/router/memory_router.py \
  backend/tests/integration/router/test_memory_router_endpoints.py
git commit -m "feat(c5-plan7a): GET /memory/audit invalidated edges 列表

按 invalidated_at DESC 排序; 从 properties JSONB 读 invalidated_by_edge_id."
```

---

### Task 5 — `POST /memory/edges/{edge_id}/invalidate` 实现 + L1 Test

**目标**: 用户一键否决 — 反查 user_id 防越权,设 `invalidated_at = now()`,写 `properties.invalidated_by = "user_manual"`。

**Spec ref**: spec § 14 P1 hooks #8 用户回路 first-class hook

**幂等性**: 已 invalidated 的 edge 重复 POST 返 400(避免覆盖原 invalidated_at 时间戳混淆 audit log)。

#### Step 5.1 测试(红)

追加:

```python
def test_invalidate_edge_marks_invalidated_at(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")
    edge = _mk_edge(session, uid, user_node, stock, rel="HOLDS")
    eid = str(edge.edge_id)

    r = client.post(
        f"/api/v0/memory/edges/{eid}/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "invalidated"
    assert body["edge_id"] == eid

    # DB side check
    session.refresh(edge)
    assert edge.invalidated_at is not None
    assert (edge.properties or {}).get("invalidated_by") == "user_manual"


def test_invalidate_edge_cross_user_returns_404(client, session, fake_auth):
    other = User(
        id=str(uuid4()), username=f"x-{uuid4().hex[:6]}",
        email=f"x-{uuid4().hex[:6]}@x", hashed_password="x", is_active=True,
    )
    session.add(other)
    session.flush()
    o_u = _mk_user_node(session, str(other.id))
    o_s = _mk_stock_node(session, str(other.id), "999999.SH")
    edge = _mk_edge(session, str(other.id), o_u, o_s, rel="HOLDS")

    r = client.post(
        f"/api/v0/memory/edges/{edge.edge_id}/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 404


def test_invalidate_edge_already_invalidated_returns_400(client, session, fake_auth):
    uid = fake_auth["user_id"]
    user_node = _mk_user_node(session, uid)
    stock = _mk_stock_node(session, uid, "600519.SH")
    edge = _mk_edge(
        session, uid, user_node, stock, rel="HOLDS",
        invalidated_at=datetime.now(timezone.utc),
    )

    r = client.post(
        f"/api/v0/memory/edges/{edge.edge_id}/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 400


def test_invalidate_edge_not_found_returns_404(client, session, fake_auth):
    r = client.post(
        f"/api/v0/memory/edges/{uuid4()}/invalidate",
        headers=fake_auth["headers"],
    )
    assert r.status_code == 404
```

#### Step 5.2 实现

替换 `invalidate_edge`:

```python
@router.post("/edges/{edge_id}/invalidate", response_model=InvalidateResponse)
def invalidate_edge(
    edge_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> InvalidateResponse:
    """spec § 14 P1 #8 — 用户一键否决.

    跨用户访问 → 404(防越权 user_id 不在 path/query)。
    已 invalidated 重复 POST → 400(防覆盖 audit log 时间戳)。
    """
    from datetime import datetime, timezone
    from uuid import UUID
    from app.memory.models import ChatMemoryEdge

    try:
        eid = UUID(edge_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="edge not found") from None

    edge = db.query(ChatMemoryEdge).filter(ChatMemoryEdge.edge_id == eid).first()
    if edge is None or str(edge.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="edge not found")
    if edge.invalidated_at is not None:
        raise HTTPException(
            status_code=400, detail="edge already invalidated"
        )

    now = datetime.now(timezone.utc)
    edge.invalidated_at = now
    new_props = dict(edge.properties or {})
    new_props["invalidated_by"] = "user_manual"
    edge.properties = new_props
    db.commit()

    return InvalidateResponse(
        edge_id=str(edge.edge_id),
        invalidated_at=now.isoformat(),
        status="invalidated",
    )
```

**注意 SQLAlchemy 坑**: JSONB 字段直接 mutate 不触发 dirty。必须**重新赋值整 dict**(如上 `edge.properties = new_props`)。Plan 1 ship 的 model 应该已经标了 `MutableDict.as_mutable`,如果没有,我们这里强制重新赋整个 dict 是正确做法。

#### Step 5.3 跑测 + commit

```bash
uv run pytest tests/integration/router/test_memory_router_endpoints.py -x -v -k "invalidate"
uv run mypy app/router/memory_router.py
```

```bash
git add backend/app/router/memory_router.py \
  backend/tests/integration/router/test_memory_router_endpoints.py
git commit -m "feat(c5-plan7a): POST /memory/edges/{id}/invalidate 用户一键否决

跨用户 → 404, 已 invalidated → 400; properties.invalidated_by='user_manual'."
```

---

### Task 6 — `GET /memory/blocks` 实现 + L1 Test

**目标**: 返当前 user 的 working blocks(persona / scratchpad)。

**Spec ref**: spec § 7 working memory budget(行 853-872)+ shared § 4 ChatMemoryWorkingBlock model

#### Step 6.1 测试(红)

追加:

```python
def test_get_blocks_returns_user_blocks(client, session, fake_auth):
    uid = fake_auth["user_id"]
    persona = ChatMemoryWorkingBlock(
        block_id=uuid4(),
        user_id=uid,
        block_name="persona",
        content="long-term value investor",
        token_count=10,
        max_tokens=500,
    )
    scratch = ChatMemoryWorkingBlock(
        block_id=uuid4(),
        user_id=uid,
        block_name="scratchpad",
        content="thinking about 茅台",
        token_count=5,
        max_tokens=1000,
    )
    session.add_all([persona, scratch])
    session.commit()

    r = client.get("/api/v0/memory/blocks", headers=fake_auth["headers"])
    assert r.status_code == 200
    blocks = r.json()["blocks"]
    assert len(blocks) == 2
    names = {b["block_name"] for b in blocks}
    assert names == {"persona", "scratchpad"}


def test_get_blocks_empty_when_no_data(client, session, fake_auth):
    r = client.get("/api/v0/memory/blocks", headers=fake_auth["headers"])
    assert r.status_code == 200
    assert r.json()["blocks"] == []


def test_get_blocks_does_not_leak_other_user(client, session, fake_auth):
    uid = fake_auth["user_id"]
    other = User(
        id=str(uuid4()), username=f"b-{uuid4().hex[:6]}",
        email=f"b-{uuid4().hex[:6]}@x", hashed_password="x", is_active=True,
    )
    session.add(other)
    session.flush()
    session.add(ChatMemoryWorkingBlock(
        block_id=uuid4(),
        user_id=str(other.id),
        block_name="persona",
        content="leaked",
        token_count=2,
        max_tokens=500,
    ))
    session.commit()

    r = client.get("/api/v0/memory/blocks", headers=fake_auth["headers"])
    assert r.status_code == 200
    contents = [b["content"] for b in r.json()["blocks"]]
    assert "leaked" not in contents
```

#### Step 6.2 实现

替换 `get_blocks`:

```python
@router.get("/blocks", response_model=BlocksResponse)
def get_blocks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_required),
) -> BlocksResponse:
    """spec § 7 working memory budget — 返 persona / scratchpad 当前内容(只读)."""
    from app.memory.models import ChatMemoryWorkingBlock

    blocks = (
        db.query(ChatMemoryWorkingBlock)
        .filter(ChatMemoryWorkingBlock.user_id == user.id)
        .order_by(ChatMemoryWorkingBlock.block_name.asc())
        .all()
    )
    return BlocksResponse(
        blocks=[
            WorkingBlockOut(
                block_name=b.block_name,
                content=b.content or "",
                token_count=b.token_count,
                max_tokens=b.max_tokens,
                updated_at=b.updated_at.isoformat() if b.updated_at else "",
            )
            for b in blocks
        ]
    )
```

#### Step 6.3 跑测 + commit

```bash
uv run pytest tests/integration/router/test_memory_router_endpoints.py -x -v -k "blocks"
uv run mypy app/router/memory_router.py
uv run ruff check app/router/memory_router.py
```

```bash
git add backend/app/router/memory_router.py \
  backend/tests/integration/router/test_memory_router_endpoints.py
git commit -m "feat(c5-plan7a): GET /memory/blocks working blocks 只读 + 跨用户隔离

5 endpoint backend 全部 ship; spec § 7 working memory budget 落地."
```

---

### Task 7 — Frontend API Client + Types + Vitest

**目标**: 创建 typed API client + Vitest msw test。覆盖 5 endpoint。

**Spec ref**: shared § 10 endpoint table

#### Step 7.1 写 TS 类型

新建 `frontend/src/types/memory.ts`:

```typescript
// C.5 cross-session memory — frontend types
// 严格对应 backend memory_router.py Pydantic schemas

export interface MemoryNode {
  node_id: string
  entity_type:
    | 'User'
    | 'Stock'
    | 'Industry'
    | 'Sector'
    | 'Metric'
    | 'Strategy'
    | 'Concept'
  entity_label: string
  properties: Record<string, unknown>
}

export interface MemoryEdge {
  edge_id: string
  source_node_id: string
  target_node_id: string
  rel_type: string
  valid_from: string  // ISO 8601
  valid_to: string | null
  importance: 0.2 | 0.5 | 0.9
  reasoning: string | null
}

export interface GraphResponse {
  nodes: MemoryNode[]
  edges: MemoryEdge[]
}

export interface TimelineEdge {
  edge_id: string
  rel_type: string
  source_label: string
  target_label: string
  valid_from: string
  valid_to: string | null
  importance: number
  invalidated_at: string | null
}

export interface TimelineResponse {
  items: TimelineEdge[]
  total: number
  page: number
  page_size: number
}

export interface AuditEdge {
  edge_id: string
  rel_type: string
  source_label: string
  target_label: string
  invalidated_at: string
  invalidated_by_edge_id: string | null
  original_reasoning: string | null
}

export interface AuditResponse {
  items: AuditEdge[]
  total: number
}

export interface WorkingBlock {
  block_name: 'persona' | 'scratchpad'
  content: string
  token_count: number
  max_tokens: number
  updated_at: string
}

export interface BlocksResponse {
  blocks: WorkingBlock[]
}

export interface InvalidateResponse {
  edge_id: string
  invalidated_at: string
  status: 'invalidated'
}

export interface TimelineFilters {
  rel_type?: string
  entity_label?: string
  page?: number
  page_size?: number
}
```

#### Step 7.2 写 Vitest test(红)

新建 `frontend/src/api/__tests__/memoryApi.test.ts`:

```typescript
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/test-utils/msw-server'
import {
  fetchMemoryGraph,
  fetchMemoryTimeline,
  fetchMemoryAudit,
  fetchMemoryBlocks,
  invalidateMemoryEdge,
} from '@/api/memoryApi'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

describe('memoryApi', () => {
  it('fetchMemoryGraph GETs /api/v0/memory/graph', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/graph`, () =>
        HttpResponse.json({
          nodes: [
            {
              node_id: 'n1',
              entity_type: 'Stock',
              entity_label: '600519.SH',
              properties: { name: '茅台' },
            },
          ],
          edges: [],
        }),
      ),
    )
    const res = await fetchMemoryGraph()
    expect(res.nodes).toHaveLength(1)
    expect(res.nodes[0].entity_label).toBe('600519.SH')
  })

  it('fetchMemoryTimeline GETs with query params', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/timeline`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('rel_type')).toBe('HOLDS')
        expect(url.searchParams.get('page')).toBe('2')
        return HttpResponse.json({
          items: [],
          total: 0,
          page: 2,
          page_size: 50,
        })
      }),
    )
    const res = await fetchMemoryTimeline({ rel_type: 'HOLDS', page: 2 })
    expect(res.page).toBe(2)
  })

  it('fetchMemoryAudit GETs /audit', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/audit`, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    )
    const res = await fetchMemoryAudit()
    expect(res.total).toBe(0)
  })

  it('fetchMemoryBlocks GETs /blocks', async () => {
    server.use(
      http.get(`${API_BASE}/api/v0/memory/blocks`, () =>
        HttpResponse.json({
          blocks: [
            {
              block_name: 'persona',
              content: 'value investor',
              token_count: 5,
              max_tokens: 500,
              updated_at: '2026-05-11T00:00:00Z',
            },
          ],
        }),
      ),
    )
    const res = await fetchMemoryBlocks()
    expect(res.blocks[0].block_name).toBe('persona')
  })

  it('invalidateMemoryEdge POSTs to /edges/{id}/invalidate', async () => {
    server.use(
      http.post(
        `${API_BASE}/api/v0/memory/edges/e1/invalidate`,
        () =>
          HttpResponse.json({
            edge_id: 'e1',
            invalidated_at: '2026-05-11T01:00:00Z',
            status: 'invalidated',
          }),
      ),
    )
    const res = await invalidateMemoryEdge('e1')
    expect(res.status).toBe('invalidated')
  })

  it('invalidateMemoryEdge throws on 400 (already invalidated)', async () => {
    server.use(
      http.post(
        `${API_BASE}/api/v0/memory/edges/e2/invalidate`,
        () => new HttpResponse(null, { status: 400 }),
      ),
    )
    await expect(invalidateMemoryEdge('e2')).rejects.toThrow()
  })
})
```

跑红: `cd frontend && npm test -- src/api/__tests__/memoryApi.test.ts` → ImportError。

#### Step 7.3 写 client

新建 `frontend/src/api/memoryApi.ts`:

```typescript
// C.5 cross-session memory — typed API client
// 契约 § 10 5 endpoint:
//   GET  /api/v0/memory/graph
//   GET  /api/v0/memory/timeline
//   GET  /api/v0/memory/audit
//   POST /api/v0/memory/edges/{id}/invalidate
//   GET  /api/v0/memory/blocks

import type {
  AuditResponse,
  BlocksResponse,
  GraphResponse,
  InvalidateResponse,
  TimelineFilters,
  TimelineResponse,
} from '@/types/memory'

const BASE = '/api/v0/memory'

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }
  return (await res.json()) as T
}

export async function fetchMemoryGraph(): Promise<GraphResponse> {
  return fetchJson<GraphResponse>(`${BASE}/graph`)
}

export async function fetchMemoryTimeline(
  filters: TimelineFilters = {},
): Promise<TimelineResponse> {
  const sp = new URLSearchParams()
  if (filters.rel_type) sp.set('rel_type', filters.rel_type)
  if (filters.entity_label) sp.set('entity_label', filters.entity_label)
  if (filters.page) sp.set('page', String(filters.page))
  if (filters.page_size) sp.set('page_size', String(filters.page_size))
  const qs = sp.toString()
  return fetchJson<TimelineResponse>(`${BASE}/timeline${qs ? `?${qs}` : ''}`)
}

export async function fetchMemoryAudit(): Promise<AuditResponse> {
  return fetchJson<AuditResponse>(`${BASE}/audit`)
}

export async function fetchMemoryBlocks(): Promise<BlocksResponse> {
  return fetchJson<BlocksResponse>(`${BASE}/blocks`)
}

export async function invalidateMemoryEdge(
  edgeId: string,
): Promise<InvalidateResponse> {
  return fetchJson<InvalidateResponse>(
    `${BASE}/edges/${encodeURIComponent(edgeId)}/invalidate`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' } },
  )
}
```

#### Step 7.4 跑测看绿

```bash
cd frontend
npm test -- src/api/__tests__/memoryApi.test.ts
npm run lint
npm run typecheck
```

#### Step 7.5 commit

```bash
git add frontend/src/types/memory.ts \
  frontend/src/api/memoryApi.ts \
  frontend/src/api/__tests__/memoryApi.test.ts
git commit -m "feat(c5-plan7a): frontend memoryApi 5 endpoint typed client + Vitest

types/memory.ts strict types; msw test 含 400 错误路径."
```

---

### Task 8 — `/memory` Page Shell + Sidebar + Router + Playwright Smoke

**目标**: 用现有 antd / page-layout 风格搭 `/memory` page,三个 tab(Graph / Timeline / Audit)+ 右栏 working blocks 卡片。tab 内容暂用 placeholder `<div>` 占位,Plan 7B 替换。Sidebar 加链接,React Router 加 route,Playwright smoke 跑通。

**Spec ref**: spec § 9 行 957(sidebar 集成)+ 行 982(AppShell 复用)

#### Step 8.1 写 Vitest RTL test(红)

新建 `frontend/src/pages/memory/__tests__/index.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '@/test-utils/msw-server'
import MemoryPage from '@/pages/memory'

const API_BASE = (import.meta.env.VITE_API_BASE as string) ?? ''

beforeEach(() => {
  server.use(
    http.get(`${API_BASE}/api/v0/memory/graph`, () =>
      HttpResponse.json({ nodes: [], edges: [] }),
    ),
    http.get(`${API_BASE}/api/v0/memory/timeline`, () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50 }),
    ),
    http.get(`${API_BASE}/api/v0/memory/audit`, () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get(`${API_BASE}/api/v0/memory/blocks`, () =>
      HttpResponse.json({
        blocks: [
          {
            block_name: 'persona',
            content: 'long-term value investor',
            token_count: 5,
            max_tokens: 500,
            updated_at: '2026-05-11T00:00:00Z',
          },
        ],
      }),
    ),
  )
})

describe('MemoryPage', () => {
  it('renders three tabs and switches between them', async () => {
    render(
      <MemoryRouter>
        <MemoryPage />
      </MemoryRouter>,
    )

    // 初始默认 graph tab
    expect(await screen.findByTestId('memory-tab-graph')).toBeInTheDocument()
    expect(screen.getByTestId('memory-graph-placeholder')).toBeInTheDocument()

    // 切到 timeline
    fireEvent.click(screen.getByTestId('memory-tab-timeline'))
    await waitFor(() =>
      expect(screen.getByTestId('memory-timeline-placeholder')).toBeInTheDocument(),
    )

    // 切到 audit
    fireEvent.click(screen.getByTestId('memory-tab-audit'))
    await waitFor(() =>
      expect(screen.getByTestId('memory-audit-placeholder')).toBeInTheDocument(),
    )
  })

  it('renders working blocks card from /blocks', async () => {
    render(
      <MemoryRouter>
        <MemoryPage />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByText(/persona/i)).toBeInTheDocument(),
    )
    expect(screen.getByText(/long-term value investor/)).toBeInTheDocument()
  })
})
```

跑红: `npm test -- src/pages/memory` → File 不存在。

#### Step 8.2 写 MemoryWorkingBlocks 组件

新建 `frontend/src/pages/memory/components/MemoryWorkingBlocks.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Card, Empty, Skeleton, Tag } from 'antd'
import { fetchMemoryBlocks } from '@/api/memoryApi'
import type { WorkingBlock } from '@/types/memory'

export function MemoryWorkingBlocks() {
  const [blocks, setBlocks] = useState<WorkingBlock[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetchMemoryBlocks()
      .then((res) => {
        if (alive) setBlocks(res.blocks)
      })
      .catch((e: Error) => {
        if (alive) setError(e.message)
      })
    return () => {
      alive = false
    }
  }, [])

  if (error) {
    return (
      <Card title="Working Memory" size="small">
        <span style={{ color: '#c0392b' }}>load failed: {error}</span>
      </Card>
    )
  }
  if (blocks === null) {
    return (
      <Card title="Working Memory" size="small">
        <Skeleton active paragraph={{ rows: 2 }} />
      </Card>
    )
  }
  if (blocks.length === 0) {
    return (
      <Card title="Working Memory" size="small">
        <Empty description="no working blocks yet" />
      </Card>
    )
  }

  return (
    <Card title="Working Memory" size="small" data-testid="memory-blocks-card">
      {blocks.map((b) => (
        <div key={b.block_name} style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <strong>{b.block_name}</strong>
            <Tag color="default">
              {b.token_count} / {b.max_tokens} tokens
            </Tag>
          </div>
          <pre
            style={{
              background: '#f7f6f4',
              padding: 8,
              borderRadius: 4,
              fontSize: 12,
              whiteSpace: 'pre-wrap',
              marginTop: 4,
            }}
          >
            {b.content || '(empty)'}
          </pre>
        </div>
      ))}
    </Card>
  )
}
```

#### Step 8.3 写 MemoryPage shell

新建 `frontend/src/pages/memory/index.tsx`:

```tsx
import { useState } from 'react'
import { Col, Row, Tabs } from 'antd'
import type { TabsProps } from 'antd'
import { MemoryWorkingBlocks } from './components/MemoryWorkingBlocks'

/**
 * /memory page shell — Plan 7A.
 *
 * 三 tab(Graph / Timeline / Audit)+ 右栏 working blocks always-visible.
 * tab 内容此 plan 留 placeholder div, 由 Plan 7B 替换为 MemoryGraph /
 * MemoryTimeline / MemoryAuditLog 真实组件。
 *
 * spec § 9 + shared contracts § 10
 */
export default function MemoryPage() {
  const [activeKey, setActiveKey] = useState<string>('graph')

  const tabs: TabsProps['items'] = [
    {
      key: 'graph',
      label: <span data-testid="memory-tab-graph">Graph</span>,
      children: (
        <div
          data-testid="memory-graph-placeholder"
          style={{ minHeight: 480, padding: 24, color: '#8a96a3' }}
        >
          Graph view (Plan 7B 实现 Cytoscape 可视化)
        </div>
      ),
    },
    {
      key: 'timeline',
      label: <span data-testid="memory-tab-timeline">Timeline</span>,
      children: (
        <div
          data-testid="memory-timeline-placeholder"
          style={{ minHeight: 480, padding: 24, color: '#8a96a3' }}
        >
          Timeline view (Plan 7B 实现 horizontal bar + valid_from 排序)
        </div>
      ),
    },
    {
      key: 'audit',
      label: <span data-testid="memory-tab-audit">Audit</span>,
      children: (
        <div
          data-testid="memory-audit-placeholder"
          style={{ minHeight: 480, padding: 24, color: '#8a96a3' }}
        >
          Audit log (Plan 7B 实现 invalidated edges 列表 + 一键否决)
        </div>
      ),
    },
  ]

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ marginBottom: 16 }}>Memory</h2>
      <Row gutter={16}>
        <Col xs={24} lg={18}>
          <Tabs
            activeKey={activeKey}
            onChange={setActiveKey}
            items={tabs}
            data-testid="memory-tabs"
          />
        </Col>
        <Col xs={24} lg={6}>
          <MemoryWorkingBlocks />
        </Col>
      </Row>
    </div>
  )
}
```

#### Step 8.4 接入 Router

修改 `frontend/src/router/routes.tsx`:

```typescript
// 顶部 import 段加:
import MemoryPage from '@/pages/memory'

// routes 数组里(在 /portfolio 行后或 /knowledge 行前任选,建议跟其他 dashboard 类放一起):
{ path: '/memory', Component: MemoryPage },
```

#### Step 8.5 接入 Sidebar

修改 `frontend/src/components/sidebar/page-nav.tsx`:

```typescript
const LINKS = [
  { to: '/research', label: 'Research' },
  { to: '/reports', label: 'Reports' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/monitoring', label: 'Monitoring' },
  { to: '/memory', label: 'Memory' },     // ← Plan 7A 新增
  { to: '/knowledge', label: 'Knowledge' },
]
```

#### Step 8.6 跑 Vitest

```bash
cd frontend
npm test -- src/pages/memory
npm run lint
npm run typecheck
```

#### Step 8.7 写 Playwright smoke

新建 `frontend/tests/e2e/memory-page.spec.ts`:

```typescript
/**
 * frontend/tests/e2e/memory-page.spec.ts
 *
 * Playwright smoke for C.5 Plan 7A /memory page foundation.
 * Scope:
 *  - sidebar 含 Memory 链接 + 点击跳到 /memory 路由
 *  - 三 tab(Graph / Timeline / Audit)可见 + 可切换
 *  - working blocks 卡片渲染(从 mock /blocks)
 *
 * Backend mock: page.route() 拦截 /api/v0/memory/* — 不依赖真后端。
 */

import { expect, test } from '@playwright/test'

const API_HOST = 'http://localhost:8001'

const FAKE_USER = {
  id: 'u-test',
  username: 'tester',
  email: 'tester@example.com',
  is_active: true,
  created_at: '2026-05-06T00:00:00Z',
}

async function seedAuth(context: import('@playwright/test').BrowserContext) {
  await context.addInitScript(([authKey, payload]: [string, string]) => {
    window.localStorage.setItem(authKey, payload)
  }, ['auth', JSON.stringify({ token: 'tk-test', user: FAKE_USER, isLoggedIn: true })])
}

async function stubMemoryEndpoints(page: import('@playwright/test').Page) {
  await page.route(`${API_HOST}/api/v0/memory/graph`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ nodes: [], edges: [] }),
    })
  })
  await page.route(`${API_HOST}/api/v0/memory/timeline*`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0, page: 1, page_size: 50 }),
    })
  })
  await page.route(`${API_HOST}/api/v0/memory/audit`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], total: 0 }),
    })
  })
  await page.route(`${API_HOST}/api/v0/memory/blocks`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        blocks: [
          {
            block_name: 'persona',
            content: 'long-term value investor',
            token_count: 5,
            max_tokens: 500,
            updated_at: '2026-05-11T00:00:00Z',
          },
        ],
      }),
    })
  })
  // Catch-all 防其他 API 404
  await page.route(`${API_HOST}/**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'success', data: {} }),
    })
  })
}

test.describe('/memory page foundation', () => {
  test('sidebar Memory link navigates to /memory', async ({ context, page }) => {
    await seedAuth(context)
    await stubMemoryEndpoints(page)

    await page.goto('/')
    const memoryLink = page.getByRole('link', { name: 'Memory' })
    await expect(memoryLink).toBeVisible()
    await memoryLink.click()
    await expect(page).toHaveURL(/\/memory$/)
  })

  test('three tabs visible and switchable', async ({ context, page }) => {
    await seedAuth(context)
    await stubMemoryEndpoints(page)

    await page.goto('/memory')
    await expect(page.getByTestId('memory-tab-graph')).toBeVisible()
    await expect(page.getByTestId('memory-tab-timeline')).toBeVisible()
    await expect(page.getByTestId('memory-tab-audit')).toBeVisible()

    // 默认 graph
    await expect(page.getByTestId('memory-graph-placeholder')).toBeVisible()

    // 切 timeline
    await page.getByTestId('memory-tab-timeline').click()
    await expect(page.getByTestId('memory-timeline-placeholder')).toBeVisible()

    // 切 audit
    await page.getByTestId('memory-tab-audit').click()
    await expect(page.getByTestId('memory-audit-placeholder')).toBeVisible()
  })

  test('working blocks card renders persona content', async ({
    context,
    page,
  }) => {
    await seedAuth(context)
    await stubMemoryEndpoints(page)

    await page.goto('/memory')
    await expect(page.getByText('persona')).toBeVisible()
    await expect(page.getByText('long-term value investor')).toBeVisible()
  })
})
```

跑:

```bash
cd frontend
npx playwright test memory-page.spec.ts
```

#### Step 8.8 commit

```bash
git add frontend/src/pages/memory/index.tsx \
  frontend/src/pages/memory/components/MemoryWorkingBlocks.tsx \
  frontend/src/pages/memory/__tests__/index.test.tsx \
  frontend/src/router/routes.tsx \
  frontend/src/components/sidebar/page-nav.tsx \
  frontend/tests/e2e/memory-page.spec.ts
git commit -m "feat(c5-plan7a): /memory page shell + sidebar + router + Playwright smoke

三 tab(Graph/Timeline/Audit) placeholder + working blocks 只读卡片;
Plan 7B 替换 placeholder 为真实可视化组件."
```

---

## 5. Self-Review Checklist

ship 前每条必勾。

### 契约对齐

- [ ] backend `memory_router.py` 5 endpoint 路径**字面**对应 shared contracts § 10 行 719-723
  - [ ] `GET /api/v0/memory/graph`
  - [ ] `GET /api/v0/memory/timeline`
  - [ ] `GET /api/v0/memory/audit`
  - [ ] `POST /api/v0/memory/edges/{edge_id}/invalidate`
  - [ ] `GET /api/v0/memory/blocks`
- [ ] 所有 endpoint 强制 `user_id` 从 `get_current_user_required` 取(契约 § 10 末尾约定),path/query 不接受 user_id
- [ ] backend 文件路径 `backend/app/router/memory_router.py` 对应 shared § 1 行 47
- [ ] frontend 路径按 § 0 适配规则(Vite/React 现实)落地 `frontend/src/pages/memory/index.tsx` + `frontend/src/api/memoryApi.ts` + `frontend/src/types/memory.ts`,跟 contracts § 1 逻辑路径对应清晰
- [ ] Pydantic `GraphEdgeOut.importance` 三档校验存在(契约 § 4 CHECK constraint mirror)

### Spec § 9 backend + 路由 coverage

- [ ] spec § 9 行 965 graph viz 数据接口 → Task 2 ✓
- [ ] spec § 9 行 967 timeline 数据接口 + entity_label 筛 → Task 3 ✓
- [ ] spec § 9 行 974 audit 接口 invalidated_at IS NOT NULL → Task 4 ✓
- [ ] spec § 14 P1 #8 用户回路 invalidate hook → Task 5 ✓
- [ ] spec § 7 working memory budget blocks 显示 → Task 6 ✓
- [ ] spec § 9 行 957 加 /memory 进 sidebar → Task 8.5 ✓
- [ ] spec § 9 行 982 复用 AppShell + Sidebar → Task 8 接入 router 在 AuthGuard + AppShell 下,自动复用 ✓

### Plan 范围边界(对照"不在范围"列)

- [ ] **没**写 Cytoscape graph viz(Plan 7B)— Task 8 用 placeholder div ✓
- [ ] **没**写 Timeline gantt 视图(Plan 7B)— placeholder div ✓
- [ ] **没**写 Audit log 列表组件(Plan 7B)— placeholder div ✓
- [ ] **没**写 OnboardingModal(Plan 7B)
- [ ] **没**改 chat agent 让它显式提及 memory 来源(Plan 7B)
- [ ] **没**写月度邮件 service(Plan 7B)

### 测试 coverage

- [ ] L0 backend Pydantic schema test(Task 1)— 5 schema round-trip + importance 三档拒绝
- [ ] L1 backend integration test(Task 2-6)— 每 endpoint 至少 2 case(成功 + 跨用户隔离),共 ≥ 13 case
- [ ] L0 frontend Vitest msw test(Task 7)— 5 endpoint + 1 错误路径
- [ ] L0 frontend RTL test(Task 8.1)— tab 切换 + working blocks 渲染
- [ ] L2 Playwright smoke(Task 8.7)— sidebar 链接 + 三 tab 切换 + working blocks

### Lint / Type / Format

- [ ] `uv run ruff check backend/app/router/memory_router.py` 绿
- [ ] `uv run mypy backend/app/router/memory_router.py` 绿
- [ ] `cd frontend && npm run lint` 绿
- [ ] `cd frontend && npm run typecheck` 绿
- [ ] `cd frontend && npm test` 全绿
- [ ] `cd frontend && npx playwright test memory-page.spec.ts` 全绿
- [ ] `cd backend && uv run pytest tests/unit/router/test_memory_router_schemas.py tests/integration/router/test_memory_router_endpoints.py -x -v` 全绿

### Workflow

- [ ] commit 频率 ≥ 6(每 task 至少 1)
- [ ] 不 push,不 amend(WORKING_AGREEMENT)
- [ ] 不修改 `app/memory/models.py`(Plan 1 主责;Plan 7A 只读 model)

---

## 6. 已知坑 / 实施期撞实策略

### 坑 1: SQLAlchemy JSONB 在 sqlite override 下

`app/memory/models.py` 用 `JSONB` / `TSVECTOR` / `PgUUID`。在 L1 router test 用 sqlite override 时 sqlite 不支持 JSONB / TSVECTOR。**前置条件**:Plan 1 ship 时必须给 model 加 `with_variant(JSON, "sqlite")` / `with_variant(Text, "sqlite")`。本 Plan 假设已加。

撞实路径: Step 2.2 跑测看到 `sqlalchemy.exc.CompileError: ... no compiler ... JSONB` → 立刻停,**回 Plan 1 patch model**(把 JSONB 类型改为 `JSON().with_variant(JSONB, "postgresql")` 等),再回来跑 test。**不要在 Plan 7A 里偷改 model 字段**(违反契约 § 4 末尾"严禁修改 model")— 这种 patch 算 spec/plan-1 layer 修复,commit body 加 `原因 layer: plan` marker。

### 坑 2: SQLAlchemy JSONB mutate 不触发 dirty(Task 5)

直接 `edge.properties["k"] = v` 不会让 SQLAlchemy 知道字段改了,UPDATE 不发。
**对策**: Task 5 实现里**重新赋整个 dict**:`edge.properties = {**(edge.properties or {}), "invalidated_by": "user_manual"}`。如果 Plan 1 ship 时已加 `MutableDict.as_mutable(JSONB)` 则可以直接 mutate,但 Plan 7A 不依赖此假设。

### 坑 3: Pydantic v2 `field_validator`

Step 1.2 的初稿用 `model_post_init` 风格做 `importance` 校验只是为了避免预设 import。实施时**直接用** `field_validator`:

```python
from pydantic import field_validator

class GraphEdgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edge_id: str
    # ...
    importance: float

    @field_validator("importance")
    @classmethod
    def _check_importance(cls, v: float) -> float:
        if v not in (0.2, 0.5, 0.9):
            raise ValueError(f"importance must be one of [0.2, 0.5, 0.9], got {v}")
        return v
```

更简洁,本仓库 Pydantic v2(可 `uv run python -c "import pydantic; print(pydantic.VERSION)"` 确认)。

### 坑 4: Frontend AuthGuard 可能拦 /memory

`frontend/src/router/routes.tsx` 把 routes 挂在 AuthGuard 下。本地跑 dev 时 `/memory` 必须先登录;**Playwright smoke 的 `seedAuth` helper** 已 ship,直接复用。

### 坑 5: `VITE_API_BASE` env 在 test 下

frontend Vitest 用 `import.meta.env.VITE_API_BASE`。如果 `.env.test` 没设默认空字符串,fetch URL 会是 `'/api/v0/memory/...'` 相对路径,msw 拦截 `${API_BASE}/api/v0/memory/...` 同样匹配。本 plan 测试已对齐 `chatApi.test.ts` pattern。

### 坑 6: AGE / Milvus 不在 Plan 7A 范围

5 个 endpoint 全部只查 PG 表(episodes / nodes / edges / working_blocks),**不**调用 AGE Cypher 或 Milvus。这是有意设计:
- Plan 7A 只服务 viz 页 + 用户回路,不需要 graph traversal
- AGE / Milvus 的 view 由 Plan 4 archival_memory_traverse / Plan 3 archival_memory_search 在 chat agent 内调用
- 这样 Plan 7A 的 L1 test 用 sqlite override 可跑,不用 PG/AGE/Milvus 三方一致性 fixture

### 坑 7: timeline `entity_label` 跨表 join 性能

Step 3.2 实现 `entity_label` 筛用了"先查 nodes 拿 ids → 再 in_(...) edges"两步策略,而非 SQL JOIN。理由:
- 跨用户隔离更清晰(两步都过 user_id 过滤)
- sqlite + PG 一致行为
- entity_label 在 nodes 表有 `(user_id, entity_type, entity_label)` UNIQUE → 命中索引快

性能上线后撞实再考虑改 JOIN(Plan 8 eval pipeline 监控)。

---

## 7. Plan 依赖与解锁

**前置(Plan 7A 必需)**:
- Plan 1A/1B ship — 4 PG 表 + Memory Protocol + working_blocks CRUD + sqlite variant 配置
- Plan 2A/2B ship — extractor 写入路径(让 audit / timeline 有真数据可看;Plan 7A 测试用 helper 直接 INSERT,不 strict 依赖,但 dogfood 时需要)
- Plan 3 ship — RRF / persona populator(让 working blocks 有内容)
- Plan 4 ship — 6 MCP tools(让 chat agent 写 memory)

**解锁后续**:
- **Plan 7B** — 复用 Plan 7A API client + page shell,把三个 placeholder 替换为真实组件(MemoryGraph / MemoryTimeline / MemoryAuditLog) + OnboardingModal + chat-side memory 来源提示 + 月度邮件 service
- Plan 8 — 跑 eval / dogfood,memory page 是观察工具

---

## 8. 工程量估算

| 阶段 | wall time(每天 4-6h) |
|---|---|
| Task 1 schema + skeleton | 0.3 天 |
| Task 2-6 5 endpoint 实现 + L1 test(每 endpoint 0.3 天) | 1.5 天 |
| Task 7 frontend client + types + Vitest | 0.3 天 |
| Task 8 page shell + sidebar + router + RTL + Playwright | 0.4 天 |
| **总计** | **~2.5 天** |

实施时若撞坑 1(JSONB sqlite variant 没加)需要回 Plan 1 patch,加 0.3 天。

---

## 9. Commit 路线图

| # | Task | Commit Title |
|---|---|---|
| 1 | Task 1 | `feat(c5-plan7a): memory_router skeleton + 5 Pydantic schemas + L0 test` |
| 2 | Task 2 | `feat(c5-plan7a): GET /memory/graph 当前快照 + 跨用户隔离 L1 test` |
| 3 | Task 3 | `feat(c5-plan7a): GET /memory/timeline DESC 排序 + 筛 + 分页` |
| 4 | Task 4 | `feat(c5-plan7a): GET /memory/audit invalidated edges 列表` |
| 5 | Task 5 | `feat(c5-plan7a): POST /memory/edges/{id}/invalidate 用户一键否决` |
| 6 | Task 6 | `feat(c5-plan7a): GET /memory/blocks working blocks 只读 + 跨用户隔离` |
| 7 | Task 7 | `feat(c5-plan7a): frontend memoryApi 5 endpoint typed client + Vitest` |
| 8 | Task 8 | `feat(c5-plan7a): /memory page shell + sidebar + router + Playwright smoke` |

8 commit,1 PR,标题 `feat(c5-plan7a): Memory Page Backend API + Frontend Foundation`。

PR body 引用本 plan + shared contracts + spec § 9。

---

## 10. 知识卡(Plan 7A ship 后写)

新建 `docs/claude-context/c5-plan7a-memory-api-foundation-done.md`(参考 `v1.0-monitoring-engine-done.md` 模式):

```markdown
---
name: c5-plan7a-memory-api-foundation-done
description: C.5 Plan 7A Memory Page Backend API + Frontend Foundation ship
type: project
---

C.5 Plan 7A ship — 2026-05-1X.

## ship 范围
- backend memory_router.py 5 endpoint(graph / timeline / audit / invalidate / blocks)
- frontend memoryApi.ts typed client + types/memory.ts
- /memory page shell + 三 tab 骨架 + working blocks 只读卡
- sidebar Memory 链接 + React Router /memory 路由
- L0/L1/L2 测试全绿

## 关键决策(实施期撞实)
- frontend 路径按 Vite/React 现实落地, 契约 § 1 Next.js 路径作为逻辑参考
- timeline entity_label 筛用两步 query 不用 JOIN(跨用户隔离 + sqlite/PG 一致)
- invalidate 已 invalidated → 400(防覆盖 audit log)

## 跟 spec 决策对齐
- spec § 9 三视图 数据接口 → 5 endpoint ship
- spec § 14 P1 #8 用户回路 invalidate hook → POST /invalidate ship
- spec § 7 working memory budget → /blocks ship

## 关键文件 ref
- backend/app/router/memory_router.py
- backend/tests/integration/router/test_memory_router_endpoints.py
- frontend/src/api/memoryApi.ts
- frontend/src/pages/memory/index.tsx
- frontend/tests/e2e/memory-page.spec.ts
```

`CLAUDE.md` 索引在 ship PR 同 commit 加一行链接。

---

**Plan 7A 完。**
