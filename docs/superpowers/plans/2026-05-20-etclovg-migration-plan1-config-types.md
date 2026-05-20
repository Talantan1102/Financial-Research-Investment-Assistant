# ETCLOVG Migration — Plan 1: 配置 + 类型 + Capability 重归属

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** [`docs/superpowers/specs/2026-05-20-harness-board-etclovg-migration-design.md`](../specs/2026-05-20-harness-board-etclovg-migration-design.md)

**版本归位**：v0.9.x harness-board ETCLOVG migration · **分支**：`refactor/etclovg-migration` · **PR 题（Plan 1 单独 PR）**：`refactor(harness-board): ETCLOVG Plan 1 — dimensions.yaml + capabilities.yaml + types 7 维重组`

**Goal**：把 dashboard 的维度模型从「自定义 8 维 + App Shell catch-all」一次性硬切到「论文 ETCLOVG 7 维 + `catch_all:` 顶层独立 key」。本 plan 只动**信息结构层**（yaml + types + derive 派生 + server.py 内部变量），**不动**前端模板 / CSS / 数据 jsonl / 测试 golden — 这三块分别属于 Plan 3 / Plan 2 / Plan 2。

**Architecture**：
- `dashboard/config/dimensions.yaml` 顶层结构变更 `dimensions: + app_shell:` → `dimensions: + catch_all:`
- `dashboard/config/capabilities.yaml` 62 → 68 capability，按 spec § 4 完整表重归属（C 层 22 项含 short_term / mid_term / long_term `group:` 字段；E 层 7 项全新增）
- `dashboard/derive/types.py` `DimensionId` Literal 从 10 项（8 维 + app_shell + unknown）改为 9 项（7 维 + shell + unknown）
- `dashboard/derive/path_router.py` `load_dimensions` 读 `data["catch_all"]`；`classify_path` sentinel `"app_shell"` → `"shell"`
- `dashboard/derive/{snapshot_builder, app_shell_stat}.py` 变量名 `_app_shell` / `app_shell` → `_catch_all` / `catch_all`（保留函数公开签名不破坏 server.py 调用方）
- `dashboard/server.py` 一处 sentinel 字符串 `"app_shell"`（Jinja ctx key）— 保留为兼容到 Plan 3（避免 base 模板未改时渲染挂掉）

**Tech Stack**：Python 3.11 / PyYAML / mypy strict / ruff / `uv run`

**Plan 1 完工预期状态**：
- ✅ mypy + ruff 全绿
- ✅ yaml load smoke 通过（68 capability 全部能 resolve）
- ✅ 启动 `dashboard.server` 不挂；GET `/api/overview/graph.json` 返 7 簇结构
- ⚠️ pytest **预期红**——11 个测试文件 golden 仍指旧 dim id；Plan 2 修复（不强求 Plan 1 跑 pytest 绿）
- ⚠️ 前端模板仍渲染旧 8 色板 / 8 spoke fingerprint — Plan 3 修复

**Breaking change**（写入 PR 描述）：`DimensionId` Literal 字面量集合变更（旧 → 新）；`dimensions.yaml` 顶层 key `app_shell:` → `catch_all:`。无外部 SDK 消费者，仅影响 dashboard 内部 + 测试。

---

## File Structure（Plan 1 范围）

**新建**：（无 — Plan 1 仅修改现有文件）

**修改**：
- `dashboard/config/dimensions.yaml` — 整文件重写
- `dashboard/config/capabilities.yaml` — 整文件重写
- `dashboard/derive/types.py` — `DimensionId` Literal + `CapabilityConfig.dimension` 注释
- `dashboard/derive/path_router.py` — `load_dimensions` 读 catch_all key + `classify_path` sentinel
- `dashboard/derive/snapshot_builder.py` — 变量名 `_app_shell` → `_catch_all`（行 64）
- `dashboard/derive/app_shell_stat.py` — docstring 与变量名更新（不动公开函数名 `compute_app_shell_stat`，Plan 3 再改）
- `dashboard/derive/capability_resolver.py` — 检查 derive_rule 列表式断言，按需调整

**不动**（Plan 2/3 范围）：
- `dashboard/data/deep_cards_seed.jsonl` / `dashboard/data/external_agent_survey.jsonl`
- `dashboard/templates/*.html` / `dashboard/static/*`
- `dashboard/tests/**`（测试 golden 在 Plan 2 同步）
- `dashboard/server.py` 行 123 `"app_shell"` Jinja ctx key（暂留兼容）

---

## Task 1：起分支 + 备份 baseline metadata

**Files**：（无文件改动，仅 git 操作）

- [ ] **Step 1：核实分支状态**

Run: `git status && git branch --show-current`
Expected：当前在 `spec/pg-only-migration` 分支；working tree 干净（spec 已 commit 或 staged）。若 spec 改动未 commit，先单独 commit spec。

- [ ] **Step 2：spec commit（若尚未 commit）**

```bash
git add docs/superpowers/specs/2026-05-20-harness-board-etclovg-migration-design.md \
        docs/superpowers/plans/2026-05-20-etclovg-migration-plan1-config-types.md
git commit -m "$(cat <<'EOF'
spec(etclovg): ETCLOVG 7 维迁移 design doc + Plan 1

把看板维度从自定义 8 维迁移到论文 ETCLOVG 7 维(Execution/Tooling/
Context/Lifecycle/Observability/Verification/Governance),并把视觉
风格从 Quiet Workshop 切到 iOS Calm Minimal。

四件套结构含 8 个非平凡决策 + 9 个决议(含 4 个视觉决议)。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3：开 feature 分支**

```bash
git checkout -b refactor/etclovg-migration
```

- [ ] **Step 4：记录 baseline snapshot**

Run（不 commit，仅在 plan 内做 reference 笔记）：
```bash
uv run python -c "
from pathlib import Path
from dashboard.derive.snapshot_builder import build_snapshot
snap = build_snapshot(Path('.'), Path('dashboard/config'))
print('baseline_total_lit:', snap.total_lit)
print('baseline_layers:', [(l.id, l.lit, l.total) for l in snap.layers])
" 2>&1 | tee /tmp/etclovg_baseline.txt
```
Expected：输出当前 8 维 lit 数（预期 ~38 lit），存到 /tmp 作 Plan 1 完工对照。

---

## Task 2：重写 `dashboard/config/dimensions.yaml`

**Files**：
- Modify: `dashboard/config/dimensions.yaml`

**契约**：
- 顶层 key 改为 `dimensions: + catch_all:`（不再用 `app_shell:`）
- `dimensions:` 7 项，编号 `01`-`07`，按 ETCLOVG 顺序：E / T / C / L / O / V / G
- `catch_all:` 5 项，无 `number` 字段（不参与主泳道编号）
- `id` 字段值见 spec § 4 末段约定

- [ ] **Step 1：写入新 yaml 内容**

完整文件内容如下（直接 Write 覆盖）：

```yaml
# dashboard/config/dimensions.yaml
# ETCLOVG 7 维主泳道 + catch_all 5 项(path_router fallback / D-view 代码地图)
# 冲突解决:更具体的优先 (specificity = path_glob 去通配符后字符数)
# 论文锚点: Li et al., Agent Harness Engineering: A Survey (2026), §2.3

