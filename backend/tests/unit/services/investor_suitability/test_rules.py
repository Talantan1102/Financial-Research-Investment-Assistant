from decimal import Decimal

import pytest
from app.models.investor_suitability import Market
from app.services.investor_suitability.rules import (
    evaluate_market_access,
    rulebook,
)


@pytest.mark.parametrize(
    ("market", "assets", "months", "allowed", "codes"),
    [
        (Market.MAIN, Decimal("0"), 0, True, ()),
        (
            Market.CHINEXT,
            Decimal("99999.99"),
            24,
            False,
            ("assets_below_minimum",),
        ),
        (Market.CHINEXT, Decimal("100000"), 24, True, ()),
        (
            Market.STAR,
            Decimal("500000"),
            23,
            False,
            ("experience_below_minimum",),
        ),
        (Market.BSE, Decimal("500000"), 24, True, ()),
    ],
)
def test_evaluate_market_access(market, assets, months, allowed, codes):
    result = evaluate_market_access(rulebook(), market, assets, months)

    assert result.allowed is allowed
    assert tuple(item.code for item in result.failed_conditions) == codes


def test_rulebook_contains_disclosure_version_for_each_market():
    rules = rulebook()

    assert rules.current(Market.MAIN).required_disclosure_version
    assert rules.current(Market.CHINEXT).required_disclosure_version
    assert rules.current(Market.STAR).required_disclosure_version
    assert rules.current(Market.BSE).required_disclosure_version


def test_evaluation_records_the_rule_version_used():
    rules = rulebook()

    result = evaluate_market_access(rules, Market.STAR, Decimal("500000"), 24)

    assert result.rule_version == rules.current(Market.STAR).rule_version
