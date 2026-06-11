from app.chatloop.tool_docs import DEFERRED_TOOLS, TOOL_DOCS, thin_schema


def test_run_python_in_deferred_group() -> None:
    assert "run_python" in DEFERRED_TOOLS
    doc = TOOL_DOCS["run_python"]
    assert doc.group == "deferred"
    assert doc.thin_required == {"code": "string"}


def test_run_python_thin_schema_keeps_required_code() -> None:
    schema = thin_schema(TOOL_DOCS["run_python"])
    params = schema["function"]["parameters"]
    assert "code" in params["properties"]
    assert params["required"] == ["code"]
