# Dev-Test-Loop C — Eval + Trace Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the **eval + trace infrastructure** — `TraceService` + SQLite spans table, `EvalResult` / `GoldenCase` schemas, `Judge` (LLM-as-judge with 4-dim rubric), `EvalRunner` skeleton, sanity-check + cross-judge validation. Eval pipeline runs end-to-end against a **bare `LLMService` SUT** (real v0 chat agent is deferred to a separate spec).

**Architecture:**
- **Two SQLite tables in one file** (`backend/data/eval.sqlite`): `spans` (TraceService) and `eval_results` (EvalRecorder). Joined by `request_id` per spec § 9. The file lives outside git (`.gitignore`) — schemas are code-defined, regenerated from scratch on each test.
- **`LLMService.chat` is extended to write a span when a `TraceService` is injected** (DI, default `None` keeps Plan B contract intact). Mode dispatch via `ChatClient` Protocol stays untouched.
- **SUT is `LLMService.chat` directly, no agent.** `tool_correctness` rubric dimension is N/A under v0 SUT and the Judge prompt explicitly handles "no tool calls in trace → score = N/A, drop from aggregate". When v0 chat agent lands later, the SUT swap is a one-line `Callable` injection into `EvalRunner`.
- **Judge runs against `LLMService` `tier="balanced"`** (still v4-flash under v0 routing), parses a 4-key JSON, validates with Pydantic. Cost of one judge call is bounded by `max_completion_tokens=300`.
- **Sanity check is offline-deterministic with `MockLLMClient`** (5 obvious-correct + 5 obvious-wrong cases). Cross-judge Spearman is a manual-trigger script using two judge models against the same SUT outputs.

**Tech Stack:**
- Already in baseline: Python 3.11, `pydantic>=2.7`, `openai>=1.40`, `pytest`, `pytest-recording`, `mypy strict on app.services.*`, `poethepoet`, `pre-commit` (cassette sanitize hook from Plan B).
- New in Plan C: stdlib `sqlite3` only — **no SQLAlchemy / no scipy** (Spearman is hand-rolled, < 30 LOC).

**Status inherited from Plan B:**
- `LLMService(client, tier_router=None)` is stable; this plan adds an optional 3rd param.
- `MockLLMClient.from_fixture_dir(path)` works with fixtures under `backend/tests/fixtures/llm_mocks/`.
- L0/L1/L2 layer conftests force `LLM_MODE=none|mock|cassette`; `_unset_proxy_env` autouse is in `backend/tests/e2e/conftest.py`.
- Cassettes route to `backend/tests/fixtures/cassettes/` and pass `scripts/check_cassette_sanitize.py`.
- `app.services.*` is mypy strict (`disallow_untyped_defs = true`); all new files in this plan must comply.

**Memory inputs (Plan B sediment):**
- `feedback_third_party_plugin_defaults` — when introducing a third-party plugin (none in Plan C, but watch out)
- `feedback_test_env_modeling` — SQLite paths must be modeled into fixtures from the start; **no global mutable db**
- `project_llm_service_contract` — `LLMService.chat(prompt, tier, schema=None) -> LLMResponse`; mode dispatch via DI; `total_tokens == prompt_tokens + completion_tokens` invariant; deepseek-v4-flash is a **reasoning model** with hidden completion tokens (cost estimation must account)

---

## File Structure

