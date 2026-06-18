from app.services import model_registry as mr


def test_allowed_and_dashscope_id():
    assert mr.is_allowed("qwen3-8b")
    assert not mr.is_allowed("gpt-4")
    assert mr.dashscope_id("qwen2.5-7b") == "qwen2.5-7b-instruct"
    assert mr.dashscope_id("deepseek-v4-flash") == "deepseek-v4-flash"


def test_size_and_availability():
    assert mr.spec("qwen3-8b").size == "small"
    assert mr.spec("qwen-max").size == "large"
    assert mr.spec("qwen3-8b").available is True
    assert mr.spec("qwen2.5-7b").available is False  # 403 未开通


def test_available_keys_excludes_unavailable():
    keys = mr.available_keys()
    assert "qwen3-8b" in keys
    assert "qwen2.5-7b" not in keys
    assert "deepseek-v4-flash" in keys


def test_spec_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        mr.spec("nope")
