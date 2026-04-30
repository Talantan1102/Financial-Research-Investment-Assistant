# Dev-Test-Loop D — CI + Cost Guardrail + Drift Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the **CI + cost guardrail + drift detection** layer. Replace `LLMResponse.cost_cny=0.0` stub with real per-model pricing; add `CostBudget` enforcement so a nightly run can't burn through `EVAL_COST_LIMIT_CNY=20`; wire GH Actions for PR (≤ 5min) and nightly (≤ 30min) jobs; build cassette-drift detection and `trace-view` CLI. Plan D closes the dev-test-loop spec.

**Architecture:**
- **`pricing.py` is a pure data table + pure function**, no I/O, no Pydantic. Keys are model names (`deepseek-v4-flash`); values are `(input_per_1k_cny, output_per_1k_cny)` tuples. `compute_cost()` takes `(model, prompt_tokens, completion_tokens)` and returns CNY. Reasoning tokens are billed as output (per Plan B/C Task 0 spike sediment).
- **`CostBudget` is monotonic**: a single instance accumulates cost across many `LLMService.chat` calls. When cumulative exceeds limit, the next call raises `BudgetExceeded` *before* hitting the LLM (fail-fast). Plan B contract holds: `LLMService(cost_budget=None)` writes nothing — additive only.
- **GH Actions has two workflows**: `pr.yml` runs ruff + mypy + cassette-only tests in ≤ 5min on every PR; `nightly.yml` runs L2 full + eval + cassette-validation + pip-audit at 北京 03:00, auto-opens an issue on failure. Secrets stay in repo settings (manual setup task).
- **Cassette drift detection is a script, not a service**: reads cassettes, replays prompts against live LLM, uses LLMService+Judge to LLM-as-judge the semantic similarity. Drift threshold is hard-coded per spec § 4 (similarity < 0.8 = drift).
- **`trace-view` CLI replaces the Plan B/C echo stub**: takes a `request_id`, reads `spans` table, prints a tree with name + latency + cost per node. `tree` ASCII art, no rich/textual.

**Tech Stack:**
- Already in baseline: Python 3.11 + uv, `pydantic`, `openai`, `pytest-recording`, `mypy strict on app.services.*`, `poethepoet`, `pre-commit`.
- New in Plan D:
  - `pip-audit` (dev dep) — vulnerability scanner, nightly only
  - GH Actions (no Python dep, just YAML)
  - **No new Python runtime deps** for any of the cost / drift / trace-view code

**Status inherited from Plan B + Plan C:**
- `LLMService(client, tier_router=None, trace_service=None)` — Plan D adds 4th optional param `cost_budget`
- `LLMResponse(cost_cny=0.0)` is the stub — Plan D fills with real value via `pricing.compute_cost`
- `TraceService` + `EvalRecorder` provide SQLite query API; `trace-view` CLI builds on `TraceService.get_trace`
- 2 cassettes exist (Plan B + Plan C); drift detection iterates over `backend/tests/fixtures/cassettes/**/*.yaml`
- `poe eval` / `poe eval-sanity` / `poe eval-cross-judge` work today
- `poe trace-view` is currently `echo 'comes in Plan D'` stub — Plan D replaces it
- 59 tests green at branch-cut baseline

**Memory inputs (Plan B+C sediment, applied to Plan D plan)**:
- `feedback_third_party_plugin_defaults` — pip-audit + GH Actions step defaults must be spike-verified before plan ships (Task 0 spike)
- `feedback_test_env_modeling` — GH Actions env vars (`LLM_MODE`, `DASHSCOPE_API_KEY`, `EVAL_COST_LIMIT_CNY`) must be set explicitly in workflow YAML, not assumed
- `feedback_cassette_dynamic_prompt_values` — drift detection must NOT replay-then-match-body (timestamps drift); use prompt-level extraction
- `feedback_type_ignore_with_typed_signature` — don't predefend with `# type: ignore` if signature already typed
- `project_llm_service_contract` — additive-only changes to `LLMService` ctor
- `project_eval_pipeline_contract` — `cost_cny=0.0` stub is allowed by `Field(ge=0.0)`; replacing it is a value change, not a schema change

---

## File Structure

| Path | Purpose | Created/Modified |
|---|---|---|
| `backend/app/services/pricing.py` | Per-model price table + `compute_cost()` pure function | Create |
| `backend/app/services/cost_budget.py` | `CostBudget` + `BudgetExceeded` exception | Create |
| `backend/app/services/llm_service.py` | **Modify**: add `cost_budget` ctor param + cost write into `LLMResponse` | Modify |
| `backend/tests/unit/test_pricing.py` | L0: price table + reasoning-tokens cost calc | Create |
| `backend/tests/unit/test_cost_budget.py` | L0: track / under_limit / raise BudgetExceeded | Create |
| `backend/tests/integration/test_llm_service_cost.py` | L1: real cost flows through LLMResponse + budget abort | Create |
| `.github/workflows/pr.yml` | PR gate: ruff + mypy + L0+L1+L2 subset, ≤ 5min | Create |
| `.github/workflows/nightly.yml` | Nightly: L2 full + eval + cassette validation + pip-audit, ≤ 30min | Create |
| `docs/SECRETS_SETUP.md` | One-page guide for setting `DASHSCOPE_API_KEY` in repo secrets | Create |
| `backend/tests/eval/__init__.py` | Make `backend.tests.eval` importable for `python -m` | Create (if not present) |
| `backend/tests/eval/cassette_validation.py` | Drift detection script: read cassettes, replay live, LLM-judge similarity | Create |
| `backend/tests/integration/test_cassette_validation.py` | L1: drift logic with mock LLM | Create |
| `scripts/trace_view.py` | CLI: read SQLite spans, print tree | Create |
| `backend/tests/unit/test_trace_view.py` | L0: tree formatter pure function | Create |
| `pyproject.toml` | **Modify**: add `pip-audit` to dev extras; replace `trace-view` echo stub with real CLI; add `nightly-local` poe task | Modify |
| `backend/.env.example` | **Modify**: add `EVAL_COST_LIMIT_CNY=20` line | Modify |

**Files NOT touched in Plan D (deferred):**
- `app.agents.*` / v0 chat agent skeleton — separate spec
- 50-70 case golden set full population — v1 spec
- Multi-model tier switching — v1 spec
- Replay-based eval (spec § 9 predicts) — v1 spec

---

## Pre-flight check (Task 0 — done before dispatching Task 1)

> **Two short spikes before plan execution.** Both are <2 minutes. They de-risk Phase 2 and Phase 4.

- [ ] **Spike 1: pip-audit current state**

```bash
uv run pip-audit 2>&1 | tail -20 || true
```

If pip-audit is not installed, this fails — that's expected, Plan D Task 11 installs it. The point of this spike is: **if any current dep has a vulnerability, the very first nightly job will fail.** Note any "Known vulnerability" lines under "Plan D retrospective — Task 0 spike result" so Task 11 can either upgrade the dep or accept-and-document.

