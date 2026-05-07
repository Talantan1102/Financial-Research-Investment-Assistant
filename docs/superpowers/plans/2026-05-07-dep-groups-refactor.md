# Dependency Groups Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move 4 KB feature heavy deps (mineru / pymilvus / pdfplumber / langchain-text-splitters) from `[project] dependencies` to `[project.optional-dependencies] kb`, delete unused matplotlib/seaborn, register a stub `knowledge_router` returning 503 when kb extras absent, update CI to install with `--extra kb`, document Mac/Codespaces install paths.

**Architecture:** `pyproject.toml` 改组结构 + `app_main.py` try/except import knowledge_router(失败时 fallback 到 stub `knowledge_stub.py` 返 503 with 信息明确的错误). 全程不动 KB 自身代码(milvus_client / pdf_parser_factory / chunkers 等),通过路由级 short-circuit 隔离 ImportError.

**Tech Stack:** uv(`uv sync --extra <group>`)、FastAPI APIRouter、pytest + pytest-asyncio、ruff/mypy strict.

**Spec:** `docs/superpowers/specs/2026-05-07-dep-groups-refactor-design.md`

**Prerequisites:** 无(独立项目级清理,不依赖 #21/#22/#23 任何一个)

---

## Task 0: Setup branch

**Files:** N/A(git operation)

- [ ] **Step 1: Pull main + create branch**

```bash
git checkout main
git pull
git log -1 --format='%h %s'
git checkout -b chore/dep-groups-refactor
```

Expected: 创建新 branch,working tree 干净。

---

## Task 1: Audit grep — 找出所有 KB top-level imports

**Files:** N/A(grep + 决策)

确保 stub 路由方案能 cover —— 如果有非 KB 代码 top-level import KB 重 deps,本 PR 还需要给那些代码加 try/except 或推到独立 PR。

- [ ] **Step 1: Grep KB module top-level imports**

```bash
grep -rn "^\(from\|import\)\s\+\(mineru\|pymilvus\|pdfplumber\|langchain_text_splitters\)" \
  backend/app
```

Expected output(根据 spec § 6 风险表已知):

```
backend/app/services/milvus_client.py:9:from pymilvus import CollectionSchema, ...
backend/app/services/pdf_parsers/mineru.py:?:from mineru import ...        (TBD line 数)
backend/app/services/pdf_parsers/pdfplumber.py:?:from pdfplumber import ...
backend/app/kb/chunkers/section.py:5:from langchain_text_splitters import RecursiveCharacterTextSplitter
backend/app/service/milvus_service.py:6:from pymilvus import (...)         (legacy)
```

如果 grep 输出 == 上面 list,**走 happy path**(本 PR 完整覆盖)。

- [ ] **Step 2: Verify each is reachable only via knowledge_router**

对每个 grep 出来的文件,验证它的 callers 都在 KB 路径(`backend/app/router/knowledge_router.py` 直接或传递引用)。

```bash
# 对每个 KB 模块查 callers
for module in milvus_client pdf_parser_factory chunkers; do
  echo "=== ${module} callers ==="
  grep -rn "from app\.services\.${module}\|from app\.kb\.${module}" backend/app | grep -v __pycache__
done
```

Expected: callers 全部在 `app/kb/`、`app/services/pdf_parsers/`、`app/router/knowledge_router.py`、或被 knowledge_router transitive load 的文件里。

- [ ] **Step 3: 处理 service/milvus_service.py(legacy)**

```bash
grep -rn "from app\.service\.milvus_service\|app\.service\.milvus_service" backend/app
```

Expected:`app.service.milvus_service` 应该没 active caller(legacy router `/memory` 没在 app_main 注册,per LEGACY_LAYOUT.md)。如果 grep 出 active caller,**记录并加进 stub 处理范围**(可能需要本 PR 加 try/except 给那些 caller)。

- [ ] **Step 4: Determine — happy path or extra work needed?**

- 如果 Step 2/3 都无 active 非 KB caller → happy path,继续 Task 2
- 如果有 → 本 task 结束前补 task list:对每个 active caller 加 try/except + ImportError fallback,然后再继续 Task 2

- [ ] **Step 5: Document audit result in commit**

```bash
git commit --allow-empty -m "chore(audit): KB module top-level imports — ready for refactor

Audit per spec § 7 Risk #1. KB modules confirmed reachable only via
knowledge_router (5 files: milvus_client, pdf_parser_factory,
pdf_parsers/mineru, pdf_parsers/pdfplumber, kb/chunkers/section).
service/milvus_service.py is legacy w/ no active caller.

原因 layer: impl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(Empty audit commit 留 trace,不动代码。)

---

## Task 2: pyproject.toml — 删 6 行 + 加 kb 组

**Files:** Modify `pyproject.toml` + `uv.lock`

- [ ] **Step 1: 找到 [project] dependencies 段当前内容**

```bash
sed -n '/^\[project\]/,/^\[/p' pyproject.toml | head -70
```

验证看到 `pymilvus>=2.6.0` / `mineru[core]>=3.1.0` / `pdfplumber>=0.11.0` / `langchain-text-splitters>=0.3.0` / `matplotlib>=3.9` / `seaborn>=0.13` 这 6 行(按 spec § 2)。

- [ ] **Step 2: 删除 6 行 from [project] dependencies**

打开 `pyproject.toml`,在 `dependencies = [...]` 数组里**删除**:

```toml
"pymilvus>=2.6.0",
"mineru[core]>=3.1.0",
"pdfplumber>=0.11.0",
"langchain-text-splitters>=0.3.0",
"matplotlib>=3.9",
"seaborn>=0.13",
```

(同时删除它们上面的 `# Vector DB / # v0.7 KB Search / # Visualization` 注释行,如果只剩这一组。)

- [ ] **Step 3: 加 [project.optional-dependencies] kb 组**

在 `[project.optional-dependencies]` 段**之后**(dev 组下面),添加:

```toml
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

- [ ] **Step 4: uv lock — 重新生成 lock**

```bash
cd backend && uv lock
```

(顶层 `pyproject.toml` 没在 backend/,但项目用 `[tool.uv] managed = true` 是顶层配置,所以从 repo root 跑 uv lock 也行。具体看项目 setup,大概率从 repo root:)

```bash
uv lock
```

Expected: `uv.lock` updated;6 个移除的 deps 仍出现(因为 kb extra 仍依赖它们),但 `[[package]]` 区块的层级关系变了。

- [ ] **Step 5: Verify slim install works**

```bash
# 先清旧 venv 重新装
rm -rf .venv
uv sync --extra dev
ls .venv/lib/python3.*/site-packages/ | grep -E "^(pymilvus|mineru|pdfplumber|langchain_text_splitters|matplotlib|seaborn)" || echo "none of the kb/dead deps installed (expected)"
```

Expected:`none of the kb/dead deps installed (expected)` —— 6 个 deps 都不在了。

- [ ] **Step 6: Verify full install works**

```bash
uv sync --extra dev --extra kb
ls .venv/lib/python3.*/site-packages/ | grep -E "^(pymilvus|mineru|pdfplumber|langchain_text_splitters)" | sort
```

Expected:4 个 kb deps 全装(matplotlib/seaborn 仍不在 — 因为它们已删,也不在 kb 组)。

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): split KB heavy deps into [optional-deps] kb + delete dead deps

Roadmap 2026-05-07 dep refactor — moved mineru[core]/pymilvus/pdfplumber/
langchain-text-splitters from base [project] dependencies to
[project.optional-dependencies] kb. Deleted matplotlib/seaborn (grep
confirmed no actual import; only mentioned in legacy wizard.py prompt
strings).

Install:
- Slim (no KB):       uv sync --extra dev
- Full (with KB):     uv sync --extra dev --extra kb

Spec: docs/superpowers/specs/2026-05-07-dep-groups-refactor-design.md § 2

原因 layer: impl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Create knowledge_stub.py + 单元测试(TDD)

**Files:**
- Create: `backend/app/router/knowledge_stub.py`
- Test: `backend/tests/unit/router/test_knowledge_stub.py`

- [ ] **Step 1: Write failing test first**

Create `backend/tests/unit/router/test_knowledge_stub.py`:

```python
"""Roadmap 2026-05-07 dep refactor — verify knowledge_stub returns 503
with informative error on all /knowledge/* paths.

Tested without spinning up the real app (no app_main lifespan, no DB).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.router.knowledge_stub import router as knowledge_stub_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_stub_router)
    return TestClient(app)


def test_get_knowledge_root_returns_503(client: TestClient) -> None:
    r = client.get("/knowledge/")
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["error"] == "kb_extras_not_installed"
    assert "uv sync --extra dev --extra kb" in detail["message"]


def test_post_knowledge_search_returns_503(client: TestClient) -> None:
    r = client.post("/knowledge/search", json={"query": "test"})
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "kb_extras_not_installed"


def test_arbitrary_subpath_returns_503(client: TestClient) -> None:
    r = client.delete("/knowledge/some/nested/path")
    assert r.status_code == 503
    assert "install" in r.json()["detail"]["message"].lower()


def test_detail_includes_doc_link(client: TestClient) -> None:
    r = client.get("/knowledge/anything")
    assert "doc" in r.json()["detail"]
    assert "2026-05-07-dep-groups-refactor" in r.json()["detail"]["doc"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/unit/router/test_knowledge_stub.py -v
```

Expected: ImportError or ModuleNotFoundError 因为 `knowledge_stub.py` 还没建。

- [ ] **Step 3: Create knowledge_stub.py**

Create `backend/app/router/knowledge_stub.py`:

```python
"""Stub knowledge_router used when kb extras not installed.

Roadmap 2026-05-07 dep refactor — when uv sync runs without --extra kb,
the real knowledge_router import fails (ImportError on pymilvus / mineru /
pdfplumber / langchain-text-splitters). app_main detects this and registers
this stub instead — same /knowledge prefix, all paths return 503 with an
informative error pointing user at the install command.

See: docs/superpowers/specs/2026-05-07-dep-groups-refactor-design.md § 3
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/knowledge", tags=["knowledge-stub"])

_UNAVAILABLE_DETAIL: dict[str, str] = {
    "error": "kb_extras_not_installed",
    "message": (
        "KB feature requires optional 'kb' deps "
        "(mineru / pymilvus / pdfplumber / langchain-text-splitters). "
        "Install with: uv sync --extra dev --extra kb"
    ),
    "doc": "docs/superpowers/specs/2026-05-07-dep-groups-refactor-design.md",
}


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def kb_unavailable(path: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_UNAVAILABLE_DETAIL,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/unit/router/test_knowledge_stub.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Run mypy strict on new files**

```bash
cd backend && uv run mypy app/router/knowledge_stub.py tests/unit/router/test_knowledge_stub.py
```

Expected: no errors.

- [ ] **Step 6: Run ruff format/check**

```bash
cd backend && uv run ruff format app/router/knowledge_stub.py tests/unit/router/test_knowledge_stub.py
uv run ruff check app/router/knowledge_stub.py tests/unit/router/test_knowledge_stub.py
```

Expected: no changes / All checks passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/router/knowledge_stub.py backend/tests/unit/router/test_knowledge_stub.py
git commit -m "feat(router): knowledge_stub — 503 fallback when kb extras missing

Roadmap 2026-05-07 dep refactor § 3.1 — stub router used by app_main
when ImportError on knowledge_router (caused by missing kb extras).
All /knowledge/* paths return 503 with structured error pointing user
at the correct install command.

Tested:
- GET / POST / DELETE all return 503
- detail includes 'kb_extras_not_installed' marker
- detail includes 'uv sync --extra dev --extra kb' install hint
- detail includes spec doc link

原因 layer: impl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: app_main.py — 条件加载 knowledge_router

**Files:** Modify `backend/app/app_main.py`(行 24 + 行 302)

- [ ] **Step 1: Read current import + include_router lines**

```bash
grep -n "knowledge_router" backend/app/app_main.py
```

Expected:
```
24:from app.router.knowledge_router import router as knowledge_router  # noqa: E402
302:app.include_router(knowledge_router)
```

(行号可能因其他改动微移,本步骤是为了**确认改动锚点**)

- [ ] **Step 2: 替换 import 行(行 24 附近)**

把:

```python
from app.router.knowledge_router import router as knowledge_router  # noqa: E402
```

替换为:

```python
# Roadmap 2026-05-07 dep refactor — knowledge_router 条件加载,
# 装 kb extras 时 import 真路由,否则 fallback 到 stub 返 503
try:
    from app.router.knowledge_router import router as knowledge_router  # noqa: E402

    _kb_router_available = True
    _kb_import_error: str | None = None
except ImportError as e:
    knowledge_router = None  # type: ignore[assignment]
    _kb_router_available = False
    _kb_import_error = str(e)
```

- [ ] **Step 3: 替换 include_router 行(行 302 附近)**

把:

```python
app.include_router(knowledge_router)
```

替换为:

```python
if _kb_router_available:
    app.include_router(knowledge_router)
    logger.info("KB router loaded — /knowledge endpoints active")
else:
    from app.router.knowledge_stub import router as knowledge_stub_router  # noqa: E402

    app.include_router(knowledge_stub_router)
    logger.warning(
        "KB feature deps not installed (%s); /knowledge endpoints return 503. "
        "Install with: uv sync --extra dev --extra kb",
        _kb_import_error,
    )
```

- [ ] **Step 4: Run mypy strict on app_main.py**

```bash
cd backend && uv run mypy app/app_main.py
```

Expected: no errors(`type: ignore[assignment]` 处理了 None vs Router 的 type 冲突)。

- [ ] **Step 5: Run ruff**

```bash
cd backend && uv run ruff format app/app_main.py
uv run ruff check app/app_main.py
```

Expected: no changes / passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/app_main.py
git commit -m "feat(app_main): conditional knowledge_router load — stub fallback

Roadmap 2026-05-07 dep refactor § 3.2 — knowledge_router import wrapped
in try/except. ImportError (caused by missing kb extras) triggers
fallback to knowledge_stub router (returns 503). app starts cleanly in
both slim and full install modes.

Logs:
- Full install:  'KB router loaded — /knowledge endpoints active'
- Slim install:  'KB feature deps not installed (...); /knowledge
                  endpoints return 503. Install with: uv sync --extra
                  dev --extra kb'

原因 layer: impl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: 本地验证 — slim install 路径

**Files:** N/A(integration verification)

- [ ] **Step 1: 清 venv,装 slim**

```bash
rm -rf .venv
uv sync --extra dev
```

Expected: 装得快(没 kb 重 deps), `.venv/lib/python3.*/site-packages/` 里没有 mineru / pymilvus / pdfplumber / langchain_text_splitters。

- [ ] **Step 2: 验证 app 启动 + KB stub 路由生效**

```bash
# 启动 server (后台)
cd backend && uv run uvicorn app.app_main:app --port 8000 &
SERVER_PID=$!
sleep 5
```

预期 server 启动日志包含:`KB feature deps not installed (...); /knowledge endpoints return 503`。

- [ ] **Step 3: 验证 /knowledge 路由返 503**

```bash
curl -s -o /tmp/kb_stub_response.json -w "%{http_code}\n" http://localhost:8000/knowledge/anything
cat /tmp/kb_stub_response.json | python3 -m json.tool
```

Expected:
- HTTP 503
- response body 包含 `"error": "kb_extras_not_installed"`
- response body 包含 `"uv sync --extra dev --extra kb"`

- [ ] **Step 4: 验证非 KB endpoint 正常工作**

```bash
# Auth endpoint
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"slim_test","password":"pwd_12345","email":"s@s.com"}'
```

Expected: 200 or 201(注册成功 — 非 KB 路由)。

- [ ] **Step 5: 关闭 server**

```bash
kill $SERVER_PID
wait $SERVER_PID 2>/dev/null
```

- [ ] **Step 6: 不需要 commit**(纯验证,无代码改动)

---

## Task 6: 本地验证 — full install 路径

**Files:** N/A(integration verification)

- [ ] **Step 1: 装 full**

```bash
uv sync --extra dev --extra kb
```

Expected: 拉 mineru / pymilvus / pdfplumber / langchain_text_splitters 等 kb 重 deps(可能要等几分钟,看网络)。

- [ ] **Step 2: 验证 venv 含 kb deps**

```bash
ls .venv/lib/python3.*/site-packages/ | grep -E "^(pymilvus|mineru|pdfplumber|langchain_text_splitters)"
```

Expected: 4 个都在。

- [ ] **Step 3: 启动 app + 验证 KB router(真路由)被加载**

```bash
cd backend && uv run uvicorn app.app_main:app --port 8000 &
SERVER_PID=$!
sleep 8  # 装 kb 后启动可能稍慢
```

Expected: server 启动日志包含 `KB router loaded — /knowledge endpoints active`(没有 `KB feature deps not installed` warning)。

- [ ] **Step 4: 验证 /knowledge 走真路由(不返 stub 503)**

```bash
# /knowledge/<some-path> 现在应该返真路由的响应,可能是 401/404,但不是 stub 的 503
curl -s -o /tmp/kb_real_response.json -w "%{http_code}\n" http://localhost:8000/knowledge/list
cat /tmp/kb_real_response.json
```

Expected:
- HTTP code 不是 503(可能 401/404/200,看真路由实现)
- response **不**包含 `"kb_extras_not_installed"` 字符串

- [ ] **Step 5: 关 server**

```bash
kill $SERVER_PID
wait $SERVER_PID 2>/dev/null
```

- [ ] **Step 6: 不 commit**(纯验证)

---

## Task 7: 改 pr.yml CI 命令

**Files:** Modify `.github/workflows/pr.yml`

- [ ] **Step 1: Read current install line**

```bash
grep -n "uv sync" .github/workflows/pr.yml
```

Expected: `run: uv sync --extra dev`(line 数视 PR #21 状态)。

- [ ] **Step 2: 替换为 `--extra dev --extra kb`**

把:
```yaml
- name: Install deps
  run: uv sync --extra dev
```

改成:
```yaml
- name: Install deps
  run: uv sync --extra dev --extra kb
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/pr.yml
git commit -m "ci(pr): install with --extra kb to keep KB tests runnable

Roadmap 2026-05-07 dep refactor § 4 — after splitting kb deps into
optional group, CI must explicitly opt in to keep test_chunkers /
test_ingest_cassette etc. running. Decision Q3 of brainstorm.

原因 layer: impl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: 改 nightly.yml CI 命令

**Files:** Modify `.github/workflows/nightly.yml`

- [ ] **Step 1: Read current**

```bash
grep -n "uv sync" .github/workflows/nightly.yml
```

- [ ] **Step 2: 同步替换**

把所有 `uv sync --extra dev` 改成 `uv sync --extra dev --extra kb`(可能多个 step,如果有的话)。

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/nightly.yml
git commit -m "ci(nightly): install with --extra kb (matches pr.yml change)

原因 layer: impl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: README.md — 安装段重写

**Files:** Modify `README.md`

- [ ] **Step 1: Read 当前 安装 段**

```bash
grep -n "### 安装\|uv sync" README.md
```

Expected: 找到 "### 安装" 段(line ~96 区域)+ 一行 `uv sync --extra dev`。

- [ ] **Step 2: 替换段落**

把:

```markdown
### 安装

\`\`\`bash
uv sync --extra dev
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type commit-msg
cp backend/.env.example backend/.env  # 然后编辑 DASHSCOPE_API_KEY、TUSHARE_TOKEN 等
cd frontend && npm install && cd ..
\`\`\`
```

改为:

```markdown
### 安装

**完整安装**(推荐 — 含 KB feature):

\`\`\`bash
uv sync --extra dev --extra kb
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type commit-msg
cp backend/.env.example backend/.env  # 然后编辑 DASHSCOPE_API_KEY、TUSHARE_TOKEN 等
cd frontend && npm install && cd ..
\`\`\`

**精简安装**(磁盘紧张 / 不需要 KB feature 的开发场景,如 Codespaces 32GB):

\`\`\`bash
uv sync --extra dev   # 不带 --extra kb
# /knowledge endpoint 此模式下会返 503;ingest 工作流不可用
\`\`\`

KB feature 需要 ~5-8 GB ML libs(mineru / torch / cuda 等)。如果你不会用到
\`/knowledge\` 路由或 ingest 工作流,可以走精简安装节省空间。
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): document slim vs full install for kb extras

Roadmap 2026-05-07 dep refactor § 5 — README 安装段说明完整 vs 精简两种
模式;Codespaces / 磁盘紧张场景指向精简模式。

原因 layer: impl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: .devcontainer/README.md — 加 KB feature 注

**Files:** Modify `.devcontainer/README.md`

- [ ] **Step 1: Read 当前文件**

```bash
cat .devcontainer/README.md
```

- [ ] **Step 2: 在 "Quick start" 段之后,"CLI from your local machine" 段之前,插入新章节**

```markdown
## KB feature(可选)

Default `setup.sh` does **slim install** (`uv sync --extra dev`). The
`/knowledge` endpoints will return 503 with a hint message. To enable
KB feature inside the codespace:

```bash
cd backend
uv sync --extra dev --extra kb
```

⚠️ `kb` extras 拉 ~5-8GB ML libs(mineru / torch / cuda)。`basicLinux32gb`
codespace(32GB 磁盘)装不下 — 需要更大 machine:

```bash
gh codespace edit --codespace <name> --machine premiumLinux  # 8-core / 64GB
```

如果你只在 codespace 里做 #3.5 类不涉及 KB 的工作(DB 迁移 / Redis cache /
monitoring 等),slim install 就够用,不需要换 machine。
```

- [ ] **Step 3: Commit**

```bash
git add .devcontainer/README.md
git commit -m "docs(devcontainer): note KB feature opt-in + 32GB machine warning