| Path | Purpose | Created/Modified |
|---|---|---|
| `backend/app/services/trace_models.py` | `Span`, `TraceTree` Pydantic schemas | Create |
| `backend/app/services/trace_service.py` | SQLite-backed span store + query API | Create |
| `backend/app/services/llm_service.py` | **Modify**: add optional `trace_service: TraceService \| None = None` | Modify |
| `backend/app/services/eval_models.py` | `EvalResult`, `GoldenCase`, `JudgeScores` Pydantic | Create |
| `backend/app/services/eval_recorder.py` | SQLite-backed eval_results writer + reader | Create |
| `backend/app/services/judge.py` | `Judge` — prompt construction + JSON parse + LLMService call | Create |
| `backend/app/services/eval_runner.py` | `EvalRunner` orchestration: SUT → trace → judge → recorder | Create |
| `backend/tests/conftest.py` | **Modify**: add `tmp_eval_db` fixture (tmp_path-scoped sqlite) | Modify |
| `backend/tests/unit/test_trace_models.py` | L0: schema roundtrip + tree builder | Create |
| `backend/tests/unit/test_trace_service.py` | L0: write_span / get_trace / query_spans against tmp_path sqlite | Create |
| `backend/tests/unit/test_eval_recorder.py` | L0: write/read round-trip | Create |
| `backend/tests/unit/test_golden_case.py` | L0: GoldenCase JSONL parser | Create |
| `backend/tests/unit/test_judge.py` | L0: Judge prompt assembly + JSON parsing (with MockLLMClient) | Create |
| `backend/tests/unit/test_cross_judge.py` | L0: Spearman + sanity-pass-rate pure functions | Create |
| `backend/tests/integration/test_llm_service_trace.py` | L1: LLMService writes span when trace_service is injected | Create |
| `backend/tests/integration/test_eval_runner.py` | L1: 1 GoldenCase end-to-end with MockLLMClient SUT + MockLLMClient Judge | Create |
| `backend/tests/integration/test_sanity_check.py` | L1: 10 sanity cases with deterministic MockLLMClient — pass rate must be 100% | Create |
| `backend/tests/e2e/test_eval_pipeline_cassette.py` | L2: 1 GoldenCase real LLM SUT + real Judge, cassette replay | Create |
| `backend/tests/fixtures/eval/golden_set_v0.jsonl` | 3 real golden cases (starter set) | Create |
| `backend/tests/fixtures/eval/sanity_obvious_cases.jsonl` | 5 obvious-correct + 5 obvious-wrong | Create |
| `backend/tests/fixtures/llm_mocks/recorded/judge_4dim_response.json` | MockLLMClient judge response fixture | Create |
| `backend/tests/fixtures/cassettes/test_eval_pipeline_cassette/...yaml` | L2 cassette (auto-recorded by Task 10) | Create |
| `scripts/cross_judge_check.py` | Manual-trigger cross-judge Spearman script | Create |
| `pyproject.toml` | **Modify**: add `poe eval` / `poe eval-sanity` / `poe eval-cross-judge` + add mypy strict for `app.eval` if introduced (we're keeping it under `app.services.*`, so no change needed) | Modify |
| `.gitignore` | **Modify**: add `backend/data/` | Modify |

**Files NOT touched in Plan C (deferred):**
- `app.agents.*`, `app.orchestration.*` — v0 chat agent deferred to its own spec
- GH Actions cron / cost guardrail enforcement / cassette drift detection — Plan D
- `cost_cny=0.0` stub in `LLMResponse` — still stub; Plan D adds price table
- 50-70 case golden set full population — v1 spec, after v0 agent SUT lands

---

## Pre-flight check (Task 0 — done before dispatching Task 1)

> **Plan B retrospective sediment:** `deepseek-v4-flash` is a reasoning model on DashScope; completion tokens include hidden reasoning. Spec § 8 estimates ¥1-2 per eval run based on ~3K total tokens / case. **Verify this still holds for the judge prompt** (which is denser than a 1-word reply: includes user_input + expected_behavior + trace_summary + 4-dim rubric).

- [ ] **Probe one judge call cost.** Run:

```bash
unset all_proxy https_proxy http_proxy
uv run python - <<'PY'
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv("backend/.env")
client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url=os.environ.get("DASHSCOPE_BASE_URL"),
)
prompt = """你是金融研究助手的输出评审员。给定:
- 用户输入: 茅台股价多少?
- 期望行为: tool_calls=[get_stock_quote(ts_code=600519.SH)], response 含 600519 + 数字+元/股
- 实际响应: 贵州茅台(600519.SH)最新股价为 1820.50 元/股,涨幅 +1.2%。

按以下 4 维度各打 0-10 分,输出 JSON:
{
  "factuality": {"score": 0-10, "evidence": "1 句话"},
  "tool_correctness": {"score": 0-10, "evidence": "1 句话"},
  "coverage": {"score": 0-10, "evidence": "1 句话"},
  "structure": {"score": 0-10, "evidence": "1 句话"}
}
仅输出 JSON,无其他文字。"""

r = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=300,
)
print("CONTENT:", r.choices[0].message.content)
print("USAGE:", r.usage)
PY
```

Record under "Plan C retrospective — Task 0 spike result" (template at the end of this file):
- **prompt_tokens**, **completion_tokens** (with `reasoning_tokens` if surfaced), **total_tokens**
- **Estimated single-case cost in ¥** (use deepseek-v4-flash pricing: ¥0.0002 / 1K input, ¥0.0008 / 1K output as of 2026-04 — sync if changed). For 70 cases, multiply.
- **Action:** if estimate > ¥3 / 70 cases, sync spec § 8 ¥1-2 estimate; otherwise record-and-proceed.

This is a 5-minute spike. Failure or surprise here may reshape Tasks 7-10.

---

## Task 1: `Span` + `TraceTree` Pydantic schemas

**Files:**
- Create: `backend/app/services/trace_models.py`
- Create: `backend/tests/unit/test_trace_models.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_trace_models.py
"""L0 — Span / TraceTree schema invariants."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.services.trace_models import Span, TraceTree


def _now() -> datetime:
    return datetime(2026, 4, 30, 12, 0, 0)


def test_span_minimal() -> None:
    s = Span(
        span_id="s1",
        request_id="r1",
        parent_id=None,
        name="LLMService.chat",
        inputs={"prompt": "hi"},
        outputs={"content": "hello"},
        metadata={"tokens": 12},
        started_at=_now(),
        ended_at=_now() + timedelta(milliseconds=250),
        error=None,
    )
    assert s.latency_ms == 250
    assert s.parent_id is None


def test_span_end_before_start_rejected() -> None:
    with pytest.raises(ValidationError):
        Span(
            span_id="s1",
            request_id="r1",
            parent_id=None,
            name="x",
            inputs={},
            outputs={},
            metadata={},
            started_at=_now() + timedelta(seconds=1),
            ended_at=_now(),
            error=None,
        )


def test_tracetree_roundtrip() -> None:
    root = Span(
        span_id="root",
        request_id="r1",
        parent_id=None,
        name="ChatRequest",
        inputs={},
        outputs={},
        metadata={},
        started_at=_now(),
        ended_at=_now() + timedelta(milliseconds=400),
        error=None,
    )
    child = Span(
        span_id="c1",
        request_id="r1",
        parent_id="root",
        name="LLMService.chat",
        inputs={},
        outputs={},
        metadata={"prompt_tokens": 10, "completion_tokens": 5, "cost_cny": 0.0},
        started_at=_now() + timedelta(milliseconds=10),
        ended_at=_now() + timedelta(milliseconds=300),
        error=None,
    )
    tree = TraceTree.from_spans(spans=[root, child])
    assert tree.request_id == "r1"
    assert tree.root_span.span_id == "root"
    assert len(tree.root_span_children) == 1
    assert tree.total_latency_ms == 400


def test_tracetree_no_root_raises() -> None:
    orphan = Span(
        span_id="o1",
        request_id="r1",
        parent_id="missing",
        name="x",
        inputs={},
        outputs={},
        metadata={},
        started_at=_now(),
        ended_at=_now() + timedelta(milliseconds=10),
        error=None,
    )
    with pytest.raises(ValueError, match="no root span"):
        TraceTree.from_spans(spans=[orphan])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/unit/test_trace_models.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the schemas**

Create `backend/app/services/trace_models.py`:

```python
"""Span + TraceTree — the in-memory shape of one trace.

`Span` is the wire format and the SQLite row format (1:1). `TraceTree` is a
view-model built from a set of spans sharing a request_id. Both are stable
across v0~v3 per spec § 9 — adding fields is fine, renaming/removing breaks
all downstream consumers (eval reader, future trace exporter).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class Span(BaseModel):
    model_config = ConfigDict(frozen=True)

    span_id: str
    request_id: str
    parent_id: str | None
    name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    metadata: dict[str, Any]
    started_at: datetime
    ended_at: datetime
    error: str | None

    @model_validator(mode="after")
    def _check_times(self) -> "Span":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must be >= started_at")
        return self

    @property
    def latency_ms(self) -> int:
        return int((self.ended_at - self.started_at).total_seconds() * 1000)


class TraceTree(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    request_id: str
    root_span: Span
    root_span_children: list[Span]
    total_latency_ms: int
    total_cost_cny: float
    cache_hit_rate: float

    @classmethod
    def from_spans(cls, spans: list[Span]) -> "TraceTree":
        if not spans:
            raise ValueError("from_spans called with empty list")
        request_ids = {s.request_id for s in spans}
        if len(request_ids) != 1:
            raise ValueError(f"spans must share one request_id, got {request_ids}")
        request_id = next(iter(request_ids))
        roots = [s for s in spans if s.parent_id is None]
        if not roots:
            raise ValueError("no root span (all spans have a parent_id)")
        if len(roots) > 1:
            raise ValueError(f"multiple root spans: {[s.span_id for s in roots]}")
        root = roots[0]
        children = [s for s in spans if s.parent_id == root.span_id]
        cache_hits = [bool(s.metadata.get("cache_hit", False)) for s in spans]
        return cls(
            request_id=request_id,
            root_span=root,
            root_span_children=children,
            total_latency_ms=root.latency_ms,
            total_cost_cny=sum(float(s.metadata.get("cost_cny", 0.0)) for s in spans),
            cache_hit_rate=(sum(cache_hits) / len(cache_hits)) if cache_hits else 0.0,
        )
```

- [ ] **Step 4: Run tests + mypy**

```bash
uv run pytest backend/tests/unit/test_trace_models.py -v
uv run mypy backend/app/services/trace_models.py
```
Expected: 4 tests PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/trace_models.py backend/tests/unit/test_trace_models.py
git commit -m "$(cat <<'EOF'
feat(services): add Span + TraceTree Pydantic contracts

原因 layer: services
EOF
)"
```

---

## Task 2: `TraceService` — SQLite-backed span store

**Files:**
- Create: `backend/app/services/trace_service.py`
- Modify: `backend/tests/conftest.py` (add `tmp_eval_db` fixture)
- Modify: `.gitignore` (add `backend/data/`)
- Create: `backend/tests/unit/test_trace_service.py`

- [ ] **Step 1: Add the tmp-db fixture**

Append to `backend/tests/conftest.py`:

```python
@pytest.fixture
def tmp_eval_db(tmp_path) -> Path:  # type: ignore[no-untyped-def]
    """L0/L1 fixture — fresh SQLite file per test, auto-cleaned by tmp_path.

    SQLite path modeling: every test that touches TraceService / EvalRecorder
    must accept this fixture and pass it as db_path. Sharing a global db is
    forbidden — Plan B's feedback_test_env_modeling lesson.
    """
    return tmp_path / "eval.sqlite"
```

- [ ] **Step 2: .gitignore**

Append to `.gitignore` under "# Cache":

```
# Eval/trace local SQLite (regenerated from schema each run)
backend/data/
```

- [ ] **Step 3: Write the failing tests**

Create `backend/tests/unit/test_trace_service.py`:

```python
"""L0 — TraceService SQLite write/read round-trip."""

from datetime import datetime, timedelta
from pathlib import Path

from app.services.trace_models import Span, TraceTree
from app.services.trace_service import TraceService


def _span(span_id: str, request_id: str, parent_id: str | None = None) -> Span:
    now = datetime(2026, 4, 30, 12, 0, 0)
    return Span(
        span_id=span_id,
        request_id=request_id,
        parent_id=parent_id,
        name="LLMService.chat",
        inputs={"prompt": "hi"},
        outputs={"content": "ok"},
        metadata={"prompt_tokens": 5, "completion_tokens": 2, "cost_cny": 0.0},
        started_at=now,
        ended_at=now + timedelta(milliseconds=100),
        error=None,
    )


def test_write_then_get_trace(tmp_eval_db: Path) -> None:
    svc = TraceService(db_path=tmp_eval_db)
    svc.init_schema()

    root = _span("root", "r1")
    child = _span("c1", "r1", parent_id="root")
    svc.write_span(root)
    svc.write_span(child)

    tree = svc.get_trace("r1")
    assert isinstance(tree, TraceTree)
    assert tree.root_span.span_id == "root"
    assert len(tree.root_span_children) == 1


def test_get_trace_missing_request_raises(tmp_eval_db: Path) -> None:
    svc = TraceService(db_path=tmp_eval_db)
    svc.init_schema()
    import pytest
    with pytest.raises(LookupError, match="no spans for request_id"):
        svc.get_trace("nonexistent")


def test_query_spans_by_name(tmp_eval_db: Path) -> None:
    svc = TraceService(db_path=tmp_eval_db)
    svc.init_schema()

    svc.write_span(_span("a", "r1"))
    svc.write_span(_span("b", "r1", parent_id="a"))
    other = _span("c", "r2")
    svc.write_span(other)

    results = svc.query_spans({"request_id": "r1"})
    assert len(results) == 2
    assert {s.span_id for s in results} == {"a", "b"}


def test_init_schema_idempotent(tmp_eval_db: Path) -> None:
    """Calling init_schema twice must not fail or wipe data."""
    svc = TraceService(db_path=tmp_eval_db)
    svc.init_schema()
    svc.write_span(_span("a", "r1"))
    svc.init_schema()  # second call
    assert len(svc.query_spans({"request_id": "r1"})) == 1
```

- [ ] **Step 4: Verify tests fail**

Run: `uv run pytest backend/tests/unit/test_trace_service.py -v`
Expected: FAIL — `TraceService` not yet defined.

- [ ] **Step 5: Implement `TraceService`**

Create `backend/app/services/trace_service.py`:

```python
"""TraceService — SQLite-backed span persistence + query.

Schema lives in code (`init_schema`); the .sqlite file is .gitignored and
recreated per test (via tmp_eval_db fixture) or per app start.

Decoupled from EvalRecorder by sharing only the file path — they each own
their own table and can be instantiated independently.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.trace_models import Span, TraceTree


_SPANS_SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    span_id     TEXT PRIMARY KEY,
    request_id  TEXT NOT NULL,
    parent_id   TEXT,
    name        TEXT NOT NULL,
    inputs      TEXT NOT NULL,
    outputs     TEXT NOT NULL,
    metadata    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT NOT NULL,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_spans_request ON spans(request_id);
CREATE INDEX IF NOT EXISTS idx_spans_name    ON spans(name);
"""


class TraceService:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.executescript(_SPANS_SCHEMA)

    def write_span(self, span: Span) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO spans VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    span.span_id,
                    span.request_id,
                    span.parent_id,
                    span.name,
                    json.dumps(span.inputs, default=str),
                    json.dumps(span.outputs, default=str),
                    json.dumps(span.metadata, default=str),
                    span.started_at.isoformat(),
                    span.ended_at.isoformat(),
                    span.error,
                ),
            )

    def get_trace(self, request_id: str) -> TraceTree:
        spans = self.query_spans({"request_id": request_id})
        if not spans:
            raise LookupError(f"no spans for request_id={request_id!r}")
        return TraceTree.from_spans(spans)

    def query_spans(self, filters: dict[str, Any]) -> list[Span]:
        if not filters:
            sql = "SELECT * FROM spans"
            params: tuple[Any, ...] = ()
        else:
            clauses = " AND ".join(f"{k} = ?" for k in filters)
            sql = f"SELECT * FROM spans WHERE {clauses}"
            params = tuple(filters.values())
        with sqlite3.connect(self._db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_span(r) for r in rows]

    @staticmethod
    def _row_to_span(row: sqlite3.Row) -> Span:
        return Span(
            span_id=row["span_id"],
            request_id=row["request_id"],
            parent_id=row["parent_id"],
            name=row["name"],
            inputs=json.loads(row["inputs"]),
            outputs=json.loads(row["outputs"]),
            metadata=json.loads(row["metadata"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]),
            error=row["error"],
        )
```

- [ ] **Step 6: Verify tests + mypy**

```bash
uv run pytest backend/tests/unit/test_trace_service.py -v
uv run mypy backend/app/services/trace_service.py
```
Expected: 4 tests PASS, mypy clean.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/trace_service.py backend/tests/unit/test_trace_service.py backend/tests/conftest.py .gitignore
git commit -m "$(cat <<'EOF'
feat(services): add TraceService with SQLite span store

原因 layer: services
EOF
)"
```

---

## Task 3: `LLMService.chat` — write a span when `trace_service` injected

**Files:**
- Modify: `backend/app/services/llm_service.py`

(L1 integration test for the trace path lives in Task 4; this task is the contract change.)

- [ ] **Step 1: Read current `LLMService` and identify the change point**

Run: `uv run cat backend/app/services/llm_service.py` (or open in editor). Note that `chat` already wraps the client call with `time.perf_counter()` for `latency_ms`. The trace-write logic slots in around that timing block.

- [ ] **Step 2: Modify `LLMService` to accept and use `trace_service`**

Edit `backend/app/services/llm_service.py`:
- In `__init__`, add a third optional param `trace_service: TraceService | None = None` (after `tier_router`). Store on `self._trace`.
- In `chat`, after computing `LLMResponse`, **if `self._trace is not None`**, build a `Span` and call `self._trace.write_span(span)` before returning. The Span fields:
  - `span_id`: `f"{request_id}-llm-{counter}"` where `counter` is a per-instance monotonic int (initialized to 0 in `__init__`, incremented per call)
  - `request_id`: a new `request_id` generated by `chat` if caller didn't pass one. **Add a new param `request_id: str | None = None` to `chat`**, defaulting to `None`. If `None`, generate `f"req-{uuid4().hex[:12]}"`.
  - `parent_id`: pass-through from a new optional param `parent_span_id: str | None = None` on `chat`
  - `name`: `"LLMService.chat"`
  - `inputs`: `{"prompt": prompt, "tier": tier, "schema": schema}`
  - `outputs`: `{"content": response.content, "model": response.model}`
  - `metadata`: `{"prompt_tokens": ..., "completion_tokens": ..., "total_tokens": ..., "cost_cny": ..., "cache_hit": response.cache_hit, "tier": tier}`
  - `started_at`, `ended_at`: real timestamps captured before/after the client call
  - `error`: `None` (Plan C does not yet handle exceptions; future plan adds error path)
- **Also return the `request_id` to the caller** by adding it as a non-default `LLMResponse` field — **NO**, that would break the Plan B contract (`LLMResponse` is `frozen` and a stable v0~v3 contract). Instead, return a new tuple: **NO**, that breaks return type. Cleanest: change the return type to `LLMResponse` unchanged, but **expose `request_id` on `LLMResponse` as a new optional field** with default `None`. This is **additive** — Plan B contract holds: existing callers see no change.

  Add to `LLMResponse` (in `backend/app/services/llm_response.py`):
  ```python
  request_id: str | None = None
  ```

  Adding a field with a default is a non-breaking change per Pydantic semver. Verify Plan B's L0 test (`test_minimal_response_validates`) still passes — it does, because no field name overlaps.

- [ ] **Step 3: Run all existing tests to confirm Plan B contract is intact**

```bash
uv run pytest backend/tests/unit/ backend/tests/integration/ -v
uv run mypy backend/app/services/
```
Expected: all Plan B tests still PASS, mypy clean. If any existing test fails, the change is not additive — fix or revert.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/llm_service.py backend/app/services/llm_response.py
git commit -m "$(cat <<'EOF'
feat(services): LLMService writes a span when trace_service injected

原因 layer: services
EOF
)"
```

---

## Task 4: L1 integration test — trace auto-write

**Files:**
- Create: `backend/tests/integration/test_llm_service_trace.py`

- [ ] **Step 1: Write the L1 test**

```python
# backend/tests/integration/test_llm_service_trace.py
"""L1 — when LLMService is constructed with a TraceService, every chat
call writes one span; LLMResponse.request_id matches the span's request_id.
"""

from pathlib import Path

from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


def test_chat_writes_one_span_per_call(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    svc = LLMService(client=mock_llm_client, trace_service=trace)

    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")

    assert r.request_id is not None
    spans = trace.query_spans({"request_id": r.request_id})
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "LLMService.chat"
    assert span.metadata["tier"] == "fast"
    assert span.metadata["prompt_tokens"] == r.prompt_tokens


def test_chat_without_trace_service_writes_nothing(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    """Plan B contract: trace_service=None → zero side effects."""
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    svc = LLMService(client=mock_llm_client)  # no trace_service

    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")

    # request_id may be set or None — either is fine; what matters is no span written
    assert trace.query_spans({}) == []
    assert r.content  # call succeeded


def test_chat_with_explicit_request_id_uses_it(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    svc = LLMService(client=mock_llm_client, trace_service=trace)

    r1 = svc.chat(prompt="What is the price of 600519.SH?", tier="fast", request_id="req-foo")
    r2 = svc.chat(prompt="What is the price of 600519.SH?", tier="fast", request_id="req-foo")

    assert r1.request_id == "req-foo"
    spans = trace.query_spans({"request_id": "req-foo"})
    assert len(spans) == 2  # two child spans under same request_id
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest backend/tests/integration/test_llm_service_trace.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_llm_service_trace.py
git commit -m "$(cat <<'EOF'
test(integration): verify LLMService trace span auto-write

原因 layer: tests
EOF
)"
```

---

## Task 5: `EvalResult` schema + `EvalRecorder` (SQLite)

**Files:**
- Create: `backend/app/services/eval_models.py`
- Create: `backend/app/services/eval_recorder.py`
- Create: `backend/tests/unit/test_eval_recorder.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_eval_recorder.py
"""L0 — EvalRecorder write/read round-trip."""

from datetime import datetime
from pathlib import Path

from app.services.eval_models import EvalResult, JudgeScores
from app.services.eval_recorder import EvalRecorder


def _result(eval_id: str, request_id: str, case_id: str) -> EvalResult:
    return EvalResult(
        eval_id=eval_id,
        request_id=request_id,
        case_id=case_id,
        scores=JudgeScores(
            factuality=8, factuality_evidence="ok",
            tool_correctness=None, tool_correctness_evidence="N/A — no tool calls",
            coverage=7, coverage_evidence="ok",
            structure=9, structure_evidence="ok",
        ),
        judge_model="deepseek-v4-flash",
        judge_cost_cny=0.001,
        judge_latency_ms=420,
        timestamp=datetime(2026, 4, 30, 12, 0, 0),
    )


def test_write_then_read(tmp_eval_db: Path) -> None:
    rec = EvalRecorder(db_path=tmp_eval_db)
    rec.init_schema()
    r = _result("e1", "req-1", "v0-chat-001")
    rec.write(r)
    got = rec.read("e1")
    assert got == r


def test_query_by_case_id(tmp_eval_db: Path) -> None:
    rec = EvalRecorder(db_path=tmp_eval_db)
    rec.init_schema()
    rec.write(_result("e1", "req-1", "v0-chat-001"))
    rec.write(_result("e2", "req-2", "v0-chat-002"))
    results = rec.query({"case_id": "v0-chat-001"})
    assert len(results) == 1
    assert results[0].eval_id == "e1"


def test_init_schema_idempotent(tmp_eval_db: Path) -> None:
    rec = EvalRecorder(db_path=tmp_eval_db)
    rec.init_schema()
    rec.write(_result("e1", "req-1", "c1"))
    rec.init_schema()
    assert len(rec.query({})) == 1
```

- [ ] **Step 2: Verify it fails**

Run: `uv run pytest backend/tests/unit/test_eval_recorder.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement `eval_models.py`**

Create `backend/app/services/eval_models.py`:

```python
"""EvalResult + JudgeScores — Pydantic contracts for eval pipeline output.

`tool_correctness` may be None when the SUT doesn't expose tool calls (v0
SUT is bare LLMService). When None, the dimension is dropped from aggregate
scoring per spec § 8 (T3 threshold uses dim averages over present-only).

