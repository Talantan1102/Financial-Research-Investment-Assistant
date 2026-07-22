from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
from app.chatloop.tool_docs import CORE_TOOLS, TOOL_DOCS


def test_paper_trade_is_a_core_tool_with_complete_operating_contract() -> None:
    assert "paper_trade" in CORE_TOOLS
    doc = TOOL_DOCS["paper_trade"]
    for action in (
        "get_account",
        "list_orders",
        "get_order",
        "prepare_order",
        "prepare_cancel",
        "prepare_reset",
    ):
        assert action in doc.doc
    assert "研究" in doc.doc
    assert "金额" in doc.doc and "股数" in doc.doc
    assert "confirm" in doc.doc


def test_prompt_has_paper_trade_safety_rules() -> None:
    assert "只在用户明确提出买入、卖出、撤单或重置时" in CHAT_SYSTEM_PROMPT
    assert "研究" in CHAT_SYSTEM_PROMPT
    assert "缺少股票身份、买卖方向或数量时先追问" in CHAT_SYSTEM_PROMPT
    assert "prepare 只是确认卡" in CHAT_SYSTEM_PROMPT
