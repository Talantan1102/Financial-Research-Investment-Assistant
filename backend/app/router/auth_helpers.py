"""共享 auth helpers — _AnonUser 和 get_current_user 依赖.

历史:原本在 app/router/chat.py 中定义,但 research.py 等其他 router 也 reuse;
v0.9.x 解耦时抽出来作为共享模块。Task 3 删除 chat.py 后,这里是单一入口。

C.6:get_current_user 由「v0 恒匿名 stub」升级为「真 JWT 认证 + 匿名回退」——
委托 app.router.auth_router.get_current_user 校验 Bearer token,有效则返回真
User,无/无效 token 回退 _AnonUser。真 auth 实现仍在 auth_router(OAuth2 + JWT)。
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends

from app.router.auth_router import get_current_user as _jwt_get_current_user

# ---------------------------------------------------------------------------
# Anonymous fallback user — 无/无效 token 时用(真 JWT auth 在 auth_router)
# ---------------------------------------------------------------------------


class _AnonUser:
    """Minimal user object for anonymous (no/invalid token) access."""

    id: str = "anonymous"

    def __init__(self) -> None:
        self.id = "anonymous"


async def get_current_user(real_user: Any = Depends(_jwt_get_current_user)) -> Any:
    """真 JWT 认证 + 匿名回退(C.6 wiring)。

    登录(有效 Bearer token)→ 真 User(真 UUID id);
    无 / 无效 token → _AnonUser(id="anonymous")——保持 v0 匿名行为。
    `_jwt_get_current_user`(auth_router)校验 token 返回 User | None。
    """
    return real_user if real_user is not None else _AnonUser()
