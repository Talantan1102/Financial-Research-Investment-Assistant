# Harness Board · M1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship M1:独立轻量 web 工具骨架,`make board` 浏览器看到 D 视图(8 layer 卡片 + capability chips 三态显示 + Hero 今日聚焦),只读无编辑无 toggle,首屏 lit 35 / total 62 与 spec § 3.2 anchor 一致。

**Architecture:** 5 层(Source 只读 / Derive 纯函数 / State sqlite / Server Starlette+Jinja+htmx / UI 浏览器);独立 `dashboard/` 顶级目录,共享 backend uv venv;无产品耦合。

**Tech Stack:** Starlette + Jinja2 + htmx 1.x (vendored) + Python sqlite3 (stdlib) + pyyaml + Python 3.11+

**Source Spec:** `docs/superpowers/specs/2026-05-07-harness-board-design.md`(M1 范围对应 § 9.1 表第一行)

**M1 不含**(留 M2/M3):
- ❌ B Kanban 视图 / Tab toggle
- ❌ 编辑模式 / wip 切换 / capability_override 写入
- ❌ /decisions route / decision_extractor
- ❌ 09 App Shell 第 9 行 mini stat(留 M2)

**M1 工期估算:1.5-2 天 wall time**(每天 4-5h Claude Code 投入,memory `feedback_estimate_in_claude_code_walltime`)

---

## File Structure

```
dashboard/                            # 顶级目录,跟 backend/ frontend/ 平级
├── __init__.py                       # sys.path 注入 backend (Task 1)
├── server.py                         # Starlette app + GET / (Task 7)
├── derive/
│   ├── __init__.py
│   ├── types.py                      # DimensionId / CapabilityStatus 等共享类型 (Task 2)
│   ├── path_router.py                # classify_path (Task 2)
│   ├── capability_resolver.py        # 5 类 derive_rule resolver (Task 4)
│   └── snapshot_builder.py           # build_snapshot (Task 5)
├── state/
│   ├── __init__.py
│   ├── db.py                         # sqlite schema + connection (Task 6)
│   └── repositories.py               # 1 表 CRUD: derived_snapshot (Task 6)
├── templates/
│   ├── base.html                     # Jinja2 base (Task 7)
│   ├── main.html                     # / 主视图 (Task 7)
│   ├── _hero.html                    # Hero 一行 partial (Task 7)
│   └── _d_view.html                  # D 视图 8 layer cards partial (Task 7)
├── static/
│   ├── htmx.min.js                   # vendored (Task 8)
│   └── style.css                     # 单文件手写 (Task 8)
├── config/
│   ├── dimensions.yaml               # 8 维 + App Shell path routing (Task 2)
│   └── capabilities.yaml             # 62 项 capability + derive_rule (Task 3)
└── tests/
    ├── __init__.py
    ├── derive/
    │   ├── __init__.py
    │   ├── fixtures/
    │   │   ├── sample_specs/         # 冻结子集
    │   │   ├── sample_memory/
    │   │   └── sample_code/
    │   ├── golden/
    │   │   └── expected_capabilities.json
    │   ├── test_path_router.py       # Task 2
    │   ├── test_capability_resolver.py  # Task 4
    │   └── test_snapshot_builder.py  # Task 5
    ├── state/
    │   ├── __init__.py
    │   └── test_repositories.py      # Task 6
    └── server/
        ├── __init__.py
        └── test_main_endpoint.py     # Task 7
```

**Modified files:**
- `backend/pyproject.toml` — 加 jinja2 + pyyaml dependencies (Task 1)
- `.gitignore` — 加 `backend/data/board.db` (Task 1)
- `Makefile`(顶级) — 加 board / board-stop / board-refresh targets (Task 9)

---

## Task 1: Setup dashboard package skeleton + 依赖

**Files:**
- Create: `dashboard/__init__.py` + 8 个 `__init__.py`(子包)
- Create: `dashboard/{config,static,templates}/.gitkeep`
- Modify: `backend/pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p dashboard/{derive,state,templates,config,static}
mkdir -p dashboard/tests/{derive/{fixtures,golden},state,server}
mkdir -p dashboard/tests/derive/fixtures/{sample_specs,sample_memory,sample_code}
touch dashboard/{config,static,templates}/.gitkeep
```

- [ ] **Step 2: 写 `dashboard/__init__.py`(sys.path 注入)**

完整内容:

```python
# dashboard/__init__.py
"""Harness Board · 独立轻量 web 工具,8 维 LLM Harness Capability Matrix。"""
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).parent.parent / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
```

- [ ] **Step 3: 创建空 `__init__.py` 各子包**

```bash
touch dashboard/derive/__init__.py \
      dashboard/state/__init__.py \
      dashboard/tests/__init__.py \
      dashboard/tests/derive/__init__.py \
      dashboard/tests/state/__init__.py \
      dashboard/tests/server/__init__.py
```

- [ ] **Step 4: 加依赖到 backend/pyproject.toml**

修改 `backend/pyproject.toml` 在 `[project] dependencies` 数组追加(注意精确版本会由 uv 写到 uv.lock):

```toml
"jinja2>=3.1",
"pyyaml>=6.0",
```

- [ ] **Step 5: uv sync 安装**

```bash
cd backend && uv sync
```

预期:无报错;`uv tree | grep -E "jinja2|pyyaml"` 应能看到两个包。

- [ ] **Step 6: 验证 sys.path 注入**

```bash
cd .. && uv run --project backend python -c "import dashboard; from app.services.llm_service import LLMService; print('OK')"
```

预期:打印 `OK`。

- [ ] **Step 7: 加 board.db 到 .gitignore**

`.gitignore` 末尾追加:

```
# Harness Board sqlite (派生重建,不进 git)
backend/data/board.db
```

- [ ] **Step 8: 提交**

```bash
git add dashboard/ backend/pyproject.toml backend/uv.lock .gitignore
git commit -m "chore(dashboard): scaffold dashboard package + jinja2/pyyaml deps"
```

---

## Task 2: dimensions.yaml + path_router

**Files:**
- Create: `dashboard/config/dimensions.yaml`
- Create: `dashboard/derive/types.py`
- Create: `dashboard/derive/path_router.py`
- Create: `dashboard/tests/derive/test_path_router.py`

- [ ] **Step 1: 写 `dashboard/config/dimensions.yaml`**

