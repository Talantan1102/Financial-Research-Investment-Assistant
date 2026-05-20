from pathlib import Path

import pytest

from dashboard.derive.path_router import classify_path, load_dimensions
from dashboard.derive.types import DimensionConfig


@pytest.fixture
def dims() -> tuple[list[DimensionConfig], list[DimensionConfig]]:
    yaml_path = Path(__file__).parent.parent.parent / "config" / "dimensions.yaml"
    return load_dimensions(yaml_path)


def test_loads_7_main_dims_and_5_catch_all(
    dims: tuple[list[DimensionConfig], list[DimensionConfig]],
) -> None:
    main, catch_all = dims
    assert len(main) == 7
    assert len(catch_all) == 5
    assert {d.id for d in main} == {
        "execution",
        "tool",
        "context",
        "lifecycle",
        "observability",
        "verification",
        "governance",
    }
    assert all(d.number.startswith("0") for d in main)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("backend/app/services/llm_service.py", "context"),
        ("backend/app/services/skills/registry.py", "context"),
        ("backend/app/agents/critic.py", "lifecycle"),
        ("backend/app/tools/get_balance_sheet.py", "tool"),
        ("backend/app/services/embedding_service.py", "context"),
        ("backend/app/services/eval_runner.py", "verification"),
        ("backend/app/services/judge.py", "verification"),
        ("backend/app/services/tier_router.py", "observability"),
        ("backend/app/services/constrained_router.py", "governance"),
        ("backend/app/tasks/celery_app.py", "execution"),
        ("docker-compose.yml", "execution"),
        ("frontend/src/App.tsx", "shell"),
        ("README.md", "unknown"),
        # tool 比 context 更具体(milvus_client 比 milvus_*)— spec § 6.3 "更具体的优先"
        ("backend/app/services/milvus_client.py", "tool"),
    ],
)
def test_classify_path(
    dims: tuple[list[DimensionConfig], list[DimensionConfig]],
    path: str,
    expected: str,
) -> None:
    main, catch_all = dims
    assert classify_path(path, main, catch_all) == expected
