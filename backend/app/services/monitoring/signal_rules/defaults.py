"""Default thresholds per signal rule(spec § 5.2)."""

from __future__ import annotations

DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "financial_ratio": {
        "yellow_debt_ratio_qoq_pp": 5.0,  # 资产负债率单季环比 +5 pp
        "yellow_net_margin_negative": 0.0,
        "red_debt_ratio_abs": 80.0,  # 资产负债率 80%
        "red_consecutive_loss_quarters": 2,
    },
    "cash_flow": {
        "yellow_op_cf_qoq_drop_pct": 30.0,
        "red_consecutive_negative_quarters": 2,
    },
    "shareholder_count": {
        "yellow_min_drop_pct": 10.0,
        "yellow_max_drop_pct": 20.0,
        "red_drop_pct": 20.0,
    },
    "announcement": {
        "yellow_lower": 0.5,
        "yellow_upper": 0.8,
        "red_threshold": 0.8,
    },
    "price_anomaly": {
        "yellow_single_day_drop_pct": 5.0,
        "yellow_60d_drop_pct": 20.0,
        "red_single_day_drop_pct": 10.0,
        "red_consecutive_5d_drop_pct": 25.0,
    },
}
