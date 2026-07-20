import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

# 加载环境变量 — must run before any app.* import that reads POSTGRES_* /
# DASHSCOPE_* / TUSHARE_* etc. at module-load time (e.g. app.core.database).
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.core.async_database import (  # noqa: E402  (must follow load_dotenv)
    _sqlalchemy_async_pg_url,  # noqa: F401  compatibility re-export for workers/evals
    build_async_database,
)
from app.core.database import Base, engine  # noqa: E402  (must follow load_dotenv)
from app.router import chat as chat_router_module  # noqa: E402
from app.router import chats as chats_router_module  # noqa: E402
from app.router import escalate as escalate_router  # noqa: E402
from app.router import research  # noqa: E402
from app.router.attachment_router import router as attachment_router  # noqa: E402
from app.router.auth_router import router as auth_router  # noqa: E402
from app.router.knowledge_router import router as knowledge_router  # noqa: E402
from app.router.memory_router import router as memory_router  # noqa: E402  (C.5)
from app.router.monitoring_router import router as monitoring_router  # noqa: E402
from app.router.observability_router import router as observability_router  # noqa: E402
from app.router.persona_router import router as persona_router  # noqa: E402  (persona-ui)
from app.router.portfolio_router import router as portfolio_router  # noqa: E402  (v1.0)
from app.router.reports import router as reports_router  # noqa: E402  (v0.9.x)
from app.router.run_observability import router as run_observability_router  # noqa: E402
from app.router.run_sessions import router as run_sessions_router  # noqa: E402
from app.router.runs import router as runs_router  # noqa: E402
from app.router.tenants import router as tenants_router  # noqa: E402
from app.scripts.migrate_phase3_execution_schema import (  # noqa: E402
    is_fresh_application_schema_connection,
    verify_run_control_schema_connection,
)
from app.services.chat_session_repo import ChatSessionRepo  # noqa: E402
from app.services.mcp_client import MCPClient  # noqa: E402
from app.services.run_escalation_repo import RunEscalationRepo  # noqa: E402
from app.tasks.celery_app import celery_app  # noqa: E402, F401  (autodiscover trigger)

# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------


