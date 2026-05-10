"""C.5 Cross-session memory subsystem.

Plan 1A ships: PG schema + AGE setup + Milvus collection + 幂等键 UNIQUE.
Plan 1B will fill: Memory Protocol / HierarchicalMemory / working_blocks / cold_start.
Plan 2-8 fill: extraction / retrieval / MCP tools / cost / routing / UI / eval.

See docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md

NOTE: Per shared contract § 17 A1, Plan 1A creates this file empty.
Plan 1B will Edit to add the public exports.
"""
