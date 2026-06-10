"""裁判重测一致性测试(元评估落地第三项,位置翻转的适配版)。

位置翻转审计是为成对比较(A vs B)设计的;本体系裁判是单答 pass/fail 判定,
故改测重测稳定性——同一答案判 k 次,看判定翻不翻(裁判方差/温度致漂)。
"""

from __future__ import annotations

from eval.memory_dialogue.meta_eval.judge_stability import compute_stability


def test_all_stable() -> None:
    # 每条 3 次判定都一致
    repeats = [[True, True, True], [False, False, False]]
    r = compute_stability(repeats)
    assert r.n == 2
    assert r.consistency_rate == 1.0
    assert r.flipped == 0


def test_one_flip() -> None:
    repeats = [[True, True, True], [True, False, True], [False, False, False]]
    r = compute_stability(repeats)
    assert r.n == 3
    assert r.flipped == 1  # 第二条翻了
    assert abs(r.consistency_rate - 2 / 3) < 1e-9


def test_majority_resolves_flip() -> None:
    repeats = [[True, False, True]]  # 多数 True
    r = compute_stability(repeats)
    assert r.majority_verdicts == [True]
    assert r.flipped == 1


def test_format_declares() -> None:
    from eval.memory_dialogue.meta_eval.judge_stability import format_stability

    r = compute_stability([[True, True, True]])
    out = format_stability(r, repeats=3)
    assert "重测" in out and "翻" in out


def test_empty_safe() -> None:
    r = compute_stability([])
    assert r.n == 0 and r.consistency_rate == 0.0
