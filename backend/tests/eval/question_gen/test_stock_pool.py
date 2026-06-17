"""stock_pool 确定性单测：纯函数，不依赖网络/DB/LLM。"""

import pytest

from eval.question_gen.stock_pool import POOL, by_sector, get, sectors_with_at_least


def test_pool_size():
    assert len(POOL) == 15


def test_by_sector_counts():
    grouped = by_sector()
    assert len(grouped["白酒"]) == 5
    assert len(grouped["医药"]) == 2


def test_sectors_with_at_least_three():
    assert sectors_with_at_least(3) == sorted(["白酒", "银行", "新能源"])


def test_get_found():
    assert get("600519.SH").name == "贵州茅台"


def test_get_missing_raises_key_error():
    with pytest.raises(KeyError):
        get("不存在")
