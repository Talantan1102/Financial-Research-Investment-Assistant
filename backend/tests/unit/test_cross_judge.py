"""L0 — pure-function tests for Spearman + sanity utilities used by
scripts/cross_judge_check.py. The script's CLI shell is not unit-tested.
"""

import math

from scripts.cross_judge_check import rank, spearman


def test_rank_no_ties() -> None:
    assert rank([3.0, 1.0, 2.0]) == [3.0, 1.0, 2.0]


def test_rank_with_ties_uses_average() -> None:
    # values: 1, 2, 2, 4 → ranks: 1, 2.5, 2.5, 4
    assert rank([1.0, 2.0, 2.0, 4.0]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_perfect_positive() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [10.0, 20.0, 30.0, 40.0]
    assert math.isclose(spearman(xs, ys), 1.0)


def test_spearman_perfect_negative() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [40.0, 30.0, 20.0, 10.0]
    assert math.isclose(spearman(xs, ys), -1.0)


def test_spearman_uncorrelated_close_to_zero() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [3.0, 1.0, 4.0, 2.0]
    rho = spearman(xs, ys)
    assert -0.5 < rho < 0.5