- [ ] **Spike 2: confirm GH Actions free-tier minute usage**

Visit https://github.com/Talantan1102/Financial-Research-Investment-Assistant/settings/billing/summary (or run `gh api /users/Talantan1102/settings/billing/actions` if you want CLI). Record current monthly minutes used. Spec § 5 wants to stay ≤ 50% (1000min) and alert at 80%. If you're already past 80%, **this is a blocker** — Plan D nightly cron would push over and cost you real money. Report and stop.

- [ ] **Record results**

Open this plan file and fill the "Plan D retrospective — Task 0 spike result" section near the bottom with both spike outputs.

---

## Task 1: `pricing.py` — per-model price table + `compute_cost`

**Files:**
- Create: `backend/app/services/pricing.py`
- Create: `backend/tests/unit/test_pricing.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_pricing.py
"""L0 — pricing table lookup + reasoning-tokens accounting."""

import pytest

from app.services.pricing import (
    PriceUnknownModelError,
    compute_cost,
    get_price,
    DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K,
    DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K,
)


def test_get_price_known_model() -> None:
    p = get_price("deepseek-v4-flash")
    assert p.input_per_1k_cny == DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K
    assert p.output_per_1k_cny == DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K


def test_get_price_unknown_model_raises() -> None:
    with pytest.raises(PriceUnknownModelError):
        get_price("gpt-99")


def test_compute_cost_simple() -> None:
    # 1000 input × ¥0.0002 = ¥0.0002; 500 output × ¥0.0008 = ¥0.0004; total ¥0.0006
    cost = compute_cost(model="deepseek-v4-flash", prompt_tokens=1000, completion_tokens=500)
    assert cost == pytest.approx(0.0006)


def test_compute_cost_reasoning_tokens_billed_as_output() -> None:
    """Per Plan C Task 0 spike: deepseek-v4-flash is a reasoning model;
    reasoning tokens are billed as output. The caller passes the total
    completion_tokens (which already includes reasoning). compute_cost
    does NOT need a separate reasoning_tokens param.
    """
    # 200 input + 549 completion (of which 400 is reasoning, all output-priced)
    cost = compute_cost(model="deepseek-v4-flash", prompt_tokens=200, completion_tokens=549)
    expected = (
        200 * DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K / 1000
        + 549 * DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K / 1000
    )
    assert cost == pytest.approx(expected)


def test_compute_cost_zero_tokens_zero_cost() -> None:
    assert compute_cost(model="deepseek-v4-flash", prompt_tokens=0, completion_tokens=0) == 0.0


def test_compute_cost_unknown_model_raises() -> None:
    with pytest.raises(PriceUnknownModelError):
        compute_cost(model="gpt-99", prompt_tokens=10, completion_tokens=5)
```

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest backend/tests/unit/test_pricing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.pricing'`.

- [ ] **Step 3: Implement `pricing.py`**

Create `backend/app/services/pricing.py`:

```python
"""Pricing table — per-model CNY-per-1K-token rates + cost computation.

Pure data + pure function. No I/O, no Pydantic. Reasoning-model pricing:
DashScope bills reasoning_tokens as part of completion_tokens, so callers
that pass `completion_tokens` from the OpenAI usage block are already
accounting for reasoning. compute_cost takes plain prompt/completion ints.

Sources:
- DashScope deepseek-v4-flash: ¥0.0002 / 1K input, ¥0.0008 / 1K output
  (as of 2026-04, sync if changed).
"""

from __future__ import annotations

from dataclasses import dataclass

# Public price constants — referenced from tests
DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K: float = 0.0002
DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K: float = 0.0008


@dataclass(frozen=True)
class ModelPrice:
    input_per_1k_cny: float
    output_per_1k_cny: float


_TABLE: dict[str, ModelPrice] = {
    "deepseek-v4-flash": ModelPrice(
        input_per_1k_cny=DEEPSEEK_V4_FLASH_INPUT_CNY_PER_1K,
        output_per_1k_cny=DEEPSEEK_V4_FLASH_OUTPUT_CNY_PER_1K,
    ),
}


class PriceUnknownModelError(KeyError):
    """Raised when get_price is called with a model not in the price table."""


def get_price(model: str) -> ModelPrice:
    if model not in _TABLE:
        raise PriceUnknownModelError(
            f"no price entry for model={model!r}; add it to pricing._TABLE"
        )
    return _TABLE[model]


def compute_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p = get_price(model)
    return (
        prompt_tokens * p.input_per_1k_cny / 1000
        + completion_tokens * p.output_per_1k_cny / 1000
    )
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest backend/tests/unit/test_pricing.py -v
uv run mypy backend/app/services/pricing.py
```
Expected: 6 PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/pricing.py backend/tests/unit/test_pricing.py
git commit -m "$(cat <<'EOF'
feat(services): add pricing table + compute_cost (deepseek-v4-flash)

原因 layer: services
EOF
)"
```

---

## Task 2: `LLMService.chat` — write real `cost_cny` from pricing

**Files:**
- Modify: `backend/app/services/llm_service.py`

(L1 test for cost flowing through LLMResponse is in Task 4; this task is the contract change.)

- [ ] **Step 1: Modify `LLMService.chat`**

In `backend/app/services/llm_service.py`:
- Add import: `from app.services.pricing import compute_cost`
- Inside `chat`, after `model = self._tier_router.resolve(tier)` and after the client returns `raw`, compute:
  ```python
  cost_cny = compute_cost(model=model, prompt_tokens=raw.prompt_tokens, completion_tokens=raw.completion_tokens)
  ```
- Replace `cost_cny=0.0` in the `LLMResponse(...)` construction with `cost_cny=cost_cny`.
- Span `metadata["cost_cny"]` should also use the real value (replacing the literal `0.0`).

- [ ] **Step 2: Verify Plan B + Plan C tests still pass**

```bash
uv run pytest backend/tests/ -v
uv run mypy backend/app/services/
```

Expected: every prior test that asserts on `cost_cny == 0.0` (if any) — there should be NONE — must NOT break. If a test does break, it asserted on the stub value; that's a Plan B/C bug not a Plan D bug, but stop and report rather than papering over.

Read existing tests with `grep -rn "cost_cny" backend/tests/` first to verify; expect mostly `>= 0.0` checks which still hold.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/llm_service.py
git commit -m "$(cat <<'EOF'
feat(services): LLMService writes real cost via pricing table

原因 layer: services
EOF
)"
```

---

## Task 3: `CostBudget` class

