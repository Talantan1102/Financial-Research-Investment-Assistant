---
title: Celery + Redis 测试 fixture pattern(L0/L1/L2 分层)
type: feedback
date: 2026-05-08
---

# Celery + Redis 测试 fixture pattern

**结论**:Celery task 在测试里走 3 层 fixture 模式(对齐 `pg-test-container-pattern.md`):

- **L0/L1(进程内,sqlite override)**:`task_always_eager=True` + `task_eager_propagates=True`,task 在调用进程同步跑,无 broker / 无 worker 进程
- **L2(e2e)**:`redis_container`(testcontainers)+ `celery_worker_subprocess` session-scoped fixture,worker 真启动 subprocess

**Why**:Celery task 的"是否丢任务 / autoretry 是否生效 / acks_late 是否生效"在 eager mode 下行为不一样(eager 直接跑,不走 broker;真生产走 broker)。L0/L1 验逻辑,L2 验通讯路径。`task_always_eager` 不能覆盖 `acks_late` / `worker_max_tasks_per_child` 等 worker-only 行为,所以 L2 必须真起 worker。

**How to apply**:
- 写新 Celery task 测试,默认走 `celery_eager` autouse fixture(在 conftest_celery.py)— 等价于 `pytest.fixture(autouse=True) monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")`
- 真要测 worker 行为(autoretry 触发 / acks_late 重派),进 L2:`pytest -m e2e -v`,需要 `pg_test_container + redis_url + celery_worker_subprocess` 3 个 fixture
- `redis_url` fixture 优先用 `REDIS_URL` env(CI 传),否则 testcontainers 启 RedisContainer 自起
- worker 启动 wait 通过读 stdout `"celery@... ready"`,15s timeout,超时 skip

**关键文件**:`backend/tests/conftest_celery.py`(本次 ship)
**Anchor**:`docs/superpowers/specs/2026-05-08-v1.0-portfolio-monitoring-engine-design.md` § 6.2
