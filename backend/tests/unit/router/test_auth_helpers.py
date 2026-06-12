"""auth_helpers: _AnonUser + get_current_user(C.6 接真 JWT 后)。

get_current_user 现为 async 依赖:委托 auth_router.get_current_user 校验 Bearer token,
有真 User 则直通、无/无效 token 回退 _AnonUser。本 test 验匿名回退侧;真 User 直通侧
见 test_auth_helpers_real_auth.py。
"""

from __future__ import annotations

import pytest
from app.router.auth_helpers import _AnonUser, get_current_user


def test_anon_user_default_id_is_anonymous() -> None:
    """_AnonUser() no-arg 构造,id 默认 'anonymous'。"""
    user = _AnonUser()
    assert user.id == "anonymous"


def test_anon_user_class_attr_is_anonymous() -> None:
    """class-level id attribute 也是 'anonymous'。"""
    assert _AnonUser.id == "anonymous"


@pytest.mark.asyncio
async def test_get_current_user_falls_back_to_anon_when_no_token() -> None:
    """get_current_user 是 async 依赖;无真 user(无/无效 token)→ 回退 _AnonUser。"""
    user = await get_current_user(real_user=None)
    assert isinstance(user, _AnonUser)
    assert user.id == "anonymous"


@pytest.mark.asyncio
async def test_get_current_user_returns_fresh_anon_each_call() -> None:
    """无 token 每次回退新 _AnonUser 实例(不缓存)。"""
    u1 = await get_current_user(real_user=None)
    u2 = await get_current_user(real_user=None)
    assert u1 is not u2
    assert u1.id == u2.id == "anonymous"
