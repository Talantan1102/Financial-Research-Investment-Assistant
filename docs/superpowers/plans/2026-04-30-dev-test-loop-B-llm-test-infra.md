# Dev-Test-Loop B — LLM Test Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the LLM half of the test pyramid — `LLMService` + `TierRouter` contract, `MockLLMClient` (static dict + pattern fallback + recorded fixture), and `pytest-recording`-based cassette replay — so that L0/L1/L2 tests can run without (or with deterministic) LLM access. Deliver one working demo test in each of L0/L1/L2.

**Architecture:**
- **`app.services.LLMService`** is the single chokepoint for all LLM calls. It takes a `tier: Literal["fast","balanced","deep"]` arg and delegates model selection to `TierRouter`. v0 maps all three tiers to `deepseek-v4-flash` (spec § 7).
- **Mode dispatch happens at client-injection time, not inside `LLMService`.** `LLMService(client=...)` accepts any object satisfying the `ChatClient` protocol. Tests use fixtures to inject a `MockLLMClient` (L1) or a real OpenAI client whose HTTP calls are captured/replayed by `pytest-recording` (L2). `LLMService` itself never branches on `LLM_MODE`.
- **`MockLLMClient` is hybrid (spec § 4 MC5):** ① static dict lookup → ② regex/pattern fallback → ③ recorded JSON fixture → ④ raise. Failure-loud is the rule — silent fallthrough is what makes mocks rot.
- **Cassettes live in `backend/tests/fixtures/cassettes/`, are committed, and are sanitized by a pre-commit hook** that greps for `dashscope-`, `sk-`, `bearer ` and refuses commits if any cassette leaks credentials.

**Tech Stack:**
- Already in Plan A baseline: `openai>=1.40` (httpx-based), `pytest`, `poethepoet`, `pre-commit`, `ruff`, `mypy strict on app.services.*`
- New in Plan B: `pytest-recording` (vcrpy modern fork), `PyYAML` (for static-dict fixture loader; pinned alongside)

**Status inherited from Plan A:**
- `backend/tests/{unit,integration,e2e,eval}/` exist with autouse fixtures forcing `LLM_MODE` per layer.
- `backend/tests/fixtures/{cassettes,llm_mocks}/` are scaffolded (empty directories).
- `backend/tests/conftest.py` exposes a session-default `LLM_MODE=none` and an `llm_mode` fixture.
- `pyproject.toml` declares `app.services.*` as a mypy strict module (`disallow_untyped_defs = true`) — every file in this plan must be 100% typed.
- Module names are rooted at `app.*` (not `backend.app.*`); `backend/` is the source-root, not a package.

---

## File Structure

| Path | Purpose | Created/Modified |
|---|---|---|
| `backend/app/services/__init__.py` | Package marker for new strict-typed services dir | Create |
| `backend/app/services/llm_response.py` | `LLMResponse` Pydantic schema | Create |
| `backend/app/services/tier_router.py` | `TierRouter` config-driven model resolver | Create |
| `backend/app/services/llm_service.py` | `LLMService` + `ChatClient` Protocol | Create |
| `backend/app/services/llm_mock_client.py` | `MockLLMClient` (MC1 + MC2 + MC4) | Create |
| `backend/tests/fixtures/llm_mocks/agent_decisions.yaml` | MC1 static-dict fixture (1 sample entry) | Create |
| `backend/tests/fixtures/llm_mocks/recorded/sample_critic.json` | MC4 hand-crafted recorded fixture (1 sample) | Create |
| `backend/tests/fixtures/cassettes/.gitattributes` | Mark cassettes as text for diff-readability | Create |
| `backend/tests/conftest.py` | **Modify** — add `mock_llm_client` + `vcr_config` fixtures | Modify |
| `backend/tests/unit/test_tier_router.py` | L0 demo: `TierRouter` config resolution | Create |
| `backend/tests/unit/test_llm_response.py` | L0 demo: `LLMResponse` schema roundtrip | Create |
| `backend/tests/unit/test_llm_mock_client.py` | L0 demo: `MockLLMClient` 3-tier dispatch | Create |
| `backend/tests/integration/test_llm_service_with_mock.py` | L1 demo: `LLMService` + injected `MockLLMClient`, asserts on outputs | Create |
| `backend/tests/e2e/test_llm_service_cassette.py` | L2 demo: `LLMService` + real OpenAI client, cassette replay | Create |
| `backend/tests/fixtures/cassettes/test_llm_service_cassette/test_chat_fast_tier_returns_response.yaml` | The recorded cassette (created by Task 11) | Create |
| `scripts/check_cassette_sanitize.py` | Pre-commit hook: refuses commits with leaked credentials | Create |
| `.pre-commit-config.yaml` | Wire the new hook | Modify |
| `pyproject.toml` | Add `pytest-recording` + `pyyaml` deps; add `poe test-fidelity` / `poe test-flake-check` | Modify |

**Files NOT touched in Plan B (deferred):**
- `app.agents.*`, `app.tools.*`, `app.orchestration.*` — no agent uses `LLMService` yet; v0 spec wires them in.
- `app.service.*` (singular, legacy) — scheduled for v0 deletion; ignored by mypy.
- Eval golden set, `TraceService`, GH Actions nightly, `EVAL_COST_LIMIT_CNY` enforcement — Plan C/D scope.

---

## Task 1: `LLMResponse` Pydantic schema

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/llm_response.py`
- Create: `backend/tests/unit/test_llm_response.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_llm_response.py
"""L0 — LLMResponse schema roundtrip and required-field invariants."""

import pytest
from pydantic import ValidationError

from app.services.llm_response import LLMResponse


def test_minimal_response_validates() -> None:
    r = LLMResponse(
        content="hello",
        model="deepseek-v4-flash",
        tier="fast",
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
        cost_cny=0.0001,
        latency_ms=320,
    )
    assert r.content == "hello"
    assert r.cache_hit is False  # default


def test_negative_tokens_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            content="x",
            model="m",
            tier="fast",
            prompt_tokens=-1,
            completion_tokens=0,
            total_tokens=0,
            cost_cny=0.0,
            latency_ms=0,
        )


