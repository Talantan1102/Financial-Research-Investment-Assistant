---
name: 测试 DB 分层策略
description: L0/L1 用 sqlite-override 保速度,L2.5 用真 PG container fixture 守护 serve path
type: feedback
---
测试 DB 策略**分层** — L0/L1 用 sqlite-override + `dependency_overrides[get_db]`,L2.5 e2e 用真 PG container fixture(`pg_test_container`)。

**Why:**
- 全部切真 PG 收益小成本高(需要清掉 `_patch_uuid_columns_to_string()` 等 sqlite 兼容 hack)
- 不挂 PG 漏 serve path bug — 之前真踩过,完整 app_main lifespan + 真 DB 才能复现
- 折中:L0/L1 保速度(每个 PR 跑很多次),L2.5 仅 1 个测试用真 PG 守护"完整 app_main lifespan + 真 DB 行为 + 多用户隔离"

**How to apply 决策树:**
- 只测路由逻辑 / pydantic / 单 service → L0 unit + sqlite-override(`backend/tests/unit/`)
- 测 agent / 多 router 协作 → L1 integration + sqlite-override + LLM=mock(`backend/tests/integration/`)
- **测 lifespan 副作用 / DB 真行为 / 多用户隔离 → L2.5 真 PG fixture**(`backend/tests/e2e/test_pg_serve_path_e2e.py`)
- 数据层 cassette(tushare/bocha/monitoring) → L2 e2e cassette(`backend/tests/e2e/test_*_cassette.py`)

参考 spec:`docs/superpowers/specs/2026-05-07-v0.9.x-pg-and-ci-setup.md` § 3
