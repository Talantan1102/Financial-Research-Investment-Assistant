"""D3 工具服务(FastAPI)—— 薄包 ToolBox,给 verl rollout 经 HTTP 调真实后端工具。

跑在 backend(fria)env(依赖全好),verl env 只发 HTTP → 零污染 verl env。
端点:GET /tools(schema)/ POST /sessions(建会话)/ POST /sessions/{sid}/exec / DELETE /sessions/{sid}。
cache=None 下工具基本无状态,会话主要做生命周期/并发隔离的记号(本 smoke 共享一个 ToolBox)。
"""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from app.tools.base import ToolError
from fastapi import FastAPI
from pydantic import BaseModel

from eval.question_gen.verl_bridge.tool_box import ToolBox


class _ExecReq(BaseModel):
    tool: str
    args: dict[str, Any] = {}


class _SessReq(BaseModel):
    as_of: str | None = None  # 本题基准日;服务端按它给"最新值"工具注入,钉死答案不随训练日漂移


def build_app(*, tushare: Any, skills_root: str, workdir_root: str) -> FastAPI:
    box = ToolBox(tushare=tushare, skills_root=skills_root, workdir_root=workdir_root)
    sessions: dict[str, dict[str, Any]] = {}
    app = FastAPI(title="D3 verl tool-server")

    @app.get("/tools")
    def list_tools() -> dict[str, Any]:
        return {"tools": box.schemas()}

    @app.post("/sessions")
    def open_session(req: _SessReq | None = None) -> dict[str, str]:
        sid = str(uuid4())
        as_of = req.as_of if req else None
        sessions[sid] = {"as_of": as_of}
        print(f"[tool-server] session open as_of={as_of}", flush=True)  # 便于确认 verl 注入
        return {"session_id": sid}

    @app.post("/sessions/{sid}/exec")
    async def exec_tool(sid: str, req: _ExecReq) -> dict[str, Any]:
        # 工具错(参数非法/取数失败/代码崩)回 {"error": ...} 给模型自纠,不抛 500
        as_of = sessions.get(sid, {}).get("as_of")
        try:
            result = await box.exec(req.tool, req.args, as_of=as_of)
            return {"ok": True, "result": result}
        except KeyError:
            return {"ok": False, "error": f"unknown tool: {req.tool}"}
        except ToolError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001 — rollout 内任何工具异常都转可读反馈
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    @app.delete("/sessions/{sid}")
    def close_session(sid: str) -> dict[str, bool]:
        sessions.pop(sid, None)
        return {"closed": True}

    return app


def main() -> None:  # 生产入口:真 tushare + 真沙箱目录
    import uvicorn
    from app.services.tushare_factory import build_tushare_service

    app = build_app(
        tushare=build_tushare_service(),
        skills_root=os.environ.get("D3_SKILLS_ROOT", "/tmp/d3_skills"),
        workdir_root=os.environ.get("D3_WORKDIR_ROOT", "/tmp/d3_work"),
    )
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("D3_TOOL_PORT", "8731")))


if __name__ == "__main__":
    main()
