"""Versioned, deterministic A-share market-access rules."""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.investor_suitability import Market


class MarketAccessRule(BaseModel):
    """One immutable market-access rule and its required risk disclosure."""

    model_config = ConfigDict(frozen=True)

    market: Market
    rule_version: str
    minimum_average_assets_20d: Decimal | None
    minimum_experience_months: int | None
    required_disclosure_version: str


class MarketRuleBook(BaseModel):
    """An immutable rulebook containing exactly one current rule per market."""

    model_config = ConfigDict(frozen=True)

    rulebook_version: str
    rules: tuple[MarketAccessRule, ...]

    @model_validator(mode="after")
    def has_exactly_one_rule_for_each_market(self) -> MarketRuleBook:
        markets = tuple(rule.market for rule in self.rules)
        if len(markets) != len(Market) or set(markets) != set(Market):
            raise ValueError("rulebook must contain exactly one rule for each market")
        if len(set(markets)) != len(markets):
            raise ValueError("rulebook cannot contain duplicate market rules")
        return self

    def current(self, market: Market) -> MarketAccessRule:
        return next(rule for rule in self.rules if rule.market is market)


class FailedCondition(BaseModel):
    """A single threshold the submitted investor information did not meet."""

    model_config = ConfigDict(frozen=True)

    code: Literal["assets_below_minimum", "experience_below_minimum"]
    actual: Decimal | int
    required: Decimal | int


class AssessmentDecision(BaseModel):
    """The deterministic decision produced from one named rule version."""

    model_config = ConfigDict(frozen=True)

    allowed: bool
    failed_conditions: tuple[FailedCondition, ...]
    rule_version: str


@lru_cache(maxsize=1)
def rulebook() -> MarketRuleBook:
    """Load the bundled A-share rulebook once as an immutable contract."""

    path = Path(__file__).with_name("rules") / "a_share_20260727.json"
    return MarketRuleBook.model_validate(json.loads(path.read_text(encoding="utf-8")))


def evaluate_market_access(
    rules: MarketRuleBook,
    market: Market,
    average_assets_20d: Decimal,
    experience_months: int,
) -> AssessmentDecision:
    """Evaluate a market request with no database, clock, or LLM dependency."""

    rule = rules.current(market)
    failures: list[FailedCondition] = []

    if (
        rule.minimum_average_assets_20d is not None
        and average_assets_20d < rule.minimum_average_assets_20d
    ):
        failures.append(
            FailedCondition(
                code="assets_below_minimum",
                actual=average_assets_20d,
                required=rule.minimum_average_assets_20d,
            )
        )
    if (
        rule.minimum_experience_months is not None
        and experience_months < rule.minimum_experience_months
    ):
        failures.append(
            FailedCondition(
                code="experience_below_minimum",
                actual=experience_months,
                required=rule.minimum_experience_months,
            )
        )

    return AssessmentDecision(
        allowed=not failures,
        failed_conditions=tuple(failures),
        rule_version=rule.rule_version,
    )
