---
name: c5-plan7a-memory-ui-shell-done
description: C.5 Plan 7A /memory page shell + 5 REST endpoint + frontend client ship
type: project
---

C.5 Plan 7A (Memory UI Shell) ship — 2026-05-11.

## ship 范围

**Backend** (`backend/app/router/memory_router.py`):
- 5 REST endpoint:
  - `GET /api/memory/graph` — Cytoscape format nodes + edges
  - `GET /api/memory/timeline` — chronological edge list
  - `GET /api/memory/working_blocks` — Tier 1 persona/scratchpad
  - `GET /api/memory/audit_log` — invalidate history
  - `POST /api/memory/{edge_id}/invalidate` — one-click otherthrow
- Pydantic schemas + L0 schema test + L1 cross-user isolation test

**Frontend** (`frontend/src/`):
- `lib/memory-api.ts` — typed REST client (5 endpoint)
- `app/memory/page.tsx` — /memory shell + sidebar 链接
- Vitest + msw L0 unit test
- Playwright smoke (page 渲染 + sidebar 出现)

**关键决策**:
- UUID 在 sqlite/PG 自动绑 (Plan 1A 已有 cast 处理)
- 跨用户严格隔离 (user_id WHERE 全 endpoint)

## 关键文件 ref

- `backend/app/router/memory_router.py`
- `backend/app/schemas/memory.py` Pydantic schemas
- `frontend/src/lib/memory-api.ts`
- `frontend/src/app/memory/page.tsx`
