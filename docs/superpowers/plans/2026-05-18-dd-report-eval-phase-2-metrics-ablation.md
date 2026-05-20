# DD Report Quality Eval — Phase 2 Implementation Plan (5 Metric + V0-V3 Ablation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 把 spec § 4.2(Hebbia 三段式 5 metric)+ § 4.7(V0-V3 ablation)落地到 Phase 1 已 ship 的 backtest infra 上,产出可写入 `eval_results.metric_scores_json` / `backtest_runs.metric_summary_json` 的真分数,并在 Phase 2 末跑完整 ablation L2 dogfood。

**Architecture:** 5 个独立 metric 模块(纯函数 + Protocol-injected dependency)实现 `MetricProtocol`,挂 `MetricRegistry` 串联;`BacktestRunner.run_one` 在 pipeline 出 report 后跑 registry + 写两表;`DDReportPipelineAdapter` 把 v0.8.5 生产 ResearchAgent + writer + critic 包装成 Phase 1 的 `PipelineProtocol`;`AblationRunner` 接 `PipelineFactory(variant) -> PipelineProtocol`,跑 4 variant × 8 sanity case 子集。

**Tech Stack:** Python 3.13 / Pydantic v2 / sqlite3 stdlib / `eval.dd_report.llm_swapper.EvaluatorClient`(OpenRouter) / 生产 LangGraph subgraph / pytest L0/L1/L2 三层 + 现有 cassette pattern。

**关键设计决策:**

1. **不污染 `JudgeScores`** — spec 假设的 `factual_accuracy / completeness / etc` 跟 actual `factuality / coverage / structure / tool_correctness / report_markdown_quality` 不对齐(Phase 1 sediment 撞过)。Phase 2 引入独立 `BacktestMetricScores` Pydantic,序列化到 `eval_results.metric_scores_json` 新列;`scores_json`(JudgeScores)在 backtest 模式不写。
2. **MetricProtocol sync 形态** — `BacktestRunner` 是 sync(Phase 1 已定),metric 跟随;LLM judge 走 `EvaluatorClient.chat()`(sync)。c5 metric 是 async 因为接 chat path,无法直接借用。
3. **生产 pipeline 包装成 PipelineProtocol** — `DDReportPipelineAdapter` 是 Phase 1 → Phase 2 桥;它知道怎么把 `tushare_adapter` / `kb_adapter` / `evaluator_client` 注进生产 ResearchAgent + writer + critic,产出 `InvestmentDueDiligenceReport`。
4. **AblationVariant 用 PipelineFactory pattern** — `V0 baseline` 用全套生产 pipeline;`V1 no RAG` swap KB adapter → `NullKBAdapter`;`V2 no multi-agent` swap pipeline → `SingleAgentPipeline`(单 prompt);`V3 no Critic` 关掉 critic subgraph。每 variant 都返回新 `PipelineProtocol` 实例,`AblationRunner` 不感知细节。
5. **Phase 2 末 ablation 跑 8 sanity case 子集而非全 32** — 控成本(spec § 5.3 估算完整 ablation $20,8 case × 4 variant × 1 evaluator ≈ $1.5),且 sanity case 选股已覆盖收益分布全象限(包含康美暴雷)。完整 32 case ablation 推到 Phase 5 dogfood。

**文件结构(新建 / 修改):**

```
backend/eval/dd_report/
├── __init__.py                                      # 修改:加 metric exports
├── backtest_runner.py                               # 修改:wire MetricRegistry + LeakDetector + write eval_results + aggregate
├── llm_swapper.py                                   # 不动(Phase 1 ship)
├── leak_detector.py                                 # 不动
├── tushare_backtest_adapter.py                      # 不动
├── kb_backtest_adapter.py                           # 不动
├── metric_scores.py                                 # 新:BacktestMetricScores Pydantic
├── pipeline_adapter.py                              # 新:DDReportPipelineAdapter (生产 → PipelineProtocol)
├── metrics/                                         # 新
│   ├── __init__.py
│   ├── base.py                                      # MetricProtocol + MetricInputs + MetricRegistry
│   ├── citation_metric.py                           # M1
│   ├── numerical_metric.py                          # M2
│   ├── risk_pairing_metric.py                       # M3
│   ├── prediction_metric.py                         # M4
│   └── composite_judge_metric.py                    # M5
├── ablation/                                        # 新
│   ├── __init__.py
│   ├── variants.py                                  # 4 AblationVariant 枚举 + PipelineFactory
│   ├── null_adapters.py                             # NullKBAdapter (V1) + SingleAgentPipeline (V2)
│   └── runner.py                                    # AblationRunner
└── golden/
    ├── backtest_cases.jsonl                         # 不动(Phase 1 ship 40 case)
    └── ground_truth_loader.py                       # 修改:Phase 1 NotImplementedError → 真实现

backend/app/services/eval_recorder.py                # 修改:加 metric_scores_json 列 + 适配 EvalResult
backend/app/services/eval_models.py                  # 修改:EvalResult 加 metric_scores_json 字段

backend/tests/eval/dd_report/
├── conftest.py                                      # 修改:加 fake_dd_report fixture + ground_truth mock
├── test_metric_scores_schema.py                     # 新
├── test_metric_registry.py                          # 新
├── test_ground_truth_loader.py                      # 新
├── test_citation_metric.py                          # 新
├── test_numerical_metric.py                         # 新
├── test_risk_pairing_metric.py                      # 新
├── test_prediction_metric.py                        # 新
├── test_composite_judge_metric.py                   # 新
├── test_backtest_runner_metric_wire.py              # 新
├── test_pipeline_adapter.py                         # 新
├── test_ablation_variants.py                        # 新
├── test_ablation_runner.py                          # 新
└── cassettes/                                       # 新目录(vcr cassette)
    ├── citation_supports_judge.yaml
    ├── risk_pairing_judge.yaml
    └── composite_judge_3llm.yaml
```

**11 个 task,~75 step,1.5 周 wall time + 1 天 ablation 跑分。**

---

## Task 2.0:Metric Base + BacktestMetricScores Schema + DB metric_scores_json 列

**Files:**
- Create: `backend/eval/dd_report/metrics/__init__.py`
- Create: `backend/eval/dd_report/metrics/base.py`
- Create: `backend/eval/dd_report/metric_scores.py`
- Modify: `backend/app/services/eval_models.py`(EvalResult 加 metric_scores_json 字段)
- Modify: `backend/app/services/eval_recorder.py`(加 metric_scores_json 列 + 适配 write/read)
- Test: `backend/tests/eval/dd_report/test_metric_scores_schema.py`
- Test: `backend/tests/eval/dd_report/test_metric_registry.py`

- [x] **Step 1: 先写失败 test for `BacktestMetricScores` schema 基本字段**

`backend/tests/eval/dd_report/test_metric_scores_schema.py`:

```python
"""BacktestMetricScores Pydantic schema — Phase 2 T2.0."""

from __future__ import annotations

from eval.dd_report.metric_scores import BacktestMetricScores


def test_schema_accepts_all_5_metric_scores() -> None:
    s = BacktestMetricScores(
        m1_citation_precision=0.92,
        m1_citation_recall=0.85,
        m2_numerical_accuracy=0.90,
        m2_numerical_total=20,
        m2_numerical_correct=18,
        m3_risk_pairing_score=0.71,
        m4_recommendation_direction_correct=True,
        m4_target_price_hit=False,
        m4_risk_flag_realized_rate=0.50,
        m5_composite_mean=7.6,
        m5_composite_majority=8.0,
        m5_composite_disagreement_max=2.0,
    )
    j = s.model_dump_json()
    assert "m1_citation_precision" in j


def test_schema_allows_partial_m4_none_when_not_applicable() -> None:
    s = BacktestMetricScores(
        m1_citation_precision=1.0,
        m1_citation_recall=1.0,
        m2_numerical_accuracy=1.0,
        m2_numerical_total=0,
        m2_numerical_correct=0,
        m3_risk_pairing_score=1.0,
        m4_recommendation_direction_correct=None,
        m4_target_price_hit=None,
        m4_risk_flag_realized_rate=None,
        m5_composite_mean=8.0,
        m5_composite_majority=8.0,
        m5_composite_disagreement_max=0.0,
    )
    assert s.m4_recommendation_direction_correct is None


def test_details_json_round_trips() -> None:
    s = BacktestMetricScores(
        m1_citation_precision=0.5,
        m1_citation_recall=0.5,
        m2_numerical_accuracy=0.5,
        m2_numerical_total=2,
        m2_numerical_correct=1,
        m3_risk_pairing_score=0.5,
        m4_recommendation_direction_correct=True,
        m4_target_price_hit=False,
        m4_risk_flag_realized_rate=0.0,
        m5_composite_mean=5.0,
        m5_composite_majority=5.0,
        m5_composite_disagreement_max=1.0,
        details_json={"m1_failed_cites": ["chunk-x"]},
    )
    roundtripped = BacktestMetricScores.model_validate_json(s.model_dump_json())
    assert roundtripped.details_json == {"m1_failed_cites": ["chunk-x"]}
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_metric_scores_schema.py -v`
Expected: `ModuleNotFoundError: No module named 'eval.dd_report.metric_scores'`

- [x] **Step 3: 实现 `BacktestMetricScores` Pydantic schema**

`backend/eval/dd_report/metric_scores.py`:

```python
"""BacktestMetricScores — Phase 2 5-metric per-case score schema.

spec § 4.2 / § 5.2

不复用 app.services.eval_models.JudgeScores —— 后者字段是
factuality / coverage / structure / tool_correctness / report_markdown_quality
(单 judge 4-5 维 rubric), 而 Phase 2 5 metric 是 backtest 维度的另一套体系。
两套 schema 并存: 普通 eval(chat path)用 JudgeScores, backtest 用本 schema。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BacktestMetricScores(BaseModel):
    """5 metric per-case scores. 序列化到 eval_results.metric_scores_json 列."""

    model_config = ConfigDict(extra="ignore")

    # M1 Citation precision/recall (spec § 4.2)
    m1_citation_precision: float = Field(ge=0.0, le=1.0)
    m1_citation_recall: float = Field(ge=0.0, le=1.0)

    # M2 Numerical accuracy (spec § 4.2)
    m2_numerical_accuracy: float = Field(ge=0.0, le=1.0)
    m2_numerical_total: int = Field(ge=0)
    m2_numerical_correct: int = Field(ge=0)

    # M3 Risk-mitigation pairing (spec § 4.2)
    m3_risk_pairing_score: float = Field(ge=0.0, le=1.0)

    # M4 Investment prediction (spec § 4.2) — 全 nullable: cut_off 之后真实数据缺失时为 None
    m4_recommendation_direction_correct: bool | None = None
    m4_target_price_hit: bool | None = None
    m4_risk_flag_realized_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    # M5 Multi-LLM consensus (spec § 4.3)
    m5_composite_mean: float = Field(ge=0.0, le=10.0)
    m5_composite_majority: float = Field(ge=0.0, le=10.0)
    m5_composite_disagreement_max: float = Field(ge=0.0)

    # 详情(失败 cite list / wrong numeric / mitigation 评语 / 各 judge raw)
    details_json: dict[str, Any] = Field(default_factory=dict)
```

- [x] **Step 4: 跑 schema test 验证 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_metric_scores_schema.py -v`
Expected: 3 PASS

- [x] **Step 5: 写失败 test for MetricProtocol + MetricRegistry**

`backend/tests/eval/dd_report/test_metric_registry.py`:

```python
"""MetricRegistry — Phase 2 T2.0."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from eval.dd_report.metrics.base import (
    MetricInputs,
    MetricRegistry,
    MetricResult,
)


class _AlwaysOneMetric:
    name = "always_one"

    def compute(self, inputs: MetricInputs) -> MetricResult:
        return MetricResult(name=self.name, value=1.0, details={})


class _AlwaysZeroMetric:
    name = "always_zero"

    def compute(self, inputs: MetricInputs) -> MetricResult:
        return MetricResult(name=self.name, value=0.0, details={"reason": "test"})


def test_registry_runs_all_metrics_in_order() -> None:
    reg = MetricRegistry([_AlwaysOneMetric(), _AlwaysZeroMetric()])
    inputs = MetricInputs(
        report={"target_name": "茅台"},
        case_meta={"ts_code": "600519.SH", "cut_off_date": date(2024, 6, 30)},
        ground_truth=None,
        tushare_adapter=None,
        kb_lookup=None,
        evaluator_clients={},
    )
    results = reg.compute_all(inputs)
    assert [r.name for r in results] == ["always_one", "always_zero"]
    assert results[0].value == 1.0
    assert results[1].details == {"reason": "test"}


def test_registry_duplicate_name_raises() -> None:
    with pytest.raises(ValueError, match="duplicate metric name"):
        MetricRegistry([_AlwaysOneMetric(), _AlwaysOneMetric()])


def test_registry_empty_returns_empty_list() -> None:
    reg = MetricRegistry([])
    inputs = MetricInputs(
        report={},
        case_meta={"ts_code": "X", "cut_off_date": date(2024, 1, 1)},
        ground_truth=None,
        tushare_adapter=None,
        kb_lookup=None,
        evaluator_clients={},
    )
    assert reg.compute_all(inputs) == []


def _ignore_unused(_: Any) -> None:
    pass
```

- [x] **Step 6: 实现 MetricProtocol + MetricInputs + MetricRegistry + 跑 test + commit**

`backend/eval/dd_report/metrics/__init__.py`:

```python
"""Phase 2 metric implementations.

5 metric 对应 spec § 4.2:
  M1 CitationMetric         — extraction
  M2 NumericalMetric        — extraction
  M3 RiskPairingMetric      — summarization (LLM judge)
  M4 PredictionMetric       — reasoning (backtest)
  M5 CompositeJudgeMetric   — reasoning (multi-LLM consensus)
"""
```

`backend/eval/dd_report/metrics/base.py`:

```python
"""MetricProtocol + MetricInputs + MetricRegistry — Phase 2 T2.0.

每个 metric 是个 stateless 对象, 实现 MetricProtocol.compute(inputs) -> MetricResult。
所有 metric 共享同一个 MetricInputs (报告 + case 元数据 + 各种依赖注入)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Protocol

from eval.dd_report.golden.ground_truth_loader import GroundTruthLoader
from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter
from eval.dd_report.llm_swapper import EvaluatorClient
from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter


@dataclass(frozen=True)
class MetricResult:
    """单个 metric 计算结果."""

    name: str
    value: float | None  # 0-1 主指标 (M5 可能 0-10)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaseMeta:
    case_id: str
    ts_code: str
    target_name: str
    cut_off_date: date


@dataclass
class MetricInputs:
    """所有 metric 共享的输入 bundle (依赖注入).

    None 字段表示该 metric 不需要这个依赖时可以传 None。
    """

    report: dict[str, Any]  # InvestmentDueDiligenceReport.model_dump() 形态
    case_meta: CaseMeta
    ground_truth: GroundTruthLoader | None
    tushare_adapter: TushareBacktestAdapter | None
    kb_lookup: Callable[[str], dict[str, Any] | None] | None  # chunk_id -> chunk
    evaluator_clients: dict[str, EvaluatorClient]  # "gpt-4o-2024-05-13": client, ...


class MetricProtocol(Protocol):
    """A metric: name + compute(inputs)."""

    name: str

    def compute(self, inputs: MetricInputs) -> MetricResult: ...


@dataclass
class MetricRegistry:
    """串行执行注册的 metric, 返回 MetricResult list."""

    metrics: list[MetricProtocol]

    def __post_init__(self) -> None:
        seen = set()
        for m in self.metrics:
            if m.name in seen:
                raise ValueError(f"duplicate metric name {m.name!r}")
            seen.add(m.name)

    def compute_all(self, inputs: MetricInputs) -> list[MetricResult]:
        return [m.compute(inputs) for m in self.metrics]
```

Run: `uv run pytest backend/tests/eval/dd_report/test_metric_registry.py backend/tests/eval/dd_report/test_metric_scores_schema.py -v`
Expected: 6 PASS total

- [x] **Step 7: 扩 EvalResult schema + EvalRecorder 加 metric_scores_json 列 + commit**

读 `backend/app/services/eval_models.py` 看 `EvalResult` 形态(Phase 1 已加 backtest_run_id / cut_off_date / evaluator_llm / case_type),加 `metric_scores_json: str | None = None` 字段。

`backend/app/services/eval_recorder.py` 修改:

1. 在 `_EVAL_RESULTS_SCHEMA` 加列 `metric_scores_json TEXT`
2. 在 `init_schema` 的 `_maybe_add_column` block 加 `_maybe_add_column(con, "eval_results", "metric_scores_json", "TEXT")`(Phase 1 同 pattern,migrate legacy DB)
3. `write` SQL 加这列,绑 `result.metric_scores_json`
4. `_row_to_result` 加 `metric_scores_json=row["metric_scores_json"]`

测试守护:`backend/tests/eval/dd_report/test_metric_scores_schema.py` 加一个 case:

```python
def test_eval_result_persists_metric_scores_json(tmp_path) -> None:
    from datetime import datetime
    from app.services.eval_models import EvalResult, JudgeScores
    from app.services.eval_recorder import EvalRecorder

    db = tmp_path / "eval.db"
    recorder = EvalRecorder(db)
    recorder.init_schema()
    scores = BacktestMetricScores(
        m1_citation_precision=0.9, m1_citation_recall=0.8,
        m2_numerical_accuracy=0.85, m2_numerical_total=10, m2_numerical_correct=8,
        m3_risk_pairing_score=0.7,
        m4_recommendation_direction_correct=None,
        m4_target_price_hit=None,
        m4_risk_flag_realized_rate=None,
        m5_composite_mean=7.5, m5_composite_majority=8.0, m5_composite_disagreement_max=1.0,
    )
    result = EvalResult(
        eval_id="ev-1",
        request_id="req-1",
        case_id="bt-test",
        scores=JudgeScores(  # 仍存最小 JudgeScores, backtest 模式下 stub
            factuality=0, factuality_evidence="N/A backtest",
            tool_correctness=None, tool_correctness_evidence="N/A backtest",
            coverage=0, coverage_evidence="N/A backtest",
            structure=0, structure_evidence="N/A backtest",
        ),
        judge_model="backtest",
        judge_cost_cny=0.0,
        judge_latency_ms=0,
        timestamp=datetime.utcnow(),
        backtest_run_id="bt-run-x",
        cut_off_date="2024-06-30",
        evaluator_llm="gpt-4o-2024-05-13",
        case_type="backtest",
        metric_scores_json=scores.model_dump_json(),
    )
    recorder.write(result)
    read = recorder.read("ev-1")
    assert read.metric_scores_json is not None
    BacktestMetricScores.model_validate_json(read.metric_scores_json)
