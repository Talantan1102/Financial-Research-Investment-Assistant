"""Span + TraceTree — the in-memory shape of one trace.

`Span` is the wire format and the SQLite row format (1:1). `TraceTree` is a
view-model built from a set of spans sharing a request_id. Both are stable
across v0~v3 per spec § 9 — adding fields is fine, renaming/removing breaks
all downstream consumers (eval reader, future trace exporter).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class Span(BaseModel):
    model_config = ConfigDict(frozen=True)

    span_id: str
    request_id: str
    parent_id: str | None
    name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    metadata: dict[str, Any]
    started_at: datetime
    ended_at: datetime
    error: str | None

    @model_validator(mode="after")
    def _check_times(self) -> Span:
        if self.ended_at < self.started_at:
            raise ValueError("ended_at must be >= started_at")
        return self

    @property
    def latency_ms(self) -> int:
        return int((self.ended_at - self.started_at).total_seconds() * 1000)


class TraceTree(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    request_id: str
    root_span: Span
    root_span_children: list[Span]
    total_latency_ms: int
    total_cost_cny: float
    cache_hit_rate: float

    @classmethod
    def from_spans(cls, spans: list[Span]) -> TraceTree:
        if not spans:
            raise ValueError("from_spans called with empty list")
        request_ids = {s.request_id for s in spans}
        if len(request_ids) != 1:
            raise ValueError(f"spans must share one request_id, got {request_ids}")
        request_id = next(iter(request_ids))
        roots = [s for s in spans if s.parent_id is None]
        if not roots:
            raise ValueError("no root span (all spans have a parent_id)")
        if len(roots) > 1:
            raise ValueError(f"multiple root spans: {[s.span_id for s in roots]}")
        root = roots[0]
        children = [s for s in spans if s.parent_id == root.span_id]
        cache_hits = [bool(s.metadata.get("cache_hit", False)) for s in spans]
        return cls(
            request_id=request_id,
            root_span=root,
            root_span_children=children,
            total_latency_ms=root.latency_ms,
            total_cost_cny=sum(float(s.metadata.get("cost_cny", 0.0)) for s in spans),
            cache_hit_rate=(sum(cache_hits) / len(cache_hits)) if cache_hits else 0.0,
        )
