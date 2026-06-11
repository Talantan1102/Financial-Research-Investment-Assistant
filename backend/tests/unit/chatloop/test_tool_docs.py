from app.chatloop.code_interpreter_tool import CodeInterpreterArgs
from app.chatloop.tool_docs import CORE_TOOLS, TOOL_DOCS


def test_run_python_in_core_group() -> None:
    # core 组:run_python 的输出契约(print 一个含 result/figures 的 JSON)随完整
    # schema 常驻可见;放 deferred 时 thin 条目剥了参数 description,模型裸调写不出
    # 符合契约的代码(verify 浏览器实测:stdout_invalid_json + 幻觉图片链接)。
    assert "run_python" in CORE_TOOLS
    doc = TOOL_DOCS["run_python"]
    assert doc.group == "core"
    assert doc.thin_required is None  # core 不走 thin 条目
    assert len(doc.brief) <= 80  # brief 保持可扫,契约改由 code 参数 description 承载


def test_run_python_code_param_carries_output_contract() -> None:
    # 契约在 code 参数 description 里(常驻完整 schema 可见),提到 figures + JSON。
    schema = CodeInterpreterArgs.model_json_schema()
    code_desc = schema["properties"]["code"].get("description", "")
    assert "figures" in code_desc
    assert "JSON" in code_desc or "json" in code_desc
