"""共享 auth helpers — _AnonUser 和 get_current_user 依赖.

历史:原本在 app/router/chat.py 中定义,但 research.py 等其他 router 也 reuse;
v0.9.x 解耦时抽出来作为共享模块。Task 3 删除 chat.py 后,这里是单一入口。

不动 logic — 只搬位置,implementation 严格逐行 copy 自 chat.py。
真 auth 仍在 app.router.auth_router(OAuth2 + JWT),本 stub 仅供 v0 路径使用。
"""

from __future__ import annotations

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
