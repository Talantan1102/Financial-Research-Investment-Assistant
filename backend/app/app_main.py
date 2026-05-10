import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 加载环境变量 — must run before any app.* import that reads POSTGRES_* /
# DASHSCOPE_* / TUSHARE_* etc. at module-load time (e.g. app.core.database).
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.core.database import Base, engine  # noqa: E402  (must follow load_dotenv)
from app.orchestration.postgres_checkpointer import (  # noqa: E402
    PostgresCheckpointerConfig,
    make_postgres_checkpointer,
)
from app.router import chat as chat_router_module  # noqa: E402
from app.router import chats as chats_router_module  # noqa: E402
from app.router import escalate as escalate_router  # noqa: E402
from app.router import research  # noqa: E402
from app.router.attachment_router import router as attachment_router  # noqa: E402
from app.router.auth_router import router as auth_router  # noqa: E402
from app.router.knowledge_router import router as knowledge_router  # noqa: E402
from app.router.monitoring_router import router as monitoring_router  # noqa: E402
from app.router.portfolio_router import router as portfolio_router  # noqa: E402  (v1.0)
from app.router.reports import router as reports_router  # noqa: E402  (v0.9.x)
from app.services.chat_session_repo import ChatSessionRepo  # noqa: E402
from app.services.mcp_client import MCPClient  # noqa: E402
from app.tasks.celery_app import celery_app  # noqa: E402, F401  (autodiscover trigger)

# ---------------------------------------------------------------------------
# Helper: build psycopg3-compatible async DATABASE_URL from env vars
# ---------------------------------------------------------------------------


