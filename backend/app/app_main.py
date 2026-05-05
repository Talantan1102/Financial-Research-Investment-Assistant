import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from app.router import chat, research  # noqa: E402
from app.router.attachment_router import router as attachment_router  # noqa: E402
from app.router.auth_router import router as auth_router  # noqa: E402
from app.router.database_router import router as database_router  # noqa: E402
from app.router.knowledge_router import router as knowledge_router  # noqa: E402
from app.router.memory_router import router as memory_router  # noqa: E402
from app.router.monitoring_router import router as monitoring_router  # noqa: E402
from app.router.news_router import router as news_router  # noqa: E402
from app.router.session_router import router as session_router  # noqa: E402

# ---------------------------------------------------------------------------
# MonitoringService singleton
# ---------------------------------------------------------------------------
# The singleton is constructed lazily on first call so that test environments
# that only import app_main for the FastAPI `app` object don't pay the cost of
# building the full monitoring dependency graph.

_monitoring_service_singleton: Any = None

if TYPE_CHECKING:
    from app.services.monitoring.monitoring_service import MonitoringService


def get_monitoring_service() -> "MonitoringService":
    """Return (or lazily build) the MonitoringService singleton.

    Wiring order mirrors agent_graph.py:
      1. build_tushare_service()  — env-driven mock/real
      2. build_bocha_service_from_env()
      3. build_llm_service_from_env()
      4. build 5 SignalRules → SignalDetector
      5. build Writer (alert_writer mode)
      6. build EscalationCoordinator (with compiled research graph)
      7. build EmailNotifier (env-driven mock/real)
      8. assemble MonitoringService
    """
    global _monitoring_service_singleton
    if _monitoring_service_singleton is not None:
        return _monitoring_service_singleton

    from app.agents.writer import Writer
    from app.services.bocha_factory import build_bocha_service_from_env
    from app.services.cost_budget import CostBudget
    from app.services.monitoring.escalation import EscalationCoordinator
    from app.services.monitoring.monitoring_service import MonitoringService
    from app.services.monitoring.notifications.factory import build_email_notifier
    from app.services.monitoring.signal_detector import SignalDetector
    from app.services.monitoring.signal_rules.announcement import AnnouncementRule
    from app.services.monitoring.signal_rules.cash_flow import CashFlowRule
    from app.services.monitoring.signal_rules.defaults import DEFAULT_THRESHOLDS
    from app.services.monitoring.signal_rules.financial_ratio import FinancialRatioRule
    from app.services.monitoring.signal_rules.price_anomaly import PriceAnomalyRule
    from app.services.monitoring.signal_rules.shareholder_count import ShareholderCountRule
    from app.services.openai_client import build_llm_service_from_env
    from app.services.tushare_factory import build_tushare_service

    # DB path: backend/data/monitoring.sqlite (resolved from this file's location)
    # __file__ = backend/app/app_main.py → parents[0] = backend/app → parents[1] = backend
    db_path = Path(__file__).resolve().parent.parent / "data" / "monitoring.sqlite"

    # Ensure tables exist (idempotent)
    from app.scripts.init_monitoring_tables import init_monitoring_tables

    init_monitoring_tables(db_path)

    tushare = build_tushare_service()
    bocha = build_bocha_service_from_env()
    llm = build_llm_service_from_env()

    rules = [
        FinancialRatioRule(),
        CashFlowRule(),
        ShareholderCountRule(),
        AnnouncementRule(),
        PriceAnomalyRule(),
    ]
    detector = SignalDetector(rules=rules)

    writer = Writer(llm=llm)

    # Research graph for RED escalation — mirrors test_research_router_sse.py wiring
    from app.agents.analyst import Analyst
    from app.agents.base import Agent
    from app.agents.critic import Critic
    from app.agents.critic_subagents.conciseness import ConcisenessScorer
    from app.agents.critic_subagents.coverage import CoverageScorer
    from app.agents.critic_subagents.factuality import FactualityScorer
    from app.agents.critic_subagents.input_context_scorer import (
        InputContextAppropriatenessScorer,
    )
    from app.agents.critic_subagents.insight import InsightScorer
    from app.agents.critic_subagents.structure import StructureScorer
    from app.agents.data_collector import DataCollector
    from app.agents.research_planner import ResearchPlanner
    from app.orchestration.research_graph import build_research_graph
    from app.tools.get_financials import GetFinancialsTool
    from app.tools.get_news import GetNewsTool
    from app.tools.get_stock_quote import StockQuoteTool
    from app.tools.registry import ToolRegistry
    from app.tools.web_search import WebSearchTool

    registry = ToolRegistry()
    registry.register(StockQuoteTool(tushare=tushare))
    registry.register(GetFinancialsTool(tushare=tushare))
    registry.register(GetNewsTool(bocha=bocha))
    registry.register(WebSearchTool(bocha=bocha))

    planner = ResearchPlanner(llm=llm)
    collector = DataCollector(llm=llm, registry=registry)
    analyst = Analyst(llm=llm)
    research_writer = Writer(llm=llm)
    scorers: list[Agent] = [
        ConcisenessScorer(llm=llm),
        CoverageScorer(llm=llm),
        FactualityScorer(llm=llm),
        InsightScorer(llm=llm),
        StructureScorer(llm=llm),
        InputContextAppropriatenessScorer(llm=llm),  # 第 6 scorer (v0.8.4)
    ]
    critic = Critic(llm=llm, scorers=scorers)

    research_graph = build_research_graph(
        planner=planner,
        collector=collector,
        analyst=analyst,
        writer=research_writer,
        critic=critic,
    )

    daily_budget_cny = float(os.environ.get("MONITORING_DAILY_BUDGET_CNY", "10"))
    per_call_cap_cny = float(os.environ.get("MONITORING_ESCALATION_PER_CALL_CAP_CNY", "1"))
    max_concurrent = int(os.environ.get("MONITORING_ESCALATION_MAX_CONCURRENT", "1"))

    escalator = EscalationCoordinator(
        graph=research_graph,
        daily_budget=CostBudget(limit_cny=daily_budget_cny),
        per_call_cap_cny=per_call_cap_cny,
        concurrent_limit=max_concurrent,
    )

    email_notifier = build_email_notifier()

    recipients_raw = os.environ.get("MONITORING_ALERT_RECIPIENTS", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    _monitoring_service_singleton = MonitoringService(
        db_path=db_path,
        detector=detector,
        writer=writer,
        escalator=escalator,
        email_notifier=email_notifier,
        tushare=tushare,
        bocha=bocha,
        llm=llm,
        thresholds_per_rule=DEFAULT_THRESHOLDS,
        recipient_emails=recipients,
        max_concurrent_customers=5,
    )
    # Wire the factory into the router's DI override point so trigger_scan
    # can call get_monitoring_service() without importing app_main circularly.
    from app.router.monitoring_router import install_monitoring_service_factory

    install_monitoring_service_factory(lambda: _monitoring_service_singleton)
    return _monitoring_service_singleton


# ---------------------------------------------------------------------------
# App lifespan — scheduler startup (feature-flagged)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    """应用生命周期管理"""
    # 启动时执行
    logger.info("应用启动中...")

    # 创建所有数据表（如果不存在）— 移入 lifespan 避免 import-time PG 硬依赖
    # (v0.9.x feedback_serve_path_no_ci_coverage)。本地无 PG 时仅 warn,不阻塞启动。
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("PostgreSQL 表初始化完成")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "PostgreSQL 表初始化跳过(可能 PG 未启动): %s — "
            "依赖 PG 的 router(auth/news/session/...) 调用时会报错,但启动不阻塞",
            e,
        )

    # 初始化定时任务调度器并检查数据
    try:
        from app.service.scheduler_service import init_scheduler_and_check_data

        await init_scheduler_and_check_data()
        logger.info("定时任务调度器启动成功")
    except Exception as e:
        logger.error(f"定时任务调度器启动失败: {e}")

    # v0.8.3 — MonitoringService DI: always install the factory so that
    # POST /api/monitoring/runs works regardless of MONITORING_SCHEDULER_ENABLED.
    # The scheduler cron is still feature-flagged below.
    try:
        svc = get_monitoring_service()
        logger.info("MonitoringService singleton initialised and factory installed")
    except Exception as e:  # noqa: BLE001
        svc = None
        logger.warning("MonitoringService init failed (non-fatal): %s", e)

    # v0.8.3 — MonitoringScheduler (feature-flagged via MONITORING_SCHEDULER_ENABLED)
    # Default is "false" to keep test/CI environments safe.  Set to "true" in
    # production .env to activate the 16:30 + 17:00 cron scans.
    scheduler_enabled = os.environ.get("MONITORING_SCHEDULER_ENABLED", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    if scheduler_enabled and svc is not None:
        try:
            from app.services.monitoring.scheduler import MonitoringScheduler

            db_path_for_sched = (
                Path(__file__).resolve().parent.parent / "data" / "monitoring.sqlite"
            )

            def _load_active_ids() -> list[str]:
                with sqlite3.connect(db_path_for_sched) as conn:
                    return [
                        r[0]
                        for r in conn.execute(
                            "SELECT id FROM monitoring_customers WHERE enabled = 1"
                        )
                    ]

            def _load_disclosure_ids(d: Any) -> list[str]:  # noqa: ANN401
                # Simplified: return empty list.  Full impl queries tushare.get_disclosure_date.
                return []

            sched = MonitoringScheduler(svc, _load_active_ids, _load_disclosure_ids)
            sched.install()
            logger.info("MonitoringScheduler installed (daily 16:30, disclosure 17:00 CST)")
        except Exception as e:
            logger.error("MonitoringScheduler install failed (non-fatal): %s", e)
    else:
        logger.info("MonitoringScheduler disabled (MONITORING_SCHEDULER_ENABLED != true)")

    yield

    # 关闭时执行
    logger.info("应用关闭中...")
    try:
        from app.service.scheduler_service import get_scheduler_service

        scheduler = get_scheduler_service()
        scheduler.stop()
    except Exception as e:
        logger.error(f"定时任务调度器关闭失败: {e}")


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
app.include_router(auth_router)
app.include_router(session_router)
app.include_router(knowledge_router)
app.include_router(attachment_router)
app.include_router(memory_router)
app.include_router(database_router)
app.include_router(chat.router)
app.include_router(research.router)
app.include_router(news_router)
app.include_router(monitoring_router)


@app.get("/hello")
async def hello_world():
    """
    Simple hello world endpoint for network verification
    """
    return {"status": "success", "message": "Hello World! The API is working correctly."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
