"""安全相关：密码哈希、JWT Token"""

import os
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from pydantic import BaseModel

# JWT 配置
# C5: a dev/test default is allowed at import time (tests/eval/CLI don't serve auth),
# but the serving app MUST call assert_jwt_secret_configured() at startup so a real
# deployment can never sign/verify tokens with a publicly-known key.
_INSECURE_JWT_DEFAULT = "insecure-dev-default-change-me"
_KNOWN_INSECURE_JWT = frozenset(
    {_INSECURE_JWT_DEFAULT, "your-super-secret-key-change-in-production"}
)
SECRET_KEY = os.getenv("JWT_SECRET_KEY") or _INSECURE_JWT_DEFAULT
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))


def assert_jwt_secret_configured() -> None:
    """C5 fail-fast guard for the serving app (call from lifespan startup).

    Raises if JWT_SECRET_KEY is unset or a known-insecure default — otherwise the
    server would silently sign/accept JWTs with a publicly-known key, letting an
    attacker forge tokens for any user. Read at call time so env loaded via
    load_dotenv() before startup is respected.
    """
    raw = os.getenv("JWT_SECRET_KEY")
    if not raw or raw in _KNOWN_INSECURE_JWT:
        raise RuntimeError(
            "JWT_SECRET_KEY is unset or uses a known-insecure default — set a unique "
            "random secret (e.g. `openssl rand -hex 32`) before starting the server."
        )


class Token(BaseModel):
    """Token 响应模型"""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Token 数据模型"""

    user_id: str | None = None
    username: str | None = None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """创建访问 Token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> TokenData | None:
    """解码 Token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        username: str = payload.get("username")
        if user_id is None:
            return None
        return TokenData(user_id=user_id, username=username)
    except JWTError:
        return None
