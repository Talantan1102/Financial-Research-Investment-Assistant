"""judge_llm 纯逻辑单测(_parse_json_array / _align / judge_structured + 假 complete)。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from eval.question_gen import judge_llm
from eval.question_gen.case import ComputationCase


def _case(shape: str, gold: object, stocks: list[str]) -> ComputationCase:
    return ComputationCase(
        case_id="c",
        intent="stock_study",
        difficulty="复杂",
        question="q",
        stocks=stocks,
        indicator="涨幅",
        window="1y",
        gold=gold,
        gold_shape=shape,
        tolerance={},
        meta={},
    )


def _fake(ret: str) -> Callable[[str], Awaitable[str]]:
    async def c(_prompt: str) -> str:
        return ret

    return c


def test_parse_json_array() -> None:
    assert judge_llm._parse_json_array('["X","Y"]') == ["X", "Y"]
    assert judge_llm._parse_json_array('结论:["工商银行"] 满足') == ["工商银行"]
    assert judge_llm._parse_json_array("[]") == []
    assert judge_llm._parse_json_array("没有 json") == []


def test_align_handles_abbreviation() -> None:
    canon = ["贵州茅台", "五粮液", "泸州老窖"]
    assert judge_llm._align(["茅台", "五粮液"], canon) == ["贵州茅台", "五粮液"]
    assert judge_llm._align(["未知股"], canon) == []
    # 保序去重
    assert judge_llm._align(["茅台", "茅台"], canon) == ["贵州茅台"]


@pytest.mark.asyncio
async def test_judge_ranking_order() -> None:
    c = _case(
        "ranking", [["贵州茅台", 1.0], ["五粮液", 2.0]], ["600519.SH", "000858.SZ", "000568.SZ"]
    )
    assert await judge_llm.judge_structured(c, "x", complete=_fake('["茅台","五粮液"]')) is True
    # 顺序反 → False
    assert await judge_llm.judge_structured(c, "x", complete=_fake('["五粮液","茅台"]')) is False
    # 没作答 → False
    assert await judge_llm.judge_structured(c, "x", complete=_fake("[]")) is False


@pytest.mark.asyncio
async def test_judge_set_including_empty() -> None:
    c1 = _case("set", ["工商银行"], ["601398.SH", "600036.SH", "000001.SZ"])
    assert await judge_llm.judge_structured(c1, "x", complete=_fake('["工商"]')) is True
    assert await judge_llm.judge_structured(c1, "x", complete=_fake('["招商"]')) is False
    # 空集 gold == 抽出空集
    c2 = _case("set", [], ["601398.SH", "600036.SH"])
    assert await judge_llm.judge_structured(c2, "x", complete=_fake("[]")) is True
    assert await judge_llm.judge_structured(c2, "x", complete=_fake('["工商"]')) is False
    # 未完成(数据不全/punt)→ 不算对,即便 gold 是空集
    assert await judge_llm.judge_structured(c2, "x", complete=_fake('["__未完成__"]')) is False


@pytest.mark.asyncio
async def test_judge_structured_rejects_scalar() -> None:
    c = _case("scalar", 1.0, ["600519.SH"])
    with pytest.raises(ValueError):
        await judge_llm.judge_structured(c, "x", complete=_fake("[]"))
