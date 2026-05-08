"""E2E: Onboarding 完整链路 + 监控周期写 quote → dashboard 读浮盈(PG container)。

Fixture 依赖 conftest.py 的 pg_test_container + register endpoint。

覆盖场景 (spec § 5 场景 7):
  1. auth register → access_token
  2. POST /portfolio/onboarding 录入 2 笔 initial trade
  3. 直连 DB 用 PositionService.update_quote() 模拟监控引擎写 quote
  4. GET /portfolio/positions 验 last_quote_price 字段

PR-A (dual-track schema bug) 说明:
  Base.metadata.create_all() 在 PG 上因 chat_sessions.user_id 类型不匹配会
  回滚整个 DDL 事务, 导致所有表都没建成。workaround: 只 pre-create 本测试
  需要的三张表(users / trades / positions), 每张独立 autocommit 事务。
  (与 test_pg_serve_path_e2e.py 中 User + ResearchReport 的 workaround 同模式)
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient


@pytest.mark.e2e
@pytest.mark.usefixtures("pg_test_container")
def test_onboarding_then_quote_then_list_e2e(
    pg_test_container: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """register → onboarding → 模拟监控写 quote → GET /positions 验 quote 字段。"""
    # 1. 覆盖 e2e conftest 的 LLM_MODE=cassette (本测试不触发 LLM)
    monkeypatch.setenv("LLM_MODE", "mock")

    # 2. Import app + models (必须在 fixture yield 之后, 即 PG 已 up + test db 已建)
    from app.app_main import app
    from app.core.database import engine
    from app.models.position import Position
    from app.models.trade import Trade
    from app.models.user import User
    from app.services.position_service import PositionService

    # 3. Workaround for PR-A dual-track schema bug:
    #    pre-create users / trades / positions 各在独立事务中, 绕过
    #    chat_sessions FK mismatch 导致的整批 DDL 回滚。
    User.__table__.create(bind=engine, checkfirst=True)
    Trade.__table__.create(bind=engine, checkfirst=True)
    Position.__table__.create(bind=engine, checkfirst=True)

    # 4. 唯一后缀避免重复 run 时 duplicate username/email 409
    suffix = _uuid.uuid4().hex[:8]
    username = f"portfolio_e2e_{suffix}"
    email = f"portfolio_e2e_{suffix}@example.com"

    # 5. TestClient MUST be used in `with` context manager to trigger lifespan
    #    (feedback_serve_path_no_ci_coverage).
    with TestClient(app) as client:
        # --- Step 1: Register ---
        reg = client.post(
            "/auth/register",
            json={"username": username, "email": email, "password": "Pa55word!!"},
        )
        assert reg.status_code == 201, f"register failed: {reg.status_code} {reg.text}"
        body = reg.json()
        assert "access_token" in body, f"missing access_token: {body}"
        token = body["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # --- Step 2: POST /portfolio/onboarding ---
        ob_resp = client.post(
            "/portfolio/onboarding",
            headers=auth,
            json={
                "trades": [
                    {
                        "ts_code": "600519.SH",
                        "name": "贵州茅台",
                        "type": "initial",
                        "quantity": 200,
                        "price": "1450.00",
                        "trade_date": "2024-06-01",
                    },
                    {
                        "ts_code": "000001.SZ",
                        "name": "平安银行",
                        "type": "initial",
                        "quantity": 1000,
                        "price": "12.00",
                        "trade_date": "2024-06-01",
                    },
                ]
            },
        )
        assert ob_resp.status_code == 201, (
            f"onboarding failed: {ob_resp.status_code} {ob_resp.text}"
        )
        ob_body = ob_resp.json()
        assert len(ob_body["trades"]) == 2
        assert len(ob_body["positions"]) == 2

        # --- Step 3: Resolve user_id via /auth/me ---
        me_resp = client.get("/auth/me", headers=auth)
        assert me_resp.status_code == 200, f"/auth/me failed: {me_resp.status_code} {me_resp.text}"
        user_id = me_resp.json()["id"]

        # --- Step 4: Directly write quote via PositionService (simulates monitoring engine) ---
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            pos_svc = PositionService(db)
            pos_svc.update_quote(
                user_id=user_id,
                ts_code="600519.SH",
                price=Decimal("1580.00"),
                at=datetime.utcnow(),
            )
            db.commit()
        finally:
            db.close()

        # --- Step 5: GET /portfolio/positions and assert quote field ---
        list_resp = client.get("/portfolio/positions", headers=auth)
        assert list_resp.status_code == 200, (
            f"GET /positions failed: {list_resp.status_code} {list_resp.text}"
        )
        items = list_resp.json()
        assert len(items) == 2, f"expected 2 positions, got {len(items)}: {items}"

        maotai = next((p for p in items if p["ts_code"] == "600519.SH"), None)
        assert maotai is not None, "贵州茅台 position not found"
        assert maotai["quantity"] == 200
        assert Decimal(maotai["last_quote_price"]) == Decimal("1580.00"), (
            f"expected last_quote_price=1580.00, got {maotai['last_quote_price']}"
        )
        # avg_cost 1450 → 浮盈 = (1580-1450)*200 = 26000; 浮盈率 ≈ 8.97%
        assert Decimal(maotai["avg_cost"]) == Decimal("1450.0000"), (
            f"expected avg_cost=1450.0000, got {maotai['avg_cost']}"
        )

        # 平安银行 position: quote price still None (未写入)
        pingan = next((p for p in items if p["ts_code"] == "000001.SZ"), None)
        assert pingan is not None, "平安银行 position not found"
        assert pingan["last_quote_price"] is None