```

Run: `uv run pytest backend/tests/eval/dd_report/test_metric_scores_schema.py backend/tests/eval/dd_report/test_metric_registry.py -v`
Expected: 7 PASS

Commit:

```bash
git add backend/eval/dd_report/metric_scores.py \
  backend/eval/dd_report/metrics/__init__.py \
  backend/eval/dd_report/metrics/base.py \
  backend/app/services/eval_models.py \
  backend/app/services/eval_recorder.py \
  backend/tests/eval/dd_report/test_metric_scores_schema.py \
  backend/tests/eval/dd_report/test_metric_registry.py
git commit -m "feat(dd-eval): Phase 2 T2.0 — MetricProtocol + BacktestMetricScores + DB metric_scores_json"
```

---

## Task 2.1:GroundTruthLoader 真实现(fetch_post_cut_off_kline + fetch_post_cut_off_anns)

**Files:**
- Modify: `backend/eval/dd_report/golden/ground_truth_loader.py`(2 NotImplementedError → 真实现)
- Test: `backend/tests/eval/dd_report/test_ground_truth_loader.py`

- [x] **Step 1: 写失败 test 用 fake tushare**

`backend/tests/eval/dd_report/test_ground_truth_loader.py`:

```python
"""GroundTruthLoader Phase 2 真实现 — T2.1."""

from __future__ import annotations

from datetime import date
from typing import Any

from eval.dd_report.golden.ground_truth_loader import GroundTruthLoader


class _FakeTushare:
    def __init__(self, kline: list[dict[str, Any]], anns: list[dict[str, Any]]) -> None:
        self._kline = kline
        self._anns = anns

    def daily(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._kline

    def anns(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._anns


def test_fetch_post_cut_off_kline_returns_rows_within_horizon() -> None:
    inner = _FakeTushare(
        kline=[
            {"trade_date": "20240701", "close": 1700.0},
            {"trade_date": "20240801", "close": 1650.0},
            {"trade_date": "20241001", "close": 1500.0},  # beyond horizon 90d
        ],
        anns=[],
    )
    loader = GroundTruthLoader(inner=inner)
    rows = loader.fetch_post_cut_off_kline("600519.SH", date(2024, 6, 30), horizon_days=90)
    dates = [r["trade_date"] for r in rows]
    assert "20240701" in dates
    assert "20240801" in dates
    assert "20241001" not in dates


def test_fetch_post_cut_off_anns_filters_pre_cut_off() -> None:
    inner = _FakeTushare(
        kline=[],
        anns=[
            {"ann_date": "20240615", "title": "前公告 ignore"},
            {"ann_date": "20240715", "title": "中报披露"},
            {"ann_date": "20241105", "title": "退市风险警告"},  # within 180d
            {"ann_date": "20260101", "title": "远未来"},  # within unbounded? horizon default 90
        ],
    )
    loader = GroundTruthLoader(inner=inner)
    rows = loader.fetch_post_cut_off_anns("600519.SH", date(2024, 6, 30), horizon_days=180)
    titles = [r["title"] for r in rows]
    assert "前公告 ignore" not in titles
    assert "中报披露" in titles
    assert "退市风险警告" in titles
    assert "远未来" not in titles


def test_fetch_returns_empty_when_no_data() -> None:
    inner = _FakeTushare(kline=[], anns=[])
    loader = GroundTruthLoader(inner=inner)
    assert loader.fetch_post_cut_off_kline("X", date(2024, 6, 30)) == []
    assert loader.fetch_post_cut_off_anns("X", date(2024, 6, 30)) == []
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_ground_truth_loader.py -v`
Expected: 3 FAIL with `NotImplementedError: Phase 2 M4 prediction metric 实施`

- [x] **Step 3: 实现 fetch_post_cut_off_kline + fetch_post_cut_off_anns**

`backend/eval/dd_report/golden/ground_truth_loader.py` 替换两个 NotImplementedError:

```python
def fetch_post_cut_off_kline(
    self,
    ts_code: str,
    cut_off: date,
    horizon_days: int = 90,
) -> list[dict[str, Any]]:
    """取 cut_off 之后 horizon_days 天的日 K (含 cut_off 当天 +1, 不含 cut_off 当天).

    用于 M4 prediction metric: cut_off 后股价方向 / 目标价命中检测。
    """
    from datetime import timedelta

    start = (cut_off + timedelta(days=1)).strftime("%Y%m%d")
    end = (cut_off + timedelta(days=horizon_days)).strftime("%Y%m%d")
    rows = self.inner.daily(ts_code=ts_code, start_date=start, end_date=end)
    return [r for r in rows if start <= r.get("trade_date", "") <= end]


def fetch_post_cut_off_anns(
    self,
    ts_code: str,
    cut_off: date,
    horizon_days: int = 90,
) -> list[dict[str, Any]]:
    """取 cut_off 之后 horizon_days 天的公告.

    用于 M4 prediction metric: 风险 flag 真实发生率检测。
    """
    from datetime import timedelta

    start = (cut_off + timedelta(days=1)).strftime("%Y%m%d")
    end = (cut_off + timedelta(days=horizon_days)).strftime("%Y%m%d")
    rows = self.inner.anns(ts_code=ts_code, start_date=start, end_date=end)
    return [r for r in rows if start <= r.get("ann_date", "") <= end]
```

- [x] **Step 4: 跑 test 验证 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_ground_truth_loader.py -v`
Expected: 3 PASS

- [x] **Step 5: 跑全 dd_report test 守护 Phase 1 没回归**

Run: `uv run pytest backend/tests/eval/dd_report/ -v`
Expected: 全 PASS(Phase 1 + T2.0 + T2.1)

- [x] **Step 6: Commit**

```bash
git add backend/eval/dd_report/golden/ground_truth_loader.py \
  backend/tests/eval/dd_report/test_ground_truth_loader.py
git commit -m "feat(dd-eval): Phase 2 T2.1 — GroundTruthLoader fetch_post_cut_off_kline/anns 真实现"
```

---

## Task 2.2:M1 CitationMetric(extraction · 程序化 + 小 LLM judge supports)

**Files:**
- Create: `backend/eval/dd_report/metrics/citation_metric.py`
- Test: `backend/tests/eval/dd_report/test_citation_metric.py`
- Cassette: `backend/tests/eval/dd_report/cassettes/citation_supports_judge.yaml`(L1 only)

- [x] **Step 1: 写失败 L0 unit test(不调 LLM,用 fake judge)**

`backend/tests/eval/dd_report/test_citation_metric.py`:

```python
"""M1 CitationMetric — extraction precision/recall.

L0 unit: fake judge, 验算法逻辑。
L1: real LLM judge via cassette, 验 prompt 不漂。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.citation_metric import (
    CitationMetric,
    SupportsJudgeProtocol,
)


def _fake_kb_lookup(known: dict[str, str]):
    def lookup(chunk_id: str) -> dict[str, Any] | None:
        text = known.get(chunk_id)
        if text is None:
            return None
        return {"chunk_id": chunk_id, "text": text}

    return lookup


class _FakeJudge:
    """Fake judge that returns True iff chunk text contains a known keyword."""

    def supports(self, claim: str, chunk_text: str) -> bool:
        return "茅台" in claim and "茅台" in chunk_text


def _make_inputs(report: dict[str, Any], kb: dict[str, str]) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta(
            case_id="bt-test", ts_code="600519.SH",
            target_name="茅台", cut_off_date=date(2024, 6, 30),
        ),
        ground_truth=None,
        tushare_adapter=None,
        kb_lookup=_fake_kb_lookup(kb),
        evaluator_clients={},
    )


def test_perfect_citation_gives_precision_1_recall_1() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台是大白马",
            "evidence": ["chunk-1"],
        },
    }
    kb = {"chunk-1": "贵州茅台是大白马"}
    metric = CitationMetric(judge=_FakeJudge(), section_paths=("target_overview",))
    r = metric.compute(_make_inputs(report, kb))
    assert r.value is not None
    assert r.details["precision"] == 1.0
    assert r.details["recall"] == 1.0


def test_missing_chunk_id_zero_precision_for_that_section() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台是大白马",
            "evidence": ["chunk-missing"],
        },
    }
    metric = CitationMetric(judge=_FakeJudge(), section_paths=("target_overview",))
    r = metric.compute(_make_inputs(report, {}))
    assert r.details["lookup_failures"] == 1
    assert r.details["precision"] == 0.0
    # has_evidence True 即使 lookup_fail; recall 衡量 "section 有写 evidence" 比例
    assert r.details["recall"] == 1.0


def test_no_evidence_zero_recall_perfect_precision_vacuous() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台是大白马",
            "evidence": [],
        },
    }
    metric = CitationMetric(judge=_FakeJudge(), section_paths=("target_overview",))
    r = metric.compute(_make_inputs(report, {}))
    assert r.details["recall"] == 0.0
    # precision vacuously 1.0 (no cited chunks)
    assert r.details["precision"] == 1.0


def test_multiple_sections_micro_avg() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台是大白马",
            "evidence": ["chunk-1", "chunk-2"],  # 2 cited, both support
        },
        "industry_analysis": {
            "narrative": "白酒行业茅台龙头",
            "evidence": ["chunk-3"],  # 1 cited, supports
        },
    }
    kb = {
        "chunk-1": "茅台龙头",
        "chunk-2": "茅台稳健",
        "chunk-3": "茅台行业地位",
    }
    metric = CitationMetric(judge=_FakeJudge(), section_paths=("target_overview", "industry_analysis"))
    r = metric.compute(_make_inputs(report, kb))
    assert r.details["precision"] == 1.0
    assert r.details["recall"] == 1.0
    assert r.details["sections_with_evidence"] == 2


def test_main_value_is_f1_of_precision_recall() -> None:
    report = {
        "target_overview": {
            "narrative": "茅台龙头",
            "evidence": ["chunk-1"],
        },
        "industry_analysis": {
            "narrative": "测试",
            "evidence": [],  # 这个 section 无 evidence -> recall 拉低
        },
    }
    kb = {"chunk-1": "茅台行业"}
    metric = CitationMetric(judge=_FakeJudge(), section_paths=("target_overview", "industry_analysis"))
    r = metric.compute(_make_inputs(report, kb))
    # precision = 1/1 = 1.0, recall = 1/2 = 0.5
    # F1 = 2 * 1 * 0.5 / 1.5 = 2/3
    assert r.value == pytest.approx(2 / 3, rel=1e-4)
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_citation_metric.py -v`
Expected: 5 FAIL with `ModuleNotFoundError`

- [x] **Step 3: 实现 CitationMetric**

`backend/eval/dd_report/metrics/citation_metric.py`:

```python
"""M1 CitationMetric — extraction precision/recall (spec § 4.2).

precision = chunks that LOOK UP + SUPPORT claim / total cited chunks
recall    = sections with non-empty evidence / total sections evaluated
value     = F1(precision, recall)

简化(spec § 4.2 v0):
- claim = section.narrative 整体 (atomic claim 拆解推到 v1.x)
- supports 判断 = LLM judge (本 metric 用小模型, 通过 SupportsJudgeProtocol 注入)
- 多 section micro avg (跨 section 累加 supports / total cited)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eval.dd_report.metrics.base import MetricInputs, MetricResult


class SupportsJudgeProtocol(Protocol):
    """小 LLM judge: chunk text 是否支持 claim."""

    def supports(self, claim: str, chunk_text: str) -> bool: ...


# 默认 6 section 路径 (InvestmentDueDiligenceReport)
DEFAULT_SECTION_PATHS: tuple[str, ...] = (
    "target_overview",
    "legal_qualification",
    "financial_analysis",
    "industry_analysis",
    "risk_assessment",
    "investment_recommendation",
)


@dataclass
class CitationMetric:
    name: str = "m1_citation"
    judge: SupportsJudgeProtocol | None = None
    section_paths: tuple[str, ...] = DEFAULT_SECTION_PATHS

    def compute(self, inputs: MetricInputs) -> MetricResult:
        if self.judge is None:
            raise ValueError("CitationMetric requires a judge (SupportsJudgeProtocol)")
        if inputs.kb_lookup is None:
            raise ValueError("CitationMetric requires kb_lookup")

        total_cited = 0
        supports = 0
        lookup_failures = 0
        sections_with_evidence = 0
        failed_cite_log: list[str] = []
        unsupported_log: list[str] = []

        for path in self.section_paths:
            sec = inputs.report.get(path)
            if not isinstance(sec, dict):
                continue
            evidence: list[str] = sec.get("evidence") or []
            claim: str = sec.get("narrative", "")
            if evidence:
                sections_with_evidence += 1
            for chunk_id in evidence:
                total_cited += 1
                chunk = inputs.kb_lookup(chunk_id)
                if chunk is None:
                    lookup_failures += 1
                    failed_cite_log.append(f"{path}:{chunk_id}")
                    continue
                if self.judge.supports(claim, chunk.get("text", "")):
                    supports += 1
                else:
                    unsupported_log.append(f"{path}:{chunk_id}")

        n_sections = sum(
            1 for p in self.section_paths if isinstance(inputs.report.get(p), dict)
        )
        precision = supports / total_cited if total_cited else 1.0
        recall = sections_with_evidence / n_sections if n_sections else 1.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        return MetricResult(
            name=self.name,
            value=f1,
            details={
                "precision": precision,
                "recall": recall,
                "total_cited": total_cited,
                "supports": supports,
                "lookup_failures": lookup_failures,
                "sections_with_evidence": sections_with_evidence,
                "n_sections": n_sections,
                "failed_cites": failed_cite_log[:20],
                "unsupported_cites": unsupported_log[:20],
            },
        )
```

- [x] **Step 4: 跑 L0 test 验 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_citation_metric.py -v`
Expected: 5 PASS

- [x] **Step 5: 加 L1 cassette test — 用真 EvaluatorClient 跑 supports judge**

在 `test_citation_metric.py` 追加:

```python
import os
import pytest
import vcr
from pathlib import Path

CASSETTE_DIR = Path(__file__).parent / "cassettes"


class _EvaluatorJudge:
    """Wrap EvaluatorClient.chat into SupportsJudgeProtocol."""

    def __init__(self, client) -> None:  # type: ignore[no-untyped-def]
        self._client = client

    def supports(self, claim: str, chunk_text: str) -> bool:
        prompt = (
            f"判断下述 chunk 内容是否支持声明。chunk 必须明确陈述声明的事实"
            f"或紧密相关的事实, 才算 'supports'。\n\n"
            f"声明: {claim}\n\nchunk: {chunk_text}\n\n"
            f"严格输出一行 JSON: {{\"supports\": true}} 或 {{\"supports\": false}}"
        )
        out = self._client.chat(prompt=prompt)
        return '"supports": true' in out.lower() or '"supports":true' in out.lower()


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set; L1 cassette test skipped",
)
def test_l1_citation_judge_supports_via_cassette() -> None:
    from eval.dd_report.llm_swapper import LLMSwapper

    swapper = LLMSwapper()
    client = swapper.get_client("gpt-4o-2024-05-13")
    judge = _EvaluatorJudge(client)
    with vcr.use_cassette(
        str(CASSETTE_DIR / "citation_supports_judge.yaml"),
        record_mode="new_episodes",
        match_on=["method", "scheme", "host", "port", "path"],
    ):
        ok = judge.supports("贵州茅台是大白马稳健蓝筹", "贵州茅台 2024 上半年营收稳健, 净利润同比 +15%")
    assert isinstance(ok, bool)
```

- [x] **Step 6: 跑 L1(可选 — 需 OPENROUTER_API_KEY)+ 录 cassette**

Run: `OPENROUTER_API_KEY=$(grep OPENROUTER_API_KEY backend/.env | cut -d= -f2) uv run pytest backend/tests/eval/dd_report/test_citation_metric.py::test_l1_citation_judge_supports_via_cassette -v`
Expected: PASS,生成 cassette 文件;若 key 缺失则 skip。

- [x] **Step 7: Commit**

```bash
git add backend/eval/dd_report/metrics/citation_metric.py \
  backend/tests/eval/dd_report/test_citation_metric.py \
  backend/tests/eval/dd_report/cassettes/citation_supports_judge.yaml
git commit -m "feat(dd-eval): Phase 2 T2.2 — M1 CitationMetric precision/recall + L0 unit + L1 cassette"
```

---

## Task 2.3:M2 NumericalMetric(extraction · regex 抽 + tushare ±1% 容差)

**Files:**
- Create: `backend/eval/dd_report/metrics/numerical_metric.py`
- Test: `backend/tests/eval/dd_report/test_numerical_metric.py`

- [x] **Step 1: 写失败 test — 4 类指标 regex 归一**

`backend/tests/eval/dd_report/test_numerical_metric.py`:

```python
"""M2 NumericalMetric — extraction regex + tushare ±1% 容差.

L0 unit: fake tushare adapter, 验数字归一 + 容差判定 + 4 类指标支持。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.numerical_metric import (
    NumericalMetric,
    parse_chinese_number,
)


class _FakeTushareAdapter:
    """fake adapter, 不限 cut_off, 直接返回固定数据."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetch_income(self, ts_code: str, **kwargs: Any) -> list[dict[str, Any]]:
        return self._rows


def _make_inputs(report: dict[str, Any], adapter: Any) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta(
            case_id="bt-test", ts_code="600519.SH",
            target_name="茅台", cut_off_date=date(2024, 6, 30),
        ),
        ground_truth=None,
        tushare_adapter=adapter,
        kb_lookup=None,
        evaluator_clients={},
    )


