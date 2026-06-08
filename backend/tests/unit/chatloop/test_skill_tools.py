"""技能双工具 in-process — L0 单测(Fake loader/executor,零 I/O,spec § 3.4)。

覆盖:
- load_skill 全文 + 资源清单 + active_skill 置位(活跃技能不降级的锚);
- load_skill 取单资源(resource 非 None,一级深校验);
- load_skill 越界资源 → 指导错误(资源不在清单内);
- load_skill 未知技能 → 指导错误;
- run_skill_script 成功三元组(stdout/stderr/return_code);
- run_skill_script rc!=0 → success=False 且 error 含 stderr,但 output 仍带三元组;
- run_skill_script stdout 超长截断 + 标记;
- run_skill_script executor 超时类异常 → [超时类] 文案;
- build_skill_listing(7 Fake 技能产出格式);
- 文档同步:TOOL_DOCS load_skill / run_skill_script 参数与实现一致(轻断言)。
"""

from __future__ import annotations

import json

import pytest
from app.chatloop.inprocess import InProcessTool
from app.chatloop.skill_listing import build_skill_listing
from app.chatloop.skill_tools import (
    LoadSkillArgs,
    LoadSkillTool,
    RunSkillScriptArgs,
    RunSkillScriptTool,
)
from app.chatloop.state import ChatLoopState
from app.chatloop.tool_docs import TOOL_DOCS
from app.chatloop.tool_hub import ToolHub
from app.services.llm_step import StepToolCall
from app.skills.script_schemas import (
    SkillExecutionError,
    SkillExecutionResult,
)
from app.skills.types import SkillLoaderError, SkillLoadResult, SkillManifest, SkillResource
from app.tools.base import ToolError

_USER_ID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeSkillLoader:
    """模拟 SkillLoader 的 load_l1 / load_skill / load_resource(真实方法签名)。"""

    def __init__(
        self,
        *,
        manifests: list[SkillManifest] | None = None,
        skill_md: dict[str, str] | None = None,
        resources: dict[tuple[str, str], SkillResource] | None = None,
        resource_names: dict[str, list[str]] | None = None,
    ) -> None:
        self._manifests = manifests or []
        self._skill_md = skill_md or {}
        # (skill, relative_ref) -> SkillResource
        self._resources = resources or {}
        # skill -> 资源清单(relative_path 列表)
        self._resource_names = resource_names or {}
        self.calls: list[tuple[str, tuple]] = []

    def load_l1(self) -> list[SkillManifest]:
        self.calls.append(("load_l1", ()))
        return self._manifests

    def load_skill(self, name: str) -> SkillLoadResult:
        self.calls.append(("load_skill", (name,)))
        if name not in self._skill_md:
            raise SkillLoaderError(f"skill not found: {name}")
        refs = self._resource_names.get(name, [])
        resources = [self._resources[(name, r)] for r in refs if (name, r) in self._resources]
        return SkillLoadResult(
            name=name,
            skill_md_content=self._skill_md[name],
            resources=resources,
            total_size_bytes=len(self._skill_md[name].encode("utf-8")),
            depth_used=1 if not resources else 2,
        )

    def load_resource(self, skill_name: str, relative_ref: str) -> SkillResource:
        self.calls.append(("load_resource", (skill_name, relative_ref)))
        key = (skill_name, relative_ref)
        if key not in self._resources:
            raise SkillLoaderError(f"resource not found: {relative_ref}")
        return self._resources[key]


