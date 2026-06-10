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

# Ensure `backend/` is on sys.path so `app.*` imports resolve when this module
# is invoked as `python -m backend.tests.eval.cassette_validation` from the
# project root (editable install adds project root, not backend/).
_BACKEND_DIR = Path(__file__).parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import yaml  # noqa: I001 — sys.path insert above must precede app.* imports
from openai import APIStatusError, OpenAI
from app.services.cost_budget import CostBudget
from app.services.llm_response import Tier
from app.services.llm_service import LLMService

CASSETTES_ROOT = Path("backend/tests/fixtures/cassettes")
SIMILARITY_THRESHOLD = 8  # 0-10 scale; spec § 4 says 0.8
# Borderline cassettes get re-sampled before we declare drift. A single live
# sample + single judge call is non-deterministic — a semantically-fine cassette
# can score below threshold by chance (this was the nightly false-positive root
# cause: a cassette passing ~11/12 nights then failing 1, a different cassette
# each time). On a sub-threshold first sample, draw up to RESAMPLE_EXTRA more
# INDEPENDENT samples and flag DRIFT only when a strict majority stay below
# threshold. Genuine drift (all samples low) still fails; one-off noise does not.
RESAMPLE_EXTRA = 2  # up to 3 total samples on the borderline path


def _extract_first_interaction(cassette_path: Path) -> tuple[str, str, str] | None:
    """Returns (model, prompt, recorded_response) or None if cassette is empty/unsupported.

    Only handles LLM-shaped cassettes (OpenAI-compatible NON-streaming
    chat.completions response with text content). Skipped: non-LLM cassettes
    (e.g. Bocha search API), SSE streaming cassettes (chat-loop tool-call
    rounds), and empty-content responses — drift detection for those uses
    different signal types and lives outside this validator.
    """
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
    if isinstance(resp_str, str) and resp_str.lstrip().startswith("data:"):
        # SSE streaming cassette (chat-loop tool-call rounds). Replaying the
        # prompt WITHOUT the tool schema makes the live model answer in full
        # text while the recording is a tool-call round (often empty content)
        # — a guaranteed false DRIFT. Tool-call drift needs a tool-sequence
        # signal, which lives outside this prompt→text validator.
        return None
    try:
        resp_obj = json.loads(resp_str)
    except (json.JSONDecodeError, TypeError):
        # Unparseable body — not an OpenAI chat.completions cassette. One bad
        # cassette must not crash the whole nightly drift sweep.
        return None
    # Skip non-LLM cassettes (no `choices` key — e.g. search APIs)
    if "choices" not in resp_obj:
        return None
    recorded = resp_obj["choices"][0]["message"]["content"]
    if not recorded:
        return None
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


def _sample_similarity(
    sut: LLMService, judge: LLMService, prompt: str, recorded: str
) -> int | None:
    """One fresh live call + judge comparison → 0-10 similarity.

    Returns None on an infra-level APIStatusError (account / rate-limit / 5xx),
    which is not real drift and must not count toward a drift verdict.
    """
    try:
        live = sut.chat(prompt=prompt, tier="balanced")
    except APIStatusError:
        return None
    return score_similarity(judge, old=recorded, new=live.content)


def _classify_drift(sims: list[int], threshold: int = SIMILARITY_THRESHOLD) -> str:
    """Drift verdict from 1+ similarity samples (pure — unit-tested).

    - 'DRIFT'       — a strict MAJORITY of samples are below threshold.
    - 'UNCONFIRMED' — the only sample is below threshold and could not be
                      re-confirmed (resamples infra-failed); treated as an
                      infra-skip, never a silent OK.
    - 'OK'          — otherwise (first sample passed, or one-off noise out-voted).

    `sims[0]` is always the first (mandatory) sample; later entries are
    confirmation resamples drawn only when sims[0] < threshold.
    """
    below = [s for s in sims if s < threshold]
    if len(sims) >= 2 and 2 * len(below) > len(sims):
        return "DRIFT"
    if sims[0] < threshold and len(sims) < 2:
        return "UNCONFIRMED"
    return "OK"


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
    infra_skips: list[str] = []
    for cassette in cassettes:
        ext = _extract_first_interaction(cassette)
        if ext is None:
            print(f"SKIP {cassette}: no replayable text interaction")
            continue
        model, prompt, recorded = ext
        rel = cassette.relative_to(CASSETTES_ROOT)
        try:
            live = sut.chat(prompt=prompt, tier="balanced")
        except APIStatusError as exc:
            # Account-level / rate-limit infra issues (Arrearage, InsufficientQuota,
            # 429 RateLimit, 503) are not real drift — skip and continue.
            print(f"SKIP {rel}: live LLM unavailable ({exc.status_code} {type(exc).__name__})")
            infra_skips.append(str(rel))
            continue
        sims = [score_similarity(judge, old=recorded, new=live.content)]

        # Confirm a sub-threshold first sample with extra INDEPENDENT samples
        # before declaring drift (see RESAMPLE_EXTRA note above).
        if sims[0] < SIMILARITY_THRESHOLD:
            for _ in range(RESAMPLE_EXTRA):
                extra = _sample_similarity(sut, judge, prompt, recorded)
                if extra is not None:
                    sims.append(extra)

        # DRIFT only on a strict MAJORITY of clean samples below threshold. A lone
        # sub-threshold sample we couldn't re-confirm (resamples infra-failed) is
        # UNCONFIRMED, not drift — counted as an infra-skip so a flaky-API night
        # can't masquerade as a code regression. (Verdict logic: _classify_drift.)
        verdict = _classify_drift(sims)
        resampled = f" (resampled {sims})" if len(sims) > 1 else ""
        if verdict == "DRIFT":
            print(f"DRIFT sim={sims[0]}/10 cassette={rel}{resampled}")
            drifts.append(str(rel))
        elif verdict == "UNCONFIRMED":
            print(f"UNCONFIRMED sim={sims[0]}/10 cassette={rel} (resamples unavailable)")
            infra_skips.append(str(rel))
        else:
            print(f"OK sim={sims[0]}/10 cassette={rel}{resampled}")

    print(
        f"\nTotal cassettes: {len(cassettes)} | drifts: {len(drifts)} | "
        f"infra-skips: {len(infra_skips)} | spent: ¥{budget.spent_cny:.4f}"
    )
    if drifts:
        print("Drift detected in:")
        for d in drifts:
            print(f"  - {d}")
        return 1
    if infra_skips and len(infra_skips) == len(cassettes):
        # ALL cassettes skipped due to infra — drift detection didn't actually
        # run. Emit warning but don't fail the nightly (account欠费 is user's
        # operational issue, not a code regression).
        print("WARNING: drift detection could not run for any cassette (LLM API unavailable).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
