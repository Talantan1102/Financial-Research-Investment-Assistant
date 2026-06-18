"""intents 确定性单测：纯字符串拼接，手写数据，不依赖网络/DB/LLM。"""

import pytest

from eval.question_gen.intents import (
    INTENT,
    q_corr,
    q_dual,
    q_filter,
    q_rank,
    q_single,
)


def test_intent_constant():
    assert INTENT == "stock_study"


# ---- q_single ----


def test_q_single_return_contains():
    # 调用方传的 window_cn 已含"近",故用包含断言避免"近近"歧义。
    out = q_single("涨幅", "贵州茅台", "近一年")
    assert "贵州茅台" in out
    assert "涨" in out


def test_q_single_drawdown():
    out = q_single("回撤", "五粮液", "近三个月")
    assert "五粮液" in out
    assert "最大回撤" in out


def test_q_single_volatility():
    out = q_single("波动", "泸州老窖", "近三年")
    assert "泸州老窖" in out
    assert "年化波动率" in out


def test_q_single_cagr_fixed_three_years():
    out = q_single("CAGR", "五粮液", "近一年")
    assert "CAGR" in out
    assert "最近三年" in out


def test_q_single_unknown_raises():
    with pytest.raises(ValueError):
        q_single("未知", "x", "近一年")


# ---- q_dual ----


def test_q_dual():
    out = q_dual("贵州茅台", "近一年")
    assert "贵州茅台" in out
    assert "最大回撤" in out
    assert "年化波动率" in out


# ---- q_corr ----


def test_q_corr():
    out = q_corr("茅台", "五粮液", "近一年")
    assert "茅台" in out
    assert "五粮液" in out
    assert "相关" in out


# ---- q_rank ----


def test_q_rank():
    out = q_rank("白酒", ["茅台", "五粮液", "泸州"], "近一年")
    assert "白酒" in out
    assert "前三" in out
    # 顿号连接
    assert "茅台、五粮液、泸州" in out


# ---- q_filter ----


def test_q_filter():
    out = q_filter(["茅台", "五粮液"], "近一年")
    assert "涨幅为正" in out
    assert "20%" in out
    assert "茅台、五粮液" in out


def test_q_snapshot_renders_date_and_label():
    from eval.question_gen import intents

    q = intents.q_snapshot("贵州茅台", "PE", "20260612")
    assert "贵州茅台" in q
    assert "2026年06月12日" in q
    assert "市盈率" in q


def test_q_snapshot_unknown_indicator_raises():
    import pytest
    from eval.question_gen import intents

    with pytest.raises(ValueError):
        intents.q_snapshot("贵州茅台", "未知", "20260612")