def test_invalid_tier_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            content="x",
            model="m",
            tier="ultra",  # type: ignore[arg-type]
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_cny=0.0,
            latency_ms=0,
        )


def test_roundtrip_json() -> None:
    r = LLMResponse(
        content="hi",
        model="m",
        tier="balanced",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_cny=0.0,
        latency_ms=1,
    )
    assert LLMResponse.model_validate_json(r.model_dump_json()) == r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/unit/test_llm_response.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services'` or similar.

- [ ] **Step 3: Implement the schema**

Create `backend/app/services/__init__.py` (empty file — package marker).

Create `backend/app/services/llm_response.py`:

```python
"""LLMResponse — the unified return shape from any LLMService.chat call.

Stable across v0~v3 per spec § 7. Adding fields is fine; renaming/removing
breaks all downstream consumers (tools, eval runner, trace exporter).
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["fast", "balanced", "deep"]


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    parsed: dict[str, Any] | None = None
    model: str
    tier: Tier
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_cny: float = Field(ge=0.0)
    latency_ms: int = Field(ge=0)
    cache_hit: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/unit/test_llm_response.py -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Verify mypy strict on the new file**

Run: `uv run mypy backend/app/services/llm_response.py`
Expected: `Success: no issues found in 1 source file`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/__init__.py backend/app/services/llm_response.py backend/tests/unit/test_llm_response.py
git commit -m "feat(services): add LLMResponse Pydantic contract

原因 layer: services"
```

---

## Task 2: `TierRouter` — config-driven tier→model resolver

**Files:**
- Create: `backend/app/services/tier_router.py`
- Create: `backend/tests/unit/test_tier_router.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_tier_router.py
"""L0 — TierRouter config resolution + interface stability."""

import pytest

from app.services.tier_router import TierConfig, TierRouter


def test_default_v0_config_all_tiers_resolve_to_v4_flash() -> None:
    router = TierRouter.from_default_v0_config()
    assert router.resolve("fast") == "deepseek-v4-flash"
    assert router.resolve("balanced") == "deepseek-v4-flash"
    assert router.resolve("deep") == "deepseek-v4-flash"


def test_custom_config_resolves_per_tier() -> None:
    cfg = TierConfig(fast="m1", balanced="m2", deep="m3")
    router = TierRouter(cfg)
    assert router.resolve("fast") == "m1"
    assert router.resolve("deep") == "m3"


def test_unknown_tier_raises() -> None:
    router = TierRouter.from_default_v0_config()
    with pytest.raises(ValueError, match="unknown tier"):
        router.resolve("ultra")  # type: ignore[arg-type]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/unit/test_tier_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.tier_router'`.

- [ ] **Step 3: Implement `TierRouter`**

Create `backend/app/services/tier_router.py`:

```python
"""TierRouter — resolves a logical tier to a concrete model name.

v0 maps all tiers to deepseek-v4-flash (spec § 7). The interface stays
stable so v1+ can swap to multi-model with a config change only.
"""

from pydantic import BaseModel, ConfigDict

from app.services.llm_response import Tier

V0_DEFAULT_MODEL = "deepseek-v4-flash"


class TierConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    fast: str
    balanced: str
    deep: str


class TierRouter:
    def __init__(self, config: TierConfig) -> None:
        self._config = config

    @classmethod
    def from_default_v0_config(cls) -> "TierRouter":
        return cls(
            TierConfig(
                fast=V0_DEFAULT_MODEL,
                balanced=V0_DEFAULT_MODEL,
                deep=V0_DEFAULT_MODEL,
            )
        )

    def resolve(self, tier: Tier) -> str:
        match tier:
            case "fast":
                return self._config.fast
            case "balanced":
                return self._config.balanced
            case "deep":
                return self._config.deep
            case _:
                raise ValueError(f"unknown tier: {tier!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/unit/test_tier_router.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Verify mypy strict**

Run: `uv run mypy backend/app/services/tier_router.py`
Expected: `Success`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/tier_router.py backend/tests/unit/test_tier_router.py
git commit -m "feat(services): add TierRouter with v0 single-model default

原因 layer: services"
```

---

## Task 3: `LLMService` skeleton + `ChatClient` Protocol

**Files:**
- Create: `backend/app/services/llm_service.py`

(Demo unit test for `LLMService` with a fake client lives in Task 9; this task is contract-only.)

- [ ] **Step 1: Implement `LLMService` and `ChatClient` Protocol**

Create `backend/app/services/llm_service.py`:

```python
"""LLMService — the single chokepoint for all LLM calls in the app.

Mode dispatch happens by injecting a different ChatClient at construction
time (mock client in L1 tests, real openai client in L2 cassette / live);
LLMService itself never branches on LLM_MODE.
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

from app.services.llm_response import LLMResponse, Tier
from app.services.tier_router import TierRouter


class ChatCompletionRaw(Protocol):
    """Minimal subset of openai.types.ChatCompletion that we depend on.

    Keeps LLMService from coupling to openai-specific types so MockLLMClient
    can return a plain object satisfying this shape.
    """

    @property
    def content(self) -> str: ...

    @property
    def prompt_tokens(self) -> int: ...

    @property
    def completion_tokens(self) -> int: ...


class ChatClient(Protocol):
    """Anything LLMService can drive — real openai client wrapper or mock."""

    def chat(
        self,
        prompt: str,
        model: str,
        schema: dict[str, Any] | None,
    ) -> ChatCompletionRaw: ...


class LLMService:
    def __init__(
        self,
        client: ChatClient,
        tier_router: TierRouter | None = None,
    ) -> None:
        self._client = client
        self._tier_router = tier_router or TierRouter.from_default_v0_config()
        if os.getenv("LLM_MODE") == "none":
            raise RuntimeError(
                "LLMService instantiated under LLM_MODE=none — L0 unit tests "
                "must not construct LLMService. Use TierRouter / LLMResponse "
                "directly, or mark the test as integration."
            )

    def chat(
        self,
        prompt: str,
        tier: Tier = "fast",
        schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        model = self._tier_router.resolve(tier)
        started = time.perf_counter()
        raw = self._client.chat(prompt=prompt, model=model, schema=schema)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return LLMResponse(
            content=raw.content,
            parsed=None,
            model=model,
            tier=tier,
            prompt_tokens=raw.prompt_tokens,
            completion_tokens=raw.completion_tokens,
            total_tokens=raw.prompt_tokens + raw.completion_tokens,
            cost_cny=0.0,
            latency_ms=latency_ms,
        )
```

