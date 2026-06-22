# run_python 长序列数据通道 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 run_python 能算长序列——① 抬截断阈值(单序列不再误截),② 加 data-by-ref 通道(大数据按引用直灌沙箱、不经 LLM)。

**Architecture:** ① 改 `ContextDeps.oversize_result_char_threshold` 默认值 + chat_runner env 覆盖。② run_python 加 `data_refs` 参数(变量名→缓存 ref),`CodeInterpreterTool` 注入 cache,服务端用 `ToolResultCache.get_raw(ref)`+`json.loads` 还原完整结构化数据注入脚本 `data`,带 `{user_id}::` 防越权。

**Tech Stack:** Python 3.12 / pydantic / pytest;测试在 WSL fria-venv 跑。

**spec:** `docs/superpowers/specs/2026-06-16-runpython-large-data-channel-design.md`

**测试前缀**(WSL): `wsl bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && source /home/administrator/fria-venv/bin/activate && set -a && source ../.env && set +a && TUSHARE_MODE=mock python -m pytest ..."`

---

## File Structure

- Modify `backend/app/chatloop/context.py` — `oversize_result_char_threshold` 默认 4000 → 24000。
- Modify `backend/app/tasks/chat_runner.py` — ContextDeps(...) 加 env 覆盖。
- Modify `backend/app/chatloop/code_interpreter_tool.py` — `data_refs` 字段 + `cache` 注入 + 解析逻辑。
- Modify `backend/app/chatloop/worker_wiring.py:245` — 注入 cache 到 CodeInterpreterTool。
- Modify `backend/app/chatloop/tool_docs.py` — run_python 文档加 data_refs。
- Create `backend/tests/unit/chatloop/test_code_interpreter_data_refs.py` — data_refs 三路测试。
- Modify `backend/tests/unit/chatloop/test_loop_oversize_cap.py` — 加新默认值断言。

---

## Task 1: ① 抬截断阈值(默认 + env 覆盖)

**Files:**
- Modify: `backend/app/chatloop/context.py`(ContextDeps 字段)
- Modify: `backend/app/tasks/chat_runner.py`(ContextDeps 构造,~line 256-264)
- Test: `backend/tests/unit/chatloop/test_loop_oversize_cap.py`

- [ ] **Step 1: 写失败测试**(追加到 test_loop_oversize_cap.py 末尾)

```python
def test_default_oversize_threshold_is_24000() -> None:
    # ① 默认阈值抬到 24000(一年单序列 ~15k 字不再误截)
    assert ContextDeps(system_prompt="s").oversize_result_char_threshold == 24000


async def test_midsize_series_not_truncated_at_default() -> None:
    # 介于旧阈值(4000)与新阈值(24000)之间的结果,在默认阈值下不截断
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=ContextDeps(system_prompt="s").oversize_result_char_threshold)
    st = _state()
    args = {"ts_code": "600519.SH"}
    st.ledger.record(
        step=1, tool_name="get_daily", args=args, digest="d", success=True,
        cache_key="u::get_daily::k",
    )
    series = {"close": list(range(2000))}  # 序列化约 1 万字,> 4000 但 < 24000
    results = [ToolResult(tool_name="get_daily", args=args, success=True, output=series, latency_ms=5)]
    await loop._extract_and_emit_charts(results, st)
    assert "truncated_digest" not in results[0].output  # 默认阈值下不截
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/chatloop/test_loop_oversize_cap.py -k "default_oversize or midsize" -q`
Expected: FAIL（默认仍 4000 → 断言 24000 失败 / midsize 被截断)

- [ ] **Step 3: 改默认值**（context.py,ContextDeps 字段)

```python
    oversize_result_char_threshold: int = 24000  # 单条工具结果进窗口的字符上限(超则截断+回指针);一年日线序列 ~15k 字不再误截,见 spec 2026-06-16-runpython-large-data-channel
```

(原为 `= 4000`。)

- [ ] **Step 4: chat_runner 加 env 覆盖**（chat_runner.py,ContextDeps(...) 内加一行,与 max_context_tokens 同段):

```python
        oversize_result_char_threshold=int(os.getenv("CHATLOOP_OVERSIZE_RESULT_CHARS", "24000")),
```

- [ ] **Step 5: 跑测试确认通过(含原有 oversize 测试不回归)**

Run: `python -m pytest tests/unit/chatloop/test_loop_oversize_cap.py tests/unit/chatloop/test_context.py -q`
Expected: PASS（原有测试显式传 threshold 不受默认变更影响）

- [ ] **Step 6: Commit**

```bash
git add backend/app/chatloop/context.py backend/app/tasks/chat_runner.py backend/tests/unit/chatloop/test_loop_oversize_cap.py
git commit -m "fix(chatloop): 抬截断阈值 4000→24000(单序列不再误截)+ env 覆盖"
```

---

## Task 2: ② data_refs 字段 + 解析(CodeInterpreterTool)

**Files:**
- Modify: `backend/app/chatloop/code_interpreter_tool.py`
- Test: `backend/tests/unit/chatloop/test_code_interpreter_data_refs.py`（新建)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/chatloop/test_code_interpreter_data_refs.py
"""run_python data_refs:按 ref 把完整结构化数据灌进沙箱(命中/越权/失效三路)。"""
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/chatloop/test_code_interpreter_data_refs.py -q`
Expected: FAIL（CodeInterpreterArgs 无 data_refs / __init__ 无 cache）

- [ ] **Step 3: 实现**（code_interpreter_tool.py)

3a. import 加 `import json`(顶部)。

3b. `CodeInterpreterArgs` 加字段(在 `data` 字段后):

```python
    data_refs: dict[str, str] | None = Field(
        default=None,
        description=(
            "把大数据工具结果(日线序列等)按引用喂进来,别手抄进 data。键=脚本里的变量名,"
            "值=该工具结果的缓存 ref(截断占位里的 ref 字段)。执行器自动把完整结构化结果灌进 "
            "data[变量名]。例:data_refs={'maotai':'<get_daily 结果的 ref>'} → 脚本里 "
            "data['maotai']['close'] 即全序列。数据量大时一律用它,不要把数组手抄进 data。"
        ),
    )
