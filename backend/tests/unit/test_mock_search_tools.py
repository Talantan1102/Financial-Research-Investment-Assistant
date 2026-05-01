"""L0 — args validation for web_search / mock_kb_search.

WebSearchArgs (v0.6) supports search_type in {"news", "industry", "report"};
"announcement" was dropped because the real Bocha API augments query instead.
"""

import pytest
from app.tools.mock_kb_search import KbSearchArgs
from app.tools.web_search import WebSearchArgs
from pydantic import ValidationError


def test_web_search_args_default() -> None:
    args = WebSearchArgs(query="茅台")
    assert args.query == "茅台"
    assert args.search_type == "news"
    assert args.count == 5


def test_web_search_args_industry_type() -> None:
    args = WebSearchArgs(query="茅台", search_type="industry")
    assert args.search_type == "industry"


def test_web_search_args_report_type() -> None:
    args = WebSearchArgs(query="茅台", search_type="report")
    assert args.search_type == "report"


def test_web_search_args_invalid_type_rejected() -> None:
    with pytest.raises(ValidationError):
        WebSearchArgs(query="x", search_type="weekly")  # type: ignore[arg-type]


def test_web_search_args_announcement_rejected() -> None:
    """v0.6 drops 'announcement' from Literal; real Bocha API has no such type."""
    with pytest.raises(ValidationError):
        WebSearchArgs(query="x", search_type="announcement")  # type: ignore[arg-type]


def test_web_search_args_negative_count_rejected() -> None:
    with pytest.raises(ValidationError):
        WebSearchArgs(query="x", count=-1)


def test_kb_search_args_minimal() -> None:
    args = KbSearchArgs(query="茅台")
    assert args.query == "茅台"
    assert args.top_k == 5


def test_kb_search_args_top_k_zero_rejected() -> None:
    with pytest.raises(ValidationError):
        KbSearchArgs(query="x", top_k=0)
