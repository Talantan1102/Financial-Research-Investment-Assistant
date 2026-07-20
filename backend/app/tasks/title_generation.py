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
from app.models.run import RunMessage, RunSession
from app.services.openai_client import build_llm_service_from_env
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_TITLE_MAX_CHARS = 255
_STRIP_CHARS = "\"'「」 \n\t"
_MAX_ATTEMPTS = 3


def _open_db_session() -> Session:
    """Indirection 给 unit test 用 monkeypatch."""
    return sessionmaker(bind=engine)()


def get_llm_service():  # noqa: ANN201
    """Indirection 给 unit test 用 patch."""
    return build_llm_service_from_env()


def _llm_generate_title(user_text: str) -> str:
    """调 LLMService cheap tier 提取用户提问意图作为 6-12 字 session 标题.

    只用 user_msg, 不喂 assistant_msg — assistant 输出会让 LLM 偏向"AI 视角的
    对话总结"(如"茅台投资需结合数据与风险"), 我们要的是"用户问了什么"
    (如"贵州茅台估值分析")。
    """
    llm = get_llm_service()
    prompt = (
        "请提取以下用户提问的核心意图, 用 6-12 个汉字生成简洁的会话标题。"
        "标题应聚焦用户问什么/想了解什么, 像新闻或文章标题那样凝练, "
        "不要描述对话过程或回复内容, 不要任何前后缀 / 引号 / 编号:\n\n"
        f"用户提问: {user_text}"
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
        session = db.query(RunSession).filter_by(id=sid).one_or_none()
        if session is None:
            logger.debug("title task: session %s gone, skipping", session_id)
            return
        if session.title:
            logger.debug(
                "title task: session %s already %s, skipping",
                session_id,
                "existing",
            )
            return

        user_msg = (
            db.query(RunMessage)
            .filter_by(session_id=sid, role="user")
            .order_by(RunMessage.created_at.asc())
            .first()
        )
        if user_msg is None:
            logger.debug("title task: no user message yet, skipping")
            return

        user_content: str = str(user_msg.content)

        title: str | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                title = _llm_generate_title(user_text=user_content)
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
        db.commit()
        logger.info("title task: session %s → %r", session_id, title)