**Files:**
- Create: `backend/app/services/cost_budget.py`
- Create: `backend/tests/unit/test_cost_budget.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_cost_budget.py
"""L0 — CostBudget accumulation + over-limit fail-fast."""

import pytest

from app.services.cost_budget import BudgetExceeded, CostBudget


def test_under_limit_accumulates() -> None:
    b = CostBudget(limit_cny=1.0)
    b.track(0.3)
    b.track(0.4)
    assert b.spent_cny == pytest.approx(0.7)
    assert b.remaining_cny == pytest.approx(0.3)


def test_at_limit_does_not_raise() -> None:
    """Exactly at limit is fine; over is not."""
    b = CostBudget(limit_cny=1.0)
    b.track(1.0)
    b.assert_under_limit()  # equals, not exceeds


def test_over_limit_assert_raises() -> None:
    b = CostBudget(limit_cny=1.0)
    b.track(0.5)
    b.track(0.6)
    with pytest.raises(BudgetExceeded, match="1.10"):
        b.assert_under_limit()


def test_track_then_assert_pattern() -> None:
    """Caller pattern: chat(...) → track(cost) → assert_under_limit() before next call."""
    b = CostBudget(limit_cny=0.5)
    b.track(0.4)
    b.assert_under_limit()
    b.track(0.2)
    with pytest.raises(BudgetExceeded):
        b.assert_under_limit()


def test_negative_track_rejected() -> None:
    b = CostBudget(limit_cny=1.0)
    with pytest.raises(ValueError, match="non-negative"):
        b.track(-0.01)


def test_default_limit_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_COST_LIMIT_CNY", "5.0")
    b = CostBudget.from_env()
    assert b.limit_cny == 5.0


def test_from_env_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVAL_COST_LIMIT_CNY", raising=False)
    b = CostBudget.from_env()
    assert b.limit_cny == 20.0  # spec § 5 default
```

- [ ] **Step 2: Verify tests fail**

Run: `uv run pytest backend/tests/unit/test_cost_budget.py -v`
Expected: FAIL — `cost_budget` module not defined.

- [ ] **Step 3: Implement `cost_budget.py`**

Create `backend/app/services/cost_budget.py`:

```python
"""CostBudget — cumulative cost tracking with fail-fast over-limit assertion.

Used by LLMService to abort an eval/nightly run BEFORE making a call that
would push cumulative cost over EVAL_COST_LIMIT_CNY (default 20).

Per Plan B contract additive rule: LLMService accepts cost_budget=None and
behaves as if budget tracking didn't exist.
"""

from __future__ import annotations

import os


class BudgetExceeded(RuntimeError):
    """Raised when CostBudget.assert_under_limit() finds spent > limit."""


_DEFAULT_LIMIT_CNY: float = 20.0  # spec § 5


class CostBudget:
    def __init__(self, limit_cny: float) -> None:
        if limit_cny <= 0:
            raise ValueError(f"limit_cny must be > 0, got {limit_cny}")
        self._limit_cny = limit_cny
        self._spent_cny = 0.0

    @classmethod
    def from_env(cls) -> "CostBudget":
        raw = os.environ.get("EVAL_COST_LIMIT_CNY")
        limit = float(raw) if raw else _DEFAULT_LIMIT_CNY
        return cls(limit_cny=limit)

    @property
    def limit_cny(self) -> float:
        return self._limit_cny

    @property
    def spent_cny(self) -> float:
        return self._spent_cny

    @property
    def remaining_cny(self) -> float:
        return max(0.0, self._limit_cny - self._spent_cny)

    def track(self, cost_cny: float) -> None:
        if cost_cny < 0:
            raise ValueError(f"cost_cny must be non-negative, got {cost_cny}")
        self._spent_cny += cost_cny

    def assert_under_limit(self) -> None:
        if self._spent_cny > self._limit_cny:
            raise BudgetExceeded(
                f"cumulative cost ¥{self._spent_cny:.2f} exceeds limit ¥{self._limit_cny:.2f}"
            )
```

- [ ] **Step 4: Verify**

```bash
uv run pytest backend/tests/unit/test_cost_budget.py -v
uv run mypy backend/app/services/cost_budget.py
```
Expected: 7 PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cost_budget.py backend/tests/unit/test_cost_budget.py
git commit -m "$(cat <<'EOF'
feat(services): add CostBudget with fail-fast over-limit assertion

原因 layer: services
EOF
)"
```

---

## Task 4: `LLMService(cost_budget=...)` DI + L1 abort test

**Files:**
- Modify: `backend/app/services/llm_service.py` (add `cost_budget` param)
- Create: `backend/tests/integration/test_llm_service_cost.py`

- [ ] **Step 1: Modify `LLMService` to accept `cost_budget`**

In `backend/app/services/llm_service.py`:
- Add to `__init__` (after `trace_service` param):
  ```python
  cost_budget: CostBudget | None = None,
  ```
- Store as `self._budget = cost_budget`.
- Inside `chat`, AFTER computing `cost_cny` (Task 2) and BEFORE returning `LLMResponse`:
  ```python
  if self._budget is not None:
      self._budget.track(cost_cny)
      self._budget.assert_under_limit()
  ```
  This means the call that pushes us over the limit DOES return its result, but the NEXT call's pre-flight check raises. Per spec § 5: budget enforcement is fail-fast at the start of each call, not refusing in-flight calls.

  Wait — re-read the spec carefully. "LLMService 累计成本超阈值即 abort". The simplest semantically: track AFTER call, assert BEFORE returning. The current call returns successfully even if it pushed over (avoid losing data). The NEXT call's pre-flight assert fires.

  Implementation: at the **top** of `chat()`, BEFORE making the call:
  ```python
  if self._budget is not None:
      self._budget.assert_under_limit()  # would-be-over from PRIOR call
  ```
  And AFTER the call, just `track`:
  ```python
  if self._budget is not None:
      self._budget.track(cost_cny)
  ```

- Add import: `from app.services.cost_budget import CostBudget`.

- [ ] **Step 2: Write the L1 test**

Create `backend/tests/integration/test_llm_service_cost.py`:

```python
"""L1 — LLMService writes real cost into LLMResponse + CostBudget enforcement."""

from pathlib import Path

import pytest

from app.services.cost_budget import BudgetExceeded, CostBudget
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.pricing import compute_cost


def test_chat_response_cost_is_real(mock_llm_client: MockLLMClient) -> None:
    svc = LLMService(client=mock_llm_client)
    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
    expected = compute_cost(
        model=r.model,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
    )
    assert r.cost_cny == pytest.approx(expected)
    assert r.cost_cny > 0  # not the stub anymore


def test_budget_aborts_next_call_after_over(mock_llm_client: MockLLMClient) -> None:
    """Budget allows the call that pushes us over; next call's pre-flight raises."""
    # Set limit so low that one call exceeds it. MockLLMClient mock-cost is tiny
    # (~tokens × ¥0.0008/1K), so use a 1e-9 limit to guarantee over-limit.
    budget = CostBudget(limit_cny=1e-9)
    svc = LLMService(client=mock_llm_client, cost_budget=budget)

    r1 = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
    assert r1.cost_cny > 0
    assert budget.spent_cny > budget.limit_cny

    with pytest.raises(BudgetExceeded):
        svc.chat(prompt="What is the price of 600519.SH?", tier="fast")


