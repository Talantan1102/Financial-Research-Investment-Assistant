"""L1 — LLMService writes real cost into LLMResponse + CostBudget enforcement."""

import pytest
from app.services.cost_budget import BudgetExceeded, CostBudget
from app.services.llm_mock_client import MockLLMClient
from app.services.llm_service import LLMService
from app.services.pricing import compute_cost


def test_chat_response_cost_is_real(mock_llm_client: MockLLMClient) -> None:
    svc = LLMService(client=mock_llm_client)
    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
    expected = compute_cost(
        model=r.model,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
    )
    assert r.cost_cny == pytest.approx(expected)
    assert r.cost_cny > 0  # not the stub anymore


def test_budget_aborts_next_call_after_over(mock_llm_client: MockLLMClient) -> None:
    """Budget allows the call that pushes us over; next call's pre-flight raises."""
    # Set limit so low that one call exceeds it.
    budget = CostBudget(limit_cny=1e-9)
    svc = LLMService(client=mock_llm_client, cost_budget=budget)

    r1 = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
    assert r1.cost_cny > 0
    assert budget.spent_cny > budget.limit_cny

    with pytest.raises(BudgetExceeded):
        svc.chat(prompt="What is the price of 600519.SH?", tier="fast")


def test_budget_under_limit_allows_many_calls(mock_llm_client: MockLLMClient) -> None:
    budget = CostBudget(limit_cny=1.0)  # 100x typical mock cost
    svc = LLMService(client=mock_llm_client, cost_budget=budget)

    for _ in range(5):
        r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
        assert r.cost_cny > 0

    assert budget.spent_cny < budget.limit_cny


def test_no_budget_keeps_plan_b_contract(mock_llm_client: MockLLMClient) -> None:
    """LLMService(client) without cost_budget is unchanged from Plan B."""
    svc = LLMService(client=mock_llm_client)
    r = svc.chat(prompt="What is the price of 600519.SH?", tier="fast")
    assert r.content