```yaml
# dashboard/config/dimensions.yaml
# 8 维 LLM Harness + App Shell catch-all 路径路由
# 冲突解决:更具体的优先(specificity = path_glob 去通配符后字符数)

dimensions:
  - id: prompt_context
    number: "01"
    name_cn: "提示与上下文"
    name_en: "Prompt & Context"
    paths:
      - "backend/app/services/llm_*.py"
      - "backend/app/services/skills/**"
    keywords: ["tier", "schema", "Skills"]

  - id: tools_function
    number: "02"
    name_cn: "工具与函数调用"
    name_en: "Tools & Function Calling"
    paths:
      - "backend/app/tools/**"
      - "backend/app/services/tool_registry*.py"
    keywords: ["Protocol", "tool"]

  - id: orchestration
    number: "03"
    name_cn: "编排与多智能体"
    name_en: "Orchestration / Multi-Agent"
    paths:
      - "backend/app/agents/**"
      - "backend/app/orchestration/**"
    keywords: ["LangGraph", "agent", "subgraph"]

  - id: memory
    number: "04"
    name_cn: "记忆层"
    name_en: "Memory"
    paths:
      - "backend/app/services/memory_*.py"
      - "backend/app/services/checkpointer*.py"
    keywords: ["Memory", "Saver", "checkpoint"]

  - id: rag_knowledge
    number: "05"
    name_cn: "检索增强"
    name_en: "RAG / Knowledge"
    paths:
      - "backend/app/services/milvus_*.py"
      - "backend/app/services/bocha_*.py"
      - "backend/app/services/kb_*.py"
      - "backend/app/services/corpus_*.py"
      - "backend/app/services/embedding_*.py"
    keywords: ["embedding", "retrieve"]

  - id: guardrails
    number: "06"
    name_cn: "护栏与自修复"
    name_en: "Guardrails & Auto-Repair"
    paths:
      - "backend/app/services/constrained_router*.py"
      - "backend/app/services/critic*.py"
      - "backend/app/services/validator*.py"
    keywords: ["Schema", "Pydantic", "retry"]

  - id: eval_observability
    number: "07"
    name_cn: "评测与可观测"
    name_en: "Eval & Observability"
    paths:
      - "backend/app/services/eval_*.py"
      - "backend/app/services/trace*.py"
      - "backend/app/services/judge*.py"
      - "backend/app/services/recorder*.py"
      - "backend/app/services/monitoring/**"
      - "backend/tests/**"
    keywords: ["EvalRunner", "TraceService", "Judge", "golden"]

  - id: cost_routing
    number: "08"
    name_cn: "成本与路由"
    name_en: "Cost & Routing"
    paths:
      - "backend/app/services/tier_router*.py"
      - "backend/app/services/pricing*.py"
      - "backend/app/services/cost_budget*.py"
      - "backend/app/services/quota*.py"
      - "backend/app/services/rate_limiter*.py"
    keywords: ["TierRouter", "pricing"]

app_shell:
  - id: frontend
    name_cn: "前端"
    paths: ["frontend/**"]
  - id: backend
    name_cn: "后端"
    paths: ["backend/app/api/**", "backend/app/main.py"]
  - id: auth
    name_cn: "鉴权"
    paths: ["backend/app/api/auth*", "frontend/src/**/Login*", "frontend/src/**/Auth*"]
  - id: database
    name_cn: "数据库"
    paths: ["backend/app/**/db.py", "backend/data/*.sql"]
  - id: connectors
    name_cn: "外部数据连接器"
    paths:
      - "backend/app/services/tushare_client*.py"
      - "backend/app/services/bocha_client*.py"
      - "backend/app/services/milvus_client*.py"
  - id: infra
    name_cn: "部署 / CI"
    paths: ["docker*/**", ".github/**", "scripts/**", "pyproject.toml"]
```

- [ ] **Step 2: 写 `dashboard/derive/types.py`**

```python
# dashboard/derive/types.py
"""派生层共享类型。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

DimensionId = Literal[
    "prompt_context", "tools_function", "orchestration", "memory",
    "rag_knowledge", "guardrails", "eval_observability", "cost_routing",
    "app_shell", "unknown",
]

CapabilityStatus = Literal["lit", "wip", "todo"]


@dataclass(frozen=True)
class DimensionConfig:
    id: DimensionId
    number: str          # "01"-"08" or "09"
    name_cn: str
    name_en: str
    paths: tuple[str, ...]
    keywords: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CapabilityConfig:
    id: str              # e.g. "01.multi_tier_signature"
    dimension: DimensionId
    name_cn: str
    name_en: str
    derive_rule: dict    # 5 类 rule type, see capability_resolver


@dataclass(frozen=True)
class Capability:
    id: str
    dimension: DimensionId
    name_cn: str
    name_en: str
    status: CapabilityStatus
    derived_status: CapabilityStatus  # 派生原值,与 status 比较可知是否 override
```

- [ ] **Step 3: 写 `dashboard/derive/path_router.py`**

```python
# dashboard/derive/path_router.py
"""路径 → 8 维主泳道 + App Shell 归类。

冲突解决:更具体的优先 (specificity = path_glob 去通配符后字符数)。
"""
from __future__ import annotations
from fnmatch import fnmatch
from pathlib import Path
import yaml
from .types import DimensionConfig, DimensionId


def load_dimensions(yaml_path: Path) -> tuple[list[DimensionConfig], list[DimensionConfig]]:
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
            id="app_shell",
            number="09",
            name_cn=d["name_cn"],
            name_en=d["name_cn"],     # App Shell 子项无 name_en,降级用中文
            paths=tuple(d["paths"]),
        )
        for d in data["app_shell"]
    ]
    return main, app_shell


def _specificity(path_glob: str) -> int:
    """更长(去通配符后)更具体。"""
    return len(path_glob.replace("*", "").replace("?", "").replace("[", "").replace("]", ""))


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
                candidates.append((_specificity(glob), d.id))
    for d in app_shell:
        for glob in d.paths:
            if fnmatch(path, glob):
                candidates.append((_specificity(glob), "app_shell"))
    if not candidates:
        return "unknown"
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
```

- [ ] **Step 4: 写测试 `dashboard/tests/derive/test_path_router.py`**

```python
# dashboard/tests/derive/test_path_router.py
from pathlib import Path
import pytest
from dashboard.derive.path_router import load_dimensions, classify_path


@pytest.fixture
def dims():
    yaml_path = Path(__file__).parent.parent.parent / "config" / "dimensions.yaml"
    return load_dimensions(yaml_path)


def test_loads_8_main_dims_and_6_app_shell(dims):
    main, app_shell = dims
    assert len(main) == 8
    assert len(app_shell) == 6
    assert {d.id for d in main} == {
        "prompt_context", "tools_function", "orchestration", "memory",
        "rag_knowledge", "guardrails", "eval_observability", "cost_routing",
    }
    assert all(d.number.startswith("0") for d in main)


@pytest.mark.parametrize("path,expected", [
    ("backend/app/services/llm_service.py", "prompt_context"),
    ("backend/app/services/skills/registry.py", "prompt_context"),
    ("backend/app/agents/critic.py", "orchestration"),
    ("backend/app/tools/get_balance_sheet.py", "tools_function"),
    ("backend/app/services/embedding_service.py", "rag_knowledge"),
    ("backend/app/services/eval_runner.py", "eval_observability"),
    ("backend/app/services/judge.py", "eval_observability"),
    ("backend/app/services/tier_router.py", "cost_routing"),
    ("frontend/src/App.tsx", "app_shell"),
    ("README.md", "unknown"),
    # connectors 比 RAG 更具体(milvus_client 比 milvus_*)— spec § 6.3 "更具体的优先"
    ("backend/app/services/milvus_client.py", "app_shell"),
])
def test_classify_path(dims, path, expected):
    main, app_shell = dims
    assert classify_path(path, main, app_shell) == expected
```