```

3c. `__init__` 加 cache:

```python
    def __init__(self, *, backend: ExecutorBackend, cache: Any = None, timeout_s: int = 30) -> None:
        self._backend = backend
        self._cache = cache  # ToolResultCache(协议 get_raw(ref)->str|None);None 则 data_refs 不可用
        self._timeout_s = timeout_s
```

3d. `run_with_state` 改为合并 data_refs + 抽解析方法:

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/chatloop/test_code_interpreter_data_refs.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/chatloop/code_interpreter_tool.py backend/tests/unit/chatloop/test_code_interpreter_data_refs.py
git commit -m "feat(chatloop): run_python data_refs 通道(按 ref 直灌大数据,不经 LLM)"
```

---

## Task 3: ② 接线 + 文档

**Files:**
- Modify: `backend/app/chatloop/worker_wiring.py`(~line 245,CodeInterpreterTool 构造)
- Modify: `backend/app/chatloop/tool_docs.py`(run_python ToolDoc 的 doc)

- [ ] **Step 1: worker_wiring 注入 cache**

把 `CodeInterpreterTool(backend=SkillExecutorBackend(singletons.executor))` 改为:

```python
            CodeInterpreterTool(
                backend=SkillExecutorBackend(singletons.executor), cache=singletons.cache
            ),
```

- [ ] **Step 2: tool_docs run_python 文档加 data_refs**

在 run_python 的 doc 文本"写法契约"段后、"参数"段里补一句(找到 `"参数:code(str,必填)= 完整脚本;data(object,可选)= 喂进来的数据 JSON。\n"` 这行,改成):

```python
            "参数:code(str,必填)= 完整脚本;data(object,可选)= 小数据 JSON 直接喂;"
            "data_refs(object,可选)= {变量名: 工具结果 ref} —— 大数据(日线序列等)用它按引用喂,"
            "执行器自动灌完整数据进 data[变量名],别把长数组手抄进 data。\n"
```

- [ ] **Step 3: 跑接线相关测试(确认无回归)**

Run: `python -m pytest tests/unit/chatloop/test_progressive_disclosure.py tests/unit/chatloop/test_code_interpreter_data_refs.py -q`
Expected: PASS（data_refs 是参数非新工具,工具计数不变;run_python 仍 core）

- [ ] **Step 4: Commit**

```bash
git add backend/app/chatloop/worker_wiring.py backend/app/chatloop/tool_docs.py
git commit -m "feat(chatloop): 接线 data_refs(worker 注入 cache)+ run_python 文档"
```

---

## Task 4: 回归 + 质量门 + 实测重跑

- [ ] **Step 1: 受影响范围回归**

Run: `python -m pytest tests/unit/chatloop tests/unit/skills -q`
Expected: 全 PASS,无 scope 外回归。

- [ ] **Step 2: ruff + mypy**

Run: `ruff check <改动文件> && ruff format --check <改动文件> && mypy app/chatloop/code_interpreter_tool.py app/chatloop/context.py app/tasks/chat_runner.py app/chatloop/worker_wiring.py app/chatloop/tool_docs.py`
Expected: clean。(行尾 LF 化 + 显式 git add,见 agent-edits-crlf-pollute-lf-repo;CRLF 噪声文件不碰。)

- [ ] **Step 3: 实测重跑(手动,真 LLM + 真 tushare 隔离栈)**

按上一轮 harness 的方式起隔离栈(broker DB ≤15、REDIS_URL ≤15、TUSHARE_MODE=real),重跑 S2/M2(①后应不再翻页螺旋)与 C2(②后用 data_refs 应能自然停),对照独立 oracle gold:
  - S2 −10.63% / M2 回撤 19.23%·波动 19.79% / C2 空集。
验证:中等/复杂档不再撞打转/预算闸;run_python 用 data_refs 一次拿全序列;答案对 oracle ±容差。

- [ ] **Step 4: review** — 用 superpowers:requesting-code-review 走 diff;按 receiving-code-review 处理。

---

## Self-Review(对 spec 核对)

- spec ① 抬阈值 → Task 1 ✓(默认 24000 + env 覆盖 + 新默认断言;原 oversize 测试显式传 threshold 不回归)。
- spec ② data-by-ref → Task 2(字段+解析+三路测试:命中/越权/失效)+ Task 3(worker 注 cache + 文档)✓。
- spec「服务端解析、user 命名空间防越权、get_raw+json.loads」→ Task 2 Step 3d `_resolve_refs` ✓(沿用 read_cached_result 的 `{user_id}::` 校验)。
- spec「inline data 保留、向后兼容」→ Task 2 `data` 仍在,`data_refs` 加项,cache 默认 None 不破坏现有构造 ✓。
- spec 验收(S2/M2/C2 重测 + pass@k)→ Task 4 Step 3 ✓。
- 类型一致:`data_refs: dict[str,str]|None`、`_resolve_refs(refs, state)->dict[str,Any]`、`cache.get_raw(ref)->str|None`(与 ToolResultCache:90 一致)三处签名贯通 ✓。
- 待执行核对:worker_wiring 第 245 行 CodeInterpreterTool 构造确切文本、tool_docs run_python 的 "参数" 行确切文本,执行时读文件对齐再改,不臆造。
