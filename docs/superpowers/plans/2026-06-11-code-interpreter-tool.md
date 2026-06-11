# 代码解释器工具(`run_python`)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 chat agent 加一个 `run_python` 工具——LLM 当场写 Python,在复用的 SkillExecutor 沙箱里执行数值计算并产出 plotly 交互图,图经 `chart` SSE 事件旁路渲染到前端,绝不进 LLM 上下文。

**Architecture:** 复用已 ship 的 `SkillExecutor`(subprocess+rlimit+AST 扫描+断网+workdir),新增 `execute_source` 内联源码入口;`ExecutorBackend` 接口抽象底座(`SkillExecutorBackend` v1.0,`DockerExecutorBackend` 留 v1.x 口);`CodeInterpreterTool`(InProcessTool,延迟组)调后端;ToolLoop 在 dispatch 与 apply_results 之间把 `figures` 抽出、发 `chart` 事件、从工具输出剥离;前端新增 `PlotlySpecRenderer` + `chart` 事件 → chart 消息。

**Tech Stack:** Python 3.11 / pydantic / asyncio / pytest(后端);plotly(沙箱绘图,optional extra);React + react-plotly.js + valtio + vitest(前端)。

**Spec:** `docs/superpowers/specs/2026-06-11-code-interpreter-tool-design.md`

---

## 文件结构图

**新建:**
- `backend/app/skills/executor_backend.py` — `ExecutorBackend` Protocol + `SkillExecutorBackend`(适配 SkillExecutor)
- `backend/app/chatloop/code_interpreter_tool.py` — `CodeInterpreterArgs` + `CodeInterpreterTool`(InProcessTool)
- `backend/tests/unit/skills/test_execute_source.py` — execute_source L0 测试
- `backend/tests/unit/skills/test_executor_backend.py` — backend 适配 L0 测试
- `backend/tests/unit/chatloop/test_code_interpreter_tool.py` — 工具 L0 测试
- `backend/tests/unit/chatloop/test_loop_chart_extract.py` — loop 抽图 L0 测试
- `frontend/src/components/chat/PlotlySpecRenderer.tsx` — plotly 渲染器
- `frontend/src/components/chat/ChartMessage.tsx` — chart 消息渲染器
- `frontend/src/components/chat/__tests__/PlotlySpecRenderer.test.tsx`
- `frontend/src/store/__tests__/current-chat-chart.test.ts`

**修改:**
- `backend/app/skills/skill_executor.py` — 加 `execute_source` 方法
- `backend/app/chatloop/tool_docs.py` — 加 `run_python` ToolDoc + DEFERRED_TOOLS
- `backend/app/chatloop/events.py` — EventType 加 `"chart"`
- `backend/app/chatloop/loop.py` — dispatch 后 apply_results 前抽图发事件
- `backend/app/chatloop/worker_wiring.py` — register_inprocess 加 CodeInterpreterTool
- `pyproject.toml` — 加 `[project.optional-dependencies] code-interpreter`
- `frontend/src/types/chat.ts` — PlotlySpec / ChartEvent / message_type 'chart' / ChatMessage.chart_spec
- `frontend/src/store/current-chat.ts` — dispatchEvent 加 `case 'chart'`
- `frontend/src/components/chat/MessageList.tsx` — MessageRouter 加 `case 'chart'`
- `frontend/package.json` — react-plotly.js + plotly.js

---

## Phase 1 — 沙箱内联源码执行(纯后端,无 chatloop 依赖)

### Task 1: `SkillExecutor.execute_source` 内联源码入口

**Files:**
- Modify: `backend/app/skills/skill_executor.py`
- Test: `backend/tests/unit/skills/test_execute_source.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/skills/test_execute_source.py
"""execute_source — SkillExecutor 内联源码执行入口的 L0 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.skills.skill_executor import SkillExecutor


@pytest.fixture
def executor(tmp_path: Path) -> SkillExecutor:
    # skills_root 对 execute_source 无意义(不读磁盘脚本),给个空目录即可。
    return SkillExecutor(skills_root=tmp_path / "skills", workdir_root=tmp_path / "wd")


@pytest.mark.asyncio
async def test_execute_source_ok_returns_stdout_json(executor: SkillExecutor) -> None:
    src = (
        "import sys, json\n"
        "d = json.load(sys.stdin)\n"
        "print(json.dumps({'result': d['a'] + d['b']}))\n"
    )
    res = await executor.execute_source(source=src, payload={"a": 2, "b": 3})
    assert res.ok is True
    assert res.stdout_json == {"result": 5}


@pytest.mark.asyncio
async def test_execute_source_rejects_banned_open(executor: SkillExecutor) -> None:
    src = "open('/etc/passwd')\n"
    res = await executor.execute_source(source=src, payload={})
    assert res.ok is False
    assert res.error is not None
    assert res.error.kind == "safety_scan_rejected"


@pytest.mark.asyncio
async def test_execute_source_non_zero_exit_carries_stderr(executor: SkillExecutor) -> None:
    src = "raise ValueError('boom')\n"
    res = await executor.execute_source(source=src, payload={})
    assert res.ok is False
    assert res.error is not None
    assert res.error.kind == "non_zero_exit"
    assert "boom" in res.stderr_text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/unit/skills/test_execute_source.py -v`
Expected: FAIL — `AttributeError: 'SkillExecutor' object has no attribute 'execute_source'`

- [ ] **Step 3: 实现 execute_source**

在 `backend/app/skills/skill_executor.py` 的 `SkillExecutor` 类里(`execute` 方法之后)加:

