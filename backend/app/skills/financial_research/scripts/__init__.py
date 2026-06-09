"""Financial research deterministic helper scripts.

Public surface re-exported here so callers can import via the package root:
    from app.skills.financial_research.scripts import lookup_industry_benchmark

去推荐改造(2026-06-04):classify_recommendation / compute_position_size_pct
推荐引擎脚本已下线,仅保留 lookup_industry_benchmark。
"""

from app.skills.financial_research.scripts.lookup_industry_benchmark import (
    lookup_industry_benchmark,
)

__all__ = [
    "lookup_industry_benchmark",
]