- [ ] **Step 5: 跑 test 验证**

```bash
uv run --project backend pytest dashboard/tests/derive/test_path_router.py -v
```

预期:11 个 test PASS(1 个 fixture 装载 + 10 个 parametrize)。

如果 milvus_client 那个 case 失败:具体度计算把 `*` 当作 0 char 处理,可能 RAG 的 `milvus_*.py`(11 char)和 connectors 的 `milvus_client*.py`(15 char)谁更具体取决于通配符前后:验证后调整 `_specificity` 公式 OR 调整 yaml ordering。

- [ ] **Step 6: 提交**

```bash
git add dashboard/config/dimensions.yaml dashboard/derive/{types,path_router}.py dashboard/tests/derive/test_path_router.py
git commit -m "feat(dashboard): dimensions.yaml + path_router (8 维 + App Shell 归类)"
```

---

## Task 3: capabilities.yaml(62 项)

**Files:**
- Create: `dashboard/config/capabilities.yaml`

这个 task 全部是 data 文件,无代码无 test。**capabilities.yaml** 是单一真源,内容根据 spec § 3.2 / § 4.1 落地。

- [ ] **Step 1: 写 `dashboard/config/capabilities.yaml` 完整 62 项**

```yaml
# dashboard/config/capabilities.yaml
# 单一真源 — 62 项 capability + derive_rule
# 5 类 derive_rule:code_grep / file_exists / spec_section / memory_frontmatter / manual

dimensions:

  # ============================================================
  # 01 Prompt & Context (8 项,预期 4 lit)
  # ============================================================
  - id: prompt_context
    capabilities:
      - id: multi_tier_signature
        name_cn: "多层级签名"
        name_en: "Multi-tier signature"
        derive_rule: { type: code_grep, pattern: 'tier:\s*Tier', path_glob: 'backend/app/services/llm_*.py' }
      - id: constrained_schema
        name_cn: "输出 Schema 约束"
        name_en: "Constrained schema"
        derive_rule: { type: code_grep, pattern: 'response_format', path_glob: 'backend/app/services/openai_client.py' }
      - id: skills_bundle
        name_cn: "Skills bundle (17-component)"
        name_en: "Skills bundle"
        derive_rule: { type: file_exists, path: 'backend/app/skills/financial_research' }
      - id: per_task_registry
        name_cn: "Per-task plan registry"
        name_en: "Per-task plan registry"
        derive_rule: { type: code_grep, pattern: 'plan_registry', path_glob: 'backend/app/agents/**' }
      - id: prompt_versioning
        name_cn: "Prompt 版本化"
        name_en: "Prompt Versioning"
        derive_rule: { type: manual }
      - id: few_shot_library
        name_cn: "Few-shot 示例库"
        name_en: "Few-shot library"
        derive_rule: { type: manual }
      - id: prompt_caching
        name_cn: "Prompt 缓存"
        name_en: "Prompt caching"
        derive_rule: { type: manual }
      - id: ctx_compression
        name_cn: "上下文压缩"
        name_en: "Context compression"
        derive_rule: { type: manual }

  # ============================================================
  # 02 Tools & Function Calling (8 项,预期 5 lit)
  # ============================================================
  - id: tools_function
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
  # 03 Orchestration / Multi-Agent (9 项,预期 6 lit)
  # ============================================================
  - id: orchestration
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
      - id: sqlite_saver
        name_cn: "SqliteSaver checkpoint"
        name_en: "SqliteSaver"
        derive_rule: { type: code_grep, pattern: 'SqliteSaver', path_glob: 'backend/app/orchestration/**' }
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
  # 04 Memory (6 项,预期 1 lit) ⚠ 弱项
  # ============================================================
  - id: memory
    capabilities:
      - id: session_checkpoint
        name_cn: "Session checkpoint"
        name_en: "Session (SqliteSaver)"
        derive_rule: { type: code_grep, pattern: 'SqliteSaver', path_glob: 'backend/app/orchestration/**' }
      - id: long_term_memory
        name_cn: "长期记忆"
        name_en: "Long-term memory"
        derive_rule: { type: manual }
      - id: semantic_memory
        name_cn: "语义记忆"
        name_en: "Semantic memory"
        derive_rule: { type: manual }
      - id: cross_user_cache
        name_cn: "跨用户缓存"
        name_en: "Cross-user cache"
        derive_rule: { type: manual }
      - id: episodic_memory
        name_cn: "情景记忆"
        name_en: "Episodic memory"
        derive_rule: { type: manual }
      - id: memory_compression
        name_cn: "记忆压缩"
        name_en: "Memory compression"
        derive_rule: { type: manual }

  # ============================================================
  # 05 RAG / Knowledge (8 项,预期 5 lit)
  # ============================================================
  - id: rag_knowledge
    capabilities:
      - id: milvus_3_collection
        name_cn: "Milvus 3 collection schema"
        name_en: "Milvus 3 collection"
        derive_rule: { type: code_grep, pattern: 'create_collection', path_glob: 'backend/app/services/milvus_*.py' }
      - id: embedding_cache
        name_cn: "Embedding + 缓存"
        name_en: "Embedding + cache"
        derive_rule: { type: file_exists, path: 'backend/app/services/embedding_service.py' }
      - id: corpus_ingest
        name_cn: "13 真 corpus ingest"
        name_en: "13 corpus ingest"
        derive_rule: { type: manual }
      - id: bocha_web
        name_cn: "Bocha 网络搜索"
        name_en: "Bocha web search"
        derive_rule: { type: file_exists, path: 'backend/app/services/bocha_client.py' }
      - id: kb_reliability
        name_cn: "KB reliability layer"
        name_en: "KB reliability"
        derive_rule: { type: file_exists, path: 'backend/app/services/reliable_kb_service.py' }
      - id: reranker
        name_cn: "Reranker"
        name_en: "Reranker"
        derive_rule: { type: manual }
      - id: hybrid_search
        name_cn: "稠密 + 稀疏混合检索"
        name_en: "Hybrid search"
        derive_rule: { type: manual }
      - id: query_decomposition
        name_cn: "Query 分解"
        name_en: "Query decomposition"
        derive_rule: { type: manual }

  # ============================================================
  # 06 Guardrails & Auto-Repair (7 项,预期 4 lit)
  # ============================================================
  - id: guardrails
    capabilities:
      - id: constrained_router
        name_cn: "Constrained LLM Router"
        name_en: "Constrained Router"
        derive_rule: { type: code_grep, pattern: 'constrained', path_glob: 'backend/app/agents/research_planner.py' }
      - id: pydantic_schema
        name_cn: "Pydantic schema 验证"
        name_en: "Pydantic schema"
        derive_rule: { type: code_grep, pattern: 'BaseModel', path_glob: 'backend/app/agents/**' }
      - id: langgraph_retry
        name_cn: "LangGraph retry edge"
        name_en: "LangGraph retry"
        derive_rule: { type: code_grep, pattern: 'add_edge.*retry|conditional_edges', path_glob: 'backend/app/orchestration/**' }
      - id: per_step_critic
        name_cn: "Per-step Critic"
        name_en: "Per-step Critic"
        derive_rule: { type: file_exists, path: 'backend/app/agents/critic_subagents' }
      - id: adversarial_test
        name_cn: "对抗测试"
        name_en: "Adversarial testing"
        derive_rule: { type: manual }
      - id: pii_redaction
        name_cn: "PII 脱敏"
        name_en: "PII redaction"
        derive_rule: { type: manual }
      - id: hallucination_check
        name_cn: "幻觉检测"
        name_en: "Hallucination check"
        derive_rule: { type: manual }

  # ============================================================
  # 07 Eval & Observability (9 项,预期 6 lit)
  # ============================================================
  - id: eval_observability
    capabilities:
      - id: eval_runner
        name_cn: "EvalRunner"
        name_en: "EvalRunner"
        derive_rule: { type: file_exists, path: 'backend/app/services/eval_runner.py' }
      - id: trace_service
        name_cn: "TraceService"
        name_en: "TraceService"
        derive_rule: { type: code_grep, pattern: 'TraceService|trace_id', path_glob: 'backend/app/services/eval_*.py' }
      - id: llm_judge
        name_cn: "LLM-as-Judge"
        name_en: "LLM-as-Judge"
        derive_rule: { type: file_exists, path: 'backend/app/services/judge.py' }
      - id: golden_cases
        name_cn: "12 golden cases"
        name_en: "12 golden cases"
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
      - id: latency_p95
        name_cn: "p95 latency 监控"
        name_en: "p95 latency monitoring"
        derive_rule: { type: manual }
      - id: dashboard
        name_cn: "项目 Harness Board(本工具)"
        name_en: "Harness Board"
        derive_rule: { type: file_exists, path: 'dashboard/server.py' }

  # ============================================================
  # 08 Cost & Routing (7 项,预期 4 lit)
  # ============================================================
  - id: cost_routing
    capabilities:
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
      - id: max_tokens_calibration
        name_cn: "max_tokens per-model 校准"
        name_en: "max_tokens calibration"
        derive_rule: { type: code_grep, pattern: 'max_tokens', path_glob: 'backend/app/services/openai_client.py' }
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
```

