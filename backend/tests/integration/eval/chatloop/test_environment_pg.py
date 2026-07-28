from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.memory.instrumentation import log_retrieval_hit, log_user_reject
from app.memory.milvus_outbox import enqueue_milvus_insert
from app.models.investor_suitability import (
    EntitlementStatus,
    Market,
    MarketAccessRule,
    MarketEntitlement,
)
from app.models.paper_account import PaperAccount
from app.models.paper_order import PaperFill, PaperOrder
from app.models.run import Run, RunEvent, RunMessage, RunPause, RunSession
from app.models.run_scheduling import RunOutbox, RunTenantScheduling
from app.models.user import User
from app.models.watchlist import WatchlistAudit
from app.services.run_service import CreateRunCommand, RunService
from app.services.trace_models import MCPToolCallLog
from eval.chatloop.case_loader import load_catalog
from eval.chatloop.case_schema import ActorSpec
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
async def test_explicit_market_entitlements_are_current_user_database_facts(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B6-04"), trial_index=0)

    snapshot = await env.snapshot()
    assert snapshot["entitlements"] == {
        "by_market": {
            "main_board": {
                "status": "enabled",
                "can_buy": True,
                "can_sell": True,
                "can_subscribe": True,
            },
            "gem": {
                "status": "enabled",
                "can_buy": True,
                "can_sell": True,
                "can_subscribe": True,
            },
            "star_market": {
                "status": "not_applied",
                "can_buy": False,
                "can_sell": False,
                "can_subscribe": False,
            },
            "bse": {
                "status": "restricted",
                "can_buy": False,
                "can_sell": True,
                "can_subscribe": False,
            },
        }
    }
    assert snapshot["permission_links"] == {"count": 0}
    assert len(env.manifest.market_entitlement_ids) == 4
    assert len(env.manifest.market_access_rule_ids) == 3
    entitlement_ids = [UUID(value) for value in env.manifest.market_entitlement_ids]
    rule_ids = [UUID(value) for value in env.manifest.market_access_rule_ids]

    async with disposable_eval_async_session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(MarketEntitlement).where(MarketEntitlement.id.in_(entitlement_ids))
                )
            ).all()
        )
        account = await session.get(PaperAccount, env.paper_account_id)
    assert account is not None
    assert account.user_id == env.primary_user_id
    assert {row.account_id for row in rows} == {env.paper_account_id}
    assert all(row.account_generation == account.generation for row in rows)

    await env.cleanup()

    async with disposable_eval_async_session_factory() as session:
        for row_id in entitlement_ids:
            assert await session.get(MarketEntitlement, row_id) is None
        for row_id in rule_ids:
            assert await session.get(MarketAccessRule, row_id) is None


