import pytest
from eval.question_gen import case as case_mod
from eval.question_gen import derive_sets


def _case(cid, stock="600519.SH"):
    return case_mod.ComputationCase(
        case_id=cid,
        intent="snapshot_quote",
        difficulty="简单",
        question="?",
        stocks=[stock],
        indicator="PE",
        window="snapshot",
        gold=1.0,
        gold_shape="scalar",
        tolerance={"kind": "rel", "value": 0.01},
        meta={},
    )


def test_select_rl_ids():
    manifest = [
        {"case_id": "a", "tags": {"in_rl": True}, "reward_eligible": True},
        {"case_id": "b", "tags": {"in_rl": True}, "reward_eligible": False},  # ranking→排除
        {"case_id": "c", "tags": {"in_rl": False}, "reward_eligible": True},  # 端点→排除
    ]
    assert derive_sets.select_rl_ids(manifest) == {"a"}


def test_select_sft_caps_per_case_and_job():
    manifest = [
        {"case_id": f"x{i}", "sft_clean_count": 5, "intent": "snapshot_quote"} for i in range(10)
    ]
    picked = derive_sets.select_sft(manifest, per_case_cap=2, per_job_cap=6)
    assert sum(p["take"] for p in picked) == 6
    assert all(p["take"] <= 2 for p in picked)


def test_assert_stock_disjoint_raises():
    with pytest.raises(AssertionError):
        derive_sets.assert_stock_disjoint([_case("a", "600519.SH")], [_case("e", "600519.SH")])


def test_write_sets(tmp_path):
    cands = [_case("a", "600519.SH"), _case("b", "000001.SZ")]
    evals = [_case("e", "300750.SZ")]
    manifest = [
        {
            "case_id": "a",
            "intent": "snapshot_quote",
            "tags": {"in_rl": True},
            "reward_eligible": True,
            "sft_clean_count": 2,
        },
        {
            "case_id": "b",
            "intent": "snapshot_quote",
            "tags": {"in_rl": False},
            "reward_eligible": True,
            "sft_clean_count": 0,
        },
    ]
    counts = derive_sets.write_sets(cands, manifest, evals, tmp_path)
    assert counts == {"rl": 1, "eval": 1, "sft": 2}
    assert (tmp_path / "rl_train.jsonl").exists()
    assert (tmp_path / "eval.jsonl").exists()
    assert (tmp_path / "sft_selection.jsonl").exists()
