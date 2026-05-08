---
name: 容器化依赖 fixture 模式
description: PG/Milvus/任何容器化依赖,session-scoped fixture + 外部已起则复用、自起则负责拆
type: feedback
---
容器化依赖(PG / Milvus / 任何 dockerized service)的 pytest fixture 用统一模式:**session-scoped + "外部已起则复用,自起则负责拆"**。

**Why:**
- 测试自包含,本地 / CI 行为一致(本地开发者可能有 PG 永久跑;CI 是 ephemeral)
- 不破坏开发者外部 db / dev 环境状态(自起就负责拆,复用就不动)
- session-scoped 跨多个测试只起一次容器,避免重复 docker compose up 带来的延迟

**How to apply:**
- 抄现成模板:`backend/tests/conftest.py` 中的 `milvus_test_container` 或 `pg_test_container`
- 关键模式:
  ```python
  if not _is_port_listening(host, port):
      subprocess.run(["docker", "compose", "up", "-d", service], check=True)
      started_by_us = True
  try:
      _wait_for_<service>_ready(...)
      yield {connection info dict}
  finally:
      if started_by_us:
          subprocess.run(["docker", "compose", "down", "-v"], check=False)
  ```
- 必要 helper:`_is_port_listening` + `_wait_for_<service>_ready`(用对应 client 探活,不只是 port listening)
- 对 PG 还需多一步:`_ensure_test_db_exists()` —— 处理 dev 已有旧 volume 的兼容(init.sql 不会在已存在的 volume 上重跑)