dimensions:
  - id: execution
    number: "01"
    name_cn: "执行环境与沙箱"
    name_en: "Execution Environment & Sandbox"
    paths:
      - "docker/**"
      - "docker-compose.yml"
      - ".github/**"
      - "scripts/**"
      - "backend/data/**"
      - "backend/app/tasks/celery_*.py"
    keywords: ["sandbox", "docker", "celery"]

  - id: tool
    number: "02"
    name_cn: "工具接口与协议"
    name_en: "Tool Interface & Protocol"
    paths:
      - "backend/app/tools/**"
      - "backend/app/services/tool_registry*.py"
      - "backend/app/services/tushare_client*.py"
      - "backend/app/services/bocha_client*.py"
      - "backend/app/services/milvus_client*.py"
    keywords: ["Protocol", "tool", "MCP"]

  - id: context
    number: "03"
    name_cn: "上下文与记忆"
    name_en: "Context & Memory Management"
    paths:
      - "backend/app/services/llm_*.py"
      - "backend/app/services/skills/**"
      - "backend/app/skills/**"
      - "backend/app/services/milvus_*.py"
      - "backend/app/services/bocha_*.py"
      - "backend/app/services/kb_*.py"
      - "backend/app/services/corpus_*.py"
      - "backend/app/services/embedding_*.py"
      - "backend/app/services/memory_*.py"
    keywords: ["tier", "schema", "Skills", "embedding", "retrieve", "Memory"]

  - id: lifecycle
    number: "04"
    name_cn: "生命周期与编排"
    name_en: "Lifecycle & Orchestration"
    paths:
      - "backend/app/agents/**"
      - "backend/app/orchestration/**"
      - "backend/app/services/checkpointer*.py"
    keywords: ["LangGraph", "agent", "subgraph", "checkpoint", "Saver"]

  - id: observability
    number: "05"
    name_cn: "可观测与运营"
    name_en: "Observability & Operations"
    paths:
      - "backend/app/services/trace*.py"
      - "backend/app/services/monitoring/**"
      - "backend/app/services/tier_router*.py"
      - "backend/app/services/pricing*.py"
      - "backend/app/services/cost_budget*.py"
      - "backend/app/services/quota*.py"
      - "backend/app/services/rate_limiter*.py"
      - "dashboard/**"
    keywords: ["TraceService", "TierRouter", "pricing", "monitoring"]

  - id: verification
    number: "06"
    name_cn: "验证与评测"
    name_en: "Verification & Evaluation"
    paths:
      - "backend/app/services/eval_*.py"
      - "backend/app/services/judge*.py"
      - "backend/app/services/recorder*.py"
      - "backend/tests/**"
    keywords: ["EvalRunner", "Judge", "golden", "cassette"]

  - id: governance
    number: "07"
    name_cn: "治理与安全"
    name_en: "Governance & Security"
    paths:
      - "backend/app/services/constrained_router*.py"
      - "backend/app/services/critic*.py"
      - "backend/app/services/validator*.py"
      - "backend/app/router/auth*.py"
      - "frontend/src/pages/auth/**"
      - "frontend/src/components/auth-guard/**"
      - "frontend/src/api/auth*"
      - "frontend/src/store/auth*"
    keywords: ["Schema", "Pydantic", "auth", "guardrail"]

catch_all:
  - id: shell.frontend
    name_cn: "前端外壳"
    paths:
      - "frontend/src/**"
  - id: shell.backend_router
    name_cn: "后端路由外壳"
    paths:
      - "backend/app/router/**"
      - "backend/app/app_main.py"
      - "backend/app/core/**"
  - id: shell.database
    name_cn: "数据库外壳"
    paths:
      - "backend/app/core/database.py"
      - "backend/app/router/database_router.py"
      - "backend/app/service/database_explorer.py"
      - "backend/data/*.sqlite"
      - "backend/data/*.db"
  - id: shell.connectors
    name_cn: "外部数据连接器外壳"
    paths:
      - "backend/app/service/*_connector*.py"
  - id: shell.infra
    name_cn: "部署 / CI 外壳"
    paths:
      - "pyproject.toml"
      - "uv.lock"
      - "Makefile"
