"""Legacy module — see backend/LEGACY_LAYOUT.md for module-by-module status and v1.x evolution plan.

New features should prefer importing from `app/services/*` (plural, v0.8.x main path).
"""

from .database import Base, SessionLocal, engine, get_db
from .redis_client import RedisCache, cache, get_redis_client
from .security import (
    Token,
    TokenData,
    create_access_token,
    decode_token,
    get_password_hash,
    verify_password,
)

__all__ = [
    "get_db",
    "SessionLocal",
    "engine",
    "Base",
    "verify_password",
    "get_password_hash",
    "create_access_token",
    "decode_token",
    "Token",
    "TokenData",
    "cache",
    "get_redis_client",
    "RedisCache",
]
