"""L0 — auth_helpers.get_current_user:真 User 直通 / 无 token 回退匿名(C.6 wiring)。"""

from __future__ import annotations

import pytest
from app.router.auth_helpers import _AnonUser, get_current_user


class _RealUser:
    def __init__(self, uid: str) -> None:
        self.id = uid


@pytest.mark.asyncio
async def test_real_user_passes_through() -> None:
    u = _RealUser("8b76068b-bcaf-4aac-80cd-1266cade1442")
    out = await get_current_user(real_user=u)
    assert out is u
    assert out.id == "8b76068b-bcaf-4aac-80cd-1266cade1442"


@pytest.mark.asyncio
async def test_no_token_falls_back_to_anonymous() -> None:
    out = await get_current_user(real_user=None)
    assert isinstance(out, _AnonUser)
    assert out.id == "anonymous"