```

- [ ] **Step 2：验证 yaml syntax**

Run:
```bash
uv run python -c "
import yaml
from pathlib import Path
data = yaml.safe_load(Path('dashboard/config/dimensions.yaml').read_text())
assert set(data.keys()) == {'dimensions', 'catch_all'}, data.keys()
assert len(data['dimensions']) == 7
assert len(data['catch_all']) == 5
ids = [d['id'] for d in data['dimensions']]
expected = ['execution', 'tool', 'context', 'lifecycle', 'observability', 'verification', 'governance']
assert ids == expected, ids
print('OK: 7 维 + 5 catch_all')
"
```
Expected：`OK: 7 维 + 5 catch_all`

- [ ] **Step 3：暂不 commit**（与 capabilities.yaml 一起 commit，Task 5）

---

## Task 3：改 `dashboard/derive/types.py` 的 `DimensionId` Literal

**Files**：
- Modify: `dashboard/derive/types.py`

- [ ] **Step 1：读现状**

Read: `dashboard/derive/types.py`（行 8-20）

- [ ] **Step 2：替换 Literal**

将：
```python
DimensionId = Literal[
    "prompt_context",
    "tools_function",
    "orchestration",
    "memory",
    "rag_knowledge",
    "guardrails",
    "eval_observability",
    "cost_routing",
    "app_shell",
    "unknown",
]
```

改为：
```python
DimensionId = Literal[
    "execution",
    "tool",
    "context",
    "lifecycle",
    "observability",
    "verification",
    "governance",
    "shell",
    "unknown",
]
```

说明：
- 7 维主泳道用单字 lowercase（`execution` / `tool` / `context` / `lifecycle` / `observability` / `verification` / `governance`）
- `shell` 是 catch_all 子项归属时 path_router 返回的统一标签
- `unknown` 保留为 fallback

- [ ] **Step 3：跑 mypy 只检查 types.py**

Run:
```bash
uv run mypy dashboard/derive/types.py
```
Expected：Success: no issues found in 1 source file

- [ ] **Step 4：暂不 commit**（与下面 path_router 等一起 commit，Task 6）

---

## Task 4：改 `dashboard/derive/path_router.py` 读 `catch_all:` key

**Files**：
- Modify: `dashboard/derive/path_router.py`

- [ ] **Step 1：读现状**

Read: `dashboard/derive/path_router.py`

- [ ] **Step 2：改 module docstring**

将：
```python
"""路径 → 8 维主泳道 + App Shell 归类。

冲突解决:更具体的优先 (specificity = path_glob 去通配符后字符数)。
"""
```

改为：
```python
"""路径 → ETCLOVG 7 维主泳道 + catch_all 归类。

冲突解决:更具体的优先 (specificity = path_glob 去通配符后字符数)。
未命中主泳道但命中 catch_all 返 "shell";都未命中返 "unknown"。
论文锚点: Li et al., Agent Harness Engineering: A Survey (2026), §2.3。
"""
```

- [ ] **Step 3：改 `load_dimensions` 函数**

将：
```python
def load_dimensions(
    yaml_path: Path,
) -> tuple[list[DimensionConfig], list[DimensionConfig]]:
    """加载 dimensions.yaml,返回 (8 维主泳道, App Shell 6 项)。"""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    main = [
        DimensionConfig(
            id=d["id"],
            number=d["number"],
            name_cn=d["name_cn"],
            name_en=d["name_en"],
            paths=tuple(d["paths"]),
            keywords=tuple(d.get("keywords", [])),
        )
        for d in data["dimensions"]
    ]
    app_shell = [
        DimensionConfig(
            id=d["id"],  # M2:保留 frontend/backend/auth/... 子 id
            number="09",
            name_cn=d["name_cn"],
            name_en=d["name_cn"],  # App Shell 子项无 name_en,降级用中文
            paths=tuple(d["paths"]),
        )
        for d in data["app_shell"]
    ]
    return main, app_shell
```

改为：
```python
def load_dimensions(
    yaml_path: Path,
) -> tuple[list[DimensionConfig], list[DimensionConfig]]:
    """加载 dimensions.yaml,返回 (7 维 ETCLOVG 主泳道, catch_all 5 项)。"""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    main = [
        DimensionConfig(
            id=d["id"],
            number=d["number"],
            name_cn=d["name_cn"],
            name_en=d["name_en"],
            paths=tuple(d["paths"]),
            keywords=tuple(d.get("keywords", [])),
        )
        for d in data["dimensions"]
    ]
    catch_all = [
        DimensionConfig(
            id=d["id"],  # 保留 shell.frontend / shell.backend_router 等子 id
            number="08",  # 仅占位,catch_all 不参与主泳道编号
            name_cn=d["name_cn"],
            name_en=d["name_cn"],  # catch_all 无 name_en,降级用中文
            paths=tuple(d["paths"]),
        )
        for d in data["catch_all"]
    ]
    return main, catch_all
```

- [ ] **Step 4：改 `classify_path` sentinel**

将：
```python
def classify_path(
    path: str,
    main_dims: list[DimensionConfig],
    app_shell: list[DimensionConfig],
) -> DimensionId:
    """归类一个 forward-slash 路径到 dimension id;无命中返 'unknown'。"""
    candidates: list[tuple[int, DimensionId]] = []
    for d in main_dims:
        for glob in d.paths:
            if fnmatch(path, glob):
                # main_dims 的 id 在 yaml 内容上仍为 DimensionId 子集,运行时安全
                candidates.append((_specificity(glob), cast(DimensionId, d.id)))
    for d in app_shell:
        for glob in d.paths:
            if fnmatch(path, glob):
                candidates.append((_specificity(glob), "app_shell"))
    if not candidates:
        return "unknown"
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
```

改为：
```python
def classify_path(
    path: str,
    main_dims: list[DimensionConfig],
    catch_all: list[DimensionConfig],
) -> DimensionId:
    """归类一个 forward-slash 路径到 dimension id;无命中返 'unknown'。

    主泳道 7 维优先;未命中主泳道但命中 catch_all 统一返 'shell'(子 id
    在 D-view 代码地图渲染时由调用方从 catch_all list 二次查询)。
    """
    candidates: list[tuple[int, DimensionId]] = []
    for d in main_dims:
        for glob in d.paths:
            if fnmatch(path, glob):
                # main_dims 的 id 在 yaml 内容上仍为 DimensionId 子集,运行时安全
                candidates.append((_specificity(glob), cast(DimensionId, d.id)))
    for d in catch_all:
        for glob in d.paths:
            if fnmatch(path, glob):
                candidates.append((_specificity(glob), "shell"))
    if not candidates:
        return "unknown"
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
```

- [ ] **Step 5：跑 mypy 校验**

Run:
```bash
uv run mypy dashboard/derive/path_router.py dashboard/derive/types.py
```
Expected：Success: no issues found

---

## Task 5：重写 `dashboard/config/capabilities.yaml`

**Files**：
- Modify: `dashboard/config/capabilities.yaml`

**契约**（按 spec § 4 完整表）：
- 7 维 dimensions，按 E / T / C / L / O / V / G 顺序
- 68 capability 总数（E 层 7 项新增 + 其余 61 项重归属 + 1 项合并去重）
- C 层 22 项含 `group:` 字段（值为 `short_term` / `mid_term` / `long_term`）
- `cap_id` 内部不再带前缀（cap_id 仅 `<cap_local>`，dimension 字段标维度）—— **注意：cap_id rename map 由 Plan 2 数据迁移脚本使用**，但 capabilities.yaml 内 `id` 字段不带 dim 前缀，因为 `dimension:` 字段已经标识所属维度

> **Step 实施时 implementer 注意**：每个 capability 必须含 `id` / `name_cn` / `name_en` / `derive_rule` 四字段；C 层额外含 `group`。`derive_rule` 5 种类型：`code_grep` / `file_exists` / `spec_section` / `memory_frontmatter` / `manual`。

- [ ] **Step 1：写入新 yaml**

完整文件内容（直接 Write 覆盖）：

```yaml
# dashboard/config/capabilities.yaml
# 单一真源 — 68 项 capability + derive_rule (ETCLOVG 7 维)
# 5 类 derive_rule: code_grep / file_exists / spec_section / memory_frontmatter / manual
# 论文锚点: Li et al., Agent Harness Engineering: A Survey (2026)

