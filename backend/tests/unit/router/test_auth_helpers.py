"""auth_helpers 解耦后行为不变.

Task 2: 把 _AnonUser + get_current_user 从 chat.py 抽到 auth_helpers.py。
本 test 验证解耦后 implementation 与 chat.py 原版完全一致。
"""

from __future__ import annotations

from app.router.auth_helpers import _AnonUser, get_current_user


def test_anon_user_default_id_is_anonymous() -> None:
    """_AnonUser() no-arg 构造,id 默认 'anonymous'。"""
    user = _AnonUser()
    assert user.id == "anonymous"


def test_anon_user_class_attr_is_anonymous() -> None:
    """class-level id attribute 也是 'anonymous'(chat.py 原版同时声明 class attr 和 __init__ 赋值)。"""
    assert _AnonUser.id == "anonymous"


def test_get_current_user_returns_anon_user_instance() -> None:
    """get_current_user() 是 sync function,无参,返回 _AnonUser 实例。"""
    user = get_current_user()
    assert isinstance(user, _AnonUser)
    assert user.id == "anonymous"


def test_get_current_user_returns_fresh_instance_each_call() -> None:
    """每次调用返回新 _AnonUser 实例(stub 不缓存)。"""
    u1 = get_current_user()
    u2 = get_current_user()
    assert u1 is not u2
    assert u1.id == u2.id == "anonymous"