> **Note on `cost_cny=0.0`**: real cost calculation needs per-model price tables, which are Plan D scope (cost guardrail § 6 of spec). Plan B leaves the field on the schema and stub-returns 0.0 — eval/trace consumers can already read the field; populating it is a one-file change later.

- [ ] **Step 2: Verify mypy strict**

Run: `uv run mypy backend/app/services/llm_service.py`
Expected: `Success`.

- [ ] **Step 3: Verify ruff**

Run: `uv run ruff check backend/app/services/llm_service.py`
Expected: `All checks passed`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/llm_service.py
git commit -m "feat(services): add LLMService + ChatClient protocol

原因 layer: services"
```

---

## Task 4: Verify `pytest-recording` + `pyyaml` deps already present

> **Plan-sync note (2026-04-30)**: Plan A merged with `pyyaml>=6.0` (runtime) and `pytest-recording>=0.13` (dev) already declared in `pyproject.toml` and locked. Plan B's original "add deps" step is therefore a no-op. We keep this task slot as an explicit verification gate so the implementer doesn't silently assume packages are present.

**Files:**
- (no modifications expected; if anything is missing, add it here)

- [ ] **Step 1: Confirm runtime + dev deps declared**

Run: `grep -E "pyyaml|pytest-recording" pyproject.toml`
Expected: both lines present, with version specifiers.

- [ ] **Step 2: Confirm both installed in this worktree's `.venv`**

Run: `uv pip list | grep -iE "pyyaml|pytest-recording"`
Expected: prints both with concrete versions (e.g. `pyyaml 6.0.x`, `pytest-recording 0.13.x`).

- [ ] **Step 3: Smoke-import**

Run: `uv run python -c "import yaml; import pytest_recording; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: No commit**

If steps 1-3 all pass, this task produces no diff. If any step fails, add the missing dep, `uv sync --extra dev`, then commit:

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): backfill <package> for Plan B test infra

原因 layer: chore"
```

---

## Task 5: `MockLLMClient` — MC1 static dict + MC2 pattern fallback + MC4 recorded fixture

**Files:**
- Create: `backend/app/services/llm_mock_client.py`
- Create: `backend/tests/fixtures/llm_mocks/agent_decisions.yaml`
- Create: `backend/tests/fixtures/llm_mocks/recorded/sample_critic.json`
- Create: `backend/tests/unit/test_llm_mock_client.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_llm_mock_client.py
"""L0 — MockLLMClient 3-tier dispatch + fail-loud on miss."""

from pathlib import Path

import pytest

from app.services.llm_mock_client import MockLLMClient, MockMissError

FIXTURES = Path("backend/tests/fixtures/llm_mocks")


def test_static_dict_hit() -> None:
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r = client.chat(prompt="What is the price of 600519.SH?", model="m", schema=None)
    assert "600519" in r.content


def test_pattern_fallback_hit() -> None:
    """A prompt not in the static dict but matching a known regex falls back."""
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r = client.chat(prompt="Please get the quote for 000001.SZ", model="m", schema=None)
    # pattern entries return a templated string with the captured ticker
    assert "000001" in r.content


def test_recorded_fixture_hit() -> None:
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r = client.chat(
        prompt="__recorded__:sample_critic",  # explicit recorded-fixture pointer
        model="m",
        schema=None,
    )
    assert r.content.startswith("{")  # recorded fixture is a JSON blob


def test_total_miss_raises() -> None:
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    with pytest.raises(MockMissError, match="no static / pattern / recorded match"):
        client.chat(prompt="something nobody put in the fixtures", model="m", schema=None)


def test_token_counts_are_deterministic() -> None:
    """Same prompt → same token counts. Critical for L1 flake control."""
    client = MockLLMClient.from_fixture_dir(FIXTURES)
    r1 = client.chat(prompt="What is the price of 600519.SH?", model="m", schema=None)
    r2 = client.chat(prompt="What is the price of 600519.SH?", model="m", schema=None)
    assert r1.prompt_tokens == r2.prompt_tokens
    assert r1.completion_tokens == r2.completion_tokens
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/unit/test_llm_mock_client.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the static-dict fixture**

Create `backend/tests/fixtures/llm_mocks/agent_decisions.yaml`. Include exactly **one** static entry and **one** pattern entry — enough to drive the tests above. Format intent (do not copy field-by-field; pick names that read naturally):

- An `entries:` list where each item has either an `exact:` key (full prompt to match) or a `pattern:` key (regex against the prompt).
- Each entry has a `response:` block with `content` (str), `prompt_tokens` (int), `completion_tokens` (int).
- For pattern entries, allow `{group_1}` etc. interpolation in the response content from regex capture groups.

Constraints:
- Static entry: prompt = `"What is the price of 600519.SH?"`, response content contains `"600519"`.
- Pattern entry: regex captures a ticker like `(\d{6}\.(SH|SZ))` and templates it back into the response.

- [ ] **Step 4: Create the recorded fixture**

Create `backend/tests/fixtures/llm_mocks/recorded/sample_critic.json` containing a single JSON object:

- `id`: `"sample_critic"`
- `response.content`: a JSON-encoded string that looks like a critic rubric output (4 dimensions × score + evidence, matching spec § 8 R4 shape)
- `response.prompt_tokens`: 200
- `response.completion_tokens`: 80

The lookup key is the trailing `:<id>` after the `__recorded__:` prefix in the prompt.

- [ ] **Step 5: Implement `MockLLMClient`**

Create `backend/app/services/llm_mock_client.py`. Required surface:

- `class MockMissError(LookupError)` — raised when no layer matches.
- `class MockLLMClient` — implements the `ChatClient` protocol from Task 3:
  - `@classmethod from_fixture_dir(path: Path) -> MockLLMClient` — loads `agent_decisions.yaml` + indexes `recorded/*.json`.
  - `def chat(prompt, model, schema) -> ChatCompletionRaw` — dispatches in this order: ① `__recorded__:<id>` short-circuit; ② exact-match in static dict; ③ regex pattern entries (first match wins); ④ raise `MockMissError`.