dimensions:

  # ============================================================
  # 01 Execution Environment & Sandbox (7 项,预期 6-7 lit) §3
  # ============================================================
  - id: execution
    capabilities:
      - id: docker_compose
        name_cn: "Docker Compose 编排"
        name_en: "Docker Compose orchestration"
        derive_rule: { type: file_exists, path: 'docker-compose.yml' }
      - id: container_isolation
        name_cn: "容器隔离 (Dockerfile)"
        name_en: "Container isolation"
        derive_rule: { type: file_exists, path: 'docker' }
      - id: ci_workflow
        name_cn: "CI workflow"
        name_en: "CI workflow"
        derive_rule: { type: file_exists, path: '.github/workflows' }
      - id: venv_isolation
        name_cn: "uv venv 隔离"
        name_en: "uv venv isolation"
        derive_rule: { type: file_exists, path: 'pyproject.toml' }
      - id: persistence_layer
        name_cn: "持久化层 (sqlite 集合)"
        name_en: "Persistence layer"
        derive_rule: { type: file_exists, path: 'backend/data' }
      - id: tushare_cache_isolation
        name_cn: "Tushare 缓存隔离"
        name_en: "Tushare cache isolation"
        derive_rule: { type: file_exists, path: 'backend/data/tushare_cache.sqlite' }
      - id: celery_redis
        name_cn: "Celery + Redis 异步队列"
        name_en: "Celery + Redis async queue"
        derive_rule: { type: file_exists, path: 'backend/app/tasks/celery_app.py' }

  # ============================================================
  # 02 Tool Interface & Protocol (8 项,预期 5 lit) §4
  # ============================================================
  - id: tool
    capabilities:
      - id: tool_registry
        name_cn: "Tool Registry"
        name_en: "Tool Registry"
        derive_rule: { type: file_exists, path: 'backend/app/tools/registry.py' }
      - id: schema_validated_io
        name_cn: "Schema-validated tool I/O"
        name_en: "Schema-validated I/O"
        derive_rule: { type: code_grep, pattern: 'args_schema:\s*type\[BaseModel\]', path_glob: 'backend/app/tools/base.py' }
      - id: di_mock_real
        name_cn: "DI mock/real 切换"
        name_en: "DI mock/real toggle"
        derive_rule: { type: code_grep, pattern: 'MOCK|TUSHARE_MODE|BOCHA_MODE', path_glob: 'backend/app/services/*_factory.py' }
      - id: reliability_layer
        name_cn: "Reliability layer (5 件)"
        name_en: "Reliability (circuit/retry/timeout/cb/quota)"
        derive_rule: { type: file_exists, path: 'backend/app/services/circuit_breaker.py' }
      - id: financial_tools
        name_cn: "8 个金融工具"
        name_en: "8 financial tools"
        derive_rule: { type: code_grep, pattern: 'class\s+\w+\(Tool\)', path_glob: 'backend/app/tools/get_*.py' }
      - id: mcp_bridge
        name_cn: "MCP 协议适配"
        name_en: "MCP bridge"
        derive_rule: { type: manual }
      - id: tool_versioning
        name_cn: "工具版本化"
        name_en: "Tool versioning"
        derive_rule: { type: manual }
      - id: parallel_tool_calls
        name_cn: "并行 tool calls"
        name_en: "Parallel tool calls"
        derive_rule: { type: manual }

  # ============================================================
  # 03 Context & Memory Management (22 项,预期 ~9 lit) §5
  # group: short_term / mid_term / long_term (子分组仅 yaml 内部,UI 不暴露)
  # ============================================================
  - id: context
    capabilities:
      # ---- short_term (9 项) ----
      - id: multi_tier_signature
        group: short_term
        name_cn: "多层级签名"
        name_en: "Multi-tier signature"
        derive_rule: { type: code_grep, pattern: 'tier:\s*Tier', path_glob: 'backend/app/services/llm_*.py' }
      - id: constrained_schema
        group: short_term
        name_cn: "输出 Schema 约束"
        name_en: "Constrained schema"
        derive_rule: { type: code_grep, pattern: 'response_format', path_glob: 'backend/app/services/openai_client.py' }
      - id: skills_bundle
        group: short_term
        name_cn: "Skills bundle (17-component)"
        name_en: "Skills bundle"
        derive_rule: { type: file_exists, path: 'backend/app/skills/financial_research' }
      - id: per_task_registry
        group: short_term
        name_cn: "Per-task plan registry"
        name_en: "Per-task plan registry"
        derive_rule: { type: code_grep, pattern: 'plan_registry', path_glob: 'backend/app/agents/**' }
      - id: max_tokens_calibration
        group: short_term
        name_cn: "max_tokens per-model 校准"
        name_en: "max_tokens calibration"
        derive_rule: { type: code_grep, pattern: 'max_tokens', path_glob: 'backend/app/services/openai_client.py' }
      - id: prompt_versioning
        group: short_term
        name_cn: "Prompt 版本化"
        name_en: "Prompt Versioning"
        derive_rule: { type: manual }
      - id: few_shot_library
        group: short_term
        name_cn: "Few-shot 示例库"
        name_en: "Few-shot library"
        derive_rule: { type: manual }
      - id: prompt_caching
        group: short_term
        name_cn: "Prompt 缓存"
        name_en: "Prompt caching"
        derive_rule: { type: manual }
      - id: ctx_compression
        group: short_term
        name_cn: "上下文压缩"
        name_en: "Context compression"
        derive_rule: { type: manual }
      # ---- mid_term (0 项,留空) ----
      # ---- long_term — memory (5 项 manual) ----
      - id: long_term_memory
        group: long_term
        name_cn: "长期记忆"
        name_en: "Long-term memory"
        derive_rule: { type: manual }
      - id: semantic_memory
        group: long_term
        name_cn: "语义记忆"
        name_en: "Semantic memory"
        derive_rule: { type: manual }
      - id: cross_user_cache
        group: long_term
        name_cn: "跨用户缓存"
        name_en: "Cross-user cache"
        derive_rule: { type: manual }
      - id: episodic_memory
        group: long_term
        name_cn: "情景记忆"
        name_en: "Episodic memory"
        derive_rule: { type: manual }
      - id: memory_compression
        group: long_term
        name_cn: "记忆压缩"
        name_en: "Memory compression"
        derive_rule: { type: manual }
      # ---- long_term — RAG (8 项) ----
      - id: milvus_3_collection
        group: long_term
        name_cn: "Milvus 3 collection schema"
        name_en: "Milvus 3 collection"
        derive_rule: { type: code_grep, pattern: 'create_collection', path_glob: 'backend/app/services/milvus_*.py' }
      - id: embedding_cache
        group: long_term
        name_cn: "Embedding + 缓存"
        name_en: "Embedding + cache"
        derive_rule: { type: file_exists, path: 'backend/app/services/embedding_service.py' }
      - id: corpus_ingest
        group: long_term
        name_cn: "13 真 corpus ingest"
        name_en: "13 corpus ingest"
        derive_rule: { type: manual }
      - id: bocha_web
        group: long_term
        name_cn: "Bocha 网络搜索"
        name_en: "Bocha web search"
        derive_rule: { type: file_exists, path: 'backend/app/services/bocha_client.py' }
      - id: kb_reliability
        group: long_term
        name_cn: "KB reliability layer"
        name_en: "KB reliability"
        derive_rule: { type: file_exists, path: 'backend/app/services/reliable_kb_service.py' }
      - id: reranker
        group: long_term
        name_cn: "Reranker"
        name_en: "Reranker"
        derive_rule: { type: manual }
      - id: hybrid_search
        group: long_term
        name_cn: "稠密 + 稀疏混合检索"
        name_en: "Hybrid search"
        derive_rule: { type: manual }
      - id: query_decomposition
        group: long_term
        name_cn: "Query 分解"
        name_en: "Query decomposition"
        derive_rule: { type: manual }

  # ============================================================
  # 04 Lifecycle & Orchestration (10 项,预期 6 lit) §6
  # ============================================================
  - id: lifecycle
    capabilities:
      - id: langgraph_skeleton
        name_cn: "LangGraph 骨架"
        name_en: "LangGraph skeleton"
        derive_rule: { type: code_grep, pattern: 'StateGraph', path_glob: 'backend/app/agents/**' }
      - id: typed_state
        name_cn: "Typed State (Pydantic)"
        name_en: "Typed State"
        derive_rule: { type: code_grep, pattern: 'class.*State.*BaseModel', path_glob: 'backend/app/agents/**' }
      - id: send_subgraph
        name_cn: "Send + subgraph 并行"
        name_en: "Send + subgraph"
        derive_rule: { type: code_grep, pattern: 'Send\(', path_glob: 'backend/app/orchestration/**' }
      - id: critic_7_stage
        name_cn: "7 阶段 Critic"
        name_en: "7-stage Critic"
        derive_rule: { type: file_exists, path: 'backend/app/agents/critic.py' }
      - id: sse_streaming
        name_cn: "SSE 流式"
        name_en: "SSE streaming"
        derive_rule: { type: code_grep, pattern: 'EventSource|StreamingResponse', path_glob: 'backend/app/router/**' }
      - id: session_checkpoint
        name_cn: "Session checkpoint (SqliteSaver)"
        name_en: "Session checkpoint"
        derive_rule: { type: code_grep, pattern: 'SqliteSaver', path_glob: 'backend/app/orchestration/**' }
      - id: langgraph_retry
        name_cn: "LangGraph retry edge"
        name_en: "LangGraph retry"
        derive_rule: { type: code_grep, pattern: 'add_edge.*retry|conditional_edges', path_glob: 'backend/app/orchestration/**' }
      - id: plan_and_execute
        name_cn: "Plan-and-Execute pattern"
        name_en: "Plan-and-Execute"
        derive_rule: { type: manual }
      - id: human_in_the_loop
        name_cn: "Human-in-the-loop"
        name_en: "Human-in-the-loop"
        derive_rule: { type: manual }
      - id: agent_handoff
        name_cn: "Agent handoff"
        name_en: "Agent handoff"
        derive_rule: { type: manual }

  # ============================================================
  # 05 Observability & Operations (9 项,预期 5 lit) §7
  # ============================================================
  - id: observability
    capabilities:
      - id: trace_service
        name_cn: "TraceService"
        name_en: "TraceService"
        derive_rule: { type: code_grep, pattern: 'TraceService|trace_id', path_glob: 'backend/app/services/eval_*.py' }
      - id: latency_p95
        name_cn: "p95 latency 监控"
        name_en: "p95 latency monitoring"
        derive_rule: { type: manual }
      - id: harness_board
        name_cn: "项目 Harness Board (本工具)"
        name_en: "Harness Board"
        derive_rule: { type: file_exists, path: 'dashboard/server.py' }
      - id: tier_router
        name_cn: "Tier Router (3 层)"
        name_en: "Tier Router"
        derive_rule: { type: file_exists, path: 'backend/app/services/tier_router.py' }
      - id: pricing_table
        name_cn: "Pricing 静态表"
        name_en: "Pricing"
        derive_rule: { type: file_exists, path: 'backend/app/services/pricing.py' }
      - id: cost_budget
        name_cn: "Cost budget"
        name_en: "Cost budget"
        derive_rule: { type: file_exists, path: 'backend/app/services/cost_budget.py' }
      - id: model_caching
        name_cn: "Model response 缓存"
        name_en: "Model caching"
        derive_rule: { type: manual }
      - id: fallback_router
        name_cn: "Fallback router"
        name_en: "Fallback router"
        derive_rule: { type: manual }
      - id: cost_alert
        name_cn: "Cost 预警"
        name_en: "Cost alerting"
        derive_rule: { type: manual }

  # ============================================================
  # 06 Verification & Evaluation (7 项,预期 5 lit) §8
  # ============================================================
  - id: verification
    capabilities:
      - id: eval_runner
        name_cn: "EvalRunner"
        name_en: "EvalRunner"
        derive_rule: { type: file_exists, path: 'backend/app/services/eval_runner.py' }
      - id: llm_judge
        name_cn: "LLM-as-Judge"
        name_en: "LLM-as-Judge"
        derive_rule: { type: file_exists, path: 'backend/app/services/judge.py' }
      - id: golden_cases
        name_cn: "12+ golden cases"
        name_en: "12+ golden cases"
        derive_rule: { type: code_grep, pattern: 'golden', path_glob: 'backend/tests/**' }
      - id: cassette_l2
        name_cn: "L2 Cassette VCR"
        name_en: "L2 Cassette"
        derive_rule: { type: code_grep, pattern: 'vcr_config|LLM_MODE', path_glob: 'backend/tests/**' }
      - id: test_suite
        name_cn: "289+ pytest"
        name_en: "289+ tests"
        derive_rule: { type: file_exists, path: 'backend/tests' }
      - id: ab_testing
        name_cn: "A/B testing"
        name_en: "A/B testing"
        derive_rule: { type: manual }
      - id: adversarial_test
        name_cn: "对抗测试"
        name_en: "Adversarial testing"
        derive_rule: { type: manual }

  # ============================================================
  # 07 Governance & Security (6 项,预期 3-4 lit) §9
  # ============================================================
  - id: governance
    capabilities:
      - id: constrained_router
        name_cn: "Constrained LLM Router"
        name_en: "Constrained Router"
        derive_rule: { type: code_grep, pattern: 'constrained', path_glob: 'backend/app/agents/research_planner.py' }
      - id: pydantic_schema
        name_cn: "Pydantic schema 验证"
        name_en: "Pydantic schema"
        derive_rule: { type: code_grep, pattern: 'BaseModel', path_glob: 'backend/app/agents/**' }
      - id: per_step_critic
        name_cn: "Per-step Critic"
        name_en: "Per-step Critic"
        derive_rule: { type: file_exists, path: 'backend/app/agents/critic_subagents' }
      - id: auth
        name_cn: "Auth 鉴权"
        name_en: "Auth"
        derive_rule: { type: file_exists, path: 'backend/app/router/auth_router.py' }
      - id: pii_redaction
        name_cn: "PII 脱敏"
        name_en: "PII redaction"
        derive_rule: { type: manual }
      - id: hallucination_check
        name_cn: "幻觉检测"
        name_en: "Hallucination check"
        derive_rule: { type: manual }