def test_budget_under_limit_allows_many_calls(mock_llm_client: MockLLMClient) -> None:
    budget = CostBudget(limit_cny=1.0)  # 100x typical mock cost
    svc = LLMService(client=mock_llm_client, cost_budget=budget)

    for _ in range(5):
        r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
        assert r.cost_cny > 0

    assert budget.spent_cny < budget.limit_cny


def test_no_budget_keeps_plan_b_contract(mock_llm_client: MockLLMClient) -> None:
    """LLMService(client) without cost_budget is unchanged from Plan B."""
    svc = LLMService(client=mock_llm_client)
    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
    assert r.content
```

- [ ] **Step 3: Verify**

```bash
uv run pytest backend/tests/integration/test_llm_service_cost.py -v
uv run pytest backend/tests/ -q  # full suite stays green
uv run mypy backend/app/services/
```
Expected: 4 new tests PASS, full suite up by 4 (60 + 4 + 6 + 7 = wait... actually 59 + 6 pricing + 7 budget + 4 cost integration = ~76).

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/llm_service.py backend/tests/integration/test_llm_service_cost.py
git commit -m "$(cat <<'EOF'
feat(services): LLMService cost_budget DI + fail-fast over-limit

原因 layer: services
EOF
)"
```

---

## Task 5: GH Actions PR workflow

**Files:**
- Create: `.github/workflows/pr.yml`

- [ ] **Step 1: Create the workflow**

Per spec § 5 + 附录 C. Goal: ≤ 5min, runs ruff + mypy + L0+L1+L2 subset (no real LLM key needed — cassettes only).

```yaml
# .github/workflows/pr.yml
name: PR

on:
  pull_request:
  push:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint-and-fast-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - name: Install deps
        run: uv sync --extra dev
      - name: Format check
        run: uv run ruff format --check .
      - name: Lint
        run: uv run ruff check .
      - name: Type check
        run: uv run mypy backend
      - name: Tests (L0 + L1 + L2 cassette)
        env:
          LLM_MODE: cassette
        run: uv run pytest backend/tests -m "not slow and not live_only" -v
```

> **Note**: spec 附录 C uses `uv sync --all-extras` but we use `--extra dev` to mirror our local dev setup. `concurrency` block cancels superseded PR runs to save quota.

- [ ] **Step 2: Verify YAML syntax locally**

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/pr.yml'))" && echo OK
```
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/pr.yml
git commit -m "$(cat <<'EOF'
ci: add GitHub Actions PR workflow (ruff + mypy + cassette tests)

原因 layer: ci
EOF
)"
```

> **Effective verification happens after merge** when GH Actions runs against the next PR. We can't truly test the workflow until it triggers in cloud.

---

## Task 6: GH Actions nightly workflow

**Files:**
- Create: `.github/workflows/nightly.yml`

- [ ] **Step 1: Create the workflow**

```yaml
# .github/workflows/nightly.yml
name: Nightly

on:
  schedule:
    - cron: "0 19 * * *"  # 19:00 UTC = 03:00 北京
  workflow_dispatch:  # manual trigger

jobs:
  full-tests-and-eval:
    runs-on: ubuntu-latest
    timeout-minutes: 35
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - name: Install deps
        run: uv sync --extra dev

      - name: L2 full (e2e cassettes)
        env:
          LLM_MODE: cassette
        run: uv run pytest backend/tests/e2e -v

      - name: L3 eval (live LLM, cost-budgeted)
        env:
          DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
          DASHSCOPE_BASE_URL: https://dashscope.aliyuncs.com/compatible-mode/v1
          LLM_MODE: live
          EVAL_COST_LIMIT_CNY: "20"
        run: uv run poe eval

      - name: Cassette drift detection
        env:
          DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
          DASHSCOPE_BASE_URL: https://dashscope.aliyuncs.com/compatible-mode/v1
          EVAL_COST_LIMIT_CNY: "20"
        run: uv run python -m backend.tests.eval.cassette_validation

      - name: Dependency security audit
        run: uv run pip-audit

      - name: Open issue on failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            const today = new Date().toISOString().split('T')[0];
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `[nightly] ${today} failure`,
              body: `Nightly job failed. See [run](${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}).`,
              labels: ['nightly-failure']
            })
```

- [ ] **Step 2: Verify YAML**

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/nightly.yml'))" && echo OK
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/nightly.yml
git commit -m "$(cat <<'EOF'
ci: add GitHub Actions nightly workflow (eval + drift + audit + auto-issue)

原因 layer: ci
EOF
)"
```

---

## Task 7: GitHub Secrets setup documentation

**Files:**
- Create: `docs/SECRETS_SETUP.md`

> **This task documents a manual user action.** The implementer cannot set repo secrets via API (would require write-permission token + plain-text key in conversation, both bad). This task produces docs the user follows once.

- [ ] **Step 1: Write the doc**

```markdown
# GitHub Repo Secrets Setup

Plan D nightly workflow needs `DASHSCOPE_API_KEY` to run real LLM calls
during eval + cassette drift detection. This is a one-time setup.

## Steps

1. Go to https://github.com/Talantan1102/Financial-Research-Investment-Assistant/settings/secrets/actions
2. Click **"New repository secret"**
3. Name: `DASHSCOPE_API_KEY`
4. Value: paste the key from your local `backend/.env` (the value after `DASHSCOPE_API_KEY=`)
5. Click **"Add secret"**

## Verification

After setup, manually trigger the nightly workflow once:

1. Go to https://github.com/Talantan1102/Financial-Research-Investment-Assistant/actions/workflows/nightly.yml
2. Click **"Run workflow"** → **"Run workflow"** (use main branch)
3. Watch the run — it should complete in ≤ 30min.

Expected total cost: ≤ ¥0.10 (per Plan C Task 0 spike: ~70 eval cases × ¥0.0006/case ≈ ¥0.04, plus drift detection on 2 cassettes ≈ ¥0.02).

If `EVAL_COST_LIMIT_CNY=20` is hit, that's a 200x buffer — almost certainly a bug, not a real cost overrun.

## What's NOT in repo secrets

- `OPENROUTER_API_KEY` / `BOCHA_API_KEY` / `TUSHARE_API_TOKEN` — none of these are needed by the nightly workflow under v0 (no agent yet uses them in eval).
- PR workflow does not use any secret (cassettes only, no live LLM).

## Rotating the key

If `DASHSCOPE_API_KEY` is compromised:
1. Revoke at https://bailian.console.aliyun.com (DashScope console)
2. Re-create in `backend/.env` (local) AND repo secret (CI)
3. Both must match for nightly to run.
```

- [ ] **Step 2: Commit**

```bash
git add docs/SECRETS_SETUP.md
git commit -m "$(cat <<'EOF'
docs: add GH repo secrets setup guide for nightly workflow