```python
    async def execute_source(
        self,
        *,
        source: str,
        payload: dict[str, Any],
        timeout_s: int | None = None,
    ) -> SkillExecutionResult:
        """执行 LLM 当场写的内联源码(代码解释器用)。

        复用 execute() 的全套沙箱(scan_script_safety / rlimit / 断网 env 白名单 /
        workdir / stdin-payload / stdout-JSON / 超时 SIGKILL),区别只在源从字符串来:
        先 AST 扫描内联源码,再写进一次性 workdir 的临时 .py,走同一个 _run_subprocess。
        """
        from app.skills.skill_safety import SafetyScanError, scan_script_safety  # noqa: PLC0415

        timeout = min(timeout_s or self._default_timeout_s, self._max_timeout_s)
        # 合成 ref —— execute_source 不读磁盘脚本,ref 仅用于结果的 skill_name/script_path
        # 标识字段(SkillScriptRef 校验 script_path 必须以 'scripts/' 开头)。
        ref = SkillScriptRef(skill_name="_interpreter", script_path="scripts/interp.py")

        try:
            scan_script_safety(source)
        except SafetyScanError as exc:
            return _err_result(
                ref,
                exit_code=-1,
                err=SkillExecutionError(kind="safety_scan_rejected", message=str(exc)),
            )

        run_id = uuid.uuid4().hex[:8]
        with make_skill_workdir(run_id=run_id, root=self._workdir_root) as wd:
            script_full = wd / "interp.py"
            script_full.write_text(source, encoding="utf-8")
            return await self._run_subprocess(
                ref, script_full, SkillScriptArgs(payload=payload), wd, timeout
            )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/unit/skills/test_execute_source.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/skills/skill_executor.py backend/tests/unit/skills/test_execute_source.py
git commit -m "feat(skills): SkillExecutor.execute_source — 内联源码沙箱执行入口"
```

---

### Task 2: `ExecutorBackend` 接口 + `SkillExecutorBackend`

**Files:**
- Create: `backend/app/skills/executor_backend.py`
- Test: `backend/tests/unit/skills/test_executor_backend.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/skills/test_executor_backend.py
"""SkillExecutorBackend — ExecutorBackend 适配层 L0 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.skills.executor_backend import SkillExecutorBackend
from app.skills.skill_executor import SkillExecutor


@pytest.mark.asyncio
async def test_backend_run_code_delegates_to_execute_source(tmp_path: Path) -> None:
    executor = SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd")
    backend = SkillExecutorBackend(executor)
    src = "import sys, json; print(json.dumps({'result': json.load(sys.stdin)['x'] * 10}))"
    res = await backend.run_code(source=src, data={"x": 4}, timeout_s=10)
    assert res.ok is True
    assert res.stdout_json == {"result": 40}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/unit/skills/test_executor_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.skills.executor_backend'`

- [ ] **Step 3: 实现**

