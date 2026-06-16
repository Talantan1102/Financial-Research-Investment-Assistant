"""run_python data_refs:按 ref 把完整结构化数据灌进沙箱(命中/合并/越权/失效四路)。"""

from __future__ import annotations

import json

import pytest

from app.chatloop.code_interpreter_tool import CodeInterpreterArgs, CodeInterpreterTool
from app.chatloop.state import ChatLoopState
from app.tools.base import ToolError


class _FakeBackend:
    def __init__(self) -> None:
        self.last_data: dict | None = None

    async def run_code(self, *, source: str, data: dict, timeout_s: int):
        self.last_data = data

        class _R:
            ok = True
            stdout_json = {"result": {"keys": sorted(data.keys())}, "figures": []}
            stderr_text = ""
            elapsed_s = 0.0
            error = None

        return _R()


class _FakeCache:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store

    async def get_raw(self, key: str) -> str | None:
        return self._store.get(key)


def _state() -> ChatLoopState:
    return ChatLoopState(user_id="u1", session_id="s", request_id="r", messages=[])


@pytest.mark.asyncio
async def test_data_refs_resolves_full_payload() -> None:
    cache = _FakeCache({"u1::get_daily::abc": json.dumps({"close": [1.0, 2.0, 3.0]})})
    backend = _FakeBackend()
    tool = CodeInterpreterTool(backend=backend, cache=cache)  # type: ignore[arg-type]
    args = CodeInterpreterArgs(code="result=1", data_refs={"m": "u1::get_daily::abc"})
    await tool.run_with_state(args, _state())
    assert backend.last_data is not None
    assert backend.last_data["m"] == {"close": [1.0, 2.0, 3.0]}  # 全量注入,非手抄


@pytest.mark.asyncio
async def test_data_refs_merges_with_inline_data() -> None:
    cache = _FakeCache({"u1::get_daily::abc": json.dumps({"close": [9.0]})})
    backend = _FakeBackend()
    tool = CodeInterpreterTool(backend=backend, cache=cache)  # type: ignore[arg-type]
    args = CodeInterpreterArgs(code="result=1", data={"k": 1}, data_refs={"m": "u1::get_daily::abc"})
    await tool.run_with_state(args, _state())
    assert backend.last_data == {"k": 1, "m": {"close": [9.0]}}


@pytest.mark.asyncio
async def test_data_refs_cross_user_rejected() -> None:
    cache = _FakeCache({"u2::get_daily::abc": json.dumps({"close": [1.0]})})
    tool = CodeInterpreterTool(backend=_FakeBackend(), cache=cache)  # type: ignore[arg-type]
    args = CodeInterpreterArgs(code="result=1", data_refs={"m": "u2::get_daily::abc"})
    with pytest.raises(ToolError, match="无权访问"):
        await tool.run_with_state(args, _state())


@pytest.mark.asyncio
async def test_data_refs_missing_rejected() -> None:
    cache = _FakeCache({})
    tool = CodeInterpreterTool(backend=_FakeBackend(), cache=cache)  # type: ignore[arg-type]
    args = CodeInterpreterArgs(code="result=1", data_refs={"m": "u1::get_daily::gone"})
    with pytest.raises(ToolError, match="缓存不存在"):
        await tool.run_with_state(args, _state())