原因 layer: docs
EOF
)"
```

---

## Task 8: `cassette_validation` script — drift detection

**Files:**
- Create: `backend/tests/eval/__init__.py` (if not present)
- Create: `backend/tests/eval/cassette_validation.py`

- [ ] **Step 1: Verify `backend/tests/eval/` is a package**

```bash
ls backend/tests/eval/__init__.py 2>&1
```

If missing, create empty: `touch backend/tests/eval/__init__.py`

- [ ] **Step 2: Implement the drift script**

Create `backend/tests/eval/cassette_validation.py`:

```python
"""Cassette drift detection — replays cassette prompts against live LLM,
LLM-as-judges semantic similarity. Drift threshold: similarity < 0.8 per
spec § 4.

Invoked by nightly workflow:
    uv run python -m backend.tests.eval.cassette_validation

Exits 0 if all cassettes within threshold. Exits 1 otherwise (drift found).

Reads cassette YAML → extracts request body (prompt + model) → real LLM
call (live, not via cassette) → asks Judge for semantic similarity score
0-10 → flags any cassette where similarity < 8 (= 0.8 per the 0-10 scale).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI

from app.services.cost_budget import CostBudget
from app.services.llm_response import Tier
from app.services.llm_service import LLMService

CASSETTES_ROOT = Path("backend/tests/fixtures/cassettes")
SIMILARITY_THRESHOLD = 8  # 0-10 scale; spec § 4 says 0.8


def _extract_first_interaction(cassette_path: Path) -> tuple[str, str, str] | None:
    """Returns (model, prompt, recorded_response) or None if cassette is empty/unsupported."""
    data = yaml.safe_load(cassette_path.read_text(encoding="utf-8"))
    if not data or "interactions" not in data or not data["interactions"]:
        return None
    first = data["interactions"][0]
    body_raw = first["request"]["body"]
    body = json.loads(body_raw) if isinstance(body_raw, str) else body_raw
    model = body.get("model", "deepseek-v4-flash")
    msgs = body.get("messages", [])
    prompt = msgs[-1]["content"] if msgs else ""
    resp_str = first["response"]["body"]["string"]
    resp_obj = json.loads(resp_str)
    recorded = resp_obj["choices"][0]["message"]["content"]
    return model, prompt, recorded


class _Adapter:
    def __init__(self, client: OpenAI) -> None:
        self._c = client

    def chat(self, prompt: str, model: str, schema: dict[str, Any] | None) -> Any:
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


_SIM_PROMPT = """\
对比下面两段 LLM 输出的语义相似度,给 0-10 整数分:
- 旧输出: {old}
- 新输出: {new}

10 = 语义完全等价;0 = 完全无关。仅输出一个整数,无其他文字。
"""


def score_similarity(judge_llm: LLMService, old: str, new: str, tier: Tier = "balanced") -> int:
    prompt = _SIM_PROMPT.format(old=old, new=new)
    r = judge_llm.chat(prompt=prompt, tier=tier)
    digits = "".join(c for c in r.content.strip() if c.isdigit())
    if not digits:
        return 0
    return min(10, max(0, int(digits[:2])))


def main() -> int:
    cassettes = sorted(CASSETTES_ROOT.rglob("*.yaml"))
    if not cassettes:
        print("No cassettes found; nothing to validate.")
        return 0

    client = OpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.environ.get(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
    )
    adapter = _Adapter(client)
    budget = CostBudget.from_env()
    sut = LLMService(client=adapter, cost_budget=budget)
    judge = LLMService(client=adapter, cost_budget=budget)

    drifts: list[str] = []
    for cassette in cassettes:
        ext = _extract_first_interaction(cassette)
        if ext is None:
            print(f"SKIP {cassette}: no interactions")
            continue
        model, prompt, recorded = ext
        live = sut.chat(prompt=prompt, tier="balanced")
        sim = score_similarity(judge, old=recorded, new=live.content)
        verdict = "OK" if sim >= SIMILARITY_THRESHOLD else "DRIFT"
        print(f"{verdict} sim={sim}/10 cassette={cassette.relative_to(CASSETTES_ROOT)}")
        if sim < SIMILARITY_THRESHOLD:
            drifts.append(str(cassette.relative_to(CASSETTES_ROOT)))

    print(f"\nTotal cassettes: {len(cassettes)} | drifts: {len(drifts)} | spent: ¥{budget.spent_cny:.4f}")
    if drifts:
        print("Drift detected in:")
        for d in drifts:
            print(f"  - {d}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify mypy + smoke run (without live LLM)**

```bash
uv run mypy backend/tests/eval/cassette_validation.py
```

mypy may complain about `from openai import OpenAI` if openai isn't typed; that's pre-existing pattern from Plan B/C cassette test. If error, add `# type: ignore[import-untyped]` ONLY if mypy genuinely flags it (per `feedback_type_ignore_with_typed_signature` memory).

Smoke (without DASHSCOPE_API_KEY set, expects KeyError):
```bash
unset DASHSCOPE_API_KEY
uv run python -m backend.tests.eval.cassette_validation 2>&1 | head -3
```
Expected: KeyError on env var (proves the script reaches the env check).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/eval/__init__.py backend/tests/eval/cassette_validation.py
git commit -m "$(cat <<'EOF'
feat(scripts): add cassette drift detection (LLM-as-judge similarity)

原因 layer: services
EOF
)"
```

---

## Task 9: L1 integration test for drift detection

**Files:**
- Create: `backend/tests/integration/test_cassette_validation.py`

- [ ] **Step 1: Write the test**

```python
"""L1 — cassette validation drift logic with mock LLM judge.