```

- [ ] **Step 2：验证 yaml syntax + capability 数量**

Run:
```bash
uv run python -c "
import yaml
from pathlib import Path
from collections import Counter
data = yaml.safe_load(Path('dashboard/config/capabilities.yaml').read_text())
dims = data['dimensions']
counts = {d['id']: len(d['capabilities']) for d in dims}
total = sum(counts.values())
expected = {'execution': 7, 'tool': 8, 'context': 22, 'lifecycle': 10, 'observability': 9, 'verification': 7, 'governance': 6}
print('per-dim:', counts)
print('total:', total)
assert counts == expected, f'mismatch: {counts}'
assert total == 69, total  # 7+8+22+10+9+7+6 = 69
# group field check for context
ctx = next(d for d in dims if d['id'] == 'context')
groups = Counter(c.get('group', 'NONE') for c in ctx['capabilities'])
print('context groups:', dict(groups))
assert groups['NONE'] == 0, 'context capabilities 必须含 group field'
print('OK: 7 dim / 69 cap / context grouped')
"
```
Expected：`OK: 7 dim / 69 cap / context grouped`

> 注：spec § 4 估算 68 项，实际重数后 69 项（含 langgraph_retry 从 G 迁 L 算 lifecycle 第 7 项；adversarial_test 从 G 迁 V 算 verification 第 7 项；G 层从 7 项减为 6 项）。最终 7+8+22+10+9+7+6 = 69。

- [ ] **Step 3：暂不 commit**（与 dimensions.yaml 一起，Task 6）

---

## Task 6：变量名/docstring 顺手修 + 整体 commit

**Files**：
- Modify: `dashboard/derive/snapshot_builder.py`（行 64 变量名）
- Modify: `dashboard/derive/app_shell_stat.py`（docstring + 参数名 — 公开函数名 `compute_app_shell_stat` **保留**到 Plan 3 再改）

- [ ] **Step 1：snapshot_builder.py 改变量名**

Edit:
```python
main_dims, _app_shell = load_dimensions(config_dir / "dimensions.yaml")
```
改为：
```python
main_dims, _catch_all = load_dimensions(config_dir / "dimensions.yaml")
```

- [ ] **Step 2：app_shell_stat.py docstring 更新**

将 module docstring：
```python
"""App Shell 第 9 行 mini stat — 数 6 项各命中多少文件。"""
```

改为：
```python
"""catch_all 第 8 行 mini stat — 数 5 项各命中多少文件。

> Plan 1 仅改 docstring 与参数名;公开函数名 `compute_app_shell_stat`
> 保留到 Plan 3 一起改(避免 server.py 调用方破坏)。
"""
```

并把函数内 `for d in app_shell:` 改成 `for d in catch_all:`，参数名 `app_shell` 改成 `catch_all`（同时函数签名）：

```python
def compute_app_shell_stat(
    project_root: Path,
    catch_all: list[DimensionConfig],
) -> list[AppShellItem]:
    """对 catch_all 5 项,各自跑 glob 数文件,返回 AppShellItem 列表。"""
    out: list[AppShellItem] = []
    for d in catch_all:
        count = 0
        ...
