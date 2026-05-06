"""用户模型"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    """用户模型"""

    __tablename__ = "users"

    # PG = native UUID; SQLite (test) = String(36) — mirrors ResearchReport pattern.
    # 必要因为 get_user_by_id(db, str_user_id) 在 SQLite + 纯 UUID column 下报
    # AttributeError: 'str' object has no attribute 'hex'(SQLAlchemy UUID type
    # 在 bind 时调 .hex);with_variant 让 SQLite 把 column 当 String(36) 处理.
    # default 用 lambda → str(uuid4()) 让 SQLite 能直接 bind;PG 也接受 str 形式 UUID.
    id = Column(
        UUID(as_uuid=True).with_variant(String(36), "sqlite"),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    knowledge_bases = relationship(
        "KnowledgeBase", back_populates="user", cascade="all, delete-orphan"
    )
    documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")
    memories = relationship("LongTermMemory", back_populates="user", cascade="all, delete-orphan")
