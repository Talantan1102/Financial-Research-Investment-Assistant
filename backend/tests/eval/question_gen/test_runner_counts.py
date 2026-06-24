from eval.question_gen import runner


def test_aggregate_exposes_counts():
    per_run = {"a": [True, False, True], "b": [False, False, False]}
    out = runner._aggregate([], per_run)  # 空 cases 也应给 counts,不 KeyError
    assert out["per_case_counts"] == {"a": 2, "b": 0}


def test_aggregate_keeps_existing_keys():
    per_run = {"a": [True, False]}
    out = runner._aggregate([], per_run)
    assert "pass_at_k" in out and "by_bucket" in out and "per_case" in out
    assert out["per_case"]["a"] is True  # pass@k = any(runs)
