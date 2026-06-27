"""HttpToolProxy —— verl BaseTool,经 HTTP 调 D3 工具服务(跑在 backend env 的真实工具)。

verl rollout 在 verl env,只需 httpx;真实工具在服务端跑 → 零污染 verl env。
verl 用 tool_config.yaml 的 class_name 实例化:`HttpToolProxy(config, tool_schema)`,
config 带 {server_url, tool_name}。每个 (工具, rollout 实例) 自建一个服务端会话
(cache=None 工具无状态,无需跨工具共享会话)。

跨环境:verl 缺失时回退桩基类,backend env 可单测(用 httpx ASGITransport 连真 app)。
"""

from __future__ import annotations

import contextlib
import json
from typing import Any
from uuid import uuid4

try:
    from verl.tools.base_tool import BaseTool
    from verl.tools.schemas import ToolResponse
except ImportError:

    class BaseTool:  # type: ignore[no-redef]
        def __init__(self, config: dict | None = None, tool_schema: Any = None) -> None:
            self.config = config
            self.tool_schema = tool_schema

    class ToolResponse:  # type: ignore[no-redef]
        def __init__(self, text: str = "") -> None:
            self.text = text


class HttpToolProxy(BaseTool):
    def __init__(self, config: dict, tool_schema: Any) -> None:
        super().__init__(config=config, tool_schema=tool_schema)
        self._server_url = config["server_url"]
        # tool_name 优先取 config,缺则从 schema 取
        self._tool_name = config.get("tool_name") or tool_schema["function"]["name"]
        self._client: Any = config.get("_client")  # 测试可注入 httpx.AsyncClient(ASGITransport)
        self._sessions: dict[str, str] = {}  # instance_id -> server session_id

    def get_openai_tool_schema(self) -> Any:
        return self.tool_schema

    def _http(self) -> Any:
        if self._client is None:
            import httpx

            # trust_env=False:忽略 HTTP(S)_PROXY,避免本地 server 被全局代理(如 127.0.0.1:7897)劫持
            self._client = httpx.AsyncClient(
                base_url=self._server_url, timeout=60.0, trust_env=False
            )
        return self._client

    async def create(
        self, instance_id: str | None = None, create_kwargs: dict | None = None, **kwargs: Any
    ) -> tuple[str, Any]:
        instance_id = instance_id or str(uuid4())
        # create_kwargs(来自 parquet tools_kwargs.<tool>.create_kwargs)带本题 as_of → 注进服务端会话
        ck = create_kwargs or {}
        resp = await self._http().post("/sessions", json={"as_of": ck.get("as_of")})
        self._sessions[instance_id] = resp.json()["session_id"]
        return instance_id, ToolResponse()

    async def execute(
        self, instance_id: str, parameters: dict[str, Any], **kwargs: Any
    ) -> tuple[Any, float, dict]:
        sid = self._sessions.get(instance_id)
        if sid is None:  # 容错:没 create 直接 exec(verl 某些路径)→ 临时开一个
            _, _ = await self.create(instance_id)
            sid = self._sessions[instance_id]
        resp = await self._http().post(
            f"/sessions/{sid}/exec", json={"tool": self._tool_name, "args": parameters}
        )
        body = resp.json()
        if body.get("ok"):
            text = json.dumps(body["result"], ensure_ascii=False, default=str)
        else:
            text = f"[tool error] {body.get('error')}"
        return ToolResponse(text=text), 0.0, {}

    async def calc_reward(self, instance_id: str, **kwargs: Any) -> float:
        return 0.0

    async def release(self, instance_id: str, **kwargs: Any) -> None:
        sid = self._sessions.pop(instance_id, None)
        if sid is not None:
            with contextlib.suppress(Exception):  # 释放失败不致命
                await self._http().delete(f"/sessions/{sid}")


__all__ = ["HttpToolProxy"]
