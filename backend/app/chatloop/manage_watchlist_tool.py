"""Direct, audited watchlist mutation tool."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.runtime.models import ExecutionContext


class ManageWatchlistArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["list", "add", "update", "remove"]
    ts_code: str | None = Field(default=None, pattern=r"^\d{6}\.(?:SH|SZ)$")
    name: str | None = Field(default=None, min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=2000)
    monitoring_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_action(self) -> ManageWatchlistArgs:
        if self.action != "list" and self.ts_code is None:
            raise ValueError(f"{self.action} requires ts_code")
        if self.action == "add" and self.name is None:
            raise ValueError("add requires name")
        if self.action in {"list", "remove"} and (
            self.name is not None or self.note is not None or self.monitoring_enabled is not None
        ):
            raise ValueError(f"{self.action} does not accept mutation fields")
        if self.action == "list" and self.ts_code is not None:
            raise ValueError("list does not accept ts_code")
        return self


class WatchlistBackend(Protocol):
    def manage(self, **kwargs: Any) -> dict[str, Any]: ...


class SqlWatchlistBackend:
    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    def manage(self, **kwargs: Any) -> dict[str, Any]:
        from app.schemas.watchlist import WatchlistRead
        from app.services.watchlist_service import ChangeSource, WatchlistService

        action = cast(str, kwargs["action"])
        source = ChangeSource(
            session_id=kwargs["source_session_id"],
            tool_call_id=kwargs["source_tool_call_id"],
        )
        with self._session_factory() as session:
            service = WatchlistService(session)
            payload: dict[str, Any]
            if action == "list":
                payload = {
                    "items": [
                        WatchlistRead.model_validate(item).model_dump(mode="json")
                        for item in service.list(user_id=kwargs["user_id"])
                    ]
                }
            elif action == "add":
                result = service.add(
                    user_id=kwargs["user_id"],
                    ts_code=kwargs["ts_code"],
                    name=kwargs["name"],
                    note=kwargs["note"],
                    monitoring_enabled=kwargs["monitoring_enabled"],
                    source=source,
                )
                payload = WatchlistRead.model_validate(result.item).model_dump(
                    mode="json"
                )
                payload["created"] = result.created
            elif action == "update":
                item = service.update(
                    user_id=kwargs["user_id"],
                    ts_code=kwargs["ts_code"],
                    changes=kwargs["changes"],
                    source=source,
                )
                if item is None:
                    payload = {"updated": False}
                else:
                    payload = WatchlistRead.model_validate(item).model_dump(mode="json")
                    payload["updated"] = True
            elif action == "remove":
                removed = service.remove(
                    user_id=kwargs["user_id"],
                    ts_code=kwargs["ts_code"],
                    source=source,
                )
                payload = {"removed": removed.removed}
            else:
                raise ValueError(f"unsupported watchlist action: {action}")
            session.commit()
            return payload


class ManageWatchlistTool(InProcessTool):
    name = "manage_watchlist"
    description = "直接新增、修改或删除当前用户的自选股；monitoring_enabled 默认关闭。"
    args_schema = ManageWatchlistArgs

    def __init__(self, backend: WatchlistBackend) -> None:
        self._backend = backend

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        del args, state
        raise RuntimeError("watchlist tool requires execution context")

    async def run_with_context(
        self, args: BaseModel, state: ChatLoopState, context: ExecutionContext
    ) -> dict[str, Any]:
        if context.user_id != state.user_id:
            raise RuntimeError("execution identity does not match chat state")
        parsed = cast(ManageWatchlistArgs, args)
        changes = dict(
            parsed.model_dump(include={"name", "note", "monitoring_enabled"}, exclude_unset=True)
        )
        if parsed.action != "update":
            changes = {}
        return await asyncio.to_thread(
            self._backend.manage,
            user_id=uuid.UUID(state.user_id),
            action=parsed.action,
            ts_code=parsed.ts_code,
            name=parsed.name,
            note=parsed.note,
            monitoring_enabled=parsed.monitoring_enabled
            if parsed.monitoring_enabled is not None
            else False,
            changes=changes,
            source_session_id=state.session_id,
            source_tool_call_id=context.task_id,
        )


__all__ = [
    "ManageWatchlistArgs",
    "ManageWatchlistTool",
    "SqlWatchlistBackend",
    "WatchlistBackend",
]
