"""v1.x A5b: DebateOrchestrator — 2 round × 2 advocate orchestration.

设计原则(spec § 4 / § 10):
- Round 1: BullAdvocate + BearAdvocate parallel via asyncio.gather +
  asyncio.to_thread (advocates 是 sync,用 to_thread wrap)
- Round 2: 同 parallel,Bull 看 bear_v1 / Bear 看 bull_v1 产 v2 + rebut_targets
- Round 1 全失败 → return None (Writer 走 v0.8.5 单线路径)
- Round 2 任一失败 → 全退到 round 1 final (rounds_completed=1, 避免不对称 debate)
- 总 latency 用 time.perf_counter 测;cost 本期 0.0 (caller 后期从 trace_service 聚合)

spec ref: 2026-05-16-v1.x-bull-bear-debate-design.md § 4 / § 8 / § 10
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.agents.bear_advocate import BearAdvocate
from app.agents.bull_advocate import BullAdvocate
from app.agents.debate_schemas import DebateTrace
from app.agents.schemas import ResearchState

__all__ = ["DebateOrchestrator"]

logger = logging.getLogger(__name__)


class DebateOrchestrator:
    """2 round × 2 advocate orchestrator."""

    def __init__(self, *, bull: BullAdvocate, bear: BearAdvocate) -> None:
        self._bull = bull
        self._bear = bear

    def run(self, state: ResearchState) -> DebateTrace | None:
        """Synchronous entry; uses asyncio.run for parallel advocate calls."""
        return asyncio.run(self._run_async(state))

    async def _run_async(self, state: ResearchState) -> DebateTrace | None:
        start = time.perf_counter()

        # Round 1: parallel via asyncio.gather + asyncio.to_thread
        bull_v1, bear_v1 = await asyncio.gather(
            asyncio.to_thread(self._bull.advocate_round_1, state),
            asyncio.to_thread(self._bear.advocate_round_1, state),
        )

        # Round 1 全失败 → return None (graceful skip)
        if bull_v1 is None and bear_v1 is None:
            logger.warning("DebateOrchestrator: round 1 全失败, graceful skip")
            return None

        # Round 1 单边失败 → 返 partial trace (rounds_completed=1)
        if bull_v1 is None or bear_v1 is None:
            logger.warning(
                "DebateOrchestrator: round 1 单边失败 (bull=%s, bear=%s); rounds=1",
                bull_v1 is not None,
                bear_v1 is not None,
            )
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return DebateTrace(
                bull_v1=bull_v1,
                bear_v1=bear_v1,
                bull_v2=None,
                bear_v2=None,
                total_cost_cny=0.0,
                total_latency_ms=elapsed_ms,
                rounds_completed=1,
            )

        # Round 2: parallel,跟 advocate.advocate_round_2(state, opposing_v1) positional
        bull_v2, bear_v2 = await asyncio.gather(
            asyncio.to_thread(self._bull.advocate_round_2, state, bear_v1),
            asyncio.to_thread(self._bear.advocate_round_2, state, bull_v1),
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        # Round 2 任一失败 → 全退到 v1 final (rounds_completed=1, 避免不对称 debate)
        if bull_v2 is None or bear_v2 is None:
            logger.warning(
                "DebateOrchestrator: round 2 任一失败 (bull_v2=%s, bear_v2=%s); 退到 v1 final",
                bull_v2 is not None,
                bear_v2 is not None,
            )
            return DebateTrace(
                bull_v1=bull_v1,
                bear_v1=bear_v1,
                bull_v2=bull_v2,  # 仍记录(可观测),但 caller 用 rounds_completed 判
                bear_v2=bear_v2,
                total_cost_cny=0.0,
                total_latency_ms=elapsed_ms,
                rounds_completed=1,
            )

        return DebateTrace(
            bull_v1=bull_v1,
            bear_v1=bear_v1,
            bull_v2=bull_v2,
            bear_v2=bear_v2,
            total_cost_cny=0.0,
            total_latency_ms=elapsed_ms,
            rounds_completed=2,
        )
