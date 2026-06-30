"""to_verl.case_to_verl_row 单测:把 ComputationCase 转成 verl ToolAgentLoop parquet 行。

格式锚:docs/research/2026-06-09-verl-multistep-tool-rl-recipe.md §2.7。
"""

from eval.question_gen import case as case_mod
from eval.question_gen import to_verl


def _case(cid="c1", intent="stock_study", gold=1.23, shape="scalar", tol=None, stocks=None):
    return case_mod.ComputationCase(
        case_id=cid,
        intent=intent,
        difficulty="简单",
        question="紫光股份最近三个月涨了多少?",
        stocks=stocks or ["000938.SZ"],
        indicator="涨幅",
        window="近三个月",
        gold=gold,
        gold_shape=shape,
        tolerance=tol or {"kind": "rel_mult", "value": 0.005},
        meta={"as_of": "20260612"},
    )


def test_row_core_structure():
    row = to_verl.case_to_verl_row(_case(), split="train", index=7, candidate_names=["紫光股份"])
    # 路由 ToolAgentLoop 的关键字段
    assert row["agent_name"] == "tool_agent"
    assert row["data_source"] == to_verl.DATA_SOURCE
    # prompt = system + user(原题)
    assert [m["role"] for m in row["prompt"]] == ["system", "user"]
    assert row["prompt"][1]["content"] == "紫光股份最近三个月涨了多少?"
    # extra_info 溯源
    assert row["extra_info"]["case_id"] == "c1"
    assert row["extra_info"]["split"] == "train" and row["extra_info"]["index"] == 7


def test_ground_truth_carries_oracle_inputs():
    # reward_model.ground_truth 必须自带 judge() 需要的全部:gold/gold_shape/tolerance/candidate_names
    c = _case(gold=-5.16, tol={"kind": "rel_mult", "value": 0.005})
    gt = to_verl.case_to_verl_row(c, split="val", index=0, candidate_names=["紫光股份"])[
        "reward_model"
    ]["ground_truth"]
    assert gt["gold"] == -5.16
    assert gt["gold_shape"] == "scalar"
    assert gt["tolerance"] == {"kind": "rel_mult", "value": 0.005}
    assert gt["candidate_names"] == ["紫光股份"]


def test_ranking_ground_truth_keeps_candidate_names():
    c = _case(
        intent="stock_study",
        gold=[["紫光股份", -5.16], ["浪潮信息", -8.59]],
        shape="ranking",
        tol={},
        stocks=["000938.SZ", "000977.SZ"],
    )
    row = to_verl.case_to_verl_row(
        c, split="test", index=3, candidate_names=["紫光股份", "浪潮信息"]
    )
    assert row["reward_model"]["ground_truth"]["candidate_names"] == ["紫光股份", "浪潮信息"]
    assert row["reward_model"]["ground_truth"]["gold_shape"] == "ranking"
