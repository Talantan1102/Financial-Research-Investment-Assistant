"""L1 integration: generate_session_title 用真 LLMService + VCR cassette.

录制方式 (需要真 API key, by user manually):
  cd backend && LLM_MODE=live uv run pytest tests/integration/test_title_generation_l1.py \
    --record-mode=once -v
回放(CI 默认):
  cd backend && LLM_MODE=cassette uv run pytest tests/integration/test_title_generation_l1.py -v
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from app.models.chat import ChatMessage, ChatSession
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Cassette presence check — skip gracefully when cassette hasn't been recorded
# yet (CI safe, user records locally once then commits the cassette).
# ---------------------------------------------------------------------------

_CASSETTE_DIR = Path(__file__).parent.parent / "fixtures" / "cassettes" / "test_title_generation_l1"
_CASSETTE_PRESENT = _CASSETTE_DIR.exists() and any(_CASSETTE_DIR.glob("*.yaml"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_db(monkeypatch):
    """Swap out the real PG engine for an in-memory SQLite DB.

    Also override LLM_MODE to 'cassette' so the integration layer's
    autouse _force_llm_mode_mock fixture doesn't stomp us.
    """
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    monkeypatch.setenv("LLM_MODE", "cassette")

    engine = create_engine("sqlite:///:memory:")
    ChatSession.__table__.create(bind=engine)
    ChatMessage.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine)

    import app.tasks.title_generation as mod

    monkeypatch.setattr(mod, "_open_db_session", lambda: Session())
    return Session


# ---------------------------------------------------------------------------
# L1 test (skipped when cassette is absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _CASSETTE_PRESENT,
    reason=("L1 cassette not recorded yet; run with LLM_MODE=live --record-mode=once to record it"),
)
@pytest.mark.vcr()
def test_l1_real_llm_generates_meaningful_title(in_memory_db):
    """Real LLMService (via VCR cassette replay) must produce a meaningful title.

    Assertions:
    - title_source becomes "llm_generated"
    - title does NOT end with "..." (distinguishes LLM from fallback truncation)
    - title length is 5-25 chars (LLM 10-15 char target; allow some slack)
    - title contains a subject keyword from the conversation
    """
    Session = in_memory_db
    sid = uuid.uuid4()
    with Session() as sess:
        sess.add(ChatSession(id=sid, title="新对话", title_source="pending"))
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="user",
                content="帮我分析一下半导体行业的投资机会和风险",
                status="done",
            )
        )
        sess.add(
            ChatMessage(
                id=uuid.uuid4(),
                session_id=sid,
                role="assistant",
                content=(
                    "半导体行业当前处于周期底部，国产替代逻辑持续演绎。"
                    "核心机会在设备和材料国产化，风险在于美国出口管制升级和需求复苏不及预期。"
                    "建议关注中芯国际、北方华创等龙头标的。"
                ),
                status="done",
            )
        )
        sess.commit()

    from app.tasks.title_generation import generate_session_title

    generate_session_title(str(sid))

    with Session() as sess:
        s = sess.query(ChatSession).filter_by(id=sid).one()
        assert s.title_source == "llm_generated"
        # "..." suffix distinguishes fallback truncation from real LLM output
        assert "..." not in s.title, (
            f"Got fallback truncation title {s.title!r}, expected LLM-generated title"
        )
        # Real LLM should produce a concise title (10-15 char target, allow 5-25)
        assert 5 <= len(s.title) <= 25, (
            f"Title length {len(s.title)} outside expected range [5, 25]: {s.title!r}"
        )
        # Subject keyword coverage — at least one topic keyword must appear
        assert any(kw in s.title for kw in ("半导体", "投资", "机会", "风险", "芯片")), (
            f"No expected keyword found in title {s.title!r}"
        )