def _initialize_postgres_schema(database_engine: Engine | None = None) -> bool:
    """Create a truly fresh schema, or read-only verify an existing one."""
    target_engine = database_engine or engine
    try:
        import app.models as _models  # noqa: F401  ensure all models registered to Base

        # Fresh detection and initialization are one transaction-scoped critical
        # section. The operator entrypoint takes the same outer lock before its
        # Phase 2/3 maintenance locks, so startup and maintenance cannot interleave.
        with target_engine.begin() as connection:
            connection.execute(text("SELECT set_config('lock_timeout', '5000ms', true)"))
            connection.execute(text("SELECT set_config('statement_timeout', '300000ms', true)"))
            connection.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('run_control_schema_maintenance', 0))"
                )
            )
            fresh_schema = is_fresh_application_schema_connection(connection)
            if fresh_schema:
                Base.metadata.create_all(bind=connection)
                verify_run_control_schema_connection(connection)
                logger.info("Fresh PostgreSQL schema initialized and verified")
            else:
                verify_run_control_schema_connection(connection)
                logger.info("Existing PostgreSQL schema verified without startup DDL")
    except OperationalError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        postgres_unavailable = (
            sqlstate is None or str(sqlstate).startswith("08") or sqlstate == "57P03"
        )
        if not postgres_unavailable:
            logger.exception("PostgreSQL schema initialization failed; refusing partial startup")
            raise
        logger.warning(
            "PostgreSQL unavailable; database-backed routes will fail until it recovers: %s",
            exc,
        )
        return False
    except Exception:
        logger.exception("PostgreSQL schema initialization failed; refusing partial startup")
        raise
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    """应用生命周期管理"""
    # 启动时执行
    logger.info("应用启动中...")

    # C5: fail-fast if JWT secret is unset / a known-insecure default. Done here
    # (serving path) rather than at import so tests/eval/CLI are unaffected.
    from app.core.security import assert_jwt_secret_configured

    assert_jwt_secret_configured()

    _initialize_postgres_schema()

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

        # Plan 3: instrumentation tables (retrieval_logs / retrieval_feedback)
        c5_instr_migration = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "migrations"
            / "2026-05-11-c5-plan3-instrumentation.sql"
        )
        if c5_instr_migration.exists():
            instr_sql = c5_instr_migration.read_text(encoding="utf-8")
            with engine.begin() as conn:
                conn.execute(_sql_text(instr_sql))
            logger.info("C.5 Plan 3 instrumentation SQL migration applied")

        # Plan 4: mcp_tool_call_log (spec § 6 周报 SQL data source)
        c5_plan4_migration = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "migrations"
            / "2026-05-11-c5-plan4-mcp-tool-call-log.sql"
        )
        if c5_plan4_migration.exists():
            mcp_sql = c5_plan4_migration.read_text(encoding="utf-8")
            with engine.begin() as conn:
                conn.execute(_sql_text(mcp_sql))
            logger.info("C.5 Plan 4 mcp_tool_call_log SQL migration applied")
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

    # === chat additions(chatloop 引擎)===
    # 老 supervisor 图退役(Phase 7):chat 路径已完全跑在 chatloop ToolLoop 上,
    # 由 Celery worker(app.tasks.chat_runner)驱动,不再在 web lifespan 构建
    # LangGraph chat 图,也不再 wire PG checkpointer(turn 原子语义,checkpoint 退役)。

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

    # 3. Shared async database for v1 RunService and legacy async repositories.
    try:
        app.state.db_async_engine, app.state.async_session_factory = build_async_database()
        logger.info("共享 async database 初始化完成")
    except Exception as e:  # noqa: BLE001
        app.state.db_async_engine = None
        app.state.async_session_factory = None
        logger.warning("共享 async database 初始化跳过: %s", e)

    # ChatSessionRepo consumes the shared factory, but its own failure must not
    # disable RunService's database dependency.
    try:
        if app.state.async_session_factory is None:
            raise RuntimeError("async_session_factory not initialized")
        app.state.chat_session_repo = ChatSessionRepo(
            session_factory=app.state.async_session_factory
        )
        logger.info("ChatSessionRepo 初始化完成")
    except Exception as e:  # noqa: BLE001
        app.state.chat_session_repo = None
        logger.warning("ChatSessionRepo 初始化跳过: %s", e)

    try:
        if app.state.async_session_factory is None:
            raise RuntimeError("async_session_factory not initialized")
        app.state.run_escalation_repo = RunEscalationRepo(
            session_factory=app.state.async_session_factory
        )
    except Exception as e:  # noqa: BLE001
        app.state.run_escalation_repo = None
        logger.warning("RunEscalationRepo init skipped: %s", e)

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

    # 7. Plan 2 Task 7: Redis async client(GET /chat/stream/{tid} XREAD + Celery worker
    #    push events 共用一条 conn pool).无 Redis 时 get_redis_async DI 返 None,
    #    POST /chat 自动 graceful degrade 到 Plan 1 inline SSE path.
    try:
        import redis.asyncio as _redis_async

        _redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        app.state.redis_async = _redis_async.Redis.from_url(_redis_url, decode_responses=False)
        # Fail-fast ping — 如果 Redis 不可达,标 None,Plan 2 path 自动 fallback
        await app.state.redis_async.ping()
        logger.info("Plan 2 Redis async client 已 wire: %s", _redis_url)
    except Exception as e:  # noqa: BLE001
        app.state.redis_async = None
        logger.warning("Plan 2 Redis async client 初始化跳过: %s", e)

    # 8. (退役)Chat graph singleton —— 老 supervisor 图已退役;chat 现在由 Celery
    #    worker(app.tasks.chat_runner)按 turn 懒构 chatloop 组件(MCP chat_tools
    #    subprocess + HeavySingletons),web 进程不再持有 chat 图。

    # 9. Persona Editable UI Plan Task 6 — 一次性 backfill (幂等)
    # SessionLocal: app.core.database.SessionLocal (sync session factory, used by Celery tasks)
    # Must run before any code path that reads persona items (Task 17 wires agent path).
    from sqlalchemy.exc import ProgrammingError as _PgProgrammingError

    try:
        from app.core.database import SessionLocal
        from app.scripts.migrate_persona_blob_to_items import migrate_all

        stats = migrate_all(SessionLocal)
        logger.info("persona migration stats: %s", stats)
    except _PgProgrammingError:
        # 表不存在等 schema 问题 — silent fail 会让 agent 看到空 persona, 标 ERROR
        logger.exception(
            "persona migration startup hook 失败 (schema 问题, 检查 create_all 是否跑过)",
        )
    except Exception:
        # 运行时错误 (DB down 等) — 不阻塞启动, 但保留 traceback 便于诊断
        logger.exception("persona migration startup hook 失败 (运行时错误)")

    # === title_source backfill (2026-05-17): 一次性 idempotent migration ===
    try:
        from app.scripts.backfill_title_source import backfill

        n_backfilled = backfill(engine)
        if n_backfilled:
            logger.info("backfilled %d old chat_sessions title_source=llm_generated", n_backfilled)
    except Exception:  # noqa: BLE001
        logger.exception("title_source backfill failed (non-fatal)")

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
    if getattr(app.state, "db_async_engine", None) is not None:
        try:
            await app.state.db_async_engine.dispose()
            logger.info("共享 async database 已关闭")
        except Exception as e:  # noqa: BLE001
            logger.warning("共享 async database 关闭失败: %s", e)
    if getattr(app.state, "redis_async", None) is not None:
        try:
            await app.state.redis_async.aclose()
            logger.info("Plan 2 Redis async client 已关闭")
        except Exception as e:  # noqa: BLE001
            logger.warning("Plan 2 Redis async client 关闭失败: %s", e)