def _async_pg_url() -> str:
    """Return a psycopg3-compatible conninfo URI (plain postgresql://).

    Note: psycopg3 / psycopg_pool use the libpq URI format (postgresql://)
    NOT the SQLAlchemy driver format (postgresql+psycopg://).  The +psycopg
    prefix is SQLAlchemy-only and is rejected by psycopg_pool.AsyncConnectionPool.
    """
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres123")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "industry_assistant")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def _sqlalchemy_async_pg_url() -> str:
    """Return a SQLAlchemy async engine URL (postgresql+psycopg://).

    SQLAlchemy's create_async_engine requires the +psycopg driver suffix
    to select the psycopg3 backend over psycopg2.
    """
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres123")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "industry_assistant")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    """应用生命周期管理"""
    # 启动时执行
    logger.info("应用启动中...")

    # 创建所有数据表（如果不存在）— 移入 lifespan 避免 import-time PG 硬依赖
    # (v0.9.x feedback_serve_path_no_ci_coverage)。本地无 PG 时仅 warn,不阻塞启动。
    # 显式 import models 包(barrel)以确保所有 model 注册到 Base.metadata —
    # 例如 ResearchReport 没有任何 router 直接 import,只能靠 barrel 拉入。
    try:
        import app.models as _models  # noqa: F401  ensure all models registered to Base

        Base.metadata.create_all(bind=engine)
        logger.info("PostgreSQL 表初始化完成")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "PostgreSQL 表初始化跳过(可能 PG 未启动): %s — "
            "依赖 PG 的 router(auth/news/session/...) 调用时会报错,但启动不阻塞",
            e,
        )

    # C.5 cross-session memory: apply SQL migration(partial index / GIN / AGE 图).
    # 幂等(IF NOT EXISTS), PG 不可用时只 warn 不阻塞启动(serve path 不强依赖 c5).
    # path 用 Path(__file__).resolve().parents[1] 锚 backend/, 不依赖 cwd
    # (sediment: feedback_path_resolution_in_plans.md).
    try:
        from pathlib import Path

        from sqlalchemy import text as _sql_text

        c5_migration = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "migrations"
            / "2026-05-11-c5-memory-schema.sql"
        )
        if c5_migration.exists():
            sql = c5_migration.read_text(encoding="utf-8")
            with engine.begin() as conn:
                conn.execute(_sql_text(sql))
            logger.info("C.5 memory SQL migration applied")

        # Plan 2A: pending_milvus_inserts outbox table
        c5_outbox_migration = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "migrations"
            / "2026-05-11-c5-pending-milvus-outbox.sql"
        )
        if c5_outbox_migration.exists():
            outbox_sql = c5_outbox_migration.read_text(encoding="utf-8")
            with engine.begin() as conn:
                conn.execute(_sql_text(outbox_sql))
            logger.info("C.5 Plan 2A outbox SQL migration applied")
    except Exception as e:  # noqa: BLE001
        logger.warning("C.5 memory SQL migration skipped: %s", e)

    # C.5 Milvus collection ensure(幂等). Milvus 不可用时只 warn.
    try:
        milvus_host = os.getenv("MILVUS_HOST", "127.0.0.1")
        milvus_port = int(os.getenv("MILVUS_PORT", "19530"))
        from app.memory.milvus_setup import ensure_chat_memory_edge_collection

        ensure_chat_memory_edge_collection(host=milvus_host, port=milvus_port)
        logger.info("C.5 Milvus chat_memory_edge_embeddings ensured")
    except Exception as e:  # noqa: BLE001
        logger.warning("C.5 Milvus collection ensure skipped: %s", e)

    # 初始化定时任务调度器并检查数据
    try:
        from app.service.scheduler_service import init_scheduler_and_check_data

        await init_scheduler_and_check_data()
        logger.info("定时任务调度器启动成功")
    except Exception as e:
        logger.error(f"定时任务调度器启动失败: {e}")

    # === v0.9 chat additions ===

    # 1. PG checkpointer for LangGraph (psycopg3 async pool)
    _chat_checkpointer_ctx = None
    try:
        conninfo = _async_pg_url()
        app.state.chat_checkpointer = await make_postgres_checkpointer(
            PostgresCheckpointerConfig(conninfo=conninfo)
        )
        logger.info("LangGraph PG checkpointer 初始化完成")
    except Exception as e:  # noqa: BLE001
        app.state.chat_checkpointer = None
        logger.warning("LangGraph PG checkpointer 初始化跳过: %s", e)

    # 2. MCP client subprocess — use as context manager
    _mcp_ctx = MCPClient.from_subprocess()
    try:
        app.state.mcp_client = await _mcp_ctx.__aenter__()
        app.state._mcp_ctx = _mcp_ctx
        logger.info("MCP client 启动完成")
    except Exception as e:  # noqa: BLE001
        app.state.mcp_client = None
        app.state._mcp_ctx = None
        logger.warning("MCP client 启动跳过: %s", e)

    # 3. ChatSessionRepo (no existing async_session_factory — create one inline)
    try:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        _chat_engine_url = _sqlalchemy_async_pg_url()  # SQLAlchemy needs +psycopg prefix
        app.state.chat_async_engine = create_async_engine(_chat_engine_url, future=True)
        _factory = async_sessionmaker(app.state.chat_async_engine, expire_on_commit=False)
        # Store factory on app.state so escalate deps (T11) can reuse it
        app.state.async_session_factory = _factory
        app.state.chat_session_repo = ChatSessionRepo(session_factory=_factory)
        logger.info("ChatSessionRepo 初始化完成")
    except Exception as e:  # noqa: BLE001
        app.state.async_session_factory = None
        app.state.chat_session_repo = None
        logger.warning("ChatSessionRepo 初始化跳过: %s", e)

    # === Plan 3 escalate deps ===

    # 4. EscalationExtractor (needs LLMService)
    try:
        from app.agents.escalation_extractor import EscalationExtractor
        from app.services.openai_client import build_llm_service_from_env

        llm_for_extraction = build_llm_service_from_env()
        app.state.escalation_extractor = EscalationExtractor(llm=llm_for_extraction)
        logger.info("EscalationExtractor 初始化完成")
    except Exception as e:  # noqa: BLE001
        app.state.escalation_extractor = None
        logger.warning("EscalationExtractor 初始化跳过: %s", e)

    # 5. EscalationRecordRepo + ResearchReportRepo (reuse async_session_factory)
    try:
        from app.services.escalation_record_repo import EscalationRecordRepo
        from app.services.research_report_repo import ResearchReportRepo

        if getattr(app.state, "async_session_factory", None) is not None:
            app.state.escalation_record_repo = EscalationRecordRepo(
                session_factory=app.state.async_session_factory,
            )
            app.state.research_report_repo = ResearchReportRepo(
                session_factory=app.state.async_session_factory,
            )
            logger.info("EscalationRecordRepo + ResearchReportRepo 初始化完成")
        else:
            app.state.escalation_record_repo = None
            app.state.research_report_repo = None
            logger.warning(
                "async_session_factory not in app.state; "
                "EscalationRecordRepo / ResearchReportRepo 未初始化"
            )
    except Exception as e:  # noqa: BLE001
        app.state.escalation_record_repo = None
        app.state.research_report_repo = None
        logger.warning("EscalationRecordRepo / ResearchReportRepo 初始化跳过: %s", e)

    # 6. ResearchAgent — stub None; escalate router handles None gracefully
    try:
        if not hasattr(app.state, "research_agent"):
            app.state.research_agent = None
    except Exception as e:  # noqa: BLE001
        app.state.research_agent = None
        logger.warning("research_agent 初始化跳过: %s", e)

    yield

    # 关闭时执行
    logger.info("应用关闭中...")
    try:
        from app.service.scheduler_service import get_scheduler_service

        scheduler = get_scheduler_service()
        scheduler.stop()
    except Exception as e:
        logger.error(f"定时任务调度器关闭失败: {e}")

    # === v0.9 chat shutdown ===
    if getattr(app.state, "_mcp_ctx", None) is not None:
        try:
            await app.state._mcp_ctx.__aexit__(None, None, None)
            logger.info("MCP client 已关闭")
        except Exception as e:  # noqa: BLE001
            logger.warning("MCP client 关闭失败: %s", e)
    if getattr(app.state, "chat_async_engine", None) is not None:
        try:
            await app.state.chat_async_engine.dispose()
            logger.info("ChatSessionRepo async engine 已关闭")
        except Exception as e:  # noqa: BLE001
            logger.warning("ChatSessionRepo async engine 关闭失败: %s", e)


app = FastAPI(
    title="行业信息助手 API",
    description="基于 AI Agent 的行业信息助手系统",
    version="2.0.0",
    lifespan=lifespan,
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有源，生产环境中应该设置具体的源
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有头
)

# 注册路由
# v0.9.x — chat / database / news / memory / session 已不再 served (frontend 已删
# 对应路由,routers 文件保留但不 include).参考 Task 8 spec.
app.include_router(auth_router)
app.include_router(knowledge_router)
app.include_router(attachment_router)
app.include_router(research.router)
app.include_router(monitoring_router)
app.include_router(reports_router)  # v0.9.x — research reports CRUD
app.include_router(portfolio_router)  # v1.0 — portfolio data model + onboarding
app.include_router(chat_router_module.router)  # v0.9 — /api/v0/chat (SSE streaming)
app.include_router(chats_router_module.router)  # v0.9 — /api/v0/chats (CRUD)
app.include_router(escalate_router.router)  # v0.9 — /api/v0/chat/escalate (confirmed packet)


# Dependency override: chats router's get_repo reads from app.state at request time
def _get_chat_session_repo() -> ChatSessionRepo:
    return app.state.chat_session_repo


app.dependency_overrides[chats_router_module.get_repo] = _get_chat_session_repo


# === Plan 3 dependency overrides (T11) ===


def _override_or_fallback(state_attr: str):
    """Return a zero-arg callable that yields app.state.<state_attr>, or raises if None."""

    def _factory():
        val = getattr(app.state, state_attr, None)
        if val is None:
            raise RuntimeError(f"app.state.{state_attr} not initialized")
        return val

    return _factory


from app.router.chat import (  # noqa: E402
    get_escalation_extractor as chat_get_extractor,
)
from app.router.chat import (
    get_escalation_record_repo as chat_get_repo,
)
from app.router.escalate import (  # noqa: E402
    get_chat_session_repo as esc_get_chat_repo,
)
from app.router.escalate import (
    get_escalation_record_repo as esc_get_repo,
)
from app.router.escalate import (
    get_research_agent as esc_get_agent,
)
from app.router.escalate import (
    get_research_report_repo as esc_get_rpt_repo,
)

app.dependency_overrides[chat_get_extractor] = _override_or_fallback("escalation_extractor")
app.dependency_overrides[chat_get_repo] = _override_or_fallback("escalation_record_repo")
app.dependency_overrides[esc_get_repo] = _override_or_fallback("escalation_record_repo")
app.dependency_overrides[esc_get_agent] = _override_or_fallback("research_agent")
app.dependency_overrides[esc_get_chat_repo] = _override_or_fallback("chat_session_repo")
app.dependency_overrides[esc_get_rpt_repo] = _override_or_fallback("research_report_repo")


@app.get("/hello")
async def hello_world():
    """
    Simple hello world endpoint for network verification
    """
    return {"status": "success", "message": "Hello World! The API is working correctly."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