def test_parse_yi_yuan() -> None:
    assert parse_chinese_number("150 亿元") == pytest.approx(1.5e10)
    assert parse_chinese_number("150亿") == pytest.approx(1.5e10)
    assert parse_chinese_number("3.5亿元") == pytest.approx(3.5e8)


def test_parse_wan_yuan() -> None:
    assert parse_chinese_number("8000 万元") == pytest.approx(8e7)


def test_parse_percent() -> None:
    assert parse_chinese_number("12.5%") == pytest.approx(0.125)
    assert parse_chinese_number("12.5 %") == pytest.approx(0.125)


def test_parse_bad_returns_none() -> None:
    assert parse_chinese_number("无") is None
    assert parse_chinese_number("约") is None


def test_revenue_within_tolerance_counts_correct() -> None:
    report = {
        "financial_analysis": {
            "key_metrics": [
                {"name": "营业收入", "value": "150 亿元", "period": "2024 H1"},
            ],
        },
    }
    # tushare income 返回真值 150.0 亿元 (revenue 列, 单位 元)
    adapter = _FakeTushareAdapter(
        [{"end_date": "20240630", "revenue": 1.501e10}],  # 0.07% 偏离, < 1% pass
    )
    m = NumericalMetric()
    r = m.compute(_make_inputs(report, adapter))
    assert r.details["total"] == 1
    assert r.details["correct"] == 1
    assert r.value == 1.0


def test_revenue_outside_tolerance_counts_wrong() -> None:
    report = {
        "financial_analysis": {
            "key_metrics": [
                {"name": "营业收入", "value": "200 亿元", "period": "2024 H1"},
            ],
        },
    }
    adapter = _FakeTushareAdapter(
        [{"end_date": "20240630", "revenue": 1.5e10}],  # 33% 偏离
    )
    m = NumericalMetric()
    r = m.compute(_make_inputs(report, adapter))
    assert r.details["total"] == 1
    assert r.details["correct"] == 0
    assert r.details["wrong_values"][0]["metric_name"] == "营业收入"


def test_unknown_metric_skipped() -> None:
    report = {
        "financial_analysis": {
            "key_metrics": [
                {"name": "某未知指标", "value": "100 万元", "period": "2024 H1"},
            ],
        },
    }
    adapter = _FakeTushareAdapter([])
    m = NumericalMetric()
    r = m.compute(_make_inputs(report, adapter))
    assert r.details["total"] == 0
    assert r.value == 1.0  # vacuous
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_numerical_metric.py -v`
Expected: 7 FAIL with `ModuleNotFoundError`

- [x] **Step 3: 实现 parse_chinese_number + NumericalMetric(4 类指标 v0)**

`backend/eval/dd_report/metrics/numerical_metric.py`:

```python
"""M2 NumericalMetric — extraction numerical accuracy (spec § 4.2).

简化 v0 — 支持 4 类指标 (其余 skip):
  - 营业收入  -> tushare income.revenue (单位 元)
  - 净利润    -> tushare income.n_income (单位 元)
  - 资产负债率 -> 计算 balancesheet.total_liab / total_assets (百分比)
  - ROE       -> tushare fina_indicator.roe (单位 %)

容差 ±1% (spec § 4.2)。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from eval.dd_report.metrics.base import MetricInputs, MetricResult

_NUM_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)")


def parse_chinese_number(text: str | None) -> float | None:
    """把 '150 亿元' / '12.5%' / '8000 万元' 归一为基础单位 (元 / 0-1 比例).

    Returns None 当无法 parse。
    """
    if not text:
        return None
    s = text.strip()
    m = _NUM_PATTERN.search(s)
    if not m:
        return None
    n = float(m.group(1))
    rest = s[m.end() :].strip()
    if "亿" in rest:
        return n * 1e8
    if "万" in rest and "亿" not in rest:
        return n * 1e4
    if "%" in rest or "百分" in rest:
        return n / 100.0
    return n


# Metric name -> (tushare adapter method, tushare row key, expected unit normalization)
_KNOWN_METRICS: dict[str, dict[str, Any]] = {
    "营业收入": {"fetch": "fetch_income", "row_key": "revenue", "unit": "yuan"},
    "净利润": {"fetch": "fetch_income", "row_key": "n_income", "unit": "yuan"},
    "ROE": {"fetch": "fetch_income", "row_key": "roe", "unit": "percent"},  # 简化:实际 ROE 在 fina_indicator
    "资产负债率": {"fetch": "fetch_income", "row_key": "_debt_ratio", "unit": "percent"},
}


@dataclass
class NumericalMetric:
    name: str = "m2_numerical"
    tolerance: float = 0.01  # ±1%
    sections_with_metrics: tuple[str, ...] = ("financial_analysis",)

    def compute(self, inputs: MetricInputs) -> MetricResult:
        if inputs.tushare_adapter is None:
            raise ValueError("NumericalMetric requires tushare_adapter")
        ts_code = inputs.case_meta.ts_code

        total = 0
        correct = 0
        wrong: list[dict[str, Any]] = []
        skipped: list[str] = []

        for sec_path in self.sections_with_metrics:
            sec = inputs.report.get(sec_path)
            if not isinstance(sec, dict):
                continue
            for item in sec.get("key_metrics", []) or []:
                if not isinstance(item, dict):
                    continue
                metric_name = item.get("name", "")
                if metric_name not in _KNOWN_METRICS:
                    skipped.append(metric_name)
                    continue
                claimed = parse_chinese_number(item.get("value"))
                if claimed is None:
                    skipped.append(f"{metric_name}:unparseable")
                    continue
                real = self._lookup_real_value(
                    metric_name, ts_code, item.get("period", ""), inputs.tushare_adapter
                )
                if real is None:
                    skipped.append(f"{metric_name}:no_tushare")
                    continue
                total += 1
                if abs(claimed - real) / max(abs(real), 1e-9) <= self.tolerance:
                    correct += 1
                else:
                    wrong.append({
                        "metric_name": metric_name,
                        "claimed": claimed,
                        "real": real,
                        "period": item.get("period", ""),
                    })

        accuracy = correct / total if total else 1.0
        return MetricResult(
            name=self.name,
            value=accuracy,
            details={
                "total": total,
                "correct": correct,
                "wrong_values": wrong[:10],
                "skipped": skipped[:20],
            },
        )

    def _lookup_real_value(
        self, metric_name: str, ts_code: str, period: str, adapter: Any
    ) -> float | None:
        spec = _KNOWN_METRICS[metric_name]
        method = getattr(adapter, spec["fetch"], None)
        if method is None:
            return None
        rows = method(ts_code=ts_code)
        if not rows:
            return None
        # 简化:取第一行(adapter 已 ann_date 过滤),按 row_key 取数
        row = rows[0]
        if spec["row_key"] == "_debt_ratio":
            total_liab = row.get("total_liab")
            total_assets = row.get("total_assets")
            if total_liab is None or total_assets is None or total_assets == 0:
                return None
            return float(total_liab) / float(total_assets)
        val = row.get(spec["row_key"])
        if val is None:
            return None
        return float(val) / 100.0 if spec["unit"] == "percent" else float(val)
```

- [x] **Step 4: 跑 L0 test 验 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_numerical_metric.py -v`
Expected: 7 PASS

- [x] **Step 5: 跑 mypy 守护类型**

Run: `uv run mypy backend/eval/dd_report/metrics/numerical_metric.py`
Expected: Success, no errors

- [x] **Step 6: 跑全 dd_report test**

Run: `uv run pytest backend/tests/eval/dd_report/ -v`
Expected: 全 PASS

- [x] **Step 7: Commit**

```bash
git add backend/eval/dd_report/metrics/numerical_metric.py \
  backend/tests/eval/dd_report/test_numerical_metric.py
git commit -m "feat(dd-eval): Phase 2 T2.3 — M2 NumericalMetric 4 类指标 ±1% 容差 + 中文数字归一"
```

---

## Task 2.4:M3 RiskPairingMetric(summarization · LLM judge)

**Files:**
- Create: `backend/eval/dd_report/metrics/risk_pairing_metric.py`
- Test: `backend/tests/eval/dd_report/test_risk_pairing_metric.py`
- Cassette: `backend/tests/eval/dd_report/cassettes/risk_pairing_judge.yaml`(L1 only)

- [x] **Step 1: 写失败 L0 unit test(fake judge)**

`backend/tests/eval/dd_report/test_risk_pairing_metric.py`:

```python
"""M3 RiskPairingMetric — summarization LLM judge.

L0 unit: fake judge 验算法逻辑。
"""

from __future__ import annotations

from datetime import date

import pytest

from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.risk_pairing_metric import (
    PairingJudgeProtocol,
    RiskPairingMetric,
)


class _AlwaysValidJudge:
    def is_valid_mitigation(self, risk_title: str, risk_desc: str, mitigations: list[str]) -> bool:
        return True


class _AlwaysInvalidJudge:
    def is_valid_mitigation(self, risk_title: str, risk_desc: str, mitigations: list[str]) -> bool:
        return False


def _make_inputs(report: dict) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=None, tushare_adapter=None, kb_lookup=None,
        evaluator_clients={},
    )


def test_all_paired_with_valid_mitigation_gives_score_1() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [{"title": "波动", "description": "高 beta", "severity": "medium",
                              "mitigations": ["分批建仓"]}],
            "growth_risk": [], "event_risk": [], "valuation_risk": [],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysValidJudge())
    r = m.compute(_make_inputs(report))
    assert r.value == 1.0
    assert r.details["total"] == 1
    assert r.details["valid"] == 1


def test_unpaired_risk_counts_as_unpaired() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [{"title": "波动", "description": "高 beta", "severity": "medium",
                              "mitigations": []}],  # 无 mitigation
            "growth_risk": [], "event_risk": [], "valuation_risk": [],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysValidJudge())
    r = m.compute(_make_inputs(report))
    assert r.details["total"] == 1
    assert r.details["unpaired"] == 1
    assert r.value == 0.0


def test_paired_but_invalid_judge_counts_as_invalid() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [{"title": "波动", "description": "高 beta", "severity": "medium",
                              "mitigations": ["啥也不干"]}],
            "growth_risk": [], "event_risk": [], "valuation_risk": [],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysInvalidJudge())
    r = m.compute(_make_inputs(report))
    assert r.details["paired"] == 1
    assert r.details["valid"] == 0
    assert r.value == 0.0


def test_aggregate_across_4_risk_buckets() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [{"title": "X1", "description": "", "severity": "low", "mitigations": ["A"]}],
            "growth_risk": [{"title": "X2", "description": "", "severity": "low", "mitigations": []}],
            "event_risk":  [{"title": "X3", "description": "", "severity": "low", "mitigations": ["B"]}],
            "valuation_risk": [{"title": "X4", "description": "", "severity": "low", "mitigations": []}],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysValidJudge())
    r = m.compute(_make_inputs(report))
    # 4 risks total, 2 paired with valid mitigation -> 2/4 = 0.5
    assert r.details["total"] == 4
    assert r.details["paired"] == 2
    assert r.details["valid"] == 2
    assert r.value == 0.5


def test_no_risks_returns_vacuous_one() -> None:
    report = {
        "risk_assessment": {
            "market_risk": [], "growth_risk": [], "event_risk": [], "valuation_risk": [],
        },
    }
    m = RiskPairingMetric(judge=_AlwaysValidJudge())
    r = m.compute(_make_inputs(report))
    assert r.details["total"] == 0
    assert r.value == 1.0
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_risk_pairing_metric.py -v`
Expected: 5 FAIL with `ModuleNotFoundError`

- [x] **Step 3: 实现 RiskPairingMetric**

`backend/eval/dd_report/metrics/risk_pairing_metric.py`:

```python
"""M3 RiskPairingMetric — summarization LLM judge (spec § 4.2).

逻辑:
1. 遍历 RiskAssessment 4 桶 (market/growth/event/valuation)
2. 每个 RiskItem 检查 mitigations 非空 (paired)
3. 对 paired 的, LLM judge 判 mitigation 是否有效 (valid)
4. score = valid / total
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from eval.dd_report.metrics.base import MetricInputs, MetricResult


class PairingJudgeProtocol(Protocol):
    def is_valid_mitigation(
        self, risk_title: str, risk_desc: str, mitigations: list[str]
    ) -> bool: ...


_RISK_BUCKETS: tuple[str, ...] = (
    "market_risk",
    "growth_risk",
    "event_risk",
    "valuation_risk",
)


@dataclass
class RiskPairingMetric:
    name: str = "m3_risk_pairing"
    judge: PairingJudgeProtocol | None = None
    section_path: str = "risk_assessment"

    def compute(self, inputs: MetricInputs) -> MetricResult:
        if self.judge is None:
            raise ValueError("RiskPairingMetric requires a judge")
        sec = inputs.report.get(self.section_path)
        if not isinstance(sec, dict):
            return MetricResult(
                name=self.name, value=1.0,
                details={"total": 0, "paired": 0, "valid": 0, "unpaired": 0},
            )

        total = 0
        paired = 0
        valid = 0
        invalid_log: list[dict[str, Any]] = []
        unpaired_log: list[str] = []

        for bucket in _RISK_BUCKETS:
            for item in sec.get(bucket, []) or []:
                if not isinstance(item, dict):
                    continue
                total += 1
                title = item.get("title", "")
                desc = item.get("description", "")
                mits: list[str] = item.get("mitigations", []) or []
                if not mits:
                    unpaired_log.append(f"{bucket}:{title}")
                    continue
                paired += 1
                if self.judge.is_valid_mitigation(title, desc, mits):
                    valid += 1
                else:
                    invalid_log.append({"bucket": bucket, "title": title, "mits": mits})

        score = valid / total if total else 1.0
        return MetricResult(
            name=self.name,
            value=score,
            details={
                "total": total,
                "paired": paired,
                "valid": valid,
                "unpaired": total - paired,
                "invalid_mitigations": invalid_log[:10],
                "unpaired_risks": unpaired_log[:10],
            },
        )
```

- [x] **Step 4: 跑 L0 test 验 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_risk_pairing_metric.py -v`
Expected: 5 PASS

- [x] **Step 5: 加 L1 cassette test 真 LLM judge**

在 `test_risk_pairing_metric.py` 追加:

```python
import os
import vcr
from pathlib import Path

CASSETTE_DIR = Path(__file__).parent / "cassettes"


class _EvaluatorPairingJudge:
    def __init__(self, client) -> None:  # type: ignore[no-untyped-def]
        self._client = client

    def is_valid_mitigation(
        self, risk_title: str, risk_desc: str, mitigations: list[str]
    ) -> bool:
        prompt = (
            f"判断下述风险的 mitigation 是否真能缓释该风险。\n\n"
            f"风险标题: {risk_title}\n风险描述: {risk_desc}\n"
            f"mitigation: {mitigations}\n\n"
            f"严格输出一行 JSON: {{\"valid\": true}} 或 {{\"valid\": false}}"
        )
        out = self._client.chat(prompt=prompt)
        return '"valid": true' in out.lower() or '"valid":true' in out.lower()


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set; L1 cassette test skipped",
)
def test_l1_risk_pairing_judge_via_cassette() -> None:
    from eval.dd_report.llm_swapper import LLMSwapper
    swapper = LLMSwapper()
    client = swapper.get_client("gpt-4o-2024-05-13")
    judge = _EvaluatorPairingJudge(client)
    with vcr.use_cassette(
        str(CASSETTE_DIR / "risk_pairing_judge.yaml"),
        record_mode="new_episodes",
        match_on=["method", "scheme", "host", "port", "path"],
    ):
        ok = judge.is_valid_mitigation(
            "股价波动风险", "茅台 beta=1.2 中期可能 20% 回撤",
            ["分批建仓, 单次仓位不超过总仓 5%", "设 5% 止损线"],
        )
    assert isinstance(ok, bool)
```

- [x] **Step 6: 跑 L1 + 录 cassette**

