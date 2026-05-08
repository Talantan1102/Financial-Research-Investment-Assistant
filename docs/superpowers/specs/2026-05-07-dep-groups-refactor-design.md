# Dependency Groups Refactor — `kb` extras 拆分 + 死 deps 清理

**作者**:Talantan1102
**起草**:2026-05-07
**状态**:Brainstorm 收敛完成,待 writing-plans 起 implementation plan
**类型**:Design spec(项目级清理,跨环境受益)
**工期**:3-4 小时 wall time

---

## § 0 元信息与范围

把 KB feature 的 4 个重型依赖(mineru / pymilvus / pdfplumber / langchain-text-splitters)从 `[project] dependencies` 拆到 `[project.optional-dependencies] kb` 组,删除真正没在用的 matplotlib / seaborn。app_main 用 try/except 条件加载 `knowledge_router` —— 装了 kb extras 的环境路由正常,没装的环境用 stub 路由返 503 + 信息明确的错误。

**触发动机:**

1. **Codespaces 32GB 装不下当前 base deps** —— 实测 `uv sync --extra dev` 装到 jieba 时磁盘爆(详见 `docs/superpowers/specs/2026-05-07-v0.9.x-pg-and-ci-setup.md` 后续 commit + Codespaces 调试记录)。根因是 `mineru[core]` 拉 torch + cuda 等 ~5-8GB,加 universal:2-linux 镜像本身~5GB,32GB 不够
2. **公司 Windows 电脑 BIOS 不好开**(VT-x 禁用 → 不能装 Docker Desktop),Codespaces 是唯一 zero-BIOS 路径,因此 Codespaces 必须能用
3. **CI 也跟着受益** —— 现在 `uv sync --extra dev` 装 5-8GB ML libs 是 CI 时间浪费,本 PR ship 后 CI 命令显式 `--extra dev --extra kb` 装跟今天一致

**前置 spec 引用:**
- `docs/superpowers/specs/2026-05-05-v0.9+-roadmap-...md` § 4 过渡期 #3 CI / dev 体验改进(本 PR 落地 dev 体验改进)
- 历史背景:Codespaces 调试 session 暴露了 base deps 太重的问题(2026-05-07)

**关键 memory 引用:**
- `user_portfolio_target` — 个人作品定位,简化运维 ok
- 待落:本 PR ship 后落 `feedback_optional_extras_for_heavy_deps`(横切 pattern,以后撞重 deps 时复用)

**不在 scope:**
- 多分组(viz / agents / parsing 等)— YAGNI,死 matplotlib/seaborn 直接删
- KB 模块 lazy import 重构 — 用路由级 try/except 已足够覆盖;单个文件 lazy import 留到将来真有 partial install 需求再做
- pytest markers / 测试分组(`@pytest.mark.kb`)— CI 全装时无需
- 项目 archive / legacy module 清理 — 独立工作

---

## § 1 决策摘要

### 决策 1:scope = 最小化(1 个 kb 组 + 删死 deps)

**Brainstorm Q1**:范围 minimal vs 中等 vs 全面?

**业界 alternatives:**
- **A. 最小化 kb 组 + 删死 deps**(本决策):4 个 KB 重型 deps 进 kb 组,matplotlib/seaborn 删
- **B. 加 viz 组**:matplotlib/seaborn 进 viz 组而不是删,以防将来用
- **C. 全面分组**:kb / viz / agents / parsing 多组拆解

**取舍**:A。

**理由:**
- matplotlib/seaborn grep 全 backend 没真 import(只是 prompt 字符串里提了一嘴 — `service/deep_research_v2/agents/wizard.py:104,284,303`,而且这文件在 ruff 排除列表里 `pyproject.toml:103-114`,本来就 legacy 待删)。**真正未使用的 deps 应该删,不该装在"以防万一"组里**
- 加 viz / agents / parsing 都是为不存在的需求做准备,违 YAGNI;以后撞痛点再加

### 决策 2:KB 不可用时,stub 路由返 503

**Brainstorm Q2**:用户没装 kb extras 启动 app 时,/knowledge endpoint 行为?

