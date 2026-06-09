"""多轮对话评估:模拟用户(角色扮演)× chat agent(spec § 5,τ-bench 式)。

模拟用户(独立模型,默认 qwen-plus)给定 总目标 + 人设,逐轮挤牙膏跟 agent 对话,
目标满足或问不下去时回 ###STOP###。每个 agent turn 用「全量历史 + 新用户消息」重建
ChatLoopState —— per-turn 计数器(step/budget)自然 reset,而消息历史延续。

防坑(spec § 5.2):只给模拟器 goal、不给参考答案(防泄漏);独立模型防自评;
retail-investor-voice 口语。本切片只验「能跑通 + 产出真多轮对话」,评分(终态/目标达成)留后续。
"""

from __future__ import annotations

import logging
from typing import Any

from eval.chatloop.scenario import Scenario

logger = logging.getLogger(__name__)

_EVAL_USER_ID = "00000000-0000-4000-8000-000000000001"
_STOP = "###STOP###"


class UserSimulator:
    """LLM 扮的散户用户:给定目标+人设,逐轮产出下一句(或 ###STOP###)。"""

    def __init__(self, goal: str, persona: str | None, model: str = "qwen-plus") -> None:
        from openai import AsyncOpenAI

        from app.config.llm_config import LLMConfig

        cfg = LLMConfig()
        self._client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        self._model = model
        self._goal = goal
        self._persona = persona or "普通中国散户,说话口语随意"

    def _prompt(self, transcript: list[dict[str, Any]]) -> str:
        convo = "\n".join(f"我:{t['user']}\n助手:{t['assistant']}" for t in transcript)
        return (
            "你在扮演一个中国散户股民,正跟一个金融助手多轮聊天。\n"
            f"你的真实目标(别一次性倒出来,也别把这句原文说给助手):{self._goal}\n"
            f"你的说话风格/人设:{self._persona}\n"
            "规则:像真人那样口语、简短、一次只说一小部分;一开始说得含糊点逼助手追问;助手问了你再补;"
            "不要替助手查数据、不要自己报答案;不要把上面这句目标原文说给助手。\n"
            f"**何时收尾**:你不是来刁难的。回顾你的目标——如果助手已经把你目标要的核心信息都给到了"
            f"(该问的问了、都答了),就别再硬找问题,直接只回 {_STOP} 这一个词;只有还差关键信息时才继续追问。\n\n"
            "已经发生的对话:\n" + (convo or "(还没开始,请说你的第一句)") + "\n\n"
            f"请只输出你接下来对助手说的一句话(或 {_STOP}):"
        )

    async def next_message(self, transcript: list[dict[str, Any]]) -> str:
        r = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": self._prompt(transcript)}],
            max_tokens=200,
            temperature=0.4,
        )
        return (r.choices[0].message.content or "").strip()


async def run_one_multiturn(
    scenario: Scenario,
    singletons: Any,
    deps: Any,
    *,
    simulator_model: str = "qwen-plus",
    max_turns: int = 5,
) -> dict[str, Any]:
    """跑单个多轮场景,返回 transcript。"""
    from app.chatloop.eval_agent import ChatLoopAgent
    from app.chatloop.gates import GateConfig
    from app.chatloop.loop import ToolLoop
    from app.chatloop.state import ChatLoopState
    from eval.tool_selection._live import build_real_hub

    goal = scenario.intent_goal or scenario.user_input
    sim = UserSimulator(goal, scenario.persona, model=simulator_model)
    history: list[dict[str, Any]] = []
    transcript: list[dict[str, Any]] = []
    stopped = False

    for turn in range(max_turns):
        user_msg = await sim.next_message(transcript)
        if not user_msg or _STOP in user_msg:
            stopped = True
            break
        history.append({"role": "user", "content": user_msg})
        rid = f"clmt-{scenario.case_id}-t{turn}"
        state = ChatLoopState(
            user_id=_EVAL_USER_ID,
            session_id=f"clmt-{scenario.case_id}",
            request_id=rid,
            messages=list(history),
        )
        loop = ToolLoop(
            llm=singletons.llm,
            tool_hub=build_real_hub(singletons),
            context_deps=deps,
            gate_cfg=GateConfig(max_steps=6),
        )
        final = await loop.run(state)
        agent_resp = final.final_response or ChatLoopAgent._last_assistant_content(final)
        tools = [tc.tool_name for tc in ChatLoopAgent._extract_tool_calls(final)]
        history = list(final.messages)  # 携全量历史进下一轮
        transcript.append({"user": user_msg, "assistant": agent_resp, "tools": tools})

    return {
        "case_id": scenario.case_id,
        "goal": goal,
        "persona": scenario.persona,
        "stopped_by_user": stopped,
        "turns": transcript,
    }