原因 layer: impl

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: 本地 dogfood — 跑 full 测试套件

**Files:** N/A(integration verification)

确保 lint / mypy / pytest L0+L1+L2 全过(模拟 CI)。

- [ ] **Step 1: 确保 venv 是 full install 状态**

```bash
ls .venv/lib/python3.*/site-packages/ | grep -E "^pymilvus" && echo "FULL OK" || \
  uv sync --extra dev --extra kb
```

- [ ] **Step 2: 跑 poe ci(本地模拟 PR CI)**

```bash
cd backend && uv run poe ci
```

Expected: lint(format/check/mypy)+ L0/L1/L2 测试全 PASS,包括新加的 `test_knowledge_stub.py`。

- [ ] **Step 3: 如果有 fail,grep 看是不是 KB 相关 import 漏了**

如果某个测试 fail with `ModuleNotFoundError: pymilvus`(slim mode 的痕迹遗留),回到 Task 1 audit + 加 try/except。如果 fail 跟 KB 无关,debug 那个测试。

- [ ] **Step 4: 不 commit**(纯验证)

---

## Task 12: Codespaces 验证 — 32GB 装得下 + stub 503

**Files:** N/A(integration verification on cloud)

- [ ] **Step 1: 删除任何旧 codespace(防干扰)**

