"""复杂档(排序/筛选)LLM 抽取判分 —— 正则判 set 偏弱(把"提到"当"选中"),改用 LLM
把 agent 自由文本答案抽成结构(有序名单 / 选中集合)再与 gold 比。

spec: docs/superpowers/specs/2026-06-17-question-gen-mvp-design.md(判分器硬化项)
设计:judge_structured 收一个注入的 complete(prompt)->文本,纯解析/对齐逻辑可单测;
complete 真实现走 dashscope(make_complete),runner 与离线重判共用。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any

from eval.question_gen import case, stock_pool

Complete = Callable[[str], Awaitable[str]]

_RANK_PROMPT = (
    "下面是对一个『涨幅排名』问题的回答。请从中抽出回答**最终给出的**涨幅从高到低的"
    '前 {n} 名股票名,按名次顺序。只输出一个 JSON 数组(如 ["贵州茅台","五粮液"]),'
    "名字用回答里出现的写法;若回答没给出明确排名(数据不全/未作答),输出 []。"
    "不要输出任何其它文字。\n\n回答:\n{answer}"
)
_SET_PROMPT = (
    "下面是对一个『股票筛选』问题的回答。请从中抽出回答**最终判定为满足条件**的股票名集合。"
    "规则:① 明确判定有股票满足 → 输出那些股票名的 JSON 数组;② 明确判定没有任何股票满足 → 输出 [];"
    '③ 回答因数据不全/计算未完成/未给出确定结论 → 输出 ["__未完成__"]。'
    "名字用回答里出现的写法,只输出 JSON 数组,不要其它文字。\n\n回答:\n{answer}"
)


def _parse_json_array(text: str) -> list[str]:
    """从 LLM 输出里抠出第一个 JSON 数组并解析为 str 列表;失败返回 []。"""
    m = re.search(r"\[.*?\]", text, re.S)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [str(x).strip() for x in arr if str(x).strip()] if isinstance(arr, list) else []


def _align(names: list[str], canonical: list[str]) -> list[str]:
    """把抽出的自由名对齐到候选股的规范名(含简称:一方是另一方子串即算命中)。

    保序、去重;对不上的丢弃。
    """
    out: list[str] = []
    for raw in names:
        for c in canonical:
            if (raw in c or c in raw) and c not in out:
                out.append(c)
                break
    return out


async def judge_structured(c: case.ComputationCase, answer: str, *, complete: Complete) -> bool:
    """ranking/set 用 LLM 抽取 + 对齐后与 gold 比;scalar/multi_scalar 不归此处。"""
    canonical = [stock_pool.get(ts).name for ts in c.stocks]
    if c.gold_shape == "ranking":
        gold_names = [g[0] for g in c.gold]
        raw = await complete(_RANK_PROMPT.format(n=len(gold_names), answer=answer))
        aligned = _align(_parse_json_array(raw), canonical)
        return aligned[: len(gold_names)] == gold_names
    if c.gold_shape == "set":
        raw = await complete(_SET_PROMPT.format(answer=answer))
        extracted = _parse_json_array(raw)
        if extracted == ["__未完成__"]:
            return False  # 数据不全/未作答 → 不算对(即便 gold 恰为空集)
        aligned_set = set(_align(extracted, canonical))
        return aligned_set == set(c.gold)
    raise ValueError(f"judge_structured 只判 ranking/set,收到 {c.gold_shape!r}")


def make_complete(model: str | None = None) -> Complete:
    """dashscope(OpenAI compatible-mode)一发式补全 complete(prompt)->文本。temperature=0。"""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.environ.get(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
    )
    mdl = model or os.environ.get("DASHSCOPE_MODEL", "qwen-plus")

    async def complete(prompt: str) -> str:
        resp = await client.chat.completions.create(
            model=mdl,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return resp.choices[0].message.content or ""

    return complete


__all__: list[Any] = ["judge_structured", "make_complete", "Complete"]