async def run_multiturn(
    scenarios: list[Scenario],
    *,
    simulator_model: str = "qwen-plus",
    max_turns: int = 5,
) -> list[dict[str, Any]]:
    """构造真件(MCP async with 包整批)+ 逐场景跑多轮(per-case 错误隔离)。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.app_main import _sqlalchemy_async_pg_url
    from app.chatloop.context import ContextDeps
    from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
    from app.chatloop.worker_wiring import build_heavy_singletons
    from app.services.mcp_client import MCPClient

    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    out: list[dict[str, Any]] = []
    try:
        async with MCPClient.from_subprocess(profile="chat_tools") as mcp:
            sing = await build_heavy_singletons(session_factory=sf, mcp_client=mcp)
            deps = ContextDeps(system_prompt=CHAT_SYSTEM_PROMPT, skill_listing=sing.skill_listing)
            for sc in scenarios:
                try:
                    out.append(
                        await run_one_multiturn(
                            sc, sing, deps, simulator_model=simulator_model, max_turns=max_turns
                        )
                    )
                except Exception as e:  # noqa: BLE001 — per-case 隔离
                    logger.exception("multiturn %s failed", sc.case_id)
                    out.append({"case_id": sc.case_id, "error": f"{type(e).__name__}: {e}", "turns": []})
    finally:
        await engine.dispose()
    return out


class MultiTurnJudge:
    """多轮目标达成裁判(独立模型):看对话结束时助手有没有把用户目标要的核心信息给到。"""

    def __init__(self, model: str = "qwen-plus") -> None:
        from openai import AsyncOpenAI

        from app.config.llm_config import LLMConfig

        cfg = LLMConfig()
        self._client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        self._model = model

    async def goal_met(self, goal: str, transcript: list[dict[str, Any]]) -> tuple[bool, str]:
        convo = "\n".join(f"用户:{t['user']}\n助手:{str(t['assistant'])[:400]}" for t in transcript)
        prompt = (
            "评估一段多轮对话:助手最终有没有把用户目标要的核心信息给到。"
            "只看对话结束时的结果,不纠结过程。\n\n"
            f"用户目标:{goal}\n\n对话:\n{convo}\n\n"
            "回答:第一行只写 yes 或 no(目标核心信息是否达成);第二行一句话理由。"
        )
        r = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0,
        )
        out = (r.choices[0].message.content or "").strip()
        met = out.lower().lstrip().startswith("yes")
        reason = out.split("\n", 1)[1].strip() if "\n" in out else ""
        return met, reason


async def score_multiturn(
    scenario: Scenario, transcript: list[dict[str, Any]], judge: MultiTurnJudge
) -> dict[str, Any]:
    """多轮评分:目标达成(裁判)+ 跨轮政策合规(确定性)+ 效率。"""
    from eval.chatloop.scorers import score_advice, score_disclaimer, should_disclaim

    if not transcript:
        return {"goal_met": False, "goal_reason": "空对话", "advice_violations": 0,
                "disclaimer_req": 0, "disclaimer_ok": 0, "turns": 0, "total_tools": 0}
    met, reason = await judge.goal_met(scenario.intent_goal or scenario.user_input, transcript)
    advice_viol = sum(1 for t in transcript if score_advice(str(t["assistant"])))
    disc_req = [t for t in transcript if should_disclaim(str(t["assistant"]))]
    disc_ok = sum(1 for t in disc_req if score_disclaimer(str(t["assistant"])))
    return {
        "goal_met": met,
        "goal_reason": reason,
        "advice_violations": advice_viol,
        "disclaimer_req": len(disc_req),
        "disclaimer_ok": disc_ok,
        "turns": len(transcript),
        "total_tools": sum(len(t["tools"]) for t in transcript),
    }


__all__ = [
    "UserSimulator",
    "MultiTurnJudge",
    "run_one_multiturn",
    "run_multiturn",
    "score_multiturn",
]