- A small `_RawCompletion` dataclass (or NamedTuple) that satisfies `ChatCompletionRaw` from Task 3 (`content` + `prompt_tokens` + `completion_tokens` properties).

Constraints (must hold):
- Determinism: same prompt → same response → same token counts (no randomness anywhere).
- Pattern interpolation: `{group_1}` in response content is replaced with the regex's first capture group.
- File 100% typed (mypy strict).

- [ ] **Step 6: Run tests**

Run: `uv run pytest backend/tests/unit/test_llm_mock_client.py -v`
Expected: 5 tests PASS.

- [ ] **Step 7: Verify mypy + ruff**

Run: `uv run mypy backend/app/services/llm_mock_client.py && uv run ruff check backend/app/services/llm_mock_client.py`
Expected: Both clean.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/llm_mock_client.py backend/tests/fixtures/llm_mocks/ backend/tests/unit/test_llm_mock_client.py
git commit -m "feat(services): add MockLLMClient with MC1+MC2+MC4 dispatch

原因 layer: services"
```

---

## Task 6: Extend global conftest — `mock_llm_client` + `vcr_config` fixtures

**Files:**
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Read the existing conftest**

Already read in this plan's preamble; no new behavior is being subtracted, only added.

- [ ] **Step 2: Add the fixtures**

Append to `backend/tests/conftest.py`:

```python
from pathlib import Path

from app.services.llm_mock_client import MockLLMClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    """L1 fixture — provides a deterministic MockLLMClient for injection
    into LLMService. L0 tests must not use this (LLM_MODE=none guard).
    """
    return MockLLMClient.from_fixture_dir(FIXTURES_DIR / "llm_mocks")


@pytest.fixture(scope="module")
def vcr_config() -> dict[str, object]:
    """L2 fixture — pytest-recording config. Sanitizes auth headers, matches
    on method/scheme/host/path/body so prompt changes invalidate cassettes.
    """
    return {
        "filter_headers": [
            "authorization",
            "x-dashscope-api-key",
            "x-api-key",
            "openai-organization",
        ],
        "filter_post_data_parameters": [],
        "decode_compressed_response": True,
        "record_mode": os.environ.get("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path", "body"],
    }
```

> **Note on `record_mode="none"` default**: this means cassettes are **replayed only** unless the operator opts in via `VCR_RECORD_MODE=once` / `new_episodes`. This protects PR CI from accidentally hitting real LLMs on a fork PR.

- [ ] **Step 3: Smoke-test the fixtures load**

Create a throwaway test or run the existing L0 suite — the fixture imports alone must not break collection.

Run: `uv run pytest backend/tests/unit/ -v --collect-only`
Expected: collects without ImportError.

- [ ] **Step 4: Verify mypy on conftest**

Run: `uv run mypy backend/tests/conftest.py`
Expected: clean (note: tests are not in the strict tier — `disallow_untyped_defs` stays false here).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test(infra): add mock_llm_client + vcr_config fixtures

原因 layer: tests"
```

---

## Task 7: Cassette sanitize pre-commit hook

**Files:**
- Create: `scripts/check_cassette_sanitize.py`
- Modify: `.pre-commit-config.yaml`
- Create: `backend/tests/fixtures/cassettes/.gitattributes`

- [ ] **Step 1: Add the .gitattributes**

Create `backend/tests/fixtures/cassettes/.gitattributes`:

```
*.yaml text eol=lf
```

This keeps cassette diffs reviewable across OSes.

- [ ] **Step 2: Write the sanitize script**

Create `scripts/check_cassette_sanitize.py`. Required behavior:

- Takes file paths on argv (pre-commit passes them).
- For each path under `backend/tests/fixtures/cassettes/`, scan for any of these case-insensitive substrings:
  - `dashscope-` (raw key prefix)
  - `sk-` (OpenAI / OpenAI-compatible key prefix)
  - `bearer ` (Authorization header value)
  - `x-api-key:` (literal header line)
- If any hit is found, print `<path>:<line_number>: leaked credential pattern: <substring>` to stderr and exit non-zero.
- Otherwise exit 0.
- File 100% typed; ruff clean; uses only stdlib (no `requests`, no `pyyaml` — text scan suffices).

Add a small inline test or a manual run example in a docstring at the top of the file showing one positive and one negative case.

- [ ] **Step 3: Manually verify the script**

Run a positive case (must fail):

```bash
mkdir -p /tmp/cassette-test && echo "Authorization: Bearer sk-test123" > /tmp/cassette-test/leak.yaml
uv run python scripts/check_cassette_sanitize.py /tmp/cassette-test/leak.yaml
echo "exit=$?"
```

Expected: exit ≠ 0, stderr mentions `sk-` or `bearer`.

Run a negative case (must succeed):

```bash
echo "Authorization: <REDACTED>" > /tmp/cassette-test/clean.yaml
uv run python scripts/check_cassette_sanitize.py /tmp/cassette-test/clean.yaml
echo "exit=$?"
```

Expected: exit = 0.

Then `rm -rf /tmp/cassette-test`.

- [ ] **Step 4: Wire the hook**

Modify `.pre-commit-config.yaml` to add a local hook:
- `id: check-cassette-sanitize`
- `name: Check that cassettes contain no live credentials`
- `entry: uv run python scripts/check_cassette_sanitize.py`
- `language: system`
- `files: ^backend/tests/fixtures/cassettes/.*\.ya?ml$`
- `pass_filenames: true`

- [ ] **Step 5: Verify pre-commit picks it up**

Run: `uv run pre-commit run check-cassette-sanitize --all-files`
Expected: passes (no cassettes yet, so no files matched is fine — pre-commit prints `(no files to check) Skipped`).

- [ ] **Step 6: Commit**

```bash
git add scripts/check_cassette_sanitize.py .pre-commit-config.yaml backend/tests/fixtures/cassettes/.gitattributes
git commit -m "chore(test): add cassette credential-sanitize pre-commit hook

原因 layer: chore"
```

---

## Task 8: L1 demo integration test — `LLMService` + injected `MockLLMClient`

