"""技能双工具 in-process —— load_skill + run_skill_script(spec § 3.4)。

把 v0.9 SkillLoader(L1/L2/L3a)与 SkillExecutor(L3b 脚本)包成两个 in-process
工具,接入 ToolHub.dispatch。技能的图回环 → 工具循环:渐进装载由循环天然承载,
专用图节点与回环边消失。

部署形态:in-process Tool(碰 harness 内部状态 —— state.active_skill,spec § 3.3
判据)。Phase 4 chat worker 构造时注入已持的 SkillLoader / SkillExecutor 实例。

**load_skill**(name, resource=None):
- resource None → SkillLoader.load_skill(name)(SKILL.md 全文 + 该技能资源清单,
  目录页设计:返回正文顺带资源清单,省一次发现调用);成功后置 state.active_skill。
- resource 非 None → 先校验该资源在清单内(一级深,越界给指导错误),再 load_resource。
- 未知技能 → SkillLoaderError → [未知技能] 指导错误。

**run_skill_script**(skill, script, args={}):
- 包 SkillExecutor.execute,结果结构化成 {stdout, stderr, return_code} 三元组;
- return_code != 0 → ToolResult success=False(模型能区分逻辑错),但 output 仍带三元组;
- 超时/输出超限类错误码映射 [超时]/[执行失败] 文案;
- stdout 超 _STDOUT_CAP 字符 → 截断 + stdout_truncated 标记 + note。

契约偏差(向 Phase 4 显式标注,见 skill_tools 模块尾 + 报告):
- skill_load / escalate_request 等专用 SSE 事件不在本任务发:InProcessTool 无 emit
  通道,沿用 hub 通用 tool_call/tool_start/tool_end 事件;前端可从 tool_end{tool:
  "load_skill"} 渲染,专用事件留 Phase 4 决定。
- run_skill_script 大输出"强制写缓存返回摘要+键"是 cache 注入时的事;本任务最小实现
  只做截断 + 标记,不强制接缓存(留 Phase 4 接 read_cached_result 取回链路)。
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.skills.script_schemas import (
    SkillExecutionResult,
    SkillScriptArgs,
    SkillScriptRef,
)
from app.skills.types import SkillLoaderError, SkillLoadResult, SkillResource
from app.tools.base import ToolError

# run_skill_script stdout 截断阈值(与 context.py downgrade_char_threshold 同口径)。
_STDOUT_CAP = 1320

# SkillExecutionError.kind 中归类为"超时类"的错误码(映射 [超时] 文案)。
_TIMEOUT_KINDS = frozenset({"timeout", "cpu_limit"})


# 构造期注入的依赖类型注解为 Any:loader 是 SkillLoader、executor 是 SkillExecutor
# (真实类),测试注入 Fake;两者都只用到 load_skill/load_resource 与 execute 子集。


# ---------------------------------------------------------------------------
# args schema
# ---------------------------------------------------------------------------


class LoadSkillArgs(BaseModel):
    name: str
    resource: str | None = None


class RunSkillScriptArgs(BaseModel):
    skill: str
    script: str
    args: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fail(error: str) -> ToolError:
    """指导性错误 —— 以 [标签] 开头,ToolHub._guidance_error 原样透出。"""
    return ToolError(error)


# ---------------------------------------------------------------------------
# load_skill
# ---------------------------------------------------------------------------


class LoadSkillTool(InProcessTool):
    """name="load_skill" —— 装载技能方法论全文 + 资源清单,置活跃技能。"""

    name = "load_skill"
    description = "装载某个技能的方法论全文(SKILL.md)+ 附属资源清单(目录页)。"
    args_schema = LoadSkillArgs

    def __init__(self, *, loader: Any) -> None:
        self._loader = loader

    async def run_with_state(
        self, args: BaseModel, state: ChatLoopState
    ) -> dict[str, Any]:
        args = LoadSkillArgs.model_validate(args.model_dump())

        # 先取技能装载结果(SKILL.md 全文 + 资源清单);未知技能 → 指导错误
        try:
            loaded: SkillLoadResult = self._loader.load_skill(args.name)
        except SkillLoaderError as e:
            raise _fail(
                f"[未知技能] {args.name}。可用技能见系统提示的技能清单。(loader: {e})"
            ) from e

        resource_listing = [r.relative_path for r in loaded.resources]

        if args.resource is None:
            # 返回正文顺带资源清单(目录页设计,省一次发现调用)
            # 成功后置活跃技能(活跃技能方法论不降级的锚,context.py 已按 load_skill 保护)
            state.active_skill = args.name
            return {
                "skill": args.name,
                "content": loaded.skill_md_content,
                "resources": resource_listing,
            }

        # resource 非 None:先校验该资源在清单内(一级深,越界给指导错误)
        if args.resource not in resource_listing:
            listing_str = ", ".join(resource_listing) if resource_listing else "(无)"
            raise _fail(
                f"[资源不存在] {args.resource} 不在技能 {args.name} 的资源清单中。"
                f"可用资源:{listing_str}"
            )

        # 校验通过 → 取单资源(load_resource 一级深,内部还有路径穿越守护)
        try:
            res: SkillResource = self._loader.load_resource(args.name, args.resource)
        except SkillLoaderError as e:
            raise _fail(
                f"[资源不存在] {args.resource} 在技能 {args.name} 中无法装载:{e}"
            ) from e

        return {
            "skill": args.name,
            "resource": args.resource,
            "content": res.content,
        }


# ---------------------------------------------------------------------------
# run_skill_script
# ---------------------------------------------------------------------------


class RunSkillScriptTool(InProcessTool):
    """name="run_skill_script" —— 执行技能脚本,结果结构化三元组。"""

    name = "run_skill_script"
    description = "执行某个已装载技能附带的脚本(确定性计算);返回 stdout/stderr/return_code 三元组。"
    args_schema = RunSkillScriptArgs

    def __init__(self, *, executor: Any) -> None:
        self._executor = executor

    async def run_with_state(
        self, args: BaseModel, state: ChatLoopState
    ) -> dict[str, Any]:
        args = RunSkillScriptArgs.model_validate(args.model_dump())

        ref = SkillScriptRef(skill_name=args.skill, script_path=args.script)
        script_args = SkillScriptArgs(payload=args.args)

        # executor 抛异常(超时类/其它)→ 映射指导错误。result.error 走结构化路径。
        try:
            result: SkillExecutionResult = await self._executor.execute(
                ref=ref, args=script_args
            )
        except TimeoutError as e:  # asyncio.TimeoutError 是其别名(3.11+)
            raise _fail(f"[超时] 脚本执行超时:{e}") from e

        # stdout 序列化(executor 的 stdout_json 是结构化 dict;失败时为 None)
        stdout_text = (
            json.dumps(result.stdout_json, ensure_ascii=False)
            if result.stdout_json is not None
            else ""
        )

        output: dict[str, Any] = {
            "stdout": stdout_text,
            "stderr": result.stderr_text,
            "return_code": result.exit_code,
        }

        # stdout 超长截断 + 标记(本任务最小实现:截断 + 注明,不强制接缓存)
        if len(stdout_text) > _STDOUT_CAP:
            output["stdout"] = stdout_text[:_STDOUT_CAP]
            output["stdout_truncated"] = True
            output["note"] = "完整输出已截断(超长),如需全文请重跑或缩小脚本输出范围。"

        # 成功路径(executor ok=True 蕴含 exit_code==0)
        if result.ok:
            return output

        # 失败路径:按错误码区分超时类 vs 其它,均带三元组 output
        kind = result.error.kind if result.error is not None else "unknown"
        if kind in _TIMEOUT_KINDS:
            raise self._fail_with_output(
                f"[超时] 脚本执行超时(kind={kind})。", output
            )

        # 脚本逻辑失败(return_code != 0 等):模型能区分逻辑错并自纠
        stderr_head = result.stderr_text[:400]
        raise self._fail_with_output(
            f"[脚本失败] return_code={result.exit_code}。stderr: {stderr_head}", output
        )

    @staticmethod
    def _fail_with_output(error: str, output: dict[str, Any]) -> ToolError:
        """构造指导错误,把三元组 output 挂在异常上(Phase 4 hub 若需可读)。

        当前 hub 走 ToolError.message 包成 tool 消息;output 暂仅供调试/Phase 4。
        """
        exc = ToolError(error)
        exc.tool_output = output  # type: ignore[attr-defined]
        return exc


__all__ = [
    "LoadSkillArgs",
    "LoadSkillTool",
    "RunSkillScriptArgs",
    "RunSkillScriptTool",
]