Stable v0~v3.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JudgeScores(BaseModel):
    model_config = ConfigDict(frozen=True)

    factuality: int = Field(ge=0, le=10)
    factuality_evidence: str
    tool_correctness: int | None = Field(default=None, ge=0, le=10)
    tool_correctness_evidence: str
    coverage: int = Field(ge=0, le=10)
    coverage_evidence: str
    structure: int = Field(ge=0, le=10)
    structure_evidence: str

    @property
    def aggregate_avg(self) -> float:
        """Average over present (non-None) dimensions."""
        present = [
            v
            for v in (self.factuality, self.tool_correctness, self.coverage, self.structure)
            if v is not None
        ]
        return sum(present) / len(present)


class EvalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    eval_id: str
    request_id: str
    case_id: str
    scores: JudgeScores
    judge_model: str
    judge_cost_cny: float = Field(ge=0.0)
    judge_latency_ms: int = Field(ge=0)
    timestamp: datetime
```

- [ ] **Step 4: Implement `eval_recorder.py`**

Create `backend/app/services/eval_recorder.py`:

```python
"""EvalRecorder — SQLite-backed eval_results writer.

Shares the file with TraceService (same .sqlite, different table) so a
single SQL JOIN on request_id retrieves "this case scored X, here's the
trace that produced it" per spec § 9.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.eval_models import EvalResult, JudgeScores


_EVAL_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_results (
    eval_id            TEXT PRIMARY KEY,
    request_id         TEXT NOT NULL,
    case_id            TEXT NOT NULL,
    scores_json        TEXT NOT NULL,
    judge_model        TEXT NOT NULL,
    judge_cost_cny     REAL NOT NULL,
    judge_latency_ms   INTEGER NOT NULL,
    timestamp          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_request ON eval_results(request_id);
CREATE INDEX IF NOT EXISTS idx_eval_case    ON eval_results(case_id);
"""


