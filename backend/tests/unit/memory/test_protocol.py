"""L0: Memory Protocol runtime_checkable + 完整签名."""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
from app.memory.protocol import Memory


def test_memory_protocol_is_runtime_checkable() -> None:
    """Protocol 用 @runtime_checkable 装饰, isinstance check 可用."""
    assert hasattr(Memory, "_is_runtime_protocol")
    assert getattr(Memory, "_is_runtime_protocol", False) is True


def test_memory_protocol_method_signatures() -> None:
    """契约 § 2: 9 个 method 签名齐全."""
    expected = {
        "get_working_blocks",
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
        "archival_memory_search",
        "archival_memory_traverse",
        "recall_memory_search",
        "write_episode",
        "get_unextracted_episodes",
        "mark_episode_extracted",
    }
    actual = {
        name
        for name, m in inspect.getmembers(Memory, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert expected.issubset(actual), f"missing methods: {expected - actual}"


def test_archival_memory_insert_has_evidence_quote() -> None:
    """算法深度补丁 #2: evidence_quote 必填参数."""
    sig = inspect.signature(Memory.archival_memory_insert)
    assert "evidence_quote" in sig.parameters
    # 必填(no default)
    assert sig.parameters["evidence_quote"].default is inspect.Parameter.empty


def test_all_methods_first_param_is_user_id() -> None:
    """契约: 所有方法第一参数 user_id: UUID(多租户隔离)."""
    method_names = [
        "get_working_blocks",
        "core_memory_append",
        "core_memory_replace",
        "archival_memory_insert",
        "archival_memory_search",
        "archival_memory_traverse",
        "recall_memory_search",
        "write_episode",
        "get_unextracted_episodes",
    ]
    for name in method_names:
        sig = inspect.signature(getattr(Memory, name))
        params = list(sig.parameters.values())
        # params[0] 是 self(Protocol method)
        assert len(params) >= 2, f"{name} 至少要 self + user_id"
        assert params[1].name == "user_id", f"{name} 第二参数应是 user_id, 实际 {params[1].name}"


def test_in_session_memory_satisfies_extended_protocol() -> None:
    """PR #39 ship 的 InSessionMemory 通过 stub 满足扩展 Protocol(isinstance check)."""
    from app.agents.in_session_memory import InSessionMemory

    instance = InSessionMemory(llm=None)
    assert isinstance(instance, Memory)


async def test_in_session_memory_stubs_raise_not_implemented() -> None:
    """InSessionMemory 的新 method stub 必须 raise NotImplementedError."""
    from app.agents.in_session_memory import InSessionMemory

    mem = InSessionMemory(llm=None)
    uid = uuid4()
    with pytest.raises(NotImplementedError):
        await mem.get_working_blocks(uid)
    with pytest.raises(NotImplementedError):
        await mem.core_memory_append(uid, "persona", "x")
    with pytest.raises(NotImplementedError):
        await mem.archival_memory_insert(uid, {}, "r", 0.5, "ev", uuid4())
    with pytest.raises(NotImplementedError):
        await mem.archival_memory_search(uid, "q")
    with pytest.raises(NotImplementedError):
        await mem.write_episode(uid, uuid4(), 0, "u", "a")
    with pytest.raises(NotImplementedError):
        await mem.mark_episode_extracted(uuid4(), "agent", {})