```

> ⚠ server.py 行 115 调用 `compute_app_shell_stat(PROJECT_ROOT, app_shell_dims)` — 调用方变量名也要改：

Edit `dashboard/server.py` 行 114-115:
```python
_main_dims, app_shell_dims = load_dimensions(CONFIG_DIR / "dimensions.yaml")
app_shell = compute_app_shell_stat(PROJECT_ROOT, app_shell_dims)
```
改为：
```python
_main_dims, catch_all_dims = load_dimensions(CONFIG_DIR / "dimensions.yaml")
app_shell = compute_app_shell_stat(PROJECT_ROOT, catch_all_dims)
```

> 注意 `app_shell = compute_app_shell_stat(...)` 这一行**保留**变量名 `app_shell`，因为下面 `ctx["app_shell"] = app_shell` 是 Jinja 模板上下文 key，Plan 3 改模板时一起换。

- [ ] **Step 3：grep 确认无其他 `data["app_shell"]` 残留**

Run:
```bash
grep -rn 'data\["app_shell"\]\|data\[.app_shell.\]\|"app_shell"' dashboard/derive/ dashboard/server.py
```
Expected：仅命中 `dashboard/server.py:123: "app_shell": app_shell`（Jinja ctx key，Plan 3 改）；derive/ 下应无残留。

- [ ] **Step 4：跑 mypy 全 dashboard**

Run:
```bash
uv run mypy dashboard
```
Expected：Success: no issues found

- [ ] **Step 5：跑 ruff**

Run:
```bash
uv run ruff check dashboard && uv run ruff format --check dashboard
```
Expected：无 violation；若 format 有 diff，跑 `uv run ruff format dashboard` 修复后再 check。

- [ ] **Step 6：commit 配置 + 类型变更**

```bash
git add dashboard/config/dimensions.yaml \
        dashboard/config/capabilities.yaml \
        dashboard/derive/types.py \
        dashboard/derive/path_router.py \
        dashboard/derive/snapshot_builder.py \
        dashboard/derive/app_shell_stat.py \
        dashboard/server.py

