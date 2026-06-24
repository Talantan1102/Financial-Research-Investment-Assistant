from eval.question_gen import case as case_mod
from eval.question_gen import tag_cases


def _case(cid, intent="snapshot_quote", shape="scalar"):
    return case_mod.ComputationCase(
        case_id=cid,
        intent=intent,
        difficulty="简单",
        question="?",
        stocks=["600519.SH"],
        indicator="PE",
        window="snapshot",
        gold=1.0,
        gold_shape=shape,
        tolerance={"kind": "rel", "value": 0.01},
        meta={},
    )


def test_build_manifest_rows():
    cases = [_case("a"), _case("b", intent="stock_study", shape="ranking")]
    counts = {"a": 4, "b": 0}  # a 黄金带, b too_hard
    clean = {"a": 2, "b": 0}
    rows = {r["case_id"]: r for r in tag_cases.build_manifest_rows(counts, 8, clean, cases)}
    assert rows["a"]["tags"]["label"] == "rl_band" and rows["a"]["tags"]["prime"] is True
    assert rows["a"]["reward_eligible"] is True and rows["a"]["sft_clean_count"] == 2
    assert rows["a"]["intent"] == "snapshot_quote"
    assert rows["b"]["tags"]["label"] == "too_hard"
    assert rows["b"]["reward_eligible"] is False  # ranking 不进奖励


def test_build_manifest_rows_missing_counts_default_zero():
    rows = tag_cases.build_manifest_rows({}, 8, {}, [_case("z")])
    assert rows[0]["pass_count"] == 0 and rows[0]["tags"]["label"] == "too_hard"


def test_dump_manifest_roundtrip(tmp_path):
    import json

    rows = tag_cases.build_manifest_rows({"a": 4}, 8, {"a": 1}, [_case("a")])
    p = tmp_path / "m.jsonl"
    tag_cases.dump_manifest(rows, p)
    loaded = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert loaded[0]["case_id"] == "a" and loaded[0]["reward_eligible"] is True