class EvalRecorder:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.executescript(_EVAL_RESULTS_SCHEMA)

    def write(self, result: EvalResult) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO eval_results VALUES (?,?,?,?,?,?,?,?)",
                (
                    result.eval_id,
                    result.request_id,
                    result.case_id,
                    result.scores.model_dump_json(),
                    result.judge_model,
                    result.judge_cost_cny,
                    result.judge_latency_ms,
                    result.timestamp.isoformat(),
                ),
            )

    def read(self, eval_id: str) -> EvalResult:
        with sqlite3.connect(self._db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM eval_results WHERE eval_id = ?", (eval_id,)
            ).fetchone()
        if row is None:
            raise LookupError(f"no eval_result with eval_id={eval_id!r}")
        return self._row_to_result(row)

    def query(self, filters: dict[str, Any]) -> list[EvalResult]:
        if not filters:
            sql = "SELECT * FROM eval_results"
            params: tuple[Any, ...] = ()
        else:
            clauses = " AND ".join(f"{k} = ?" for k in filters)
            sql = f"SELECT * FROM eval_results WHERE {clauses}"
            params = tuple(filters.values())
        with sqlite3.connect(self._db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_result(r) for r in rows]

    @staticmethod
    def _row_to_result(row: sqlite3.Row) -> EvalResult:
        return EvalResult(
            eval_id=row["eval_id"],
            request_id=row["request_id"],
            case_id=row["case_id"],
            scores=JudgeScores.model_validate_json(row["scores_json"]),
            judge_model=row["judge_model"],
            judge_cost_cny=row["judge_cost_cny"],
            judge_latency_ms=row["judge_latency_ms"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
```

- [ ] **Step 5: Verify**

```bash
uv run pytest backend/tests/unit/test_eval_recorder.py -v
uv run mypy backend/app/services/eval_models.py backend/app/services/eval_recorder.py
```
Expected: 3 tests PASS, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/eval_models.py backend/app/services/eval_recorder.py backend/tests/unit/test_eval_recorder.py
git commit -m "$(cat <<'EOF'
feat(services): add EvalResult + EvalRecorder (SQLite eval_results table)

原因 layer: services
EOF
)"
```

---

## Task 6: `GoldenCase` schema + 3 starter cases

**Files:**
- Modify: `backend/app/services/eval_models.py` (add `GoldenCase`)
- Create: `backend/tests/fixtures/eval/golden_set_v0.jsonl`
- Create: `backend/tests/unit/test_golden_case.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_golden_case.py
"""L0 — GoldenCase schema + JSONL loader."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.eval_models import GoldenCase, load_golden_jsonl


GOLDEN_PATH = Path("backend/tests/fixtures/eval/golden_set_v0.jsonl")


def test_load_starter_set() -> None:
    cases = load_golden_jsonl(GOLDEN_PATH)
    assert len(cases) >= 3
    for c in cases:
        assert c.case_id
        assert c.user_input
        assert c.expected_behavior is not None
        assert c.metadata.get("added_at")


def test_case_minimal() -> None:
    c = GoldenCase(
        case_id="x",
        category="single_tool_call",
        user_input="hi",
        expected_behavior={"response_must_contain": ["ok"]},
        metadata={"added_by": "init", "added_at": "2026-04-30", "tags": ["chat"]},
    )
    assert c.category == "single_tool_call"


def test_invalid_category_rejected() -> None:
    with pytest.raises(ValidationError):
        GoldenCase(
            case_id="x",
            category="invented_category",  # type: ignore[arg-type]
            user_input="hi",
            expected_behavior={},
            metadata={},
        )
```

- [ ] **Step 2: Verify it fails**

Run: `uv run pytest backend/tests/unit/test_golden_case.py -v`
Expected: FAIL — `GoldenCase` and `load_golden_jsonl` not defined.

- [ ] **Step 3: Add to `eval_models.py`**

Append to `backend/app/services/eval_models.py`:

```python
import json
from pathlib import Path
from typing import Any, Literal

GoldenCategory = Literal[
    "single_tool_call",
    "chat_multi_turn",
    "boundary_case",
]


class GoldenCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: GoldenCategory
    user_input: str
    expected_behavior: dict[str, Any]
    metadata: dict[str, Any]


def load_golden_jsonl(path: Path) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            cases.append(GoldenCase.model_validate_json(line))
    return cases
```

- [ ] **Step 4: Create the starter golden set**

Create `backend/tests/fixtures/eval/golden_set_v0.jsonl` with **3 cases** total (one per category). Each line is one JSON object. Use:

- **Case 1** (`single_tool_call`): user asks for a stock price by name (e.g. 茅台). `expected_behavior.response_must_contain` includes the ticker `"600519"` and a price-shaped substring (e.g. `"元"`).
- **Case 2** (`chat_multi_turn`): a 2-turn conversation about company fundamentals where the second turn references the first ("它的 PE 呢?" after asking for a quote). `expected_behavior.response_must_contain` includes `"PE"`.
- **Case 3** (`boundary_case`): ambiguous query like "茅台怎么样" (no tool call expected, the SUT should ask for clarification or describe coverage). `expected_behavior.response_must_contain` is empty; instead set `expected_behavior.note: "判定 coverage 维度 ≥ 6 即可"`.

Each case includes `metadata.added_by="plan-c-init"`, `metadata.added_at="2026-04-30"`, `metadata.tags=["v0", "chat"]`.

> **Why only 3**: enough to drive the test for the loader and the eval_runner end-to-end test, while honoring the "v0 starter set" scope (full 50-70 case population is v1 work after the chat agent SUT lands).

- [ ] **Step 5: Verify**

```bash
uv run pytest backend/tests/unit/test_golden_case.py -v
uv run mypy backend/app/services/eval_models.py
```
Expected: 3 tests PASS, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/eval_models.py backend/tests/fixtures/eval/golden_set_v0.jsonl backend/tests/unit/test_golden_case.py
git commit -m "$(cat <<'EOF'
feat(services): add GoldenCase + 3-case starter golden set

原因 layer: services
EOF
)"
```

---

## Task 7: `Judge` — LLM-as-judge with 4-dim rubric

**Files:**
- Create: `backend/app/services/judge.py`
- Create: `backend/tests/fixtures/llm_mocks/recorded/judge_4dim_response.json` (MockLLMClient fixture)
- Modify: `backend/tests/fixtures/llm_mocks/agent_decisions.yaml` (add a pattern entry that matches the judge prompt prefix)
- Create: `backend/tests/unit/test_judge.py`

- [ ] **Step 1: Add the recorded fixture**

Create `backend/tests/fixtures/llm_mocks/recorded/judge_4dim_response.json`:

A JSON object whose `response.content` is itself a JSON-encoded string with the 4-key shape:
```json
{"factuality": {"score": 8, "evidence": "..."},
 "tool_correctness": {"score": null, "evidence": "N/A"},
 "coverage": {"score": 7, "evidence": "..."},
 "structure": {"score": 9, "evidence": "..."}}
```
`response.prompt_tokens=350`, `response.completion_tokens=80`.

- [ ] **Step 2: Wire MockLLMClient to return that fixture for judge prompts**

Add an entry to `backend/tests/fixtures/llm_mocks/agent_decisions.yaml` whose **pattern** matches the judge prompt prefix (`"^你是金融研究助手的输出评审员"`) and whose response is a `__recorded__:judge_4dim_response` reference. (The `MockLLMClient` plan-B dispatch already supports the `__recorded__:` short-circuit; this entry just tells it which recorded fixture to use for any prompt starting with that prefix.)

> **Note**: pattern-based dispatch in MockLLMClient currently does string interpolation, not redirect to recorded. **Add a tiny extension** to `MockLLMClient` allowing a pattern entry's `response` to itself be a `__recorded__:<id>` literal — when seen, the dispatcher resolves it to the recorded fixture. Add an L0 unit test for this in `test_llm_mock_client.py`.

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/unit/test_judge.py
"""L0 — Judge prompt assembly + response parsing.

L1 SUT-Judge integration is in test_eval_runner.py; this test isolates the
prompt-construction and JSON-parsing units.
"""

from datetime import datetime
from pathlib import Path

from app.services.eval_models import GoldenCase, JudgeScores
from app.services.judge import Judge, build_judge_prompt
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


FIXTURES = Path("backend/tests/fixtures/llm_mocks")


def test_build_judge_prompt_includes_required_sections() -> None:
    case = GoldenCase(
        case_id="x",
        category="single_tool_call",
        user_input="茅台股价?",
        expected_behavior={"response_must_contain": ["600519", "元"]},
        metadata={"added_by": "test", "added_at": "2026-04-30", "tags": []},
    )
    prompt = build_judge_prompt(
        case=case,
        sut_response="茅台 600519.SH 股价 1820 元/股。",
        trace_summary="LLMService.chat called 1x, no tool calls",
    )
    assert "你是金融研究助手的输出评审员" in prompt
    assert "茅台股价?" in prompt
    assert "600519" in prompt
    assert "factuality" in prompt
    assert "tool_correctness" in prompt
    assert "coverage" in prompt
    assert "structure" in prompt


def test_judge_returns_parsed_scores(mock_llm_client: MockLLMClient) -> None:
    svc = LLMService(client=mock_llm_client)
    j = Judge(llm=svc, judge_tier="balanced")
    case = GoldenCase(
        case_id="x",
        category="single_tool_call",
        user_input="茅台股价?",
        expected_behavior={"response_must_contain": ["600519", "元"]},
        metadata={"added_by": "test", "added_at": "2026-04-30", "tags": []},
    )

    scores, judge_meta = j.score(
        case=case,
        sut_response="茅台 600519.SH 股价 1820 元/股。",
        trace_summary="LLMService.chat called 1x, no tool calls",
    )

    assert isinstance(scores, JudgeScores)
    assert 0 <= scores.factuality <= 10
    assert scores.tool_correctness is None  # null in fixture → None
    assert scores.coverage is not None
    assert judge_meta["model"]
    assert judge_meta["latency_ms"] >= 0
```

- [ ] **Step 4: Implement `Judge`**

Create `backend/app/services/judge.py`:

```python
"""Judge — LLM-as-judge with 4-dim rubric (spec § 8 R4).

Constructs a deterministic prompt from (GoldenCase, sut_response, trace_summary),
calls LLMService.chat, parses the JSON response into JudgeScores.

`tool_correctness` may be null in the response — interpreted as N/A and
recorded as None on JudgeScores. The aggregate average ignores N/A dims.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.eval_models import GoldenCase, JudgeScores
from app.services.llm_response import Tier
from app.services.llm_service import LLMService


_JUDGE_TEMPLATE = """\
你是金融研究助手的输出评审员。给定:
- 用户输入: {user_input}
- 期望行为: {expected_behavior}
- 实际 trace: {trace_summary}
- 实际响应: {sut_response}

按以下 4 维度各打 0-10 分,输出 JSON。如果某维度不适用(例如 trace 中无 tool_calls,
则 tool_correctness 不适用),将 score 设为 null,evidence 写 "N/A — <原因>"。

{{
  "factuality": {{"score": 0-10, "evidence": "1 句话"}},
  "tool_correctness": {{"score": 0-10 或 null, "evidence": "1 句话"}},
  "coverage": {{"score": 0-10, "evidence": "1 句话"}},
  "structure": {{"score": 0-10, "evidence": "1 句话"}}
}}

仅输出 JSON,无其他文字。
"""


def build_judge_prompt(
    case: GoldenCase,
    sut_response: str,
    trace_summary: str,
) -> str:
    return _JUDGE_TEMPLATE.format(
        user_input=case.user_input,
        expected_behavior=json.dumps(case.expected_behavior, ensure_ascii=False),
        trace_summary=trace_summary,
        sut_response=sut_response,
    )


class Judge:
    def __init__(self, llm: LLMService, judge_tier: Tier = "balanced") -> None:
        self._llm = llm
        self._tier = judge_tier

    def score(
        self,
        case: GoldenCase,
        sut_response: str,
        trace_summary: str,
    ) -> tuple[JudgeScores, dict[str, Any]]:
        prompt = build_judge_prompt(case, sut_response, trace_summary)
        r = self._llm.chat(prompt=prompt, tier=self._tier)
        raw = json.loads(r.content)
        scores = JudgeScores(
            factuality=raw["factuality"]["score"],
            factuality_evidence=raw["factuality"]["evidence"],
            tool_correctness=raw["tool_correctness"]["score"],
            tool_correctness_evidence=raw["tool_correctness"]["evidence"],
            coverage=raw["coverage"]["score"],
            coverage_evidence=raw["coverage"]["evidence"],
            structure=raw["structure"]["score"],
            structure_evidence=raw["structure"]["evidence"],
        )
        meta = {
            "model": r.model,
            "cost_cny": r.cost_cny,
            "latency_ms": r.latency_ms,
        }
        return scores, meta
```

- [ ] **Step 5: Verify**

```bash
uv run pytest backend/tests/unit/test_judge.py backend/tests/unit/test_llm_mock_client.py -v
uv run mypy backend/app/services/judge.py
```
Expected: tests PASS (including the new `__recorded__:` redirect test from step 2), mypy clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/judge.py backend/app/services/llm_mock_client.py backend/tests/fixtures/llm_mocks/ backend/tests/unit/test_judge.py backend/tests/unit/test_llm_mock_client.py
git commit -m "$(cat <<'EOF'
feat(services): add Judge with 4-dim rubric + MockLLMClient pattern→recorded redirect

原因 layer: services
EOF
)"
```

---

## Task 8: `EvalRunner` skeleton

**Files:**
- Create: `backend/app/services/eval_runner.py`
- Create: `backend/tests/integration/test_eval_runner.py`

- [ ] **Step 1: Write the L1 test**

```python
# backend/tests/integration/test_eval_runner.py
"""L1 — EvalRunner end-to-end against MockLLMClient SUT and MockLLMClient Judge.

One golden case → SUT → trace → Judge → EvalResult written. Verify each step.
"""