**Files:**
- Create: `backend/tests/integration/test_llm_service_with_mock.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/integration/test_llm_service_with_mock.py
"""L1 — LLMService end-to-end with MockLLMClient injected.

This is the canonical demo: a real LLMService instance (not stubbed) plus a
mock client. Asserts on output shape + tier resolution + latency_ms presence.
"""

import pytest

from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService


def test_chat_fast_tier_returns_v0_default_model(
    mock_llm_client: MockLLMClient,
) -> None:
    svc = LLMService(client=mock_llm_client)
    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
    assert r.tier == "fast"
    assert r.model == "deepseek-v4-flash"
    assert "600519" in r.content
    assert r.latency_ms >= 0
    assert r.total_tokens == r.prompt_tokens + r.completion_tokens


def test_chat_with_pattern_match_returns_templated_content(
    mock_llm_client: MockLLMClient,
) -> None:
    svc = LLMService(client=mock_llm_client)
    r = svc.chat(prompt="Please get the quote for 000001.SZ", tier="balanced")
    assert "000001" in r.content
    assert r.tier == "balanced"


def test_chat_unknown_prompt_propagates_mock_miss(
    mock_llm_client: MockLLMClient,
) -> None:
    """LLMService doesn't swallow MockMissError — bubbles up so test sees a
    real failure when the fixture is incomplete."""
    from app.services.llm_mock_client import MockMissError

    svc = LLMService(client=mock_llm_client)
    with pytest.raises(MockMissError):
        svc.chat(prompt="totally unseen prompt", tier="fast")
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest backend/tests/integration/test_llm_service_with_mock.py -v`
Expected: 3 tests PASS. The autouse fixture in `integration/conftest.py` already sets `LLM_MODE=mock`.

- [ ] **Step 3: Confirm L0 guard fires**

Sanity-check that `LLMService` cannot be constructed under `LLM_MODE=none`. Add this temporary verification:

Run:
```bash
LLM_MODE=none uv run python -c "from app.services.llm_service import LLMService; from app.services.llm_mock_client import MockLLMClient; from pathlib import Path; LLMService(client=MockLLMClient.from_fixture_dir(Path('backend/tests/fixtures/llm_mocks')))"
```
Expected: raises `RuntimeError: LLMService instantiated under LLM_MODE=none ...`.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_llm_service_with_mock.py
git commit -m "test(integration): add L1 demo for LLMService + MockLLMClient

原因 layer: tests"
```

---

## Task 9: API connectivity spike — verify DashScope key + `deepseek-v4-flash` reachable

**Files:**
- (no permanent file — this task produces evidence, not artifacts)

> **Why this is a separate task**: spec § 7 names `deepseek-v4-flash` but no code in the repo has actually called it. If the model id is wrong, or the key is dead, **Task 10 (record cassette) will fail in a confusing way**. We spend ≤ 5 minutes here to fail-fast.

- [ ] **Step 1: Confirm `.env` has the key**

Run: `grep DASHSCOPE_API_KEY backend/.env | grep -v "your-dashscope" && echo OK`
Expected: prints the line and `OK`. If not, **stop and ask the user**.

- [ ] **Step 2: Probe the API**

Run (one-shot, no file written):

```bash
uv run python - <<'PY'
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv("backend/.env")
client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url=os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
)
r = client.chat.completions.create(
    model="deepseek-v4-flash",
    messages=[{"role": "user", "content": "Say hi in one word."}],
    max_tokens=10,
)
print("MODEL_OK:", r.choices[0].message.content)
print("USAGE:", r.usage)
PY
```

Expected outcomes:
- **Success**: prints `MODEL_OK: <some word>` and a usage object. Proceed to Step 3.
- **Auth failure** (`401` / `invalid_api_key`): stop, ask the user to renew the key.
- **Model not found** (`model_not_exist` or similar): stop, sync the spec — the canonical model id may differ (e.g. `deepseek-chat` on DashScope). Update spec § 7 and `tier_router.V0_DEFAULT_MODEL` together, then redo Task 2 step 6 commit.
- **Other error**: stop, surface to user.

- [ ] **Step 3: Record the result inline**

Open this plan file and replace the `[Step 3 evidence]` placeholder under "Plan B retrospective — Task 9 spike result" with the model id confirmed and the response snippet. (Plan stays a living doc; the spike result is the only persistent record we keep.)

- [ ] **Step 4: Commit (docs only)**

If the spec needed to be updated: `git commit -m "docs(spec): sync v0 model id after Task 9 spike\n\n原因 layer: docs"`. If everything matched: no commit needed in this task.

---

## Task 10: pytest-recording integration — wire the L2 fixture path

**Files:**
- Modify: `backend/tests/conftest.py` (add `pytest_plugins` registration if not auto-discovered)
- (No new test in this task — the test gets added in Task 11.)

- [ ] **Step 1: Confirm pytest discovers the plugin**

Run: `uv run pytest --version`
Expected: includes `pytest-recording-X.Y.Z` in the plugin list. (`pytest-recording` registers via entry points — no manual `pytest_plugins` needed.) If absent, re-check Task 4's `uv sync`.

- [ ] **Step 2: Confirm the `vcr_config` fixture is wired**

Run a quick collection check:

```bash
uv run pytest backend/tests/e2e/ -v --collect-only --co -q
```

Expected: collects without errors. (No e2e test exists yet, so this is a no-op collection.)

- [ ] **Step 3: Verify default `record_mode` is `none`**

Run:

```bash
uv run python - <<'PY'
import os; os.environ["LLM_MODE"] = "cassette"
from backend.tests.conftest import vcr_config  # noqa
# fixture is generator-shaped only when used through pytest; here we want
# to verify the function returns the dict directly
import inspect
sig = inspect.signature(vcr_config.__wrapped__) if hasattr(vcr_config, "__wrapped__") else None
print("ok")
PY
```

Or simpler: trust pytest, and verify in Task 11 by attempting a record without `VCR_RECORD_MODE=once` set — pytest-recording must refuse to make new HTTP calls.

- [ ] **Step 4: Commit**

If no file was modified, skip. Otherwise:

```bash
git add backend/tests/conftest.py
git commit -m "test(infra): finalize pytest-recording wiring