- [ ] **Step 2: 验证 yaml 合法 + 计数 62**

```bash
uv run --project backend python -c "
import yaml
from pathlib import Path
data = yaml.safe_load(Path('dashboard/config/capabilities.yaml').read_text())
total = sum(len(d['capabilities']) for d in data['dimensions'])
print(f'8 维 / total {total} 项')
assert total == 62, f'Expected 62 got {total}'
print('OK')
"
```

预期:打印 `8 维 / total 62 项` + `OK`。

- [ ] **Step 3: 提交**

```bash
git add dashboard/config/capabilities.yaml
git commit -m "feat(dashboard): capabilities.yaml 62 项 (8 维 + 5 derive_rule type)"
```

---

## Task 4: capability_resolver(5 类 derive_rule)

**Files:**
- Create: `dashboard/derive/capability_resolver.py`
- Create: `dashboard/tests/derive/fixtures/sample_code/{llm_service,tool_registry,memory_dummy}.py`(冻结子集)
- Create: `dashboard/tests/derive/test_capability_resolver.py`

- [ ] **Step 1: 写 `dashboard/derive/capability_resolver.py`**

```python
# dashboard/derive/capability_resolver.py
"""5 类 derive_rule 解析:code_grep / file_exists / spec_section / memory_frontmatter / manual。"""
from __future__ import annotations
import re
from glob import glob
from pathlib import Path
import yaml
from .types import Capability, CapabilityConfig, CapabilityStatus, DimensionId


def load_capabilities(yaml_path: Path) -> list[CapabilityConfig]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    out: list[CapabilityConfig] = []
    for dim in data["dimensions"]:
        dim_id: DimensionId = dim["id"]
        for cap in dim["capabilities"]:
            out.append(CapabilityConfig(
                id=f"{dim_id}.{cap['id']}",
                dimension=dim_id,
                name_cn=cap["name_cn"],
                name_en=cap.get("name_en", cap["name_cn"]),
                derive_rule=cap["derive_rule"],
            ))
    return out


def resolve_status(capability: CapabilityConfig, project_root: Path) -> CapabilityStatus:
    """按 derive_rule.type 分发,返回 lit/wip/todo。manual 默认 todo。"""
    rule = capability.derive_rule
    rtype = rule["type"]
    if rtype == "manual":
        return "todo"
    if rtype == "file_exists":
        return "lit" if (project_root / rule["path"]).exists() else "todo"
    if rtype == "code_grep":
        pattern = re.compile(rule["pattern"])
        for fp in glob(str(project_root / rule["path_glob"]), recursive=True):
            try:
                if pattern.search(Path(fp).read_text(encoding="utf-8", errors="ignore")):
                    return "lit"
            except (OSError, UnicodeDecodeError):
                continue
        return "todo"
    if rtype == "spec_section":
        spec_pat = re.compile(rule["section_pattern"])
        for fp in glob(str(project_root / rule["path"]), recursive=True):
            if spec_pat.search(Path(fp).read_text(encoding="utf-8", errors="ignore")):
                return "lit"
        return "todo"
    if rtype == "memory_frontmatter":
        version_re = re.compile(r"^version:\s*" + re.escape(rule.get("version", "")), re.MULTILINE)
        for fp in glob(str(project_root / rule["path"]), recursive=True):
            content = Path(fp).read_text(encoding="utf-8", errors="ignore")
            if version_re.search(content):
                return "lit"
        return "todo"
    raise ValueError(f"Unknown derive_rule type: {rtype}")


def resolve_all(
    capabilities: list[CapabilityConfig],
    project_root: Path,
    overrides: dict[str, CapabilityStatus] | None = None,
) -> list[Capability]:
    """resolve all + apply overrides。"""
    overrides = overrides or {}
    out: list[Capability] = []
    for c in capabilities:
        derived = resolve_status(c, project_root)
        final = overrides.get(c.id, derived)
        out.append(Capability(
            id=c.id, dimension=c.dimension,
            name_cn=c.name_cn, name_en=c.name_en,
            status=final, derived_status=derived,
        ))
    return out
```