**业界 alternatives:**
- **1. 静默跳过**:不注册 knowledge_router,/knowledge 返 404
- **2. stub 503**(本决策):注册占位路由,/knowledge/* 返 503 带"install with --extra kb"
- **3. 启动崩溃**:不允许部分启动

**取舍**:2。

**理由:**
- 1 让用户分不清"路由不存在"vs"路由存在但没装 deps",**用户体验差**
- 2 工程量只多 ~25 行 stub 路由,但用户看到 503 + 明确说明 → 知道怎么修
- 3 违背本 PR 初衷(让 codespace slim install 能跑非 KB 工作流)

### 决策 3:CI 装齐(`--extra dev --extra kb`)

**Brainstorm Q3**:CI install 命令怎么改?

**业界 alternatives:**
- **A. 都装**(本决策):CI 显式 `--extra dev --extra kb`,装 = 今天一样
- **B. CI 也 slim + 加 `@pytest.mark.kb` 跳过**:测试要 audit 标记
- **C. 两 job 分开**:slim job + kb job 并发

**取舍**:A。

**理由:**
- B/C 需要给所有 KB 测试加 marker —— 跨 unit / integration / e2e / eval 4 个目录 audit,工程量中等
- CI 跑慢几十秒可以接受,本 PR scope 不该扩到测试架构层
- 未来 CI 时间真成瓶颈再做 B/C(独立 task)

### 决策 4:Mac/生产/CI 默认 full install,Codespaces 唯一 slim

**澄清(2026-05-07 brainstorm 中段)**:用户曾质疑"KB 是不是业务核心,extras 不该把它边缘化"。

**澄清结论:** extras 是 pyproject.toml 安装机制,**不代表 product hierarchy**。本 PR 之后:

| 环境 | 默认装 KB? |
|---|---|
| Mac dev(主战场) | ✅ README 推荐 `uv sync --extra dev --extra kb` |
| 生产 | ✅ |
| CI | ✅(决策 3)|
| **Codespaces 默认 setup.sh** | ❌ 只 `--extra dev`(磁盘约束) |
| Codespaces 用户主动需要 | ✅ 手动 `uv sync --extra kb` |

**理由:** KB 是 v1 产品 first-class feature,**default install 全部环境装齐除了 Codespaces 这一个特例**。Codespaces 受 32GB 限制,默认 slim → 不影响 production / CI / Mac dev。

---

## § 2 pyproject.toml 改动

**`[project] dependencies` 删除以下 6 行:**

```toml
# 删:
# "pymilvus>=2.6.0",
# "mineru[core]>=3.1.0",
# "pdfplumber>=0.11.0",
# "langchain-text-splitters>=0.3.0",
# "matplotlib>=3.9",     # 死 deps,grep 无 import
# "seaborn>=0.13",       # 死 deps,grep 无 import
```

**`[project.optional-dependencies]` 新增 kb 组:**

```toml
[project.optional-dependencies]
dev = [
    # ... 不动 ...
]

# Roadmap 2026-05-07 dep refactor:KB feature 4 重型 deps 拆 optional
# 装这组:uv sync --extra dev --extra kb
# 不装(slim):uv sync --extra dev,/knowledge endpoint 返 503
kb = [
    "mineru[core]>=3.1.0",
    "pymilvus>=2.6.0",
    "pdfplumber>=0.11.0",
    "langchain-text-splitters>=0.3.0",
]
```

**uv.lock 同步:** `uv lock` 重新生成。

---

## § 3 代码改动 — **无 active code 改动需要**

> ⚠️ **2026-05-07 实施中校准**:本节原计划 stub router + app_main try/except,实际验证发现是**基于错误假设**。校准后:**Task 2 pyproject 拆分已经达成所有目标,无需 router-level 兜底**。

### 3.1 校准:knowledge_router **不依赖 kb-extras**

**原假设**(出 spec 时未深查):`from app.router.knowledge_router import router` 在 slim install 时会 ImportError(pymilvus 没装),所以需要 stub 兜底。

**实际**(实施中 grep + 实测):
- `knowledge_router.py:23` prefix 是 `/knowledge-bases`(不是 `/knowledge`),只做 KB metadata CRUD
- 它的 imports 只有 `app.core.database` / `app.models.knowledge` / `app.models.user` / `app.router.auth_router` / `app.schemas.knowledge` —— **没** import `services.milvus_client` / `services.pdf_parser_factory` / `services.kb_search_service` / `services.kb_factory` 等任何 kb-extras 依赖路径
- **slim install + `python -c "from app.app_main import app"` 实测**:42 routes 全部加载成功,**完全不报错**

### 3.2 真正会 ImportError 的位置(运行时,不在启动链上)

- `tools/kb_search.py:13` → `from app.services.kb_search_service import KbSearchService`(顶层 import)
- `kb_search_service.py:11` → `from app.services.milvus_client import (...)`(顶层 import)
- `milvus_client.py:9` → `from pymilvus import (...)` ← 这才是真 ImportError 触发点
- `kb_factory.py:8-9` → 同样链路
- `router/research.py:317` → **lazy import** in function body(`from app.services.kb_factory import build_kb_search_service_from_env`),只在 RAG search 调用时触发

**含义:** Slim install 启动 app 没问题。**只有 agent 运行时调 KB search 工具**(比如 research_agent 的 RAG 搜索 / kb_search tool)才会 ImportError。

### 3.3 决策:**不在本 PR 处理运行时 KB ImportError**(YAGNI)

理由:
- 本 PR 目标是"Codespaces 32GB 装得下" → Task 2 已达成
- 运行时失败位于 agent / tool 层面,不是 app 启动层 → 跟本 PR 主题不耦合
- Slim install 用户的语境是"我做 #3.5 类不需要 KB 的工作" → 不期望 KB search 跑 → ImportError 是 expected behavior
- 真要包,应该在 `kb_factory.build_kb_search_service_from_env` 入口加 try/except,让它返一个 stub `KbSearchService` 抛 informative error。这是独立 PR 的 scope(若未来真需要的话)

**所以 § 3 全部代码改动 = 无**。Task 2 (pyproject 拆分) 是这个 PR 的全部代码改动。

---

## § 4 CI 改动

### `.github/workflows/pr.yml`

```yaml
- name: Install deps
  run: uv sync --extra dev --extra kb   # ← 之前是 --extra dev
```

### `.github/workflows/nightly.yml`

```yaml
- name: Install deps
  run: uv sync --extra dev --extra kb
```

(`pr.yml` 之前的 `services.postgres`(PR #21)+ env vars 不动)

---

## § 5 Codespaces & README & 文档改动

### `.devcontainer/setup.sh`(已经是 universal image 之后的版本)

```bash
# 当前版本 (slim):
cd backend
uv sync --extra dev
```

**不改**(本方案就是要它 slim)。

### `README.md` 安装段更新

**当前**(行 99 附近):
```markdown
uv sync --extra dev
```

**改为:**
```markdown
### 安装

**完整安装**(推荐 — 含 KB feature):

```bash
uv sync --extra dev --extra kb
```

**精简安装**(磁盘紧张 / 不需要 KB 检索 + ingest 的开发场景,如 Codespaces 32GB):

```bash
uv sync --extra dev
# /knowledge-bases CRUD 仍可用(KB metadata 操作不依赖重型 ML deps)
# 只有 KB 检索(milvus 向量搜索)+ ingest(PDF 切片)在 agent 运行时调用会 ImportError
# 这种模式适合做 #3.5 类纯 DB / cache 等不碰 KB 检索的开发工作
```
```

### `.devcontainer/README.md` 加一段说明

```markdown
## KB feature

Default `setup.sh` does **slim install** (`uv sync --extra dev`) — app starts
cleanly, `/knowledge-bases` CRUD works (KB metadata 操作不需要重 ML deps)。
但 KB 检索(走 milvus)和 ingest 工作流(走 mineru / pdfplumber)在调用时
会 ImportError。

要启用完整 KB feature(检索 + ingest),在 codespace 里:

```bash
cd backend
uv sync --extra dev --extra kb
```

⚠️ `kb` extras 拉 ~5-8GB ML libs(mineru / torch / cuda)。32GB codespace 装不下;
要改 codespace machine 为 64GB(`gh codespace edit --machine premiumLinux`)再装。

**典型 codespace 工作流:**
- Codespaces 默认 slim → 适合做不依赖 KB 检索的 dev 工作(DB 迁移 / cache / monitoring 等)
- 需要 KB dogfood → 切到 Mac 本地 dev(已经装齐)或换大 codespace
```

---

## § 6 Migration plan(给现有 dev 环境)

| 环境 | 现在状态 | ship 后动作 |
|---|---|---|
| Mac dev(用户主战场) | 现在跑 `uv sync --extra dev`(装齐)| **要改** README 推荐为 `uv sync --extra dev --extra kb`,用户需 re-sync |
| Mac dev 用户已有 venv | 已装齐 | 跑 `uv sync --extra dev --extra kb` re-sync,实际不会重装(deps 都在) |
| 生产部署(若有) | 现在装齐 | 部署脚本改 `--extra dev --extra kb` |
| CI(GitHub Actions) | 现在 `--extra dev` 装齐 | 决策 3 改 `--extra dev --extra kb`,CI 时间不变 |
| **Codespaces** | 现在 slim install + setup.sh 装失败(磁盘满) | ship 后 setup.sh 跑 `uv sync --extra dev`,**装得下**;`/knowledge-bases` CRUD 工作;agent 调 KB 检索 / ingest 时运行时 ImportError(expected) |

**所有 `_DEFAULT_KB_*` 配置 / `KB_MODE=mock` 等 env 变量** 不动 —— 它们是 KB 内部的 config switch,本 PR 只改 install 入口。

---

## § 7 风险与缓解

| 风险 | 概率 | 后果 | 缓解 |
|---|---|---|---|
| ~~KB 模块被非 KB 代码 transitive import~~ | ~~中~~ | ~~app 启动崩溃~~ | **2026-05-07 实测验证此风险不存在**:slim install 启动 app 成功,42 routes 全部加载,knowledge_router.py 不依赖 kb extras。原 spec 假设错误,§ 3 已校准 |
| Mac 用户 ship 后第一次 sync 没 `--extra kb` 导致 agent 跑 KB 时 ImportError | 中 | UX 困惑(尤其是 dogfood 完整研报时撞到) | README 安装段强推荐"完整安装";本 PR ship 时通知用户;agent 报错信息可后续 PR 改 graceful |
| Codespaces 用户在 codespace 里手动 `--extra kb` 装失败(32GB 不够) | 高 | UX:用户尝试装但看到磁盘错 | `.devcontainer/README.md` 标注 32GB 局限 + 推荐换 premiumLinux machine |
| 测试发现某个 unit/integration 测试假定 KB deps 装着 → CI 不通 | 低 | CI 红 | CI 装 kb extras(决策 3),不踩这个坑 |
| 运行时 ImportError 体验差(没 graceful 降级)| 低-中 | KB search 报 raw `ModuleNotFoundError: pymilvus` 而非"请装 kb extras" | 留作独立 PR(在 `kb_factory.build_kb_search_service_from_env` / `tools/kb_search.py` 入口加 try/except,YAGNI 直到真有用户撞)|

---

## § 8 自审(Spec Self-Review)

> **2026-05-07 校准更新**:实施中发现原 § 3.1 (stub router) + § 3.2 (try/except) 基于错误假设(以为 knowledge_router import 链含 kb-extras,实测不含)。校准后:本 PR 唯一代码改动是 § 2 pyproject.toml 拆分。决策 2(stub 503)在校准后变为 N/A —— spec 保留为决策记录但实施跳过。

- **Placeholder scan:** 无 TBD/TODO,所有 § 有具体内容
- **Internal consistency:** 决策 1(minimal kb 组)→ § 2 pyproject 改动 ✓ ;~~决策 2(stub 503)→ § 3.1 stub router~~ → 校准后 N/A,§ 3 已重写说明原因 ✓ ;决策 3(CI 全装)→ § 4 yml 改动一行 ✓ ;决策 4(Mac/CI 默认 full,只 Codespaces slim)→ § 6 migration 表对齐 ✓
- **Scope check:** 一个 PR 里完成 pyproject.toml + 2 个 yml + README + .devcontainer 文档 — **5 个文件改动**(校准后,从原 7 个减为 5 个),~2-3 小时(校准后偏乐观,1-2 小时即可),scope 简化
- **Ambiguity check:**
  - "删 matplotlib/seaborn" 不是"移到 viz 组" — 决策 1 明确 ✓
  - ~~"stub router 走 503 不走 404"~~ — 校准后 N/A,knowledge_router 不需要 stub
  - Codespaces 用户主动加 kb extras 时磁盘可能不够 — § 7 风险表 + § 5 .devcontainer/README 标注 ✓
  - "slim install 后 KB search 行为" — § 3.2 + § 5 明确(运行时 ImportError,/knowledge-bases CRUD 仍可用)
- **Roadmap traceability:** § 0 引用 v0.9+ roadmap § 4 过渡期 #3 CI/dev 体验改进;本 PR 是 brainstorm 中冒出来的项目级清理(类比 § 4 过渡期 #2 legacy cleanup)

---

## § 9 Refs

- 触发 brainstorm:Codespaces 调试 session(2026-05-07)
- 上游 spec:`docs/superpowers/specs/2026-05-05-v0.9+-roadmap-and-long-running-task-scheduling.md` § 4 过渡期 #3
- 关联 PR:#23 (devcontainer 配置,本 PR 后 setup.sh 真能跑)