```bash
gh codespace list 2>&1 | grep "Financial-Research" | awk '{print $1}' | \
  xargs -I{} gh codespace delete --codespace {} --force 2>&1
```

- [ ] **Step 2: 创建新 codespace from 本 branch**

```bash
gh codespace create \
  --repo Talantan1102/Financial-Research-Investment-Assistant \
  --branch chore/dep-groups-refactor \
  --machine basicLinux32gb \
  --display-name "dep-refactor-verify"
```

Expected: 创建成功,等 ~7-10 min Available(universal image 大)。

- [ ] **Step 3: SSH in + 等 setup.sh 完成 + 看 disk usage**

```bash
CS_NAME=$(gh codespace list --json name,displayName --jq '.[] | select(.displayName=="dep-refactor-verify") | .name')

# Wait for setup.sh complete (signal: .venv exists)
until gh codespace ssh --codespace $CS_NAME -- "test -f /workspaces/Financial-Research-Investment-Assistant/.venv/bin/python" 2>/dev/null; do
  echo "Waiting for setup.sh..."; sleep 60
done

# Check disk usage
gh codespace ssh --codespace $CS_NAME -- "df -h /workspaces"
```

Expected:
- `.venv/bin/python` exists(setup.sh 跑完)
- 磁盘使用 ~12-15GB / 32GB(slim install + universal base, much less than failed 95% before)

