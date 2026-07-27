"""SUT-runner —— 跑真 ChatLoopAgent,产出每 case 的 SUTOutput 投影。

修了现有 ``eval.tool_selection._live_deps.build_eval_singletons`` 的 latent bug:
那里手动 ``await mcp_ctx.__aenter__()`` 把 MCP subprocess 上下文跨任务泄漏,anyio 抛
``RuntimeError: Attempted to exit cancel scope in a different task``,连首次 LLM 调用
都被 cancel。**修法**:用 ``async with MCPClient.from_subprocess(...)`` 把 singletons
构造 + 整个 case 循环包在同一任务里(本文件 run_scenarios)。

dispatch 两模式:
- ``noop``(行为①②③ + 免责):FakeNoopHub —— schema 透传真件,dispatch 占位,
  首轮工具选择即 SUTOutput.tool_calls;max_steps=1(序列 case=2)。
- ``real``(行为④ grounding):真 ToolHub —— agent 真检索真答,max_steps=6。

k>1:同 case 跑 k 次(独立 request_id),供 pass^k。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from eval.chatloop.scenario import Scenario

logger = logging.getLogger(__name__)

# 评测固定 user_id —— 必须是合法 UUID(memory_search 等按 UUID 解析;"eval" 会炸)。
_EVAL_USER_ID = "00000000-0000-4000-8000-000000000001"


class OutcomeEvalLockUnavailableError(RuntimeError):
    """Another process owns the dedicated stateful-eval identity."""


class OutcomeEvalIdentityError(RuntimeError):
    """The configured token, tenant, user, or created Run identity is unsafe."""


@dataclass(frozen=True)
class SutResult:
    case_id: str
    run_idx: int
    tool_calls: list[dict[str, Any]]
    response_text: str
    escalate_offered: bool
    evidence: str = ""  # real dispatch:agent 看到的工具返回(grounding 判依据)
    error: str | None = None
    run_state: dict[str, Any] | None = None
    database_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class TransportObservation:
    run_id: str
    tool_calls: list[dict[str, Any]]
    response_text: str
    escalate_offered: bool
    run_state: dict[str, Any]
    evidence: str = ""


class OutcomeTransport(Protocol):
    user_id: str

    async def execute(self, scenario: Scenario, run_idx: int) -> TransportObservation: ...


class OutcomeCollector(Protocol):
    async def prepare(
        self,
        *,
        user_id: str,
        scenario: Scenario,
        sample_key: str,
    ) -> None: ...

    async def capture(
        self,
        *,
        user_id: str,
        run_id: str | None,
        scenario: Scenario,
    ) -> dict[str, Any]: ...


class DurableRunHttpTransport:
    """Drive the real Run API and read its durable RunPause/tool ledger."""

    _TERMINAL = frozenset({"completed", "failed", "cancelled"})

    def __init__(self, session_factory: Any) -> None:
        required = {
            "base_url": os.getenv("CHATLOOP_EVAL_RUN_BASE_URL"),
            "tenant_id": os.getenv("CHATLOOP_EVAL_TENANT_ID"),
            "token": os.getenv("CHATLOOP_EVAL_AUTH_TOKEN"),
            "user_id": os.getenv("CHATLOOP_EVAL_USER_ID"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                "outcome eval requires durable Run configuration: " + ", ".join(missing)
            )
        self._base_url = str(required["base_url"]).rstrip("/")
        self._tenant_id = UUID(str(required["tenant_id"]))
        self._token = str(required["token"])
        self.user_id = str(UUID(str(required["user_id"])))
        self._session_factory = session_factory
        self._timeout_s = float(os.getenv("CHATLOOP_EVAL_RUN_TIMEOUT_S", "60"))
        self._batch_id = uuid4().hex

    @property
    def tenant_id(self) -> str:
        return str(self._tenant_id)

    async def execute(self, scenario: Scenario, run_idx: int) -> TransportObservation:
        import httpx

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Idempotency-Key": f"eval:{self._batch_id}:{scenario.case_id}:{run_idx}",
        }
        async with httpx.AsyncClient(base_url=self._base_url, timeout=10) as client:
            await self._preflight_identity(client, headers)
            response = await client.post(
                f"/api/v1/tenants/{self._tenant_id}/runs",
                headers=headers,
                json={"prompt": scenario.user_input},
            )
            response.raise_for_status()
            run_id = self._validated_created_run_id(response.json())
            status, pause = await self._wait(run_id)
            if pause is not None and pause.pause_type == "approval":
                resume_payload = self._resume_payload(scenario, pause.request_payload)
                resumed = await client.post(
                    f"/api/v1/tenants/{self._tenant_id}/runs/{run_id}/resume",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={"pause_id": str(pause.id), "response": resume_payload},
                )
                resumed.raise_for_status()
                status, _ = await self._wait(run_id)
                if status not in self._TERMINAL:
                    raise RuntimeError(f"resumed outcome Run stopped in {status}")
            elif status == "waiting_input":
                pass
            elif status not in self._TERMINAL:
                raise RuntimeError(f"outcome Run stopped in unexpected status {status}")
        tool_calls, run_state, response_text = await self._read_trace(run_id)
        run_state["status"] = status
        run_state["observation"] = {"version": 1, "status": "collected"}
        return TransportObservation(
            run_id=run_id,
            tool_calls=tool_calls,
            response_text=response_text,
            escalate_offered=False,
            run_state=run_state,
        )

    async def _preflight_identity(
        self,
        client: Any,
        headers: dict[str, str],
    ) -> None:
        auth_headers = {"Authorization": headers["Authorization"]}
        try:
            me = await client.get("/auth/me", headers=auth_headers)
            me.raise_for_status()
            me_payload = me.json()
        except Exception as exc:
            raise OutcomeEvalIdentityError("eval auth preflight failed") from exc
        try:
            actual_user_id = UUID(str(me_payload["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise OutcomeEvalIdentityError("eval auth preflight returned no valid user id") from exc
        if actual_user_id != UUID(self.user_id):
            raise OutcomeEvalIdentityError(
                "eval auth token does not belong to the dedicated eval user"
            )

        try:
            tenants = await client.get("/api/v1/tenants", headers=auth_headers)
            tenants.raise_for_status()
            payload = tenants.json()
        except Exception as exc:
            raise OutcomeEvalIdentityError("eval tenant preflight failed") from exc
        if not isinstance(payload, list):
            raise OutcomeEvalIdentityError("eval tenant preflight returned an invalid response")
        try:
            tenant_ids = {UUID(str(item["id"])) for item in payload if isinstance(item, dict)}
        except (KeyError, TypeError, ValueError) as exc:
            raise OutcomeEvalIdentityError(
                "eval tenant preflight returned an invalid tenant id"
            ) from exc
        if self._tenant_id not in tenant_ids:
            raise OutcomeEvalIdentityError(
                "eval auth token is not a member of the dedicated eval tenant"
            )

    def _validated_created_run_id(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            raise OutcomeEvalIdentityError("created eval Run response is not an object")
        try:
            run_id = UUID(str(payload["id"]))
            tenant_id = UUID(str(payload["tenant_id"]))
            user_id = UUID(str(payload["created_by_user_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise OutcomeEvalIdentityError(
                "created eval Run response is missing identity fields"
            ) from exc
        if tenant_id != self._tenant_id or user_id != UUID(self.user_id):
            raise OutcomeEvalIdentityError(
                "created eval Run identity does not match dedicated eval identity"
            )
        return str(run_id)

    async def _wait(self, run_id: str) -> tuple[str, Any | None]:
        import asyncio
        import time

        from app.models.run import Run, RunPause
        from sqlalchemy import select

        deadline = time.monotonic() + self._timeout_s
        while time.monotonic() < deadline:
            async with self._session_factory() as session:
                run = await session.get(Run, UUID(run_id))
                if run is None:
                    raise RuntimeError("created eval Run disappeared")
                if UUID(str(run.tenant_id)) != self._tenant_id or UUID(
                    str(run.created_by_user_id)
                ) != UUID(self.user_id):
                    raise OutcomeEvalIdentityError(
                        "persisted eval Run identity does not match preflight"
                    )
                status = str(run.status)
                pause = await session.scalar(
                    select(RunPause)
                    .where(RunPause.run_id == run.id, RunPause.resolved_at.is_(None))
                    .order_by(RunPause.pause_no.desc())
                    .limit(1)
                )
                if status in self._TERMINAL or pause is not None:
                    return status, pause
            await asyncio.sleep(0.1)
        raise TimeoutError(f"eval Run {run_id} did not reach pause/terminal state")

    @staticmethod
    def _resume_payload(scenario: Scenario, request: dict[str, Any]) -> dict[str, Any]:
        interaction = scenario.interaction or {}
        approved = interaction.get("pause_decision") == "approve"
        response: dict[str, Any] = {"approved": approved}
        edits_by_tool = interaction.get("edited_arguments", {})
        if approved and edits_by_tool:
            edits: dict[str, dict[str, Any]] = {}
            for call in request.get("tool_calls", []):
                tool_name = call.get("name")
                if tool_name in edits_by_tool:
                    edits[str(call["id"])] = dict(edits_by_tool[tool_name])
            response["edited_arguments"] = edits
        return response

    async def _read_trace(self, run_id: str) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
        from app.models.run import Run, RunMessage, RunPause
        from app.models.run_execution import RunToolExecution
        from sqlalchemy import select

        async with self._session_factory() as session:
            run = await session.get(Run, UUID(run_id))
            assert run is not None
            rows = (
                await session.scalars(
                    select(RunToolExecution)
                    .where(RunToolExecution.run_id == run.id)
                    .order_by(RunToolExecution.started_at, RunToolExecution.id)
                )
            ).all()
            pauses = (
                await session.scalars(
                    select(RunPause).where(RunPause.run_id == run.id).order_by(RunPause.pause_no)
                )
            ).all()
            calls: list[dict[str, Any]] = []
            seen_call_ids: set[str] = set()
            pause_permissions: dict[str, list[str]] = {}
            for pause in pauses:
                request = dict(pause.request_payload)
                response = dict(pause.response_payload or {})
                paused_calls = request.get("tool_calls")
                if not isinstance(paused_calls, list):
                    continue
                for paused in paused_calls:
                    if not isinstance(paused, dict):
                        continue
                    call_id = str(paused.get("id", ""))
                    initial = paused.get("permission_decision")
                    if not call_id or not isinstance(initial, str):
                        continue
                    trajectory = [initial]
                    approved = response.get("approved")
                    if approved is True:
                        trajectory.append("approved")
                    elif approved is False:
                        trajectory.append("rejected")
                    pause_permissions[call_id] = trajectory
            for row in rows:
                summary = dict(row.request_summary)
                args = summary.get("args", summary)
                call_id = str(row.tool_call_id)
                seen_call_ids.add(call_id)
                final_decision = str(row.permission_decision)
                decisions = list(pause_permissions.get(call_id, []))
                if not decisions or decisions[-1] != final_decision:
                    decisions.append(final_decision)
                calls.append(
                    {
                        "tool_call_id": call_id,
                        "tool_name": str(row.tool_name),
                        "args": dict(args) if isinstance(args, dict) else {},
                        "risk_level": str(row.risk_level),
                        "permission_decision": final_decision,
                        "permission_decisions": decisions,
                    }
                )
            for pause in pauses:
                request = dict(pause.request_payload)
                response = dict(pause.response_payload or {})
                paused_calls = request.get("tool_calls")
                if isinstance(paused_calls, list):
                    for paused in paused_calls:
                        if not isinstance(paused, dict):
                            continue
                        call_id = str(paused.get("id", ""))
                        if not call_id or call_id in seen_call_ids:
                            continue
                        arguments = paused.get("arguments", {})
                        if isinstance(arguments, str):
                            import json

                            arguments = json.loads(arguments)
                        approved = response.get("approved")
                        decision = (
                            "approved"
                            if approved is True
                            else "rejected"
                            if approved is False
                            else paused.get("permission_decision")
                        )
                        calls.append(
                            {
                                "tool_call_id": call_id,
                                "tool_name": str(paused.get("name", "")),
                                "args": dict(arguments) if isinstance(arguments, dict) else {},
                                "risk_level": paused.get("risk_level"),
                                "permission_decision": decision,
                                "permission_decisions": pause_permissions.get(
                                    call_id,
                                    [str(decision)] if decision is not None else [],
                                ),
                            }
                        )
                        seen_call_ids.add(call_id)
                elif pause.pause_type == "input" and request.get("tool_name") == "ask_user":
                    calls.append(
                        {
                            "tool_call_id": f"pause:{pause.id}",
                            "tool_name": "ask_user",
                            "args": {"question": request.get("question")},
                            "risk_level": request.get("risk_level"),
                            "permission_decision": request.get("permission_decision"),
                            "permission_decisions": [request.get("permission_decision")],
                        }
                    )
            pause_trace = [self._pause_trace(row) for row in pauses]
            final = (
                None
                if run.final_message_id is None
                else await session.get(RunMessage, run.final_message_id)
            )
            return (
                calls,
                {
                    "pauses": pause_trace,
                    "resumed": any(p.resolved_at for p in pauses),
                    "outcome": None
                    if run.outcome_code is None
                    else {
                        "code": str(run.outcome_code),
                        "payload": dict(run.outcome_payload or {}),
                    },
                },
                "" if final is None else str(final.content),
            )

    @staticmethod
    def _pause_trace(pause: Any) -> dict[str, Any]:
        response = dict(pause.response_payload or {})
        approved = response.get("approved")
        trace: dict[str, Any] = {
            "pause_type": str(pause.pause_type),
            "request": dict(pause.request_payload),
            "response": response,
        }
        if type(approved) is bool:
            trace["decision"] = "approved" if approved else "rejected"
        calls = pause.request_payload.get("tool_calls", [])
        if calls:
            original = calls[0].get("arguments", {})
            if isinstance(original, str):
                import json

                original = json.loads(original)
            trace["original"] = original
            edits = response.get("edited_arguments", {})
            trace["effective"] = edits.get(str(calls[0].get("id")), original)
        return trace


class SqlOutcomeCollector:
    """Capture user-owned paper/watchlist terminal facts around a durable Run."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._batch_id = uuid4().hex
        self._active_lock: tuple[int, Any] | None = None

    @asynccontextmanager
    async def sample_lock(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> Any:
        import asyncio
        import hashlib

        from sqlalchemy import text

        if self._active_lock is not None:
            raise RuntimeError("outcome eval sample advisory lock cannot be nested")
        identity = f"{UUID(tenant_id)}:{UUID(user_id)}".encode()
        lock_key = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)
        session = self._session_factory()
        try:
            acquired = bool(
                await session.scalar(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            )
        except BaseException:
            await session.close()
            raise
        if not acquired:
            await session.close()
            raise OutcomeEvalLockUnavailableError(
                "another stateful outcome eval owns the dedicated eval identity"
            )
        self._active_lock = (lock_key, session)
        try:
            yield
        finally:

            async def release() -> None:
                try:
                    await session.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                finally:
                    await session.close()
                    self._active_lock = None

            cleanup = asyncio.create_task(release())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def prepare(
        self,
        *,
        user_id: str,
        scenario: Scenario,
        sample_key: str,
    ) -> None:
        configured = os.getenv("CHATLOOP_EVAL_USER_ID")
        if configured is None:
            raise RuntimeError("CHATLOOP_EVAL_USER_ID is required for stateful eval setup")
        uid = UUID(user_id)
        if uid != UUID(configured) or uid != UUID(_EVAL_USER_ID):
            raise RuntimeError("stateful eval setup is restricted to the dedicated eval user")
        async with self._session_factory() as session, session.begin():
            await session.run_sync(
                lambda sync_session: self._prepare_sync(
                    sync_session,
                    user_id=uid,
                    scenario=scenario,
                    sample_key=sample_key,
                )
            )

    def _prepare_sync(
        self,
        session: Any,
        *,
        user_id: UUID,
        scenario: Scenario,
        sample_key: str,
    ) -> None:
        import hashlib

        from app.services.paper_trading.account_service import PaperAccountService
        from app.services.watchlist_service import ChangeSource, WatchlistService

        digest = hashlib.sha256(f"{self._batch_id}:{sample_key}".encode()).hexdigest()[:24]
        source = f"eval-setup-{digest}"
        outcome_type = str((scenario.outcome or {}).get("type"))
        if outcome_type == "paper_trading":
            accounts = PaperAccountService(session)
            accounts.get_or_create(
                user_id=user_id,
                initial_cash=Decimal("10000000.00"),
            )
            accounts.reset_confirmed(
                user_id=user_id,
                initial_cash=Decimal("10000000.00"),
                source_session_id=source,
                confirmation_id=digest,
            )
            return
        if outcome_type == "market_permission":
            # This evaluator observes a separately completed suitability flow.
            # It must not simulate applications or alter entitlement facts.
            return
        if outcome_type != "watchlist":
            raise RuntimeError(f"unsupported stateful outcome type: {outcome_type}")

        args = (scenario.outcome or {}).get("tool_args_contains", {}).get("manage_watchlist", {})
        action = args.get("action")
        ts_code = args.get("ts_code")
        if action not in {"add", "update", "remove"} or not isinstance(ts_code, str):
            raise RuntimeError("watchlist outcome setup requires action and ts_code")
        watchlist = WatchlistService(session)
        change_source = ChangeSource(session_id=source, tool_call_id="prepare")
        existing = next(
            (item for item in watchlist.list(user_id=user_id) if item.ts_code == ts_code),
            None,
        )
        if action == "add":
            if existing is not None:
                watchlist.remove(
                    user_id=user_id,
                    ts_code=ts_code,
                    source=change_source,
                )
            return
        if existing is None:
            watchlist.add(
                user_id=user_id,
                ts_code=ts_code,
                name=str(args.get("name") or ts_code),
                note="eval-seed",
                monitoring_enabled=False,
                source=change_source,
            )
            return
        watchlist.update(
            user_id=user_id,
            ts_code=ts_code,
            changes={"note": "eval-seed", "monitoring_enabled": False},
            source=change_source,
        )

    async def capture(
        self,
        *,
        user_id: str,
        run_id: str | None,
        scenario: Scenario,
    ) -> dict[str, Any]:
        from app.models.investor_suitability import MarketEntitlement
        from app.models.paper_account import PaperAccount
        from app.models.paper_order import PaperOrder
        from app.models.run import Run
        from app.models.watchlist import WatchlistAudit, WatchlistItem
        from sqlalchemy import func, select, text

        uid = UUID(user_id)
        async with self._session_factory() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            source_session_id = None
            if run_id is not None:
                run = await session.get(Run, UUID(run_id))
                source_session_id = None if run is None else str(run.session_id)
            account = await session.scalar(
                select(PaperAccount)
                .where(PaperAccount.user_id == uid, PaperAccount.status == "active")
                .order_by(PaperAccount.generation.desc())
                .limit(1)
            )
            await self._after_capture_account_read()
            order_count = int(
                await session.scalar(
                    select(func.count()).select_from(PaperOrder).where(PaperOrder.user_id == uid)
                )
                or 0
            )
            order = None
            created_order_count = 0
            if run_id is not None:
                created_order_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(PaperOrder)
                        .where(
                            PaperOrder.user_id == uid,
                            PaperOrder.source_run_id == UUID(run_id),
                        )
                    )
                    or 0
                )
                order = await session.scalar(
                    select(PaperOrder)
                    .where(PaperOrder.user_id == uid, PaperOrder.source_run_id == UUID(run_id))
                    .order_by(PaperOrder.created_at.desc())
                    .limit(1)
                )
            item_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(WatchlistItem)
                    .where(WatchlistItem.user_id == uid)
                )
                or 0
            )
            expected_args = (
                (scenario.outcome or {}).get("tool_args_contains", {}).get("manage_watchlist", {})
            )
            target_code = expected_args.get("ts_code")
            entitlement = None
            market = (scenario.outcome or {}).get("market")
            if isinstance(market, str) and account is not None:
                entitlement = await session.scalar(
                    select(MarketEntitlement)
                    .where(
                        MarketEntitlement.account_id == account.id,
                        MarketEntitlement.account_generation == account.generation,
                        MarketEntitlement.market == market,
                    )
                    .limit(1)
                )
            item_statement = select(WatchlistItem).where(WatchlistItem.user_id == uid)
            if target_code:
                item_statement = item_statement.where(WatchlistItem.ts_code == target_code)
            item = await session.scalar(
                item_statement.order_by(WatchlistItem.updated_at.desc()).limit(1)
            )
            audit = None
            if source_session_id is not None:
                audit_statement = select(WatchlistAudit).where(WatchlistAudit.user_id == uid)
                audit_statement = audit_statement.where(
                    WatchlistAudit.source_session_id == source_session_id
                )
                audit = await session.scalar(
                    audit_statement.order_by(
                        WatchlistAudit.created_at.desc(), WatchlistAudit.id.desc()
                    ).limit(1)
                )
            snapshot: dict[str, Any] = {
                "observation": {"version": 1, "status": "collected"},
                "snapshot_collected": True,
                "account_generation": None if account is None else int(account.generation),
                "order_count": order_count,
                "created_order_count": created_order_count,
                "available_cash": None
                if account is None
                else _decimal_text(account.available_cash),
                "reserved_cash": None if account is None else _decimal_text(account.frozen_cash),
                "watchlist": {
                    "count": item_count,
                    "exists": item is not None,
                    **(
                        {}
                        if item is None
                        else {
                            "ts_code": str(item.ts_code),
                            "note": item.note,
                            "monitoring_enabled": bool(item.monitoring_enabled),
                        }
                    ),
                },
                "audit": None
                if audit is None
                else {
                    "action": str(audit.action),
                    "before": audit.before_json,
                    "after": audit.after_json,
                },
            }
            if entitlement is not None:
                snapshot["entitlement"] = {
                    "market": str(entitlement.market),
                    "status": str(entitlement.status),
                    "can_buy": bool(entitlement.can_buy),
                    "can_sell": bool(entitlement.can_sell),
                    "can_subscribe": bool(entitlement.can_subscribe),
                }
            if order is not None:
                snapshot["order"] = {
                    "ts_code": str(order.ts_code),
                    "side": str(order.side),
                    "quantity": int(order.quantity),
                    "limit_price": _decimal_text(order.limit_price),
                    "source_run_matches": str(order.source_run_id) == run_id,
                    "current_generation": (
                        account is not None
                        and int(order.account_generation) == int(account.generation)
                    ),
                }
                snapshot["audit"] = {
                    "original": order.original_proposal,
                    "effective": order.confirmed_payload,
                }
            return snapshot

    async def _after_capture_account_read(self) -> None:
        """Internal observation seam; capture tests use it to interleave a writer."""


