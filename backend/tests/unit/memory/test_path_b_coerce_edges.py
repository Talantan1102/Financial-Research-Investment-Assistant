"""C3 regression: PathBRunner._coerce_edges must emit dicts in the exact shape
hierarchical.archival_memory_insert reads as `content`.

The old impl called edge.model_dump() and discarded item.entities, so the dict
lacked source_entity_type/target_entity_type (→ KeyError) and kept valid_from as
a str (→ AttributeError on .isoformat()). Every real Path B edge silently failed
to persist. These unit tests pin the coerce→insert contract directly (no AGE/Milvus
stack needed), which is exactly what the mocked integration tests could not catch.
"""

from __future__ import annotations

from datetime import datetime

from app.memory.extractor import ExtractedEdge, ExtractedEntity, ExtractionOutput
from app.memory.path_b_runner import _coerce_edges


def _output() -> ExtractionOutput:
    return ExtractionOutput(
        entities=[
            ExtractedEntity(entity_type="User", entity_label="user-1", properties={}),
            ExtractedEntity(entity_type="Stock", entity_label="600519.SH", properties={}),
        ],
        edges=[
            ExtractedEdge(
                rel_type="HOLDS",
                source_label="user-1",
                target_label="600519.SH",
                valid_from="2026-05-01T00:00:00+00:00",
                importance=0.9,
                reasoning="user holds the stock",
            )
        ],
    )


def test_coerce_injects_entity_types_and_datetime() -> None:
    """The coerced dict carries every key archival_memory_insert hard-reads."""
    out = _coerce_edges([_output()])
    assert len(out) == 1
    ed = out[0]
    # *_entity_type injected from co-extracted entities (was missing → KeyError)
    assert ed["source_entity_type"] == "User"
    assert ed["target_entity_type"] == "Stock"
    assert ed["source_label"] == "user-1"
    assert ed["target_label"] == "600519.SH"
    assert ed["rel_type"] == "HOLDS"
    # valid_from coerced str → tz-aware datetime (was str → AttributeError on .isoformat())
    assert isinstance(ed["valid_from"], datetime)
    assert ed["valid_from"].tzinfo is not None
    # the exact set of keys archival_memory_insert reads is present
    for key in (
        "rel_type",
        "source_entity_type",
        "source_label",
        "target_entity_type",
        "target_label",
        "valid_from",
    ):
        assert key in ed


def test_coerce_legacy_dict_shape_also_enriched() -> None:
    """The legacy {'entities':..,'edges':..} dict shape gets the same enrichment."""
    out = _coerce_edges(
        {
            "entities": [{"entity_type": "User", "entity_label": "u"}],
            "edges": [
                {
                    "rel_type": "WATCHES",
                    "source_label": "u",
                    "target_label": "u",
                    "valid_from": "2026-05-01T00:00:00+00:00",
                    "importance": 0.5,
                    "reasoning": "r",
                }
            ],
        }
    )
    assert len(out) == 1
    assert out[0]["source_entity_type"] == "User"
    assert isinstance(out[0]["valid_from"], datetime)


def test_coerce_skips_edge_with_unresolvable_entity_type() -> None:
    """An edge whose label is absent from entities is skipped, not half-written."""
    out = _coerce_edges(
        {
            "entities": [{"entity_type": "User", "entity_label": "u"}],
            "edges": [
                {
                    "rel_type": "WATCHES",
                    "source_label": "u",
                    "target_label": "UNKNOWN-LABEL",  # not in entities → unresolvable
                    "valid_from": "2026-05-01T00:00:00+00:00",
                    "importance": 0.5,
                    "reasoning": "r",
                }
            ],
        }
    )
    assert out == []


def test_coerce_implicit_user_source_resolves_without_user_entity() -> None:
    """The well-known 'User' root is NOT re-listed in entities (extractor prompt:
    'User: 固定 User'), so an edge like User HOLDS Stock must still resolve its
    source_entity_type to 'User' by default — not be skipped."""
    out = _coerce_edges(
        {
            "entities": [{"entity_type": "Stock", "entity_label": "600519.SH"}],
            "edges": [
                {
                    "rel_type": "HOLDS",
                    "source_label": "User",
                    "target_label": "600519.SH",
                    "valid_from": "2026-05-01T00:00:00+00:00",
                    "importance": 0.9,
                    "reasoning": "user holds",
                }
            ],
        }
    )
    assert len(out) == 1
    assert out[0]["source_entity_type"] == "User"
    assert out[0]["target_entity_type"] == "Stock"
