"""异步生成 chat session title 的 Celery task.

触发: router/chat_finalize.py 在首轮 assistant 落库后 enqueue.
幂等: 启动时检查 title_source 不为 pending 则 skip.
失败兜底: 显式 3 次 attempt 用完后 fallback 到 user.content[:20] 截断 (超 20 字才追加 "...").

注: 用显式 for-loop attempts 而非 Celery autoretry, 因为 eager 模式下 autoretry 行为
不可观察 / 难单测; 这种 best-effort 副产品任务三次本进程内即可, 失败成本极低。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.core.database import engine
from app.models.chat import ChatMessage, ChatSession
from app.services.openai_client import build_llm_service_from_env
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_TITLE_MAX_CHARS = 255
_ASSISTANT_INPUT_CHARS = 500
_STRIP_CHARS = "\"'「」 \n\t"
_MAX_ATTEMPTS = 3


def _open_db_session() -> Session:
    """Indirection 给 unit test 用 monkeypatch."""
    return sessionmaker(bind=engine)()


def get_llm_service():  # noqa: ANN201
    """Indirection 给 unit test 用 patch."""
    return build_llm_service_from_env()


def _llm_generate_title(user_text: str, assistant_text: str) -> str:
    """调 LLMService cheap tier 生成 10-15 字 title."""
    llm = get_llm_service()
    prompt = (
        "请为以下对话生成一个 10-15 个汉字的简洁标题, 直接返回标题文本, "
        "不要任何前后缀 / 引号 / 编号:\n\n"
        f"用户: {user_text}\n"
        f"助手: {assistant_text}"
    )
    resp = llm.chat(prompt=prompt, tier="fast", schema=None)
    raw = resp.content.strip()
    for ch in _STRIP_CHARS:
        raw = raw.strip(ch)
    return raw[:_TITLE_MAX_CHARS]


@celery_app.task(
    bind=True,
    name="app.tasks.title_generation.generate_session_title",
)
def generate_session_title(self, session_id: str) -> None:  # noqa: ANN001
    sid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id

    with _open_db_session() as db:
        session = db.query(ChatSession).filter_by(id=sid).one_or_none()
        if session is None:
            logger.debug("title task: session %s gone, skipping", session_id)
            return
        if session.title_source != "pending":
            logger.debug(
                "title task: session %s already %s, skipping",
                session_id,
                session.title_source,
            )
            return

        msgs = (
            db.query(ChatMessage)
            .filter_by(session_id=sid)
            .order_by(ChatMessage.created_at.asc())
            .limit(2)
            .all()
        )
        if len(msgs) < 2:
            logger.debug("title task: only %d messages, skipping", len(msgs))
            return
        user_msg, assistant_msg = msgs[0], msgs[1]

        user_content: str = str(user_msg.content)
        assistant_content: str = str(assistant_msg.content)

        title: str | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                title = _llm_generate_title(
                    user_text=user_content,
                    assistant_text=assistant_content[:_ASSISTANT_INPUT_CHARS],
                )
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == _MAX_ATTEMPTS - 1:
                    logger.warning(
                        "title task: LLM exhausted %d attempts (%s), fallback to truncation",
                        _MAX_ATTEMPTS,
                        exc,
                    )
                    title = user_content[:20] + ("..." if len(user_content) > 20 else "")
                    break
                logger.debug(
                    "title task: LLM attempt %d failed (%s), retrying",
                    attempt + 1,
                    exc,
                )

        assert title is not None  # loop 必走通其中一支; helps mypy narrow str | None
        session.title = title  # type: ignore[assignment]
        session.title_source = "llm_generated"  # type: ignore[assignment]
        db.commit()
        logger.info("title task: session %s → %r", session_id, title)