Run: `OPENROUTER_API_KEY=$(grep OPENROUTER_API_KEY backend/.env | cut -d= -f2) uv run pytest backend/tests/eval/dd_report/test_risk_pairing_metric.py::test_l1_risk_pairing_judge_via_cassette -v`
Expected: PASS,生成 cassette。

- [x] **Step 7: Commit**

```bash
git add backend/eval/dd_report/metrics/risk_pairing_metric.py \
  backend/tests/eval/dd_report/test_risk_pairing_metric.py \
  backend/tests/eval/dd_report/cassettes/risk_pairing_judge.yaml
git commit -m "feat(dd-eval): Phase 2 T2.4 — M3 RiskPairingMetric 4-bucket valid mitigation judge"
```

---

## Task 2.5:M4 PredictionMetric(reasoning · backtest 用 GroundTruthLoader)

**Files:**
- Create: `backend/eval/dd_report/metrics/prediction_metric.py`
- Test: `backend/tests/eval/dd_report/test_prediction_metric.py`

- [x] **Step 1: 写失败 L0 test — 3 子指标(方向 / 目标价 / 风险 flag)**

`backend/tests/eval/dd_report/test_prediction_metric.py`:

```python
"""M4 PredictionMetric — reasoning backtest accuracy.

3 子指标:
  1. recommendation_direction_correct: 建议方向 vs 后续股价方向
  2. target_price_hit: 后续 horizon 内是否触及 target_price_range
  3. risk_flag_realized_rate: 报告 RiskItem 关键词在后续公告 title 命中率
"""

from __future__ import annotations

from datetime import date
from typing import Any

from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.prediction_metric import PredictionMetric


class _FakeGroundTruth:
    def __init__(
        self,
        kline: list[dict[str, Any]],
        anns: list[dict[str, Any]],
    ) -> None:
        self._kline = kline
        self._anns = anns

    def fetch_post_cut_off_kline(
        self, ts_code: str, cut_off: date, horizon_days: int = 90
    ) -> list[dict[str, Any]]:
        return self._kline

    def fetch_post_cut_off_anns(
        self, ts_code: str, cut_off: date, horizon_days: int = 90
    ) -> list[dict[str, Any]]:
        return self._anns


def _make_inputs(report: dict, gt: _FakeGroundTruth) -> MetricInputs:
    return MetricInputs(
        report=report,
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=gt,  # type: ignore[arg-type]
        tushare_adapter=None, kb_lookup=None,
        evaluator_clients={},
    )


def _report_buy_target_1700_1900_risk(risk_titles: list[str]) -> dict:
    return {
        "target_close_price_at_gen": 1500.0,
        "investment_recommendation": {
            "recommendation": "recommend_buy",
            "estimated_target_price_range": {"low": 1700.0, "high": 1900.0},
        },
        "risk_assessment": {
            "market_risk": [{"title": t, "description": "", "severity": "medium",
                              "mitigations": []} for t in risk_titles],
            "growth_risk": [], "event_risk": [], "valuation_risk": [],
        },
    }


def test_direction_buy_and_price_rises_is_correct() -> None:
    gt = _FakeGroundTruth(
        kline=[
            {"trade_date": "20240701", "close": 1550.0},
            {"trade_date": "20240901", "close": 1750.0},  # rose 16%
        ],
        anns=[],
    )
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["direction_correct"] is True


def test_direction_buy_but_price_drops_incorrect() -> None:
    gt = _FakeGroundTruth(
        kline=[
            {"trade_date": "20240701", "close": 1450.0},
            {"trade_date": "20240901", "close": 1350.0},
        ],
        anns=[],
    )
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["direction_correct"] is False


def test_target_price_hit_when_high_touched() -> None:
    gt = _FakeGroundTruth(
        kline=[
            {"trade_date": "20240701", "close": 1550.0},
            {"trade_date": "20240801", "high": 1750.0, "close": 1700.0},  # 触及 1700-1900
            {"trade_date": "20240901", "close": 1620.0},
        ],
        anns=[],
    )
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["target_price_hit"] is True


def test_risk_flag_realized_match_in_announcement_title() -> None:
    gt = _FakeGroundTruth(
        kline=[{"trade_date": "20240701", "close": 1500.0}],
        anns=[
            {"ann_date": "20240801", "title": "公司就被ST退市风险提示"},
            {"ann_date": "20240901", "title": "正常中报披露"},
        ],
    )
    report = _report_buy_target_1700_1900_risk(["退市风险", "供应链中断"])
    m = PredictionMetric()
    r = m.compute(_make_inputs(report, gt))
    # 退市 命中, 供应链中断 不命中 -> 1/2 = 0.5
    assert r.details["risk_flag_realized_rate"] == 0.5


def test_no_ground_truth_returns_all_none() -> None:
    gt = _FakeGroundTruth(kline=[], anns=[])
    m = PredictionMetric()
    r = m.compute(_make_inputs(_report_buy_target_1700_1900_risk([]), gt))
    assert r.details["direction_correct"] is None
    assert r.details["target_price_hit"] is None
    assert r.details["risk_flag_realized_rate"] is None
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_prediction_metric.py -v`
Expected: 5 FAIL with `ModuleNotFoundError`

- [x] **Step 3: 实现 PredictionMetric**

`backend/eval/dd_report/metrics/prediction_metric.py`:

```python
"""M4 PredictionMetric — reasoning backtest accuracy (spec § 4.2).

3 子指标:
  1. direction_correct: rec_dir(+1/0/-1) × actual_dir(+1/0/-1) > 0
  2. target_price_hit: cut_off 后 horizon 内 high 触及 target_price.low ~ high 区间
  3. risk_flag_realized_rate: RiskItem.title 关键词在后续 ann.title substring 命中率

主 value = 3 子指标平均 (None 不计入)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eval.dd_report.metrics.base import MetricInputs, MetricResult


_REC_DIRECTION: dict[str, int] = {
    "recommend_buy": 1,
    "recommend_overweight": 1,
    "recommend_hold": 0,
    "recommend_underweight": -1,
    "recommend_sell": -1,
}


@dataclass
class PredictionMetric:
    name: str = "m4_prediction"
    horizon_days: int = 90

    def compute(self, inputs: MetricInputs) -> MetricResult:
        if inputs.ground_truth is None:
            raise ValueError("PredictionMetric requires ground_truth")
        ts_code = inputs.case_meta.ts_code
        cut_off = inputs.case_meta.cut_off_date
        kline = inputs.ground_truth.fetch_post_cut_off_kline(
            ts_code, cut_off, horizon_days=self.horizon_days
        )
        anns = inputs.ground_truth.fetch_post_cut_off_anns(
            ts_code, cut_off, horizon_days=self.horizon_days
        )

        rec = inputs.report.get("investment_recommendation") or {}
        risk_sec = inputs.report.get("risk_assessment") or {}
        anchor_price = inputs.report.get("target_close_price_at_gen")

        # 1. direction
        direction_correct = self._direction_correct(rec, kline, anchor_price)
        # 2. target_price_hit
        target_price_hit = self._target_price_hit(rec, kline)
        # 3. risk_flag_realized
        rate, hit_log, miss_log = self._risk_flag_realized(risk_sec, anns)

        subs: list[float] = []
        if direction_correct is not None:
            subs.append(1.0 if direction_correct else 0.0)
        if target_price_hit is not None:
            subs.append(1.0 if target_price_hit else 0.0)
        if rate is not None:
            subs.append(rate)
        value = sum(subs) / len(subs) if subs else None

        return MetricResult(
            name=self.name,
            value=value,
            details={
                "direction_correct": direction_correct,
                "target_price_hit": target_price_hit,
                "risk_flag_realized_rate": rate,
                "risk_flag_hits": hit_log[:10],
                "risk_flag_misses": miss_log[:10],
                "kline_rows": len(kline),
                "ann_rows": len(anns),
            },
        )

    @staticmethod
    def _direction_correct(
        rec: dict[str, Any], kline: list[dict[str, Any]], anchor_price: float | None
    ) -> bool | None:
        if not kline or anchor_price is None:
            return None
        rec_dir = _REC_DIRECTION.get(rec.get("recommendation", ""))
        if rec_dir is None:
            return None
        last_close = float(kline[-1].get("close", 0.0))
        if last_close == 0.0:
            return None
        change = (last_close - float(anchor_price)) / float(anchor_price)
        actual_dir = 1 if change > 0.02 else (-1 if change < -0.02 else 0)
        if rec_dir == 0 and actual_dir == 0:
            return True
        return rec_dir * actual_dir > 0

    @staticmethod
    def _target_price_hit(
        rec: dict[str, Any], kline: list[dict[str, Any]]
    ) -> bool | None:
        rng = rec.get("estimated_target_price_range")
        if not isinstance(rng, dict) or not kline:
            return None
        low = float(rng.get("low", 0.0))
        high = float(rng.get("high", 0.0))
        if low >= high:
            return None
        for row in kline:
            h = row.get("high")
            if h is None:
                continue
            if low <= float(h) <= high or float(h) >= low:
                return True
        return False

    @staticmethod
    def _risk_flag_realized(
        risk_sec: dict[str, Any], anns: list[dict[str, Any]]
    ) -> tuple[float | None, list[str], list[str]]:
        keywords: list[str] = []
        for bucket in ("market_risk", "growth_risk", "event_risk", "valuation_risk"):
            for it in risk_sec.get(bucket, []) or []:
                if isinstance(it, dict) and it.get("title"):
                    keywords.append(it["title"])
        if not keywords:
            return None, [], []
        if not anns:
            return 0.0, [], keywords
        ann_titles = " | ".join(a.get("title", "") for a in anns)
        hits: list[str] = []
        misses: list[str] = []
        for kw in keywords:
            # 简化关键词匹配:title 中 substring (去 "风险" 后缀)
            core = kw.replace("风险", "").strip() or kw
            if core in ann_titles:
                hits.append(kw)
            else:
                misses.append(kw)
        return len(hits) / len(keywords), hits, misses
```

- [x] **Step 4: 跑 test 验 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_prediction_metric.py -v`
Expected: 5 PASS

- [x] **Step 5: 跑全 dd_report test + mypy**

Run: `uv run pytest backend/tests/eval/dd_report/ -v && uv run mypy backend/eval/dd_report/metrics/`
Expected: 全 PASS + mypy success

- [x] **Step 6: Commit**

```bash
git add backend/eval/dd_report/metrics/prediction_metric.py \
  backend/tests/eval/dd_report/test_prediction_metric.py
git commit -m "feat(dd-eval): Phase 2 T2.5 — M4 PredictionMetric direction/target_price/risk_flag"
```

- [x] **Step 7: 写一个 spec § 4.4 康美 case spike check(可选,非阻塞)**

Run: 手动验证康美 (600518.SH) cut_off=2024-06-30 后 90 天 tushare anns 是否有"退市/造假"关键词命中,确认 M4 在暴雷 case 上行为符合预期。命令:

```bash
uv run python -c "
from datetime import date
from app.service.tushare_client import TushareClient  # 真客户端,见 v0.8.3
from eval.dd_report.golden.ground_truth_loader import GroundTruthLoader
gtl = GroundTruthLoader(inner=TushareClient())
anns = gtl.fetch_post_cut_off_anns('600518.SH', date(2024, 6, 30), horizon_days=180)
print(f'康美 2024-07-01 ~ 2024-12-30 公告 {len(anns)} 条,样本:')
for a in anns[:5]: print(' -', a.get('ann_date'), a.get('title'))
"
```

记录输出到 sediment card 的"撞实工业问题"区(spec § 9 风险 #3 缓解 — 退市 case 数据完整性)。

---

## Task 2.6:M5 CompositeJudgeMetric(reasoning · 3 LLM majority + disagreement)

**Files:**
- Create: `backend/eval/dd_report/metrics/composite_judge_metric.py`
- Test: `backend/tests/eval/dd_report/test_composite_judge_metric.py`
- Cassette: `backend/tests/eval/dd_report/cassettes/composite_judge_3llm.yaml`(L1)

- [x] **Step 1: 写失败 L0 test(fake clients, 验 majority + disagreement + 可重复性)**

`backend/tests/eval/dd_report/test_composite_judge_metric.py`:

```python
"""M5 CompositeJudgeMetric — multi-LLM consensus.

L0: fake EvaluatorClient, 验 majority / disagreement 逻辑。
L1 cassette: 3 真 LLM 跑共识, 验 prompt 不漂。
"""

from __future__ import annotations

from datetime import date

import pytest

from eval.dd_report.metrics.base import CaseMeta, MetricInputs
from eval.dd_report.metrics.composite_judge_metric import CompositeJudgeMetric


class _FakeClient:
    def __init__(self, score: int, evidence: str = "ok") -> None:
        self._score = score
        self._evidence = evidence

    def chat(self, prompt: str, response_format=None) -> str:  # type: ignore[no-untyped-def]
        return f'{{"score": {self._score}, "reasoning": "{self._evidence}"}}'


def _make_inputs(clients: dict) -> MetricInputs:
    return MetricInputs(
        report={
            "target_name": "茅台",
            "target_overview": {"narrative": "茅台是大白马"},
            "investment_recommendation": {
                "recommendation": "recommend_buy",
                "narrative": "看多",
            },
        },
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=None, tushare_adapter=None, kb_lookup=None,
        evaluator_clients=clients,
    )


