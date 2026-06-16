"""CodeInterpreterTool — name="run_python"(spec § 3)。

LLM 当场写 Python,经 ExecutorBackend 沙箱执行,返回 {result, figures, stderr,
elapsed_s}。figures(plotly fig.to_dict() 列表)由 ToolLoop 抽出发 chart 事件并从
输出剥离 —— 工具本身只负责"执行 + 透传",不碰 SSE/缓存(职责单一)。

执行失败(safety_scan_rejected / non_zero_exit / timeout / stdout_invalid_json)
→ 抛 ToolError(带 stderr),hub 的 _guidance_error 见 '[' 前缀原样透出,LLM 据
stderr 改代码重试(chatloop while 循环天然承载自纠)。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.skills.executor_backend import ExecutorBackend
from app.tools.base import ToolError

_STDERR_FEEDBACK_LEN = 500  # 回喂模型自纠的 stderr 截断


class CodeInterpreterArgs(BaseModel):
    code: str = Field(
        description=(
            "完整 Python 脚本。数据在变量 data(dict)里,直接用,不用读 stdin。"
            "把图赋给 fig(单张)或 figures(plotly Figure 列表),结论赋给 result。"
            "不要 print、不要返回图片链接/markdown 图——执行器自动序列化并套统一主题。例:"
            "import plotly.graph_objects as go; "
            "fig=go.Figure(); fig.add_bar(x=data['names'], y=data['vals']); result='已画'。"
            "硬约束:用 plotly(非 matplotlib);无网络无文件;画复杂图/要统一风格先 "
            "load_skill('charting')。"
        )
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="喂给脚本的数据 JSON(把现有工具拿到的数据传进来),脚本里用变量 data 取;无则不传。",
    )
    data_refs: dict[str, str] | None = Field(
        default=None,
        description=(
            "把大数据工具结果(日线序列等)按引用喂进来,别手抄进 data。键=脚本里的变量名,"
            "值=该工具结果的缓存 ref(截断占位里的 ref 字段)。执行器自动把完整结构化结果灌进 "
            "data[变量名]。例:data_refs={'maotai':'<get_daily 结果的 ref>'} → 脚本里 "
            "data['maotai']['close'] 即全序列。数据量大时一律用它,不要把长数组手抄进 data。"
        ),
    )


class CodeInterpreterTool(InProcessTool):
    name = "run_python"
    description = "执行 Python 做数值计算/画交互分析图(plotly)。需二次计算或可视化时用。"
    args_schema = CodeInterpreterArgs

    def __init__(self, *, backend: ExecutorBackend, cache: Any = None, timeout_s: int = 30) -> None:
        self._backend = backend
        self._cache = cache  # ToolResultCache(协议 get_raw(ref)->str|None);None 则 data_refs 不可用
        self._timeout_s = timeout_s

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        args = CodeInterpreterArgs.model_validate(args.model_dump())
        data: dict[str, Any] = dict(args.data or {})
        if args.data_refs:
            data.update(await self._resolve_refs(args.data_refs, state))
        result = await self._backend.run_code(
            source=args.code, data=data, timeout_s=self._timeout_s
        )
        if not result.ok:
            kind = result.error.kind if result.error else "unknown"
            stderr = result.stderr_text[:_STDERR_FEEDBACK_LEN]
            raise ToolError(f"[执行失败:{kind}] 代码执行未成功。\nstderr: {stderr}")

        out = result.stdout_json or {}
        return {
            "result": out.get("result"),
            "figures": out.get("figures") or [],
            "stderr": result.stderr_text[:_STDERR_FEEDBACK_LEN],
            "elapsed_s": round(result.elapsed_s, 2),
        }

    async def _resolve_refs(
        self, refs: dict[str, str], state: ChatLoopState
    ) -> dict[str, Any]:
        """按 ref 从缓存还原完整结构化数据(服务端,不经 LLM);带 user 命名空间防越权。"""
        if self._cache is None:
            raise ToolError("[执行失败:no_cache] data_refs 不可用(未注入缓存)。")
        out: dict[str, Any] = {}
        for varname, ref in refs.items():
            if not ref.startswith(f"{state.user_id}::"):
                raise ToolError(f"[无权访问] data_refs['{varname}'] 的 ref 不属于当前用户。")
            raw = await self._cache.get_raw(ref)
            if raw is None:
                raise ToolError(
                    f"[缓存不存在/已过期] data_refs['{varname}'] 的 ref 无对应缓存,请重调原工具。"
                )
            try:
                out[varname] = json.loads(raw)
            except (ValueError, TypeError) as e:
                raise ToolError(
                    f"[执行失败:bad_cache] data_refs['{varname}'] 缓存解析失败: {e}"
                ) from e
        return out


__all__ = ["CodeInterpreterArgs", "CodeInterpreterTool"]
