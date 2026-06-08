"""裁判-人类一致率 meta-eval 计算逻辑测试(元评估研报落地第一项)。

报一致率必须声明口径(元评估研报第 24 条):单答判定 / 无平局 / 单标注者。
除朴素一致率外加 Cohen's kappa(扣除随机一致),以及四格混淆。
"""

from __future__ import annotations

import math

from eval.memory_dialogue.meta_eval.judge_agreement import (
    JudgePair,
    compute_agreement,
)


def test_perfect_agreement() -> None:
    pairs = [
        JudgePair(case_id="a", human_pass=True, llm_pass=True),
        JudgePair(case_id="b", human_pass=False, llm_pass=False),
    ]
    r = compute_agreement(pairs)
    assert r.n == 2
    assert r.agreement == 1.0
    assert r.kappa == 1.0
    assert r.both_pass == 1 and r.both_fail == 1


def test_half_agreement_with_confusion() -> None:
    pairs = [
        JudgePair(case_id="a", human_pass=True, llm_pass=True),  # both pass
        JudgePair(case_id="b", human_pass=True, llm_pass=False),  # 漏判(裁判更严)
        JudgePair(case_id="c", human_pass=False, llm_pass=True),  # 误判(裁判更松)
        JudgePair(case_id="d", human_pass=False, llm_pass=False),  # both fail
    ]
    r = compute_agreement(pairs)
    assert r.agreement == 0.5
    assert r.both_pass == 1 and r.both_fail == 1
    assert r.human_pass_llm_fail == 1  # 裁判漏判
    assert r.human_fail_llm_pass == 1  # 裁判误判(放水)
    # 边际各 50/50 → 期望一致 0.5 → kappa = (0.5-0.5)/(1-0.5) = 0
    assert abs(r.kappa) < 1e-9


def test_kappa_beats_chance() -> None:
    # 9 一致 1 不一致,但人类边际偏斜(8 pass / 2 fail)
    pairs = (
        [JudgePair(case_id=f"p{i}", human_pass=True, llm_pass=True) for i in range(7)]
        + [JudgePair(case_id="p7", human_pass=True, llm_pass=False)]
        + [JudgePair(case_id=f"f{i}", human_pass=False, llm_pass=False) for i in range(2)]
    )
    r = compute_agreement(pairs)
    assert r.n == 10
    assert r.agreement == 0.9
    assert 0.0 < r.kappa < 1.0  # 超随机但不完美


def test_format_declares_protocol() -> None:
    from eval.memory_dialogue.meta_eval.judge_agreement import format_report

    r = compute_agreement([JudgePair(case_id="a", human_pass=True, llm_pass=True)])
    out = format_report(r)
    # 必须声明口径(元评估纪律:脱离口径的一致率数字没意义)
    assert "单答判定" in out
    assert "无平局" in out
    assert "一致率" in out and "kappa" in out.lower()


def test_empty_pairs_safe() -> None:
    r = compute_agreement([])
    assert r.n == 0 and r.agreement == 0.0 and math.isnan(r.kappa) is False
