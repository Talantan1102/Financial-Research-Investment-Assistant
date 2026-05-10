"""L0: Cold start helper 纯函数."""

from __future__ import annotations

from datetime import datetime

from app.memory.cold_start import build_holds_edge_payload


def test_build_holds_payload_default_valid_from() -> None:
    """没有 purchase_date 时, 用 fallback(spec § 8 容许 last_updated_at 或 default)."""
    payload = build_holds_edge_payload(
        ts_code="600519.SH",
        qty=500,
        avg_cost=1500.0,
        purchase_date=None,
        fallback_date=datetime(2024, 1, 1),
    )
    assert payload["target_label"] == "600519.SH"
    assert payload["qty"] == 500
    assert payload["valid_from"].year == 2024
    assert payload["rel_type"] == "HOLDS"


def test_build_holds_payload_uses_purchase_date_when_present() -> None:
    purchase = datetime(2025, 6, 15)
    payload = build_holds_edge_payload(
        ts_code="000858.SZ",
        qty=300,
        avg_cost=200.0,
        purchase_date=purchase,
        fallback_date=datetime(2024, 1, 1),
    )
    assert payload["valid_from"] == purchase
    assert payload["importance"] == 0.9
