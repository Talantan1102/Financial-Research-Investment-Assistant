from app.chatloop.paper_trade_schemas import (
    CancelPaperOrderArgs,
    PlacePaperOrderArgs,
    ResetPaperAccountArgs,
)
from app.chatloop.worker_wiring import paper_approval_schemas


def test_only_high_risk_paper_writes_are_editable_on_resume() -> None:
    assert paper_approval_schemas() == {
        "place_paper_order": PlacePaperOrderArgs,
        "cancel_paper_order": CancelPaperOrderArgs,
        "reset_paper_account": ResetPaperAccountArgs,
    }