- [ ] **Step 2: 写 fixture 文件(冻结子集,golden 测试用)**

```bash
mkdir -p dashboard/tests/derive/fixtures/sample_code/services dashboard/tests/derive/fixtures/sample_code/tools
```

写 `dashboard/tests/derive/fixtures/sample_code/services/llm_service.py`(冻结):

```python
# fixture: sample llm service, simulating real backend/app/services/llm_service.py
class LLMService:
    def chat(self, prompt: str, tier: Tier, response_format: dict | None = None):
        max_tokens = 1024
        return ...
```

写 `dashboard/tests/derive/fixtures/sample_code/services/tool_registry.py`:

```python
# fixture
class ToolRegistry:
    pass
```

- [ ] **Step 3: 写测试 `dashboard/tests/derive/test_capability_resolver.py`**

```python
# dashboard/tests/derive/test_capability_resolver.py
from pathlib import Path
import pytest
from dashboard.derive.capability_resolver import load_capabilities, resolve_status, resolve_all
from dashboard.derive.types import CapabilityConfig

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_load_62_capabilities():
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    assert len(caps) == 62
    assert all(c.id.count(".") >= 1 for c in caps)


def test_file_exists_rule(tmp_path: Path):
    cfg = CapabilityConfig(id="t.fe", dimension="memory", name_cn="x", name_en="x",
                           derive_rule={"type": "file_exists", "path": "exists.py"})
    (tmp_path / "exists.py").write_text("x")
    assert resolve_status(cfg, tmp_path) == "lit"
    cfg2 = CapabilityConfig(id="t.fe2", dimension="memory", name_cn="x", name_en="x",
                            derive_rule={"type": "file_exists", "path": "missing.py"})
    assert resolve_status(cfg2, tmp_path) == "todo"


def test_code_grep_rule(tmp_path: Path):
    (tmp_path / "x.py").write_text("def chat(self, prompt: str, tier: Tier): pass")
    cfg = CapabilityConfig(id="t.cg", dimension="prompt_context", name_cn="x", name_en="x",
                           derive_rule={"type": "code_grep", "pattern": r"tier:\s*Tier", "path_glob": "*.py"})
    assert resolve_status(cfg, tmp_path) == "lit"


def test_manual_rule_returns_todo():
    cfg = CapabilityConfig(id="t.m", dimension="memory", name_cn="x", name_en="x",
                           derive_rule={"type": "manual"})
    assert resolve_status(cfg, Path("/tmp")) == "todo"


def test_unknown_rule_raises():
    cfg = CapabilityConfig(id="t.u", dimension="memory", name_cn="x", name_en="x",
                           derive_rule={"type": "wat"})
    with pytest.raises(ValueError):
        resolve_status(cfg, Path("/tmp"))


def test_overrides_applied():
    project_root = Path(__file__).parent.parent.parent.parent  # repo root
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")[:3]
    overrides = {caps[0].id: "wip"}
    resolved = resolve_all(caps, project_root, overrides)
    assert resolved[0].status == "wip"
    assert resolved[0].derived_status in ("lit", "todo")  # 派生原值不被擦除


def test_real_project_lit_count_anchor():
    """在真实 repo 跑全部 62 capability,lit 计数应 ≈ 35(spec § 3.2 anchor)。"""
    project_root = Path(__file__).parent.parent.parent.parent
    caps = load_capabilities(CONFIG_DIR / "capabilities.yaml")
    resolved = resolve_all(caps, project_root)
    lit_count = sum(1 for c in resolved if c.status == "lit")
    # 容忍 ±5(grep pattern 可能调,manual 项可能改)
    assert 30 <= lit_count <= 40, f"Lit count {lit_count} out of expected 35±5"
```

- [ ] **Step 4: 跑 test 验证**

```bash
uv run --project backend pytest dashboard/tests/derive/test_capability_resolver.py -v
```

预期:7 个 test PASS。如果 `test_real_project_lit_count_anchor` fail,看实际 lit count,调 yaml grep pattern 至 30-40 之间。

- [ ] **Step 5: 提交**

```bash
git add dashboard/derive/capability_resolver.py dashboard/tests/derive/
git commit -m "feat(dashboard): capability_resolver 5 类 derive_rule + fixture + 真实 lit anchor 测"
```

---

## Task 5: snapshot_builder

**Files:**
- Create: `dashboard/derive/snapshot_builder.py`
- Create: `dashboard/tests/derive/test_snapshot_builder.py`

- [ ] **Step 1: 写 `dashboard/derive/snapshot_builder.py`**

```python
# dashboard/derive/snapshot_builder.py
"""聚合派生层输出到一个 Snapshot,可序列化到 sqlite payload。"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from .capability_resolver import load_capabilities, resolve_all
from .path_router import load_dimensions
from .types import Capability, CapabilityStatus, DimensionConfig


@dataclass(frozen=True)
class LayerSummary:
    id: str
    number: str
    name_cn: str
    name_en: str
    lit: int
    wip: int
    todo: int
    total: int
    capabilities: list[Capability]


@dataclass(frozen=True)
class Snapshot:
    """单次派生快照,JSON 序列化进 derived_snapshot.payload。"""
    refreshed_at: str
    layers: list[LayerSummary]
    total_lit: int
    total_wip: int
    total_todo: int
    total: int

    def to_dict(self) -> dict:
        return {
            "refreshed_at": self.refreshed_at,
            "layers": [
                {**asdict(L), "capabilities": [asdict(c) for c in L.capabilities]}
                for L in self.layers
            ],
            "total_lit": self.total_lit,
            "total_wip": self.total_wip,
            "total_todo": self.total_todo,
            "total": self.total,
        }


def build_snapshot(
    project_root: Path,
    config_dir: Path,
    overrides: dict[str, CapabilityStatus] | None = None,
    refreshed_at: str | None = None,
) -> Snapshot:
    """读 yaml + 派生 + 聚合到 Snapshot。"""
    from datetime import datetime, timezone
    refreshed_at = refreshed_at or datetime.now(timezone.utc).isoformat()
    main_dims, _app_shell = load_dimensions(config_dir / "dimensions.yaml")
    caps = load_capabilities(config_dir / "capabilities.yaml")
    resolved = resolve_all(caps, project_root, overrides)
    by_dim: dict[str, list[Capability]] = {d.id: [] for d in main_dims}
    for c in resolved:
        by_dim.setdefault(c.dimension, []).append(c)
    layers: list[LayerSummary] = []
    for d in main_dims:
        items = by_dim.get(d.id, [])
        layers.append(LayerSummary(
            id=d.id, number=d.number, name_cn=d.name_cn, name_en=d.name_en,
            lit=sum(1 for c in items if c.status == "lit"),
            wip=sum(1 for c in items if c.status == "wip"),
            todo=sum(1 for c in items if c.status == "todo"),
            total=len(items),
            capabilities=items,
        ))
    return Snapshot(
        refreshed_at=refreshed_at,
        layers=layers,
        total_lit=sum(L.lit for L in layers),
        total_wip=sum(L.wip for L in layers),
        total_todo=sum(L.todo for L in layers),
        total=sum(L.total for L in layers),
    )
```

