"""L0: HierarchicalMemory class 骨架 — DI signature + Plan 2-4 stub raise."""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
from app.memory.hierarchical import HierarchicalMemory
from app.memory.protocol import Memory


def test_hierarchical_memory_implements_protocol() -> None:
    """HierarchicalMemory satisfies Memory Protocol (runtime_checkable)."""
    instance = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    assert isinstance(instance, Memory)


def test_init_signature_has_required_di_params() -> None:
    """契约 § 3: __init__ 必须接受 7 个 DI 参数(injection_classifier 默认 None)."""
    sig = inspect.signature(HierarchicalMemory.__init__)
    expected_params = {
        "pg_session_factory",
        "age_executor",
        "milvus_client",
        "embed_service",
        "llm_extractor",
        "llm_judge",
        "injection_classifier",
    }
    actual = set(sig.parameters.keys()) - {"self"}
    assert expected_params.issubset(actual), f"missing DI params: {expected_params - actual}"


def test_injection_classifier_defaults_none() -> None:
    sig = inspect.signature(HierarchicalMemory.__init__)
    assert sig.parameters["injection_classifier"].default is None


# ---- Plan 2-4 stub method 必须 raise NotImplementedError ----


async def test_archival_memory_insert_implemented_post_plan_2a() -> None:
    """Plan 2A ship 后, archival_memory_insert 不再是 stub.

    Plan 2A 替换 stub 为 8-step pipeline (extractor + conflict_resolver +
    age_sync + milvus_outbox). 不能再 raise NotImplementedError; 调 empty content
    会因 KeyError / 缺 DI 抛 — 本 test 只验"非 NotImplementedError".
    """
    mem = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    # Empty content → KeyError 'rel_type' (or 类似), 不是 NotImplementedError
    with pytest.raises(Exception) as excinfo:
        await mem.archival_memory_insert(
            user_id=uuid4(),
            content={},
            reasoning="r",
            importance=0.5,
            evidence_quote="ev",
            episode_id=uuid4(),
        )
    assert not isinstance(excinfo.value, NotImplementedError)


async def test_archival_memory_search_stub() -> None:
    mem = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    with pytest.raises(NotImplementedError, match="Plan 3"):
        await mem.archival_memory_search(uuid4(), "q")


async def test_archival_memory_traverse_stub() -> None:
    mem = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    with pytest.raises(NotImplementedError, match="Plan 4"):
        await mem.archival_memory_traverse(uuid4(), "User")


async def test_recall_memory_search_stub() -> None:
    mem = HierarchicalMemory(
        pg_session_factory=None,
        age_executor=None,
        milvus_client=None,
        embed_service=None,
        llm_extractor=None,
        llm_judge=None,
    )
    with pytest.raises(NotImplementedError, match="Plan 4"):
        await mem.recall_memory_search(uuid4(), "q")
