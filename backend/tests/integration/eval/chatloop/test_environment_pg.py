from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.memory.instrumentation import log_retrieval_hit, log_user_reject
from app.memory.milvus_outbox import enqueue_milvus_insert
from app.models.run import Run, RunEvent, RunMessage, RunSession
from app.models.run_scheduling import RunOutbox, RunTenantScheduling
from app.models.user import User
from app.models.watchlist import WatchlistAudit
from app.services.run_service import CreateRunCommand, RunService
from app.services.trace_models import MCPToolCallLog
from eval.chatloop.case_loader import load_catalog
from eval.chatloop.environment import CaseEnvironmentManager, EvalActor
from eval.chatloop.scenario import Scenario
from eval.chatloop.sut_runner import DurableRunHttpTransport, SqlOutcomeCollector
from sqlalchemy import func, select, text


def _case(case_id: str):
    return load_catalog().by_id(case_id)


@pytest.fixture
def environment_manager(disposable_eval_runtime):
    async def cleanup_memory_mirrors(_edge_ids, _node_ids) -> None:
        return None

    return CaseEnvironmentManager(
        disposable_eval_runtime,
        external_memory_cleanup=cleanup_memory_mirrors,
    )


@pytest.mark.asyncio
async def test_shared_database_is_rejected_for_strict_eval(pg_async_session_factory) -> None:
    with pytest.raises(RuntimeError, match="DisposableEvalRuntime"):
        CaseEnvironmentManager(pg_async_session_factory)


@pytest.mark.asyncio
async def test_each_trial_gets_unique_users_and_clean_state(environment_manager) -> None:
    first = await environment_manager.prepare(_case("B4-01"), trial_index=0)
    second = await environment_manager.prepare(_case("B4-01"), trial_index=1)

    assert first.primary_user_id != second.primary_user_id
    assert first.paper_account_id != second.paper_account_id
    assert first.tenant_id != second.tenant_id
    assert first.actor("creator").membership_role == "owner"
    assert await first.snapshot() == first.expected_initial_snapshot
    assert await second.snapshot() == second.expected_initial_snapshot
    assert str(first.primary_user_id) in first.manifest.user_ids
    assert str(first.paper_account_id) in first.manifest.paper_account_ids
    assert first.expected_initial_snapshot["funds"] == {
        "available_cash": "620000.00",
        "frozen_cash": "80000.00",
    }
    assert len(first.manifest.paper_cash_ledger_ids) == 2

    await first.cleanup()
    await second.cleanup()


@pytest.mark.asyncio
async def test_admin_actor_has_no_creator_financial_visibility(environment_manager) -> None:
    env = await environment_manager.prepare(_case("B4-09"), trial_index=0)

    assert env.actor("tenant_admin").user_id != env.actor("creator").user_id
    assert env.actor("tenant_admin").token
    assert env.actor("requester") == env.actor("tenant_admin")
    assert env.actor("target_user") == env.actor("other_user")
    assert (await env.snapshot(actor_name="tenant_admin"))["paper_accounts"]["count"] == 0

    await env.cleanup()


