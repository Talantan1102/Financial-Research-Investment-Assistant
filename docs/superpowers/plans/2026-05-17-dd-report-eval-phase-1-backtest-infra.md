# DD Report Quality Eval — Phase 1: Backtest Infra Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 InvestmentDueDiligenceReport 质量评估体系搭建 Phase 1 backtest 基础设施 — 包含 time-travel 数据控制、LLM swap 机制、golden case 数据采集、leak detector,为 Phase 2 的 5 个 metric 实现提供运行底座。

**Architecture:** 新建 `backend/eval/dd_report/` 子系统(跟 `backend/eval/memory/` 同级),包含 `BacktestRunner`(orchestrate)/ `LLMSwapper`(OpenRouter wrapper)/ `LeakDetector`(integration test 工具)/ `golden/backtest_cases.jsonl`(32 backtest + 8 sanity case)。DB 复用 `eval_results` 表 + 新增 `backtest_runs` 表(含 `git_sha` / `ablation_variant` / `llm_model` 字段)。Tushare client 已有 `ann_date` filter 复用即可;KB schema 缺 `publish_date` 字段需要 spike + 补字段。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy / Pydantic v2 / pytest / vcrpy(cassette)/ OpenRouter API / 复用项目现有 EvalRecorder / TraceService / LLMService 等基础设施

**关联文档:** `docs/superpowers/specs/2026-05-17-dd-report-quality-eval-design.md`(spec v1.1)— Phase 1 对应 spec § 4.1 / § 4.4 / § 4.5 / § 5.1 / § 5.3 / § 7.4

---

## File Structure(本 Plan 涉及)

**Create:**
- `backend/eval/dd_report/__init__.py` — 模块入口
- `backend/eval/dd_report/llm_swapper.py` — OpenRouter wrapper,evaluator LLM swap
- `backend/eval/dd_report/backtest_runner.py` — orchestrator skeleton(Phase 1 不接 metric,Phase 2 才接)
- `backend/eval/dd_report/leak_detector.py` — 数据 leakage 检测工具
- `backend/eval/dd_report/tushare_backtest_adapter.py` — tushare ann_date filter wrapper
- `backend/eval/dd_report/kb_backtest_adapter.py` — KB chunk publish_date filter wrapper
- `backend/eval/dd_report/golden/backtest_cases.jsonl` — 32 backtest + 8 sanity case 元数据
- `backend/eval/dd_report/golden/ground_truth_loader.py` — 加载后续真实数据(后续股价/公告)
- `backend/scripts/build_dd_backtest_cases.py` — 一次性 CLI,从 tushare 采集 32+8 case 数据
- `backend/tests/eval/dd_report/__init__.py`
- `backend/tests/eval/dd_report/conftest.py` — fixture(沿用 b1_differential pattern)
- `backend/tests/eval/dd_report/test_llm_swapper.py`
- `backend/tests/eval/dd_report/test_tushare_backtest_adapter.py`
- `backend/tests/eval/dd_report/test_kb_backtest_adapter.py`
- `backend/tests/eval/dd_report/test_backtest_runner.py`
- `backend/tests/eval/dd_report/test_leak_detector.py`
- `backend/tests/eval/dd_report/test_golden_cases_smoke.py`
- `alembic/versions/<rev>_dd_report_eval_schema.py` — DB migration(eval_results 加列 + backtest_runs 新表)

**Modify:**
- `backend/app/kb/ingest/schemas.py`(或等价文件,Phase 1 第一步 spike 后确认实际路径)— KB chunk schema 加 `publish_date` 字段
- `backend/app/services/eval_models.py` — `EvalResult` 加可选 `backtest_run_id` / `cut_off_date` / `evaluator_llm` / `case_type` 字段
- `backend/.env.example` — 加 `OPENROUTER_API_KEY` env var

**Reference(不动,但 plan 内需要 import / 参考)**:
- `backend/app/services/eval_recorder.py:33` — `EvalRecorder` 类(eval_results 表写入入口)
- `backend/app/services/trace_service.py` — TraceService(request_id JOIN)
- `backend/app/data/tushare_client.py:202` — 已有 `ann_date_start/end` 参数,直接复用
- `backend/eval/memory/eval_runner.py` — c5 eval runner pattern 参考
- `backend/tests/eval/golden_cases/b1_differential/conftest.py` — golden case fixture pattern 参考

---

## Task 1.0:Project setup — 创建目录骨架 + spike KB schema

**Files:**
- Create: `backend/eval/dd_report/__init__.py`
- Create: `backend/tests/eval/dd_report/__init__.py`
- Inspect(spike): `backend/app/kb/` 全树,定位 chunk schema 文件 + 确认是否已有 `publish_date`

- [ ] **Step 1: 创建模块骨架目录 + __init__.py**

```bash
mkdir -p backend/eval/dd_report/golden
mkdir -p backend/tests/eval/dd_report
```

写空 `__init__.py`:

```python
# backend/eval/dd_report/__init__.py
"""InvestmentDueDiligenceReport quality eval — Phase 1 backtest infra.

spec: docs/superpowers/specs/2026-05-17-dd-report-quality-eval-design.md
"""
```

```python
# backend/tests/eval/dd_report/__init__.py
# empty marker file
```

- [ ] **Step 2: Spike KB chunk schema — 确认 publish_date 字段存在性**

Run:

```bash
grep -rn "class.*Chunk\|class.*Document" backend/app/kb/ --include="*.py"
grep -rn "publish_date\|publish_time\|pub_date\|published_at" backend/app/kb/ --include="*.py"
```