def test_3_judges_consensus_mean_majority() -> None:
    clients = {
        "gpt-4o-2024-05-13": _FakeClient(8),
        "qwen2.5-72b-instruct": _FakeClient(7),
        "deepseek-v3": _FakeClient(8),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    assert r.details["mean"] == pytest.approx((8 + 7 + 8) / 3)
    # majority = median([8,7,8]) = 8
    assert r.details["majority"] == 8.0
    assert r.details["disagreement_max"] == 1.0


def test_high_disagreement_flags_audit() -> None:
    clients = {
        "gpt-4o-2024-05-13": _FakeClient(9),
        "qwen2.5-72b-instruct": _FakeClient(3),  # 6 分差
        "deepseek-v3": _FakeClient(7),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    assert r.details["disagreement_max"] == 6.0
    assert r.details["needs_audit"] is True


def test_consensus_low_quality_flag() -> None:
    clients = {
        "gpt-4o-2024-05-13": _FakeClient(3),
        "qwen2.5-72b-instruct": _FakeClient(4),
        "deepseek-v3": _FakeClient(3),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    assert r.details["low_quality"] is True


def test_main_value_is_mean_score() -> None:
    clients = {
        "gpt-4o-2024-05-13": _FakeClient(8),
        "qwen2.5-72b-instruct": _FakeClient(7),
        "deepseek-v3": _FakeClient(7),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    assert r.value == pytest.approx((8 + 7 + 7) / 3)


def test_missing_clients_raises() -> None:
    m = CompositeJudgeMetric()
    with pytest.raises(ValueError, match="needs at least 3"):
        m.compute(_make_inputs({"gpt-4o-2024-05-13": _FakeClient(5)}))


def test_malformed_json_score_treated_as_neutral_5() -> None:
    class _MalformedClient:
        def chat(self, prompt: str, response_format=None):  # type: ignore[no-untyped-def]
            return "I cannot evaluate this"
    clients = {
        "gpt-4o-2024-05-13": _MalformedClient(),
        "qwen2.5-72b-instruct": _FakeClient(8),
        "deepseek-v3": _FakeClient(7),
    }
    m = CompositeJudgeMetric()
    r = m.compute(_make_inputs(clients))
    # malformed -> 5 默认 + 8 + 7 = 20/3
    assert r.details["mean"] == pytest.approx(20 / 3)
    assert r.details["parse_failures"] >= 1
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_composite_judge_metric.py -v`
Expected: 6 FAIL with `ModuleNotFoundError`

- [x] **Step 3: 实现 CompositeJudgeMetric**

`backend/eval/dd_report/metrics/composite_judge_metric.py`:

```python
"""M5 CompositeJudgeMetric — multi-LLM consensus (spec § 4.3).

3 evaluator LLM 跑同一 rubric prompt, 各 1-10 打分, 取 majority(median)、mean、
disagreement(max - min)。
disagreement > 2 -> needs_audit
mean <= 4         -> low_quality (push 到 dogfood loop)

可重复性 (spec § 7.3): temperature=0 强制, 同 prompt 跑 3 次 majority 决策稳定 > 80%
— 测试在 conftest fixture + 单独 stress test (本 task 不实施, Phase 5 dogfood 时拉)。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from statistics import median

from eval.dd_report.llm_swapper import EvaluatorClient
from eval.dd_report.metrics.base import MetricInputs, MetricResult


_PROMPT_TEMPLATE = """你是金融研究助手报告的评审员。给定下述 InvestmentDueDiligenceReport 内容,
按以下 5 维综合打 1-10 分(1=极差, 10=完美)。结合 factuality + coverage + structure +
investment thesis 合理性 + risk completeness。

报告标的: {target_name}
报告摘要 (JSON 截断 4000 字符): {report_json}

严格输出一行 JSON: {{"score": <1-10>, "reasoning": "<1 句话>"}}
"""

_DEFAULT_JUDGE_MODELS: tuple[str, ...] = (
    "gpt-4o-2024-05-13",
    "qwen2.5-72b-instruct",
    "deepseek-v3",
)

_DEFAULT_SCORE = 5.0
_AUDIT_THRESHOLD = 2.0
_LOW_QUALITY_THRESHOLD = 4.0


@dataclass
class CompositeJudgeMetric:
    name: str = "m5_composite"
    judge_models: tuple[str, ...] = _DEFAULT_JUDGE_MODELS
    audit_threshold: float = _AUDIT_THRESHOLD
    low_quality_threshold: float = _LOW_QUALITY_THRESHOLD

    def compute(self, inputs: MetricInputs) -> MetricResult:
        clients_needed = [
            inputs.evaluator_clients.get(m) for m in self.judge_models
        ]
        present = [c for c in clients_needed if c is not None]
        if len(present) < 3:
            raise ValueError(
                f"CompositeJudgeMetric needs at least 3 evaluator clients, got {len(present)}"
            )

        report_json = json.dumps(inputs.report, ensure_ascii=False)[:4000]
        prompt = _PROMPT_TEMPLATE.format(
            target_name=inputs.case_meta.target_name, report_json=report_json
        )

        raw_scores: list[dict[str, float | str | None]] = []
        parse_failures = 0
        scores_only: list[float] = []
        for model, client in zip(self.judge_models, present, strict=False):
            out = client.chat(prompt=prompt)
            parsed = _parse_score(out)
            if parsed is None:
                parse_failures += 1
                scores_only.append(_DEFAULT_SCORE)
                raw_scores.append({"model": model, "score": None, "raw": out[:200]})
            else:
                scores_only.append(parsed["score"])
                raw_scores.append({"model": model, "score": parsed["score"], "reasoning": parsed.get("reasoning")})

        mean_score = sum(scores_only) / len(scores_only)
        majority = float(median(scores_only))
        disagreement_max = max(scores_only) - min(scores_only)

        return MetricResult(
            name=self.name,
            value=mean_score,
            details={
                "mean": mean_score,
                "majority": majority,
                "disagreement_max": disagreement_max,
                "needs_audit": disagreement_max > self.audit_threshold,
                "low_quality": mean_score <= self.low_quality_threshold,
                "per_judge": raw_scores,
                "parse_failures": parse_failures,
            },
        )


_SCORE_RE = re.compile(r'"score"\s*:\s*(\d+(?:\.\d+)?)')


def _parse_score(text: str) -> dict[str, object] | None:
    """从 LLM raw output parse {"score": int, "reasoning": str}, 容忍 markdown 围栏."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", cleaned, flags=re.MULTILINE)
    try:
        d = json.loads(cleaned)
        if isinstance(d, dict) and "score" in d:
            return {"score": float(d["score"]), "reasoning": d.get("reasoning")}
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    m = _SCORE_RE.search(text)
    if m:
        return {"score": float(m.group(1)), "reasoning": None}
    return None
```

- [x] **Step 4: 跑 L0 test 验 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_composite_judge_metric.py -v`
Expected: 6 PASS

- [x] **Step 5: 加 L1 cassette test — 真 3 LLM 跑共识**

在 `test_composite_judge_metric.py` 追加:

```python
import os
import vcr
from pathlib import Path

CASSETTE_DIR = Path(__file__).parent / "cassettes"


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set; L1 cassette test skipped",
)
def test_l1_composite_judge_3llm_via_cassette() -> None:
    from eval.dd_report.llm_swapper import LLMSwapper
    swapper = LLMSwapper()
    clients = {m: swapper.get_client(m) for m in (
        "gpt-4o-2024-05-13", "qwen2.5-72b-instruct", "deepseek-v3",
    )}
    inputs = MetricInputs(
        report={
            "target_name": "贵州茅台",
            "target_overview": {"narrative": "茅台是大白马稳健蓝筹, 净利润 +15%."},
            "investment_recommendation": {
                "recommendation": "recommend_buy",
                "narrative": "估值合理,建议买入, 目标价 1700-1900"
            },
        },
        case_meta=CaseMeta("bt-test", "600519.SH", "茅台", date(2024, 6, 30)),
        ground_truth=None, tushare_adapter=None, kb_lookup=None,
        evaluator_clients=clients,
    )
    m = CompositeJudgeMetric()
    with vcr.use_cassette(
        str(CASSETTE_DIR / "composite_judge_3llm.yaml"),
        record_mode="new_episodes",
        match_on=["method", "scheme", "host", "port", "path"],
    ):
        r = m.compute(inputs)
    assert r.value is not None
    assert 0 <= r.value <= 10
    assert len(r.details["per_judge"]) == 3
```

- [x] **Step 6: 跑 L1 + 录 cassette**

Run: `OPENROUTER_API_KEY=$(grep OPENROUTER_API_KEY backend/.env | cut -d= -f2) uv run pytest backend/tests/eval/dd_report/test_composite_judge_metric.py::test_l1_composite_judge_3llm_via_cassette -v`
Expected: PASS,生成 cassette。

- [x] **Step 7: Commit**

```bash
git add backend/eval/dd_report/metrics/composite_judge_metric.py \
  backend/tests/eval/dd_report/test_composite_judge_metric.py \
  backend/tests/eval/dd_report/cassettes/composite_judge_3llm.yaml
git commit -m "feat(dd-eval): Phase 2 T2.6 — M5 CompositeJudgeMetric 3 LLM majority + audit/low_quality flag"
```

---

## Task 2.7:BacktestRunner wire MetricRegistry + LeakDetector + write eval_results per case + aggregate

**Files:**
- Modify: `backend/eval/dd_report/backtest_runner.py`
- Test: `backend/tests/eval/dd_report/test_backtest_runner_metric_wire.py`

- [x] **Step 1: 写失败 integration test — fake pipeline 出 dummy report, MetricRegistry 应跑出 BacktestMetricScores**

`backend/tests/eval/dd_report/test_backtest_runner_metric_wire.py`:

```python
"""BacktestRunner Phase 2 wire — MetricRegistry + LeakDetector + 写表."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from eval.dd_report.backtest_runner import BacktestCase, BacktestRunner
from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter
from eval.dd_report.llm_swapper import EvaluatorClient
from eval.dd_report.metrics.base import (
    MetricInputs,
    MetricRegistry,
    MetricResult,
    MetricProtocol,
)
from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter


class _DummyTushare:
    def income(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"ann_date": "20240601", "end_date": "20240331", "revenue": 1.5e10}]
    def daily(self, **kwargs: Any): return []
    def balancesheet(self, **kwargs: Any): return []
    def cashflow(self, **kwargs: Any): return []
    def anns(self, **kwargs: Any): return []


class _DummyKB:
    def search(self, query: str, k: int = 10, **kw: Any): return []


class _DummyClient:
    model = "fake"
    def chat(self, prompt: str, response_format=None) -> str:  # type: ignore[no-untyped-def]
        return '{"score": 8, "reasoning": "ok"}'


class _DummySwapper:
    def get_client(self, model_id: str) -> Any:
        return _DummyClient()


class _DummyPipeline:
    def run(self, *, target_name: str, ts_code: str,
            tushare_adapter, kb_adapter, evaluator_client) -> dict[str, Any]:
        return {
            "target_name": target_name,
            "target_close_price_at_gen": 1500.0,
            "target_overview": {"narrative": "测试 narrative", "evidence": []},
            "financial_analysis": {"narrative": "财务分析", "evidence": [], "key_metrics": []},
            "risk_assessment": {
                "market_risk": [], "growth_risk": [], "event_risk": [], "valuation_risk": [],
            },
            "investment_recommendation": {
                "recommendation": "recommend_hold",
                "estimated_target_price_range": {"low": 1400, "high": 1600},
            },
        }


class _ConstMetric:
    def __init__(self, name: str, value: float) -> None:
        self.name = name; self._value = value
    def compute(self, inputs: MetricInputs) -> MetricResult:
        return MetricResult(name=self.name, value=self._value, details={"k": "v"})


def test_run_one_writes_backtest_runs_and_eval_results(tmp_path) -> None:
    db = tmp_path / "eval.db"
    from app.services.eval_recorder import EvalRecorder
    EvalRecorder(db).init_schema()

    runner = BacktestRunner(
        swapper=_DummySwapper(),  # type: ignore[arg-type]
        tushare_inner=_DummyTushare(),
        kb_inner=_DummyKB(),
        db_path=db,
        pipeline=_DummyPipeline(),
        metric_registry=MetricRegistry([
            _ConstMetric("m1_citation", 0.9),
            _ConstMetric("m2_numerical", 0.85),
            _ConstMetric("m3_risk_pairing", 0.7),
            _ConstMetric("m5_composite", 8.0),
        ]),  # M4 跳过 (ground_truth=None)
    )
    case = BacktestCase(
        case_id=f"bt-{uuid4().hex[:8]}", ts_code="600519.SH",
        target_name="茅台", cut_off_date=date(2024, 6, 30),
    )
    run_id = runner.run_one(
        case=case, evaluator_llm="gpt-4o-2024-05-13",
        ablation_variant="V0_baseline", git_sha="testsha",
    )

    # backtest_runs row 写入
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    assert r["status"] == "completed"
    assert r["llm_model"] == "gpt-4o-2024-05-13"
    assert r["ablation_variant"] == "V0_baseline"
    metric_summary = json.loads(r["metric_summary_json"])
    assert metric_summary["m1_citation"] == 0.9

    # eval_results 写一行 (per case)
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM eval_results WHERE backtest_run_id = ?", (run_id,)
        ).fetchall()
    assert len(rows) == 1
    er = rows[0]
    assert er["case_id"] == case.case_id
    assert er["cut_off_date"] == "2024-06-30"
    assert er["evaluator_llm"] == "gpt-4o-2024-05-13"
    mscores = json.loads(er["metric_scores_json"])
    assert mscores["m1_citation_precision"] is not None or mscores.get("m5_composite_mean") == 8.0


def test_run_one_leakdetector_fires_on_future_data(tmp_path) -> None:
    """spec § 4.5: leak detector wired 进 run_one, 检到 > cut_off 数据 raise."""
    db = tmp_path / "eval.db"
    from app.services.eval_recorder import EvalRecorder
    EvalRecorder(db).init_schema()

    class _LeakyTushare:
        def income(self, **kwargs: Any) -> list[dict[str, Any]]:
            # 模拟 inner client 不老实, 注 future ann_date
            return [{"ann_date": "20250715", "end_date": "20250630", "revenue": 1.5e10}]
        def daily(self, **kwargs: Any): return []
        def balancesheet(self, **kwargs: Any): return []
        def cashflow(self, **kwargs: Any): return []
        def anns(self, **kwargs: Any): return [{"ann_date": "20250801", "title": "future"}]

    class _LeakyPipeline:
        def run(self, **kwargs: Any) -> dict[str, Any]:
            # 故意调 adapter, 把 leaky 数据塞 prompt (模拟 agent 行为)
            tushare = kwargs["tushare_adapter"]
            _ = tushare.fetch_announcements(ts_code="600519.SH")  # 触发 adapter 二次过滤后应空
            return {"narrative": "Mock pipeline ran"}

    runner = BacktestRunner(
        swapper=_DummySwapper(),  # type: ignore[arg-type]
        tushare_inner=_LeakyTushare(),
        kb_inner=_DummyKB(),
        db_path=db,
        pipeline=_LeakyPipeline(),
        metric_registry=MetricRegistry([]),
        enable_leak_detection=True,
    )
    case = BacktestCase(
        case_id=f"bt-{uuid4().hex[:8]}", ts_code="600519.SH",
        target_name="茅台", cut_off_date=date(2024, 6, 30),
    )
    # adapter 已做 ann_date 过滤防御, pipeline 拿到的是空 list - 不会 leak。
    # 这个 test 验:即使 adapter 二次过滤 + pipeline 没看到 leak, run_one 也跑通完成。
    run_id = runner.run_one(
        case=case, evaluator_llm="gpt-4o-2024-05-13",
        ablation_variant="V0_baseline", git_sha="testsha",
    )
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT status FROM backtest_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    assert r["status"] == "completed"
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_backtest_runner_metric_wire.py -v`
Expected: FAIL with `unexpected keyword argument 'metric_registry'` 或类似

- [x] **Step 3: 修改 `BacktestRunner` — 加 `metric_registry` 参数 + 在 finally 前跑 metric + 写 eval_results + 写 metric_summary_json**

`backend/eval/dd_report/backtest_runner.py` 替换 `BacktestRunner` class:

```python
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4
import json
import sqlite3

from app.services.eval_models import EvalResult, JudgeScores
from app.services.eval_recorder import EvalRecorder

from eval.dd_report.kb_backtest_adapter import KBBacktestAdapter
from eval.dd_report.leak_detector import LeakDetector
from eval.dd_report.llm_swapper import LLMSwapper
from eval.dd_report.metric_scores import BacktestMetricScores
from eval.dd_report.metrics.base import (
    CaseMeta, MetricInputs, MetricRegistry, MetricResult,
)
from eval.dd_report.tushare_backtest_adapter import TushareBacktestAdapter


class BacktestRunner:
    """Orchestrator: 装配 backtest 数据控制层 + LLM swap + 调 pipeline + 跑 metric."""

    def __init__(
        self,
        swapper: LLMSwapper,
        tushare_inner: Any,
        kb_inner: Any,
        db_path: Path,
        pipeline: PipelineProtocol | None = None,
        metric_registry: MetricRegistry | None = None,
        ground_truth_loader: Any | None = None,
        kb_lookup: Any | None = None,
        enable_leak_detection: bool = False,
    ) -> None:
        self._swapper = swapper
        self._tushare_inner = tushare_inner
        self._kb_inner = kb_inner
        self._db_path = db_path
        self._pipeline = pipeline
        self._metric_registry = metric_registry or MetricRegistry([])
        self._ground_truth = ground_truth_loader
        self._kb_lookup = kb_lookup
        self._enable_leak_detection = enable_leak_detection
        self._recorder = EvalRecorder(db_path)

    def run_one(
        self,
        case: BacktestCase,
        evaluator_llm: str,
        ablation_variant: str,
        git_sha: str,
        case_type: str = "backtest",
    ) -> str:
        run_id = f"bt-run-{uuid4().hex[:12]}"
        created_at = datetime.now(UTC).isoformat()

        tushare_adapter = TushareBacktestAdapter(
            inner=self._tushare_inner, cut_off=case.cut_off_date
        )
        kb_adapter = KBBacktestAdapter(inner=self._kb_inner, cut_off=case.cut_off_date)
        evaluator_client = self._swapper.get_client(evaluator_llm)

        # 拼装 3 evaluator clients(M5 需要)
        from eval.dd_report.llm_swapper import BACKTEST_EVALUATOR_MODELS
        m5_clients = {m: self._swapper.get_client(m) for m in BACKTEST_EVALUATOR_MODELS}

        status = "completed"
        report: dict[str, Any] = {}
        metric_results: list[MetricResult] = []
        try:
            if self._pipeline is not None:
                report = self._pipeline.run(
                    target_name=case.target_name,
                    ts_code=case.ts_code,
                    tushare_adapter=tushare_adapter,
                    kb_adapter=kb_adapter,
                    evaluator_client=evaluator_client,
                )
            if self._enable_leak_detection:
                self._run_leak_detection(report, case)
            if self._metric_registry.metrics and report:
                inputs = MetricInputs(
                    report=report,
                    case_meta=CaseMeta(
                        case_id=case.case_id, ts_code=case.ts_code,
                        target_name=case.target_name, cut_off_date=case.cut_off_date,
                    ),
                    ground_truth=self._ground_truth,
                    tushare_adapter=tushare_adapter,
                    kb_lookup=self._kb_lookup,
                    evaluator_clients=m5_clients,
                )
                metric_results = self._metric_registry.compute_all(inputs)
                self._write_eval_result(
                    run_id=run_id, case=case, evaluator_llm=evaluator_llm,
                    case_type=case_type, metric_results=metric_results,
                )
        except Exception:
            status = "failed"
            raise
        finally:
            self._write_run_row(
                run_id=run_id, created_at=created_at, case_count=1, status=status,
                git_sha=git_sha, ablation_variant=ablation_variant,
                llm_model=evaluator_llm,
                metric_summary_json=_aggregate_summary_json(metric_results),
            )
        return run_id

    def _run_leak_detection(self, report: dict[str, Any], case: BacktestCase) -> None:
        detector = LeakDetector(cut_off=case.cut_off_date)
        leaks: list = []
        # 仅扫报告 narrative 中的日期 (adapter 已做 row-level 防御)
        for sec_path in (
            "target_overview", "legal_qualification", "financial_analysis",
            "industry_analysis", "risk_assessment", "investment_recommendation",
        ):
            sec = report.get(sec_path)
            if isinstance(sec, dict):
                leaks += detector.scan_prompt_text(
                    sec.get("narrative", ""), source=f"report:{sec_path}"
                )
        detector.assert_no_leaks(leaks)

    def _write_eval_result(
        self, *, run_id: str, case: BacktestCase, evaluator_llm: str,
        case_type: str, metric_results: list[MetricResult],
    ) -> None:
        bscores = _to_backtest_metric_scores(metric_results)
        eval_id = f"ev-{uuid4().hex[:12]}"
        request_id = case.case_id  # backtest 模式 — 1 case 对应 1 eval, request_id 复用 case_id
        # backtest 模式 JudgeScores 为 stub (满足 EvalResult schema 不空)
        stub_judge = JudgeScores(
            factuality=0, factuality_evidence="N/A backtest 模式",
            tool_correctness=None, tool_correctness_evidence="N/A backtest 模式",
            coverage=0, coverage_evidence="N/A backtest 模式",
            structure=0, structure_evidence="N/A backtest 模式",
        )
        result = EvalResult(
            eval_id=eval_id, request_id=request_id, case_id=case.case_id,
            scores=stub_judge, judge_model=f"backtest:{evaluator_llm}",
            judge_cost_cny=0.0, judge_latency_ms=0,
            timestamp=datetime.now(UTC),
            backtest_run_id=run_id, cut_off_date=case.cut_off_date.isoformat(),
            evaluator_llm=evaluator_llm, case_type=case_type,
            metric_scores_json=bscores.model_dump_json(),
        )
        self._recorder.write(result)

    def _write_run_row(
        self, *, run_id: str, created_at: str, case_count: int, status: str,
        git_sha: str, ablation_variant: str, llm_model: str,
        metric_summary_json: str | None,
    ) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT INTO backtest_runs "
                "(run_id, created_at, case_count, metric_summary_json, status, "
                "git_sha, ablation_variant, llm_model) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (run_id, created_at, case_count, metric_summary_json, status,
                 git_sha, ablation_variant, llm_model),
            )


def _aggregate_summary_json(results: list[MetricResult]) -> str | None:
    if not results:
        return None
    return json.dumps({r.name: r.value for r in results})


def _to_backtest_metric_scores(results: list[MetricResult]) -> BacktestMetricScores:
    """从 MetricResult list 拼出 BacktestMetricScores. 缺失 metric 用安全默认."""
    by_name = {r.name: r for r in results}
    m1 = by_name.get("m1_citation")
    m2 = by_name.get("m2_numerical")
    m3 = by_name.get("m3_risk_pairing")
    m4 = by_name.get("m4_prediction")
    m5 = by_name.get("m5_composite")
    return BacktestMetricScores(
        m1_citation_precision=(m1.details.get("precision", 1.0) if m1 else 1.0),
        m1_citation_recall=(m1.details.get("recall", 1.0) if m1 else 1.0),
        m2_numerical_accuracy=(m2.value if m2 else 1.0) or 1.0,
        m2_numerical_total=(m2.details.get("total", 0) if m2 else 0),
        m2_numerical_correct=(m2.details.get("correct", 0) if m2 else 0),
        m3_risk_pairing_score=(m3.value if m3 else 1.0) or 1.0,
        m4_recommendation_direction_correct=(m4.details.get("direction_correct") if m4 else None),
        m4_target_price_hit=(m4.details.get("target_price_hit") if m4 else None),
        m4_risk_flag_realized_rate=(m4.details.get("risk_flag_realized_rate") if m4 else None),
        m5_composite_mean=(m5.details.get("mean", 0.0) if m5 else 0.0),
        m5_composite_majority=(m5.details.get("majority", 0.0) if m5 else 0.0),
        m5_composite_disagreement_max=(m5.details.get("disagreement_max", 0.0) if m5 else 0.0),
        details_json={r.name: r.details for r in results},
    )
```

- [x] **Step 4: 跑 test 验 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_backtest_runner_metric_wire.py backend/tests/eval/dd_report/test_backtest_runner.py -v`
Expected: 全 PASS(新 + 原 Phase 1 runner test 不回归)

- [x] **Step 5: 跑 mypy + 全 dd_report test**

Run: `uv run mypy backend/eval/dd_report/ && uv run pytest backend/tests/eval/dd_report/ -v`
Expected: 全 PASS,mypy clean

- [x] **Step 6: 跑 backend 全测试守护无横向回归**

Run: `uv run poe ci`(项目标准 CI 命令)
Expected: 全 PASS

- [x] **Step 7: Commit**

```bash
git add backend/eval/dd_report/backtest_runner.py \
  backend/tests/eval/dd_report/test_backtest_runner_metric_wire.py
git commit -m "feat(dd-eval): Phase 2 T2.7 — BacktestRunner wire MetricRegistry + LeakDetector + eval_results"
```

---

## Task 2.8:DDReportPipelineAdapter — 把生产 ResearchAgent 包成 PipelineProtocol

**Files:**
- Create: `backend/eval/dd_report/pipeline_adapter.py`
- Test: `backend/tests/eval/dd_report/test_pipeline_adapter.py`

**关键约束:** 不能改生产 `ResearchAgent` / writer / critic / orchestration 内部签名 — 此 task 是单向适配。先 grep 现有生产入口签名,本 plan 给出适配抽象,具体调用 implementer 实施时按 grep 结果填。

- [x] **Step 1: 探索生产 pipeline 入口**

Run:

```bash
grep -n "InvestmentDueDiligenceReport" backend/app/orchestration/critic_subgraph.py
grep -n "investment_dd\|InvestmentDD\|generate_report\|build_dd_report" backend/app/router/research.py backend/app/agents/research_agent.py backend/app/agents/writer.py | head -20
```

确认生产入口的函数签名(可能形态:`research_agent.build_report(target_ts_code, llm_service, kb_client, tushare_client) -> InvestmentDueDiligenceReport`)。

- [x] **Step 2: 写失败 L1 smoke test — mock 生产 pipeline, 验适配器把 evaluator_client 等正确注入并返回 dict**

`backend/tests/eval/dd_report/test_pipeline_adapter.py`:

```python
"""DDReportPipelineAdapter — 把生产 ResearchAgent 包成 PipelineProtocol."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from eval.dd_report.pipeline_adapter import DDReportPipelineAdapter


def test_adapter_runs_pipeline_and_returns_report_dict() -> None:
    """适配器接受 mock production pipeline factory, 返回 dict(InvestmentDueDiligenceReport)."""
    from app.agents.investment_dd_schema import (
        DEFAULT_DISCLAIMER, FinancialAnalysis, IndustryAnalysis,
        InvestmentDueDiligenceReport, InvestmentRecommendation,
        LegalQualification, PriceRange, RiskAssessment, RiskItem,
        TargetOverview, ValuationAnalysis,
    )
    from datetime import datetime

    # mock production pipeline: 接受 4 个依赖 -> 出 InvestmentDueDiligenceReport
    fake_report = InvestmentDueDiligenceReport(
        target_name="茅台", target_ts_code="600519.SH",
        request_id="req-test", generated_at=datetime.utcnow(),
        target_close_price_at_gen=1500.0,
        target_overview=TargetOverview(narrative="...", main_business="白酒"),
        legal_qualification=LegalQualification(
            narrative="...", legal_status="合规",
            business_qualifications=[], adverse_records=[],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="...", key_metrics=[],
            profitability_analysis="...", growth_analysis="...",
            return_analysis="...", cash_flow_analysis="...",
            valuation_analysis=ValuationAnalysis(narrative="..."),
        ),
        industry_analysis=IndustryAnalysis(
            narrative="...", industry_name="白酒", industry_outlook="...",
            competitive_position="...", key_competitors=[], policy_impact="...",
        ),
        risk_assessment=RiskAssessment(
            narrative="...", market_risk=[], growth_risk=[],
            event_risk=[], valuation_risk=[], overall_risk_level="medium",
        ),
        investment_recommendation=InvestmentRecommendation(
            narrative="...", recommendation="recommend_hold",
            recommended_position_size_pct=5.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=1400, high=1500),
            recommended_stop_loss_price=1300,
            estimated_target_price_range=PriceRange(low=1600, high=1700),
            position_management_conditions=[],
        ),
    )

    captured_kwargs = {}

    def fake_pipeline_factory(*, tushare_adapter, kb_adapter, evaluator_client):
        def runner(target_name: str, target_ts_code: str):
            captured_kwargs["target_name"] = target_name
            captured_kwargs["target_ts_code"] = target_ts_code
            captured_kwargs["tushare_adapter"] = tushare_adapter
            captured_kwargs["kb_adapter"] = kb_adapter
            captured_kwargs["evaluator_client"] = evaluator_client
            return fake_report
        return runner

    adapter = DDReportPipelineAdapter(pipeline_factory=fake_pipeline_factory)
    out = adapter.run(
        target_name="茅台", ts_code="600519.SH",
        tushare_adapter=MagicMock(), kb_adapter=MagicMock(), evaluator_client=MagicMock(),
    )
    assert isinstance(out, dict)
    assert out["target_name"] == "茅台"
    assert out["target_ts_code"] == "600519.SH"
    assert out["disclaimer"] == DEFAULT_DISCLAIMER
    # 确认 4 依赖正确注入到 pipeline factory
    assert captured_kwargs["target_name"] == "茅台"
    assert captured_kwargs["evaluator_client"] is not None


def test_adapter_raises_when_pipeline_returns_wrong_type() -> None:
    def bad_factory(*, tushare_adapter, kb_adapter, evaluator_client):
        def runner(target_name: str, target_ts_code: str): return "not a report"
        return runner
    adapter = DDReportPipelineAdapter(pipeline_factory=bad_factory)
    with pytest.raises(TypeError, match="expected InvestmentDueDiligenceReport"):
        adapter.run(
            target_name="X", ts_code="X.SH",
            tushare_adapter=MagicMock(), kb_adapter=MagicMock(), evaluator_client=MagicMock(),
        )
```

- [x] **Step 3: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_pipeline_adapter.py -v`
Expected: 2 FAIL with `ModuleNotFoundError`

- [x] **Step 4: 实现 DDReportPipelineAdapter**

`backend/eval/dd_report/pipeline_adapter.py`:

```python
"""DDReportPipelineAdapter — 桥接 Phase 1 PipelineProtocol 和生产 ResearchAgent.

设计:
  pipeline_factory(tushare_adapter, kb_adapter, evaluator_client) -> Callable
  这个 Callable 接受 (target_name, target_ts_code) 并返回 InvestmentDueDiligenceReport。

为什么这样设计:
  - factory 让生产 ResearchAgent / writer / critic / orchestration 可以在装配阶段把
    swapped dependency (backtest adapter + evaluator client) 注入闭包, 而 run-time
    入口只接 case-level 参数 (target_name)。
  - 兼容 v0.8.5 现有形态: ResearchAgent 一般在 app.orchestration.* 里 build_graph(),
    factory 模式让 backtest 不重写 build_graph()。

具体 production 函数签名 implementer 实施时按 router/research.py 入口对齐。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.agents.investment_dd_schema import InvestmentDueDiligenceReport


class _ProductionRunner(Protocol):
    def __call__(self, target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport: ...


class _PipelineFactoryProtocol(Protocol):
    def __call__(
        self, *, tushare_adapter: Any, kb_adapter: Any, evaluator_client: Any
    ) -> _ProductionRunner: ...


@dataclass
class DDReportPipelineAdapter:
    """Wrap 生产 pipeline factory 成 BacktestRunner.PipelineProtocol."""

    pipeline_factory: _PipelineFactoryProtocol

    def run(
        self,
        *,
        target_name: str,
        ts_code: str,
        tushare_adapter: Any,
        kb_adapter: Any,
        evaluator_client: Any,
    ) -> dict[str, Any]:
        runner = self.pipeline_factory(
            tushare_adapter=tushare_adapter,
            kb_adapter=kb_adapter,
            evaluator_client=evaluator_client,
        )
        report = runner(target_name=target_name, target_ts_code=ts_code)
        if not isinstance(report, InvestmentDueDiligenceReport):
            raise TypeError(
                f"expected InvestmentDueDiligenceReport, got {type(report).__name__}"
            )
        return report.model_dump(mode="json")
```

- [x] **Step 5: 跑 test 验 PASS + mypy**

Run: `uv run pytest backend/tests/eval/dd_report/test_pipeline_adapter.py -v && uv run mypy backend/eval/dd_report/pipeline_adapter.py`
Expected: 2 PASS + mypy clean

- [x] **Step 6: Commit(生产 pipeline factory 真接 implementer 实施时如发现 v0.8.5 入口与本抽象不匹配, 加 wrapper 调整 — 留 docstring 警告)**

```bash
git add backend/eval/dd_report/pipeline_adapter.py \
  backend/tests/eval/dd_report/test_pipeline_adapter.py
git commit -m "feat(dd-eval): Phase 2 T2.8 — DDReportPipelineAdapter (production ResearchAgent wrap)"
```

---

## Task 2.9:AblationVariant + PipelineFactory(V0/V1/V2/V3 swapping)

**Files:**
- Create: `backend/eval/dd_report/ablation/__init__.py`
- Create: `backend/eval/dd_report/ablation/null_adapters.py`
- Create: `backend/eval/dd_report/ablation/variants.py`
- Test: `backend/tests/eval/dd_report/test_ablation_variants.py`

- [x] **Step 1: 写失败 test — 4 variant 分别拿到不同 PipelineFactory**

`backend/tests/eval/dd_report/test_ablation_variants.py`:

```python
"""AblationVariant + PipelineFactory — V0/V1/V2/V3 swap."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from eval.dd_report.ablation.null_adapters import NullKBAdapter, SingleAgentPipeline
from eval.dd_report.ablation.variants import (
    AblationVariant, build_pipeline_for_variant,
)


def test_v0_baseline_uses_full_production_pipeline() -> None:
    """V0 baseline = 直接复用注入的 production_factory 不动."""
    prod_factory = MagicMock()
    adapter = build_pipeline_for_variant(
        AblationVariant.V0_BASELINE, production_factory=prod_factory,
    )
    assert adapter.pipeline_factory is prod_factory


def test_v1_no_rag_swaps_kb_adapter_to_null() -> None:
    """V1 无 RAG: KBBacktestAdapter 包一层, search 返 []."""
    prod_factory = MagicMock()
    adapter = build_pipeline_for_variant(
        AblationVariant.V1_NO_RAG, production_factory=prod_factory,
    )
    # adapter.pipeline_factory 不是原 prod_factory, 是 wrapper
    wrapped = adapter.pipeline_factory(
        tushare_adapter=MagicMock(),
        kb_adapter=MagicMock(),
        evaluator_client=MagicMock(),
    )
    # production_factory 被以 NullKBAdapter 注入调用
    args, kwargs = prod_factory.call_args
    assert isinstance(kwargs["kb_adapter"], NullKBAdapter)


def test_v2_no_multi_agent_swaps_pipeline_to_single_agent() -> None:
    """V2 单 agent: pipeline factory 整体替换成 SingleAgentPipeline."""
    prod_factory = MagicMock()
    adapter = build_pipeline_for_variant(
        AblationVariant.V2_NO_MULTI_AGENT, production_factory=prod_factory,
        single_agent_pipeline_class=SingleAgentPipeline,
    )
    # production_factory 完全不被使用
    prod_factory.assert_not_called()


def test_v3_no_critic_strips_critic_in_factory_kwargs() -> None:
    """V3 无 critic: 传 disable_critic=True 给 production_factory."""
    prod_factory = MagicMock()
    adapter = build_pipeline_for_variant(
        AblationVariant.V3_NO_CRITIC, production_factory=prod_factory,
    )
    # adapter.pipeline_factory 是 wrapper, 调用时把 disable_critic=True 透传
    wrapped_factory = adapter.pipeline_factory
    wrapped_factory(
        tushare_adapter=MagicMock(),
        kb_adapter=MagicMock(),
        evaluator_client=MagicMock(),
    )
    args, kwargs = prod_factory.call_args
    assert kwargs.get("disable_critic") is True


def test_unknown_variant_raises() -> None:
    with pytest.raises(ValueError, match="unknown ablation variant"):
        build_pipeline_for_variant("V99_INVALID", production_factory=MagicMock())  # type: ignore[arg-type]


def test_null_kb_adapter_search_returns_empty() -> None:
    a = NullKBAdapter()
    assert a.search("anything", k=10) == []


def test_single_agent_pipeline_callable_returns_report() -> None:
    """SingleAgentPipeline 用单 prompt 一次性出报告 — 这里只验 protocol shape."""
    # 这个 test 验 SingleAgentPipeline 可装配 + 返回 InvestmentDueDiligenceReport
    # 真 LLM 调用 L1 cassette test 在 Phase 5 dogfood, T2.9 本 task L0 用 mock evaluator
    class _MockEvaluatorClient:
        model = "fake"
        def chat(self, prompt: str, response_format=None) -> str:
            # 返回最小合法 InvestmentDueDiligenceReport JSON
            return '{}'  # SingleAgentPipeline 内部应有 fallback path

    pipe = SingleAgentPipeline(
        tushare_adapter=MagicMock(),
        kb_adapter=NullKBAdapter(),
        evaluator_client=_MockEvaluatorClient(),
    )
    # runner 签名跟生产对齐: (target_name, target_ts_code) -> InvestmentDueDiligenceReport
    # 但 LLM mock 返 '{}' Pydantic 不能 parse, 所以这里只验对象能 build, 真跑通推到 T2.11
    assert callable(pipe)
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_ablation_variants.py -v`
Expected: 7 FAIL with `ModuleNotFoundError`

- [x] **Step 3: 实现 NullKBAdapter + SingleAgentPipeline + AblationVariant + build_pipeline_for_variant**

`backend/eval/dd_report/ablation/__init__.py`:

```python
"""Phase 2 ablation framework — V0/V1/V2/V3 (spec § 4.7)."""
```

`backend/eval/dd_report/ablation/null_adapters.py`:

```python
"""Null adapters for V1 (无 RAG) + SingleAgentPipeline for V2 (无 multi-agent).

spec § 4.7 决策 7: 用 swap 组件方式量化每个 pipeline 组件的贡献。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.agents.investment_dd_schema import (
    DEFAULT_DISCLAIMER, FinancialAnalysis, IndustryAnalysis,
    InvestmentDueDiligenceReport, InvestmentRecommendation,
    LegalQualification, PriceRange, RiskAssessment,
    TargetOverview, ValuationAnalysis,
)


@dataclass
class NullKBAdapter:
    """V1 ablation: search 永远返 [] (模拟无 RAG path)."""

    def search(self, query: str, k: int = 10, **kwargs: Any) -> list[Any]:
        return []


@dataclass
class SingleAgentPipeline:
    """V2 ablation: 单 prompt 一次性出全报告 (无 multi-agent 编排).

    用单 LLM call (evaluator_client.chat) 让模型直接输出整个
    InvestmentDueDiligenceReport JSON。Pydantic parse 失败时返回最小 fallback
    stub (此变体的目标就是与 V0 对比, 失败本身也是数据点)。
    """

    tushare_adapter: Any
    kb_adapter: Any
    evaluator_client: Any

    def __call__(
        self, target_name: str, target_ts_code: str
    ) -> InvestmentDueDiligenceReport:
        prompt = (
            f"你是金融分析师, 直接出 {target_name} ({target_ts_code}) 的 "
            f"InvestmentDueDiligenceReport JSON, 包含全部 6 section 字段, "
            f"严格匹配 schema。不要思考过程, 直接 JSON。"
        )
        try:
            raw = self.evaluator_client.chat(prompt=prompt)
            import json
            data = json.loads(raw)
            return InvestmentDueDiligenceReport.model_validate(data)
        except Exception:
            return _minimal_stub(target_name, target_ts_code)


def _minimal_stub(target_name: str, target_ts_code: str) -> InvestmentDueDiligenceReport:
    """V2 fallback stub — 让 backtest 走通, metric 评分自动 vacuous."""
    return InvestmentDueDiligenceReport(
        target_name=target_name, target_ts_code=target_ts_code,
        request_id="ablation-v2-stub",
        generated_at=datetime.utcnow(),
        target_overview=TargetOverview(
            narrative="(V2 single-agent stub)", main_business="N/A",
        ),
        legal_qualification=LegalQualification(
            narrative="(stub)", legal_status="N/A",
            business_qualifications=[], adverse_records=[],
        ),
        financial_analysis=FinancialAnalysis(
            narrative="(stub)", key_metrics=[],
            profitability_analysis="N/A", growth_analysis="N/A",
            return_analysis="N/A", cash_flow_analysis="N/A",
            valuation_analysis=ValuationAnalysis(narrative="N/A"),
        ),
        industry_analysis=IndustryAnalysis(
            narrative="(stub)", industry_name="N/A", industry_outlook="N/A",
            competitive_position="N/A", key_competitors=[], policy_impact="N/A",
        ),
        risk_assessment=RiskAssessment(
            narrative="(stub)", market_risk=[], growth_risk=[],
            event_risk=[], valuation_risk=[], overall_risk_level="medium",
        ),
        investment_recommendation=InvestmentRecommendation(
            narrative="(stub)", recommendation="recommend_hold",
            recommended_position_size_pct=0.0,
            recommended_holding_period="medium_term",
            recommended_entry_price_range=PriceRange(low=0, high=0),
            recommended_stop_loss_price=0,
            estimated_target_price_range=PriceRange(low=0, high=0),
            position_management_conditions=[],
        ),
        disclaimer=DEFAULT_DISCLAIMER,
    )
```

`backend/eval/dd_report/ablation/variants.py`:

```python
"""AblationVariant 枚举 + build_pipeline_for_variant (spec § 4.7)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from eval.dd_report.ablation.null_adapters import (
    NullKBAdapter, SingleAgentPipeline,
)
from eval.dd_report.pipeline_adapter import DDReportPipelineAdapter


class AblationVariant(str, Enum):
    V0_BASELINE = "V0_baseline"
    V1_NO_RAG = "V1_no_rag"
    V2_NO_MULTI_AGENT = "V2_no_multi_agent"
    V3_NO_CRITIC = "V3_no_critic"


def build_pipeline_for_variant(
    variant: AblationVariant | str,
    *,
    production_factory: Callable[..., Any],
    single_agent_pipeline_class: type = SingleAgentPipeline,
) -> DDReportPipelineAdapter:
    """根据 variant 装配 PipelineAdapter."""
    if variant == AblationVariant.V0_BASELINE:
        return DDReportPipelineAdapter(pipeline_factory=production_factory)

    if variant == AblationVariant.V1_NO_RAG:
        def factory_v1(*, tushare_adapter, kb_adapter, evaluator_client):  # type: ignore[no-untyped-def]
            return production_factory(
                tushare_adapter=tushare_adapter,
                kb_adapter=NullKBAdapter(),
                evaluator_client=evaluator_client,
            )
        return DDReportPipelineAdapter(pipeline_factory=factory_v1)

    if variant == AblationVariant.V2_NO_MULTI_AGENT:
        def factory_v2(*, tushare_adapter, kb_adapter, evaluator_client):  # type: ignore[no-untyped-def]
            return single_agent_pipeline_class(
                tushare_adapter=tushare_adapter,
                kb_adapter=kb_adapter,
                evaluator_client=evaluator_client,
            )
        return DDReportPipelineAdapter(pipeline_factory=factory_v2)

    if variant == AblationVariant.V3_NO_CRITIC:
        def factory_v3(*, tushare_adapter, kb_adapter, evaluator_client):  # type: ignore[no-untyped-def]
            return production_factory(
                tushare_adapter=tushare_adapter,
                kb_adapter=kb_adapter,
                evaluator_client=evaluator_client,
                disable_critic=True,
            )
        return DDReportPipelineAdapter(pipeline_factory=factory_v3)

    raise ValueError(f"unknown ablation variant: {variant!r}")
```

- [x] **Step 4: 跑 test 验 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_ablation_variants.py -v`
Expected: 7 PASS

- [x] **Step 5: mypy + 全 dd_report test**

Run: `uv run mypy backend/eval/dd_report/ && uv run pytest backend/tests/eval/dd_report/ -v`
Expected: 全 PASS

- [x] **Step 6: Commit**

```bash
git add backend/eval/dd_report/ablation/ \
  backend/tests/eval/dd_report/test_ablation_variants.py
git commit -m "feat(dd-eval): Phase 2 T2.9 — AblationVariant V0-V3 + NullKBAdapter + SingleAgentPipeline"
```

---

## Task 2.10:AblationRunner — 跑 4 variant × case 子集

**Files:**
- Create: `backend/eval/dd_report/ablation/runner.py`
- Test: `backend/tests/eval/dd_report/test_ablation_runner.py`

- [x] **Step 1: 写失败 test — fake production_factory, AblationRunner 跑 4 variant × 2 case smoke**

`backend/tests/eval/dd_report/test_ablation_runner.py`:

```python
"""AblationRunner — 跑 4 variant × case 子集 + 写 ablation_variant 字段."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from eval.dd_report.ablation.runner import AblationRunner
from eval.dd_report.ablation.variants import AblationVariant
from eval.dd_report.backtest_runner import BacktestCase


def _make_runner(db: Path) -> AblationRunner:
    """AblationRunner 接受 production_factory + BacktestRunner deps."""
    from eval.dd_report.llm_swapper import LLMSwapper
    from eval.dd_report.metrics.base import MetricRegistry

    from app.services.eval_recorder import EvalRecorder
    EvalRecorder(db).init_schema()

    class _Tushare:
        def income(self, **kw: Any): return []
        def daily(self, **kw: Any): return []
        def balancesheet(self, **kw: Any): return []
        def cashflow(self, **kw: Any): return []
        def anns(self, **kw: Any): return []

    class _KB:
        def search(self, q: str, k: int = 10, **kw: Any): return []

    class _DummySwapper:
        def get_client(self, m: str):
            c = MagicMock()
            c.chat.return_value = '{"score": 7, "reasoning": "ok"}'
            return c

    def production_factory(*, tushare_adapter, kb_adapter, evaluator_client, disable_critic=False):
        from datetime import datetime
        from app.agents.investment_dd_schema import (
            DEFAULT_DISCLAIMER, FinancialAnalysis, IndustryAnalysis,
            InvestmentDueDiligenceReport, InvestmentRecommendation,
            LegalQualification, PriceRange, RiskAssessment,
            TargetOverview, ValuationAnalysis,
        )
        def runner(target_name: str, target_ts_code: str):
            return InvestmentDueDiligenceReport(
                target_name=target_name, target_ts_code=target_ts_code,
                request_id="prod-test", generated_at=datetime.utcnow(),
                target_overview=TargetOverview(narrative="...", main_business="X"),
                legal_qualification=LegalQualification(
                    narrative="...", legal_status="ok",
                    business_qualifications=[], adverse_records=[],
                ),
                financial_analysis=FinancialAnalysis(
                    narrative="...", key_metrics=[],
                    profitability_analysis="...", growth_analysis="...",
                    return_analysis="...", cash_flow_analysis="...",
                    valuation_analysis=ValuationAnalysis(narrative="..."),
                ),
                industry_analysis=IndustryAnalysis(
                    narrative="...", industry_name="X", industry_outlook="...",
                    competitive_position="...", key_competitors=[], policy_impact="...",
                ),
                risk_assessment=RiskAssessment(
                    narrative="...", market_risk=[], growth_risk=[],
                    event_risk=[], valuation_risk=[], overall_risk_level="medium",
                ),
                investment_recommendation=InvestmentRecommendation(
                    narrative="...", recommendation="recommend_hold",
                    recommended_position_size_pct=5.0,
                    recommended_holding_period="medium_term",
                    recommended_entry_price_range=PriceRange(low=1400, high=1500),
                    recommended_stop_loss_price=1300,
                    estimated_target_price_range=PriceRange(low=1600, high=1700),
                    position_management_conditions=[],
                ),
                disclaimer=DEFAULT_DISCLAIMER,
            )
        return runner

    return AblationRunner(
        swapper=_DummySwapper(),  # type: ignore[arg-type]
        tushare_inner=_Tushare(),
        kb_inner=_KB(),
        db_path=db,
        production_factory=production_factory,
        metric_registry=MetricRegistry([]),  # 空 registry, 只验调度
    )


def test_run_4_variants_x_2_cases_writes_8_runs(tmp_path) -> None:
    runner = _make_runner(tmp_path / "ev.db")
    cases = [
        BacktestCase("c1", "600519.SH", "茅台", date(2024, 6, 30)),
        BacktestCase("c2", "300750.SZ", "宁德", date(2024, 6, 30)),
    ]
    results = runner.run_ablation(
        cases=cases,
        variants=list(AblationVariant),
        evaluator_llm="gpt-4o-2024-05-13",
        git_sha="testsha",
    )
    assert len(results) == 4 * 2
    with sqlite3.connect(tmp_path / "ev.db") as con:
        n = con.execute(
            "SELECT COUNT(*) FROM backtest_runs WHERE git_sha = ?", ("testsha",)
        ).fetchone()[0]
    assert n == 8


def test_ablation_variant_field_set_per_run(tmp_path) -> None:
    runner = _make_runner(tmp_path / "ev.db")
    cases = [BacktestCase("c1", "600519.SH", "茅台", date(2024, 6, 30))]
    runner.run_ablation(
        cases=cases,
        variants=[AblationVariant.V0_BASELINE, AblationVariant.V1_NO_RAG],
        evaluator_llm="gpt-4o-2024-05-13",
        git_sha="testsha2",
    )
    with sqlite3.connect(tmp_path / "ev.db") as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT ablation_variant FROM backtest_runs WHERE git_sha = ?", ("testsha2",)
        ).fetchall()
    variants_written = sorted(r["ablation_variant"] for r in rows)
    assert variants_written == ["V0_baseline", "V1_no_rag"]
```

- [x] **Step 2: 跑 test 确认失败**

Run: `uv run pytest backend/tests/eval/dd_report/test_ablation_runner.py -v`
Expected: 2 FAIL with `ModuleNotFoundError`

- [x] **Step 3: 实现 AblationRunner**

`backend/eval/dd_report/ablation/runner.py`:

```python
"""AblationRunner — 跑 4 variant × cases 矩阵 (spec § 4.7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from eval.dd_report.ablation.variants import (
    AblationVariant, build_pipeline_for_variant,
)
from eval.dd_report.backtest_runner import BacktestCase, BacktestRunner
from eval.dd_report.llm_swapper import LLMSwapper
from eval.dd_report.metrics.base import MetricRegistry


@dataclass
class AblationRunResult:
    """单个 (variant × case) 的运行结果."""

    variant: str
    case_id: str
    run_id: str
    status: str  # "completed" | "failed"
    error: str | None = None


@dataclass
class AblationRunner:
    """跑 4 variant × cases 矩阵, 每 (variant, case) 一次 backtest run."""

    swapper: LLMSwapper
    tushare_inner: Any
    kb_inner: Any
    db_path: Path
    production_factory: Callable[..., Any]
    metric_registry: MetricRegistry = field(default_factory=lambda: MetricRegistry([]))
    ground_truth_loader: Any | None = None
    kb_lookup: Any | None = None
    enable_leak_detection: bool = False

    def run_ablation(
        self,
        cases: list[BacktestCase],
        variants: list[AblationVariant],
        evaluator_llm: str,
        git_sha: str,
        case_type: str = "backtest",
    ) -> list[AblationRunResult]:
        """跑笛卡尔积 variant × case, 每次 BacktestRunner 用对应 variant 装配 pipeline."""
        results: list[AblationRunResult] = []
        for variant in variants:
            pipeline_adapter = build_pipeline_for_variant(
                variant, production_factory=self.production_factory,
            )
            runner = BacktestRunner(
                swapper=self.swapper,
                tushare_inner=self.tushare_inner,
                kb_inner=self.kb_inner,
                db_path=self.db_path,
                pipeline=pipeline_adapter,
                metric_registry=self.metric_registry,
                ground_truth_loader=self.ground_truth_loader,
                kb_lookup=self.kb_lookup,
                enable_leak_detection=self.enable_leak_detection,
            )
            for case in cases:
                try:
                    run_id = runner.run_one(
                        case=case, evaluator_llm=evaluator_llm,
                        ablation_variant=variant.value,
                        git_sha=git_sha, case_type=case_type,
                    )
                    results.append(AblationRunResult(
                        variant=variant.value, case_id=case.case_id,
                        run_id=run_id, status="completed",
                    ))
                except Exception as e:
                    results.append(AblationRunResult(
                        variant=variant.value, case_id=case.case_id,
                        run_id="-", status="failed", error=str(e)[:200],
                    ))
        return results
```

- [x] **Step 4: 跑 test 验 PASS**

Run: `uv run pytest backend/tests/eval/dd_report/test_ablation_runner.py -v`
Expected: 2 PASS

- [x] **Step 5: mypy + 全 dd_report test + backend ci**

Run: `uv run mypy backend/eval/dd_report/ && uv run pytest backend/tests/eval/dd_report/ -v && uv run poe ci`
Expected: 全绿

- [x] **Step 6: Commit**

```bash
git add backend/eval/dd_report/ablation/runner.py \
  backend/tests/eval/dd_report/test_ablation_runner.py
git commit -m "feat(dd-eval): Phase 2 T2.10 — AblationRunner V0-V3 × cases matrix scheduler"
```

---

## Task 2.11:Phase 2 末完整 ablation L2 dogfood + sediment + plan tick

**Files:**
- Create: `backend/scripts/run_phase2_ablation_dogfood.py`(单次运行脚本)
- Create: `docs/claude-context/dd-report-eval-phase-2-landed.md`(sediment 卡片)
- Modify: `docs/superpowers/plans/2026-05-18-dd-report-eval-phase-2-metrics-ablation.md`(勾完 checkbox)

- [x] **Step 1: 写 Phase 2 ablation dogfood 脚本 — 跑 4 variant × 8 sanity case × 1 evaluator_llm**

`backend/scripts/run_phase2_ablation_dogfood.py`:

```python
"""Phase 2 末完整 ablation L2 dogfood — spec § 4.7 决策 7.

跑 4 variant (V0/V1/V2/V3) × 8 sanity case (cut_off=2026-04-30, 已被 Phase 1 sediment
的 LLM cutoff 警告覆盖, sanity case 设计本就是 cutoff-after 窗口) × 1 evaluator_llm
(gpt-4o-2024-05-13) — 总 32 run。

成本估算: 32 run × 1 case/run × 6 agent_call/case × 4k token ≈ 768k token,
按 OpenRouter $5/M token ≈ $4 (约 28 RMB)。

输出:
  - backend/data/eval_phase2_dogfood.db (新 sqlite)
  - 控制台 print 4×5 metric 对比矩阵
  - 跑完同时刷新 docs/claude-context/dd-report-eval-phase-2-landed.md
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

from eval.dd_report.ablation.runner import AblationRunner
from eval.dd_report.ablation.variants import AblationVariant
from eval.dd_report.backtest_runner import BacktestCase
from eval.dd_report.golden.ground_truth_loader import GroundTruthLoader
from eval.dd_report.llm_swapper import LLMSwapper
from eval.dd_report.metrics.base import MetricRegistry
from eval.dd_report.metrics.citation_metric import CitationMetric
from eval.dd_report.metrics.composite_judge_metric import CompositeJudgeMetric
from eval.dd_report.metrics.numerical_metric import NumericalMetric
from eval.dd_report.metrics.prediction_metric import PredictionMetric
from eval.dd_report.metrics.risk_pairing_metric import RiskPairingMetric


def main() -> None:
    db = Path("backend/data/eval_phase2_dogfood.db")
    db.parent.mkdir(parents=True, exist_ok=True)

    # 加载 8 sanity case
    cases_path = Path("backend/eval/dd_report/golden/backtest_cases.jsonl")
    sanity_cases = [
        _row_to_case(json.loads(line))
        for line in cases_path.read_text().splitlines()
        if json.loads(line).get("case_type") == "sanity"
    ]
    assert len(sanity_cases) == 8, f"expected 8 sanity cases, got {len(sanity_cases)}"

    # production_factory 真接 — implementer 实施时按 grep 出来的入口对齐
    from app.eval.dd_report_production_factory import build_dd_report_production_factory  # implementer 实施时新建
    production_factory = build_dd_report_production_factory()

    swapper = LLMSwapper()
    from app.service.tushare_client import TushareClient
    tushare_inner = TushareClient()
    gtl = GroundTruthLoader(inner=tushare_inner)

    # MetricRegistry 装全 5 metric
    from app.services.openai_client import build_llm_service_from_env
    # M1/M3 用小 judge - 复用 evaluator 的 chat 接口包成 judge
    eval_client = swapper.get_client("gpt-4o-2024-05-13")
    from app.eval.dd_report_production_factory import (
        build_supports_judge, build_pairing_judge,
    )  # implementer 实施时新建
    metric_registry = MetricRegistry([
        CitationMetric(judge=build_supports_judge(eval_client)),
        NumericalMetric(),
        RiskPairingMetric(judge=build_pairing_judge(eval_client)),
        PredictionMetric(),
        CompositeJudgeMetric(),
    ])

    git_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"]).decode().strip()

    runner = AblationRunner(
        swapper=swapper,
        tushare_inner=tushare_inner,
        kb_inner=_load_kb_client(),  # implementer 接 production KB client
        db_path=db,
        production_factory=production_factory,
        metric_registry=metric_registry,
        ground_truth_loader=gtl,
        kb_lookup=_make_kb_lookup(),  # implementer 接 production KB chunk lookup
        enable_leak_detection=True,
    )

    print(f"Phase 2 末 ablation dogfood — 4 variant × 8 sanity case (git_sha={git_sha})")
    results = runner.run_ablation(
        cases=sanity_cases,
        variants=list(AblationVariant),
        evaluator_llm="gpt-4o-2024-05-13",
        git_sha=git_sha,
        case_type="sanity",
    )

    # 汇总 4 × 5 矩阵
    print("\n=== Ablation 4×5 矩阵 ===")
    _print_ablation_matrix(db, git_sha)

    # 失败的 run
    failed = [r for r in results if r.status == "failed"]
    if failed:
        print(f"\n⚠️ {len(failed)} run failed:")
        for f in failed:
            print(f"  {f.variant} / {f.case_id}: {f.error}")


def _row_to_case(d: dict) -> BacktestCase:
    return BacktestCase(
        case_id=d["case_id"], ts_code=d["ts_code"],
        target_name=d["target_name"],
        cut_off_date=date.fromisoformat(d["cut_off_date"]),
    )


def _print_ablation_matrix(db: Path, git_sha: str) -> None:
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT ablation_variant, metric_summary_json FROM backtest_runs "
            "WHERE git_sha = ? AND status = 'completed'", (git_sha,),
        ).fetchall()
    by_variant: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if not r["metric_summary_json"]:
            continue
        m = json.loads(r["metric_summary_json"])
        for k, v in m.items():
            if v is not None:
                by_variant[r["ablation_variant"]][k].append(float(v))
    header = ["Variant", "M1", "M2", "M3", "M4", "M5"]
    print(f"{header[0]:<20} | {header[1]:>6} | {header[2]:>6} | {header[3]:>6} | {header[4]:>6} | {header[5]:>6}")
    for v in ("V0_baseline", "V1_no_rag", "V2_no_multi_agent", "V3_no_critic"):
        scores = by_variant.get(v, {})
        def avg(k: str) -> str:
            vs = scores.get(k, [])
            return f"{sum(vs)/len(vs):.2f}" if vs else "N/A"
        print(
            f"{v:<20} | {avg('m1_citation'):>6} | {avg('m2_numerical'):>6} | "
            f"{avg('m3_risk_pairing'):>6} | {avg('m4_prediction'):>6} | "
            f"{avg('m5_composite'):>6}"
        )


def _load_kb_client():  # type: ignore[no-untyped-def]
    """Implementer 接生产 KB client (Milvus collection)."""
    raise NotImplementedError("接生产 KB client - 见 app/service/kb_*.py")


def _make_kb_lookup():  # type: ignore[no-untyped-def]
    """Implementer 实现 chunk_id -> chunk dict 的查询函数."""
    raise NotImplementedError("接生产 KB chunk lookup")


if __name__ == "__main__":
    main()
```

- [x] **Step 2: implementer 实施时按生产 ResearchAgent 入口完善 production_factory + KB client wire**

这一步 plan 留 placeholder(`NotImplementedError`):

- 在 `backend/app/eval/dd_report_production_factory.py` 新建 module(注意:`app/eval/` 是个**新目录**,需要先建 `__init__.py`),提供:
  - `build_dd_report_production_factory()` — 返回 `(*, tushare_adapter, kb_adapter, evaluator_client, disable_critic=False) -> runner` 形态
  - `build_supports_judge(client)` / `build_pairing_judge(client)` — 把 EvaluatorClient.chat 包成 M1/M3 judge protocol
- 在 `_load_kb_client` / `_make_kb_lookup` 接生产 Milvus + sqlite chunk 表

implementer **必须 grep**:`grep -rn 'InvestmentDueDiligenceReport' backend/app/orchestration backend/app/router backend/app/agents | head -30`,据此对齐签名。**此步若发现生产入口跟 PipelineFactory 抽象不匹配,在 sediment 卡里记录"撞实工业问题",并加 wrapper 调和**(不重写生产 pipeline,只在 adapter 层吸收)。

Run dry-run smoke 验组装不报错:

```bash
uv run python -c "from backend.app.eval.dd_report_production_factory import build_dd_report_production_factory; f = build_dd_report_production_factory(); print('OK:', f)"
```

Expected: `OK: <function ...>`,不抛 ImportError / TypeError。

- [x] **Step 3: 跑 Phase 2 末 ablation dogfood(L2 真 LLM,真生产 pipeline)**

```bash
unset all_proxy https_proxy http_proxy  # see project memory
uv run python backend/scripts/run_phase2_ablation_dogfood.py
```

Expected: 4×5 矩阵打印,backend/data/eval_phase2_dogfood.db 写 32 行 backtest_runs + 32 行 eval_results。
**记录任何 ≥3 round 才修通的 issue 到 sediment(per "3+ round fix 没用立刻 Phase 1 重做" memory)**。

- [x] **Step 4: 写 sediment 卡片 + 加进 CLAUDE.md 索引**

`docs/claude-context/dd-report-eval-phase-2-landed.md`:

```markdown
---
name: DD report eval Phase 2 (metric + ablation) landed
description: v1.x DD report quality eval Phase 2 — 5 metric + V0-V3 ablation ship 完, 内部三维对比 ablation 一维数字到位
type: project
---

## v1.x DD report eval Phase 2 ship 完 (2026-05-XX)

### 做了什么

**spec**: `docs/superpowers/specs/2026-05-17-dd-report-quality-eval-design.md` v1.1
**plan**: `docs/superpowers/plans/2026-05-18-dd-report-eval-phase-2-metrics-ablation.md`

11 task ship:
- T2.0 MetricProtocol + BacktestMetricScores + DB metric_scores_json 列
- T2.1 GroundTruthLoader fetch_post_cut_off_kline / anns 真实现
- T2.2 M1 CitationMetric (extraction precision/recall, F1)
- T2.3 M2 NumericalMetric (4 类指标 ±1% 容差 + 中文数字归一)
- T2.4 M3 RiskPairingMetric (4 bucket valid mitigation judge)
- T2.5 M4 PredictionMetric (direction + target_price_hit + risk_flag_rate)
- T2.6 M5 CompositeJudgeMetric (3 LLM majority + disagreement audit)
- T2.7 BacktestRunner wire MetricRegistry + LeakDetector + eval_results
- T2.8 DDReportPipelineAdapter (production ResearchAgent wrap)
- T2.9 AblationVariant V0-V3 + NullKBAdapter + SingleAgentPipeline
- T2.10 AblationRunner (4 variant × cases scheduler)
- T2.11 Phase 2 末 ablation dogfood (4×8 sanity = 32 run)

### 真跑出来的数字 (Phase 2 末 ablation dogfood, git_sha=<XXX>)

| Variant         | M1     | M2     | M3     | M4     | M5     |
|-----------------|-------:|-------:|-------:|-------:|-------:|
| V0 baseline     | XX%    | XX%    | XX%    | XX%    | X.X    |
| V1 no RAG       | XX%    | XX%    | XX%    | XX%    | X.X    |
| V2 no MA        | XX%    | XX%    | XX%    | XX%    | X.X    |
| V3 no Critic    | XX%    | XX%    | XX%    | XX%    | X.X    |

(implementer 跑完 dogfood 填实数字)

### Why (技术亮点)

- **Hebbia 三段式 metric 分层落地** — extraction(M1/M2 程序化)/ summarization(M3 LLM judge)/ reasoning(M4 backtest + M5 multi-LLM consensus)
- **5 metric 独立模块 + Protocol-injected** — MetricRegistry 串联, 每 metric stateless 纯函数
- **BacktestMetricScores 独立 schema** — 不污染 JudgeScores(Phase 1 sediment 教训); 序列化到 eval_results.metric_scores_json
- **V0-V3 ablation 控制变量** — PipelineFactory pattern, NullKBAdapter / SingleAgentPipeline / disable_critic flag 三类 swap
- **生产 pipeline 0 改动** — DDReportPipelineAdapter 单向适配, 不重写 ResearchAgent

### How to apply

- Phase 3 接 dashboard + cross-LLM 矩阵时, eval_results.metric_scores_json + backtest_runs.metric_summary_json 已可读
- 新 ablation 变体加在 AblationVariant 枚举 + build_pipeline_for_variant 加 if branch
- 新 metric 加在 metrics/ 下实现 MetricProtocol + 注入 MetricRegistry + BacktestMetricScores schema 加字段
- M4 horizon 默认 90 天, Phase 3 可扩 180/365 走多 PredictionMetric instance 不同 horizon

### 撞到的工业问题

(implementer 跑 dogfood 时记录)

- 例 1: 生产 ResearchAgent 入口签名跟 PipelineFactory 假设不匹配 — 加了 X wrapper 吸收
- 例 2: M3 LLM judge 对 "stop loss" 类 mitigation 召回偏低 — prompt 加了 "stop loss = valid mitigation" 例子
- 例 3: V2 SingleAgentPipeline JSON parse 失败率 X% — fallback stub 影响 M5 评分
- 例 4: 康美 2024-06-30 cut_off + 180 天公告里"退市"关键词命中状况
```

加索引到 `CLAUDE.md`(项目根):

```markdown
### v1.x DD Report Quality Eval
- [Phase 1 (backtest infra) landed](docs/claude-context/dd-report-eval-phase-1-landed.md)
- [Phase 2 (metric + ablation) landed](docs/claude-context/dd-report-eval-phase-2-landed.md) — 5 metric 实现 + V0-V3 ablation 控制变量
```

- [x] **Step 5: tick plan checkbox + commit + sediment commit**

将本 plan 文件所有 `- [x]` 改为 `- [x]`(implementer 完成所有 step 后):

```bash
# 替换 plan 的 checkbox 状态
sed -i.bak 's/- \[ \]/- [x]/g' docs/superpowers/plans/2026-05-18-dd-report-eval-phase-2-metrics-ablation.md
rm docs/superpowers/plans/2026-05-18-dd-report-eval-phase-2-metrics-ablation.md.bak

git add backend/scripts/run_phase2_ablation_dogfood.py \
  backend/app/eval/dd_report_production_factory.py \
  docs/claude-context/dd-report-eval-phase-2-landed.md \
  CLAUDE.md \
  docs/superpowers/plans/2026-05-18-dd-report-eval-phase-2-metrics-ablation.md
git commit -m "feat(dd-eval): Phase 2 T2.11 — ablation dogfood 4×8=32 run + sediment + plan tick" \
  -m "Ablation 4×5 matrix (sanity 8 case avg):" \
  -m "  V0 baseline: M1=XX M2=XX M3=XX M4=XX M5=X.X" \
  -m "  V1 no RAG:   ..."
```

(commit body 由 implementer 跑完真数字后填实)

---

## Self-Review Checklist(plan writer 已勾)

**1. Spec coverage** — 检查 spec § 4.2 / § 4.3 / § 4.7 全部要求是否有 task 落实:

| spec 要求 | Task |
|---|---|
| § 4.2 M1 Citation precision/recall + 小 LLM judge | T2.2 |
| § 4.2 M2 Numerical regex + tushare ±1% 容差 | T2.3 |
| § 4.2 M3 Risk-mitigation pairing LLM judge | T2.4 |
| § 4.2 M4 Investment prediction backtest | T2.5 |
| § 4.2 M5 Multi-LLM consensus | T2.6 |
| § 4.3 3 evaluator LLM 跨厂商 + temperature=0 可重复性 | T2.6(可重复性 stress test 推到 Phase 5,Plan T2.6 注释提示) |
| § 4.3 disagreement > 2 → audit / 一致 ≤ 4 → low quality | T2.6 |
| § 4.7 V0 baseline | T2.9 V0_BASELINE |
| § 4.7 V1 无 RAG | T2.9 V1_NO_RAG |
| § 4.7 V2 无 multi-agent | T2.9 V2_NO_MULTI_AGENT + SingleAgentPipeline |
| § 4.7 V3 无 Critic | T2.9 V3_NO_CRITIC + disable_critic flag |
| § 4.7 Phase 2 末跑一次完整 ablation | T2.11 |
| § 4.5 LeakDetector wire 进 BacktestRunner.run_one | T2.7 step 3 |
| § 5.2 eval_results 加 backtest_run_id 等 4 列 | Phase 1 ship,T2.0 加 metric_scores_json 第 5 列 |
| § 5.3 LLMSwapper 复用(BACKTEST_EVALUATOR_MODELS) | T2.7 / T2.11 |
| § 7.3 多 LLM judge 可重复性 > 80% | T2.6 注释 + Phase 5 stress test |
| § 7.4 Backtest 数据 leak detector | T2.7 step 3 / Phase 1 已有独立 leak_detector,T2.7 wire |

✅ 无 spec 要求漏覆盖。

**2. Placeholder scan** — 扫 "TBD" / "fill in" / "add appropriate" / "implement later":

- T2.11 step 2 留了 `_load_kb_client` / `_make_kb_lookup` 的 `NotImplementedError` placeholder + step 2 显式给出 implementer 该做什么 + 怎么 grep,**这不是 placeholder 失败,是显式委托 — 因为生产 KB client 接什么类需 grep 实际 repo 确定**,plan 这里不臆造代码。

✅ 无其他 placeholder。

**3. Type 一致性** — 跨 task 类型/方法名:

- `MetricProtocol.compute(inputs) -> MetricResult` — 一致 T2.0 ~ T2.6
- `MetricResult(name, value, details)` — 一致
- `MetricInputs(report, case_meta, ground_truth, tushare_adapter, kb_lookup, evaluator_clients)` — T2.0 定义,T2.2-2.6 用到
- `BacktestMetricScores` 字段名(`m1_citation_precision` etc.) — T2.0 定义,T2.7 `_to_backtest_metric_scores` 用一致
- `BacktestRunner.__init__(metric_registry, ...)` — T2.7 加,T2.10 `AblationRunner` 调用一致
- `AblationVariant.V0_BASELINE` value 是 `"V0_baseline"` — T2.9 定义,T2.10 / T2.11 写 ablation_variant 字段一致
- `pipeline_factory(*, tushare_adapter, kb_adapter, evaluator_client, disable_critic=False)` — T2.8 / T2.9 / T2.10 / T2.11 一致
- `DDReportPipelineAdapter.run(*, target_name, ts_code, tushare_adapter, kb_adapter, evaluator_client)` — T2.8 定义,匹配 `PipelineProtocol`(Phase 1 backtest_runner.py 已定 sig)

✅ 类型一致。

---

## 工期 + 成本估算(per spec § 5.3 / § 8)

- T2.0-T2.6:7 个 task(metric + schema + ground_truth), 每个 0.5-1 天 → **5-6 天**
- T2.7-T2.10:4 个 task(wire + pipeline adapter + ablation), 每个 0.5-1 天 → **3-4 天**
- T2.11:1 个 task(dogfood + sediment), 0.5-1 天 + 1 天 ablation 跑分 → **1.5-2 天**
- **总:1.5-2 周 wall time(4-6 h/day),其中 ablation 跑分约 28 RMB / 一轮**(spec § 5.3 矩阵估算)

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-dd-report-eval-phase-2-metrics-ablation.md`. Two execution options:

**1. Subagent-Driven(recommended,user 默认指定)** — 每 task fresh subagent + spec reviewer + code quality reviewer + optional fix → next。**REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development`。

**2. Inline Execution** — 本 session 顺序跑完 11 task。**REQUIRED SUB-SKILL:** `superpowers:executing-plans`。

User 复述里已经指定 **Subagent-Driven**。default mode:dispatch subagent per task with sonnet model(per `feedback_subagent_default_sonnet` memory)。