git commit -m "$(cat <<'EOF'
refactor(harness-board): ETCLOVG 7 维结构 — yaml + types + path_router

把 dashboard 维度模型从「自定义 8 维 + App Shell」一次性切到论文
ETCLOVG 7 维(Execution/Tool/Context/Lifecycle/Observability/
Verification/Governance)+ catch_all 顶层独立 key。

- dimensions.yaml: 8 维 → 7 维 + catch_all 5 项
- capabilities.yaml: 62 → 69 cap (E 层 7 项新增 + C 层加 group 字段)
- types.py: DimensionId Literal 7 项
- path_router.py: 读 data["catch_all"]; sentinel "app_shell" → "shell"
- snapshot_builder / app_shell_stat: 变量名 _app_shell → _catch_all
- server.py: 调用方变量名同步(Jinja ctx key "app_shell" 保留到 Plan 3)

Plan 1 完工状态:
- mypy + ruff 全绿
- pytest 预期红(11 个 test 文件 golden 仍指旧 dim id, Plan 2 修复)
- 模板渲染仍是旧 8 色板(Plan 3 切 iOS Calm Minimal)
- 数据 jsonl 仍是旧 cap_id(Plan 2 迁移)

Spec: docs/superpowers/specs/2026-05-20-harness-board-etclovg-migration-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7：启动 dashboard 烟测 yaml load + capability snapshot

**Files**：（无文件改动，仅 runtime 验证）

- [ ] **Step 1：snapshot smoke 通过 capability_resolver**

Run:
```bash
uv run python -c "
from pathlib import Path
from dashboard.derive.snapshot_builder import build_snapshot
snap = build_snapshot(Path('.'), Path('dashboard/config'))
print('total_lit:', snap.total_lit, 'total_wip:', snap.total_wip, 'total_todo:', snap.total_todo)
print()
print('per-dim:')
for layer in snap.layers:
    print(f'  {layer.id:15s} {layer.number}  lit={layer.lit:2d} wip={layer.wip:2d} todo={layer.todo:2d} total={layer.total}')
" 2>&1 | tee /tmp/etclovg_plan1.txt
```

Expected 输出（容许 ±1 lit 偏差）：
```
total_lit: 40-45 total_wip: ? total_todo: ?
per-dim:
  execution      01  lit= 6 wip= 0 todo= 1 total= 7
  tool           02  lit= 5 wip= 0 todo= 3 total= 8
  context        03  lit= 6 wip= 0 todo=16 total=22
  lifecycle      04  lit= 7 wip= 0 todo= 3 total=10
  observability  05  lit= 4 wip= 0 todo= 5 total= 9
  verification   06  lit= 5 wip= 0 todo= 2 total= 7
  governance     07  lit= 3 wip= 0 todo= 3 total= 6
```

✓ 关键 gate：E 层 lit ≥ 6（spec § 6.1）

- [ ] **Step 2：path_router 命中率统计**

Run:
```bash
uv run python -c "
from pathlib import Path
from collections import Counter
from dashboard.derive.path_router import load_dimensions, classify_path
main, catch_all = load_dimensions(Path('dashboard/config/dimensions.yaml'))
counter = Counter()
total = 0
for p in Path('backend').rglob('*.py'):
    rel = str(p)
    cls = classify_path(rel, main, catch_all)
    counter[cls] += 1
    total += 1
print('total files:', total)
for k, v in counter.most_common():
    pct = 100 * v / total
    print(f'  {k:15s} {v:4d}  {pct:5.1f}%')
unknown_pct = 100 * counter['unknown'] / total
shell_pct = 100 * counter['shell'] / total
main_pct = 100 - unknown_pct - shell_pct
print(f'\\nmain hit: {main_pct:.1f}%, shell: {shell_pct:.1f}%, unknown: {unknown_pct:.1f}%')
"
```

Expected：main hit ≥ 80%（spec § 6.1 gate）

> 若 main hit < 80%：检查哪些 backend/app/ 子目录 path glob 没覆盖（可能 `backend/app/utils/` `backend/app/core/` 等），按需扩 dimensions.yaml 的 path 字段。

- [ ] **Step 3：启动 dashboard 服务（短跑 + 杀进程）**

Run:
```bash
uv run --extra dev python -m dashboard.server &
SERVER_PID=$!
sleep 3
curl -sf http://127.0.0.1:8001/api/overview/graph.json | python -c "
import json, sys
data = json.load(sys.stdin)
print('nodes:', len(data.get('nodes', [])))
print('edges:', len(data.get('edges', [])))
print('layer ids:', sorted(set(n.get('layer', '?') for n in data['nodes'])))
"
kill $SERVER_PID 2>/dev/null
```

Expected：
- 节点数 ≥ 65（69 capability，部分 todo 节点 confidence=0 但仍渲染）
- layer ids 包含 7 维（`['context', 'execution', 'governance', 'lifecycle', 'observability', 'tool', 'verification']`）
- HTTP 200，无 500

> 若端口冲突或环境有 milvus / OPENAI 需 unset，参考 `MEMORY.md` 启动注意：`unset all_proxy https_proxy http_proxy`

- [ ] **Step 4：commit 后 baseline 对照**

Diff `/tmp/etclovg_baseline.txt`（Task 1.4 记录）和 `/tmp/etclovg_plan1.txt`（Task 7.1）：
```bash
diff /tmp/etclovg_baseline.txt /tmp/etclovg_plan1.txt
```

Expected：
- 旧 baseline 8 layer：`prompt_context / tools_function / orchestration / memory / rag_knowledge / guardrails / eval_observability / cost_routing`
- 新 plan1 7 layer：`execution / tool / context / lifecycle / observability / verification / governance`
- total_lit 变化 ≤ ±5（迁移目标：基本保留旧 lit + E 层贡献 6 新 lit；预期 38 → ~42-44）

---

## Task 8：跑 pytest baseline（预期红 — 仅用于 Plan 2 入口）