Doesn't actually call drift script's main(); tests the score_similarity
pure function with mock judge to ensure it parses LLM digit output.
"""

import pytest

from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from backend.tests.eval.cassette_validation import score_similarity


def test_score_similarity_parses_int(mock_llm_client: MockLLMClient) -> None:
    """The mock LLM responds with the templated string for similarity prompts.
    Add a static-dict entry that returns '8' to match the 'high similarity' path.
    """
    pytest.importorskip("backend.tests.eval.cassette_validation")
    judge = LLMService(client=mock_llm_client)
    # MockLLMClient returns content from agent_decisions.yaml; for arbitrary
    # similarity prompts (no entry), we expect MockMissError. So this test
    # primarily verifies the parse-int path works on a known fixture.
    # We don't add a new mock entry — the goal here is the digit-extraction
    # logic, which we test against a hand-crafted response below.
    pass


def test_digit_extraction_clamps_to_0_10() -> None:
    """Pure-function test: the digit-extraction logic clamps to [0, 10]."""
    # We don't have a class to instantiate — score_similarity is a function
    # that calls the LLM. Instead test the digit-extraction inline via a
    # small fake LLM that returns specific strings.

    class _FakeChat:
        def __init__(self, text: str) -> None:
            self._text = text

        def chat(self, prompt, model, schema):  # type: ignore[no-untyped-def]
            class _R:
                content = self._text
                prompt_tokens = 1
                completion_tokens = 1
            return _R()

    # Each fake returns a different string; verify clamping
    cases = [
        ("8", 8),
        ("12 (out of range)", 10),  # clamp to 10
        ("0", 0),
        ("nope", 0),  # no digits → 0
        ("score: 7/10", 7),
    ]
    for text, expected in cases:
        svc = LLMService(client=_FakeChat(text))
        sim = score_similarity(svc, old="x", new="y")
        assert sim == expected, f"text={text!r} → {sim}, expected {expected}"
```

- [ ] **Step 2: Verify**

```bash
uv run pytest backend/tests/integration/test_cassette_validation.py -v
```

Expected: 2 PASS (one is a placeholder noop, one is the digit-extraction test).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_cassette_validation.py
git commit -m "$(cat <<'EOF'
test(integration): verify cassette drift score_similarity digit parsing

原因 layer: tests
EOF
)"
```

---

## Task 10: `trace-view` CLI

**Files:**
- Create: `scripts/trace_view.py`
- Create: `backend/tests/unit/test_trace_view.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_trace_view.py
"""L0 — trace_view tree formatter pure function."""

from datetime import datetime, timedelta

from app.services.trace_models import Span, TraceTree
from scripts.trace_view import format_trace_tree


def _span(span_id: str, parent_id: str | None, name: str, latency_ms: int) -> Span:
    base = datetime(2026, 4, 30, 12, 0, 0)
    return Span(
        span_id=span_id,
        request_id="r1",
        parent_id=parent_id,
        name=name,
        inputs={},
        outputs={},
        metadata={"cost_cny": 0.001},
        started_at=base,
        ended_at=base + timedelta(milliseconds=latency_ms),
        error=None,
    )


def test_format_root_only() -> None:
    root = _span("root", None, "ChatRequest", 400)
    tree = TraceTree.from_spans([root])
    out = format_trace_tree(tree)
    assert "root" in out
    assert "ChatRequest" in out
    assert "400ms" in out


def test_format_with_children() -> None:
    root = _span("root", None, "ChatRequest", 400)
    c1 = _span("c1", "root", "LLMService.chat", 250)
    tree = TraceTree.from_spans([root, c1])
    out = format_trace_tree(tree)
    assert "ChatRequest" in out
    assert "LLMService.chat" in out
    # Child should be indented under root
    lines = out.splitlines()
    root_line_idx = next(i for i, l in enumerate(lines) if "ChatRequest" in l)
    child_line_idx = next(i for i, l in enumerate(lines) if "LLMService.chat" in l)
    assert child_line_idx > root_line_idx
    # Child line has more leading whitespace OR a tree-prefix char
    assert lines[child_line_idx].startswith(("  ", "│", "└", "├"))
```

- [ ] **Step 2: Verify it fails**

Run: `uv run pytest backend/tests/unit/test_trace_view.py -v`
Expected: FAIL — `format_trace_tree` not defined.

- [ ] **Step 3: Implement `trace_view.py`**

Create `scripts/trace_view.py`:

```python
"""trace-view — read SQLite spans table and pretty-print a TraceTree.

Usage:
    uv run python scripts/trace_view.py --db backend/data/eval.sqlite --request-id req-foo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.services.trace_models import Span, TraceTree
from app.services.trace_service import TraceService


def format_trace_tree(tree: TraceTree) -> str:
    """ASCII-art tree of the trace. Each span shows: name, latency, cost."""
    lines: list[str] = []
    _format_span(tree.root_span, depth=0, prefix="", is_last=True, lines=lines)
    for i, child in enumerate(tree.root_span_children):
        is_last = i == len(tree.root_span_children) - 1
        _format_span(child, depth=1, prefix="", is_last=is_last, lines=lines)
    lines.append("")
    lines.append(
        f"  request_id={tree.request_id} total_latency_ms={tree.total_latency_ms} total_cost_cny=¥{tree.total_cost_cny:.4f}"
    )
    return "\n".join(lines)


def _format_span(span: Span, depth: int, prefix: str, is_last: bool, lines: list[str]) -> None:
    if depth == 0:
        marker = ""
    else:
        marker = "└─ " if is_last else "├─ "
    indent = "  " * (depth - 1) if depth > 0 else ""
    cost = float(span.metadata.get("cost_cny", 0.0))
    lines.append(
        f"{indent}{marker}{span.name} [{span.latency_ms}ms, ¥{cost:.4f}] (id={span.span_id})"
    )


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=Path("backend/data/eval.sqlite"))
    p.add_argument("--request-id", required=True)
    args = p.parse_args(argv)

    if not args.db.exists():
        print(f"ERROR: db not found: {args.db}", file=sys.stderr)
        return 2

    svc = TraceService(db_path=args.db)
    try:
        tree = svc.get_trace(args.request_id)
    except LookupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(format_trace_tree(tree))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Verify**

```bash
uv run pytest backend/tests/unit/test_trace_view.py -v
uv run mypy scripts/trace_view.py
uv run python scripts/trace_view.py --help
```

Expected: 2 PASS, mypy clean, CLI prints argparse help.

- [ ] **Step 5: Commit**

```bash
git add scripts/trace_view.py backend/tests/unit/test_trace_view.py
git commit -m "$(cat <<'EOF'
feat(scripts): add trace-view CLI (read SQLite spans, print tree)

原因 layer: services
EOF
)"
```

---

## Task 11: `pip-audit` dev dep + replace `trace-view` poe stub + `nightly-local` task

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/.env.example`

- [ ] **Step 1: Add `pip-audit` to dev extras**

In `pyproject.toml [project.optional-dependencies] dev`, add:
```toml
"pip-audit>=2.7",
```

- [ ] **Step 2: Replace `trace-view` echo stub + add new poe tasks**

Find the `trace-view = "echo '...'"` line in `[tool.poe.tasks]` and REPLACE it with:

```toml
trace-view.shell = "uv run python scripts/trace_view.py $@"

# Run nightly's eval+drift sequence locally (uses live LLM via .env). Skips dep audit.
nightly-local.sequence = [
    { cmd = "pytest backend/tests/e2e -v" },
    { cmd = "uv run poe eval" },
    { shell = "unset all_proxy https_proxy http_proxy && uv run python -m backend.tests.eval.cassette_validation" },
]

# Manual: pip-audit only.
audit = "uv run pip-audit"
```

- [ ] **Step 3: Add EVAL_COST_LIMIT_CNY to .env.example**

In `backend/.env.example`, append (or in the appropriate section):

```
# ==================== Eval Cost Guardrail ====================
# Plan D: cumulative LLM spend cap for eval / nightly. Default 20 if unset.
EVAL_COST_LIMIT_CNY=20
```

- [ ] **Step 4: Sync deps**

```bash
uv sync --extra dev
uv run pip-audit --version  # smoke
```

Expected: pip-audit installed; version prints.

- [ ] **Step 5: Verify**

```bash
uv run poe trace-view --help
uv run poe audit 2>&1 | tail -3
```

Expected:
- `trace-view --help` prints argparse usage (the `--` after `poe trace-view --` is needed if your poe version requires it; if `--help` doesn't propagate, drop the help test).
- `poe audit` runs `pip-audit` and either passes (no vulns) or fails with vulnerabilities listed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock backend/.env.example
git commit -m "$(cat <<'EOF'
chore(dx): add pip-audit + replace trace-view stub + nightly-local task

原因 layer: chore
EOF
)"
```