class FakeSkillExecutor:
    """模拟 SkillExecutor.execute(返回 SkillExecutionResult 或抛异常)。"""

    def __init__(
        self,
        *,
        result: SkillExecutionResult | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._result = result
        self._raises = raises
        self.calls: list[dict] = []

    async def execute(self, *, ref, args, timeout_s=None) -> SkillExecutionResult:
        self.calls.append({"ref": ref, "args": args, "timeout_s": timeout_s})
        if self._raises is not None:
            raise self._raises
        assert self._result is not None
        return self._result


def _manifest(name: str, desc: str) -> SkillManifest:
    return SkillManifest(name=name, description=desc, path=f"/skills/{name}")


def _resource(skill: str, ref: str, content: str = "rubric body") -> SkillResource:
    return SkillResource(
        name=ref.split("/")[-1].rsplit(".", 1)[0],
        relative_path=ref,
        content_type="md",
        content=content,
        size_bytes=len(content.encode("utf-8")),
    )


def _state(messages: list[dict] | None = None) -> ChatLoopState:
    s = ChatLoopState(
        user_id=_USER_ID,
        session_id="s1",
        request_id="r1",
        messages=messages or [{"role": "user", "content": "看看我的持仓集中度"}],
    )
    s.step = 1
    return s


def _exec_result(
    *,
    ok: bool,
    stdout: dict | None,
    stderr: str = "",
    exit_code: int = 0,
    error: SkillExecutionError | None = None,
) -> SkillExecutionResult:
    return SkillExecutionResult(
        ok=ok,
        stdout_json=stdout,
        stderr_text=stderr,
        exit_code=exit_code,
        elapsed_s=0.01,
        skill_name="portfolio_risk",
        script_path="scripts/hhi.py",
        error=error,
    )


# ===========================================================================
# load_skill — 全文 + 资源清单 + active_skill
# ===========================================================================


async def test_load_skill_returns_full_md_and_resource_listing_sets_active():
    res = _resource("portfolio_risk", "resources/concentration_rubric.md")
    loader = FakeSkillLoader(
        skill_md={"portfolio_risk": "# 持仓集中度方法论\n按 HHI 计算..."},
        resources={("portfolio_risk", "resources/concentration_rubric.md"): res},
        resource_names={"portfolio_risk": ["resources/concentration_rubric.md"]},
    )
    tool = LoadSkillTool(loader=loader)
    state = _state()
    out = await tool.run_with_state(LoadSkillArgs(name="portfolio_risk"), state)

    assert out["skill"] == "portfolio_risk"
    assert "持仓集中度方法论" in out["content"]
    # 资源清单顺带返回(目录页设计,省一次发现调用)
    assert "resources/concentration_rubric.md" in out["resources"]
    # 成功后活跃技能置位(活跃技能不降级的锚)
    assert state.active_skill == "portfolio_risk"
    json.dumps(out, ensure_ascii=False)  # 可序列化


async def test_load_skill_single_resource():
    res = _resource("portfolio_risk", "resources/concentration_rubric.md", content="HHI 阈值 0.25")
    loader = FakeSkillLoader(
        skill_md={"portfolio_risk": "# 方法论"},
        resources={("portfolio_risk", "resources/concentration_rubric.md"): res},
        resource_names={"portfolio_risk": ["resources/concentration_rubric.md"]},
    )
    tool = LoadSkillTool(loader=loader)
    out = await tool.run_with_state(
        LoadSkillArgs(name="portfolio_risk", resource="resources/concentration_rubric.md"),
        _state(),
    )
    assert out["skill"] == "portfolio_risk"
    assert out["resource"] == "resources/concentration_rubric.md"
    assert "HHI 阈值" in out["content"]


async def test_load_skill_resource_out_of_listing_guidance():
    loader = FakeSkillLoader(
        skill_md={"portfolio_risk": "# 方法论"},
        resource_names={"portfolio_risk": ["resources/concentration_rubric.md"]},
    )
    tool = LoadSkillTool(loader=loader)
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(
            LoadSkillArgs(name="portfolio_risk", resource="resources/secret.md"),
            _state(),
        )
    msg = str(exc.value)
    assert "[资源不存在]" in msg
    assert "resources/secret.md" in msg
    # 越界不应置活跃技能
    # (失败路径)


async def test_load_skill_resource_out_of_listing_does_not_set_active():
    loader = FakeSkillLoader(
        skill_md={"portfolio_risk": "# 方法论"},
        resource_names={"portfolio_risk": ["resources/concentration_rubric.md"]},
    )
    tool = LoadSkillTool(loader=loader)
    state = _state()
    with pytest.raises(ToolError):
        await tool.run_with_state(
            LoadSkillArgs(name="portfolio_risk", resource="resources/secret.md"), state
        )
    assert state.active_skill is None


async def test_load_skill_unknown_skill_guidance():
    loader = FakeSkillLoader(skill_md={"portfolio_risk": "# x"})
    tool = LoadSkillTool(loader=loader)
    state = _state()
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(LoadSkillArgs(name="no_such_skill"), state)
    msg = str(exc.value)
    assert "[未知技能]" in msg
    assert "no_such_skill" in msg
    assert state.active_skill is None  # 失败不置位


async def test_load_skill_resource_absolute_path_rejected():
    """工具层路径防线:resource 为绝对路径 → [资源路径非法] 指导错误,不触达 loader。"""
    loader = FakeSkillLoader(
        skill_md={"portfolio_risk": "# 方法论"},
        resource_names={"portfolio_risk": ["resources/concentration_rubric.md"]},
    )
    tool = LoadSkillTool(loader=loader)
    state = _state()
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(
            LoadSkillArgs(name="portfolio_risk", resource="/etc/passwd"),
            state,
        )
    msg = str(exc.value)
    assert "[资源路径非法]" in msg
    # 绝对路径被拦截前不应调用 load_resource
    assert ("load_resource", ("portfolio_risk", "/etc/passwd")) not in loader.calls


async def test_load_skill_resource_path_traversal_rejected():
    """工具层路径防线:resource 含 '..' 片段(目录穿越) → [资源路径非法] 指导错误,不触达 loader。"""
    loader = FakeSkillLoader(
        skill_md={"portfolio_risk": "# 方法论"},
        resource_names={"portfolio_risk": ["resources/concentration_rubric.md"]},
    )
    tool = LoadSkillTool(loader=loader)
    state = _state()
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(
            LoadSkillArgs(name="portfolio_risk", resource="../../../secret.md"),
            state,
        )
    msg = str(exc.value)
    assert "[资源路径非法]" in msg
    # 穿越路径被拦截前不应调用 load_resource
    assert ("load_resource", ("portfolio_risk", "../../../secret.md")) not in loader.calls


# ===========================================================================
# run_skill_script
# ===========================================================================


async def test_run_skill_script_success_triplet():
    executor = FakeSkillExecutor(
        result=_exec_result(ok=True, stdout={"hhi": 0.31}, stderr="warn line", exit_code=0)
    )
    tool = RunSkillScriptTool(executor=executor)
    out = await tool.run_with_state(
        RunSkillScriptArgs(
            skill="portfolio_risk", script="scripts/hhi.py", args={"weights": [0.5, 0.5]}
        ),
        _state(),
    )
    assert out["return_code"] == 0
    assert out["stderr"] == "warn line"
    # stdout 三元组(structured result 序列化进 stdout)
    assert "hhi" in out["stdout"]
    json.dumps(out, ensure_ascii=False)


async def test_run_skill_script_nonzero_rc_is_failure_but_keeps_triplet():
    executor = FakeSkillExecutor(
        result=_exec_result(
            ok=False,
            stdout=None,
            stderr="Traceback: bad input weights",
            exit_code=2,
            error=SkillExecutionError(kind="non_zero_exit", message="exit code 2"),
        )
    )
    tool = RunSkillScriptTool(executor=executor)
    # rc!=0 → ToolError(success=False),但 output 仍带三元组
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(
            RunSkillScriptArgs(skill="portfolio_risk", script="scripts/hhi.py"), _state()
        )
    msg = str(exc.value)
    assert "[脚本失败]" in msg
    assert "return_code=2" in msg
    assert "bad input weights" in msg


async def test_run_skill_script_stdout_truncation():
    big = {"data": "x" * 5000}
    executor = FakeSkillExecutor(result=_exec_result(ok=True, stdout=big, exit_code=0))
    tool = RunSkillScriptTool(executor=executor)
    out = await tool.run_with_state(
        RunSkillScriptArgs(skill="portfolio_risk", script="scripts/hhi.py"), _state()
    )
    assert out["stdout_truncated"] is True
    assert len(out["stdout"]) == 1320
    assert "note" in out
    assert "截断" in out["note"]


async def test_run_skill_script_timeout_maps_error_code():
    executor = FakeSkillExecutor(
        result=_exec_result(
            ok=False,
            stdout=None,
            stderr="",
            exit_code=-9,
            error=SkillExecutionError(kind="timeout", message="exceeded 30s"),
        )
    )
    tool = RunSkillScriptTool(executor=executor)
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(
            RunSkillScriptArgs(skill="portfolio_risk", script="scripts/hhi.py"), _state()
        )
    msg = str(exc.value)
    # 超时类错误映射 [超时] 文案
    assert "[超时]" in msg


async def test_run_skill_script_executor_raises_timeout_exception():
    """executor 直接抛 TimeoutError 类异常(非 result.error)→ [超时] 文案。"""
    executor = FakeSkillExecutor(raises=TimeoutError("hard timeout"))
    tool = RunSkillScriptTool(executor=executor)
    with pytest.raises(ToolError) as exc:
        await tool.run_with_state(
            RunSkillScriptArgs(skill="portfolio_risk", script="scripts/hhi.py"), _state()
        )
    assert "[超时]" in str(exc.value)


# ===========================================================================
# build_skill_listing
# ===========================================================================


def test_build_skill_listing_7_skills():
    names = [
        "portfolio_risk",
        "valuation_check",
        "macro_policy",
        "earnings_quality",
        "technical_signal",
        "sector_rotation",
        "risk_assessment",
    ]
    manifests = [_manifest(n, f"当用户问{n}相关时使用") for n in names]
    loader = FakeSkillLoader(manifests=manifests)
    listing = build_skill_listing(loader)
    assert "## 可用技能" in listing
    for n in names:
        assert f"- {n}:" in listing
        assert f"当用户问{n}相关时使用" in listing


def test_build_skill_listing_empty_loader():
    loader = FakeSkillLoader(manifests=[])
    listing = build_skill_listing(loader)
    # 空清单仍产出标题(稳定前缀恒定)
    assert "## 可用技能" in listing


# ===========================================================================
# hub 集成 — InProcessTool 经 dispatch
# ===========================================================================


async def test_load_skill_is_inprocess_tool():
    loader = FakeSkillLoader(skill_md={"x": "# x"})
    assert isinstance(LoadSkillTool(loader=loader), InProcessTool)
    assert isinstance(RunSkillScriptTool(executor=FakeSkillExecutor()), InProcessTool)


async def test_hub_dispatch_load_skill_sets_active():
    loader = FakeSkillLoader(
        skill_md={"portfolio_risk": "# 方法论全文"},
        resource_names={"portfolio_risk": []},
    )
    hub = ToolHub()
    hub.register_inprocess([LoadSkillTool(loader=loader)])
    state = _state()
    call = StepToolCall(
        id="c1", name="load_skill", arguments=json.dumps({"name": "portfolio_risk"})
    )
    results = await hub.dispatch([call], state)
    assert results[0].success is True
    assert state.active_skill == "portfolio_risk"


# ===========================================================================
# 文档同步
# ===========================================================================


def test_docs_load_skill_params_match_impl():
    fields = set(LoadSkillArgs.model_fields.keys())
    assert fields == {"name", "resource"}
    doc = TOOL_DOCS["load_skill"].doc
    assert "name" in doc
    assert "resource" in doc


def test_docs_run_skill_script_params_match_impl():
    fields = set(RunSkillScriptArgs.model_fields.keys())
    assert fields == {"skill", "script", "args"}
    doc = TOOL_DOCS["run_skill_script"].doc
    assert "skill" in doc
    assert "script" in doc


def test_tool_names_match_docs():
    assert LoadSkillTool(loader=FakeSkillLoader()).name == "load_skill"
    assert RunSkillScriptTool(executor=FakeSkillExecutor()).name == "run_skill_script"
