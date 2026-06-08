"""L0: Memory Protocol runtime_checkable + 完整签名."""

from __future__ import annotations

import inspect

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


# 老 supervisor 图退役(Phase 7):InSessionMemory(agents.in_session_memory)随老图删除,
# 对应的两条 isinstance / stub-raises 测试移除。HierarchicalMemory 满足本 Protocol 的
# 守护见 test_router_di_swap.test_hierarchical_memory_satisfies_protocol_at_import。
