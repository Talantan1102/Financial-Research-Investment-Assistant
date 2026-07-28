from __future__ import annotations

from app.chatloop.state import ChatLoopState
from eval.chatloop.business_runner import extract_business_tool_ledger
from eval.chatloop.faults import FaultPlan


def test_extract_tool_ledger_keeps_arguments_results_errors_and_call_ids() -> None:
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "ok-1",
                        "type": "function",
                        "function": {
                            "name": "get_market_quote",
                            "arguments": '{"ts_code":"000001.SZ"}',
                        },
                    },
                    {
                        "id": "bad-1",
                        "type": "function",
                        "function": {
                            "name": "place_paper_order",
                            "arguments": '{"quantity":100}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "ok-1",
                "content": '{"price":10.2}',
            },
            {
                "role": "tool",
                "tool_call_id": "bad-1",
                "content": "[ERROR] permission denied",
            },
        ],
    )

    ledger = extract_business_tool_ledger(state)

    assert ledger == (
        {
            "tool_name": "get_market_quote",
            "arguments": {"ts_code": "000001.SZ"},
            "result": {"price": 10.2},
            "error": None,
            "idempotency_key": "ok-1",
        },
        {
            "tool_name": "place_paper_order",
            "arguments": {"quantity": 100},
            "result": None,
            "error": "permission denied",
            "idempotency_key": "bad-1",
        },
    )


def test_extract_tool_ledger_marks_missing_response_instead_of_hiding_it() -> None:
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "lost-1",
                        "type": "function",
                        "function": {"name": "get_news", "arguments": "{}"},
                    }
                ],
            }
        ],
    )

    ledger = extract_business_tool_ledger(state)

    assert ledger[0]["result"] is None
    assert ledger[0]["error"] == "missing tool response"


def test_extract_tool_ledger_records_eval_fault_provenance_without_changing_tool_output() -> None:
    state = ChatLoopState(
        user_id="u",
        session_id="s",
        request_id="r",
        messages=[
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "quote-1",
                        "type": "function",
                        "function": {
                            "name": "get_stock_quote",
                            "arguments": '{"ts_code":"300308.SZ"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "quote-1",
                "content": '{"price":135.2,"trade_date":"2026-07-24"}',
            },
        ],
    )

    ledger = extract_business_tool_ledger(
        state,
        fault_plans=(FaultPlan(target="get_stock_quote", mode="stale"),),
    )

    assert ledger[0]["result"] == {"price": 135.2, "trade_date": "2026-07-24"}
    assert ledger[0]["fault_injection"] == {
        "injected": True,
        "mode": "stale",
        "target": "get_stock_quote",
    }