@pytest.mark.asyncio
async def test_not_applied_entitlement_is_stable_and_cleanup_removes_its_fact(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B6-06"), trial_index=0)

    before = await env.capture_before()
    after = await env.capture_after()
    expected = {
        "status": "not_applied",
        "can_buy": False,
        "can_sell": False,
        "can_subscribe": False,
    }
    assert before["entitlements"]["by_market"]["star_market"] == expected
    assert after["entitlements"]["by_market"]["star_market"] == expected
    assert before["permission_links"] == after["permission_links"] == {"count": 0}
    assert len(env.manifest.market_entitlement_ids) == 1
    entitlement_id = UUID(env.manifest.market_entitlement_ids[0])

    await env.cleanup()

    async with disposable_eval_async_session_factory() as session:
        assert await session.get(MarketEntitlement, entitlement_id) is None


@pytest.mark.asyncio
async def test_boolean_entitlements_are_projected_as_market_capabilities(
    environment_manager,
) -> None:
    env = await environment_manager.prepare(_case("B8-05"), trial_index=0)

    assert (await env.snapshot())["entitlements"] == {
        "by_market": {
            "main_board": {
                "status": "enabled",
                "can_buy": True,
                "can_sell": True,
                "can_subscribe": True,
            },
            "gem": {
                "status": "not_applied",
                "can_buy": False,
                "can_sell": False,
                "can_subscribe": False,
            },
        }
    }

    await env.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("declared", "expected_status"),
    [
        (
            {
                "status": "not_applied",
                "can_buy": False,
                "can_sell": False,
                "can_subscribe": False,
            },
            EntitlementStatus.NOT_APPLIED,
        ),
        (
            {
                "status": "restricted",
                "can_buy": False,
                "can_sell": True,
                "can_subscribe": False,
            },
            EntitlementStatus.RESTRICTED,
        ),
    ],
    ids=("not-applied", "restricted"),
)
async def test_historical_order_restores_declared_entitlement_final_state(
    environment_manager,
    disposable_eval_async_session_factory,
    declared: dict[str, object],
    expected_status: EntitlementStatus,
) -> None:
    base = _case("B7-01")
    business_state = dict(base.initial_state.business_state)
    business_state["entitlements"] = {"by_market": {"main": declared}}
    case = base.model_copy(
        update={
            "initial_state": base.initial_state.model_copy(
                update={"business_state": business_state}
            )
        }
    )

    env = await environment_manager.prepare(case, trial_index=0)
    snapshot = await env.snapshot()

    assert snapshot["orders"]["count"] == 1
    assert snapshot["orders"]["latest"]["status"] == "partially_filled"
    assert snapshot["entitlements"]["by_market"]["main_board"] == declared
    assert len(env.manifest.market_entitlement_ids) == 1
    assert len(env.manifest.market_access_rule_ids) == 1
    entitlement_id = UUID(env.manifest.market_entitlement_ids[0])
    rule_id = UUID(env.manifest.market_access_rule_ids[0])

    async with disposable_eval_async_session_factory() as session:
        entitlement = await session.get(MarketEntitlement, entitlement_id)
        rule = await session.get(MarketAccessRule, rule_id)
    assert entitlement is not None
    assert entitlement.status is expected_status
    assert entitlement.can_buy is declared["can_buy"]
    assert entitlement.can_sell is declared["can_sell"]
    assert entitlement.can_subscribe is declared["can_subscribe"]
    assert rule is not None
    if expected_status is EntitlementStatus.NOT_APPLIED:
        assert entitlement.rule_version is None
        assert entitlement.enabled_at is None
        assert entitlement.restricted_at is None
    else:
        assert entitlement.rule_version == rule.rule_version
        assert entitlement.enabled_at is not None
        assert entitlement.restricted_at is not None

    await env.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("alias", "market", "snapshot_alias"),
    [
        ("main", Market.MAIN, "main_board"),
        ("chinext", Market.CHINEXT, "gem"),
        ("star", Market.STAR, "star_market"),
    ],
)
async def test_entitlement_catalog_aliases_map_to_production_markets(
    environment_manager,
    disposable_eval_async_session_factory,
    alias: str,
    market: Market,
    snapshot_alias: str,
) -> None:
    base = _case("B6-04")
    declared = {
        "status": "enabled",
        "can_buy": True,
        "can_sell": True,
        "can_subscribe": True,
    }
    business_state = {
        "entitlements": {"by_market": {alias: declared}},
        "orders": {"count": 0},
    }
    case = base.model_copy(
        update={
            "initial_state": base.initial_state.model_copy(
                update={"business_state": business_state}
            )
        }
    )

    env = await environment_manager.prepare(case, trial_index=0)

    assert (await env.snapshot())["entitlements"] == {"by_market": {snapshot_alias: declared}}
    async with disposable_eval_async_session_factory() as session:
        entitlement = await session.get(
            MarketEntitlement,
            UUID(env.manifest.market_entitlement_ids[0]),
        )
    assert entitlement is not None
    assert entitlement.market is market

    await env.cleanup()


