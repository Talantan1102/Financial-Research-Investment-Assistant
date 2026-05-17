"""L0 fixture sanity — db_session 是真 PG + 每 test rollback isolation."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def test_db_session_is_postgres(db_session: Session) -> None:
    """fixture 提供的 session 连的是真 PG,不是 sqlite。"""
    dialect = db_session.bind.dialect.name
    assert dialect == "postgresql", f"db_session expected postgresql, got {dialect}"


def test_db_session_create_all_already_ran(db_session: Session) -> None:
    """fixture 启动时 create_all 已跑过,users 表存在。"""
    result = db_session.execute(text("SELECT to_regclass('public.users')")).scalar()
    assert result == "users"


def test_db_session_rolls_back_between_tests_step1(db_session: Session) -> None:
    """前置 test:插一行 sentinel。Step 2 用同 fixture 应该看不到这一行。"""
    db_session.execute(
        text("CREATE TABLE IF NOT EXISTS _fixture_rollback_probe (id INT PRIMARY KEY, marker TEXT)")
    )
    db_session.execute(text("INSERT INTO _fixture_rollback_probe (id, marker) VALUES (1, 'step1')"))


def test_db_session_rolls_back_between_tests_step2(db_session: Session) -> None:
    """后置 test:跨 fixture rollback 后,上一 test 插的 sentinel 不可见。"""
    result = db_session.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = '_fixture_rollback_probe'"
        )
    ).scalar()
    assert result == 0, (
        "rollback failed — _fixture_rollback_probe table leaked from prior test "
        "(DDL in PG is transactional; table should not exist after outer-tx rollback)"
    )