from pathlib import Path

from app.services.eval_models import GoldenCase
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner
from app.services.judge import Judge
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


def test_run_one_case_writes_eval_result(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    recorder = EvalRecorder(db_path=tmp_eval_db)
    recorder.init_schema()

    sut_llm = LLMService(client=mock_llm_client, trace_service=trace)
    judge_llm = LLMService(client=mock_llm_client)
    judge = Judge(llm=judge_llm, judge_tier="balanced")

    case = GoldenCase(
        case_id="x",
        category="single_tool_call",
        user_input="What is the price of 600519.SH?",
        expected_behavior={"response_must_contain": ["600519"]},
        metadata={"added_by": "test", "added_at": "2026-04-30", "tags": []},
    )

    runner = EvalRunner(
        sut=sut_llm,
        judge=judge,
        trace_service=trace,
        recorder=recorder,
    )
    eval_result = runner.run_one(case)

    assert eval_result.case_id == "x"
    assert eval_result.scores.factuality is not None
    stored = recorder.read(eval_result.eval_id)
    assert stored == eval_result
    spans = trace.query_spans({"request_id": eval_result.request_id})
    assert len(spans) >= 1


def test_run_many_cases(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    recorder = EvalRecorder(db_path=tmp_eval_db)
    recorder.init_schema()
    sut_llm = LLMService(client=mock_llm_client, trace_service=trace)
    judge = Judge(llm=LLMService(client=mock_llm_client), judge_tier="balanced")
    runner = EvalRunner(sut=sut_llm, judge=judge, trace_service=trace, recorder=recorder)

    cases = [
        GoldenCase(
            case_id=f"c{i}",
            category="single_tool_call",
            user_input="What is the price of 600519.SH?",
            expected_behavior={"response_must_contain": ["600519"]},
            metadata={"added_by": "test", "added_at": "2026-04-30", "tags": []},
        )
        for i in range(3)
    ]
    results = runner.run_many(cases)
    assert len(results) == 3
    assert len({r.eval_id for r in results}) == 3  # unique IDs
```

- [ ] **Step 2: Verify it fails**

Run: `uv run pytest backend/tests/integration/test_eval_runner.py -v`
Expected: FAIL — `EvalRunner` not defined.

- [ ] **Step 3: Implement `EvalRunner`**

Create `backend/app/services/eval_runner.py`:

```python
"""EvalRunner — orchestrates one or many GoldenCase runs.

For each case: SUT → fetch trace → Judge → write EvalResult. The SUT under
v0 is bare LLMService.chat (no agent); when the agent skeleton lands the
sut param accepts any object satisfying a tiny `SUT` protocol.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.services.eval_models import EvalResult, GoldenCase
from app.services.eval_recorder import EvalRecorder
from app.services.judge import Judge
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


class EvalRunner:
    def __init__(
        self,
        sut: LLMService,
        judge: Judge,
        trace_service: TraceService,
        recorder: EvalRecorder,
    ) -> None:
        self._sut = sut
        self._judge = judge
        self._trace = trace_service
        self._recorder = recorder

    def run_one(self, case: GoldenCase) -> EvalResult:
        request_id = f"eval-{case.case_id}-{uuid4().hex[:8]}"
        sut_response = self._sut.chat(
            prompt=case.user_input,
            tier="balanced",
            request_id=request_id,
        )
        trace = self._trace.get_trace(request_id)
        trace_summary = self._summarize_trace(trace)

        scores, judge_meta = self._judge.score(
            case=case,
            sut_response=sut_response.content,
            trace_summary=trace_summary,
        )

        result = EvalResult(
            eval_id=f"eval-{uuid4().hex[:12]}",
            request_id=request_id,
            case_id=case.case_id,
            scores=scores,
            judge_model=judge_meta["model"],
            judge_cost_cny=float(judge_meta["cost_cny"]),
            judge_latency_ms=int(judge_meta["latency_ms"]),
            timestamp=datetime.utcnow(),
        )
        self._recorder.write(result)
        return result

    def run_many(self, cases: list[GoldenCase]) -> list[EvalResult]:
        return [self.run_one(c) for c in cases]

    @staticmethod
    def _summarize_trace(trace: Any) -> str:
        # Keep lightweight: name list + total_latency.
        spans = [trace.root_span, *trace.root_span_children]
        names = ", ".join(s.name for s in spans)
        return f"spans=[{names}] total_latency_ms={trace.total_latency_ms}"
```

- [ ] **Step 4: Verify**

```bash
uv run pytest backend/tests/integration/test_eval_runner.py -v
uv run mypy backend/app/services/eval_runner.py
```
Expected: 2 tests PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/eval_runner.py backend/tests/integration/test_eval_runner.py
git commit -m "$(cat <<'EOF'
feat(services): add EvalRunner orchestrator (SUT→trace→Judge→Recorder)

原因 layer: services
EOF
)"
```

---

## Task 9: Sanity check fixture + verification

**Files:**
- Create: `backend/tests/fixtures/eval/sanity_obvious_cases.jsonl` (5 obvious-correct + 5 obvious-wrong)
- Modify: `backend/app/services/eval_runner.py` (add `compute_sanity_pass_rate`)
- Create: `backend/tests/integration/test_sanity_check.py`

- [ ] **Step 1: Build the sanity fixture**

Create `backend/tests/fixtures/eval/sanity_obvious_cases.jsonl`. **10 lines total**, each a `GoldenCase` JSON with one extra metadata field `sanity_label` ∈ `{"obvious_correct", "obvious_wrong"}`:

- 5 obvious-correct: SUT will give a clearly-aligned response → judge MUST score `factuality + coverage + structure` ≥ 8 each
- 5 obvious-wrong: SUT will give a clearly-misaligned response (e.g. "你好我是助手" to a stock-price query) → judge MUST score factuality ≤ 3

Use category `single_tool_call` for all sanity cases. The 5 obvious-correct cases match the static-dict / pattern entries in `agent_decisions.yaml` so the MockLLMClient SUT returns aligned responses. The 5 obvious-wrong cases map to a new MockLLMClient entry that returns `"你好,我是助手。"` regardless of input — add this as a pattern entry matching `"sanity-wrong-"` prefix in `case_id`.

Implementation note: rather than carrying `sanity_label` on `GoldenCase` Pydantic, keep it inside `metadata.sanity_label` (already a free-form dict).

- [ ] **Step 2: Add `compute_sanity_pass_rate` to `eval_runner.py`**

Append:

```python
def compute_sanity_pass_rate(results: list[EvalResult]) -> tuple[float, list[str]]:
    """Returns (pass_rate, failures).

    Sanity rule per spec § 8: judge gives obvious-correct ≥ 8 on factuality
    and obvious-wrong ≤ 3 on factuality. Anything else is a failure.

    Each result must have its source GoldenCase metadata['sanity_label']
    available — but EvalResult doesn't carry case metadata. Caller passes
    a sibling list of (result, label). To keep the API ergonomic, we
    accept (result, label) pairs as a list[tuple]. The runner test wires
    this up.
    """
```

Actually, restructure: return `(pass_rate, failures)` from a function that takes the **labeled results**:

```python
def compute_sanity_pass_rate(
    labeled: list[tuple[EvalResult, str]],
) -> tuple[float, list[str]]:
    """labeled is list of (result, sanity_label).

    sanity_label ∈ {"obvious_correct", "obvious_wrong"}.
    """
    failures: list[str] = []
    for result, label in labeled:
        f = result.scores.factuality
        if label == "obvious_correct" and f < 8:
            failures.append(f"{result.case_id}: obvious_correct but factuality={f} (< 8)")
        elif label == "obvious_wrong" and f > 3:
            failures.append(f"{result.case_id}: obvious_wrong but factuality={f} (> 3)")
    pass_rate = 1.0 - (len(failures) / len(labeled)) if labeled else 1.0
    return pass_rate, failures
```

- [ ] **Step 3: Write the L1 sanity test**

Create `backend/tests/integration/test_sanity_check.py`:

```python
"""L1 — sanity check: with deterministic mock judge fixture, all 10 sanity
cases must pass. If they don't, the mock fixture or the prompt is wrong.

A non-100% sanity pass with mock judge means the mock fixture's scores
don't match the cases — fix the fixture.
"""

from pathlib import Path

from app.services.eval_models import load_golden_jsonl
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner, compute_sanity_pass_rate
from app.services.judge import Judge
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


SANITY_PATH = Path("backend/tests/fixtures/eval/sanity_obvious_cases.jsonl")


def test_mock_sanity_pass_rate_is_100(
    mock_llm_client: MockLLMClient,
    tmp_eval_db: Path,
) -> None:
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    recorder = EvalRecorder(db_path=tmp_eval_db)
    recorder.init_schema()
    sut = LLMService(client=mock_llm_client, trace_service=trace)
    judge = Judge(llm=LLMService(client=mock_llm_client), judge_tier="balanced")
    runner = EvalRunner(sut=sut, judge=judge, trace_service=trace, recorder=recorder)

    cases = load_golden_jsonl(SANITY_PATH)
    assert len(cases) == 10
    results = runner.run_many(cases)

    labeled = [(r, c.metadata["sanity_label"]) for r, c in zip(results, cases)]
    pass_rate, failures = compute_sanity_pass_rate(labeled)
    assert pass_rate == 1.0, f"Sanity failures:\n  - " + "\n  - ".join(failures)
```

> **Note**: this requires the MockLLMClient to return **distinct** scores for "obvious correct" vs "obvious wrong" prompts. Add a second `__recorded__:` fixture (`judge_4dim_obvious_wrong.json`) with `factuality.score = 1`, and route the wrong-case judge prompts to it via a pattern in `agent_decisions.yaml` matching the prompt's `sut_response="你好,我是助手"` substring.

- [ ] **Step 4: Verify**

```bash
uv run pytest backend/tests/integration/test_sanity_check.py -v
```
Expected: 1 test PASS (pass rate = 1.0).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/eval/sanity_obvious_cases.jsonl backend/tests/fixtures/llm_mocks/ backend/app/services/eval_runner.py backend/tests/integration/test_sanity_check.py
git commit -m "$(cat <<'EOF'
feat(services): add sanity check — 10-case obvious-pair fixture + pass-rate calc

原因 layer: services
EOF
)"
```

---

## Task 10: L2 cassette demo — 1 GoldenCase real LLM, real Judge

**Files:**
- Create: `backend/tests/e2e/test_eval_pipeline_cassette.py`
- Create: `backend/tests/fixtures/cassettes/test_eval_pipeline_cassette/test_one_case_real_llm_real_judge.yaml` (auto-recorded)

- [ ] **Step 1: Write the test**

```python
# backend/tests/e2e/test_eval_pipeline_cassette.py
"""L2 — eval pipeline against real DashScope endpoint, replayed via cassette.

This proves the entire pipeline (SUT call → trace → judge call → recorder)
works against the real LLM behavior. Slow on first record, fast on replay.
"""

import os
from pathlib import Path

import pytest
from openai import OpenAI

from app.services.eval_models import GoldenCase
from app.services.eval_recorder import EvalRecorder
from app.services.eval_runner import EvalRunner
from app.services.judge import Judge
from app.services.llm_service import LLMService
from app.services.trace_service import TraceService


class _Adapter:
    """Same adapter pattern as Plan B's L2 cassette test."""
    def __init__(self, client: OpenAI) -> None:
        self._c = client

    def chat(self, prompt, model, schema):  # type: ignore[no-untyped-def]
        r = self._c.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        return _Raw(
            content=r.choices[0].message.content or "",
            prompt_tokens=r.usage.prompt_tokens if r.usage else 0,
            completion_tokens=r.usage.completion_tokens if r.usage else 0,
        )


class _Raw:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


@pytest.fixture
def real_adapter() -> _Adapter:
    return _Adapter(
        OpenAI(
            api_key=os.environ.get("DASHSCOPE_API_KEY", "fake-for-replay"),
            base_url=os.environ.get(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    )


@pytest.mark.vcr
def test_one_case_real_llm_real_judge(
    real_adapter: _Adapter,
    tmp_eval_db: Path,
) -> None:
    trace = TraceService(db_path=tmp_eval_db)
    trace.init_schema()
    recorder = EvalRecorder(db_path=tmp_eval_db)
    recorder.init_schema()

    sut = LLMService(client=real_adapter, trace_service=trace)
    judge_llm = LLMService(client=real_adapter)
    judge = Judge(llm=judge_llm, judge_tier="balanced")
    runner = EvalRunner(sut=sut, judge=judge, trace_service=trace, recorder=recorder)

    case = GoldenCase(
        case_id="cassette-1",
        category="single_tool_call",
        user_input="贵州茅台的股票代码是什么?用一句话回答。",
        expected_behavior={"response_must_contain": ["600519"]},
        metadata={"added_by": "plan-c-l2", "added_at": "2026-04-30", "tags": ["v0"]},
    )

    result = runner.run_one(case)
    assert result.case_id == "cassette-1"
    # On a clean run vs replay, the score must be reproducible
    assert result.scores.factuality is not None
    assert result.judge_cost_cny >= 0
```

- [ ] **Step 2: First run must FAIL (no cassette yet)**

Run: `uv run pytest backend/tests/e2e/test_eval_pipeline_cassette.py -v`
Expected: FAIL with `CannotOverwriteExistingCassetteException` — same safety as Plan B.

- [ ] **Step 3: Record the cassette**

```bash
unset all_proxy https_proxy http_proxy
VCR_RECORD_MODE=once uv run pytest backend/tests/e2e/test_eval_pipeline_cassette.py -v
```

Expected:
- Test PASSES
- Cassette appears at `backend/tests/fixtures/cassettes/test_eval_pipeline_cassette/test_one_case_real_llm_real_judge.yaml`
- DashScope cost increases by ≤ ¥0.05 (one SUT call + one Judge call)

- [ ] **Step 4: Sanitize check**

```bash
uv run python scripts/check_cassette_sanitize.py backend/tests/fixtures/cassettes/test_eval_pipeline_cassette/test_one_case_real_llm_real_judge.yaml
```
Expected: exit 0.

- [ ] **Step 5: Replay (no network)**

```bash
unset VCR_RECORD_MODE
uv run pytest backend/tests/e2e/test_eval_pipeline_cassette.py -v
```
Expected: PASS, ≤ 500ms (two interactions to replay vs Plan B's 200ms single interaction).

- [ ] **Step 6: Cassette size check**

```bash
du -h backend/tests/fixtures/cassettes/test_eval_pipeline_cassette/test_one_case_real_llm_real_judge.yaml
```
Expected: ≤ 80KB (two interactions, larger than Plan B's single interaction).

- [ ] **Step 7: Commit**

```bash
git add backend/tests/e2e/test_eval_pipeline_cassette.py backend/tests/fixtures/cassettes/test_eval_pipeline_cassette/
git commit -m "$(cat <<'EOF'
test(e2e): add L2 cassette demo for full eval pipeline

原因 layer: tests
EOF
)"
```

---

## Task 11: Cross-judge Spearman script + L0 unit tests

**Files:**
- Create: `scripts/cross_judge_check.py`
- Create: `backend/tests/unit/test_cross_judge.py`

- [ ] **Step 1: Write the L0 test**

```python
# backend/tests/unit/test_cross_judge.py
"""L0 — pure-function tests for Spearman + sanity utilities used by
scripts/cross_judge_check.py. The script's CLI shell is not unit-tested.
"""

import math

from scripts.cross_judge_check import rank, spearman


def test_rank_no_ties() -> None:
    assert rank([3.0, 1.0, 2.0]) == [3.0, 1.0, 2.0]


def test_rank_with_ties_uses_average() -> None:
    # values: 1, 2, 2, 4 → ranks: 1, 2.5, 2.5, 4
    assert rank([1.0, 2.0, 2.0, 4.0]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_perfect_positive() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [10.0, 20.0, 30.0, 40.0]
    assert math.isclose(spearman(xs, ys), 1.0)


def test_spearman_perfect_negative() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [40.0, 30.0, 20.0, 10.0]
    assert math.isclose(spearman(xs, ys), -1.0)


def test_spearman_uncorrelated_close_to_zero() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [3.0, 1.0, 4.0, 2.0]
    rho = spearman(xs, ys)
    assert -0.5 < rho < 0.5
```

- [ ] **Step 2: Verify it fails**

Run: `uv run pytest backend/tests/unit/test_cross_judge.py -v`
Expected: FAIL — `scripts.cross_judge_check` not importable.

- [ ] **Step 3: Implement `cross_judge_check.py`**

Create `scripts/cross_judge_check.py`:

```python
"""Cross-judge Spearman script — manual-trigger sanity check.

Reads two sets of EvalResult (e.g. judge=v4-flash vs judge=qwen-max) keyed
by case_id, computes Spearman over factuality scores. Spec § 8 e-alt
demands ≥ 0.70.

Not invoked from CI under v0 — `uv run python scripts/cross_judge_check.py
--judge-a results_a.jsonl --judge-b results_b.jsonl` only.

Pure functions (rank, spearman) are unit-tested; the CLI shell is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def rank(xs: list[float]) -> list[float]:
    """Average-rank — ties get the mean of their ordinal positions."""
    n = len(xs)
    indexed = sorted(range(n), key=lambda i: xs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[indexed[j + 1]] == xs[indexed[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-indexed
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("Spearman requires equal-length lists with len >= 2")
    rx = rank(xs)
    ry = rank(ys)
    n = len(rx)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    den_x = sum((r - mean_x) ** 2 for r in rx) ** 0.5
    den_y = sum((r - mean_y) ** 2 for r in ry) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _load_factualities(path: Path) -> dict[str, float]:
    """Reads JSONL of EvalResult shape, returns {case_id: factuality_score}."""
    out: dict[str, float] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            out[row["case_id"]] = float(row["scores"]["factuality"])
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--judge-a", type=Path, required=True)
    p.add_argument("--judge-b", type=Path, required=True)
    p.add_argument("--threshold", type=float, default=0.70)
    args = p.parse_args(argv)

    a = _load_factualities(args.judge_a)
    b = _load_factualities(args.judge_b)
    common = sorted(set(a) & set(b))
    if len(common) < 2:
        print(f"ERROR: only {len(common)} cases in common; need >= 2", file=sys.stderr)
        return 2
    xs = [a[c] for c in common]
    ys = [b[c] for c in common]
    rho = spearman(xs, ys)
    print(f"Spearman over {len(common)} cases: {rho:.3f}")
    if rho < args.threshold:
        print(f"FAIL: rho < threshold ({args.threshold})", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Verify**

```bash
uv run pytest backend/tests/unit/test_cross_judge.py -v
```
Expected: 5 tests PASS.

> **Note**: `scripts/` is not a Python package by default. To make `from scripts.cross_judge_check import rank, spearman` work in tests, either (a) add an empty `scripts/__init__.py` (consistent with `scripts/check_cassette_sanitize.py` from Plan B which is currently runnable but not importable), or (b) add `scripts/` to `sys.path` in a conftest. Choose (a) — minimal, makes both files importable from tests.

If `scripts/__init__.py` already exists from Plan B work, no action needed; otherwise add it in this commit.

- [ ] **Step 5: Commit**

```bash
git add scripts/cross_judge_check.py scripts/__init__.py backend/tests/unit/test_cross_judge.py
git commit -m "$(cat <<'EOF'
feat(scripts): add cross-judge Spearman manual-trigger script

原因 layer: services
EOF
)"
```

---

## Task 12: `poe` commands + Plan C retrospective

**Files:**
- Modify: `pyproject.toml`
- Modify: this plan file (fill retrospective)

- [ ] **Step 1: Add the three poe tasks**

In `pyproject.toml [tool.poe.tasks]`, append:

```toml
# v0 eval — runs the L1 EvalRunner integration test (mock SUT + mock Judge).
# Real-LLM eval comes via L2 cassette test which `poe ci` already runs.
eval.cmd = "pytest backend/tests/integration/test_eval_runner.py backend/tests/integration/test_sanity_check.py -v"
eval.help = "Run mock-driven eval pipeline (L1)."

# Sanity check only — fast, deterministic, must always pass.
eval-sanity.cmd = "pytest backend/tests/integration/test_sanity_check.py -v"
eval-sanity.help = "Run sanity-pair check (10 cases) under mock judge."

# Manual trigger — usage: poe eval-cross-judge -- --judge-a a.jsonl --judge-b b.jsonl
eval-cross-judge.shell = "uv run python scripts/cross_judge_check.py $@"
eval-cross-judge.help = "Compute cross-judge Spearman on two judge runs (manual)."
```

- [ ] **Step 2: Verify the three commands**

```bash
uv run poe eval
uv run poe eval-sanity
uv run poe eval-cross-judge --help  # should print argparse help and exit
```
Expected: first two pass; third prints help.

- [ ] **Step 3: Fill the Plan C retrospective**

Append to the bottom of this plan file. Use the same template Plan B used:
- Implementation completion date / branch / merge commit / commits / time
- 对的设计(3 条)
- 错的设计 / plan 漏了什么(3 条)
- 下个 spec / plan 要避免(3 条)
- 沉淀到 memory(specific memory file names + 1-line each)
- Subagent-driven-development 节奏复盘
- Plan D 启动条件 — what is now ready for "Nightly CI + cost guardrail + cassette drift detection"

- [ ] **Step 4: Final CI gate**

```bash
uv run poe ci
```
Expected: ruff format check, ruff check, mypy 100%, pytest all green (Plan B 29 + Plan C ≈ 30 new tests).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml docs/superpowers/plans/2026-04-30-dev-test-loop-C-eval-trace-infra.md
git commit -m "$(cat <<'EOF'
docs(plan): Plan C retrospective + poe eval scaffold

原因 layer: docs
EOF
)"
```

---

## Acceptance Criteria

- [ ] `uv run poe ci` green on the worktree
- [ ] All Plan B tests still pass (Plan B contract intact)
- [ ] `tmp_eval_db` fixture used by every test that touches SQLite (no global db)
- [ ] L2 cassette exists for the eval pipeline, ≤ 80KB, sanitized, replays in ≤ 500ms
- [ ] `LLMService.chat(trace_service=None)` writes zero rows to SQLite (Plan B contract)
- [ ] `LLMService.chat(trace_service=ts)` writes exactly 1 span per call
- [ ] Sanity check L1 test: 10/10 pass (pass_rate = 1.0)
- [ ] Cross-judge `spearman` unit tests pass; CLI script invokable via `poe eval-cross-judge`
- [ ] Plan C retrospective filled

## Test plan (run on completion)

- Local: `uv run poe ci`
- Local: `uv run poe eval`
- Local: `uv run poe eval-sanity`
- Local: cassette replay: `unset VCR_RECORD_MODE && uv run pytest backend/tests/e2e/test_eval_pipeline_cassette.py -v`
- Local: pre-commit on cassette: `uv run pre-commit run check-cassette-sanitize --all-files`

---

## Notes for the implementer

- **Plan B contract is sacred.** `LLMService(client, tier_router)` must keep working without `trace_service`. New behavior is opt-in via the optional 3rd param. If any Plan B test fails after Task 3, **stop and report** — don't paper over.
- **Trace summary in Judge prompt is intentionally minimal.** Future plans can swap in richer summaries (token counts per span, per-tool latency, etc.) without changing the Judge contract.
- **`tool_correctness=None` is a valid evidence-bearing answer**, not a missing field. The Judge prompt instructs the LLM to set null + write "N/A — no tool calls" as evidence. `JudgeScores.aggregate_avg` ignores None values.
- **SQLite is per-test in tests, per-app in prod.** The `tmp_eval_db` fixture cleans up after each test. There is no shared `backend/data/eval.sqlite` checked into git — the file is created on demand by `init_schema`.
- **Spike result drives Tasks 7-10 cost.** If Task 0 spike shows a single judge call costs > ¥0.05, file an issue and discuss before proceeding to Task 10 (which records 2 calls).
- **Per Plan B sediment**: this plan writes "intent + constraint" for fixture file *contents* (Tasks 6/9), poe task bodies (Task 12), and starter golden cases — not literal lines. The Pydantic contracts (Tasks 1/5/6/7) and SQL schemas (Tasks 2/5) are fully prescribed because they're stability promises.

---

## Plan C retrospective — Task 0 spike result

- **Date probed**: 2026-04-30
- **prompt_tokens**: 208
- **completion_tokens**: 549 (含 `reasoning_tokens=400`,即用户可见的 JSON 输出 ≈ 149 tokens,reasoning 占 73%)
- **total_tokens**: 757
- **Estimated single-case cost in ¥**: ~¥0.0005(judge 一次);加上 SUT 一次 ~¥0.0001 → 一条 case ≈ ¥0.0006
- **Estimated 70-case eval cost**: ~¥0.04 / 次(远低于 spec § 8 估算的 ¥1-2 / 次,主因 v4-flash 单价比 spec 起草时假设的低 + token 消耗 ~1K 而非 ~3K / case)
- **Action taken**: proceed,no spec sync needed。¥20 hard limit 的 10× buffer 保留作 fail-fast。**Reasoning token 占 73% 的现象在 Plan D 写 cost guardrail 时要注意**:计费是按 reasoning + visible 都算 output,一次"短回答"实际可能消耗 5x output tokens,Plan D 的 `EVAL_COST_LIMIT_CNY` 累计逻辑要按 total_tokens 而非 visible content length 估。

---

## Retrospective

**Implementation completion date**: 2026-04-30
**Branch**: `feat/dev-test-loop-C`(基于 main `750ee3f`)
**Total commits**: 13(11 task commits + 2 fix commits)
**Total time**: ~3 小时(跟 Plan B 的 3 小时持平,比 Plan A 的 5 小时少;Plan A/B 立基础设施 vs Plan C 是上层服务垒)

### 对的设计(3 条)

1. **`LLMService.chat` 加 trace 是严格 additive,Plan B 契约零回归**。`trace_service: TraceService | None = None` 默认 None,Plan B 11 个 LLMService-related 测试 + 5 个 MockLLMClient 测试零修改。`request_id` 加到 `LLMResponse` 也是 default-None additive。这个"零回归扩展"模式将延续 Plan D 加 cost_cny price table 时也不破坏 schema。

2. **`tmp_eval_db` fixture 把 Plan B 教训直接落地**。每个测试自己一份 sqlite,tmp_path 自动清理。0 次共享 db 污染,0 次"我跑这个测试影响了那个测试"。Plan B `feedback_test_env_modeling` 沉淀的"测试 env 必须 plan 阶段建模到 fixture"完美兑现。

3. **MockLLMClient pattern→recorded redirect 让 mock 也能区分多 judge 分数**。Task 7 加 4 行(命中 pattern 后检查 `__recorded__:` 前缀就 redirect),Task 9 sanity check 用两层路由(`SANITY_WRONG_q1` SUT 输入 → MockLLMClient 返回 `"你好,我是助手"` → judge prompt 含该串 → 命中 specific judge pattern → routed to `judge_4dim_obvious_wrong` 给 factuality=1)。**没改 Plan B 已稳定代码的核心 dispatch logic**,只在 pattern 命中后加一个 if-startswith 分支。这就是好的扩展性。

### 错的设计 / plan 漏了什么(3 条)

1. **Plan 让 implementer 同时加 typed signature 和 `# type: ignore[no-untyped-def]`**(Task 2 step 1 fixture)。两者矛盾:typed signature 已经让 mypy 不报 no-untyped-def,ignore 反而触发 unused-ignore 警告。Task 1/2 都是单文件 mypy 跑没暴露,Task 3 后跑全 backend mypy 才出错。**Lesson**:plan 写"加 type:ignore" 时,先想清楚同位置的 type annotation 是不是已经满足 — 不要预防式加 ignore。

2. **Plan 没指定 cassette `before_record_response` 处理 vendor headers**。Plan B retrospective 已记录"`x-dashscope-call-gateway` header 触发 sanitize hook"是事后补丁,但 Plan C plan 没把这个 sediment 落地为 conftest 改动。Task 10 implementer 又一次"recording 时发现 leak,加 strip"。**Plan B 的教训没成功传到 Plan C plan 阶段** — 这本身是 plan 与 retrospective 流转的问题。

3. **Plan 没考虑 trace_summary 含 latency_ms 会让 cassette body match 失败**。Task 10 implementer 发现 `_summarize_trace` 给 judge prompt 注入 `total_latency_ms=137`(实测一次)、`total_latency_ms=2`(replay 时 mock client 速度)—— 同一 prompt body 在 record 和 replay 之间不同,vcr `body` matcher 拒绝。implementer 不得不在 test-module 级 override vcr_config 删 body match。**Lesson**:任何 prompt template 含动态值(latency / timestamp / uuid),plan 阶段就要选择 strip-from-prompt 或 vcr-not-match-body 二者之一。

### 下个 spec / plan 要避免(3 条)

1. **`# type: ignore` 不要预防式加** — 先想清楚同位置的 type annotation 是否已满足该错码;如果是,ignore 多余,会触发 unused-ignore。
2. **任何动态值进 prompt 必预案** — latency / timestamp / uuid 进 prompt body 会让 cassette body match 失效,plan 阶段就决定 strip 还是 vcr_config 不 match body。
3. **跨 plan 的 retrospective sediment 必须显式落地到下一 plan 的具体 task** — Plan B 的 vendor-header strip 教训没传到 Plan C plan,导致 Task 10 重蹈覆辙。新 plan 的"Memory inputs"段落要不只是列 memory 文件,还要把每条 memory 翻译成具体 task 步骤。

### 沉淀到 memory

- [feedback_cassette_dynamic_prompt_values.md](memory/feedback_cassette_dynamic_prompt_values.md) — prompt 含动态值(latency/uuid/timestamp)会破坏 cassette body match;plan 阶段必须选 strip-from-prompt 或 vcr-not-match-body
- [feedback_type_ignore_with_typed_signature.md](memory/feedback_type_ignore_with_typed_signature.md) — typed signature 已满足 no-untyped-def 时不要加 `# type: ignore`,会触发 unused-ignore 警告
- [project_eval_pipeline_contract.md](memory/project_eval_pipeline_contract.md) — Plan C 立的 EvalRunner / Judge / TraceService / EvalRecorder 契约;SUT 通过 DI 注入(v0 是 bare LLMService);v0~v3 稳定;两表共享 sqlite 文件 + request_id JOIN

### Subagent-driven-development 节奏复盘

- **总 subagent 调用**:**9 次**(8 implementer + 1 final reviewer 撞 rate limit 取消)。Plan B 是 19 次,Plan C 减少 53%。
- **节省来自**:
  - (1) 全部 inline review,跳过 spec reviewer + code quality reviewer subagent
  - (2) Task 0 spike + Task 4 L1 test + Task 12 poe/retrospective 直接 inline 不派 implementer
  - (3) 单一 sonnet model 全部一轮过,无 review-loop iteration
- **全 inline review 的代价**:1 次 mypy unused-ignore 错误未被 implementer 提前发现(Task 2 后),inline 加了 2 个 fix commit(`385122a` + `853c93c`)。比派 spec reviewer 节省的 quota 多。
- **主对话 context 消耗**:中等。涉及多个 task 修改 Plan B 已稳定代码(`LLMService` / `MockLLMClient`),inline review 需要细看 diff,但 0 次回归。
- **没派 final-reviewer 因为 rate limit**(8:10pm 重置撞上)。inline self-verify 替代:跑全套 ci + 验证关键架构契约(LLM_MODE 不分支 / openai 不 import / cassette 路径 / sanitize 0 命中)。
- **Plan B 的"两层 review"缺席没造成质量下降**:implementer 自己抓到 yaml pattern 顺序问题(Task 7)+ cassette body match 漂移(Task 10)+ vendor header sanitize(Task 10),都比预期更主动。

### Plan D 启动条件

Plan C 完成后,Plan D(Nightly CI + Cost Guardrail + Drift Detection)依赖已就位:

- ✅ Eval pipeline 端到端可跑(SUT → trace → judge → recorder),`poe eval` / `poe eval-sanity` 一键
- ✅ Cross-judge Spearman 计算可用(`poe eval-cross-judge`),手动触发
- ✅ L2 cassette 录制 + 回放闭环验证过两次(Plan B `test_llm_service_cassette` + Plan C `test_eval_pipeline_cassette`)
- ✅ Sanitize hook + before_record_response 钩子组合可靠(实测两次发现 + 自动修)
- ✅ Cost 数据点充分(Task 0 spike:judge prompt 757 total_tokens,其中 reasoning 占 73%)。Plan D 写 `EVAL_COST_LIMIT_CNY` enforcement 时按 total_tokens 累加,不要按 visible content length。

**Plan D 范围**(spec § 5 + § 6):
- GH Actions PR job(ruff + mypy + L0 + L1 + L2 子集 ≤ 5min)
- GH Actions nightly job(L2 全集 + L3 eval + cassette validation + dependency security audit ≤ 30min)
- `EVAL_COST_LIMIT_CNY=20` hard limit(LLMService 累计成本超阈值即 abort)
- Per-model price table(消除 Plan B/C 的 `cost_cny=0.0` stub)
- Cassette drift detection(nightly 真打 LLM 对 cassette 跑 LLM-as-judge,差异 ≥ 阈值开 issue)
- `trace-view` CLI(读 SQLite spans 表呈现 trace,replace 现有 echo stub)

**未解风险**:`deepseek-v4-flash` reasoning_tokens 占比 73%(Plan B + Plan C 都观察到)。如果 v0 model 切到非 reasoning model(spec § 7 留接口),per-token 成本会大幅下降但行为可能变。Plan D cost guardrail 默认按当前 reasoning model 估,留 5x buffer。