- [ ] **Step 4: 启动 app + 验证 stub 路由返 503**

```bash
gh codespace ssh --codespace $CS_NAME -- "
cd /workspaces/Financial-Research-Investment-Assistant
docker compose up -d postgres redis
sleep 8
cd backend && uv run uvicorn app.app_main:app --port 8000 > /tmp/server.log 2>&1 &
sleep 8
curl -s -w '%{http_code}\n' http://localhost:8000/knowledge/foo
cat /tmp/server.log | grep -i 'kb feature' || echo 'KB warning log not found'
"
```

Expected:
- HTTP 503 returned
- server log 含 `KB feature deps not installed` warning

- [ ] **Step 5: Cleanup codespace**

```bash
gh codespace delete --codespace $CS_NAME --force
```

- [ ] **Step 6: 不 commit**(纯验证)

---

## Task 13: 推 + 开 PR + 监 CI

**Files:** N/A(git/gh operations)

- [ ] **Step 1: Push branch**

```bash
git push -u origin chore/dep-groups-refactor
```

- [ ] **Step 2: gh pr create --draft**

```bash
gh pr create --draft \
  --base main \
  --head chore/dep-groups-refactor \
  --title "chore(deps): split kb extras + delete dead deps + stub 503 router" \
  --body "$(cat <<'EOF'
## Roadmap 2026-05-07 dep refactor

落地 spec \`docs/superpowers/specs/2026-05-07-dep-groups-refactor-design.md\`,
plan \`docs/superpowers/plans/2026-05-07-dep-groups-refactor.md\`。

## 包含

- **pyproject.toml**:删 6 行(4 个 KB 重 deps 进 [optional] kb 组,
  matplotlib/seaborn 删 — 死 deps)
- **knowledge_stub.py**:新建 30 行 stub 路由,/knowledge/* 返 503
  + 信息明确的错误指 install 命令
- **app_main.py**:try/except import knowledge_router,失败 fallback stub
- **.github/workflows/pr.yml + nightly.yml**:install 改 \`--extra dev --extra kb\`
- **README.md**:安装段写"完整 vs 精简"两种
- **.devcontainer/README.md**:KB feature opt-in note + 32GB 局限警告
- **tests/unit/router/test_knowledge_stub.py**:4 个 test 验 stub 503 行为

## Acceptance(对照 spec § 8 自审)

- ✅ \`uv sync --extra dev\`(slim)装得快,没 KB 重 deps,app 起来,/knowledge 返 503
- ✅ \`uv sync --extra dev --extra kb\`(full)装齐,/knowledge 走真路由
- ✅ \`uv run poe ci\` 本地全绿
- ✅ Codespaces basicLinux32gb 装得下 slim install,/knowledge stub 503 工作

## Refs

- spec: \`docs/superpowers/specs/2026-05-07-dep-groups-refactor-design.md\`
- plan: \`docs/superpowers/plans/2026-05-07-dep-groups-refactor.md\`
- 关联 PR #23(devcontainer)— 本 PR ship 后 setup.sh 真能跑通

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch CI**

```bash
RUN_ID=$(gh run list --branch chore/dep-groups-refactor --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --exit-status
gh pr checks
```

Expected: lint-and-fast-tests pass(本 PR ship 后 CI 装 kb extras,所有现有 KB 测试继续过 + 新加的 test_knowledge_stub.py 也过)。

- [ ] **Step 4: 如果 CI 红,iterate**

常见失败模式(预测):
- ruff format on app_main.py 改动 — `uv run ruff format .` then push
- mypy strict on app_main.py 的 None type → 加 `type: ignore[assignment]`(已在 plan code 里)
- 某个测试 import knowledge_stub 但路径不对 — fix import

- [ ] **Step 5: CI 绿 + dogfood 完成 → mark ready**

```bash
gh pr ready
```

---

## Task 14: 落 memory + 收尾

**Files:**
- Create: `C:/Users/Administrator/.claude/projects/D--mys-Financial-Research-Investment-Assistant/memory/feedback_optional_extras_for_heavy_deps.md`
- Modify: `MEMORY.md`(加索引行)

- [ ] **Step 1: Write the new memory file**

```markdown
---
name: 重型 deps 走 optional extras
description: 项目级 dep 拆分模式 — 重型 ML/可选 feature deps 进 [project.optional-dependencies] 而不是 [project] base
type: feedback
---

KB / ML / viz 等"可选 feature"的 deps 应该放 `[project.optional-dependencies] <group>`,不是 `[project] dependencies`。

**Why:**
- base deps 决定每次 `uv sync` 的最小磁盘占用
- 个人作品里有 KB(mineru/torch/cuda 5-8GB)等重型 feature → base deps 塞不下 32GB Codespaces
- "feature 是不是核心"跟"deps 放哪一组"是两件事 — 装哪一组在 install 命令里控制(README 推荐 full,Codespaces 默认 slim)

**How to apply:**
- 加新 deps 前问:它服务的 feature 是 "must always installed" 还是 "opt-in for specific use case"?
- 后者 → 进 optional 组,在 README 安装段标明 "uv sync --extra dev --extra <group>"
- 加 router/service 用到 feature 时,在 app_main 用 try/except + stub fallback,装了真路由 / 没装 stub 503
- CI / 生产 / Mac dev 默认装齐(extras 不影响产品 hierarchy);Codespaces 默认 slim(磁盘约束)

参考 spec:`docs/superpowers/specs/2026-05-07-dep-groups-refactor-design.md`
参考 plan:`docs/superpowers/plans/2026-05-07-dep-groups-refactor.md`
```

- [ ] **Step 2: Update MEMORY.md index**

加一行(到 MEMORY.md):

```markdown
- [重型 deps 走 optional extras](feedback_optional_extras_for_heavy_deps.md) — 项目级 dep 拆分模式,base 留 core,重型/可选进 optional 组
```

- [ ] **Step 3: 不 commit memory(在 .claude/ 下,git 不追踪)**

---

## Self-Review Checklist

Per `superpowers:writing-plans` skill:

**1. Spec coverage(对照 spec § 1 决策摘要 + § 2-6 改动表):**

| Spec § | Plan task |
|---|---|
| § 1 决策 1 (minimal scope) | Task 2(pyproject 改动)|
| § 1 决策 2 (stub 503) | Task 3(knowledge_stub.py + 测试)+ Task 4(app_main 条件加载)|
| § 1 决策 3 (CI 装齐) | Task 7(pr.yml)+ Task 8(nightly.yml)|
| § 1 决策 4 (Mac/CI full, Codespaces slim) | Task 9(README)+ Task 10(.devcontainer/README)|
| § 2 pyproject 改 | Task 2 |
| § 3 代码改 | Task 3 + 4 |
| § 4 CI 改 | Task 7 + 8 |
| § 5 Codespaces / README | Task 9 + 10 |
| § 6 Migration | implicit in Task 9(README 写法引导用户)|
| § 7 风险:KB import 漏 grep | Task 1(audit grep)|
| § 7 风险:Mac 用户首次 sync 没 --extra kb | Task 9(README 写法 + 完整推荐)|
| § 7 风险:Codespaces 用户加 kb 装不下 | Task 10(.devcontainer/README 警告 + 推 64GB)|

**2. Placeholder scan:** 无 TBD / TODO / "implement later"。Task 1 step 4 的 "如果有 → 补 task list" 是 conditional logic 不是 placeholder(明确说明了什么情况下补什么)。

**3. Type consistency:**
- `_kb_router_available: bool`(Task 4 step 2 + 3 用同名)✓
- `_kb_import_error: str | None`(同上)✓
- `_UNAVAILABLE_DETAIL: dict[str, str]`(Task 3 step 3 + step 1 测试访问字段一致 — `error` / `message` / `doc`)✓
- 路由 prefix 全部 `/knowledge`(stub + 真路由都用同 prefix)✓

**4. File path consistency:** 所有 `backend/app/router/knowledge_stub.py` 路径一致 ✓;所有 spec/plan 引用路径一致 ✓。