@pytest.mark.asyncio
async def test_partial_order_seed_uses_real_settlement_and_fee_reservation(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B7-01"), trial_index=0)
    snapshot = await env.snapshot()

    assert snapshot["orders"]["latest"]["status"] == "partially_filled"
    assert snapshot["orders"]["latest"]["filled_quantity"] == 300
    assert snapshot["orders"]["latest"]["source_run_id"]
    assert snapshot["orders"]["latest"]["source_tool_call_id"].startswith("eval-seed-")
    assert snapshot["fills"]["count"] == 1
    assert snapshot["fills"]["records"][0]["price"] == "11.18"
    assert snapshot["funds"]["frozen_cash"] == "7840.08"
    assert len(env.manifest.match_pass_ids) == 1
    assert len(env.manifest.trade_ids) == 1
    assert len(env.manifest.holding_lot_ids) == 1
    assert len(env.manifest.market_entitlement_ids) == 1
    assert len(env.manifest.market_access_rule_ids) == 1
    async with disposable_eval_async_session_factory() as session:
        order = await session.get(PaperOrder, UUID(snapshot["orders"]["latest"]["id"]))
        entitlement = await session.get(
            MarketEntitlement,
            UUID(env.manifest.market_entitlement_ids[0]),
        )
        rule = await session.get(
            MarketAccessRule,
            UUID(env.manifest.market_access_rule_ids[0]),
        )
    assert entitlement is not None
    assert order is not None
    assert snapshot["orders"]["latest"]["source_run_id"] == str(order.source_run_id)
    assert snapshot["orders"]["latest"]["source_tool_call_id"] == order.source_tool_call_id
    assert entitlement.market is Market.MAIN
    assert entitlement.status is EntitlementStatus.ENABLED
    assert entitlement.can_buy is True
    assert entitlement.account_id == env.paper_account_id
    assert rule is not None
    assert rule.market is Market.MAIN
    assert entitlement.rule_version == rule.rule_version

    await env.cleanup()


@pytest.mark.asyncio
async def test_b7_order_alias_resolves_to_real_uuid_and_pause_fill_is_real_settlement(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B7-09"), trial_index=0)
    order_id = UUID(env.manifest.order_aliases["ord-b7-09"])
    initial_trade_count = len(env.manifest.trade_ids)

    assert str(order_id) != "ord-b7-09"
    assert env.manifest.order_alias_owners["ord-b7-09"] == str(env.actor("requester").user_id)
    requester_user_id = env.actor("requester").user_id
    assert requester_user_id is not None
    before = await env.snapshot()
    assert before["orders"]["records"][0]["id"] == str(order_id)
    assert before["orders"]["records"][0]["filled_quantity"] == 0

    await env.apply_order_fill(
        order_alias="ord-b7-09",
        quantity=200,
        expected_user_id=requester_user_id,
        requester_user_id=requester_user_id,
    )
    after = await env.snapshot()

    assert after["orders"]["records"][0]["status"] == "partially_filled"
    assert after["orders"]["records"][0]["filled_quantity"] == 200
    assert after["fills"]["count"] == 1
    assert after["fills"]["records"][0]["quantity"] == 200
    assert after["positions"]["records"][0]["quantity"] == 200
    assert len(env.manifest.fill_ids) == 1
    assert len(env.manifest.match_pass_ids) == 1
    assert len(env.manifest.trade_ids) == initial_trade_count + 1

    async with disposable_eval_async_session_factory() as session:
        order = await session.get(PaperOrder, order_id)
    assert order is not None
    assert order.filled_quantity == 200

    await env.cleanup()


@pytest.mark.asyncio
async def test_b7_apply_order_fill_rejects_cross_user_even_if_manifest_owner_is_forged(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B7-16"), trial_index=0)
    alias = "ord-b7-16-owner"
    order_id = UUID(env.manifest.order_aliases[alias])
    owner_user_id = env.actor("owner").user_id
    requester_user_id = env.actor("requester").user_id
    assert owner_user_id is not None
    assert requester_user_id is not None
    assert owner_user_id != requester_user_id
    assert env.manifest.order_alias_owners[alias] == str(owner_user_id)

    with pytest.raises(PermissionError, match="expected owner and requester"):
        await env.apply_order_fill(
            order_alias=alias,
            quantity=200,
            expected_user_id=owner_user_id,
            requester_user_id=requester_user_id,
        )

    env.manifest.order_alias_owners[alias] = str(requester_user_id)
    with pytest.raises(PermissionError, match="database owner"):
        await env.apply_order_fill(
            order_alias=alias,
            quantity=200,
            expected_user_id=requester_user_id,
            requester_user_id=requester_user_id,
        )

    async with disposable_eval_async_session_factory() as session:
        order = await session.get(PaperOrder, order_id)
        fill_count = await session.scalar(
            select(func.count()).select_from(PaperFill).where(PaperFill.order_id == order_id)
        )
    assert order is not None
    assert order.user_id == owner_user_id
    assert order.filled_quantity == 0
    assert fill_count == 0

    await env.cleanup()


@pytest.mark.asyncio
async def test_seed_order_aliases_are_globally_unique_and_cannot_be_overwritten(
    environment_manager,
) -> None:
    base = _case("B7-09")
    duplicate = dict(base.initial_state.business_state["orders"]["records"][0])
    duplicate["order_id"] = "ord-duplicate"
    business_state = dict(base.initial_state.business_state)
    business_state["orders"] = {
        "records": [dict(duplicate)],
        "by_user": {"other_user": [dict(duplicate)]},
    }
    actors = dict(base.initial_state.actors)
    actors["other_user"] = ActorSpec(role="other_user", tenant_scope="same")
    case = base.model_copy(
        update={
            "initial_state": base.initial_state.model_copy(
                update={"actors": actors, "business_state": business_state}
            )
        }
    )

    with pytest.raises(ValueError, match="duplicate order alias.*ord-duplicate"):
        await environment_manager.prepare(case, trial_index=0)


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
async def test_approval_delay_ages_only_the_requesters_real_unresolved_pause(
    environment_manager,
    disposable_eval_async_session_factory,
) -> None:
    env = await environment_manager.prepare(_case("B6-06"), trial_index=0)
    created = await RunService(disposable_eval_async_session_factory).create_run(
        CreateRunCommand(
            tenant_id=env.tenant_id,
            actor_id=env.primary_user_id,
            session_id=None,
            prompt="宁德时代买100股，限价210",
            idempotency_key=f"eval-delay-{uuid4().hex}",
            replaces_run_id=None,
        )
    )
    pause_id = uuid4()
    async with disposable_eval_async_session_factory() as session, session.begin():
        session.add(
            RunPause(
                id=pause_id,
                run_id=created.run.id,
                pause_no=1,
                pause_type="approval",
                request_payload={"tool_calls": [{"name": "place_paper_order"}]},
                continuation_payload={},
            )
        )

    before = datetime.now(UTC).replace(tzinfo=None)
    await env.apply_approval_delay(
        run_id=created.run.id,
        pause_id=pause_id,
        elapsed_seconds=660,
        requester_user_id=env.primary_user_id,
    )

    async with disposable_eval_async_session_factory() as session:
        pause = await session.get(RunPause, pause_id)
    assert pause is not None
    assert pause.resolved_at is None
    assert pause.created_at <= before - timedelta(seconds=659)
    assert pause.created_at >= before - timedelta(seconds=665)

    with pytest.raises(PermissionError, match="requester"):
        await env.apply_approval_delay(
            run_id=created.run.id,
            pause_id=pause_id,
            elapsed_seconds=660,
            requester_user_id=uuid4(),
        )

    await env.cleanup()


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