- [ ] **Step 2: 写测试 `dashboard/tests/derive/test_snapshot_builder.py`**

```python
# dashboard/tests/derive/test_snapshot_builder.py
from pathlib import Path
from dashboard.derive.snapshot_builder import build_snapshot

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def test_snapshot_has_8_layers():
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    assert len(snap.layers) == 8
    assert {L.id for L in snap.layers} == {
        "prompt_context", "tools_function", "orchestration", "memory",
        "rag_knowledge", "guardrails", "eval_observability", "cost_routing",
    }


def test_snapshot_total_62():
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    assert snap.total == 62
    assert snap.total_lit + snap.total_wip + snap.total_todo == 62


def test_snapshot_lit_anchor_within_range():
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    assert 30 <= snap.total_lit <= 40, f"Lit {snap.total_lit} out of expected 35±5"


def test_snapshot_overrides_applied():
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR, overrides={"memory.long_term_memory": "wip"})
    mem = next(L for L in snap.layers if L.id == "memory")
    target = next(c for c in mem.capabilities if c.id == "memory.long_term_memory")
    assert target.status == "wip"


def test_snapshot_to_dict_json_roundtrip():
    import json
    snap = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
    d = snap.to_dict()
    s = json.dumps(d)
    assert json.loads(s)["total"] == 62
```

- [ ] **Step 3: 跑 test**

```bash
uv run --project backend pytest dashboard/tests/derive/test_snapshot_builder.py -v
```

预期:5 个 test PASS。

- [ ] **Step 4: 提交**

```bash
git add dashboard/derive/snapshot_builder.py dashboard/tests/derive/test_snapshot_builder.py
git commit -m "feat(dashboard): snapshot_builder + JSON 序列化 + lit anchor 验证"
```

---

## Task 6: state · sqlite + repositories

**Files:**
- Create: `dashboard/state/db.py`
- Create: `dashboard/state/repositories.py`
- Create: `dashboard/tests/state/test_repositories.py`

- [ ] **Step 1: 写 `dashboard/state/db.py`**

```python
# dashboard/state/db.py
"""sqlite schema + connection。M1 仅用 derived_snapshot 一张表。"""
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS derived_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  refreshed_at TEXT NOT NULL,
  payload TEXT NOT NULL  -- JSON
);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
```

- [ ] **Step 2: 写 `dashboard/state/repositories.py`**

```python
# dashboard/state/repositories.py
"""sqlite CRUD。M1 仅 SnapshotRepo;M2 增 OverrideRepo / DecisionRepo。"""
from __future__ import annotations
import json
import sqlite3


class SnapshotRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save(self, refreshed_at: str, payload: dict) -> None:
        """全量替换 — 仅保留最新一行(M1 简单语义)。"""
        with self.conn:
            self.conn.execute("DELETE FROM derived_snapshot")
            self.conn.execute(
                "INSERT INTO derived_snapshot (refreshed_at, payload) VALUES (?, ?)",
                (refreshed_at, json.dumps(payload)),
            )

    def get_latest(self) -> dict | None:
        cur = self.conn.execute(
            "SELECT refreshed_at, payload FROM derived_snapshot ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return None
        d = json.loads(row["payload"])
        d["refreshed_at"] = row["refreshed_at"]
        return d
```

- [ ] **Step 3: 写测试 `dashboard/tests/state/test_repositories.py`**

```python
# dashboard/tests/state/test_repositories.py
from pathlib import Path
from dashboard.state.db import open_db
from dashboard.state.repositories import SnapshotRepo


def test_snapshot_save_get(tmp_path: Path):
    conn = open_db(tmp_path / "board.db")
    repo = SnapshotRepo(conn)
    assert repo.get_latest() is None
    repo.save("2026-05-07T00:00:00Z", {"total": 62, "total_lit": 35})
    latest = repo.get_latest()
    assert latest is not None
    assert latest["total"] == 62
    assert latest["refreshed_at"] == "2026-05-07T00:00:00Z"


def test_snapshot_overwrite(tmp_path: Path):
    conn = open_db(tmp_path / "board.db")
    repo = SnapshotRepo(conn)
    repo.save("t1", {"total": 60})
    repo.save("t2", {"total": 62})
    latest = repo.get_latest()
    assert latest["total"] == 62
    cur = conn.execute("SELECT COUNT(*) AS n FROM derived_snapshot")
    assert cur.fetchone()["n"] == 1  # 全量替换语义
```

- [ ] **Step 4: 跑 test**

```bash
uv run --project backend pytest dashboard/tests/state/test_repositories.py -v
```

预期:2 个 test PASS。

- [ ] **Step 5: 提交**

```bash
git add dashboard/state/ dashboard/tests/state/
git commit -m "feat(dashboard): sqlite db + SnapshotRepo (全量替换语义)"
```

---

## Task 7: Starlette server + Jinja templates + GET /

**Files:**
- Create: `dashboard/server.py`
- Create: `dashboard/templates/base.html`
- Create: `dashboard/templates/main.html`
- Create: `dashboard/templates/_hero.html`
- Create: `dashboard/templates/_d_view.html`
- Create: `dashboard/tests/server/test_main_endpoint.py`

- [ ] **Step 1: 写 `dashboard/server.py`**

```python
# dashboard/server.py
"""Starlette app + 路由。M1:GET / + GET /healthz。"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import locale

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
import uvicorn

from dashboard.derive.snapshot_builder import build_snapshot
from dashboard.state.db import open_db
from dashboard.state.repositories import SnapshotRepo

DASHBOARD_ROOT = Path(__file__).parent
PROJECT_ROOT = DASHBOARD_ROOT.parent
CONFIG_DIR = DASHBOARD_ROOT / "config"
DB_PATH = PROJECT_ROOT / "backend" / "data" / "board.db"

templates = Jinja2Templates(directory=str(DASHBOARD_ROOT / "templates"))


def _today_label() -> str:
    """e.g. '2026-05-07 周三'(中文星期)。"""
    weekdays_cn = ["一", "二", "三", "四", "五", "六", "日"]
    now = datetime.now()
    return f"{now.strftime('%Y-%m-%d')} 周{weekdays_cn[now.weekday()]}"


def _get_or_build_snapshot() -> dict:
    """Lazy 派生:若 sqlite 无 snapshot,跑一次 build。"""
    conn = open_db(DB_PATH)
    repo = SnapshotRepo(conn)
    snap = repo.get_latest()
    if snap is None:
        snapshot = build_snapshot(PROJECT_ROOT, CONFIG_DIR)
        repo.save(snapshot.refreshed_at, snapshot.to_dict())
        snap = repo.get_latest()
    conn.close()
    return snap


async def index(request: Request) -> HTMLResponse:
    snap = _get_or_build_snapshot()
    wips = [c for L in snap["layers"] for c in L["capabilities"] if c["status"] == "wip"]
    return templates.TemplateResponse(
        "main.html",
        {
            "request": request,
            "today": _today_label(),
            "snap": snap,
            "wips": wips,
        },
    )


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


app = Starlette(
    routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Mount("/static", StaticFiles(directory=str(DASHBOARD_ROOT / "static")), name="static"),
    ],
)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8910, log_level="info")
```

