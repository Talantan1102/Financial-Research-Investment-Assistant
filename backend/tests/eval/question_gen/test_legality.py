"""legality 纯函数确定性单测。"""

import pytest

from eval.question_gen.legality import LEGAL, WINDOWS, is_legal, window_cn


def test_cagr_only_legal_for_3y():
    assert is_legal("CAGR", "1y") is False
    assert is_legal("CAGR", "3m") is False
    assert is_legal("CAGR", "3y") is True


def test_common_indicators_legal():
    assert is_legal("涨幅", "3m") is True
    assert is_legal("相关", "1y") is True


def test_unknown_indicator_is_illegal():
    assert is_legal("未知指标", "1y") is False


def test_window_cn_maps_known_codes():
    assert window_cn("1y") == "近一年"
    assert window_cn("3y") == "近三年"
    assert window_cn("3m") == "近三个月"


def test_window_cn_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        window_cn("zzz")


def test_windows_and_legal_consistency():
    # LEGAL 中出现的每个窗口码都应在 WINDOWS 里有中文名
    for windows in LEGAL.values():
        for w in windows:
            assert w in WINDOWS
