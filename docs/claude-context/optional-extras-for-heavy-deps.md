---
name: 重型 deps 走 optional extras
description: 项目级 dep 拆分模式 — 重型 ML / 可选 feature deps 进 [project.optional-dependencies] 而不是 [project] base
type: feedback
---
KB / ML / viz 等"可选 feature"的 deps 应该放 `[project.optional-dependencies] <group>`,不是 `[project] dependencies`。

**Why:**
- base deps 决定每次 `uv sync` 的最小磁盘占用
- 个人作品里有 KB(mineru/torch/cuda 5-8GB)等重型 feature → base deps 塞不下 32GB Codespaces
- "feature 是不是核心"跟"deps 放哪一组"是两件事 — 装哪一组在 install 命令里控制(README 推荐 full,Codespaces 默认 slim)

**How to apply:**
- 加新 deps 前问:它服务的 feature 是 "must always installed" 还是 "opt-in for specific use case"?
- 后者 → 进 optional 组,在 README 安装段标明 `uv sync --extra dev --extra <group>`
- CI / 生产 / Mac dev 默认装齐(extras 不影响产品 hierarchy);Codespaces 默认 slim(磁盘约束)

**反面教材**(本会话 dep refactor 实施中暴露):
- 原 spec 计划在 `app_main.py` 用 try/except 包住 `from app.router.knowledge_router import router`,失败时用 stub 返 503。**实测发现 knowledge_router 不依赖 kb-extras**(prefix `/knowledge-bases`,只 import sqlalchemy/fastapi/app.models),slim install 时根本不报错,stub 永远是 dead code。**真正的 ImportError 在运行时**(agent 调 kb_search tool → kb_search_service → milvus_client → pymilvus)。
- 教训:`pyproject.toml` 拆分本身就够用,运行时 ImportError graceful 降级是独立 scope(YAGNI 直到撞到)

参考 spec:`docs/superpowers/specs/2026-05-07-dep-groups-refactor-design.md`(2026-05-07 校准版)
PR:#24(chore/dep-groups-refactor)