```python
# backend/app/skills/executor_backend.py
"""ExecutorBackend — 代码解释器的执行后端抽象(spec § 4)。

v1.0 唯一实现 SkillExecutorBackend(复用 subprocess+rlimit+AST 沙箱);
DockerExecutorBackend 是 v1.x 留口子——接口已定,真要更强隔离再实装,
工具层(CodeInterpreterTool)只依赖本 Protocol,不动工具就能换后端。
"""

from __future__ import annotations

from typing import Any, Protocol

from app.skills.script_schemas import SkillExecutionResult
from app.skills.skill_executor import SkillExecutor


class ExecutorBackend(Protocol):
    """代码执行后端契约。"""

    async def run_code(
        self, *, source: str, data: dict[str, Any], timeout_s: int
    ) -> SkillExecutionResult: ...


class SkillExecutorBackend:
    """v1.0 后端 —— 委派给 SkillExecutor.execute_source。"""

    def __init__(self, executor: SkillExecutor) -> None:
        self._executor = executor

    async def run_code(
        self, *, source: str, data: dict[str, Any], timeout_s: int
    ) -> SkillExecutionResult:
        return await self._executor.execute_source(
            source=source, payload=data, timeout_s=timeout_s
        )


__all__ = ["ExecutorBackend", "SkillExecutorBackend"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/unit/skills/test_executor_backend.py -v`
Expected: PASS(1 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/skills/executor_backend.py backend/tests/unit/skills/test_executor_backend.py
git commit -m "feat(skills): ExecutorBackend 接口 + SkillExecutorBackend(Docker 留 v1.x 口)"
```

---

## Phase 2 — 工具本体

### Task 3: plotly optional extra + 装包冒烟

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 加 optional extra**

在 `pyproject.toml` 的 `[project.optional-dependencies]` 段加一组(pandas/numpy 已在 base,只需 plotly):

```toml
code-interpreter = [
    "plotly>=5.17",
]
```

- [ ] **Step 2: 在后端运行 venv 装包**

> 环境约定(见用户记忆):后端跑在 WSL `fria-venv`,装包走 http 代理 7897,不用 `uv run`。

Run(WSL):
```bash
cd backend && pip install -e '.[code-interpreter]' --proxy http://127.0.0.1:7897
```
Expected: plotly 安装成功

- [ ] **Step 3: 冒烟 import 链(spec 风险项:装错 venv 则脚本 import 失败)**

> 约定 `verify-import-chain-with-smoke-test`:spec 谈 import 行为必须实测。沙箱子进程用 `sys.executable` 启动,与后端同解释器,故必须在后端 venv 实测。

Run(WSL,后端 venv):
```bash
python -c "import plotly; import plotly.graph_objects as go; print(go.Figure().to_dict().keys())"
```
Expected: `dict_keys(['data', 'layout'])`(无 ImportError)

- [ ] **Step 4: 提交**

```bash
git add pyproject.toml
git commit -m "build: 加 code-interpreter optional extra(plotly)"
```

---

### Task 4: `CodeInterpreterTool`

**Files:**
- Create: `backend/app/chatloop/code_interpreter_tool.py`
- Test: `backend/tests/unit/chatloop/test_code_interpreter_tool.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/chatloop/test_code_interpreter_tool.py
"""CodeInterpreterTool — run_python 工具 L0 测试(用 Fake backend,不起真子进程)。"""

from __future__ import annotations

from typing import Any

import pytest

from app.chatloop.code_interpreter_tool import CodeInterpreterArgs, CodeInterpreterTool
from app.skills.script_schemas import SkillExecutionError, SkillExecutionResult
from app.tools.base import ToolError


class _FakeBackend:
    def __init__(self, result: SkillExecutionResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def run_code(self, *, source: str, data: dict[str, Any], timeout_s: int):
        self.calls.append({"source": source, "data": data, "timeout_s": timeout_s})
        return self._result


def _ok(stdout: dict[str, Any]) -> SkillExecutionResult:
    return SkillExecutionResult(
        ok=True, stdout_json=stdout, stderr_text="", exit_code=0,
        elapsed_s=0.1, skill_name="_interpreter", script_path="scripts/interp.py",
    )


def _err(kind: str, stderr: str) -> SkillExecutionResult:
    return SkillExecutionResult(
        ok=False, stdout_json=None, stderr_text=stderr, exit_code=1,
        elapsed_s=0.1, skill_name="_interpreter", script_path="scripts/interp.py",
        error=SkillExecutionError(kind=kind, message="x"),
    )


@pytest.mark.asyncio
async def test_ok_returns_result_and_figures() -> None:
    backend = _FakeBackend(_ok({"result": {"corr": 0.83}, "figures": [{"data": [], "layout": {}}]}))
    tool = CodeInterpreterTool(backend=backend)
    out = await tool.run_with_state(CodeInterpreterArgs(code="print('x')", data={"k": 1}), state=None)
    assert out["result"] == {"corr": 0.83}
    assert out["figures"] == [{"data": [], "layout": {}}]
    assert backend.calls[0]["data"] == {"k": 1}


@pytest.mark.asyncio
async def test_missing_figures_defaults_empty_list() -> None:
    backend = _FakeBackend(_ok({"result": 42}))
    tool = CodeInterpreterTool(backend=backend)
    out = await tool.run_with_state(CodeInterpreterArgs(code="x=1"), state=None)
    assert out["figures"] == []


@pytest.mark.asyncio
async def test_exec_failure_raises_toolerror_with_stderr() -> None:
    backend = _FakeBackend(_err("non_zero_exit", "Traceback ... ValueError: boom"))
    tool = CodeInterpreterTool(backend=backend)
    with pytest.raises(ToolError) as ei:
        await tool.run_with_state(CodeInterpreterArgs(code="raise ValueError"), state=None)
    msg = str(ei.value)
    assert msg.startswith("[")  # 指导性前缀 → hub 原样透出给模型自纠
    assert "boom" in msg
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/unit/chatloop/test_code_interpreter_tool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.chatloop.code_interpreter_tool'`

- [ ] **Step 3: 实现**

```python
# backend/app/chatloop/code_interpreter_tool.py
"""CodeInterpreterTool — name="run_python"(spec § 3)。

LLM 当场写 Python,经 ExecutorBackend 沙箱执行,返回 {result, figures, stderr,
elapsed_s}。figures(plotly fig.to_dict() 列表)由 ToolLoop 抽出发 chart 事件并从
输出剥离 —— 工具本身只负责"执行 + 透传",不碰 SSE/缓存(职责单一)。

执行失败(safety_scan_rejected / non_zero_exit / timeout / stdout_invalid_json)
→ 抛 ToolError(带 stderr),hub 的 _guidance_error 见 '[' 前缀原样透出,LLM 据
stderr 改代码重试(chatloop while 循环天然承载自纠)。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.chatloop.inprocess import InProcessTool
from app.chatloop.state import ChatLoopState
from app.skills.executor_backend import ExecutorBackend
from app.tools.base import ToolError

_STDERR_FEEDBACK_LEN = 500  # 回喂模型自纠的 stderr 截断


class CodeInterpreterArgs(BaseModel):
    code: str
    data: dict[str, Any] | None = None


class CodeInterpreterTool(InProcessTool):
    name = "run_python"
    description = "执行 Python 做数值计算/画交互分析图(plotly)。需二次计算或可视化时用。"
    args_schema = CodeInterpreterArgs

    def __init__(self, *, backend: ExecutorBackend, timeout_s: int = 30) -> None:
        self._backend = backend
        self._timeout_s = timeout_s

    async def run_with_state(self, args: BaseModel, state: ChatLoopState) -> dict[str, Any]:
        args = CodeInterpreterArgs.model_validate(args.model_dump())
        result = await self._backend.run_code(
            source=args.code, data=args.data or {}, timeout_s=self._timeout_s
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


__all__ = ["CodeInterpreterArgs", "CodeInterpreterTool"]
```

> 注:`state=None` 在测试里可行,因为 run_with_state 不读 state。签名仍按 InProcessTool 协议保留 state 形参(hub 注入)。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/unit/chatloop/test_code_interpreter_tool.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/code_interpreter_tool.py backend/tests/unit/chatloop/test_code_interpreter_tool.py
git commit -m "feat(chatloop): CodeInterpreterTool(run_python)"
```

---

### Task 5: tool_docs 条目 + 延迟组挂接

**Files:**
- Modify: `backend/app/chatloop/tool_docs.py`
- Test: `backend/tests/unit/chatloop/test_tool_docs.py`(若不存在则新建)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/chatloop/test_tool_docs.py  (若已存在,追加这两个测试函数)
from app.chatloop.tool_docs import DEFERRED_TOOLS, TOOL_DOCS, thin_schema


def test_run_python_in_deferred_group() -> None:
    assert "run_python" in DEFERRED_TOOLS
    doc = TOOL_DOCS["run_python"]
    assert doc.group == "deferred"
    assert doc.thin_required == {"code": "string"}


def test_run_python_thin_schema_keeps_required_code() -> None:
    schema = thin_schema(TOOL_DOCS["run_python"])
    params = schema["function"]["parameters"]
    assert "code" in params["properties"]
    assert params["required"] == ["code"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/unit/chatloop/test_tool_docs.py -k run_python -v`
Expected: FAIL — `KeyError: 'run_python'`

- [ ] **Step 3: 加 ToolDoc 条目**

在 `backend/app/chatloop/tool_docs.py` 的 `TOOL_DOCS` dict 末尾(`read_cached_result` 条目后、dict 闭合前)加:

```python
    "run_python": ToolDoc(
        name="run_python",
        group="deferred",
        brief="执行 Python 做数值计算/画交互分析图(plotly)。需二次计算或可视化时用。",
        doc=(
            "执行 LLM 当场写的 Python 脚本:数值计算 + 用 plotly 画交互式数据分析图。\n"
            "何时用:用户要的不是单点查询,而是要对数据做二次计算(相关性/增速/加权/"
            "统计)或要一张图(趋势/对比/分布)。触发词:画图、趋势图、对比图、算一下、"
            "相关性、占比、分布。\n"
            "何时不用:能被单个数据工具直接回答的(查现价→get_stock_quote,查财报→"
            "get_financial_statements)别绕到 run_python;跑预审技能脚本(如 DCF)→ "
            "run_skill_script。\n"
            "参数:\n"
            " - code(str,必填)—— 完整 Python 脚本。从 sys.stdin 读 data(json.load),"
            "把结果 print 成一个 JSON:{\"result\": <可序列化结论>, \"figures\": "
            "[<plotly fig.to_dict()>, ...]}。figures 可空。\n"
            " - data(object,可选)—— 喂给脚本 stdin 的 JSON(把现有工具拿到的数据传进来)。\n"
            "示例:run_python(code='import sys,json,plotly.express as px; "
            "d=json.load(sys.stdin); fig=px.line(d[\"rows\"]); "
            "print(json.dumps({\"result\":\"ok\",\"figures\":[fig.to_dict()]}))', "
            "data={'rows': [...]})。\n"
            "硬约束:沙箱无网络、无文件读写(open 被禁)、无状态(变量不跨调用保留);"
            "可用 pandas/numpy/plotly;超时 30s;图必须用 plotly(matplotlib 写文件会失败)。"
        ),
        thin_required={"code": "string"},
    ),
```

在 `DEFERRED_TOOLS` 列表末尾加 `"run_python"`:

```python
DEFERRED_TOOLS = [
    "get_market_indicators",
    "get_corporate_actions",
    "get_news",
    "web_search",
    "compare_stocks",
    "memory_write",
    "run_skill_script",
    "read_cached_result",
    "run_python",
]
```

同时把模块顶部 docstring 的「14 个工具」改为「15 个工具」(line 46 注释):`# 15 个工具文档(8 金融 + 2 记忆 + 2 技能 + 升级 + 取回 + 代码解释器)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/unit/chatloop/test_tool_docs.py -k run_python -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/tool_docs.py backend/tests/unit/chatloop/test_tool_docs.py
git commit -m "feat(chatloop): run_python tool_docs 条目 + 延迟组挂接"
```

---

### Task 6: 在 worker_wiring 注册工具

**Files:**
- Modify: `backend/app/chatloop/worker_wiring.py`
- Test: `backend/tests/unit/chatloop/test_worker_wiring_run_python.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/chatloop/test_worker_wiring_run_python.py
"""run_python 注册进 turn ToolHub 的 L0 测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.chatloop.events import SeqCounter
from app.chatloop.gates import GateConfig
from app.chatloop.worker_wiring import HeavySingletons, build_turn_components
from app.skills.skill_executor import SkillExecutor


class _EmptyRegistry:
    def list_for_llm(self) -> list[dict[str, Any]]:
        return []

    def get(self, name: str) -> Any:  # pragma: no cover
        raise KeyError(name)


@pytest.mark.asyncio
async def test_run_python_registered(tmp_path: Path) -> None:
    singletons = HeavySingletons(
        llm=object(),
        registry=_EmptyRegistry(),
        memory=object(),
        loader=object(),
        executor=SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd"),
        cache=None,
        skill_listing="## 可用技能",
        gate_cfg=GateConfig(),
    )

    async def _emit(_ev: Any) -> None:  # noqa: ANN401
        return None

    comp = build_turn_components(singletons, emit=_emit, seq_counter=SeqCounter())
    names = [s["function"]["name"] for s in comp.tool_hub.schemas_for_llm()]
    assert "run_python" in names
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/unit/chatloop/test_worker_wiring_run_python.py -v`
Expected: FAIL — `assert 'run_python' in [...]`(未注册)

- [ ] **Step 3: 注册工具**

在 `backend/app/chatloop/worker_wiring.py` 顶部 import 区加:

```python
from app.chatloop.code_interpreter_tool import CodeInterpreterTool
from app.skills.executor_backend import SkillExecutorBackend
```

在 `build_turn_components` 的 `hub.register_inprocess([...])` 列表里(`ReadCachedResultTool(...)` 后)加一行:

```python
            ReadCachedResultTool(cache=singletons.cache),
            CodeInterpreterTool(backend=SkillExecutorBackend(singletons.executor)),
        ]
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/unit/chatloop/test_worker_wiring_run_python.py -v`
Expected: PASS(1 passed)

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/worker_wiring.py backend/tests/unit/chatloop/test_worker_wiring_run_python.py
git commit -m "feat(chatloop): 注册 run_python 进 turn ToolHub"
```

---

## Phase 3 — chart 事件接线(后端)

### Task 7: `chart` EventType + ToolLoop 抽图发事件

**Files:**
- Modify: `backend/app/chatloop/events.py`
- Modify: `backend/app/chatloop/loop.py`
- Test: `backend/tests/unit/chatloop/test_loop_chart_extract.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/chatloop/test_loop_chart_extract.py
"""ToolLoop._extract_and_emit_charts — figures 抽出发 chart 事件 + 从输出剥离。"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.schemas import ToolResult
from app.chatloop.events import LoopEvent, SeqCounter
from app.chatloop.loop import ToolLoop


def _make_loop(events: list[LoopEvent]) -> ToolLoop:
    async def _emit(ev: LoopEvent) -> None:
        events.append(ev)

    class _Hub:
        def schemas_for_llm(self) -> list[dict[str, Any]]:
            return []

        async def dispatch(self, calls: Any, state: Any) -> list[ToolResult]:  # pragma: no cover
            return []

    return ToolLoop(
        llm=object(), tool_hub=_Hub(), context_deps=object(),
        emit=_emit, seq_counter=SeqCounter(),
    )


class _State:
    request_id = "req-1"
    step = 2


@pytest.mark.asyncio
async def test_figures_emitted_as_chart_events_and_stripped() -> None:
    events: list[LoopEvent] = []
    loop = _make_loop(events)
    fig_a = {"data": [{"type": "scatter"}], "layout": {}}
    fig_b = {"data": [{"type": "bar"}], "layout": {}}
    results = [
        ToolResult(
            tool_name="run_python", args={}, success=True,
            output={"result": {"corr": 0.8}, "figures": [fig_a, fig_b]}, latency_ms=5,
        ),
        ToolResult(
            tool_name="get_stock_quote", args={}, success=True,
            output={"price": 100}, latency_ms=5,
        ),
    ]

    await loop._extract_and_emit_charts(results, _State())  # type: ignore[arg-type]

    chart_events = [e for e in events if e.type == "chart"]
    assert len(chart_events) == 2
    assert chart_events[0].data["figure"] == fig_a
    assert chart_events[0].data["chart_id"] == "req-1-2-0-0"
    assert chart_events[1].data["chart_id"] == "req-1-2-0-1"
    # figures 已从 LLM 可见的 output 剥离,替换成计数标记
    assert "figures" not in results[0].output
    assert results[0].output["charts_rendered"] == 2
    assert results[0].output["result"] == {"corr": 0.8}
    # 无 figures 的工具输出不动
    assert results[1].output == {"price": 100}


@pytest.mark.asyncio
async def test_empty_figures_no_events_no_marker() -> None:
    events: list[LoopEvent] = []
    loop = _make_loop(events)
    results = [
        ToolResult(
            tool_name="run_python", args={}, success=True,
            output={"result": 1, "figures": []}, latency_ms=5,
        )
    ]
    await loop._extract_and_emit_charts(results, _State())  # type: ignore[arg-type]
    assert [e for e in events if e.type == "chart"] == []
    assert "figures" not in results[0].output
    assert "charts_rendered" not in results[0].output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && pytest tests/unit/chatloop/test_loop_chart_extract.py -v`
Expected: FAIL — `AttributeError: 'ToolLoop' object has no attribute '_extract_and_emit_charts'`

- [ ] **Step 3a: EventType 加 `"chart"`**

`backend/app/chatloop/events.py` 的 `EventType` Literal 里加 `"chart"`(放 `"tool_error"` 之后):

```python
EventType = Literal[
    "step_start",
    "token",
    "reasoning",
    "tool_call",
    "tool_start",
    "tool_end",
    "tool_error",
    "chart",
    "skill_load",
    "steer_merged",
    "loop_halt",
    "approval_request",
    "escalate_request",
    "cost_update",
    "done",
    "error",
]
```

- [ ] **Step 3b: ToolLoop 加抽图方法 + 在主循环调用**

在 `backend/app/chatloop/loop.py` 的 `ToolLoop` 类里(`_merge_results` 之前)加方法:

```python
    async def _extract_and_emit_charts(
        self, results: list[ToolResult], state: ChatLoopState
    ) -> None:
        """把工具输出里的 figures 抽出发 chart 事件,并从 output 剥离(spec § 5)。

        figure JSON 可达数 KB,绝不进 LLM 上下文(窗口铁律)—— 图只走 chart 事件
        旁路渲染到前端;LLM 侧 output 的 figures 被替换为 charts_rendered 计数。
        chart_id 确定性:{request_id}-{step}-{结果序}-{图序}(无随机,可复现)。
        """
        for ridx, r in enumerate(results):
            if not (r.success and isinstance(r.output, dict)):
                continue
            figures = r.output.get("figures")
            if not isinstance(figures, list) or not figures:
                # 无图:把空 figures 键也清掉,保持 LLM 侧 output 干净
                r.output.pop("figures", None)
                continue
            for fidx, fig in enumerate(figures):
                chart_id = f"{state.request_id}-{state.step}-{ridx}-{fidx}"
                await self._emit("chart", state.step, chart_id=chart_id, figure=fig)
            r.output.pop("figures", None)
            r.output["charts_rendered"] = len(figures)
```

在 `run()` 主循环里,`merged = self._merge_results(...)`(约 loop.py:190)与 `state = apply_results(...)`(约 loop.py:191)之间插一行:

```python
            merged = self._merge_results(step_result.tool_calls, allowed, results)
            await self._extract_and_emit_charts(merged, state)
            state = apply_results(state, merged, step_result.tool_calls)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && pytest tests/unit/chatloop/test_loop_chart_extract.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 后端回归 + 提交**

Run: `cd backend && pytest tests/unit/chatloop -q`
Expected: 全绿(无既有用例回归)

```bash
git add backend/app/chatloop/events.py backend/app/chatloop/loop.py backend/tests/unit/chatloop/test_loop_chart_extract.py
git commit -m "feat(chatloop): chart 事件 — figures 抽出发事件并剥离出 LLM 上下文"
```

---

## Phase 4 — 前端渲染

### Task 8: plotly 依赖 + PlotlySpecRenderer

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/components/chat/PlotlySpecRenderer.tsx`
- Test: `frontend/src/components/chat/__tests__/PlotlySpecRenderer.test.tsx`

- [ ] **Step 1: 装依赖**

> 前端包管理走 Windows pnpm + http 代理(见用户记忆 understand-anything 工具链条目的 pnpm 约定)。

Run:
```bash
cd frontend && pnpm add react-plotly.js plotly.js && pnpm add -D @types/react-plotly.js
```
Expected: 三个包写入 package.json

- [ ] **Step 2: 写失败测试**

```tsx
// frontend/src/components/chat/__tests__/PlotlySpecRenderer.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { PlotlySpecRenderer } from '../PlotlySpecRenderer'
import type { PlotlySpec } from '@/types/chat'

// plotly.js 在 jsdom 跑不起来,mock react-plotly.js 为占位 div(只验数据透传/兜底分支)。
vi.mock('react-plotly.js', () => ({
  default: ({ data }: { data: unknown[] }) => (
    <div data-testid="plot" data-traces={String((data ?? []).length)} />
  ),
}))

describe('PlotlySpecRenderer', () => {
  it('renders a Plot with the figure traces', () => {
    const spec: PlotlySpec = { type: 'plotly', figure: { data: [{ type: 'scatter' }], layout: {} } }
    render(<PlotlySpecRenderer spec={spec} />)
    expect(screen.getByTestId('plot').getAttribute('data-traces')).toBe('1')
  })

  it('shows a fallback for an invalid spec', () => {
    // @ts-expect-error 故意传非法 spec
    render(<PlotlySpecRenderer spec={{ type: 'plotly' }} />)
    expect(screen.getByText(/plotly spec invalid/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd frontend && pnpm vitest run src/components/chat/__tests__/PlotlySpecRenderer.test.tsx`
Expected: FAIL — 找不到模块 `../PlotlySpecRenderer`

- [ ] **Step 4: 实现(照搬 ChartSpecRenderer 的结构 + 兜底)**

```tsx
// frontend/src/components/chat/PlotlySpecRenderer.tsx
import Plot from 'react-plotly.js'
import type { PlotlySpec } from '@/types/chat'

export interface PlotlySpecRendererProps {
  spec: PlotlySpec
}

export function PlotlySpecRenderer({ spec }: PlotlySpecRendererProps) {
  if (
    !spec ||
    spec.type !== 'plotly' ||
    !spec.figure ||
    !Array.isArray(spec.figure.data)
  ) {
    return (
      <div style={{ padding: 12, border: '1px dashed #ff4d4f', color: '#ff4d4f' }}>
        plotly spec invalid
      </div>
    )
  }
  return (
    <Plot
      data={spec.figure.data}
      layout={{ autosize: true, ...(spec.figure.layout ?? {}) }}
      config={{ displaylogo: false, responsive: true }}
      style={{ width: '100%', height: 320 }}
      useResizeHandler
    />
  )
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && pnpm vitest run src/components/chat/__tests__/PlotlySpecRenderer.test.tsx`
Expected: PASS(2 passed)

- [ ] **Step 6: 提交**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/components/chat/PlotlySpecRenderer.tsx frontend/src/components/chat/__tests__/PlotlySpecRenderer.test.tsx
git commit -m "feat(frontend): PlotlySpecRenderer + plotly 依赖"
```

---

### Task 9: 前端类型(PlotlySpec / ChartEvent / message_type 'chart')

**Files:**
- Modify: `frontend/src/types/chat.ts`

- [ ] **Step 1: 加类型**

在 `frontend/src/types/chat.ts`:

(a) `MessageType` 加 `'chart'`:
```ts
export type MessageType = 'text' | 'tool_call' | 'tool_result' | 'research_report' | 'escalation' | 'system' | 'chart'
```

(b) `ChartSpec` 之后加 `PlotlySpec`:
```ts
export interface PlotlyFigure {
  data: Record<string, unknown>[]
  layout?: Record<string, unknown>
}

export interface PlotlySpec {
  type: 'plotly'
  figure: PlotlyFigure
}
```

(c) `ToolErrorEvent` 之后加 `ChartEvent`:
```ts
export interface ChartEvent extends BaseEvent {
  type: 'chart'
  chart_id: string
  figure: PlotlyFigure
}
```

(d) `SSEEvent` 联合里加 `| ChartEvent`(放 `ToolErrorEvent` 后):
```ts
  | ToolErrorEvent
  | ChartEvent
```

(e) `ChatMessage` 接口加可选字段:
```ts
  // run_python 产出的交互图(message_type='chart');由 chart SSE 事件构造的本地消息携带。
  chart_spec?: PlotlySpec
```

- [ ] **Step 2: 类型检查通过**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: 无新增类型错误(已存在的无关错误忽略)

- [ ] **Step 3: 提交**

```bash
git add frontend/src/types/chat.ts
git commit -m "feat(frontend): PlotlySpec / ChartEvent / message_type 'chart' 类型"
```

---

### Task 10: store dispatchEvent 处理 chart 事件

**Files:**
- Modify: `frontend/src/store/current-chat.ts`
- Test: `frontend/src/store/__tests__/current-chat-chart.test.ts`

- [ ] **Step 1: 写失败测试**

```ts
// frontend/src/store/__tests__/current-chat-chart.test.ts
import { beforeEach, describe, expect, it } from 'vitest'
import { currentChatActions, currentChatState } from '../current-chat'
import type { ChartEvent } from '@/types/chat'

describe('current-chat chart event', () => {
  beforeEach(() => {
    currentChatActions.setSession('sess-1', [])
  })

  it('chart event pushes a chart message carrying the figure', () => {
    const ev: ChartEvent = {
      type: 'chart',
      seq: 1,
      chart_id: 'req-1-2-0-0',
      figure: { data: [{ type: 'scatter' }], layout: {} },
    }
    currentChatActions.dispatchEvent(ev)
    const chartMsgs = currentChatState.messages.filter((m) => m.message_type === 'chart')
    expect(chartMsgs).toHaveLength(1)
    expect(chartMsgs[0].chart_spec?.figure.data).toHaveLength(1)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && pnpm vitest run src/store/__tests__/current-chat-chart.test.ts`
Expected: FAIL — chartMsgs 长度为 0(chart 走 default 进了 toolEvents,没进 messages)

- [ ] **Step 3: 加 case 'chart'**

在 `frontend/src/store/current-chat.ts`:

(a) 顶部 import 类型补 `ChartEvent`:
```ts
import type {
  ChartEvent,
  ChatMessage,
  CostUpdateEvent,
  ...
}
```

(b) 在 `dispatchEvent` 的 switch 里,`case 'tool_error':` 之后加:
```ts
      case 'chart': {
        const e = ev as ChartEvent
        if (currentChatState.session_id) {
          currentChatState.messages.push({
            id: `local-chart-${e.chart_id}`,
            session_id: currentChatState.session_id,
            role: 'assistant',
            content: '',
            message_type: 'chart',
            tool_call_data: null,
            research_report_id: null,
            research_report_summary: null,
            created_at: new Date().toISOString(),
            chart_spec: { type: 'plotly', figure: e.figure },
          })
        }
        break
      }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && pnpm vitest run src/store/__tests__/current-chat-chart.test.ts`
Expected: PASS(1 passed)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/store/current-chat.ts frontend/src/store/__tests__/current-chat-chart.test.ts
git commit -m "feat(frontend): chart 事件 → chart 消息入 messages"
```

---

### Task 11: ChartMessage + MessageRouter 路由

**Files:**
- Create: `frontend/src/components/chat/ChartMessage.tsx`
- Modify: `frontend/src/components/chat/MessageList.tsx`
- Test: `frontend/src/components/chat/__tests__/ChartMessage.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
// frontend/src/components/chat/__tests__/ChartMessage.test.tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ChartMessage } from '../ChartMessage'
import type { ChatMessage } from '@/types/chat'

vi.mock('react-plotly.js', () => ({
  default: ({ data }: { data: unknown[] }) => (
    <div data-testid="plot" data-traces={String((data ?? []).length)} />
  ),
}))

function chartMsg(): ChatMessage {
  return {
    id: 'local-chart-x',
    session_id: 's',
    role: 'assistant',
    content: '',
    message_type: 'chart',
    tool_call_data: null,
    research_report_id: null,
    research_report_summary: null,
    created_at: '2026-06-11T00:00:00Z',
    chart_spec: { type: 'plotly', figure: { data: [{ type: 'bar' }], layout: {} } },
  }
}

describe('ChartMessage', () => {
  it('renders the plotly figure', () => {
    render(<ChartMessage message={chartMsg()} />)
    expect(screen.getByTestId('plot').getAttribute('data-traces')).toBe('1')
  })

  it('renders nothing when chart_spec missing', () => {
    const m = { ...chartMsg(), chart_spec: undefined }
    const { container } = render(<ChartMessage message={m} />)
    expect(container.querySelector('[data-testid="plot"]')).toBeNull()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && pnpm vitest run src/components/chat/__tests__/ChartMessage.test.tsx`
Expected: FAIL — 找不到模块 `../ChartMessage`

- [ ] **Step 3a: 实现 ChartMessage**

```tsx
// frontend/src/components/chat/ChartMessage.tsx
import type { ChatMessage } from '@/types/chat'
import { PlotlySpecRenderer } from './PlotlySpecRenderer'

export interface ChartMessageProps {
  message: ChatMessage
}

export function ChartMessage({ message }: ChartMessageProps) {
  if (!message.chart_spec) return null
  return (
    <div data-testid="chart-message" style={{ width: '100%' }}>
      <PlotlySpecRenderer spec={message.chart_spec} />
    </div>
  )
}
```

- [ ] **Step 3b: MessageRouter 加 case 'chart'**

在 `frontend/src/components/chat/MessageList.tsx`:

(a) 顶部 import:
```ts
import { ChartMessage } from './ChartMessage'
```

(b) `MessageRouter` 的 switch 里,`case 'tool_call':` 之后加:
```ts
      case 'chart':
        return <ChartMessage message={message} />
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && pnpm vitest run src/components/chat/__tests__/ChartMessage.test.tsx`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/chat/ChartMessage.tsx frontend/src/components/chat/MessageList.tsx frontend/src/components/chat/__tests__/ChartMessage.test.tsx
git commit -m "feat(frontend): ChartMessage + MessageRouter 路由 chart 消息"
```

---

## Phase 5 — 评测 + 文档 + 端到端守护

### Task 12: 工具选择 eval 金标准

**Files:**
- Modify: `backend/eval/tool_selection/golden.jsonl`(已存在,JSONL 每行一 case)
- Test: `backend/tests/unit/eval_tool_selection/test_golden_schema.py`(已存在,加载即校验)

> golden.jsonl 行 schema(实测):`{"case_id", "category", "user_input", "expected": {...}, "bucket"}`;
> `expected` 至少含一键(`first_tool` / `args_contains` / `not_tools` / `tools_sequence_contains`);
> `bucket` 须在 VALID_BUCKETS(用 `"金融数据"`)。
> **关键语义**:`first_tool` = 第一个被调的工具。需先取数的查询(如「画营收趋势图」会先
> `get_financial_statements`)**first_tool 不是 run_python**;故 run_python 正例只用
> **数据已在 prompt 里内联**的查询(对齐 `data` 参数设计:数据由 LLM 传入)。

- [ ] **Step 1: 追加 3 条正例 + 2 条负例(在 golden.jsonl 末尾)**

run_python 正例(数据内联 → run_python 确为第一个工具;args 是自由 code,故 expected 只给 first_tool):
```jsonl
{"case_id": "ts-pyint-001", "category": "single_tool", "user_input": "帮我把这两组数画成对比折线图:A=[1094,1241,1476,1645,1709],B=[662,739,832,891,920]", "expected": {"first_tool": "run_python"}, "bucket": "金融数据"}
{"case_id": "ts-pyint-002", "category": "single_tool", "user_input": "算一下这两列日收益率的相关系数:x=[0.01,-0.02,0.03,0.005],y=[0.012,-0.018,0.025,0.004]", "expected": {"first_tool": "run_python"}, "bucket": "金融数据"}
{"case_id": "ts-pyint-003", "category": "single_tool", "user_input": "我的持仓市值是 茅台12万、五粮液8万、宁德6万,画个饼图看占比", "expected": {"first_tool": "run_python"}, "bucket": "金融数据"}
```

run_python 负例(单点查询该走数据工具直答,不该绕到 run_python):
```jsonl
{"case_id": "ts-pyint-neg-001", "category": "mutex_boundary", "user_input": "茅台现在多少钱?", "expected": {"first_tool": "get_stock_quote", "not_tools": ["run_python"]}, "bucket": "金融数据"}
{"case_id": "ts-pyint-neg-002", "category": "mutex_boundary", "user_input": "茅台的资产负债率是多少?", "expected": {"first_tool": "get_financial_statements", "not_tools": ["run_python"]}, "bucket": "金融数据"}
```

- [ ] **Step 2: 跑 schema 校验(确定性,无 LLM)—— 验新行能加载 + bucket 合法 + case_id 不重**

Run: `cd backend && pytest tests/unit/eval_tool_selection/test_golden_schema.py -v`
Expected: PASS(新增 5 行被 `load_golden` 接受,floor ≥24 仍满足,无重复 case_id)

- [ ] **Step 3: (可选)跑 live 选择 eval 看真实区分度**

> `--live` 烧真 LLM(spec 评测口径),非必跑;CI 仍只跑 Step 2 的确定性 schema 校验。

Run: `cd backend && python -m eval.tool_selection._cli --live -k pyint`(参数以 `_cli.py` 实际 flag 为准)
Expected: 3 正例首工具命中 run_python,2 负例不误触 run_python

- [ ] **Step 4: 提交**

```bash
git add backend/eval/tool_selection/golden.jsonl
git commit -m "test(eval): run_python 工具选择金标准(3 内联数据正例 + 2 单点查询负例)"
```

---

### Task 13: 端到端真实执行守护测试(integration)

**Files:**
- Create: `backend/tests/integration/test_code_interpreter_e2e.py`

> 这是唯一起真子进程 + 真 plotly 的测试(前面都是 Fake backend)。守护「LLM 写的代码 → 真沙箱 → plotly 图 JSON 往返」整条链。需后端 venv 已装 `code-interpreter` extra(Task 3)。

- [ ] **Step 1: 写测试**

```python
# backend/tests/integration/test_code_interpreter_e2e.py
"""代码解释器端到端:真 subprocess + 真 plotly figure 往返。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.chatloop.code_interpreter_tool import CodeInterpreterArgs, CodeInterpreterTool
from app.skills.executor_backend import SkillExecutorBackend
from app.skills.skill_executor import SkillExecutor

pytest.importorskip("plotly")  # 未装 code-interpreter extra 则跳过


@pytest.mark.asyncio
async def test_run_python_produces_plotly_figure(tmp_path: Path) -> None:
    executor = SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd")
    tool = CodeInterpreterTool(backend=SkillExecutorBackend(executor))
    code = (
        "import sys, json\n"
        "import plotly.express as px\n"
        "d = json.load(sys.stdin)\n"
        "fig = px.line(x=d['x'], y=d['y'])\n"
        "print(json.dumps({'result': {'n': len(d['x'])}, 'figures': [fig.to_dict()]}))\n"
    )
    out = await tool.run_with_state(
        CodeInterpreterArgs(code=code, data={"x": [1, 2, 3], "y": [4, 5, 6]}), state=None
    )
    assert out["result"] == {"n": 3}
    assert len(out["figures"]) == 1
    fig = out["figures"][0]
    assert "data" in fig and "layout" in fig  # plotly figure 形状


@pytest.mark.asyncio
async def test_run_python_network_banned(tmp_path: Path) -> None:
    executor = SkillExecutor(skills_root=tmp_path / "s", workdir_root=tmp_path / "wd")
    tool = CodeInterpreterTool(backend=SkillExecutorBackend(executor))
    from app.tools.base import ToolError

    with pytest.raises(ToolError):
        await tool.run_with_state(
            CodeInterpreterArgs(code="import requests; requests.get('http://x')"), state=None
        )
```

- [ ] **Step 2: 跑测试确认通过**

Run(WSL 后端 venv): `cd backend && pytest tests/integration/test_code_interpreter_e2e.py -v`
Expected: PASS(2 passed)

- [ ] **Step 3: 提交**

```bash
git add backend/tests/integration/test_code_interpreter_e2e.py
git commit -m "test(integration): run_python 端到端 — 真沙箱 + plotly 往返 + 断网守护"
```

---

### Task 14: 沉淀 claude-context 卡片 + spec follow-up

**Files:**
- Create: `docs/claude-context/code-interpreter-run-python-done.md`
- Modify: `CLAUDE.md`(加卡片链接)

- [ ] **Step 1: 写知识卡片(三段式:结论 + Why + How to apply)**

```markdown
---
title: run_python 代码解释器工具 ship
type: project
date: 2026-06-11
---

# 代码解释器工具 run_python(2026-06-11 ship)

**结论**:chat agent 加 `run_python`(延迟组工具)—— LLM 当场写 Python,经复用的
SkillExecutor 沙箱(新增 `execute_source` 内联源码入口)执行,产 plotly 交互图。图经
`chart` SSE 事件旁路渲染(前端 PlotlySpecRenderer + chart 消息),figures 在 loop 的
dispatch→apply_results 之间被剥离,绝不进 LLM 上下文。沙箱底座抽成 `ExecutorBackend`
接口,DockerExecutorBackend 留 v1.x 口。

## Why

- 破「计算进技能脚本(零名额)」旧决策:LLM 自主写代码 ≠ 跑预审脚本,语义不同,值
  一个延迟组工具名额(常驻 ~30 token)。代价是执行不可信代码 → AST 扫描吃重。
- 渲染没复用现成 ECharts chart_spec 链路:手搓 ECharts option 只能覆盖四类且非「分析
  代码」;plotly.express 才是真分析代码,且 `to_json()` 纯内存绕开沙箱 open() ban。
- figures 走 chart 事件不走 message markdown:figure JSON 数 KB,进 message 会污染
  下一 turn 的 LLM 上下文(KV-cache 铁律),旁路事件最干净。

## How to apply

- 改执行后端找 `backend/app/skills/executor_backend.py`(接口)+ `skill_executor.py`
  的 `execute_source`;Docker 版只需新增 backend 实现,不动 `CodeInterpreterTool`。
- 加新「产图」工具:工具 output 放 `figures: [plotly_fig_dict]`,ToolLoop
  `_extract_and_emit_charts` 自动抽出发 chart 事件(约定即接线,无需改 loop)。
- 已知留口(follow-up):图不跨 reload 持久化(reload 从 PG 拉消息无 chart);持仓/
  日线/行业数据工具未接(部分示例端到端不通,见 spec § 9);DockerExecutorBackend。

相关:[[chat-loop-redesign-done]] [[v0.9-skill-loader-l1-l2-l3a-landed]] [[optional-extras-for-heavy-deps]]
```

- [ ] **Step 2: CLAUDE.md 加链接**

在 `CLAUDE.md` 的「Chat Loop 重设计」区块后加一行:
```markdown
### 代码解释器
- [run_python 代码解释器 ship](docs/claude-context/code-interpreter-run-python-done.md) — LLM 写 Python→复用 SkillExecutor 沙箱→plotly 交互图;figures 走 chart 事件不进上下文;ExecutorBackend 留 Docker 口
```

- [ ] **Step 3: 提交**

```bash
git add docs/claude-context/code-interpreter-run-python-done.md CLAUDE.md
git commit -m "docs(claude-context): run_python 代码解释器知识卡片"
```

---

## 自审清单(实施完成后逐项验)

- [ ] 后端全量回归:`cd backend && pytest tests/unit/chatloop tests/unit/skills -q` 全绿
- [ ] 前端全量:`cd frontend && pnpm vitest run` 全绿
- [ ] lint/type:`cd backend && ruff check app/ && mypy app/chatloop/code_interpreter_tool.py app/skills/executor_backend.py`;`cd frontend && pnpm tsc --noEmit`
- [ ] 端到端手验:起后端 + 前端,聊天里发「把 [1,2,3] 和 [4,5,6] 画条折线」,确认:① run_python tool 卡片出现;② 图渲染;③ LLM 回答文字引用了图(上下文里看不到 figure JSON)

---

## 范围外(本计划不做,spec § 9 已记)

- 图跨页面 reload 持久化(需存 figure + GET 端点 + 前端 refetch)
- `get_portfolio_positions` / `get_daily_series` / `get_stock_industry` 数据工具
- `DockerExecutorBackend` 实装
- 会话内有状态 kernel
- `/python ...` slash 强制调用
- **stdout 大小护栏**(spec § 6 列的硬化项):本计划暂不加。理由——子进程已被
  `RLIMIT_AS` 256MB 间接封顶(打印量超不过其内存),而合法 plotly figure 本身就可能
  数十 KB,一刀切的 stdout 上限会误杀正当大图。若日后要加,应设宽松上限(如 8MB)且只
  在 `execute_source` 路径生效,不碰 `execute()` 共享子进程逻辑(避免回归 run_skill_script)。
