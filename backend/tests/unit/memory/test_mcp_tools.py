"""L0 — 6 MCP tool input schema / TOOL_DEF / Pydantic 校验测试.

不依赖 PG / AGE / Milvus, 全 mock.
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize(
    "module_path,expected_name",
    [
        ("app.mcp_server.tools.memory.core_memory_append", "core_memory_append"),
        ("app.mcp_server.tools.memory.core_memory_replace", "core_memory_replace"),
        ("app.mcp_server.tools.memory.archival_memory_insert", "archival_memory_insert"),
        ("app.mcp_server.tools.memory.archival_memory_search", "archival_memory_search"),
        ("app.mcp_server.tools.memory.archival_memory_traverse", "archival_memory_traverse"),
        ("app.mcp_server.tools.memory.recall_memory_search", "recall_memory_search"),
    ],
)
def test_tool_def_exposes_correct_name_and_schema(module_path: str, expected_name: str) -> None:
    mod = importlib.import_module(module_path)
    assert mod.TOOL_DEF.name == expected_name
    assert mod.TOOL_DEF.inputSchema["type"] == "object"
    assert "properties" in mod.TOOL_DEF.inputSchema
    assert "required" in mod.TOOL_DEF.inputSchema


def test_memory_tool_modules_registry() -> None:
    """__init__.MEMORY_TOOL_MODULES exposes all 6 tools."""
    from app.mcp_server.tools.memory import MEMORY_TOOL_MODULES

    assert len(MEMORY_TOOL_MODULES) == 6
    assert all(p.startswith("app.mcp_server.tools.memory.") for p in MEMORY_TOOL_MODULES)


# === core_memory_append ===


def test_core_memory_append_args_max_200_chars() -> None:
    from app.mcp_server.tools.memory.core_memory_append import CoreMemoryAppendArgs

    # 200 chars 通过
    CoreMemoryAppendArgs(
        user_id="00000000-0000-0000-0000-000000000001",
        block_name="persona",
        content="a" * 200,
    )
    # 201 chars 拒绝
    with pytest.raises(ValidationError):
        CoreMemoryAppendArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            block_name="persona",
            content="a" * 201,
        )


def test_core_memory_append_args_block_name_whitelist() -> None:
    from app.mcp_server.tools.memory.core_memory_append import CoreMemoryAppendArgs

    CoreMemoryAppendArgs(
        user_id="00000000-0000-0000-0000-000000000001",
        block_name="persona",
        content="ok",
    )
    CoreMemoryAppendArgs(
        user_id="00000000-0000-0000-0000-000000000001",
        block_name="scratchpad",
        content="ok",
    )
    with pytest.raises(ValidationError):
        CoreMemoryAppendArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            block_name="random",
            content="ok",
        )


def test_core_memory_append_args_empty_content_rejected() -> None:
    from app.mcp_server.tools.memory.core_memory_append import CoreMemoryAppendArgs

    with pytest.raises(ValidationError):
        CoreMemoryAppendArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            block_name="persona",
            content="   ",
        )


# === core_memory_replace ===


def test_core_memory_replace_args_old_new_required() -> None:
    from app.mcp_server.tools.memory.core_memory_replace import CoreMemoryReplaceArgs

    CoreMemoryReplaceArgs(
        user_id="00000000-0000-0000-0000-000000000001",
        block_name="persona",
        old_content="old",
        new_content="new",
    )
    # missing new_content
    with pytest.raises(ValidationError):
        CoreMemoryReplaceArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            block_name="persona",
            old_content="old",
        )  # type: ignore[call-arg]


def test_core_memory_replace_args_old_content_must_not_be_empty() -> None:
    from app.mcp_server.tools.memory.core_memory_replace import CoreMemoryReplaceArgs

    with pytest.raises(ValidationError):
        CoreMemoryReplaceArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            block_name="persona",
            old_content="",
            new_content="new",
        )


# === archival_memory_insert ===


def test_archival_memory_insert_args_importance_three_tier() -> None:
    from app.mcp_server.tools.memory.archival_memory_insert import (
        ArchivalMemoryInsertArgs,
    )

    for imp in [0.9, 0.5, 0.2]:
        ArchivalMemoryInsertArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            content={
                "rel_type": "HOLDS",
                "source_label": "User",
                "target_label": "贵州茅台",
            },
            reasoning="user said 'I bought 500 share'",
            importance=imp,
            evidence_quote="我买了500股茅台",
            episode_id="00000000-0000-0000-0000-000000000099",
        )

    # 0.7 拒绝（三档约束 spec § 11 末尾 #3）
    with pytest.raises(ValidationError):
        ArchivalMemoryInsertArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            content={
                "rel_type": "HOLDS",
                "source_label": "User",
                "target_label": "X",
            },
            reasoning="r",
            importance=0.7,
            evidence_quote="quote",
            episode_id="00000000-0000-0000-0000-000000000099",
        )


def test_archival_memory_insert_args_evidence_quote_required() -> None:
    from app.mcp_server.tools.memory.archival_memory_insert import (
        ArchivalMemoryInsertArgs,
    )

    with pytest.raises(ValidationError):
        ArchivalMemoryInsertArgs(  # type: ignore[call-arg]
            user_id="00000000-0000-0000-0000-000000000001",
            content={
                "rel_type": "HOLDS",
                "source_label": "User",
                "target_label": "X",
            },
            reasoning="r",
            importance=0.5,
            episode_id="00000000-0000-0000-0000-000000000099",
        )


def test_archival_memory_insert_args_content_required_keys() -> None:
    from app.mcp_server.tools.memory.archival_memory_insert import (
        ArchivalMemoryInsertArgs,
    )

    # missing target_label
    with pytest.raises(ValidationError):
        ArchivalMemoryInsertArgs(
            user_id="00000000-0000-0000-0000-000000000001",
            content={"rel_type": "HOLDS", "source_label": "User"},
            reasoning="r",
            importance=0.5,
            evidence_quote="q",
            episode_id="00000000-0000-0000-0000-000000000099",
        )


# === archival_memory_search ===


def test_archival_memory_search_args_k_default_5_max_20() -> None:
    from app.mcp_server.tools.memory.archival_memory_search import (
        ArchivalMemorySearchArgs,
    )

    args = ArchivalMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="茅台")
    assert args.k == 5
    ArchivalMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="X", k=20)
    with pytest.raises(ValidationError):
        ArchivalMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="X", k=21)


def test_archival_memory_search_args_query_non_empty() -> None:
    from app.mcp_server.tools.memory.archival_memory_search import (
        ArchivalMemorySearchArgs,
    )

    with pytest.raises(ValidationError):
        ArchivalMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="")


# === archival_memory_traverse ===


def test_archival_memory_traverse_args_hops_default_2_max_3() -> None:
    from app.mcp_server.tools.memory.archival_memory_traverse import (
        ArchivalMemoryTraverseArgs,
    )

    args = ArchivalMemoryTraverseArgs(
        user_id="00000000-0000-0000-0000-000000000001", start_label="贵州茅台"
    )
    assert args.hops == 2
    ArchivalMemoryTraverseArgs(
        user_id="00000000-0000-0000-0000-000000000001", start_label="X", hops=3
    )
    with pytest.raises(ValidationError):
        ArchivalMemoryTraverseArgs(
            user_id="00000000-0000-0000-0000-000000000001", start_label="X", hops=4
        )


def test_archival_memory_traverse_args_rel_types_optional() -> None:
    from app.mcp_server.tools.memory.archival_memory_traverse import (
        ArchivalMemoryTraverseArgs,
    )

    args = ArchivalMemoryTraverseArgs(
        user_id="00000000-0000-0000-0000-000000000001",
        start_label="X",
        rel_types=["BELONGS_TO", "HOLDS"],
    )
    assert args.rel_types == ["BELONGS_TO", "HOLDS"]


# === recall_memory_search ===


def test_recall_memory_search_args_k_default_5_max_20() -> None:
    from app.mcp_server.tools.memory.recall_memory_search import (
        RecallMemorySearchArgs,
    )

    args = RecallMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="我之前说")
    assert args.k == 5
    with pytest.raises(ValidationError):
        RecallMemorySearchArgs(user_id="00000000-0000-0000-0000-000000000001", query="X", k=21)
