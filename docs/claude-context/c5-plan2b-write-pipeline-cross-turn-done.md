---
name: c5-plan2b-write-pipeline-cross-turn-done
description: C.5 Plan 2B 跨轮抽取 + Path B Celery 编排 ship
type: project
---

C.5 Plan 2B (Write Pipeline Cross-Turn) ship — 2026-05-11.

## ship 范围

**Path B (end-of-session batch extraction)**:
- `cross_turn_grouper` — 5 turn 滑动窗口 + 语义连续性合并(算法深度补丁 #4)
- `LLMExtractor.extract_facts()` — 跨轮 prompt + episode_ids list
- `PathBRunner` — 编排 cross_turn group → extract → conflict resolve → 写图
- `failure_matrix` — max-3 LLM retry + alert hook
- Milvus pending reconciliation 5min retry job

**Celery tasks** (`backend/app/tasks/memory.py`):
- `extract_session_episodes_async` — end-of-session 触发
- `reconcile_pending_milvus` — 5min beat schedule

**L1 + L2 tests**:
- Path B full path (mock LLM)
- failure matrix 5 行(LLM fail / AGE fail / Milvus fail / conflict fail / 幂等)
- L2 cassette stub (cassette 待 dogfood 期录)

## 关键决策

- **5 turn 滑窗 + 语义连续性合并** — "我刚买了" → "买的什么" → "茅台 500" 跨 3 turn 单 turn 抽不出
- **end-of-session batch 而非 per-turn** — 单 session 成本从 $0.025 → $0.005

## 关键文件 ref

- `backend/app/memory/cross_turn_grouper.py`
- `backend/app/memory/path_b_runner.py`
- `backend/app/memory/failure_matrix.py`
- `backend/app/memory/reconciliation.py` (Plan 1B 骨架 + 2B 完整实现)
- `backend/app/tasks/memory.py`