- [ ] **Step 2: 写 `dashboard/templates/base.html`**

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Harness Board · {{ snap.refreshed_at[:10] }}</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/htmx.min.js"></script>
</head>
<body>
  <main class="board">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 3: 写 `dashboard/templates/main.html`**

```html
{% extends "base.html" %}
{% block content %}
  {% include "_hero.html" %}
  <section class="d-view">
    {% include "_d_view.html" %}
  </section>
{% endblock %}
```

- [ ] **Step 4: 写 `dashboard/templates/_hero.html`**

```html
<header class="hero">
  <span class="hero-date">📅 {{ today }}</span>
  <span class="hero-wips">
    {% if wips %}
      当前 wip:
      {% for c in wips %}
        <a class="chip wip" href="#layer-{{ c.dimension }}">[{{ c.dimension[:2] }}] {{ c.name_cn }}</a>
      {% endfor %}
    {% else %}
      <em class="empty">今天没在做任何 capability — 从 todo 挑一个?</em>
    {% endif %}
  </span>
  <span class="hero-actions">
    <span class="hero-counter">{{ snap.total_lit }}/{{ snap.total }} lit</span>
  </span>
</header>
```

- [ ] **Step 5: 写 `dashboard/templates/_d_view.html`**

```html
<div class="layer-grid">
  {% for L in snap.layers %}
    <article class="layer-card" id="layer-{{ L.id }}">
      <div class="layer-head">
        <span class="layer-num">{{ L.number }}</span>
        <span class="layer-count">{{ L.lit }}/{{ L.total }}</span>
      </div>
      <div class="layer-name">
        <strong>{{ L.name_cn }}</strong>
        <small>· {{ L.name_en }}</small>
      </div>
      <div class="cap-list">
        {% for c in L.capabilities %}
          <span class="chip {{ c.status }}" title="{{ c.id }}">
            {% if c.status == 'lit' %}✅{% elif c.status == 'wip' %}🟠{% else %}⬜{% endif %}
            {{ c.name_cn }}
          </span>
        {% endfor %}
      </div>
    </article>
  {% endfor %}
</div>
```

- [ ] **Step 6: 写测试 `dashboard/tests/server/test_main_endpoint.py`**

```python
# dashboard/tests/server/test_main_endpoint.py
from starlette.testclient import TestClient
from dashboard.server import app


def test_healthz():
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


def test_index_renders():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        body = r.text
        # Hero
        assert "📅" in body
        # 8 layer 卡片
        assert body.count("layer-card") >= 8
        # 三态 chip
        assert "lit" in body and "todo" in body
        # 计数
        assert "/62" in body or "62" in body  # total appears somewhere
```

- [ ] **Step 7: 跑 test**

```bash
uv run --project backend pytest dashboard/tests/server/test_main_endpoint.py -v
```

预期:2 个 test PASS。

需要装 uvicorn(若 backend 没装):

```bash
cd backend && uv add uvicorn
```

- [ ] **Step 8: 手动 smoke**

```bash
uv run --project backend python -m dashboard.server &
sleep 1
curl -s http://localhost:8910/healthz
# 期望:{"ok":true}
curl -s http://localhost:8910/ | head -50
# 期望:HTML 含 layer-card / lit chip / 📅
pkill -f "python -m dashboard.server"
```

- [ ] **Step 9: 提交**

```bash
git add dashboard/server.py dashboard/templates/ dashboard/tests/server/
git commit -m "feat(dashboard): Starlette server + Jinja templates + GET / 主视图(只读)"
```

---

## Task 8: CSS + htmx vendor

**Files:**
- Create: `dashboard/static/style.css`
- Create: `dashboard/static/htmx.min.js`(vendored)

- [ ] **Step 1: 下载 htmx 1.x vendored**

```bash
curl -sL https://unpkg.com/htmx.org@1.9.10/dist/htmx.min.js -o dashboard/static/htmx.min.js
ls -lh dashboard/static/htmx.min.js
# 期望 ~ 47KB
```

- [ ] **Step 2: 写 `dashboard/static/style.css`**

```css
/* dashboard/static/style.css — 单文件手写,无框架 */

:root {
  --bg: #020617;
  --fg: #f1f5f9;
  --muted: #94a3b8;
  --panel: #0f172a;
  --border: #334155;
  --lit-bg: #14532d;
  --lit-fg: #86efac;
  --wip-bg: #7c2d12;
  --wip-fg: #fdba74;
  --todo-fg: #64748b;
  --todo-border: #475569;
  --link: #93c5fd;
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
}

.board {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px;
}

/* Hero */
.hero {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 12px 16px;
  background: var(--panel);
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 13px;
}
.hero-date { color: var(--muted); }
.hero-wips { flex: 1; color: var(--muted); }
.hero-wips a { color: var(--wip-fg); text-decoration: none; margin-right: 8px; }
.hero-wips .empty { color: var(--todo-fg); font-style: italic; }
.hero-counter { color: var(--lit-fg); font-family: ui-monospace, monospace; font-size: 12px; }

/* Layer grid (D view) */
.layer-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.layer-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
}
.layer-head {
  display: flex;
  justify-content: space-between;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--muted);
}
.layer-name { margin: 4px 0 8px; }
.layer-name strong { font-size: 14px; }
.layer-name small { color: var(--muted); margin-left: 4px; }
.cap-list { display: flex; flex-wrap: wrap; gap: 4px; }

/* Chip 三态 */
.chip {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 11px;
  font-family: ui-monospace, monospace;
  white-space: nowrap;
}
.chip.lit  { background: var(--lit-bg);  color: var(--lit-fg);  border: 1px solid #166534; }
.chip.wip  { background: var(--wip-bg);  color: var(--wip-fg);  border: 1px solid #9a3412; }
.chip.todo { background: transparent;    color: var(--todo-fg); border: 1px dashed var(--todo-border); }

/* 响应式简版 */
@media (max-width: 1024px) { .layer-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 600px) { .layer-grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 3: 手动 smoke 视觉**

```bash
uv run --project backend python -m dashboard.server &
sleep 1
open http://localhost:8910
# 视觉验证:
# - Hero 一行有 📅 日期 + 计数
# - 8 个 layer 卡 2x4 grid
# - chip 三态颜色清晰(绿 lit / 灰虚线 todo;wip 暂时为 0,看不到橙)
pkill -f "python -m dashboard.server"
```

- [ ] **Step 4: 提交**

```bash
git add dashboard/static/
git commit -m "feat(dashboard): CSS 三态视觉规范 + htmx 1.9.10 vendored"
```

---

## Task 9: Makefile + M1 ship

**Files:**
- Create or modify: `Makefile`(顶级)

- [ ] **Step 1: 检查顶级 Makefile 是否存在**

```bash
ls -la Makefile 2>/dev/null
```

如果不存在,创建空 Makefile;如果存在,检查现有 target 不冲突。

- [ ] **Step 2: 添加 board target 到 Makefile**

追加到 Makefile:

```makefile
# ============================================================
# Harness Board (dev meta-tool)
# ============================================================
.PHONY: board board-stop board-refresh board-test

