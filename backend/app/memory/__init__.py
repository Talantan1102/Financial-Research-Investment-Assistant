"""C.5 Cross-session memory subsystem.

Plan 1A ships: PG schema + AGE setup + Milvus collection + 幂等键 UNIQUE.
Plan 1B fills: Memory Protocol / HierarchicalMemory / working_blocks / cold_start.
Plan 2A fills: extractor + conflict_resolver + age_sync + milvus_outbox + archival_memory_insert.
Plan 2B-8 fill: cross-turn extraction / retrieval / MCP tools / cost / routing / UI / eval.

See docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md
"""

from app.memory.age_sync import age_create_edge, age_merge_node
from app.memory.conflict_resolver import (
    ConflictAction,
    ConflictResolver,
    ConflictVerdict,
    apply_action,
)
from app.memory.extractor import (
    ExtractedEdge,
    ExtractedEntity,
    ExtractionOutput,
    LLMExtractor,
)
from app.memory.hierarchical import HierarchicalMemory
from app.memory.milvus_outbox import (
    build_edge_embed_text,
    enqueue_milvus_insert,
    try_milvus_insert,
)
from app.memory.protocol import Memory

__all__ = [
    "ConflictAction",
    "ConflictResolver",
    "ConflictVerdict",
    "ExtractedEdge",
    "ExtractedEntity",
    "ExtractionOutput",
    "HierarchicalMemory",
    "LLMExtractor",
    "Memory",
    "age_create_edge",
    "age_merge_node",
    "apply_action",
    "build_edge_embed_text",
    "enqueue_milvus_insert",
    "try_milvus_insert",
]
