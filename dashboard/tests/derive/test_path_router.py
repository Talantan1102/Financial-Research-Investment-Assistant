from pathlib import Path

import pytest

from dashboard.derive.path_router import classify_path, load_dimensions
from dashboard.derive.types import DimensionConfig


@pytest.fixture
def dims() -> tuple[list[DimensionConfig], list[DimensionConfig]]:
    yaml_path = Path(__file__).parent.parent.parent / "config" / "dimensions.yaml"
    return load_dimensions(yaml_path)


def test_loads_8_main_dims_and_6_app_shell(
    dims: tuple[list[DimensionConfig], list[DimensionConfig]],
) -> None:
    main, app_shell = dims
    assert len(main) == 8
    assert len(app_shell) == 6
    assert {d.id for d in main} == {
        "prompt_context",
        "tools_function",
        "orchestration",
        "memory",
        "rag_knowledge",
        "guardrails",
        "eval_observability",
        "cost_routing",
    }
    assert all(d.number.startswith("0") for d in main)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("backend/app/services/llm_service.py", "prompt_context"),
        ("backend/app/services/skills/registry.py", "prompt_context"),
        ("backend/app/agents/critic.py", "orchestration"),
        ("backend/app/tools/get_balance_sheet.py", "tools_function"),
        ("backend/app/services/embedding_service.py", "rag_knowledge"),
        ("backend/app/services/eval_runner.py", "eval_observability"),
        ("backend/app/services/judge.py", "eval_observability"),
        ("backend/app/services/tier_router.py", "cost_routing"),
        ("frontend/src/App.tsx", "app_shell"),
        ("README.md", "unknown"),
        # connectors 比 RAG 更具体(milvus_client 比 milvus_*)— spec § 6.3 "更具体的优先"
        ("backend/app/services/milvus_client.py", "app_shell"),
    ],
)
def test_classify_path(
    dims: tuple[list[DimensionConfig], list[DimensionConfig]],
    path: str,
    expected: str,
) -> None:
    main, app_shell = dims
    assert classify_path(path, main, app_shell) == expected
