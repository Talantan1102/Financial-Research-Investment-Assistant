"""L0 schema test for chat_memory_* models. PG-specific behaviors covered in L1."""


def test_models_importable() -> None:
    """Smoke: 4 model classes import without error."""
    from app.memory.models import (
        ChatMemoryEdge,
        ChatMemoryEpisode,
        ChatMemoryNode,
        ChatMemoryWorkingBlock,
    )

    assert ChatMemoryEpisode.__tablename__ == "chat_memory_episodes"
    assert ChatMemoryNode.__tablename__ == "chat_memory_nodes"
    assert ChatMemoryEdge.__tablename__ == "chat_memory_edges"
    assert ChatMemoryWorkingBlock.__tablename__ == "chat_memory_working_blocks"
