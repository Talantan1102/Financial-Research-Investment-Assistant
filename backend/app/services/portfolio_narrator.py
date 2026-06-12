"""portfolio_narrator — AI 叙事:把算好的数翻成人话。

narrate_today(attribution, persona_note) -> str

规则:
- AI 只讲不算:prompt 明确禁止 LLM 给买卖建议、编造/重算数字、预测涨跌。
- LLM_MODE in {"mock","none"} 时走确定性模板,不调真实 LLM。
- 禁止输出包含:建议买 / 建议卖 / 应该减仓 / 应该加仓 / 清仓。
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 红线词(输出前过一遍兜底检查)
# ---------------------------------------------------------------------------

_BANNED_PHRASES = ("建议买", "建议卖", "应该减仓", "应该加仓", "清仓")

_SYSTEM_PROMPT = """\
你只负责把给定数字讲成人话。

硬约束(不得违反):
1. 禁止给买卖建议 — 不得出现"建议买""建议卖""应该减仓""应该加仓""清仓"等字眼。
2. 禁止自己编造或重算数字 — 只引用输入中已有的数字,不能推算新值。
3. 禁止预测涨跌 — 不得说"明天""下周"等前瞻性判断。
4. 挑最该说的一两件事说清楚即可,不要罗列所有数据。
5. 可结合用户在意点(persona_note)选择侧重点。
"""


def _build_user_message(attribution: dict, persona_note: str | None) -> str:
    total_pct = attribution.get("total_pct", 0.0)
    breakdown = attribution.get("stock_breakdown", {})
    contributions = attribution.get("contributions", [])

    lines = [f"今日整盘涨跌:{total_pct:+.2f}%"]

    if breakdown:
        mkt = breakdown.get("market", 0.0)
        sec = breakdown.get("sector_excess", 0.0)
        idio = breakdown.get("idiosyncratic", 0.0)
        lines.append(
            f"股票三层拆解 — 大盘贡献:{mkt:+.2f}%,板块超额:{sec:+.2f}%,个股自身:{idio:+.2f}%"
        )

    if contributions:
        top = contributions[0]
        lines.append(
            f"拖累/贡献最大的持仓:{top.get('ts_code', '')}  贡献:{top.get('contrib_pct', 0.0):+.2f}%"
        )

    if persona_note:
        lines.append(f"用户在意点:{persona_note}")

    lines.append("\n请用两三句自然中文把上面数据讲给投资者听。")
    return "\n".join(lines)


def _deterministic_template(attribution: dict, persona_note: str | None) -> str:
    """LLM_MODE=mock/none 时的确定性占位叙事,不调任何外部 API。"""
    total_pct: float = attribution.get("total_pct", 0.0)
    contributions: list[dict] = attribution.get("contributions", [])

    sign = "下跌" if total_pct < 0 else "上涨"
    summary = f"今天整盘{sign} {abs(total_pct):.2f}%。"

    detail = ""
    if contributions:
        top = contributions[0]
        contrib = top.get("contrib_pct", 0.0)
        code = top.get("ts_code", "")
        direction = "拖累" if contrib < 0 else "贡献"
        detail = f"主要来自 {code} 对组合的{direction}({contrib:+.2f}%)。"

    persona_line = ""
    if persona_note:
        persona_line = f"（用户关注点：{persona_note}）"

    text = summary + detail + persona_line
    return text


def _check_no_banned(text: str) -> str:
    """兜底:确认输出不含红线词。若含则截断并附注。"""
    for phrase in _BANNED_PHRASES:
        if phrase in text:
            # 替换为空,保证不泄出禁词
            text = text.replace(phrase, "***")
    return text


async def narrate_today(
    attribution: dict,
    persona_note: str | None = None,
) -> str:
    """把组合归因数字翻成人话短文。

    Args:
        attribution: compute_daily_attribution 返回的 dict(或 dataclasses.asdict 后的版本)。
        persona_note: 用户在意点提示(可 None)。

    Returns:
        两三句中文叙事;LLM_MODE=mock/none 时返回确定性模板。
    """
    mode = os.environ.get("LLM_MODE", "none")

    # mock / none 模式:确定性模板,不调 LLM
    if mode in {"mock", "none"}:
        text = _deterministic_template(attribution, persona_note)
        return _check_no_banned(text)

    # 真实模式:调 LLM
    from app.services.openai_client import build_llm_service_from_env

    llm = build_llm_service_from_env()
    user_msg = _build_user_message(attribution, persona_note)
    full_prompt = f"{_SYSTEM_PROMPT}\n\n---\n{user_msg}"

    response = llm.chat(full_prompt, tier="fast")
    text = response.content or ""
    return _check_no_banned(text)
