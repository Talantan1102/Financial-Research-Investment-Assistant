"""聊天相关模型"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChatAttachment(Base):
    """聊天附件模型"""

    __tablename__ = "chat_attachments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(
        UUID(as_uuid=True), ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=True
    )
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # pdf, docx, txt, image, etc.
    file_size = Column(BigInteger, nullable=False)
    file_path = Column(String(500), nullable=False)  # 文件存储路径
    content_text = Column(Text)  # 提取的文本内容（用于问答）
    status = Column(String(20), default="pending")  # pending, processing, completed, failed
    error_message = Column(Text)  # 处理错误信息
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    message = relationship("ChatMessage", back_populates="attachments")
    session = relationship("ChatSession", back_populates="attachments")


class ChatSession(Base):
    """聊天会话模型"""

    __tablename__ = "chat_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    title = Column(String(255), default="新对话")
    session_type = Column(String(50), default="chat")  # chat, deepsearch
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # === v0.9 NEW (sidebar list usage) ===
    message_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_msg_preview = Column(Text, nullable=True)

    # 关系
    user = relationship("User", back_populates="sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    memories = relationship("LongTermMemory", back_populates="session")
    attachments = relationship(
        "ChatAttachment", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """聊天消息模型"""

    __tablename__ = "chat_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    thinking = Column(Text)  # 思考过程
    references_data = Column(JSONB)  # 引用的文档
    image_results = Column(JSONB)  # 图片搜索结果
    created_at = Column(DateTime, default=datetime.utcnow)

    # === v0.9 NEW ===
    message_type = Column(
        String(32),
        nullable=False,
        default="text",
        server_default="text",
    )  # text|tool_result|research_report
    research_report_id = Column(String(64), nullable=True)
    research_report_summary = Column(Text, nullable=True)
    tool_call_data = Column(JSONB(), nullable=True)
    task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(
        String(16),
        nullable=False,
        default="done",
        server_default="done",
    )  # done|partial|cancelled|error

    # 关系
    session = relationship("ChatSession", back_populates="messages")
    attachments = relationship("ChatAttachment", back_populates="message")


class ChatTask(Base):
    """聊天任务模型(Plan 1 落地;Plan 2 由 Celery worker 写入)"""

    __tablename__ = "chat_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(
        String(16),
        nullable=False,
        default="queued",
        server_default="queued",
    )  # queued|running|done|cancelled|partial|error
    langgraph_thread_id = Column(String(128), nullable=False)
    langgraph_checkpoint_id = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    last_event_seq = Column(BigInteger, nullable=False, default=0, server_default="0")
    initial_prompt_message_id = Column(UUID(as_uuid=True), nullable=True)
    parent_task_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chat_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','cancelled','partial','error')",
            name="chat_tasks_status_check",
        ),
    )

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("status", "queued")
        kwargs.setdefault("last_event_seq", 0)
        super().__init__(**kwargs)


class LongTermMemory(Base):
    """长期记忆模型"""

    __tablename__ = "long_term_memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    session_id = Column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    summary = Column(Text, nullable=False)  # 记忆摘要
    key_insights = Column(JSONB)  # 关键洞察
    milvus_ids = Column(ARRAY(Text))  # Milvus 中的向量 ID
    token_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关系
    user = relationship("User", back_populates="memories")
    session = relationship("ChatSession", back_populates="memories")