app = FastAPI(
    title="行业信息助手 API",
    description="基于 AI Agent 的行业信息助手系统",
    version="2.0.0",
    lifespan=lifespan,
)

# 添加 CORS 中间件
# C38: `Access-Control-Allow-Origin: *` + credentials is spec-invalid (browsers
# reject it) and a forward-looking hole. Drive origins from CORS_ORIGINS env
# (comma-separated); default to the local dev frontends. Never combine "*" with
# credentials.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://localhost:3000",
]
if "*" in _cors_origins:
    raise RuntimeError(
        "CORS_ORIGINS must not contain '*' while allow_credentials=True "
        "(invalid per the CORS spec); list explicit origins."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
app.include_router(tenants_router)
app.include_router(runs_router)
app.include_router(run_sessions_router)
app.include_router(chat_router_module.router)  # v0.9 — /api/v0/chat (SSE streaming)
app.include_router(chats_router_module.router)  # v0.9 — /api/v0/chats (CRUD)
app.include_router(escalate_router.router)  # v0.9 — /api/v0/chat/escalate (confirmed packet)
app.include_router(escalate_router.research_router)  # v1 — tenant-scoped research escalation
app.include_router(memory_router)  # C.5 — /api/v0/memory (cross-session memory page)
app.include_router(persona_router)  # persona-ui — /api/v0/persona (Tier 1 persona items)
app.include_router(observability_router)  # chatloop 可观测性(只读聚合)
app.include_router(run_observability_router)


# C39: chats router's get_repo override is registered below alongside the other
# Plan-3 overrides, via _override_or_fallback so a failed PG init raises a clear
# RuntimeError instead of leaking None (typed ChatSessionRepo) into handlers.


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

# C43: escalate.get_escalation_record_repo is now re-exported from chat, so the
# single chat_get_repo override below covers both routers — no esc_get_repo dup.
from app.router.escalate import (
    get_research_agent as esc_get_agent,
)
from app.router.escalate import (
    get_research_report_repo as esc_get_rpt_repo,
)

app.dependency_overrides[chats_router_module.get_repo] = _override_or_fallback("chat_session_repo")
app.dependency_overrides[chat_get_extractor] = _override_or_fallback("escalation_extractor")
app.dependency_overrides[chat_get_repo] = _override_or_fallback("escalation_record_repo")
app.dependency_overrides[esc_get_agent] = _override_or_fallback("research_agent")
app.dependency_overrides[esc_get_chat_repo] = _override_or_fallback("run_escalation_repo")
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