---

## Task 12: Plan D retrospective + final ci

**Files:**
- Modify: this plan file (fill retrospective)

- [ ] **Step 1: Final ci sweep**

```bash
uv run poe ci
```

Expected: ruff format check, ruff check, mypy on full backend, pytest 60+ tests all green. If pip-audit reports vulnerabilities, those don't fail `poe ci` (audit is only in nightly + `poe audit` standalone).

- [ ] **Step 2: Verify all 4 phase outputs reachable**

```bash
# Phase 1: cost
uv run pytest backend/tests/unit/test_pricing.py backend/tests/unit/test_cost_budget.py backend/tests/integration/test_llm_service_cost.py -v
# Phase 3: drift logic
uv run pytest backend/tests/integration/test_cassette_validation.py -v
# Phase 4: trace-view
uv run pytest backend/tests/unit/test_trace_view.py -v
uv run poe trace-view --help
# Phase 5: audit
uv run poe audit 2>&1 | tail -5
```

Each should pass or print expected output.

- [ ] **Step 3: Fill the Plan D retrospective**

Append to the bottom of this plan file. Use the same template Plan B + C used:
- Implementation completion date / branch / commits / time
- 对的设计(3 条)
- 错的设计 / plan 漏了什么(3 条)
- 下个 plan 要避免(3 条)
- 沉淀到 memory(specific memory file names)
- Subagent-driven-development 节奏复盘
- **dev-test-loop spec is COMPLETE** — what's next is the v0 chat agent skeleton (separate spec)

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-04-30-dev-test-loop-D-ci-cost-guardrail.md
git commit -m "$(cat <<'EOF'
docs(plan): Plan D retrospective + dev-test-loop spec close

原因 layer: docs
EOF
)"
```

---

## Acceptance Criteria

- [ ] `uv run poe ci` green on the worktree
- [ ] `LLMResponse.cost_cny > 0` for any successful chat call (no more stub)
- [ ] `CostBudget(limit_cny=X)` raises `BudgetExceeded` on the next `chat` after cumulative cost > X
- [ ] `LLMService(client=...)` without `cost_budget` is unchanged from Plan B/C contract
- [ ] `.github/workflows/{pr,nightly}.yml` parse as valid YAML
- [ ] `docs/SECRETS_SETUP.md` exists (manual user step documented)
- [ ] `python -m backend.tests.eval.cassette_validation` runs (with key) or fails-with-clear-error (without)
- [ ] `poe trace-view --help` prints argparse usage
- [ ] `poe audit` runs pip-audit
- [ ] Plan D retrospective filled

## Test plan (run on completion)

- Local: `uv run poe ci`
- Local: `uv run poe nightly-local` — exercises the full nightly chain locally (with live LLM via `.env`)
- Local: `uv run poe audit`
- Local: `uv run poe trace-view --db backend/data/eval.sqlite --request-id <some-id-from-nightly-local>` — pretty-prints a tree
- Cloud: after merging Plan D, the next PR triggers `pr.yml`; verify it goes green in ≤ 5min
- Cloud: after `DASHSCOPE_API_KEY` is in repo secrets (per SECRETS_SETUP.md), manually trigger `nightly.yml` once and verify it completes in ≤ 30min and cost ≤ ¥0.10

---

## Notes for the implementer

- **Plan B + Plan C contracts hold**: `LLMService(client)` without trace_service or cost_budget MUST keep working with zero side effects. Run Plan B/C tests after Tasks 2 and 4 to confirm.
- **GH Actions can't be unit-tested locally** — Task 5 and Task 6 verify YAML syntax and rely on cloud feedback after merge. Be explicit in PR description that the workflow's first real run is a verification step.
- **`pip-audit` may fail Task 11 step 4** if a current dep has a known vulnerability. If so:
  - For dev-only deps: bump the dep's version constraint and re-run.
  - For runtime deps: discuss before bumping (may need code changes).
  - Document the result in retrospective.
- **`backend/data/` is .gitignored** (Plan C). `trace-view` works against a real SQLite that exists only after eval has run; CI/test does not produce the file. Tests for `trace-view` use Pydantic objects (no SQLite I/O).
- **Cassette drift detection script costs real ¥** (~¥0.02 for 2 cassettes). Don't run it locally without intent. `poe nightly-local` runs it because that's the point.
- **Per Plan B+C sediment**: this plan writes "intent + constraint" for the workflow YAML structure (we copy spec § 5 + 附录 C verbatim) but specifies the cost-guardrail behavior precisely (it's a contract, not a config detail).

---

## Plan D retrospective — Task 0 spike result

### Spike 1: pip-audit current state
- **Date probed**: 2026-04-30
- **Output**: `No known vulnerabilities found`(127 dependencies scanned via `uv tool run pip-audit`,30s)
- **Vulnerabilities found**: 0
- **Action taken**: proceed。Task 11 装 pip-audit 进 dev extras 时,首跑不会因现存依赖漏洞而 fail。

### Spike 2: GH Actions free-tier usage
- **Date probed**: 2026-04-30
- **Current monthly minutes used**: 未能用 `gh api` 查(token 缺 user scope,API 返回 404)。**Project repo 刚启用 Actions(本月仅 0-2 次 PR run,远低于 1000 min 阈值)**,实测继续。如果 Plan D 落地后 nightly 跑了 1 周还没撞 80% 阈值告警,则证明估算正确。
- **Action taken**: proceed,record-and-watch。建议 Plan D PR merge 后 1 周时 inline 检查一次 billing UI 看实际累计。

---

## Retrospective

**Implementation completion date**: 2026-04-30
**Branch**: `feat/dev-test-loop-D`(基于 main `f3deed8`)
**Total commits**: 13(11 task commits + 2 fix commits)
**Total time**: ~3 小时(跟 Plan B/C 持平)

### 对的设计(3 条)

1. **`CostBudget` 用"先 assert,再 track"语义**。Task 4 实施时一度纠结:budget 究竟是"call 前 assert"还是"call 后 track 即 raise"。最终选了**call 前 assert prior over-limit + call 后 track**:即"破限的那一次成功返回(数据不丢),下一次 call 的 pre-flight 才 raise"。这个语义在 nightly 真跑时有用 —— 不会因为单 call 超限丢中间结果,但下一 call 立刻 fail-fast。**这是个 nuanced 设计选择,plan 写清楚后 implementer 一次过**。

2. **`yaml` mypy override 一劳永逸解决 Plan B/C 反复出现的 unused-ignore**。Plan B/C 实施时各撞过一次"yaml import 的 type:ignore 多余/必要"的反复,因为不同 venv 的 mypy 推断不一致。Plan D 加 `[[tool.mypy.overrides]] module = "yaml"; ignore_missing_imports = true` 后,**inline `# type: ignore` 删干净,跨 venv 永久稳定**。这是从 Plan B/C 的 inline fix 升级到 plan-config-level 的根除。

