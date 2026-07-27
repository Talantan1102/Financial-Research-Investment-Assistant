from app.chatloop.paper_trade_schemas import (
    CancelPaperOrderArgs,
    PlacePaperOrderArgs,
    ResetPaperAccountArgs,
)
from app.chatloop.tool_runtime_policy import production_visible_capabilities
from app.chatloop.worker_wiring import paper_approval_schemas


def test_only_high_risk_paper_writes_are_editable_on_resume() -> None:
    assert paper_approval_schemas() == {
        "place_paper_order": PlacePaperOrderArgs,
        "cancel_paper_order": CancelPaperOrderArgs,
        "reset_paper_account": ResetPaperAccountArgs,
    }


def test_market_permission_tools_are_visible_to_the_worker() -> None:
    visible = production_visible_capabilities(object())
    assert {
        "get_market_entitlements",
        "check_order_eligibility",
        "get_entitlement_application_link",
    } <= visible
