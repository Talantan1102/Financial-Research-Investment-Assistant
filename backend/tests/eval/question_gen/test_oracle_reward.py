"""oracle_reward.compute_score 单测:verl 认的确定性奖励,复用 judge.judge。

签名锚:docs/research/2026-06-09-verl-multistep-tool-rl-recipe.md §3.4/§3.5。
"""

import json

from eval.question_gen import oracle_reward


def _gt(gold, shape="scalar", tol=None, names=None):
    """模拟 to_verl 写进 parquet 的 ground_truth(JSON 字符串)。"""
    return json.dumps(
        {
            "gold": gold,
            "gold_shape": shape,
            "tolerance": tol or {"kind": "rel_mult", "value": 0.005},
            "candidate_names": names or [],
        },
        ensure_ascii=False,
    )


def test_scalar_correct_scores_one():
    out = oracle_reward.compute_score(
        data_source="fin_indicator_oracle",
        solution_str="经计算,紫光股份近三个月涨幅约为 -5.17%。",
        ground_truth=_gt(-5.165912),
    )
    assert out["score"] == 1.0 and out["format_ok"] == 1.0


def test_scalar_wrong_scores_zero():
    out = oracle_reward.compute_score(
        data_source="fin_indicator_oracle",
        solution_str="涨幅大约是 +20%。",
        ground_truth=_gt(-5.165912),
    )
    assert out["score"] == 0.0


def test_accepts_dict_ground_truth_too():
    # ground_truth 也可能已是 dict(非 JSON 串),要兼容
    gt = {
        "gold": 1.0,
        "gold_shape": "scalar",
        "tolerance": {"kind": "abs", "value": 0.01},
        "candidate_names": [],
    }
    out = oracle_reward.compute_score("fin", "答案是 1.0", gt)
    assert out["score"] == 1.0


def test_tail_clip_ignores_midtrajectory_number():
    # 中间步出现 gold 数字,但最终答案错 → tail-clip 后应判错(防中间数字误命中)
    mid = "第一步取到收盘价 -5.17 ... " + "x" * 800 + " 最终答案:+30%。"
    out = oracle_reward.compute_score("fin", mid, _gt(-5.165912))
    assert out["score"] == 0.0


def test_no_parseable_answer_zero_format():
    out = oracle_reward.compute_score("fin", "我不知道。", _gt(-5.165912))
    assert out["score"] == 0.0


def test_no_intent_no_extra_key():
    out = oracle_reward.compute_score("fin", "答案 -5.17%", _gt(-5.165912))
    assert not any(k.startswith("acc/") for k in out)
