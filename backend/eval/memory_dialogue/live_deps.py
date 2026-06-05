"""真实依赖 wiring — 仅 CLI(run_eval)用,测试不 import 本模块。

写侧:LLMExtractor + ConflictResolver judge + HierarchicalMemory(完整配置:
judge/Milvus 都接,对齐 mcp_server._common.build_memory_from_env 的口径,
而非 Celery tasks/memory.py 那套 judge=None 的简化 wiring——评估测的是
能力链的真实上限;若与生产 wiring 有差异,差异本身就是发现)。
读侧:archival_memory_search 绑定评估 user + LLMService 生成(balanced)/裁判(fast)。
每次跑评估新建独立 user,不污染真实用户数据。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from app.services.openai_client import build_llm_service_from_env
from sqlalchemy import text

logger = logging.getLogger(__name__)

GENERATE_PROMPT = """\
你是用户的金融研究助手。仅基于下面检索到的记忆回答用户问题;
记忆里没有的信息明确说"你没有跟我聊过这个,我没有这个信息",不要编造。

[检索到的记忆]
{facts}

[用户问题]
{question}
"""

JUDGE_PROMPT = """\
你是评估裁判。按下面的评分标准判断回答是否合格,只输出 yes 或 no。

[问题] {question}
[回答] {answer}
[评分标准] {rubric}
"""


class LiveGenerator:
    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm or build_llm_service_from_env()

    async def generate(self, query: str, facts: list[Any]) -> str:
        facts_text = "\n".join(f"- {f}" for f in facts) or "(空)"
        resp = self._llm.chat(
            prompt=GENERATE_PROMPT.format(facts=facts_text, question=query),
            tier="balanced",
        )
        return str(resp.content)


class LiveJudge:
    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm or build_llm_service_from_env()

    async def judge(self, question: str, answer: str, rubric: str) -> bool:
        resp = self._llm.chat(
            prompt=JUDGE_PROMPT.format(question=question, answer=answer, rubric=rubric),
            tier="fast",
        )
        return str(resp.content).strip().lower().startswith("yes")


def _fact_to_text(session_factory: Any, edge: Any) -> str:
    """把 ChatMemoryEdge 渲染成生成 prompt 可读的一行(带目标实体名)。"""
    s = session_factory()
    try:
        row = s.execute(
            text("SELECT entity_label FROM chat_memory_nodes WHERE node_id=:n"),
            {"n": str(edge.target_node_id)},
        ).first()
        target = row[0] if row else "?"
    finally:
        s.close()
    status = "当前有效" if (edge.valid_to is None and edge.invalidated_at is None) else "已作废"
    props = ", ".join(f"{k}={v}" for k, v in (edge.properties or {}).items())
    return (
        f"[{status}] {edge.rel_type} → {target} ({props}) "
        f"生效自 {edge.valid_from.date()}"
        + (f" 至 {edge.valid_to.date()}" if edge.valid_to is not None else "")
    )


class _BoundRetriever:
    """把 HierarchicalMemory.archival_memory_search 绑定到评估 user,产出文本化事实。"""

    def __init__(self, memory: Any, session_factory: Any, user_id: UUID) -> None:
        self._memory = memory
        self._session_factory = session_factory
        self._user_id = user_id

    async def search(self, query: str, k: int = 5) -> list[Any]:
        edges = await self._memory.archival_memory_search(self._user_id, query, k=k)
        return [_fact_to_text(self._session_factory, e) for e in edges]


async def build_live_runners() -> tuple[Any, Any]:
    """构造 (write_runner, read_runner):真 PG + 真抽取 + 真冲突消解 + 真检索 + 真裁判。"""
    import os

    from app.core.database import SessionLocal
    from app.memory.conflict_resolver import ConflictResolver
    from app.memory.extractor import LLMExtractor
    from app.memory.hierarchical import HierarchicalMemory
    from app.memory.path_b_runner import PathBRunner
    from app.services.embedding_factory import build_embedding_service_from_env

    from eval.memory_dialogue.read_phase import ReadPhaseRunner
    from eval.memory_dialogue.script_schema import ScriptSession
    from eval.memory_dialogue.write_phase import WritePhaseRunner

    llm = build_llm_service_from_env()
    embed = build_embedding_service_from_env()
    extractor = LLMExtractor(llm_client=llm)
    judge = ConflictResolver(llm_client=llm)

    milvus_client: Any = None
    try:
        from pymilvus import MilvusClient

        host = os.environ.get("MILVUS_HOST", "127.0.0.1")
        port = int(os.environ.get("MILVUS_PORT", "19530"))
        milvus_client = MilvusClient(uri=f"http://{host}:{port}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("eval live wiring: Milvus 不可用,向量路降级: %s", exc)

    memory = HierarchicalMemory(
        pg_session_factory=SessionLocal,
        age_executor=None,  # AGE 走 traverse 时才需要,冒烟先不接
        milvus_client=milvus_client,
        embed_service=embed,
        llm_extractor=extractor,
        llm_judge=judge,
    )
    path_b = PathBRunner(
        session_factory=SessionLocal,
        llm_extractor=extractor,
        archival_insert_fn=memory.archival_memory_insert,
    )

    # 评估专用 user + chat session(每次跑新建,不污染真实数据)
    user_id, chat_session_id = uuid4(), uuid4()
    setup = SessionLocal()
    try:
        setup.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, is_active) "
                "VALUES (:i, :u, :e, :p, true)"
            ),
            {
                "i": str(user_id),
                "u": f"eval-dialogue-{user_id.hex[:8]}",
                "e": f"eval-dialogue-{user_id.hex[:8]}@eval.local",
                "p": "x",
            },
        )
        setup.execute(
            text("INSERT INTO chat_sessions (id, user_id, title) VALUES (:s, :u, :t)"),
            {"s": str(chat_session_id), "u": str(user_id), "t": "memory-dialogue-eval"},
        )
        setup.commit()
    finally:
        setup.close()
    logger.info("eval live wiring: user=%s chat_session=%s", user_id, chat_session_id)

    async def extract_session(
        user_id: UUID, chat_session_id: UUID, ss: ScriptSession
    ) -> None:
        result = await path_b.run_for_session(
            chat_session_id, trigger_reason="session_closed"
        )
        logger.info(
            "path_b session %s: scanned=%s inserted=%s",
            ss.n,
            getattr(result, "episodes_scanned", "?"),
            getattr(result, "edges_inserted", "?"),
        )

    write_runner = WritePhaseRunner(
        session=SessionLocal(),
        user_id=user_id,
        chat_session_id=chat_session_id,
        extract_session=extract_session,
    )
    read_runner = ReadPhaseRunner(
        retriever=_BoundRetriever(memory, SessionLocal, user_id),
        generator=LiveGenerator(llm),
        judge=LiveJudge(llm),
    )
    return write_runner, read_runner