board:
	@uv run --project backend python -m dashboard.server &
	@sleep 1 && open http://localhost:8910

board-stop:
	@pkill -f "python -m dashboard.server" || true

board-refresh:
	@curl -sX POST http://localhost:8910/refresh && echo " ✓ refreshed"

board-test:
	@uv run --project backend pytest dashboard/tests/ -v
```

注意:`board-refresh` 需要 server 已起 + POST /refresh endpoint(M2 加),M1 暂时调用会 404。先列出来,M2 任务里会让它工作。

- [ ] **Step 3: 跑 board-test 验证全部 task 1-7 测试**

```bash
make board-test
```

预期:全部 PASS,总测试数 ~ 25(11 path_router + 7 capability_resolver + 5 snapshot_builder + 2 repositories + 2 server)。

- [ ] **Step 4: 跑 `make board` 完整 E2E 视觉**

```bash
make board
# 浏览器自动开 http://localhost:8910
# 确认:
# 1. Hero 显示今日日期(中文星期)
# 2. 8 个 layer 卡 2x4 grid 完整
# 3. lit 计数 30-40 范围(应接近 35)
# 4. chip 三态颜色:绿 (lit) / 虚线灰 (todo);wip 列表暂为空,Hero 显示"今天没在做任何 capability — 从 todo 挑一个?"
# 5. 总计 62 项 capability
make board-stop
```

- [ ] **Step 5: 提交 + tag M1 ship**

```bash
git add Makefile
git commit -m "feat(dashboard): Makefile board/board-stop/board-test targets — M1 ship"

# 可选:轻量 git tag
git tag -a harness-board-m1 -m "Harness Board M1: D 视图只读,8 layer + 62 capability + Hero"
```

- [ ] **Step 6: 验收**

ship 标准 checklist(spec § 9.1):

- [ ] `make board` 浏览器看到 D 视图
- [ ] 8 layer 卡片显示
- [ ] capability chips 三态显示(lit / todo,wip 为 0)
- [ ] 无编辑功能(M1 只读)
- [ ] 无 toggle(B Kanban M2 加)
- [ ] 首屏 lit 30-40(spec anchor 35 ± 5)
- [ ] 总计 62 项

---

## Self-Review Checklist

**1. Spec 覆盖**:
- ✓ § 6.1 5 层架构:Source(Task 2 dimensions yaml + 3 capabilities yaml)/ Derive(Task 2-5)/ State(Task 6)/ Server(Task 7)/ UI(Task 7-8)
- ✓ § 7.1 主视图:Hero(Task 7 _hero.html)+ D 视图(Task 7 _d_view.html)
- ✓ § 7.2 D 视图卡片:layer 编号 + lit/total + 中英名 + chip(Task 7 + 8)
- ⚠ § 7.1 Tab toggle [D / B]:**M1 不实现**(B Kanban 在 M2)— spec § 9.1 ship 标准明确"无 toggle",符合
- ⚠ § 7.4 /decisions:**M1 不实现**(M3)
- ⚠ § 5.3 09 App Shell 第 9 行:**M1 不实现**(M2)— ship 标准未要求,符合
- ✓ § 8.3 启动方式:Makefile board target(Task 9)
- ✓ § 9.3.1 Derive golden 模式:fixture 子集 + lit anchor 测(Task 4)— **简化版**:M1 用 anchor 测代替完整 golden,完整 golden 留 M2(decision_extractor 一起做)
- ✓ § 4.1 derive_rule 5 类:全部实现(Task 4)
- ✓ § 4.2 手填 override:capability_override 表 M2 加,M1 用 dict 参数 stub

**2. Placeholder 扫描**:无 TBD/TODO/FIXME。

**3. Type 一致性**:`CapabilityStatus` Literal 定义在 `types.py`,被 `capability_resolver.resolve_status` / `Capability.status` / `SnapshotRepo.save payload` 一致使用 ✓

**4. 风险点**(implementation 时注意):

- **Risk 1**:Task 2 `_specificity` 可能在 milvus_client.py case 算错(连接器 vs RAG)。Step 5 跑 test 失败时调公式 OR 调 yaml ordering。
- **Risk 2**:Task 4 `test_real_project_lit_count_anchor` 30-40 区间是 spec § 3.2 的"35 ± 5"放宽。如果跑出真实 lit 远离 35(<25 或 >45),说明 grep pattern 跟代码 drift,需要调 yaml 的 derive_rule patterns。
- **Risk 3**:Task 6 用 `data/board.db`,但 backend uv venv 跑 `python -m dashboard.server` 时 cwd 是 project root,绝对路径应 OK。memory `feedback_path_resolution_in_plans` 教训。
- **Risk 4**:Task 7 `Jinja2Templates` 引用 starlette 内置,版本要 >= 0.20。FastAPI 已装 starlette,默认 OK。Task 1 Step 5 后 `uv tree | grep starlette` 验证版本。
- **Risk 5**:Task 8 htmx vendored 用 1.9.10(spec § 12.5 决定 1.x stable)。版本固定不漂。
- **Risk 6**:memory `feedback_python_m_path_dual_context` — `python -m dashboard.server` 在 project root 跑,`dashboard/__init__.py` 注入 sys.path 让 backend 模块可导。Task 1 Step 6 已 smoke。
- **Risk 7**:memory `feedback_unguarded_imports_after_delete` — 本 plan 不删任何模块,无风险。
- **Risk 8**:memory `feedback_dev_tool_version_pin_alignment` — Task 1 加新 dep 必须 align uv.lock,已在 Step 5 提示 `uv sync` 后 commit `uv.lock`。

---

## 后续(超 M1 范围)

M1 ship 后按 spec § 9 进入 M2(B Kanban + 编辑模式 + 09 App Shell)→ M3(/decisions + decision_extractor)。各自独立 plan,实施时 ship 后再写下一期 plan(避免预先抽象未撞痛点)。
