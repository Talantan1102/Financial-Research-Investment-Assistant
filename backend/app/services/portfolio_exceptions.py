"""Portfolio service domain exceptions(三态机 guard)。

Spec ref: docs/superpowers/specs/2026-05-07-v1.0-portfolio-data-model-engineering-design.md
§ 1 决策 2 + § 3.3。

API 层捕获 PortfolioError 子类返回 4xx + 用户友好消息。
"""

from __future__ import annotations


class PortfolioError(Exception):
    """Portfolio domain exception base — all portfolio service errors inherit."""


class ImmutableTradeError(PortfolioError):
    """Attempted to update fields on a non-initial Trade(常规 trade 任何时候不可改字段)。"""


class ExpiredDeletionError(PortfolioError):
    """Attempted to delete a Trade older than 24h(超 24h 不可删,需录反向交易抵消)。"""
