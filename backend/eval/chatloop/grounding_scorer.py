"""grounding scorer(行为④,裁判)。复用 eval.memory.faithful_answer + provenance 思路。

判定:回答里每个**事实论断**能否从证据推出 → 二元 PASS/FAIL。
- 免责声明在判 grounding 前剥离(blueprint § 8.1.1 铁律②:只判 grounding,不判免责)。
- 弃答(refusal markers)= PASS(诚实无编造)。
- 裁判模型独立(默认 qwen-plus,区别于 SUT 的 deepseek-v4-flash,防自我偏好)。
"""

from __future__ import annotations

import re
from typing import Any

from eval.chatloop.scorers import DISCLAIMER_MARK
from eval.memory.faithful_answer_metric import faithful_answer

# 弃答标记(与 read_phase REFUSAL_MARKERS 同源)
REFUSAL_MARKERS: tuple[str, ...] = (
    "没有这个信息", "没跟我聊过", "没有跟我聊过", "没聊过", "没提过", "没说过",
    "无法回答", "没有相关", "不知道", "没有找到",
)


def strip_disclaimer(answer: str) -> str:
    """剥掉含「不构成投资建议」的整句(及前置标点),只留事实内容供 grounding 判。"""
    text = answer or ""
    # 去掉以句末标点分隔、含免责标记的尾句
    sentences = re.split(r"(?<=[。!?\n])", text)
    kept = [s for s in sentences if DISCLAIMER_MARK not in s and "仅供参考" not in s]
    return "".join(kept).strip()


def is_abstention(answer: str) -> bool:
    stripped = strip_disclaimer(answer)
    return any(m in stripped for m in REFUSAL_MARKERS)


class GroundingJudge:
    """二元 grounding 裁判 —— AsyncOpenAI 直连,模型独立可配。"""

    def __init__(self, model: str = "qwen-plus") -> None:
        from openai import AsyncOpenAI

        from app.config.llm_config import LLMConfig

        cfg = LLMConfig()
        self._client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        self._model = model

    async def _ask(self, prompt: str, *, max_tokens: int = 400) -> str:
        r = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0,
        )
        return r.choices[0].message.content or ""

    async def decompose_to_claims(self, answer: str) -> list[str]:
        prompt = (
            "把下面这段回答拆成原子事实论断,每行一条。"
            "只拆**可证伪的事实/数字陈述**(如某数值、某事件),"
            "**忽略**寒暄、免责声明、主观措辞、提问。若没有事实论断,输出空。\n\n"
            f"回答:\n{answer}"
        )
        out = await self._ask(prompt)
        return [
            re.sub(r"^[\s\-\d.、)]+", "", ln).strip()
            for ln in out.splitlines()
            if ln.strip() and "无" != ln.strip()
        ]

    async def is_grounded(self, claim: str, facts: list[dict[str, Any]]) -> bool:
        evidence = "\n".join(str(f.get("text", f)) for f in facts)
        prompt = (
            "判断下面这条论断是否被给定证据**直接支持**(数字必须一致;证据没提到=不支持)。"
            "只回 yes 或 no。\n\n"
            f"证据:\n{evidence}\n\n论断:{claim}"
        )
        out = await self._ask(prompt, max_tokens=10)
        return out.strip().lower().startswith("yes")


async def score_grounding_pass(answer: str, evidence: str, judge: GroundingJudge) -> dict[str, Any]:
    """单条 grounding 二元判定。返回 {pass, faithfulness, abstain}。"""
    if is_abstention(answer):
        return {"pass": True, "faithfulness": 1.0, "abstain": True}
    stripped = strip_disclaimer(answer)
    faith = await faithful_answer(stripped, [{"text": evidence}], judge)
    return {"pass": faith >= 1.0, "faithfulness": faith, "abstain": False}


__all__ = ["GroundingJudge", "score_grounding_pass", "strip_disclaimer", "is_abstention"]
