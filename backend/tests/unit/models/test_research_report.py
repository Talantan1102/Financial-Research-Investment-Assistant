"""ResearchReport SQLAlchemy model 字段 schema.

Production = PostgreSQL (JSONB + UUID native types).
Unit test = sqlite in-memory (JSONB → JSON, UUID → String via with_variant).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from app.models.research_report import ResearchReport
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def in_memory_engine() -> Any:
    """sqlite in-memory 跑 unit test (production = PG)."""
    engine = create_engine("sqlite:///:memory:")
    # Only create the research_reports table (FK to users will be a no-op in
    # sqlite by default; we don't need the users table for these tests).
    ResearchReport.__table__.create(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(in_memory_engine: Any) -> Any:
    SessionLocal = sessionmaker(bind=in_memory_engine)
    s = SessionLocal()
    yield s
    s.close()


def test_research_report_create(session: Session) -> None:
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
    session.add(report)
    session.commit()

    fetched = session.query(ResearchReport).filter_by(id="report-uuid-1").first()
    assert fetched is not None
    assert fetched.target_name == "贵州茅台"
    assert fetched.target_ts_code == "600519.SH"
    assert fetched.status == "completed"
    assert fetched.report_json["target_overview"]["target_name"] == "贵州茅台"
    assert fetched.cost == Decimal("3.50")
    assert fetched.request_id == "req-uuid-1"
    assert isinstance(fetched.created_at, datetime)
    assert isinstance(fetched.updated_at, datetime)


def test_research_report_default_cost(session: Session) -> None:
    """cost 默认 0;target_ts_code / request_id nullable;status 必填."""
    report = ResearchReport(
        id="report-uuid-2",
        target_name="test target",
        status="streaming",
        report_json={},
    )
    session.add(report)
    session.commit()
    fetched = session.query(ResearchReport).filter_by(id="report-uuid-2").first()
    assert fetched is not None
    assert fetched.cost == Decimal("0")
    assert fetched.target_ts_code is None
    assert fetched.request_id is None
    assert fetched.user_id is None
    assert fetched.status == "streaming"


def test_research_report_status_transitions(session: Session) -> None:
    """status 字段支持 streaming → completed → failed 任意值(应用层语义,非 DB 约束)."""
    report = ResearchReport(
        id="report-uuid-3",
        target_name="status-test",
        status="streaming",
        report_json={"sections": []},
    )
    session.add(report)
    session.commit()

    fetched = session.query(ResearchReport).filter_by(id="report-uuid-3").first()
    assert fetched is not None
    fetched.status = "completed"
    fetched.report_json = {"sections": ["overview"]}
    session.commit()

    re_fetched = session.query(ResearchReport).filter_by(id="report-uuid-3").first()
    assert re_fetched is not None
    assert re_fetched.status == "completed"
    assert re_fetched.report_json == {"sections": ["overview"]}
