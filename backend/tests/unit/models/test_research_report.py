"""ResearchReport SQLAlchemy model 字段 schema.

Production = PostgreSQL (JSONB + UUID native types).
Unit test = real PG via db_session fixture.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.models.research_report import ResearchReport
from sqlalchemy.orm import Session


def test_research_report_create(db_session: Session) -> None:
    """完整字段写入 + 读取还原."""
    report = ResearchReport(
        id="report-uuid-1",
        user_id=None,  # nullable=True 允许 anon user
        target_name="贵州茅台",
        target_ts_code="600519.SH",
        status="completed",
        report_json={"target_overview": {"target_name": "贵州茅台"}},
        cost=Decimal("3.50"),
        request_id="req-uuid-1",
    )
    db_session.add(report)
    db_session.commit()

    fetched = db_session.query(ResearchReport).filter_by(id="report-uuid-1").first()
    assert fetched is not None
    assert fetched.target_name == "贵州茅台"
    assert fetched.target_ts_code == "600519.SH"
    assert fetched.status == "completed"
    assert fetched.report_json["target_overview"]["target_name"] == "贵州茅台"
    assert fetched.cost == Decimal("3.50")
    assert fetched.request_id == "req-uuid-1"
    assert isinstance(fetched.created_at, datetime)
    assert isinstance(fetched.updated_at, datetime)


def test_research_report_default_cost(db_session: Session) -> None:
    """cost 默认 0;target_ts_code / request_id nullable;status 必填."""
    report = ResearchReport(
        id="report-uuid-2",
        target_name="test target",
        status="streaming",
        report_json={},
    )
    db_session.add(report)
    db_session.commit()
    fetched = db_session.query(ResearchReport).filter_by(id="report-uuid-2").first()
    assert fetched is not None
    assert fetched.cost == Decimal("0")
    assert fetched.target_ts_code is None
    assert fetched.request_id is None
    assert fetched.user_id is None
    assert fetched.status == "streaming"


def test_research_report_status_transitions(db_session: Session) -> None:
    """status 字段支持 streaming → completed → failed 任意值(应用层语义,非 DB 约束)."""
    report = ResearchReport(
        id="report-uuid-3",
        target_name="status-test",
        status="streaming",
        report_json={"sections": []},
    )
    db_session.add(report)
    db_session.commit()

    fetched = db_session.query(ResearchReport).filter_by(id="report-uuid-3").first()
    assert fetched is not None
    fetched.status = "completed"  # type: ignore[assignment]
    fetched.report_json = {"sections": ["overview"]}  # type: ignore[assignment]
    db_session.commit()

    re_fetched = db_session.query(ResearchReport).filter_by(id="report-uuid-3").first()
    assert re_fetched is not None
    assert re_fetched.status == "completed"
    assert re_fetched.report_json == {"sections": ["overview"]}