@pytest.mark.asyncio
async def test_structured_state_is_seeded_for_the_correct_actors(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B5-01"), trial_index=0)

    creator = await env.snapshot(actor_name="creator")
    other = await env.snapshot(actor_name="other_user")
    assert creator["watchlist"]["codes"] == ["600036.SH", "600519.SH"]
    assert creator["positions"]["codes"] == ["600036.SH"]
    assert other["watchlist"]["codes"] == ["300750.SZ"]
    assert other["positions"]["count"] == 0
    assert len(env.manifest.watchlist_item_ids) == 3
    assert len(env.manifest.position_ids) == 1
    creator_by_code = {row["ts_code"]: row for row in creator["watchlist"]["records"]}
    assert creator_by_code["600519.SH"] == {
        "id": creator_by_code["600519.SH"]["id"],
        "ts_code": "600519.SH",
        "name": "贵州茅台",
        "note": "长拿",
        "monitoring_enabled": True,
    }
    assert creator_by_code["600036.SH"]["name"] == "招商银行"
    assert creator_by_code["600036.SH"]["note"] is None
    assert creator_by_code["600036.SH"]["monitoring_enabled"] is False
    other_user_id = env.actor("other_user").user_id
    assert other_user_id is not None
    async with disposable_eval_async_session_factory() as session:
        audit_count = await session.scalar(
            select(func.count())
            .select_from(WatchlistAudit)
            .where(WatchlistAudit.user_id.in_([env.primary_user_id, other_user_id]))
        )
    assert audit_count == 0

    await env.cleanup()


@pytest.mark.asyncio
async def test_b402_seed_matches_every_approved_position_field(environment_manager) -> None:
    env = await environment_manager.prepare(_case("B4-02"), trial_index=0)
    records = {
        row["name"]: {
            "quantity": row["quantity"],
            "avg_cost": row["avg_cost"],
            "last_quote_price": row["last_quote_price"],
            "market_value": row["market_value"],
        }
        for row in (await env.snapshot())["positions"]["records"]
    }

    assert records == {
        "贵州茅台": {
            "quantity": 100,
            "avg_cost": "1500.00",
            "last_quote_price": "1560.00",
            "market_value": "156000.00",
        },
        "招商银行": {
            "quantity": 2000,
            "avg_cost": "36.00",
            "last_quote_price": "40.00",
            "market_value": "80000.00",
        },
        "宁德时代": {
            "quantity": 300,
            "avg_cost": "210.00",
            "last_quote_price": "200.00",
            "market_value": "60000.00",
        },
    }

    await env.cleanup()


@pytest.mark.asyncio
async def test_stateful_collector_accepts_dynamic_trial_actor(
    monkeypatch: pytest.MonkeyPatch,
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    monkeypatch.delenv("CHATLOOP_EVAL_USER_ID", raising=False)
    env = await environment_manager.prepare(_case("B4-01"), trial_index=0)
    actor = env.actor("creator")
    collector = SqlOutcomeCollector(disposable_eval_async_session_factory, actor=actor)
    scenario = Scenario(
        case_id="dynamic-trial-paper-setup",
        category="stateful",
        user_input="seed",
        expected={"outcome": {"type": "paper_trading"}},
        bucket="交易",
        difficulty="直球",
    )

    await collector.prepare(
        user_id=str(actor.user_id),
        scenario=scenario,
        sample_key="dynamic:0",
    )
    with pytest.raises(RuntimeError, match="trial actor"):
        await collector.prepare(
            user_id=str(env.actor("other_user").user_id),
            scenario=scenario,
            sample_key="dynamic:1",
        )

    await env.cleanup()


@pytest.mark.asyncio
async def test_seed_uses_trade_position_and_current_memory_tables(environment_manager) -> None:
    position_env = await environment_manager.prepare(_case("B4-03"), trial_index=0)
    position = (await position_env.snapshot())["positions"]["records"][0]
    assert position["quantity"] == 100
    assert position["total_cost"] == "150000.00"
    assert position["realized_pnl"] == "1000.00"
    assert position["last_quote_price"] == "1560.00"
    assert position["market_value"] == "156000.00"
    assert len(position_env.manifest.trade_ids) == 2

    memory_env = await environment_manager.prepare(_case("B4-06"), trial_index=0)
    memory = (await memory_env.snapshot())["memory"]
    assert [row["text"] for row in memory["records"]] == [
        "2025年12月：长期看好新能源。",
        "2026年5月：库存压力没解决前暂时不看新能源。",
    ]
    assert len(memory_env.manifest.memory_episode_ids) == 2
    assert len(memory_env.manifest.memory_edge_ids) == 2

    sellable_env = await environment_manager.prepare(_case("B6-02"), trial_index=0)
    sellable_snapshot = await sellable_env.snapshot()
    assert sellable_snapshot["positions"]["records"][0]["quantity"] == 500
    assert sellable_snapshot["orders"]["count"] == 0
    assert len(sellable_env.manifest.holding_lot_ids) == 2
    assert len(sellable_env.manifest.support_order_ids) == 2
    assert len(sellable_env.manifest.fill_ids) == 2
    assert len(sellable_env.manifest.match_pass_ids) == 2
    assert len(sellable_env.manifest.trade_ids) == 2
    assert len(sellable_env.manifest.paper_cash_ledger_ids) > 2

    await position_env.cleanup()
    await memory_env.cleanup()
    await sellable_env.cleanup()


@pytest.mark.asyncio
async def test_partial_order_seed_uses_real_settlement_and_fee_reservation(
    environment_manager,
) -> None:
    env = await environment_manager.prepare(_case("B7-01"), trial_index=0)
    snapshot = await env.snapshot()

    assert snapshot["orders"]["latest"]["status"] == "partially_filled"
    assert snapshot["orders"]["latest"]["filled_quantity"] == 300
    assert snapshot["fills"]["count"] == 1
    assert snapshot["fills"]["records"][0]["price"] == "11.18"
    assert snapshot["funds"]["frozen_cash"] == "7840.08"
    assert len(env.manifest.match_pass_ids) == 1
    assert len(env.manifest.trade_ids) == 1
    assert len(env.manifest.holding_lot_ids) == 1

    await env.cleanup()


@pytest.mark.asyncio
async def test_disposable_database_retains_append_only_audits_until_database_drop(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B5-03"), trial_index=0)
    creator_id = env.actor("creator").user_id
    assert creator_id is not None
    assert len(env.manifest.watchlist_audit_ids) == 4

    await env.cleanup()

    async with disposable_eval_async_session_factory() as session:
        audits = list(
            (
                await session.scalars(
                    WatchlistAudit.__table__.select().where(WatchlistAudit.user_id == creator_id)
                )
            ).all()
        )
        assert len(audits) == 4
        assert await session.get(User, creator_id) is not None
    assert str(creator_id) in env.manifest.retained_user_ids


@pytest.mark.asyncio
async def test_every_stateful_catalog_case_can_be_prepared_and_cleaned(
    environment_manager,
) -> None:
    cases = [
        case
        for case in load_catalog().cases
        if case.case_id.startswith("B4-") or set(case.initial_state.business_state) != {"state_zh"}
    ]
    assert len(cases) >= 50

    for case in cases:
        env = await environment_manager.prepare(case, trial_index=0)
        try:
            assert await env.snapshot() == env.expected_initial_snapshot, case.case_id
        finally:
            await env.cleanup()


@pytest.mark.asyncio
async def test_cleanup_deletes_only_manifest_rows(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    sentinel_id = uuid4()
    async with disposable_eval_async_session_factory() as session, session.begin():
        session.add(
            User(
                id=sentinel_id,
                username=f"outside-eval-{sentinel_id.hex}",
                email=f"outside-eval-{sentinel_id.hex}@example.com",
                hashed_password="test-password-hash",
            )
        )

    env = await environment_manager.prepare(_case("B4-01"), trial_index=0)
    manifest = env.manifest.to_dict()
    await env.cleanup()

    async with disposable_eval_async_session_factory() as session:
        assert await session.get(User, sentinel_id) is not None
        for user_id in manifest["user_ids"]:
            assert await session.get(User, user_id) is None


@pytest.mark.asyncio
async def test_cleanup_tracks_and_removes_durable_run_rows(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B4-01"), trial_index=0)
    created = await RunService(disposable_eval_async_session_factory).create_run(
        CreateRunCommand(
            tenant_id=env.tenant_id,
            actor_id=env.primary_user_id,
            session_id=None,
            prompt="分析贵州茅台",
            idempotency_key=f"eval-{uuid4().hex}",
            replaces_run_id=None,
        )
    )
    async with disposable_eval_async_session_factory() as session, session.begin():
        session.add(RunTenantScheduling(tenant_id=env.tenant_id))

    await env.capture_after()

    assert str(created.run.id) in env.manifest.run_ids
    assert str(created.run.session_id) in env.manifest.run_session_ids
    assert str(created.message.id) in env.manifest.run_message_ids
    assert str(created.events[0].id) in env.manifest.run_event_ids
    assert env.manifest.run_outbox_ids
    assert str(env.tenant_id) in env.manifest.run_tenant_scheduling_ids

    await env.cleanup()

    async with disposable_eval_async_session_factory() as session:
        assert await session.get(Run, created.run.id) is None
        assert await session.get(RunSession, created.run.session_id) is None
        assert await session.get(RunMessage, created.message.id) is None
        assert await session.get(RunEvent, created.events[0].id) is None
        assert await session.get(RunOutbox, env.manifest.run_outbox_ids[0]) is None
        assert await session.get(RunTenantScheduling, env.tenant_id) is None


@pytest.mark.asyncio
async def test_cleanup_tracks_memory_observation_and_outbox_rows(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    async with disposable_eval_async_session_factory() as session, session.begin():
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS chat_memory_retrieval_logs (
                    log_id UUID PRIMARY KEY,
                    user_id UUID NOT NULL,
                    query_text TEXT NOT NULL,
                    retrieved_edge_ids JSONB NOT NULL,
                    rrf_scores JSONB NOT NULL,
                    top_k_valid_from_p90_days DOUBLE PRECISION,
                    retriever_breakdown JSONB NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chat_memory_retrieval_feedback (
                    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL,
                    edge_id UUID NOT NULL,
                    feedback_kind TEXT NOT NULL,
                    reason TEXT,
                    log_id UUID
                );
                CREATE TABLE IF NOT EXISTS pending_milvus_inserts (
                    edge_id UUID PRIMARY KEY,
                    edge_text TEXT NOT NULL,
                    user_id UUID NOT NULL,
                    rel_type TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_attempt_at TIMESTAMPTZ
                )
                """
            )
        )
    env = await environment_manager.prepare(_case("B4-05"), trial_index=0)
    edge_id = UUID(env.manifest.memory_edge_ids[0])

    def _write(sync_session):
        log_id = log_retrieval_hit(
            sync_session,
            user_id=env.primary_user_id,
            query_text="风险偏好",
            retrieved_edge_ids=[str(edge_id)],
            rrf_scores={str(edge_id): 1.0},
            edges_meta={str(edge_id): {"valid_from": datetime(2026, 1, 1, tzinfo=UTC)}},
            retriever_breakdown={"pg": 1},
            latency_ms=3,
        )
        log_user_reject(
            sync_session,
            user_id=env.primary_user_id,
            edge_id=edge_id,
            feedback_kind="confirm",
            log_id=log_id,
        )
        enqueue_milvus_insert(
            sync_session,
            edge_id=edge_id,
            edge_text="eval edge",
            user_id=env.primary_user_id,
            rel_type="PREFERS",
            last_error="eval fault",
        )

    async with disposable_eval_async_session_factory() as session, session.begin():
        await session.run_sync(_write)
        session.add(
            MCPToolCallLog(
                user_id=str(env.primary_user_id),
                tool_name="memory_search",
                args_json={"query": "风险偏好"},
                result_count=1,
                latency_ms=3,
            )
        )

    await env.capture_after()

    assert len(env.manifest.memory_retrieval_log_ids) == 1
    assert len(env.manifest.memory_retrieval_feedback_ids) == 1
    assert env.manifest.pending_milvus_edge_ids == [str(edge_id)]
    assert len(env.manifest.mcp_tool_call_log_ids) == 1

    await env.cleanup()

    async with disposable_eval_async_session_factory() as session:
        for table_name, id_column, ids in (
            (
                "chat_memory_retrieval_logs",
                "log_id",
                env.manifest.memory_retrieval_log_ids,
            ),
            (
                "chat_memory_retrieval_feedback",
                "feedback_id",
                env.manifest.memory_retrieval_feedback_ids,
            ),
            ("pending_milvus_inserts", "edge_id", env.manifest.pending_milvus_edge_ids),
        ):
            count = await session.scalar(
                text(
                    f'SELECT count(*) FROM "{table_name}" '
                    f'WHERE "{id_column}" = ANY(CAST(:ids AS uuid[]))'
                ),
                {"ids": ids},
            )
            assert count == 0
        assert (
            await session.get(MCPToolCallLog, UUID(env.manifest.mcp_tool_call_log_ids[0])) is None
        )


def test_durable_transport_accepts_trial_actor_without_process_global_identity(
    monkeypatch: pytest.MonkeyPatch,
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    for name in (
        "CHATLOOP_EVAL_RUN_BASE_URL",
        "CHATLOOP_EVAL_TENANT_ID",
        "CHATLOOP_EVAL_AUTH_TOKEN",
        "CHATLOOP_EVAL_USER_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    actor = EvalActor(
        role="creator",
        user_id=uuid4(),
        tenant_id=uuid4(),
        token="trial-scoped-token",
        membership_role="member",
    )
    transport = DurableRunHttpTransport(
        disposable_eval_async_session_factory,
        actor=actor,
        tenant_id=actor.tenant_id,
        base_url="http://run-api",
    )

    assert transport.user_id == str(actor.user_id)
    assert transport.tenant_id == str(actor.tenant_id)


def test_durable_execution_fails_before_environment_seed(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    del disposable_eval_async_session_factory
    with pytest.raises(RuntimeError, match="durable stack isolation"):
        environment_manager.require_execution_capabilities(_case("B7-16"))