Expected outcomes:
- 若 grep 第二条返回任意 hit → **publish_date 已存在**,记录文件路径 + 类名,本 task Step 4 skip;Task 1.3 直接复用
- 若 grep 第二条为空 → **publish_date 缺失**(已知风险,spec § 9 #5),需要在 Task 1.3 加字段

把 spike 结论写到本 plan 顶部"Spike Notes"区(下面):

```markdown
## Spike Notes (Step 2 结果)
- KB chunk schema 文件位置: <path>
- publish_date 字段是否存在: yes / no
- 若 no,Task 1.3 第一步要在该文件加字段 + 提供 migration / re-ingest 方案
```

- [ ] **Step 3: 验证 OpenRouter API 可用性 + .env.example 加 key**

修改 `backend/.env.example` 在 OpenRouter 段加注释 + key 模板(若已有 OPENROUTER_API_KEY 跳过此 step):

```bash
grep -n "OPENROUTER_API_KEY" backend/.env.example
```

若已存在则确认 placeholder 是 `your-openrouter-api-key` 这种,无需修改;若不存在,在 OpenRouter 段后加:

```bash
# OpenRouter API Key（v1.x DD report eval 必填，用于 evaluator LLM swap）
# 申请地址: https://openrouter.ai/
OPENROUTER_API_KEY=your-openrouter-api-key
```

- [ ] **Step 4: Commit**

```bash
git add backend/eval/dd_report/__init__.py backend/tests/eval/dd_report/__init__.py backend/.env.example
git commit -m "feat(dd-eval): Phase 1 Task 1.0 — 创建 dd_report 模块骨架 + KB schema spike + .env 加 OPENROUTER_API_KEY"
```

---

## Task 1.1:DB schema 扩展(eval_results 加列 + backtest_runs 新表)

**Files:**
- Modify: `backend/app/services/eval_models.py` — `EvalResult` Pydantic model 加可选字段
- Create: `alembic/versions/<rev>_dd_report_eval_schema.py` — migration
- Modify: `backend/app/services/eval_recorder.py:33` — 写入支持新字段
- Test: `backend/tests/unit/test_eval_recorder.py`(扩展现有测试)

**注意**:项目记忆 `v0.9.x-no-alembic-until-db-unify.md` 说 v0.9.x 不引 alembic。但 spec § 5.2 / § 5.3 提到 alembic + roadmap 3.5 已经 PR A 引入了 alembic foundation(`2026-05-07-roadmap-3.5-pr-A-alembic-foundation.md`)。**Step 1 先确认 alembic 是否已 ship**:

- [ ] **Step 1: 确认 alembic 状态**

Run:

```bash
ls alembic/versions/ 2>/dev/null && head -5 alembic.ini 2>/dev/null
```

Expected:
- 若 `alembic/versions/` 存在且有现成 migration → 走 alembic 路线(下面 Step 4)
- 若不存在 → 走 `create_all()` 幂等路线(项目记忆 v0.9.x pattern)

把结论记到 task 顶部:

```markdown
## Alembic Status (Step 1 结果)
- alembic 是否已 ship: yes / no
- 路线: alembic migration / create_all() 幂等
```

- [ ] **Step 2: Write failing test — EvalResult 接受新字段**

```python
# backend/tests/unit/test_eval_recorder.py (在文件末尾加新测试)
def test_eval_result_accepts_backtest_fields() -> None:
    """v1.x DD report eval: EvalResult 接受 backtest 相关可选字段."""
    from datetime import UTC, datetime
    from app.services.eval_models import EvalResult, JudgeScores

    result = EvalResult(
        eval_id="bt-eval-001",
        request_id="bt-req-001",
        case_id="bt-case-600519-20240630",
        scores=JudgeScores(
            factual_accuracy=0.9,
            completeness=0.8,
            tone_appropriateness=0.85,
            safety_compliance=0.95,
        ),
        judge_model="gpt-4o-2024-05-13",
        judge_cost_cny=0.5,
        judge_latency_ms=2000,
        timestamp=datetime.now(UTC),
        # 新字段
        backtest_run_id="bt-run-001",
        cut_off_date="2024-06-30",
        evaluator_llm="gpt-4o-2024-05-13",
        case_type="backtest",
    )
    assert result.backtest_run_id == "bt-run-001"
    assert result.cut_off_date == "2024-06-30"
    assert result.evaluator_llm == "gpt-4o-2024-05-13"
    assert result.case_type == "backtest"
```

- [ ] **Step 3: Run test — verify failure**

```bash
uv run pytest backend/tests/unit/test_eval_recorder.py::test_eval_result_accepts_backtest_fields -v
```

Expected: FAIL — `EvalResult` 没有 `backtest_run_id` 等字段。

- [ ] **Step 4: Implement — EvalResult 加可选字段**

修改 `backend/app/services/eval_models.py`,在 `EvalResult` 类里加:

```python
# 在 EvalResult 类定义内,timestamp 字段下方加:

# v1.x DD report eval 扩展字段(可选,保持 Plan C/c5 backward compat)
backtest_run_id: str | None = Field(
    default=None, description="关联 backtest_runs.run_id (Phase 1 起)"
)
cut_off_date: str | None = Field(
    default=None, description="backtest 时点 ISO date string (YYYY-MM-DD)"
)
evaluator_llm: str | None = Field(
    default=None, description="评估时 swap 的 LLM model id (e.g. gpt-4o-2024-05-13)"
)
case_type: Literal["backtest", "sanity", "financebench", "cross_llm"] | None = Field(
    default=None, description="case 类别"
)
```

确保文件顶部 `from typing import Literal` 已 import。

- [ ] **Step 5: Run test — verify pass**

```bash
uv run pytest backend/tests/unit/test_eval_recorder.py::test_eval_result_accepts_backtest_fields -v
```

Expected: PASS.

- [ ] **Step 6: Write failing test — EvalRecorder 持久化新字段**

```python
# backend/tests/unit/test_eval_recorder.py (继续)
def test_eval_recorder_persists_backtest_fields(tmp_path: Path) -> None:
    """EvalRecorder 写入新 backtest 字段后能正确读回."""
    from datetime import UTC, datetime
    from pathlib import Path
    from app.services.eval_models import EvalResult, JudgeScores
    from app.services.eval_recorder import EvalRecorder

    db = tmp_path / "eval.sqlite"
    rec = EvalRecorder(db_path=db)
    rec.init_schema()

    rec.write(EvalResult(
        eval_id="bt-eval-002",
        request_id="bt-req-002",
        case_id="bt-case-002",
        scores=JudgeScores(factual_accuracy=0.9, completeness=0.8,
                           tone_appropriateness=0.85, safety_compliance=0.95),
        judge_model="qwen2.5-72b-instruct",
        judge_cost_cny=0.3,
        judge_latency_ms=1500,
        timestamp=datetime.now(UTC),
        backtest_run_id="bt-run-002",
        cut_off_date="2024-12-31",
        evaluator_llm="qwen2.5-72b-instruct",
        case_type="backtest",
    ))

    got = rec.read("bt-eval-002")
    assert got.backtest_run_id == "bt-run-002"
    assert got.cut_off_date == "2024-12-31"
    assert got.evaluator_llm == "qwen2.5-72b-instruct"
    assert got.case_type == "backtest"
```

- [ ] **Step 7: Run test — verify failure**

```bash
uv run pytest backend/tests/unit/test_eval_recorder.py::test_eval_recorder_persists_backtest_fields -v
```

Expected: FAIL — `EvalRecorder.write` 当前不接受新字段,或 SQL schema 不含新列。

- [ ] **Step 8: Implement — EvalRecorder schema + write 接 4 新字段**

修改 `backend/app/services/eval_recorder.py`:

```python
# 替换 _EVAL_RESULTS_SCHEMA:
_EVAL_RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_results (
    eval_id            TEXT PRIMARY KEY,
    request_id         TEXT NOT NULL,
    case_id            TEXT NOT NULL,
    scores_json        TEXT NOT NULL,
    judge_model        TEXT NOT NULL,
    judge_cost_cny     REAL NOT NULL,
    judge_latency_ms   INTEGER NOT NULL,
    timestamp          TEXT NOT NULL,
    backtest_run_id    TEXT,
    cut_off_date       TEXT,
    evaluator_llm      TEXT,
    case_type          TEXT
);
CREATE INDEX IF NOT EXISTS idx_eval_request  ON eval_results(request_id);
CREATE INDEX IF NOT EXISTS idx_eval_case     ON eval_results(case_id);
CREATE INDEX IF NOT EXISTS idx_eval_btrun    ON eval_results(backtest_run_id);
CREATE INDEX IF NOT EXISTS idx_eval_casetype ON eval_results(case_type);
"""
```

替换 `write()` 方法:

```python
def write(self, result: EvalResult) -> None:
    with sqlite3.connect(self._db_path) as con:
        con.execute(
            "INSERT OR REPLACE INTO eval_results "
            "(eval_id, request_id, case_id, scores_json, judge_model, "
            "judge_cost_cny, judge_latency_ms, timestamp, "
            "backtest_run_id, cut_off_date, evaluator_llm, case_type) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                result.eval_id,
                result.request_id,
                result.case_id,
                result.scores.model_dump_json(),
                result.judge_model,
                result.judge_cost_cny,
                result.judge_latency_ms,
                result.timestamp.isoformat(),
                result.backtest_run_id,
                result.cut_off_date,
                result.evaluator_llm,
                result.case_type,
            ),
        )
```

替换 `_row_to_result()`:

```python
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
        backtest_run_id=row["backtest_run_id"],
        cut_off_date=row["cut_off_date"],
        evaluator_llm=row["evaluator_llm"],
        case_type=row["case_type"],
    )
```

- [ ] **Step 9: Run tests — verify pass**

```bash
uv run pytest backend/tests/unit/test_eval_recorder.py -v
```

Expected: 全 PASS(包括原有测试 + 2 个新测试)。

- [ ] **Step 10: Write failing test — backtest_runs 表 schema 存在**

```python
# backend/tests/unit/test_eval_recorder.py (继续)
def test_backtest_runs_table_schema(tmp_path: Path) -> None:
    """backtest_runs 表 schema 含决策 7-8 所需字段."""
    import sqlite3
    from app.services.eval_recorder import EvalRecorder

    db = tmp_path / "eval.sqlite"
    rec = EvalRecorder(db_path=db)
    rec.init_schema()

    with sqlite3.connect(db) as con:
        cols = {row[1] for row in con.execute("PRAGMA table_info(backtest_runs)")}

    expected = {
        "run_id", "created_at", "case_count", "metric_summary_json", "status",
        "git_sha", "ablation_variant", "llm_model",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"
```

- [ ] **Step 11: Run test — verify failure**

```bash
uv run pytest backend/tests/unit/test_eval_recorder.py::test_backtest_runs_table_schema -v
```

Expected: FAIL — backtest_runs 表不存在。

- [ ] **Step 12: Implement — backtest_runs 表 schema 加入 init_schema()**

在 `backend/app/services/eval_recorder.py` 顶部加 schema 常量:

```python
_BACKTEST_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id              TEXT PRIMARY KEY,
    created_at          TEXT NOT NULL,
    case_count          INTEGER NOT NULL,
    metric_summary_json TEXT,
    status              TEXT NOT NULL,
    git_sha             TEXT,
    ablation_variant    TEXT,
    llm_model           TEXT
);
CREATE INDEX IF NOT EXISTS idx_btrun_created ON backtest_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_btrun_ablation ON backtest_runs(ablation_variant);
CREATE INDEX IF NOT EXISTS idx_btrun_llm      ON backtest_runs(llm_model);
"""
```

修改 `init_schema()`:

```python
def init_schema(self) -> None:
    with sqlite3.connect(self._db_path) as con:
        con.executescript(_EVAL_RESULTS_SCHEMA)
        con.executescript(_BACKTEST_RUNS_SCHEMA)
```

- [ ] **Step 13: Run test — verify pass**

```bash
uv run pytest backend/tests/unit/test_eval_recorder.py::test_backtest_runs_table_schema -v
```

Expected: PASS.

- [ ] **Step 14: 跑全套 backend test 确认无回归**

```bash
uv run pytest backend/tests/unit/ -v --maxfail=3
```

Expected: 全 PASS,无回归。

- [ ] **Step 15: Commit**

```bash
git add backend/app/services/eval_models.py backend/app/services/eval_recorder.py backend/tests/unit/test_eval_recorder.py
git commit -m "feat(dd-eval): Phase 1 Task 1.1 — DB schema 扩展 (eval_results 4 新列 + backtest_runs 表)"
```

---

## Task 1.2:LLMSwapper(OpenRouter wrapper)

**Files:**
- Create: `backend/eval/dd_report/llm_swapper.py`
- Test: `backend/tests/eval/dd_report/test_llm_swapper.py`
- Reference: `backend/app/services/openai_client.py`(参考 OpenAI adapter pattern)

- [ ] **Step 1: Write failing test — LLMSwapper 接受 model id 返回 callable**

```python
# backend/tests/eval/dd_report/test_llm_swapper.py
"""LLMSwapper unit tests — Phase 1 Task 1.2.

spec § 4.1 决策 1 / § 5.3 LLM swap 机制
"""
from __future__ import annotations

import pytest


def test_llm_swapper_init_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLMSwapper init 时读 OPENROUTER_API_KEY env."""
    from eval.dd_report.llm_swapper import LLMSwapper

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
    swapper = LLMSwapper()
    assert swapper.api_key == "test-key-123"


def test_llm_swapper_init_explicit_key() -> None:
    """LLMSwapper 接受显式 api_key 覆盖 env."""
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper(api_key="explicit-key")
    assert swapper.api_key == "explicit-key"


def test_llm_swapper_get_client_for_known_models() -> None:
    """LLMSwapper.get_client 对每个 backtest evaluator model 返回 client."""
    from eval.dd_report.llm_swapper import LLMSwapper, EVALUATOR_MODELS

    swapper = LLMSwapper(api_key="test-key")

    # spec § 4.1 决策 1 — 3 个 backtest evaluator LLM
    expected = {"gpt-4o-2024-05-13", "qwen2.5-72b-instruct", "deepseek-v3"}
    assert expected.issubset(set(EVALUATOR_MODELS))

    for model_id in expected:
        client = swapper.get_client(model_id)
        assert client.model == model_id
        assert client.api_key == "test-key"


def test_llm_swapper_unknown_model_raises() -> None:
    """LLMSwapper.get_client 对未知 model raise."""
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper(api_key="test-key")
    with pytest.raises(ValueError, match="unknown evaluator model"):
        swapper.get_client("not-a-real-model")
```

- [ ] **Step 2: Run test — verify failure**

```bash
uv run pytest backend/tests/eval/dd_report/test_llm_swapper.py -v
```

Expected: FAIL — `eval.dd_report.llm_swapper` 不存在。

- [ ] **Step 3: Implement — LLMSwapper**

```python
# backend/eval/dd_report/llm_swapper.py
"""LLMSwapper — OpenRouter API wrapper for evaluator LLM swap.

spec § 4.1 决策 1 / § 5.3:Pipeline-as-SUT 评估的核心组件,允许 BacktestRunner
在运行时切换 evaluator LLM。生产 path 不受影响(OpenAIAdapter 走 dashscope)。

支持的 evaluator model(spec § 4.1 决策 1 选 cutoff < 2024):
  - gpt-4o-2024-05-13       (cutoff 2023-10)
  - qwen2.5-72b-instruct    (cutoff 2023-10)
  - deepseek-v3             (cutoff 早期 2024)

Cross-LLM 矩阵(决策 8.2)额外支持:
  - deepseek-v4-flash       (生产模型,cutoff 2026-04 — 只跑 sanity case)
  - claude-sonnet-4         (可选)
  - gpt-4-turbo             (可选)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI

# Backtest 主线 evaluator (spec § 4.1 决策 1):cutoff < 2024 的 3 LLM cross-check
BACKTEST_EVALUATOR_MODELS: tuple[str, ...] = (
    "gpt-4o-2024-05-13",
    "qwen2.5-72b-instruct",
    "deepseek-v3",
)

# Cross-LLM 矩阵 (spec § 4.8.2):上述 3 个 + 生产 + 可选
CROSS_LLM_MATRIX_MODELS: tuple[str, ...] = (
    *BACKTEST_EVALUATOR_MODELS,
    "deepseek-v4-flash",
    "claude-sonnet-4",
    "gpt-4-turbo",
)

# 公共白名单
EVALUATOR_MODELS: tuple[str, ...] = CROSS_LLM_MATRIX_MODELS

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class EvaluatorClient:
    """已绑定 model id 的 OpenAI-compatible client.

    暴露 chat(prompt, schema) 形态,与 LLMService.chat 类似但不走 dashscope。
    """

    model: str
    api_key: str
    _client: OpenAI

    def chat(self, prompt: str, response_format: dict[str, str] | None = None) -> str:
        """Chat completion via OpenRouter, 返回 content str.

        Args:
            prompt: User-message prompt.
            response_format: 透传 OpenAI response_format (e.g. {"type": "json_object"}).

        Returns:
            response.choices[0].message.content (str, 可能为 "")
        """
        kwargs: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8000,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        r = self._client.chat.completions.create(**kwargs)  # type: ignore[arg-type]
        return r.choices[0].message.content or ""


class LLMSwapper:
    """Evaluator LLM swap orchestrator.

    使用方式:
        swapper = LLMSwapper()  # 从 env 读 OPENROUTER_API_KEY
        client = swapper.get_client("gpt-4o-2024-05-13")
        out = client.chat("Hello")
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            # 允许 init 不报错(Phase 1 部分 test 不需要实际 call),
            # 但 get_client + 真 chat 时会 fail at HTTP layer。
            pass

    def get_client(self, model_id: str) -> EvaluatorClient:
        """返回已绑定 model 的 EvaluatorClient.

        Raises:
            ValueError: model_id 不在白名单。
        """
        if model_id not in EVALUATOR_MODELS:
            raise ValueError(
                f"unknown evaluator model {model_id!r}; "
                f"allowed: {EVALUATOR_MODELS}"
            )
        client = OpenAI(api_key=self.api_key, base_url=OPENROUTER_BASE_URL)
        return EvaluatorClient(model=model_id, api_key=self.api_key, _client=client)
```

- [ ] **Step 4: Run test — verify pass**

```bash
uv run pytest backend/tests/eval/dd_report/test_llm_swapper.py -v
```

Expected: 4 个 test 全 PASS。

- [ ] **Step 5: Mypy strict check**

```bash
cd backend && uv run mypy app eval/dd_report --strict
```

Expected: PASS 无 type error。若 fail,根据具体 error 修正 type annotation(注意:`from openai import OpenAI` 的 stubs 在 pyproject.toml `ignore_missing_imports=true` 全局覆盖,该 import 无需 type:ignore)。

- [ ] **Step 6: Commit**

```bash
git add backend/eval/dd_report/llm_swapper.py backend/tests/eval/dd_report/test_llm_swapper.py
git commit -m "feat(dd-eval): Phase 1 Task 1.2 — LLMSwapper OpenRouter wrapper (3 backtest + 6 cross-LLM model)"
```

---

## Task 1.3:KB chunk schema 加 publish_date 字段(若 spike 缺失)

**注意**:仅当 Task 1.0 Step 2 的 Spike 结论是"publish_date 缺失"时执行本 task。若已存在则 skip,直接到 Task 1.4。

**Files**(Step 2 结论指向的实际文件,以下为示例路径,根据 spike 结果替换):
- Modify: `backend/app/kb/ingest/schemas.py`(或 `backend/app/kb/chunkers/...`)— chunk schema 加 `publish_date` 字段
- Modify: `backend/app/kb/ingest/<ingester>.py`(若有专门的 ingester)— ingest 时提取 publish_date
- Test: `backend/tests/unit/kb/test_chunk_schema_publish_date.py`

- [ ] **Step 1: Write failing test — Chunk schema 含 publish_date**

```python
# backend/tests/unit/kb/test_chunk_schema_publish_date.py
"""KB Chunk schema 加 publish_date 字段 — Phase 1 Task 1.3.

spec § 9 风险 #5
"""
from __future__ import annotations


def test_chunk_schema_has_publish_date_field() -> None:
    """Chunk Pydantic / dataclass schema 必须含 publish_date: date | None 字段."""
    # 根据 Task 1.0 Step 2 spike 结果替换实际 import path:
    from app.kb.ingest.schemas import Chunk  # 示例 path

    fields = Chunk.model_fields if hasattr(Chunk, "model_fields") else Chunk.__dataclass_fields__
    assert "publish_date" in fields, "Chunk schema 必须含 publish_date 字段(time-travel 数据控制需要)"


def test_chunk_publish_date_optional() -> None:
    """publish_date 默认 None — 兼容历史已 ingest 的 chunk."""
    from app.kb.ingest.schemas import Chunk

    chunk = Chunk(
        chunk_id="test-001",
        text="某公司财报数据",
        # 注:此处其他必填字段需要根据实际 schema 补全
    )
    assert chunk.publish_date is None
```

- [ ] **Step 2: Run test — verify failure**

```bash
uv run pytest backend/tests/unit/kb/test_chunk_schema_publish_date.py -v
```

Expected: FAIL — `Chunk` 没有 `publish_date` 字段。

- [ ] **Step 3: Implement — Chunk schema 加 publish_date**

修改 `backend/app/kb/ingest/schemas.py`(以 spike 结果为准),在 `Chunk` 类加:

```python
from datetime import date

# 在 Chunk 类定义内加:
publish_date: date | None = Field(
    default=None,
    description="原文档发布日期 (v1.x DD report backtest 用 — time-travel filter)",
)
```

- [ ] **Step 4: Run test — verify pass**

```bash
uv run pytest backend/tests/unit/kb/test_chunk_schema_publish_date.py -v
```

Expected: PASS.

- [ ] **Step 5: 检查 ingest path 是否需要传 publish_date**

Grep 已有 ingest path:

```bash
grep -rn "Chunk(" backend/app/kb/ --include="*.py" | head -10
```

对每个 `Chunk(...)` 调用,在能拿到 publish_date 的地方(如文档元数据)补上:

```python
chunk = Chunk(
    chunk_id=...,
    text=...,
    publish_date=doc.publish_date if hasattr(doc, "publish_date") else None,  # 新加
)
```

**注意**:历史已 ingest 的 chunk 没有 publish_date,在 backtest 时只能选 `publish_date is None` → 当作"unknown,默认通过"或"unknown,默认拒绝",**决策放 Task 1.4 backtest_adapter 时统一处理**(本 task 先只加字段)。

- [ ] **Step 6: 跑 KB 全套 test 确认无回归**

```bash
uv run pytest backend/tests/unit/kb/ -v --maxfail=3
```

Expected: 全 PASS,无回归。

- [ ] **Step 7: Commit**

```bash
git add backend/app/kb/ingest/schemas.py backend/app/kb/ingest/<ingester>.py backend/tests/unit/kb/test_chunk_schema_publish_date.py
git commit -m "feat(dd-eval): Phase 1 Task 1.3 — KB Chunk schema 加 publish_date 字段 (backtest time-travel 准备)"
```

---

## Task 1.4:Tushare backtest adapter(ann_date filter wrapper)

**Files:**
- Create: `backend/eval/dd_report/tushare_backtest_adapter.py`
- Test: `backend/tests/eval/dd_report/test_tushare_backtest_adapter.py`
- Reference: `backend/app/data/tushare_client.py:202`(已有 `ann_date_start/end`)+ `backend/app/services/tushare_service.py`

- [ ] **Step 1: Write failing test — adapter 注入 cut_off 到所有 ann_date 查询**

```python
# backend/tests/eval/dd_report/test_tushare_backtest_adapter.py
"""TushareBacktestAdapter unit tests — Phase 1 Task 1.4.

spec § 4.5 决策 5 time-travel 数据控制
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


def test_adapter_injects_cut_off_into_income_query() -> None:
    """fetch_income 自动加 ann_date <= cut_off filter."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    inner = MagicMock()
    inner.income.return_value = [{"ts_code": "600519.SH", "ann_date": "20240315"}]

    adapter = TushareBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    adapter.fetch_income(ts_code="600519.SH")

    # 验证 inner.income 被调用时带了 end_date <= cut_off
    inner.income.assert_called_once()
    kwargs = inner.income.call_args.kwargs
    assert "end_date" in kwargs or "ann_date_end" in kwargs
    end = kwargs.get("end_date") or kwargs.get("ann_date_end")
    assert end == "20240630", f"expected cut_off end_date=20240630, got {end}"


def test_adapter_drops_rows_after_cut_off() -> None:
    """即使 inner 返回 ann_date > cut_off 的行(理论上不该,防御性),adapter 也过滤掉."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    inner = MagicMock()
    inner.income.return_value = [
        {"ts_code": "600519.SH", "ann_date": "20240315"},
        {"ts_code": "600519.SH", "ann_date": "20240815"},  # > cut_off, 必须被丢
    ]

    adapter = TushareBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    rows = adapter.fetch_income(ts_code="600519.SH")

    assert len(rows) == 1
    assert rows[0]["ann_date"] == "20240315"


def test_adapter_daily_kline_caps_trade_date() -> None:
    """fetch_daily_kline 也按 cut_off 截止."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    inner = MagicMock()
    inner.daily.return_value = [
        {"trade_date": "20240329", "close": 1700.0},
        {"trade_date": "20240801", "close": 1500.0},  # > cut_off
    ]

    adapter = TushareBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    rows = adapter.fetch_daily_kline(ts_code="600519.SH", start_date="20240101")

    assert len(rows) == 1
    assert rows[0]["trade_date"] == "20240329"


def test_adapter_cut_off_required() -> None:
    """cut_off 必填,不允许 None."""
    from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter

    with pytest.raises(TypeError):
        TushareBacktestAdapter(inner=MagicMock())  # type: ignore[call-arg]
```

- [ ] **Step 2: Run test — verify failure**

```bash
uv run pytest backend/tests/eval/dd_report/test_tushare_backtest_adapter.py -v
```

Expected: FAIL — adapter 不存在。

- [ ] **Step 3: Implement — TushareBacktestAdapter**

```python
# backend/eval/dd_report/tushare_backtest_adapter.py
"""TushareBacktestAdapter — backtest 模式下的 tushare client wrapper.

spec § 4.5 决策 5:time-travel 数据控制 — 任何 tushare 调用都不能返回 ann_date /
trade_date > cut_off 的数据。本 adapter 通过两层防御实现:
  1. 调用 inner client 时强制注入 end_date <= cut_off 参数
  2. 对返回行做二次过滤(防御 inner 不老实)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


class TushareClientProtocol(Protocol):
    """允许真 TushareClient 或 mock 都注入."""

    def income(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def daily(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def balancesheet(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def cashflow(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def anns(self, **kwargs: Any) -> list[dict[str, Any]]: ...


@dataclass
class TushareBacktestAdapter:
    """Wrap a tushare client, 注入 cut_off 限制到所有时间相关接口."""

    inner: TushareClientProtocol
    cut_off: date

    @property
    def _cut_off_str(self) -> str:
        """tushare 接受的日期格式: YYYYMMDD."""
        return self.cut_off.strftime("%Y%m%d")

    def fetch_income(self, ts_code: str, **extra: Any) -> list[dict[str, Any]]:
        """fetch 利润表, 自动加 ann_date end <= cut_off."""
        rows = self.inner.income(
            ts_code=ts_code,
            end_date=self._cut_off_str,
            **extra,
        )
        return self._filter_by_ann_date(rows)

    def fetch_balancesheet(self, ts_code: str, **extra: Any) -> list[dict[str, Any]]:
        rows = self.inner.balancesheet(
            ts_code=ts_code,
            end_date=self._cut_off_str,
            **extra,
        )
        return self._filter_by_ann_date(rows)

    def fetch_cashflow(self, ts_code: str, **extra: Any) -> list[dict[str, Any]]:
        rows = self.inner.cashflow(
            ts_code=ts_code,
            end_date=self._cut_off_str,
            **extra,
        )
        return self._filter_by_ann_date(rows)

    def fetch_daily_kline(
        self, ts_code: str, start_date: str, **extra: Any
    ) -> list[dict[str, Any]]:
        """fetch 日 K, end_date 由 cut_off 限定."""
        rows = self.inner.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=self._cut_off_str,
            **extra,
        )
        return [r for r in rows if r.get("trade_date", "99999999") <= self._cut_off_str]

    def fetch_announcements(self, ts_code: str, **extra: Any) -> list[dict[str, Any]]:
        rows = self.inner.anns(
            ts_code=ts_code,
            end_date=self._cut_off_str,
            **extra,
        )
        return self._filter_by_ann_date(rows)

    # ----- 二次防御过滤 -----

    def _filter_by_ann_date(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """丢掉任何 ann_date > cut_off 的行(防御 inner 不老实)."""
        return [
            r for r in rows
            if r.get("ann_date", "99999999") <= self._cut_off_str
        ]
```

- [ ] **Step 4: Run test — verify pass**

```bash
uv run pytest backend/tests/eval/dd_report/test_tushare_backtest_adapter.py -v
```

Expected: 4 个 test 全 PASS.

- [ ] **Step 5: Mypy strict check**

```bash
cd backend && uv run mypy app eval/dd_report --strict
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/eval/dd_report/tushare_backtest_adapter.py backend/tests/eval/dd_report/test_tushare_backtest_adapter.py
git commit -m "feat(dd-eval): Phase 1 Task 1.4 — TushareBacktestAdapter (cut_off 双层防御 filter)"
```

---

## Task 1.5:KB backtest adapter(publish_date filter wrapper)

**Files:**
- Create: `backend/eval/dd_report/kb_backtest_adapter.py`
- Test: `backend/tests/eval/dd_report/test_kb_backtest_adapter.py`

- [ ] **Step 1: Write failing test — KB adapter 过滤 publish_date > cut_off 的 chunk**

```python
# backend/tests/eval/dd_report/test_kb_backtest_adapter.py
"""KBBacktestAdapter unit tests — Phase 1 Task 1.5.

spec § 4.5 决策 5 time-travel 数据控制(KB chunk 层)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest


@dataclass
class _FakeChunk:
    chunk_id: str
    text: str
    publish_date: date | None


def test_kb_adapter_drops_chunks_after_cut_off() -> None:
    """KB 搜索结果中 publish_date > cut_off 的 chunk 被过滤掉."""
    from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter

    inner = MagicMock()
    inner.search.return_value = [
        _FakeChunk(chunk_id="c1", text="2024 Q1 财报数据", publish_date=date(2024, 3, 30)),
        _FakeChunk(chunk_id="c2", text="2024 Q3 财报数据", publish_date=date(2024, 9, 30)),
    ]

    adapter = KBBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    chunks = adapter.search(query="茅台财报", k=10)

    ids = {c.chunk_id for c in chunks}
    assert ids == {"c1"}
    assert "c2" not in ids


def test_kb_adapter_drops_none_publish_date_in_strict_mode() -> None:
    """strict 模式下 publish_date is None 也被丢(因为无法证伪 leak)."""
    from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter

    inner = MagicMock()
    inner.search.return_value = [
        _FakeChunk(chunk_id="c1", text="带日期", publish_date=date(2024, 3, 30)),
        _FakeChunk(chunk_id="c2", text="无日期", publish_date=None),
    ]

    adapter = KBBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30), strict_no_date=True)
    chunks = adapter.search(query="任意", k=10)
    assert {c.chunk_id for c in chunks} == {"c1"}


def test_kb_adapter_keeps_none_publish_date_in_lenient_mode() -> None:
    """lenient 模式(默认)— publish_date is None 保留(历史 chunk 兼容)."""
    from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter

    inner = MagicMock()
    inner.search.return_value = [
        _FakeChunk(chunk_id="c1", text="带日期", publish_date=date(2024, 3, 30)),
        _FakeChunk(chunk_id="c2", text="无日期", publish_date=None),
    ]

    adapter = KBBacktestAdapter(inner=inner, cut_off=date(2024, 6, 30))
    chunks = adapter.search(query="任意", k=10)
    assert {c.chunk_id for c in chunks} == {"c1", "c2"}


def test_kb_adapter_cut_off_required() -> None:
    """cut_off 必填."""
    from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter

    with pytest.raises(TypeError):
        KBBacktestAdapter(inner=MagicMock())  # type: ignore[call-arg]
```

- [ ] **Step 2: Run test — verify failure**

```bash
uv run pytest backend/tests/eval/dd_report/test_kb_backtest_adapter.py -v
```

Expected: FAIL — adapter 不存在。

- [ ] **Step 3: Implement — KBBacktestAdapter**

```python
# backend/eval/dd_report/kb_backtest_adapter.py
"""KBBacktestAdapter — backtest 模式下的 KB 检索 wrapper.

spec § 4.5 决策 5 time-travel:KB chunk 必须按 publish_date <= cut_off 过滤。
两种模式:
  - lenient (默认):publish_date is None 保留(兼容历史 chunk)
  - strict:publish_date is None 也丢(确保 100% leak-free,但召回降)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


class KBClientProtocol(Protocol):
    """允许任意支持 search 的 KB client 注入."""

    def search(self, query: str, k: int = 10, **kwargs: Any) -> list[Any]: ...


@dataclass
class KBBacktestAdapter:
    """Wrap KB client, 按 publish_date 过滤搜索结果."""

    inner: KBClientProtocol
    cut_off: date
    strict_no_date: bool = False

    def search(self, query: str, k: int = 10, **kwargs: Any) -> list[Any]:
        """搜索 KB, 自动过滤 publish_date > cut_off 的 chunk."""
        # 先放大 k(因为后续要过滤,避免命中数太少)
        raw = self.inner.search(query=query, k=k * 2, **kwargs)
        filtered = [c for c in raw if self._keep(c)]
        return filtered[:k]

    def _keep(self, chunk: Any) -> bool:
        pd = getattr(chunk, "publish_date", None)
        if pd is None:
            return not self.strict_no_date
        return pd <= self.cut_off
```

- [ ] **Step 4: Run test — verify pass**

```bash
uv run pytest backend/tests/eval/dd_report/test_kb_backtest_adapter.py -v
```

Expected: 4 个 test 全 PASS.

- [ ] **Step 5: Mypy strict check**

```bash
cd backend && uv run mypy app eval/dd_report --strict
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/eval/dd_report/kb_backtest_adapter.py backend/tests/eval/dd_report/test_kb_backtest_adapter.py
git commit -m "feat(dd-eval): Phase 1 Task 1.5 — KBBacktestAdapter (publish_date 过滤, lenient/strict 模式)"
```

---

## Task 1.6:BacktestRunner skeleton(orchestrator)

**Files:**
- Create: `backend/eval/dd_report/backtest_runner.py`
- Test: `backend/tests/eval/dd_report/test_backtest_runner.py`

**注**:Phase 1 的 BacktestRunner 是 skeleton — 接受 case + cut_off + LLM model id,负责装配 adapter + swap LLM + 调用 pipeline + emit `backtest_run` row。**不接 metric**(metric 是 Phase 2 接进来,通过 `MetricRegistry`)。

- [ ] **Step 1: Write failing test — BacktestRunner 初始化 + run_one 基础**

```python
# backend/tests/eval/dd_report/test_backtest_runner.py
"""BacktestRunner skeleton tests — Phase 1 Task 1.6.

spec § 4.1 / § 5.1 / § 5.3
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """初始化包含 backtest_runs 表的临时 sqlite."""
    from app.services.eval_recorder import EvalRecorder
    db = tmp_path / "eval.sqlite"
    rec = EvalRecorder(db_path=db)
    rec.init_schema()
    return db


def test_backtest_runner_init(tmp_db: Path) -> None:
    """BacktestRunner 接受必要依赖."""
    from eval.dd_report.backtest_runner import BacktestRunner, BacktestCase
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper(api_key="test")
    runner = BacktestRunner(
        swapper=swapper,
        tushare_inner=MagicMock(),
        kb_inner=MagicMock(),
        db_path=tmp_db,
    )
    assert runner is not None


def test_backtest_runner_writes_run_row(tmp_db: Path) -> None:
    """run_one 完成后 backtest_runs 表写入一行 status='completed'."""
    from eval.dd_report.backtest_runner import BacktestRunner, BacktestCase
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper(api_key="test")
    # Pipeline mock — Phase 1 skeleton: 直接返回 dict 占位
    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = {"target_name": "贵州茅台", "target_ts_code": "600519.SH"}

    runner = BacktestRunner(
        swapper=swapper,
        tushare_inner=MagicMock(),
        kb_inner=MagicMock(),
        db_path=tmp_db,
        pipeline=pipeline_mock,
    )

    case = BacktestCase(
        case_id="bt-600519-20240630",
        ts_code="600519.SH",
        target_name="贵州茅台",
        cut_off_date=date(2024, 6, 30),
    )
    run_id = runner.run_one(
        case=case,
        evaluator_llm="gpt-4o-2024-05-13",
        ablation_variant="V0_baseline",
        git_sha="abc1234",
    )

    assert run_id

    with sqlite3.connect(tmp_db) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)
        ).fetchone()

    assert row is not None
    assert row["status"] == "completed"
    assert row["case_count"] == 1
    assert row["git_sha"] == "abc1234"
    assert row["ablation_variant"] == "V0_baseline"
    assert row["llm_model"] == "gpt-4o-2024-05-13"


def test_backtest_runner_calls_pipeline_with_adapters(tmp_db: Path) -> None:
    """pipeline.run 收到包装好的 tushare_adapter + kb_adapter + evaluator_client."""
    from eval.dd_report.backtest_runner import BacktestRunner, BacktestCase
    from eval.dd_report.llm_swapper import LLMSwapper

    pipeline_mock = MagicMock()
    pipeline_mock.run.return_value = {"target_name": "宁德时代"}

    runner = BacktestRunner(
        swapper=LLMSwapper(api_key="test"),
        tushare_inner=MagicMock(),
        kb_inner=MagicMock(),
        db_path=tmp_db,
        pipeline=pipeline_mock,
    )

    case = BacktestCase(
        case_id="bt-300750-20240630",
        ts_code="300750.SZ",
        target_name="宁德时代",
        cut_off_date=date(2024, 6, 30),
    )
    runner.run_one(case=case, evaluator_llm="qwen2.5-72b-instruct",
                   ablation_variant="V0_baseline", git_sha="abc1234")

    pipeline_mock.run.assert_called_once()
    kwargs = pipeline_mock.run.call_args.kwargs
    assert "tushare_adapter" in kwargs
    assert "kb_adapter" in kwargs
    assert "evaluator_client" in kwargs
    assert kwargs["evaluator_client"].model == "qwen2.5-72b-instruct"
```

- [ ] **Step 2: Run test — verify failure**

```bash
uv run pytest backend/tests/eval/dd_report/test_backtest_runner.py -v
```

Expected: FAIL — `BacktestRunner` 不存在。

- [ ] **Step 3: Implement — BacktestRunner skeleton**

```python
# backend/eval/dd_report/backtest_runner.py
"""BacktestRunner — orchestrator skeleton (Phase 1).

spec § 4.1 / § 5.1 / § 5.3

Phase 1 形态:
  - 接受 BacktestCase + cut_off + evaluator_llm + ablation_variant + git_sha
  - 装配 TushareBacktestAdapter + KBBacktestAdapter + EvaluatorClient
  - 调 pipeline.run(...) 并捕获 output
  - 写一行到 backtest_runs 表

Phase 2 扩展:
  - 接 MetricRegistry, 跑 5 个 metric
  - 写 metric_summary_json 字段
  - 写 eval_results 表(per case)

注:本 Phase 1 skeleton 的 pipeline 是占位接口 (传入任意有 .run(...) 的对象),
真接生产 pipeline 是 Phase 2/3 的事。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter
from eval.dd_report.llm_swapper import LLMSwapper
from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter


@dataclass(frozen=True)
class BacktestCase:
    """单个 backtest case 的元数据."""

    case_id: str
    ts_code: str
    target_name: str
    cut_off_date: date


class PipelineProtocol(Protocol):
    """需 InvestmentDueDiligenceReport 生产 pipeline 实现的 protocol.

    Phase 1: 用 mock 满足即可。
    Phase 2/3: 接生产 ResearchAgent / chat path。
    """

    def run(
        self,
        *,
        target_name: str,
        ts_code: str,
        tushare_adapter: TushareBacktestAdapter,
        kb_adapter: KBBacktestAdapter,
        evaluator_client: Any,
    ) -> dict[str, Any]: ...


class BacktestRunner:
    """Orchestrator: 装配 backtest 数据控制层 + LLM swap + 调 pipeline."""

    def __init__(
        self,
        swapper: LLMSwapper,
        tushare_inner: Any,
        kb_inner: Any,
        db_path: Path,
        pipeline: PipelineProtocol | None = None,
    ) -> None:
        self._swapper = swapper
        self._tushare_inner = tushare_inner
        self._kb_inner = kb_inner
        self._db_path = db_path
        self._pipeline = pipeline

    def run_one(
        self,
        case: BacktestCase,
        evaluator_llm: str,
        ablation_variant: str,
        git_sha: str,
    ) -> str:
        """跑一个 case,写 backtest_runs 表,返回 run_id."""
        run_id = f"bt-run-{uuid4().hex[:12]}"
        created_at = datetime.now(UTC).isoformat()

        tushare_adapter = TushareBacktestAdapter(
            inner=self._tushare_inner, cut_off=case.cut_off_date
        )
        kb_adapter = KBBacktestAdapter(
            inner=self._kb_inner, cut_off=case.cut_off_date
        )
        evaluator_client = self._swapper.get_client(evaluator_llm)

        status = "completed"
        try:
            if self._pipeline is not None:
                _ = self._pipeline.run(
                    target_name=case.target_name,
                    ts_code=case.ts_code,
                    tushare_adapter=tushare_adapter,
                    kb_adapter=kb_adapter,
                    evaluator_client=evaluator_client,
                )
        except Exception:
            status = "failed"
            raise
        finally:
            self._write_run_row(
                run_id=run_id,
                created_at=created_at,
                case_count=1,
                status=status,
                git_sha=git_sha,
                ablation_variant=ablation_variant,
                llm_model=evaluator_llm,
            )

        return run_id

    def _write_run_row(
        self,
        *,
        run_id: str,
        created_at: str,
        case_count: int,
        status: str,
        git_sha: str,
        ablation_variant: str,
        llm_model: str,
    ) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT INTO backtest_runs "
                "(run_id, created_at, case_count, metric_summary_json, status, "
                "git_sha, ablation_variant, llm_model) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (run_id, created_at, case_count, None, status, git_sha, ablation_variant, llm_model),
            )
```

- [ ] **Step 4: Run test — verify pass**

```bash
uv run pytest backend/tests/eval/dd_report/test_backtest_runner.py -v
```

Expected: 3 个 test 全 PASS.

- [ ] **Step 5: Mypy strict check**

```bash
cd backend && uv run mypy app eval/dd_report --strict
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/eval/dd_report/backtest_runner.py backend/tests/eval/dd_report/test_backtest_runner.py
git commit -m "feat(dd-eval): Phase 1 Task 1.6 — BacktestRunner skeleton (装配 adapter + LLM swap + backtest_runs 写入)"
```

---

## Task 1.7:LeakDetector + integration test

**Files:**
- Create: `backend/eval/dd_report/leak_detector.py`
- Test: `backend/tests/eval/dd_report/test_leak_detector.py`

- [ ] **Step 1: Write failing test — LeakDetector 检测 ann_date > cut_off**

```python
# backend/tests/eval/dd_report/test_leak_detector.py
"""LeakDetector unit + integration tests — Phase 1 Task 1.7.

spec § 4.5 决策 5 / § 7.4 backtest 数据 leak detector
"""
from __future__ import annotations

from datetime import date

import pytest


def test_leak_detector_detects_ann_date_after_cutoff() -> None:
    from eval.dd_report.leak_detector import LeakDetector, LeakRecord

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    rows = [
        {"ann_date": "20240501", "source": "tushare:income"},
        {"ann_date": "20240715", "source": "tushare:income"},
    ]
    leaks = detector.scan_tushare_rows(rows)

    assert len(leaks) == 1
    assert leaks[0].source == "tushare:income"
    assert leaks[0].value == "20240715"


def test_leak_detector_detects_chunk_publish_date_after_cutoff() -> None:
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    chunks = [
        {"chunk_id": "c1", "publish_date": date(2024, 3, 30)},
        {"chunk_id": "c2", "publish_date": date(2024, 9, 30)},
    ]
    leaks = detector.scan_chunks(chunks)
    assert len(leaks) == 1
    assert leaks[0].source == "kb:c2"


def test_leak_detector_detects_future_dates_in_prompt_text() -> None:
    """LLM prompt 文本中出现 cut_off 之后的具体日期视为 leak signal."""
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    prompt = "茅台 2024-08-15 公告显示分红比例提升至 80%"
    leaks = detector.scan_prompt_text(prompt, source="agent:writer:prompt")
    assert any("2024-08-15" in leak.value for leak in leaks)


def test_leak_detector_no_false_positive_on_dates_before_cutoff() -> None:
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    prompt = "茅台 2024-03-15 公告显示"
    leaks = detector.scan_prompt_text(prompt, source="agent:writer:prompt")
    assert leaks == []


def test_leak_detector_assertion_helper() -> None:
    """assert_no_leaks 在 leak 存在时 raise AssertionError."""
    from eval.dd_report.leak_detector import LeakDetector, LeakRecord

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    rows = [{"ann_date": "20240715", "source": "tushare:income"}]
    with pytest.raises(AssertionError, match="data leakage detected"):
        detector.assert_no_leaks(detector.scan_tushare_rows(rows))
```

- [ ] **Step 2: Run test — verify failure**

```bash
uv run pytest backend/tests/eval/dd_report/test_leak_detector.py -v
```

Expected: FAIL — `LeakDetector` 不存在。

- [ ] **Step 3: Implement — LeakDetector**

```python
# backend/eval/dd_report/leak_detector.py
"""LeakDetector — backtest 模式下的数据 leakage 检测工具.

spec § 4.5 决策 5 / § 7.4

用法:
    detector = LeakDetector(cut_off=date(2024, 6, 30))
    leaks = detector.scan_tushare_rows(rows)
    leaks += detector.scan_chunks(chunks)
    leaks += detector.scan_prompt_text(prompt_str, source="agent:writer")
    detector.assert_no_leaks(leaks)   # raise AssertionError if any leak
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# 匹配 YYYY-MM-DD / YYYYMMDD / YYYY/MM/DD 三种常见日期格式
_DATE_PATTERN = re.compile(
    r"\b(20\d{2})[-/年.]?(\d{1,2})[-/月.]?(\d{1,2})\b"
)


@dataclass(frozen=True)
class LeakRecord:
    """单条 leakage 证据."""

    source: str  # e.g. "tushare:income" / "kb:c123" / "agent:writer:prompt"
    value: str   # 触发 leak 的具体值,如 "20240715" 或 "2024-08-15"


@dataclass
class LeakDetector:
    """跑 backtest 时审查所有数据来源,识别 cut_off 之后的内容."""

    cut_off: date

    @property
    def _cut_off_compact(self) -> str:
        return self.cut_off.strftime("%Y%m%d")

    def scan_tushare_rows(self, rows: list[dict[str, Any]]) -> list[LeakRecord]:
        """检查 tushare 返回行中 ann_date / trade_date / f_ann_date."""
        out: list[LeakRecord] = []
        for r in rows:
            for field_name in ("ann_date", "trade_date", "f_ann_date", "end_date"):
                v = r.get(field_name)
                if isinstance(v, str) and len(v) == 8 and v > self._cut_off_compact:
                    out.append(LeakRecord(
                        source=f"tushare:{r.get('source', 'unknown')}",
                        value=v,
                    ))
        return out

    def scan_chunks(self, chunks: list[Any]) -> list[LeakRecord]:
        """检查 KB chunk publish_date."""
        out: list[LeakRecord] = []
        for c in chunks:
            cid = c.get("chunk_id") if isinstance(c, dict) else getattr(c, "chunk_id", "?")
            pd = c.get("publish_date") if isinstance(c, dict) else getattr(c, "publish_date", None)
            if isinstance(pd, date) and pd > self.cut_off:
                out.append(LeakRecord(source=f"kb:{cid}", value=pd.isoformat()))
        return out

    def scan_prompt_text(self, text: str, source: str) -> list[LeakRecord]:
        """扫描 prompt / agent 输出文本中出现的日期,识别 cut_off 之后的."""
        out: list[LeakRecord] = []
        for m in _DATE_PATTERN.finditer(text):
            y, mo, d = m.group(1), m.group(2), m.group(3)
            try:
                found = date(int(y), int(mo), int(d))
            except ValueError:
                continue
            if found > self.cut_off:
                out.append(LeakRecord(source=source, value=f"{y}-{int(mo):02d}-{int(d):02d}"))
        return out

    def assert_no_leaks(self, leaks: list[LeakRecord]) -> None:
        if leaks:
            details = "; ".join(f"{l.source}:{l.value}" for l in leaks[:10])
            raise AssertionError(
                f"data leakage detected ({len(leaks)} record(s)): {details}"
            )
```

- [ ] **Step 4: Run test — verify pass**

```bash
uv run pytest backend/tests/eval/dd_report/test_leak_detector.py -v
```

Expected: 5 个 test 全 PASS.

- [ ] **Step 5: 加 integration smoke test — BacktestRunner + LeakDetector 联合**

```python
# 加到 backend/tests/eval/dd_report/test_backtest_runner.py 末尾:
def test_backtest_run_passes_leak_detector_with_clean_data(tmp_db: Path) -> None:
    """跑一个 case, 用 LeakDetector 审查 tushare/kb 返回行无 leak."""
    from datetime import date
    from unittest.mock import MagicMock
    from eval.dd_report.backtest_runner import BacktestRunner, BacktestCase
    from eval.dd_report.leak_detector import LeakDetector
    from eval.dd_report.llm_swapper import LLMSwapper

    # 干净的 tushare: 所有 ann_date <= cut_off
    tushare_inner = MagicMock()
    tushare_inner.income.return_value = [{"ann_date": "20240315", "ts_code": "600519.SH"}]
    tushare_inner.daily.return_value = [{"trade_date": "20240329", "close": 1700.0}]

    # 干净的 KB
    kb_inner = MagicMock()
    kb_inner.search.return_value = []

    pipeline = MagicMock()
    pipeline.run.return_value = {"target_name": "贵州茅台"}

    runner = BacktestRunner(
        swapper=LLMSwapper(api_key="test"),
        tushare_inner=tushare_inner,
        kb_inner=kb_inner,
        db_path=tmp_db,
        pipeline=pipeline,
    )

    case = BacktestCase(
        case_id="bt-smoke-001",
        ts_code="600519.SH",
        target_name="贵州茅台",
        cut_off_date=date(2024, 6, 30),
    )
    runner.run_one(case=case, evaluator_llm="gpt-4o-2024-05-13",
                   ablation_variant="V0_baseline", git_sha="smoke")

    # 用 detector 审查 mock 返回内容
    detector = LeakDetector(cut_off=date(2024, 6, 30))
    income_rows = tushare_inner.income.return_value
    daily_rows = tushare_inner.daily.return_value

    leaks = detector.scan_tushare_rows(income_rows) + detector.scan_tushare_rows(daily_rows)
    detector.assert_no_leaks(leaks)  # 不 raise = pass


def test_backtest_run_fails_leak_detector_with_polluted_data(tmp_db: Path) -> None:
    """如果 tushare 返回带 leak 的数据, detector 必须 catch."""
    import pytest
    from datetime import date
    from eval.dd_report.leak_detector import LeakDetector

    detector = LeakDetector(cut_off=date(2024, 6, 30))
    polluted = [{"ann_date": "20240715", "ts_code": "600519.SH"}]
    leaks = detector.scan_tushare_rows(polluted)
    with pytest.raises(AssertionError, match="data leakage detected"):
        detector.assert_no_leaks(leaks)
```

- [ ] **Step 6: Run integration test — verify pass**

```bash
uv run pytest backend/tests/eval/dd_report/test_backtest_runner.py -v
```

Expected: 5 个 test 全 PASS(原 3 + 新 2).

- [ ] **Step 7: Commit**

```bash
git add backend/eval/dd_report/leak_detector.py backend/tests/eval/dd_report/test_leak_detector.py backend/tests/eval/dd_report/test_backtest_runner.py
git commit -m "feat(dd-eval): Phase 1 Task 1.7 — LeakDetector + BacktestRunner integration smoke test"
```

---

## Task 1.8:Golden case 数据采集(32 backtest + 8 sanity)

**Files:**
- Create: `backend/scripts/build_dd_backtest_cases.py` — 一次性 CLI
- Create: `backend/eval/dd_report/golden/backtest_cases.jsonl` — 由 CLI 产出
- Create: `backend/eval/dd_report/golden/ground_truth_loader.py` — 后续在 Phase 2 M4 prediction metric 用
- Test: `backend/tests/eval/dd_report/test_golden_cases_smoke.py`

**注**:本 task 只做"采集 + 校验"。真的跑 ground truth(后续 1/3/6/12 月股价 + 真实公告)留 Phase 2 M4 实现时。

- [ ] **Step 1: 定义 8 公司 × 4 时点 case 列表**

8 公司选股(spec § 4.4):

```
1. 贵州茅台   600519.SH   大白马
2. 宁德时代   300750.SZ   成长龙头
3. 中国神华   601088.SH   周期股
4. 海航控股   600221.SH   困境反转
5. 康美药业   600518.SH   暴雷退市样本
6. 招商银行   600036.SH   银行金融
7. 恒瑞医药   600276.SH   医药
8. 海康威视   002415.SZ   科技
```

4 backtest 时点:`2024-06-30 / 2024-12-31 / 2025-06-30 / 2025-12-31`
1 sanity 时点:`2026-04-30`(生产模型 cutoff 边界)

总 case 数:
- backtest: 8 × 4 = 32
- sanity: 8 × 1 = 8
- 总 40 case

- [ ] **Step 2: Write failing test — golden case file 存在且行数对**

```python
# backend/tests/eval/dd_report/test_golden_cases_smoke.py
"""Golden case file smoke test — Phase 1 Task 1.8."""
from __future__ import annotations

import json
from pathlib import Path


GOLDEN_PATH = Path(__file__).parents[3] / "eval" / "dd_report" / "golden" / "backtest_cases.jsonl"


def test_golden_cases_file_exists() -> None:
    assert GOLDEN_PATH.exists(), f"missing {GOLDEN_PATH}"


def test_golden_cases_count_32_backtest_plus_8_sanity() -> None:
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    backtest = [c for c in cases if c["case_type"] == "backtest"]
    sanity = [c for c in cases if c["case_type"] == "sanity"]
    assert len(backtest) == 32, f"expected 32 backtest case, got {len(backtest)}"
    assert len(sanity) == 8, f"expected 8 sanity case, got {len(sanity)}"


def test_golden_cases_8_companies_each() -> None:
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = {
        "600519.SH", "300750.SZ", "601088.SH", "600221.SH",
        "600518.SH", "600036.SH", "600276.SH", "002415.SZ",
    }
    assert {c["ts_code"] for c in cases} == expected


def test_golden_cases_4_backtest_timepoints() -> None:
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    backtest_cuts = {c["cut_off_date"] for c in cases if c["case_type"] == "backtest"}
    assert backtest_cuts == {"2024-06-30", "2024-12-31", "2025-06-30", "2025-12-31"}


def test_golden_cases_sanity_cut_off_2026_04_30() -> None:
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    sanity_cuts = {c["cut_off_date"] for c in cases if c["case_type"] == "sanity"}
    assert sanity_cuts == {"2026-04-30"}


def test_golden_case_fields_complete() -> None:
    """每 case 必含 case_id / ts_code / target_name / cut_off_date / case_type / company_type."""
    cases = [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    required = {"case_id", "ts_code", "target_name", "cut_off_date", "case_type", "company_type"}
    for c in cases:
        assert required.issubset(c.keys()), f"case {c.get('case_id')} missing {required - c.keys()}"
```

- [ ] **Step 3: Run test — verify failure**

```bash
uv run pytest backend/tests/eval/dd_report/test_golden_cases_smoke.py -v
```

Expected: FAIL — golden file 不存在。

- [ ] **Step 4: 写 CLI 生成 backtest_cases.jsonl**

```python
# backend/scripts/build_dd_backtest_cases.py
"""Build golden case JSONL for DD report backtest.

spec § 4.4 决策 4 — 8 公司 × 4 backtest 时点 + 8 sanity case

用法:
    uv run python -m backend.scripts.build_dd_backtest_cases
    输出: backend/eval/dd_report/golden/backtest_cases.jsonl  (40 行)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path


# 8 公司 (spec § 4.4)
COMPANIES: list[dict[str, str]] = [
    {"ts_code": "600519.SH", "name": "贵州茅台", "type": "blue_chip"},
    {"ts_code": "300750.SZ", "name": "宁德时代", "type": "growth_leader"},
    {"ts_code": "601088.SH", "name": "中国神华", "type": "cyclical"},
    {"ts_code": "600221.SH", "name": "海航控股", "type": "distressed_turnaround"},
    {"ts_code": "600518.SH", "name": "康美药业", "type": "fraud_delisted"},
    {"ts_code": "600036.SH", "name": "招商银行", "type": "bank"},
    {"ts_code": "600276.SH", "name": "恒瑞医药", "type": "pharma"},
    {"ts_code": "002415.SZ", "name": "海康威视", "type": "tech_sanctioned"},
]

BACKTEST_CUT_OFFS: list[date] = [
    date(2024, 6, 30),
    date(2024, 12, 31),
    date(2025, 6, 30),
    date(2025, 12, 31),
]

SANITY_CUT_OFF: date = date(2026, 4, 30)


def build_cases() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    # 32 backtest case
    for co in BACKTEST_CUT_OFFS:
        for c in COMPANIES:
            out.append({
                "case_id": f"bt-{c['ts_code']}-{co.strftime('%Y%m%d')}",
                "ts_code": c["ts_code"],
                "target_name": c["name"],
                "cut_off_date": co.isoformat(),
                "case_type": "backtest",
                "company_type": c["type"],
            })

    # 8 sanity case
    for c in COMPANIES:
        out.append({
            "case_id": f"sn-{c['ts_code']}-{SANITY_CUT_OFF.strftime('%Y%m%d')}",
            "ts_code": c["ts_code"],
            "target_name": c["name"],
            "cut_off_date": SANITY_CUT_OFF.isoformat(),
            "case_type": "sanity",
            "company_type": c["type"],
        })

    return out


def main() -> None:
    out_path = Path(__file__).parents[1] / "eval" / "dd_report" / "golden" / "backtest_cases.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cases = build_cases()
    with out_path.open("w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"wrote {len(cases)} cases to {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 跑 CLI 生成 file**

```bash
uv run python -m backend.scripts.build_dd_backtest_cases
```

Expected: 输出 `wrote 40 cases to .../backtest_cases.jsonl`.

- [ ] **Step 6: Run test — verify pass**

```bash
uv run pytest backend/tests/eval/dd_report/test_golden_cases_smoke.py -v
```

Expected: 6 个 test 全 PASS.

- [ ] **Step 7: 加 ground_truth_loader.py 占位(Phase 2 M4 用)**

```python
# backend/eval/dd_report/golden/ground_truth_loader.py
"""Ground truth loader for backtest case prediction validation.

Phase 1: 仅占位 + 接口签名 (真实现 Phase 2 M4 prediction metric).
Phase 2 M4: 实现 fetch_post_cut_off_kline / fetch_post_cut_off_anns 等方法.

spec § 4.4 / § 5.1
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol


class TushareReadOnlyProtocol(Protocol):
    """ground truth 用真 tushare(不限 cut_off,因为是事后查)."""

    def daily(self, **kwargs: Any) -> list[dict[str, Any]]: ...
    def anns(self, **kwargs: Any) -> list[dict[str, Any]]: ...


@dataclass
class GroundTruthLoader:
    """加载 backtest case cut_off 之后的真实数据用于 M4 验证.

    Phase 1: 仅 stub, Phase 2 M4 实现具体方法.
    """

    inner: TushareReadOnlyProtocol

    def fetch_post_cut_off_kline(
        self,
        ts_code: str,
        cut_off: date,
        horizon_days: int = 90,
    ) -> list[dict[str, Any]]:
        """Phase 2 M4: 取 cut_off 之后 horizon_days 天的日 K."""
        raise NotImplementedError("Phase 2 M4 prediction metric 实施")

    def fetch_post_cut_off_anns(
        self,
        ts_code: str,
        cut_off: date,
        horizon_days: int = 90,
    ) -> list[dict[str, Any]]:
        """Phase 2 M4: 取 cut_off 之后 horizon_days 天的公告."""
        raise NotImplementedError("Phase 2 M4 prediction metric 实施")
```

- [ ] **Step 8: Commit**

```bash
git add backend/scripts/build_dd_backtest_cases.py \
        backend/eval/dd_report/golden/backtest_cases.jsonl \
        backend/eval/dd_report/golden/ground_truth_loader.py \
        backend/tests/eval/dd_report/test_golden_cases_smoke.py
git commit -m "feat(dd-eval): Phase 1 Task 1.8 — 32 backtest + 8 sanity golden case 数据 + ground truth loader stub"
```

---

## Task 1.9:Phase 1 收尾 — conftest + 全套测试 + sediment

**Files:**
- Create: `backend/tests/eval/dd_report/conftest.py` — fixture(沿用 b1_differential pattern)
- Modify: `pyproject.toml`(若需要,确认 `eval` 在 pytest paths)
- Create: `docs/claude-context/dd-report-eval-phase-1-landed.md` — sediment 卡片

- [ ] **Step 1: 创建 conftest.py(env + proxy)**

```python
# backend/tests/eval/dd_report/conftest.py
"""Conftest for dd_report Phase 1 tests — 沿用 b1_differential pattern.

env 加载 + proxy unset(避免 vcr / openai client 抓 proxy 干扰).
"""
from __future__ import annotations

from pathlib import Path

import pytest

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).parents[3] / ".env")
except ImportError:
    pass


@pytest.fixture(autouse=True)
def _unset_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip proxy env vars — 沿用 b1_differential conftest."""
    for var in ("all_proxy", "ALL_PROXY", "https_proxy", "HTTPS_PROXY",
                "http_proxy", "HTTP_PROXY"):
        monkeypatch.delenv(var, raising=False)
```

- [ ] **Step 2: 跑 Phase 1 全套测试**

```bash
uv run pytest backend/tests/eval/dd_report/ -v
```

Expected: 全 PASS,task 1.2 / 1.4 / 1.5 / 1.6 / 1.7 / 1.8 的所有 test 都过。

- [ ] **Step 3: 跑全 backend 测试集确认无回归**

```bash
uv run pytest backend/tests/ --maxfail=5
```

Expected: 全 PASS,无回归。若有 failure 修复后再 commit。

- [ ] **Step 4: mypy 全 backend strict**

```bash
cd backend && uv run mypy app eval --strict
```

Expected: PASS.

- [ ] **Step 5: ruff format + lint**

```bash
cd backend && uv run ruff format eval/dd_report tests/eval/dd_report scripts/build_dd_backtest_cases.py
cd backend && uv run ruff check eval/dd_report tests/eval/dd_report scripts/build_dd_backtest_cases.py
```

Expected: 全过。

- [ ] **Step 6: 写 sediment 卡片**

```markdown
<!-- docs/claude-context/dd-report-eval-phase-1-landed.md -->
---
name: DD report eval Phase 1 (backtest infra) landed
description: v1.x DD report quality eval Phase 1 — backtest infra ship 完, 40 golden case + DB schema + LLMSwapper + 数据 leak detector
type: project
---

## v1.x DD report eval Phase 1 ship 完(2026-05-?)

### 做了什么

**spec**: `docs/superpowers/specs/2026-05-17-dd-report-quality-eval-design.md` v1.1
**plan**: `docs/superpowers/plans/2026-05-17-dd-report-eval-phase-1-backtest-infra.md`

8 个 task,~1.5 周 wall time:

- T1.0 模块骨架 + KB schema spike + .env OPENROUTER_API_KEY
- T1.1 DB schema(eval_results 加 4 字段 + backtest_runs 新表 含 git_sha/ablation_variant/llm_model)
- T1.2 LLMSwapper OpenRouter wrapper(3 backtest evaluator + 6 cross-LLM model 白名单)
- T1.3 KB Chunk schema 加 publish_date(若 spike 缺失)
- T1.4 TushareBacktestAdapter(双层 cut_off 防御 — 注入参数 + 二次过滤)
- T1.5 KBBacktestAdapter(lenient/strict 模式过滤 publish_date)
- T1.6 BacktestRunner skeleton(装配 adapter + LLM swap + backtest_runs 写入)
- T1.7 LeakDetector + integration smoke test
- T1.8 32 backtest + 8 sanity golden case 数据 + ground_truth_loader stub

### Why(技术亮点)

- **Pipeline-as-SUT 范式落地**:BacktestRunner 装配 adapter + EvaluatorClient 给 pipeline,pipeline 接什么就跑什么,不耦合生产 LLM
- **双层 leak 防御**:tushare adapter 注入 end_date 参数 + 收到行二次 ann_date 过滤
- **lenient/strict 二档**:KB adapter 允许历史无 publish_date chunk 兼容,strict 模式可严格 leak-free 但召回降

### How to apply

- Phase 2 起,所有 metric 走 BacktestRunner pipeline,通过 adapter 拿数据
- 新 ablation 变体走 `ablation_variant` 字段标记,同一 case 跑多变体写多 backtest_runs 行
- cross-LLM 矩阵走 `llm_model` 字段标记,sanity case 跑生产模型
- 任何怀疑 leak 时,用 `LeakDetector.scan_tushare_rows / scan_chunks / scan_prompt_text` 三层扫
```

修改 `docs/claude-context/README.md` 索引(若有的话)加这个卡片链接。

- [ ] **Step 7: 收尾 commit + push**

```bash
git add backend/tests/eval/dd_report/conftest.py \
        docs/claude-context/dd-report-eval-phase-1-landed.md
git commit -m "feat(dd-eval): Phase 1 Task 1.9 — conftest + sediment 卡片, Phase 1 ship 完"
```

---

## Phase 1 完成验收清单

- [ ] `backend/eval/dd_report/` 目录骨架 + 7 个核心 py 文件(`__init__` / `llm_swapper` / `tushare_backtest_adapter` / `kb_backtest_adapter` / `backtest_runner` / `leak_detector` / `golden/ground_truth_loader`)
- [ ] `backend/eval/dd_report/golden/backtest_cases.jsonl` 40 行(32 backtest + 8 sanity)
- [ ] `backend/scripts/build_dd_backtest_cases.py` CLI 可重跑
- [ ] `backend/tests/eval/dd_report/` 6 个 test 文件(`test_llm_swapper` / `test_tushare_backtest_adapter` / `test_kb_backtest_adapter` / `test_backtest_runner` / `test_leak_detector` / `test_golden_cases_smoke`)+ `conftest.py`
- [ ] DB schema:`eval_results` 4 新列 + `backtest_runs` 表 8 字段
- [ ] KB Chunk schema 加 `publish_date` 字段(若 Task 1.0 spike 标记缺失)
- [ ] `backend/.env.example` 含 `OPENROUTER_API_KEY` 模板
- [ ] 全 backend 测试集 PASS,mypy strict PASS,ruff PASS
- [ ] sediment 卡片 `docs/claude-context/dd-report-eval-phase-1-landed.md`
- [ ] git log:9 个 task commit 全有,commit message 带 `Phase 1 Task X.Y`

---

## 与 Phase 2-5 的衔接

**Phase 1 不接 metric**(spec § 4.2 5 个 metric)— 这是 Phase 2 起的事。Phase 1 BacktestRunner 的 `pipeline` 参数是 placeholder,Phase 2 才真接生产 pipeline。

**Phase 2 起需要的依赖**(本 plan 已交付):
- `BacktestRunner.run_one()` 签名稳定(case + evaluator_llm + ablation_variant + git_sha)
- `LLMSwapper.get_client(model_id)` 返回 `EvaluatorClient`
- TushareBacktestAdapter + KBBacktestAdapter 已封装 cut_off filter
- `backtest_runs` 表的 `metric_summary_json` 字段已留(Phase 2 写入)
- `eval_results.case_type` 已支持 backtest / sanity / financebench / cross_llm
- `GroundTruthLoader` stub 已留接口(Phase 2 M4 实现)

**Phase 2 spec 起草前必做的 review**:
- Phase 1 跑出来后的真实情况(LLMSwapper API 是否好用 / KB adapter 召回是否降太多 / golden case 数据采集中 tushare 实际可用性)
- 据此调整 Phase 2 plan scope