def _decimal_text(value: Any) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@asynccontextmanager
async def _unlocked_sample() -> Any:
    """Compatibility seam for unit transports/collectors with no external state."""
    yield


async def run_scenarios(
    scenarios: list[Scenario],
    *,
    dispatch_mode: str = "noop",
    k: int = 1,
    max_steps: int | None = None,
    system_prompt: str | None = None,
    outcome_transport: OutcomeTransport | None = None,
    outcome_collector: OutcomeCollector | None = None,
) -> list[SutResult]:
    """构造真件,跑全部 scenarios × k 次,返回 SutResult 列表(per-case 错误隔离)。

    system_prompt: 覆盖系统提示词(prompt 消融用,如对照"加免责前/后");None=生产 CHAT_SYSTEM_PROMPT。
    """
    # 延迟 import:dry / 单测路径零重依赖(无 PG/MCP/LLM)。
    from app.app_main import _sqlalchemy_async_pg_url
    from app.chatloop.context import ContextDeps
    from app.chatloop.eval_agent import ChatLoopAgent
    from app.chatloop.gates import GateConfig
    from app.chatloop.loop import ToolLoop
    from app.chatloop.state import ChatLoopState
    from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
    from app.chatloop.worker_wiring import build_heavy_singletons
    from app.services.mcp_client import MCPClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from eval.tool_selection._live import FakeNoopHub, build_real_hub

    engine = create_async_engine(_sqlalchemy_async_pg_url(), future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    results: list[SutResult] = []

    try:
        outcome_scenarios = [scenario for scenario in scenarios if scenario.outcome is not None]
        ordinary_scenarios = [scenario for scenario in scenarios if scenario.outcome is None]
        if outcome_scenarios:
            transport = outcome_transport or DurableRunHttpTransport(session_factory)
            collector = outcome_collector or SqlOutcomeCollector(session_factory)
            for scenario in outcome_scenarios:
                for run_idx in range(k):
                    try:
                        lock_factory = getattr(collector, "sample_lock", None)
                        if lock_factory is None:
                            sample = _unlocked_sample()
                        else:
                            tenant_id = getattr(transport, "tenant_id", None)
                            if tenant_id is None:
                                raise RuntimeError(
                                    "stateful outcome transport does not expose tenant identity"
                                )
                            sample = lock_factory(
                                tenant_id=tenant_id,
                                user_id=transport.user_id,
                            )
                        async with sample:
                            await collector.prepare(
                                user_id=transport.user_id,
                                scenario=scenario,
                                sample_key=f"{scenario.case_id}:{run_idx}",
                            )
                            before = await collector.capture(
                                user_id=transport.user_id,
                                run_id=None,
                                scenario=scenario,
                            )
                            observed = await transport.execute(scenario, run_idx)
                            after = await collector.capture(
                                user_id=transport.user_id,
                                run_id=observed.run_id,
                                scenario=scenario,
                            )
                        results.append(
                            SutResult(
                                case_id=scenario.case_id,
                                run_idx=run_idx,
                                tool_calls=observed.tool_calls,
                                response_text=observed.response_text,
                                escalate_offered=observed.escalate_offered,
                                evidence=observed.evidence,
                                run_state=observed.run_state,
                                database_state={
                                    **after,
                                    "before": before,
                                    "after": after,
                                },
                            )
                        )
                    except (OutcomeEvalIdentityError, OutcomeEvalLockUnavailableError):
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("outcome case %s run %d failed", scenario.case_id, run_idx)
                        results.append(
                            SutResult(
                                case_id=scenario.case_id,
                                run_idx=run_idx,
                                tool_calls=[],
                                response_text="",
                                escalate_offered=False,
                                error=f"{type(exc).__name__}: {exc}",
                            )
                        )
        if not ordinary_scenarios:
            return results
        # 关键:async with 把 MCP 上下文 + singletons + case 循环锁在同一任务(修 cancel-scope bug)
        async with MCPClient.from_subprocess(profile="chat_tools") as mcp_client:
            singletons = await build_heavy_singletons(
                session_factory=session_factory,
                mcp_client=mcp_client,
            )
            deps = ContextDeps(
                system_prompt=system_prompt or CHAT_SYSTEM_PROMPT,
                skill_listing=singletons.skill_listing,
            )
            for sc in ordinary_scenarios:
                is_seq = "tools_sequence_contains" in sc.expected
                if dispatch_mode == "real":
                    steps = max_steps or 6
                else:
                    steps = max_steps or (2 if is_seq else 1)
                for run_idx in range(k):
                    rid = f"clev-{sc.case_id}-{run_idx}"
                    try:
                        real_hub = build_real_hub(singletons)
                        hub: Any = (
                            real_hub
                            if dispatch_mode == "real"
                            else FakeNoopHub(real_hub, run_search_tools_live=is_seq)
                        )
                        # 直接跑 ToolLoop(而非 ChatLoopAgent.run)以保留 final 状态 → 抽 evidence
                        state = ChatLoopState(
                            user_id=_EVAL_USER_ID,
                            session_id=rid,
                            request_id=rid,
                            messages=[{"role": "user", "content": sc.user_input}],
                        )
                        toolloop = ToolLoop(
                            llm=singletons.llm,
                            tool_hub=hub,
                            context_deps=deps,
                            gate_cfg=GateConfig(max_steps=steps),
                        )
                        final = await toolloop.run(state)
                        resp = final.final_response or ChatLoopAgent._last_assistant_content(final)
                        tcs = ChatLoopAgent._extract_tool_calls(final)
                        evidence = "\n".join(
                            str(m.get("content", ""))
                            for m in final.messages
                            if m.get("role") == "tool"
                        )
                        results.append(
                            SutResult(
                                case_id=sc.case_id,
                                run_idx=run_idx,
                                tool_calls=[
                                    {"tool_name": tc.tool_name, "args": tc.args} for tc in tcs
                                ],
                                response_text=resp,
                                escalate_offered=final.escalate_offered,
                                evidence=evidence,
                            )
                        )
                    except Exception as e:  # noqa: BLE001 — per-case 隔离,fail loud 但不炸整跑
                        logger.exception("case %s run %d 失败", sc.case_id, run_idx)
                        results.append(
                            SutResult(
                                case_id=sc.case_id,
                                run_idx=run_idx,
                                tool_calls=[],
                                response_text="",
                                escalate_offered=False,
                                error=f"{type(e).__name__}: {e}",
                            )
                        )
    finally:
        await engine.dispose()

    return results


__all__ = [
    "DurableRunHttpTransport",
    "OutcomeCollector",
    "OutcomeTransport",
    "SqlOutcomeCollector",
    "SutResult",
    "TransportObservation",
    "run_scenarios",
]
