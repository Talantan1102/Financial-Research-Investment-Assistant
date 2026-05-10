"""Eval runner runtime deps — wire 真 LLM judge / planner / retriever for nightly / dogfood.

L0/L1 测试不调用此 module(用 mock fixture 直接调 metric 函数).
仅 CLI `python -m backend.eval.memory.eval_runner` 入口跑时用.

设计:
    - judge:    haiku tier LLMService chat 输出 yes/no, claim decomposition
    - planner:  Plan 6 memory_kb_router 输出 RouterDecision → 转 plan obj
    - retriever: HierarchicalMemory.archival_memory_search 包一层(暴露 generate_answer)

NOTE: 此 module 不能 fail import — 测试只在 unit / integration 级别覆盖 metric 函数.
真 CLI 跑时若 LLMService 未配置会在 build_runtime_deps() 内 raise.
"""

from __future__ import annotations

from typing import Any


def build_runtime_deps() -> tuple[Any, Any, Any]:
    """Build (judge, planner, retriever) for live eval run.

    生产用: OpenAI client + chat agent + HierarchicalMemory.
    CI nightly: cassette 模式 (env BOCHA_MODE / VCR record-mode).

    Raises:
        RuntimeError: 若 LLMService 环境变量缺失.
    """
    try:
        from app.services.openai_client import build_llm_service_from_env
    except ImportError as e:
        raise RuntimeError(
            "build_runtime_deps: app.services.openai_client unavailable; "
            "use mock fixtures in test path"
        ) from e

    llm = build_llm_service_from_env()

    class _LiveJudge:
        async def eval(self, query: str, fact: dict[str, Any], prompt: str) -> str:
            resp = await llm.chat(prompt=prompt, tier="haiku", schema=None)
            return resp.text

        async def decompose_to_claims(self, answer: str) -> list[str]:
            resp = await llm.chat(
                prompt=f"分解以下回答为 atomic claims (one per line):\n{answer}",
                tier="haiku",
                schema=None,
            )
            return [line.strip() for line in resp.text.splitlines() if line.strip()]

        async def is_grounded(self, claim: str, facts: list[dict[str, Any]]) -> bool:
            resp = await llm.chat(
                prompt=(f"以下 fact 是否支持 claim '{claim}'?\nfacts: {facts}\nAnswer yes/no."),
                tier="haiku",
                schema=None,
            )
            return resp.text.strip().lower().startswith("yes")

    # planner / retriever 在 CLI 真跑前需要 wire HierarchicalMemory + DB;
    # 此处只 raise to remind, 不直接 wire (避免 import side effect on test path).
    class _PlaceholderPlanner:
        async def plan(self, query: str) -> Any:
            raise RuntimeError(
                "_PlaceholderPlanner: wire real planner in CLI driver "
                "(HierarchicalMemory + chat agent factory)"
            )

    class _PlaceholderRetriever:
        async def archival_memory_search(self, query: str, k: int = 5) -> list[Any]:
            raise RuntimeError(
                "_PlaceholderRetriever: wire HierarchicalMemory.archival_memory_search "
                "with user_id in real CLI driver"
            )

        async def generate_answer(self, query: str, facts: list[Any]) -> str:
            raise RuntimeError("_PlaceholderRetriever.generate_answer: wire in real CLI driver")

    return _LiveJudge(), _PlaceholderPlanner(), _PlaceholderRetriever()