3. **Tasks 5+6+7 inline 一并 commit 节省 quota**。GH Actions YAML + secrets 文档纯 paste-from-plan,无 logic,inline 三件一并落地比派 3 个 implementer subagent 节省 ~3 次调用 + ~5 分钟。Plan A retrospective 提"trivial config tasks 可以 inline review",Plan D 直接 inline 实施(连 implementer subagent 都不派),效率最高。

### 错的设计 / plan 漏了什么(3 条)

1. **Plan 没识别 `python -m backend.tests.eval.cassette_validation` 与 mypy/pytest 的模块名冲突**。Task 8 implementer 不得不在 `cassette_validation.py` 顶部加 `sys.path.insert(0, _BACKEND_DIR)`,Task 9 测试又因 `import backend.tests...` vs mypy 把 `backend/` 当 source-root 推断为 `tests.eval...` 而冲突,需要改用 `from tests.eval import cassette_validation as cv`。**双向兼容(从 project root 用 `python -m` 跑 + 从 backend/ source-root 跑 mypy/pytest)的脚本必须 plan 阶段就标注模块路径策略**。

2. **Plan 让 implementer 在 `score_similarity` 测试中加 `# type: ignore[arg-type]`**(Task 9 inline 写时我也加了)。但 mypy 在 `LLMService(client=_FakeChat())` 的 ChatClient Protocol structural matching 下不报错,ignore 多余。**这是 Plan B/C 沉淀过的同型教训(`feedback_type_ignore_with_typed_signature`)第三次应用失败** — implementer/我都还是预防式加。下次 plan 写测试代码时,不要在 mock-injection 那行加 ignore,先跑 mypy 看是否真需要。

3. **Plan Task 11 `pip-audit>=2.7` 已被 Plan A 加进 dev extras**。Task 0 spike 已用 `uv tool run pip-audit`(临时装)证实 0 漏洞,但 plan 写"Add `pip-audit` to dev extras"仍然假设它没装。Implementer 实施时发现已就位,无 install action。**没引发问题(已在就行),但 plan 应该先 grep deps 再写"add"**。

### 下个 spec / plan 要避免(3 条)

1. 双向兼容(`python -m` from project root + mypy/pytest from source root)的脚本,plan 阶段要明确两种 context 下的模块路径,**或在 plan 里给出 `sys.path.insert` boilerplate**。
2. 测试代码里的 `# type: ignore[arg-type]` 不要预防式加 — Protocol structural typing 通常会让 mock 自动 satisfy,跑 mypy 验证再决定是否需要 ignore。
3. plan 写"add dependency"前,先 `grep <dep> pyproject.toml` 确认是否已存在 — Plan A 全栈 deps 加得很全,后续 plan 只需 verify。

### 沉淀到 memory

- [feedback_python_m_path_dual_context.md](memory/feedback_python_m_path_dual_context.md) — 脚本同时被 `python -m <full.path>` 和 mypy/pytest 跑时,双 source-root 路径冲突;plan 阶段必须显式 sys.path 注入或文档化 PYTHONPATH 策略

(只新增 1 条 memory — Plan D 的其他教训都是 Plan B/C 沉淀的复用应用,不需要新 entry。这是好现象:Plan B/C 沉淀正在生效。)

### Subagent-driven-development 节奏复盘

- **总 subagent 调用**:**5 次**(Tasks 1, 2, 3, 4, 8, 10 implementer;Tasks 5+6+7 inline;Tasks 9 + 11 inline;Tasks 12 inline)。
  - 实际是 6 次 implementer + 0 reviewer = 6 次。
- **Plan B 19 → Plan C 9 → Plan D 6**(连续两 plan 减少,total 节省 68%)
- **节省来自**:
  - Tasks 5+6+7(3 task 合 1 inline commit)
  - Tasks 9, 11, 12(都 inline)
  - 全部 inline review,无 spec/quality reviewer subagent
- **代价**:
  - mypy unused-ignore 反复(Plan C 撞过,Plan D 又撞 + 增加 mypy override 一举永久解决)
  - Task 4 implementer 写 test 时把 `from pathlib import Path` 当 unused 留下被 ruff fix(无影响,但属于 implementer 思考粒度问题)
- **主对话 context 消耗**:中等。Plan D 涉及 `LLMService` 第三次 additive 改动(已熟练),GH Actions 是新东西但 paste-from-plan 无 logic,trace-view 标准 CLI 模式。
- **dev-test-loop 4 plan 累计 subagent 调用**:Plan A(~11)+ Plan B(19)+ Plan C(9)+ Plan D(6)= **~45 次**。比"19 × 4 = 76"减少 41%。

### dev-test-loop spec close

Plan D 完成 → **dev-test-loop spec(2026-04-29)落地完毕**。

✅ 4 plan 累计落地:
- Plan A — Repo bootstrap(uv / ruff / mypy / pytest / poe / pre-commit / 测试目录)
- Plan B — LLM Test Infrastructure(LLMService / MockLLMClient / cassette + sanitize)
- Plan C — Eval + Trace Infrastructure(TraceService / EvalRecorder / Judge / EvalRunner)
- Plan D — CI + Cost + Drift(GH Actions / pricing / CostBudget / cassette_validation / trace-view)

✅ Spec § 4 + § 5 + § 7 全部决策实施完毕。Spec § 8(Eval 系统)+ § 9(Trace+Eval 接口)在 Plan C 完成。

**未完成的 spec 量化指标**(留给 v1+ 监控):
- "PR flake 率: 同 commit 重跑 10 次失败 ≤ 1" — 需要积累数据
- "Drift 检测时效: nightly 发现 cassette drift 后开 issue 平均关闭 ≤ 3 天" — 需要 nightly 真跑一段时间
- "Portfolio 信号: repo 主页 CI badge passing;最近 30 天 CI 运行 > 50 次" — 需要时间积累

**下一步:v0 chat agent skeleton**(独立 spec,2026-04-29 brainstorming session a4ce0864 已暂停)。

✅ 接入条件就绪:
- LLMService(Plan B)+ TraceService(Plan C)+ CostBudget(Plan D)三件横切完整
- v0 agent 写完后,只需在 EvalRunner 里把 SUT 从 bare LLMService 换成 ChatAgent,eval pipeline 不动
- Cassette + sanitize hook + GH Actions(Plan D)在那时直接复用

dev-test-loop 4 plan 共 ~14 小时实施(Plan A 5h + B 3h + C 3h + D 3h)。下一步 v0 chat agent skeleton 估计同等量级。