**Files**：（无）

- [ ] **Step 1：跑 dashboard test suite 收集 fail 列表**

Run:
```bash
cd /Users/talantan/.openclaw/workspace-main/financial-research-assistant
uv run pytest dashboard/tests/ --tb=no -q 2>&1 | tail -60 | tee /tmp/etclovg_plan1_pytest.txt
```

Expected：
- 多个 fail（11 个测试文件含旧 dim id；具体 fail 数取决于 golden assertion 覆盖度）
- **fail 数 ≤ 20**（容忍上限；超过说明 derive 模块有未发现的 hard-code 残留，需回头检查）
- 关键失败应集中在：`test_path_router` / `test_app_shell_stat` / `test_capability_resolver` / `test_snapshot_builder` / `test_graph_builder` / `test_story_builder` / `test_main_endpoint` / `test_seed_deep_cards` / `test_flashcards_stats_endpoint` / `test_v2_modal_endpoint` / `test_decision_extractor`

- [ ] **Step 2：把 fail 列表写入 Plan 2 入口笔记**

Write: `/tmp/etclovg_plan2_pending.md`（不进 git，仅 Plan 2 起草参考）：
```bash
echo "# Plan 2 待修测试列表 (Plan 1 完工时的 baseline)" > /tmp/etclovg_plan2_pending.md
echo "" >> /tmp/etclovg_plan2_pending.md
echo "生成于: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /tmp/etclovg_plan2_pending.md
echo "" >> /tmp/etclovg_plan2_pending.md
cat /tmp/etclovg_plan1_pytest.txt >> /tmp/etclovg_plan2_pending.md
```

> 此文件仅 Plan 2 起草时参考，**不 commit**。

- [ ] **Step 3：不 commit**（无新文件改动）

---

## Task 9：Plan 1 self-review + 准备 Plan 2 起草

**Files**：（无）

- [ ] **Step 1：跑 self-review checklist**

| 项 | 验证 | 结果 |
|---|---|---|
| yaml 顶层 key `dimensions: + catch_all:` | `grep -E '^(dimensions|catch_all):' dashboard/config/dimensions.yaml` | □ |
| 7 个 dim id 全部为新名 | yaml load + assert ids | □ |
| 69 capability | yaml load + sum | □ |
| C 层 22 项全含 group | yaml load + counter | □ |
| E 层首版 7 项 + 含 celery_redis | yaml load + grep | □ |
| `DimensionId` Literal 9 项 | grep types.py | □ |
| path_router sentinel "shell" | grep | □ |
| mypy 全绿 | `uv run mypy dashboard` | □ |
| ruff 全绿 | `uv run ruff check dashboard && uv run ruff format --check dashboard` | □ |
| snapshot smoke | Task 7.1 | □ |
| path_router main hit ≥ 80% | Task 7.2 | □ |
| dashboard 服务启动 + /api/overview/graph.json 返 7 簇 | Task 7.3 | □ |
| pytest fail 数 ≤ 20 | Task 8.1 | □ |
| 无 `data["app_shell"]` 残留 in derive/ | grep | □ |
| commit 1 个（统一 commit） | git log | □ |

- [ ] **Step 2：(可选) 推 feature 分支到远程，但不 PR**

```bash
git push -u origin refactor/etclovg-migration
```

> Plan 1 不单独 PR — Plan 2 + Plan 3 完工后 3 plan 合一个 PR（`feat(harness-board): ETCLOVG 7 维迁移 + iOS Calm Minimal 视觉重做`）。

- [ ] **Step 3：起草 Plan 2 入口**

参考 `/tmp/etclovg_plan2_pending.md` 的 fail 列表 + spec § 5 Plan 2 范围 + spec § 4 capability id rename map，起草：
`docs/superpowers/plans/2026-05-20-etclovg-migration-plan2-data-migration.md`

Plan 2 范围预览：
1. 起一次性迁移脚本 `dashboard/scripts/migrate_to_etclovg.py`（dry-run 输出 diff → 用户确认 → in-place rewrite）
2. 跑脚本：35 张 seed.jsonl cap_id rename + 53 条 survey.jsonl dimension rewrite
3. 11 个测试文件 golden 同步
4. pytest 全绿
5. 删除迁移脚本（不长期保留）
6. commit + 准备 Plan 3

---

## 风险与回滚

### 风险

| 风险 | 缓解 |
|---|---|
| capabilities.yaml 写错某 derive_rule 路径 → 某 capability 误判 lit/todo | Task 7.1 snapshot 输出与预期对照（容许 ±1）；超出回头审 yaml |
| path_router 7 维 path glob 漏覆盖 backend/app/ 子目录 → main hit < 80% | Task 7.2 命中率统计 + 按需补 path 字段 |
| mypy 因 Literal 变更报新错（其他模块用旧 dim id 字符串） | Task 6.4 跑全 dashboard mypy；若有 type error 修复后再 commit |
| pytest fail 数失控（> 20） | Task 8.1 检查 fail 列表；若 derive 模块有未发现的 hard-code，回头扫 grep |
| `data["app_shell"]` 残留导致 KeyError | Task 6.3 grep 守门 |

### 回滚

Plan 1 在 `refactor/etclovg-migration` 分支单 commit；回滚：
```bash
git reset --hard HEAD~1  # 回到分支起点
# 或
git checkout spec/pg-only-migration  # 切回原分支
git branch -D refactor/etclovg-migration  # 删 feature 分支
```

无持久化数据变更（sqlite 无 dimension 列），无外部消费者，回滚 0 风险。

---

## Plan 1 估算

| 维度 | 估算 |
|---|---|
| Task 数 | 9 |
| 文件改动 | 7 个 |
| 行数 diff | ~600 行（含 capabilities.yaml 重写 ~400 行 + dimensions.yaml ~120 行 + derive 边角 ~80 行）|
| Wall time | 0.5-0.75 天（Claude Code 加速段） |
| 阻塞点 | 无 — 不动 jsonl / 不动模板 / 不动测试，纯结构改造 |

---

## 关联 spec / 上下游 plan

- Spec: `docs/superpowers/specs/2026-05-20-harness-board-etclovg-migration-design.md`
- Plan 2: `docs/superpowers/plans/2026-05-20-etclovg-migration-plan2-data-migration.md`（Plan 1 完工后起草）
- Plan 3: `docs/superpowers/plans/2026-05-20-etclovg-migration-plan3-ios-visual-and-templates.md`（Plan 2 完工后起草；含 mockup-v3.html）
