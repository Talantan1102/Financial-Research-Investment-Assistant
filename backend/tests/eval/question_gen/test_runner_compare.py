"""_compare_table 纯聚合单测:不打真模型。"""

from eval.question_gen.runner import _compare_table


def test_compare_table_shape_and_values():
    per_model = {
        "qwen-max": {
            "pass_at_k": {"pass": 9, "total": 10, "rate": 0.9},
            "by_bucket": {"简单/涨幅": {"pass": 4, "total": 5, "rate": 0.8}},
        },
        "qwen3-8b": {
            "pass_at_k": {"pass": 4, "total": 10, "rate": 0.4},
            "by_bucket": {"简单/涨幅": {"pass": 2, "total": 5, "rate": 0.4}},
        },
    }
    t = _compare_table(per_model)
    assert t["models"] == ["qwen-max", "qwen3-8b"]
    assert t["buckets"] == ["简单/涨幅"]
    assert t["rows"]["qwen-max"]["总分"] == 0.9
    assert t["rows"]["qwen3-8b"]["简单/涨幅"] == 0.4


def test_compare_table_missing_bucket_is_none():
    per_model = {
        "a": {"pass_at_k": {"rate": 0.5}, "by_bucket": {"x": {"rate": 0.5}}},
        "b": {"pass_at_k": {"rate": 0.7}, "by_bucket": {"y": {"rate": 0.7}}},
    }
    t = _compare_table(per_model)
    assert t["rows"]["a"]["y"] is None  # a 没有桶 y