原因 layer: tests"
```

---

## Task 11: L2 demo e2e test — record real cassette + replay

**Files:**
- Create: `backend/tests/e2e/test_llm_service_cassette.py`
- Create: `backend/tests/fixtures/cassettes/test_llm_service_cassette/test_chat_fast_tier_returns_response.yaml` (auto-created in Step 3)

- [ ] **Step 1: Write the test**

```python
# backend/tests/e2e/test_llm_service_cassette.py
"""L2 — LLMService against the real DashScope-compatible endpoint, replayed
via cassette. The cassette is committed to git after Task 11 step 3 records
it for the first time. Subsequent runs are pure replay (no network).
"""

import os

import pytest
from openai import OpenAI

from app.services.llm_response import LLMResponse
from app.services.llm_service import ChatCompletionRaw, LLMService


class _OpenAIClientAdapter:
    """Adapts openai.OpenAI to the ChatClient protocol used by LLMService."""

    def __init__(self, client: OpenAI) -> None:
        self._c = client

    def chat(self, prompt, model, schema):  # type: ignore[no-untyped-def]
        r = self._c.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=64,
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
def real_openai_adapter() -> _OpenAIClientAdapter:
    """Real client. Under cassette mode the HTTP call is intercepted by
    pytest-recording — no live traffic. Under VCR_RECORD_MODE=once the call
    goes out and gets recorded.
    """
    return _OpenAIClientAdapter(
        OpenAI(
            api_key=os.environ.get("DASHSCOPE_API_KEY", "fake-for-replay"),
            base_url=os.environ.get(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    )


@pytest.mark.vcr
def test_chat_fast_tier_returns_response(
    real_openai_adapter: _OpenAIClientAdapter,
) -> None:
    svc = LLMService(client=real_openai_adapter)
    r: LLMResponse = svc.chat(prompt="Say hi in one word.", tier="fast")
    assert r.tier == "fast"
    assert r.model == "deepseek-v4-flash"
    assert len(r.content) > 0
    assert r.prompt_tokens > 0
```

- [ ] **Step 2: Replay-only run must fail (cassette doesn't exist yet)**

Run: `uv run pytest backend/tests/e2e/test_llm_service_cassette.py -v`
Expected: FAIL with a `vcr.errors.CannotOverwriteExistingCassetteException` (or similar — pytest-recording refuses to create a cassette under `record_mode=none`).

This proves the safety mechanism works: PR CI cannot accidentally hit real LLMs.

- [ ] **Step 3: Record the cassette**

Run:

```bash
VCR_RECORD_MODE=once uv run pytest backend/tests/e2e/test_llm_service_cassette.py -v
```

Expected:
- Test PASSES.
- A new file appears at `backend/tests/fixtures/cassettes/test_llm_service_cassette/test_chat_fast_tier_returns_response.yaml`.
- The cost on the DashScope dashboard increases by ≤ ¥0.01.

- [ ] **Step 4: Verify the cassette is sanitized**

Run: `uv run python scripts/check_cassette_sanitize.py backend/tests/fixtures/cassettes/test_llm_service_cassette/test_chat_fast_tier_returns_response.yaml`
Expected: exit 0.

If non-zero: open the cassette, inspect what leaked, file an issue against `vcr_config.filter_headers` in Task 6, and re-record.

- [ ] **Step 5: Replay the cassette (no network)**

Run:
```bash
unset VCR_RECORD_MODE  # ensure default record_mode=none
uv run pytest backend/tests/e2e/test_llm_service_cassette.py -v
```
Expected: PASS, and **fast** (≤ 200ms per spec § 5 quantification).

- [ ] **Step 6: Verify cassette size**

Run: `du -h backend/tests/fixtures/cassettes/test_llm_service_cassette/test_chat_fast_tier_returns_response.yaml`
Expected: ≤ 50KB (spec § 5 budget).

- [ ] **Step 7: Commit**

```bash
git add backend/tests/e2e/test_llm_service_cassette.py backend/tests/fixtures/cassettes/test_llm_service_cassette/
git commit -m "test(e2e): add L2 cassette demo for LLMService.chat

原因 layer: tests"
```

---

## Task 12: `poe test-fidelity` + `poe test-flake-check` + Plan B retrospective

**Files:**
- Modify: `pyproject.toml` (add two `[tool.poe.tasks]` entries)
- Modify: this file (fill retrospective section)

> **Note**: `test-fidelity` and `test-flake-check` are **scaffolded as runnable but minimal** in Plan B. Their full implementations (run mock vs live, compare assertion pass-rates / re-run 100x) need eval infra (Plan C) or live LLM access budget (Plan D). What we deliver here is the **command surface** so spec § 4's quantification metrics have a concrete `poe` invocation to point at.

- [ ] **Step 1: Add the two poe tasks**

In `pyproject.toml`, add to `[tool.poe.tasks]`:

```toml
# Spec § 4 quantification scaffold — full impl in Plan C/D.
# Today: just runs the L1 suite under LLM_MODE=mock and prints a pointer.
test-fidelity.cmd = "pytest backend/tests/integration/ -v"
test-fidelity.help = "[Plan B scaffold] Mock vs live fidelity check — full impl in Plan C."

# Spec § 4 quantification scaffold — full impl in Plan C/D.
# Today: re-runs the L1 suite N=10 times to surface obvious flakes.
test-flake-check.cmd = "pytest backend/tests/integration/ --count=10"
test-flake-check.help = "[Plan B scaffold] Re-runs L1 to spot flakes — full impl in Plan C."
```

The `--count` flag requires `pytest-repeat`; if not already installed, also append `pytest-repeat>=0.9` to dev deps in this same task and `uv sync`.

- [ ] **Step 2: Verify both tasks run**

Run: `uv run poe test-fidelity` then `uv run poe test-flake-check`
Expected:
- `test-fidelity`: L1 suite passes once.
- `test-flake-check`: L1 suite runs 10x — must pass all 10 runs (otherwise the mock client is non-deterministic and Task 5 test_token_counts_are_deterministic missed something).

- [ ] **Step 3: Fill the Plan B retrospective**

Append to the bottom of this plan file. Use the same template Plan A used (`docs/superpowers/plans/2026-04-29-dev-test-loop-A-repo-bootstrap.md` § Retrospective):
- Implementation completion date
- Branch + PR link + merge commit
- Total commits / time
- 对的设计(3 条)
- 错的设计 / plan 漏了什么(3 条)
- 下个 spec / plan 要避免(3 条)
- 沉淀到 memory(具体 memory file 名)
- Subagent-driven-development 节奏复盘
- Plan C 启动条件(eval golden set + judge + TraceService 接口已可起草)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock docs/superpowers/plans/2026-04-30-dev-test-loop-B-llm-test-infra.md
git commit -m "docs(plan): Plan B retrospective + poe scaffold tasks

原因 layer: docs"
```

---

## Acceptance Criteria

- [ ] `uv run poe ci` passes (existing Plan A gate).
- [ ] `uv run pytest backend/tests/unit/ backend/tests/integration/ backend/tests/e2e/ -v` passes — every demo test green.
- [ ] `uv run mypy backend/app/services/` passes with strict tier (`disallow_untyped_defs = true`).
- [ ] `uv run pre-commit run --all-files` passes including the new `check-cassette-sanitize` hook.
- [ ] One cassette exists under `backend/tests/fixtures/cassettes/`, sanitized, ≤ 50KB.
- [ ] L2 cassette test replays in ≤ 200ms (spec § 5 quantification ⑤).
- [ ] `poe test-fidelity` and `poe test-flake-check` runnable; flake-check passes 10/10 (mock determinism check).
- [ ] Plan retrospective filled.

## Test plan (run on completion)

- Local: `uv run poe ci`
- Local: `uv run pytest backend/tests/ -v`
- Local: `unset VCR_RECORD_MODE && uv run pytest backend/tests/e2e/ -v` — confirms replay-only mode.
- Local: `uv run pre-commit run --all-files`
- Local: `uv run poe test-flake-check` — 10/10 green.

---

## Notes for the implementer

- **`LLM_MODE=none` is enforced in L0**, but `LLMService.__init__` also has a runtime guard. If a future test author tries to construct `LLMService` from L0, they get a clear error instead of silently spinning up a real client.
- **The `ChatCompletionRaw` Protocol decouples `LLMService` from the `openai` types.** Don't accidentally `import openai.types.ChatCompletion` in `llm_service.py` — that breaks the Mock client's contract.
- **Cassettes are committed.** The `check_cassette_sanitize.py` hook is the only line of defense against leaking a key into git history. Don't disable it.
- **Plan B is a scaffold for Plan C/D.** `cost_cny=0.0` stub, `test-fidelity` placeholder, `test-flake-check` placeholder — all tracked here so Plan C can pick them up with full context.
- **Per Plan A retrospective**: this plan deliberately writes "intent + constraint" for fixture file contents (Task 5 step 3-4), config dicts (Task 6), and poe task bodies (Task 12) — not the literal lines. Discover the right shape during implementation and `git commit` the actual content.

---

## Plan B retrospective — Task 9 spike result

- **Date probed**: 2026-04-30
- **Confirmed model id**: `deepseek-v4-flash` (the spec-canonical name resolves on DashScope without `model_not_exist`).
- **Endpoint**: `https://dashscope.aliyuncs.com/compatible-mode/v1` (OpenAI-compatible, default in `.env.example`).
- **Sample response**: prompt `"Say hi in one word."` (max_tokens=10) → content `"Hi"`. Usage: `prompt_tokens=10, completion_tokens=25, total_tokens=35`. Note `completion_tokens_details.reasoning_tokens=22` — `deepseek-v4-flash` is a reasoning model on DashScope, so completion-token cost includes hidden reasoning. The `total_tokens == prompt + completion` invariant from Task 1 still holds (35 == 10 + 25), but eval / cost dashboards downstream should be aware that a 1-word user-visible answer can be billed for ~25 completion tokens.
- **Action taken**: none — model id matches spec, no spec sync needed.
- **Dev-environment note**: `all_proxy=socks5://127.0.0.1:7897` was set in the shell and tripped httpx's missing-`socksio` import. Workaround: `unset all_proxy https_proxy http_proxy` before any DashScope call. DashScope is a mainland-China endpoint and shouldn't be proxied. **Task 11 must `unset` these proxy env vars before recording the cassette**, otherwise pytest-recording will hit the same `ImportError`.

---

## Retrospective

**Implementation completion date**: 2026-04-30
**Branch**: `feat/dev-test-loop-B` (from `3ca069d`, ahead of `main` by 13 commits including Task 12)
**Total commits**: 13 (10 task commits + 3 fix commits)
**Total time**: ~3 hours (vs Plan A's ~5h — Plan B is smaller because the test layer scaffolding was done in Plan A)

### 对的设计(3 条)

1. **Mode dispatch via dependency injection at construction time, not LLM_MODE branching inside `LLMService`.** `LLMService.chat` is mode-agnostic — Tasks 8/11 swap between `MockLLMClient` and `_OpenAIClientAdapter` without `LLMService` knowing the difference. Cassette interception happens at the HTTP layer below the adapter. This kept `LLMService` at 81 lines and made the L2 demo test trivially mirror the L1 demo. **The single-`LLM_MODE=none` runtime guard at `__init__`** is the only mode-aware code in the whole service — fail-loud on misuse, zero branches in the hot path. Will replicate this pattern in Plan C's `TraceService` (one chokepoint, no mode flags inside).

2. **Plan A 沉淀的"intent + 约束"风格让 implementer 有判断空间.** Tasks 4/5/7/12 deliberately wrote constraints, not literal config. The Task 5 yaml schema design ended up cleaner than what I would have prescribed (flat `entries:` list, two-deep nesting). Tasks 1-3/8/11 still got verbatim code from the plan because their contracts are stability promises (`LLMResponse` schema, `ChatClient` protocol). Mixing prescription where it's load-bearing with intent where it isn't kept the plan honest.

3. **Pre-commit `check_cassette_sanitize.py` doubled as a debugging tool.** When Task 11 fix subagent moved the cassette to `fixtures/cassettes/`, the hook immediately surfaced a `dashscope-` substring in the response header that the original cassette path had silently bypassed. The sanitize check found a real (low-severity, vendor-name) leak that the loose initial path layout hid. Fail-loud sanitize at PR time > "we'll audit cassettes later".

### 错的设计 / plan 漏了什么(3 条)

1. **Plan didn't anticipate pytest-recording's default `cassette_library_dir` location.** The plan File Structure section put cassettes at `backend/tests/fixtures/cassettes/...`, the Task 7 sanitize hook regex assumed the same, but pytest-recording 0.13 defaults to `<test-file-dir>/cassettes/`. Task 11 implementer recorded under `backend/tests/e2e/cassettes/` and the hook didn't notice. **The path divergence created an actual security hole** — the `x-dashscope-call-gateway: true` response header would have shipped with the cassette unsanitized if Task 11 reviewer hadn't caught the path mismatch. **Lesson**: any spec that depends on a third-party plugin's default path must include a 30-second spike at plan-write time to verify the default matches the spec, or specify the override fixture (`vcr_cassette_dir`) explicitly. (Same family of bug as Plan A's `pytest_configure` hook lesson — third-party pytest plugin defaults bite when the plan assumes them.)

2. **Plan didn't anticipate the dev shell's proxy env vars contaminating CI.** Task 9 spike worked only after `unset all_proxy https_proxy http_proxy` in the shell. Task 11 hit the same wall during recording (worked around in shell). **`poe ci` then failed at the very end of Task 12** because pytest spawned a subprocess that inherited the proxy vars. Required adding an autouse `_unset_proxy_env` fixture in `backend/tests/e2e/conftest.py`. **Lesson**: shell-level env workarounds during a spike are a tell that the test infra needs the same workaround. Don't ship a Plan that says "unset proxy before running" — bake it into the layer conftest. Add this to the Plan-template checklist: "any env var the spike touched must have a permanent fixture-level handler before the plan ships."

3. **Plan didn't say how the test process loads `.env`.** Task 11 implementer hit a 401 on the first record because pytest doesn't auto-load dotenv. They worked around with `export DASHSCOPE_API_KEY=...` in the shell. Plan should have either (a) added a session-scoped fixture in `conftest.py` calling `load_dotenv("backend/.env")`, or (b) explicitly told implementer to invoke pytest with `set -a; . backend/.env; set +a; pytest ...`. Currently the cassette is recorded but the path is brittle for future re-records. **Plan C must specify .env loading for tests.**

### 下个 spec / plan 要避免(3 条)

1. **任何依赖第三方 pytest plugin 默认路径的 plan,先跑 30 秒 spike** verify default 行为(已在 Plan A retrospective 提到过 pytest 多 layer 协同的 spike 教训;Plan B 再次撞同型 bug,这条规则需要升级为 plan-template 默认 checklist)。
2. **任何 spike 阶段需要 shell 级 env workaround 的事项,plan 必须把 workaround 编进 fixture/conftest 而不是写"实施时手动 unset"。**否则 CI 在生产环境复现 spike 环境时必定 fail。
3. **测试 infra 项目里"测试自身需要的环境"必须显式建模.** `.env` loading、proxy unset、cassette dir override —— 这三个在 Plan B 里都是事后补丁,Plan C 的 spec 必须用一节明确"测试 process 看到的 env 长什么样"。

### 沉淀到 memory

- [feedback_third_party_plugin_defaults.md](memory/feedback_third_party_plugin_defaults.md) — 任何 plan 引用第三方 pytest 插件默认行为时,必须先 30 秒 spike 验证,否则建立显式 override fixture
- [feedback_test_env_modeling.md](memory/feedback_test_env_modeling.md) — 测试 infra 项目里 .env loading / proxy 处理 / 第三方插件路径必须 plan 阶段就建模到 fixture,不能依赖实施时 shell 级 workaround
- [project_llm_service_contract.md](memory/project_llm_service_contract.md) — `LLMService.chat(prompt, tier, schema=None) -> LLMResponse` 是 v0~v3 稳定契约;mode dispatch 通过 DI(`ChatClient` Protocol)而非 LLM_MODE 分支;`LLMResponse.total_tokens == prompt_tokens + completion_tokens` invariant 由 model_validator 强制

### Subagent-driven-development 节奏复盘

- 总 subagent 调用:~19 次(12 implementer + 2 spec reviewer + 1 code quality reviewer + 4 fix subagent)— 比 Plan A 的 ~30 减少 37%
- 减少来自:简单 paste-from-plan task(Task 2/3/8/10)inline review,跳过 reviewer 派单
- 全 review 投入回报最高的两个点:
  - Task 5(logic-heavy MockLLMClient)spec reviewer 抓到 fullmatch+search 偏差(Critical)
  - Task 11(cassette 录制)我自己 read implementer report 抓到 cassette path 偏差 → fix subagent 又顺手发现真 leak
- 主对话 context 消耗:中等(比 Plan A 略低,但写 plan + retrospective 占 ~30%)
- Plan B 的 fix 路径都是单轮(implementer fix → inline verify);没像 Plan A Task 2 那样走 5 commit ping-pong。原因:plan 写"intent + 约束"减少了 spec ↔ impl 来回澄清

### Plan C 启动条件

Plan B 完成后,Plan C(eval-trace-infra)的依赖已就位:

- ✅ `LLMService` 接口稳定,可被 eval runner 通过 DI 调用
- ✅ `MockLLMClient` 可被注入,L1 eval-runner unit test 不走 LLM
- ✅ Cassette 闭环可用,L2 eval-runner integration test 可用 cassette 跑
- ✅ `mypy strict on app.services.*` 已扩展;Plan C 的 `app.tracing.*` / `app.eval.*` 应纳入 strict tier
- ✅ Pre-commit cassette sanitize 已就位,nightly cassette validation(spec § 5)可在 Plan D 加 GH Actions step

Plan C 范围:`TraceService` Pydantic 契约 + spans 表 + Eval golden set(70 用例新写)+ judge + cross-judge sanity + nightly job 编排。具体 task 拆分按 spec § 8 + § 9。

**未解风险**:`deepseek-v4-flash` 在 DashScope 是 reasoning model(Task 9 spike 发现),completion_tokens 含隐藏 reasoning。Plan C eval cost 估算时要按 ~3K total tokens / 用例算(spec § 7 已按这个量级假设),实际跑下来如果偏差大,触发 Plan C 的 cost guardrail re-tune。
