"""LLM prefill prompt + constrained Pydantic schema。Plan 1 Task 6。"""

from __future__ import annotations

from pydantic import BaseModel

from dashboard.derive.llm_prefill_prompt import (
    PrefillRequest,
    PrefillResponse,
    SingleFieldPrefillResponse,
    build_full_prefill_prompt,
    build_single_field_prefill_prompt,
)


def test_prefill_response_schema_has_provenance() -> None:
    """Pydantic schema 必须含 each-field provenance(spec § 7.3)。"""
    schema = PrefillResponse.model_json_schema()
    props = schema["properties"]
    for f in ("what", "why", "alternatives", "tradeoff", "lessons_learned"):
        assert f in props
        assert f"{f}_provenance" in props


def test_full_prompt_includes_cap_name_and_sources() -> None:
    req = PrefillRequest(
        cap_id="01.constrained_schema",
        cap_name_cn="输出 Schema 约束",
        linked_spec_paths=["docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md"],
        linked_memory_paths=["memory/feedback_design_doc_format.md"],
        decisions_summary=[("abc12", "Constrained Router 4 选 1")],
    )
    prompt = build_full_prefill_prompt(req)
    assert "01.constrained_schema" in prompt
    assert "输出 Schema 约束" in prompt
    assert "2026-05-05-v0.8.5" in prompt
    assert "feedback_design_doc_format" in prompt
    assert "Constrained Router 4 选 1" in prompt
    assert "provenance" in prompt.lower()
    assert "quote" in prompt.lower()


def test_single_field_prompt_specifies_field() -> None:
    req = PrefillRequest(
        cap_id="x",
        cap_name_cn="x",
        linked_spec_paths=["a.md"],
        linked_memory_paths=[],
        decisions_summary=[],
    )
    prompt = build_single_field_prefill_prompt(req, field_name="why")
    assert "why" in prompt
    # Either Chinese 仅生成 or English single field 都应出现
    assert (
        "仅生成" in prompt or "single field" in prompt.lower() or "only generate" in prompt.lower()
    )


def test_single_field_response_schema_is_pydantic() -> None:
    assert issubclass(SingleFieldPrefillResponse, BaseModel)
    schema = SingleFieldPrefillResponse.model_json_schema()
    assert "value" in schema["properties"]
    assert "provenance" in schema["properties"]
