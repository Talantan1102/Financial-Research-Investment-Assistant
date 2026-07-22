from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.models.position import Position
from app.models.watchlist import WatchlistAudit, WatchlistItem


class ManageWatchlistArgs(BaseModel):
    action: Literal["list", "add", "update", "remove"]
    ts_code: str | None = None
    name: str | None = None
    note: str | None = None
    monitoring_enabled: bool = False
    changes: dict[str, object] = Field(default_factory=dict)


def _snapshot(item: WatchlistItem) -> dict[str, object]:
    return {
        "id": str(item.id),
        "ts_code": item.ts_code,
        "name": item.name,
        "note": item.note,
        "monitoring_enabled": bool(item.monitoring_enabled),
    }


class ManageWatchlistTool(InProcessTool):
    name = "manage_watchlist"
    description = "直接新增、修改、删除或查看自选股；写入立即执行，不产生模拟交易审批。"
    args_schema = ManageWatchlistArgs

    def __init__(self, *, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        parsed = ManageWatchlistArgs.model_validate(args.model_dump())
        user_id = UUID(state.user_id)
        async with self._session_factory() as session:
            if parsed.action == "list":
                rows = (
                    (
                        await session.execute(
                            select(WatchlistItem)
                            .where(WatchlistItem.user_id == user_id)
                            .order_by(WatchlistItem.ts_code)
                        )
                    )
                    .scalars()
                    .all()
                )
                return {"items": [_snapshot(row) for row in rows]}
            if not parsed.ts_code:
                return {"error": "missing_ts_code"}
            item = (
                await session.execute(
                    select(WatchlistItem).where(
                        WatchlistItem.user_id == user_id, WatchlistItem.ts_code == parsed.ts_code
                    )
                )
            ).scalar_one_or_none()
            if parsed.action == "add":
                if item is not None:
                    return {"created": False, "item": _snapshot(item)}
                item = WatchlistItem(
                    user_id=user_id,
                    ts_code=parsed.ts_code,
                    name=parsed.name or parsed.ts_code,
                    note=parsed.note,
                    monitoring_enabled=parsed.monitoring_enabled,
                )
                session.add(item)
                await session.flush()
                session.add(
                    WatchlistAudit(
                        item_id=item.id,
                        user_id=user_id,
                        action="add",
                        after_json=_snapshot(item),
                        source_session_id=state.session_id,
                        source_tool_call_id=state.request_id,
                    )
                )
                await session.commit()
                return {"created": True, "item": _snapshot(item)}
            if item is None:
                return {"error": "not_found", "ts_code": parsed.ts_code}
            before = _snapshot(item)
            if parsed.action == "update":
                for key, value in parsed.changes.items():
                    if key not in {"name", "note", "monitoring_enabled"}:
                        return {"error": "unsupported_field", "field": key}
                    setattr(item, key, value)
                session.add(
                    WatchlistAudit(
                        item_id=item.id,
                        user_id=user_id,
                        action="update",
                        before_json=before,
                        after_json=_snapshot(item),
                        source_session_id=state.session_id,
                        source_tool_call_id=state.request_id,
                    )
                )
                await session.commit()
                return {"updated": True, "item": _snapshot(item)}
            position = (
                await session.execute(
                    select(Position).where(
                        Position.user_id == user_id,
                        Position.ts_code == parsed.ts_code,
                        Position.paper_account_id.is_(None),
                        Position.quantity > 0,
                    )
                )
            ).scalar_one_or_none()
            session.add(
                WatchlistAudit(
                    item_id=item.id,
                    user_id=user_id,
                    action="remove",
                    before_json=before,
                    source_session_id=state.session_id,
                    source_tool_call_id=state.request_id,
                )
            )
            await session.delete(item)
            await session.commit()
            result: dict[str, Any] = {"removed": True, "ts_code": parsed.ts_code}
            if position is not None:
                result["monitoring_note"] = "该股票仍在真实持仓中，删除自选股不会停止持仓监控。"
            return result


__all__ = ["ManageWatchlistArgs", "ManageWatchlistTool"]
