"""共享 auth helpers — _AnonUser 和 get_current_user 依赖.

历史:原本在 app/router/chat.py 中定义,但 research.py 等其他 router 也 reuse;
v0.9.x 解耦时抽出来作为共享模块。Task 3 删除 chat.py 后,这里是单一入口。

不动 logic — 只搬位置,implementation 严格逐行 copy 自 chat.py。
真 auth 仍在 app.router.auth_router(OAuth2 + JWT),本 stub 仅供 v0 路径使用。
"""

from __future__ import annotations

import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Stub User — v0 anonymous auth (real JWT auth lives in auth_router)
# ---------------------------------------------------------------------------


class _AnonUser:
    """Minimal user object for v0 anonymous access."""

    id: str = "anonymous"

    def __init__(self) -> None:
        self.id = "anonymous"


def get_current_user() -> _AnonUser:
    """v0 stub: every request is treated as anonymous.

    Real auth is preserved in app.router.auth_router (OAuth2 + JWT).  This
    stub is replaced by a proper dependency once auth integration is wired
    into the new router in a future task.
    """
    return _AnonUser()


# ---------------------------------------------------------------------------
# Object-level authorization — owns_resource(资源.user_id, 认证用户)
# ---------------------------------------------------------------------------


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    """Best-effort coerce a user id (UUID | str | None) into a UUID, else None."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def owns_resource(resource_user_id: Any, user: Any) -> bool:
    """True iff a per-user resource belongs to the authenticated ``user``.

    Used by chat / chats / escalate routers for object-level authorization
    (一律配合 ``get_current_user_required``,跨用户访问 → 404 防越权 + 防枚举)。

    强制登录下 ``user.id`` 永远是真 UUID,所以遗留匿名行(``user_id is None``)对
    任何登录用户都判 False。``None == None`` 这条「双方都不是 UUID」分支只在测试桩
    (id="test-user")里出现,生产路径(JWT 必出真 UUID)不可达。
    """
    return _coerce_uuid(resource_user_id) == _coerce_uuid(getattr(user, "id", None))
