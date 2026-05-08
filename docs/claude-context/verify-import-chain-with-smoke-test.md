---
name: import 链假设要 smoke test 验,不能只 grep
description: 写 spec 时假设 "X 模块 import Y" 一定要跑 `python -c "from X import ..."` 实测,grep 看不到 transitive / lazy / subprocess 调用
type: feedback
---
写 spec / plan 时如果你在假设"模块 A 的 import 会触发模块 B 的 import"(链式 import 或 transitive 失败 propagation),**必须跑 smoke test 验证**:

```bash
# 在干净 venv 状态下
uv sync --extra dev   # (或对应的 slim 安装命令)
python -c "from app.X import ...; print('imports OK')"
```

光 grep `from B import` 不够,因为:
- B 可能被 lazy import(在函数体内,非顶层) → grep 看不到运行时触发
- B 可能被 subprocess CLI 调用(非 Python import) → grep 完全不命中
- A → C → D → B 链式 import → grep A 看不到 B
- 项目目录有别名(`app/service/` vs `app/services/`)— 容易误判哪个是 active 路径

**反面教材**(2026-05-07 dep refactor):

写 spec 时假设 `knowledge_router.py` import 链上有 pymilvus(因为 KB feature 嘛)。实施中 grep + smoke test 才发现:
- `knowledge_router.py:23` prefix 是 `/knowledge-bases`(不是 `/knowledge`),只做 metadata CRUD
- 它只 import `app.core.database` / `app.models.knowledge` / `app.router.auth_router` / `app.schemas.knowledge`,**全链路无 kb-extras 依赖**
- 真 pymilvus import 在运行时:`tools/kb_search.py` → `kb_search_service` → `milvus_client` → `pymilvus`,这条链由 agent 调 kb_search tool 触发,不在 app 启动链上

结果:基于错误假设写的 stub router + try/except 是 dead code,只能 revert(`git reset --hard`)。

**How to apply:**
- spec 阶段如果谈"X import 会 fail",写完 spec 但实施第一步先 smoke test
- 实施 task 0 / Task 1 类的 audit 步骤里加一个明确的 smoke test 验证假设
- 校准成本(改 spec)远小于回滚成本(写完代码再删)

PR:#24(校准 commit `36b67e6` on `docs/dep-groups-refactor-spec`)
