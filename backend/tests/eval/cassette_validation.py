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
from openai import OpenAI
from app.services.cost_budget import CostBudget
from app.services.llm_response import Tier
from app.services.llm_service import LLMService

CASSETTES_ROOT = Path("backend/tests/fixtures/cassettes")
SIMILARITY_THRESHOLD = 8  # 0-10 scale; spec § 4 says 0.8


def _extract_first_interaction(cassette_path: Path) -> tuple[str, str, str] | None:
    """Returns (model, prompt, recorded_response) or None if cassette is empty/unsupported.

    Only handles LLM-shaped cassettes (OpenAI-compatible chat.completions response).
    Non-LLM cassettes (e.g. Bocha search API) are skipped — drift detection for
    those uses different signal types and lives outside this validator.
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
    resp_obj = json.loads(resp_str)
    # Skip non-LLM cassettes (no `choices` key — e.g. search APIs)
    if "choices" not in resp_obj:
        return None
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

    print(
        f"\nTotal cassettes: {len(cassettes)} | drifts: {len(drifts)} | spent: ¥{budget.spent_cny:.4f}"
    )
    if drifts:
        print("Drift detected in:")
        for d in drifts:
            print(f"  - {d}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
