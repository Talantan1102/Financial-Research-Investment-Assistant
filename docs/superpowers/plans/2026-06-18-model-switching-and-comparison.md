# 模型选择与对比模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** chat agent 底层模型可切换(每会话选,记录归因)+ 反向出题 pass@k 按模型自动出"模型×桶"对比表,量化"小模型(RL 候选)vs 大模型(天花板)"在工具可靠性上的差距。

**Architecture:** 承 `docs/superpowers/specs/2026-06-18-model-switching-and-comparison-design.md`。核心=给 `LLMService` 加"模型覆盖"escape hatch(不传则照旧走 tier→model);其余把"选哪个模型"喂进来。生产每会话走**新表**(`chat_session_model`,遵 v0.9.x"只加新表不 ALTER"约定);评测加 `model` 参数 + `run_compare` 对比表。

**Tech Stack:** Python / FastAPI / SQLAlchemy(create_all 幂等)/ dashscope OpenAI-compatible / pytest;后端运行环境 = WSL fria-venv。

---

## File Structure

| 文件 | 责任 | 改动 |
| --- | --- | --- |
| `backend/eval/question_gen/_model_smoke.py`(临时) | 5 模型流式函数调用 smoke | 新建,Task 1 跑完即删 |
| `backend/app/services/model_registry.py` | 模型 allowlist + 元信息(SSOT) | 新建 |
| `backend/app/services/llm_service.py` | LLM 调用 | stream_step/chat 加 `model` 覆盖 + 校验 |
| `backend/app/chatloop/loop.py` | ToolLoop | 加 `model` 字段,透传 stream_step(两处) |
| `backend/eval/question_gen/runner.py` | pass@k 跑分 | run_passk 加 `model`;_dump_answers 带 model;新增 run_compare + 对比表 |
| `backend/app/models/chat.py` | ORM | 新增 `ChatSessionModel` 表(不 ALTER 旧表) |
| `backend/app/router/chat.py` | chat 端点 | ChatRequest 加 `model`;首轮 upsert 会话模型 |
| `backend/app/tasks/chat_runner.py` | Celery chat 跑 | 读会话模型 → ToolLoop(model=...) |
| `backend/tests/...` | 单测 | 各 task 配套 |

执行环境:WSL fria-venv,`source /home/administrator/fria-venv/bin/activate && cd backend && python -m pytest ...`;跑测试/服务需 `source .env`。

---

### Task 1: Smoke-test 5 模型的流式函数调用(gating,非 TDD)

确认每个模型的 dashscope 准确 ID + 是否支持流式 native function-calling(小模型是核心未知)。

**Files:** Create `backend/eval/question_gen/_model_smoke.py`

- [ ] **Step 1: 写 smoke 脚本**

```python
"""一次性:5 模型各发一次带工具的流式请求,看能否原生 function-call。跑完即删。"""

import asyncio
import os

_MODELS = [
    "deepseek-v4-flash",
    "qwen-plus",
    "qwen-max",
    "qwen2.5-7b-instruct",
    "qwen3-8b",
]
_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "get_quote",
            "description": "查股票现价",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
        },
    }
]


async def _probe(client, model: str) -> str:
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "茅台现价多少?用工具查 600519.SH"}],
            tools=_TOOL,
            stream=True,
        )
        saw_tool = False
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and getattr(delta, "tool_calls", None):
                saw_tool = True
        return "工具调用 OK" if saw_tool else "只回文本,未函数调用"
    except Exception as ex:  # noqa: BLE001
        return f"失败: {type(ex).__name__}: {str(ex)[:80]}"


async def main() -> None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    for m in _MODELS:
        print(f"{m:24s}: {await _probe(client, m)}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 跑(live)**

Run: `wsl bash -lc 'source /home/administrator/fria-venv/bin/activate && set -a && source /mnt/d/mys/Financial-Research-Investment-Assistant/.env && set +a && cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && python -m eval.question_gen._model_smoke'`
Expected: 每个模型一行结论。**记下:哪些 ID 对、哪些支持函数调用。** 若某小模型 ID 错(404)→ 换 ID 重试(如去/加 `-instruct`);若不支持函数调用 → 记为 supports_tools=False(这是比较数据,Task 2 标注,不兜底)。

- [ ] **Step 3: 删脚本**(findings 写进 Task 2 的 registry)。

---

### Task 2: model_registry(allowlist + 元信息 SSOT)

**Files:** Create `backend/app/services/model_registry.py`;Test `backend/tests/unit/services/test_model_registry.py`

- [ ] **Step 1: 写失败测试**

```python
from app.services import model_registry as mr


def test_allowed_keys_and_dashscope_id():
    assert mr.is_allowed("qwen2.5-7b")
    assert not mr.is_allowed("gpt-4")
    assert mr.dashscope_id("qwen2.5-7b") == "qwen2.5-7b-instruct"  # 按 Task 1 实测校正
    assert mr.dashscope_id("deepseek-v4-flash") == "deepseek-v4-flash"


def test_size_tag_marks_rl_candidates():
    assert mr.spec("qwen2.5-7b").size == "small"
    assert mr.spec("qwen-max").size == "large"
```

- [ ] **Step 2: 跑测试确认失败** — Run: `python -m pytest tests/unit/services/test_model_registry.py -q`(模块不存在)。

- [ ] **Step 3: 实现**

```python
"""模型 allowlist + 元信息(SSOT)。dashscope_id / size / supports_tools 由 Task 1 smoke 校正。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    key: str
    dashscope_id: str
    size: str  # "large" | "small"
    supports_tools: bool  # Task 1 实测;False = 比较数据,不兜底


_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("deepseek-v4-flash", "deepseek-v4-flash", "large", True),
    ModelSpec("qwen-plus", "qwen-plus", "large", True),
    ModelSpec("qwen-max", "qwen-max", "large", True),
    ModelSpec("qwen2.5-7b", "qwen2.5-7b-instruct", "small", True),  # 按 smoke 实测改
    ModelSpec("qwen3-8b", "qwen3-8b", "small", True),  # 按 smoke 实测改
)
_BY_KEY = {m.key: m for m in _MODELS}


def is_allowed(key: str) -> bool:
    return key in _BY_KEY


def spec(key: str) -> ModelSpec:
    if key not in _BY_KEY:
        raise ValueError(f"model 不在清单: {key!r}(允许:{sorted(_BY_KEY)})")
    return _BY_KEY[key]


def dashscope_id(key: str) -> str:
    return spec(key).dashscope_id


def all_keys() -> list[str]:
    return [m.key for m in _MODELS]


__all__ = ["ModelSpec", "is_allowed", "spec", "dashscope_id", "all_keys"]
```

- [ ] **Step 4: 跑测试确认通过** — Run: `python -m pytest tests/unit/services/test_model_registry.py -q`

- [ ] **Step 5: 提交** — `feat(model): model_registry allowlist(5 模型 + 大小/函数调用元信息)`

---

### Task 3: LLMService 模型覆盖口子

**Files:** Modify `backend/app/services/llm_service.py`(stream_step 与 chat);Test `backend/tests/unit/services/test_llm_service_model_override.py`(或并入现有 llm_service 测试)

- [ ] **Step 1: 写失败测试**(用现有的 fake/scripted client 注入,断言传给 client 的 model)

```python
# 伪代码骨架:构造 LLMService(注入 fake client 记录收到的 model),
# 调 stream_step(model="qwen2.5-7b") → fake 收到 dashscope_id "qwen2.5-7b-instruct";
# 调 stream_step(model=None, tier="balanced") → fake 收到 tier 解析的 deepseek-v4-flash;
# 调 stream_step(model="gpt-4") → raise ValueError(不在清单)。
```

(按 `tests/` 里现有 LLMService 测试的 fake client 模式写;断言 `_client.chat`/`stream_chat` 收到的 model。)

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现** — `stream_step` 与 `chat` 签名各加 `model: str | None = None`;model 解析改为:

```python
from app.services import model_registry

# 原: model = self._tier_router.resolve(tier)
# 改:
if model is not None:
    model = model_registry.dashscope_id(model)  # 校验在清单 + 映射 dashscope id;不在则 raise
else:
    model = self._tier_router.resolve(tier)
```

(chat 与 stream_step 两处同改;其余 trace/StepResult 记录的 model 自然变成实际用的。)

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交** — `feat(llm): stream_step/chat 加 model 覆盖口子(不传则走 tier)`

---

### Task 4: ToolLoop 透传 model

**Files:** Modify `backend/app/chatloop/loop.py`;Test `backend/tests/unit/chatloop/test_loop_model_passthrough.py`

- [ ] **Step 1: 写失败测试** — 构造 ToolLoop(llm=fake, model="qwen-max", ...),跑一圈,断言 fake.stream_step 收到 `model="qwen-max"`;不传 model 时收到 `model=None`。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现** — `ToolLoop.__init__` 在 `tier` 旁加 `model: str | None = None`;`self._model = model`;两处 `self._llm.stream_step(...)` 加 `model=self._model`。

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交** — `feat(chatloop): ToolLoop 透传 model 到 stream_step`

---

### Task 5: 评测 runner 选模型 + run_compare 对比表

**Files:** Modify `backend/eval/question_gen/runner.py`;Test `backend/tests/eval/question_gen/test_runner_compare.py`

- [ ] **Step 1: 写失败测试**(纯聚合,用假的 per-model per_case 结果喂 _compare_table,断言"模型×桶"表形状/值)

```python
from eval.question_gen.runner import _compare_table


def test_compare_table_shape():
    # 两个模型、各自 {bucket: {pass,total,rate}} → 行=模型,列=桶+总分
    per_model = {
        "qwen-max": {"pass_at_k": {"pass": 9, "total": 10, "rate": 0.9}, "by_bucket": {"简单/涨幅": {"pass": 4, "total": 5, "rate": 0.8}}},
        "qwen2.5-7b": {"pass_at_k": {"pass": 4, "total": 10, "rate": 0.4}, "by_bucket": {"简单/涨幅": {"pass": 2, "total": 5, "rate": 0.4}}},
    }
    table = _compare_table(per_model)
    assert table["models"] == ["qwen-max", "qwen2.5-7b"]
    assert table["rows"]["qwen-max"]["总分"] == 0.9
    assert table["rows"]["qwen2.5-7b"]["简单/涨幅"] == 0.4
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`run_passk` 签名加 `model: str | None = None`;`ToolLoop(..., model=model)`;`_dump_answers` 的记录加 `"model": model`。新增:

```python
def _compare_table(per_model: dict[str, dict]) -> dict:
    """{model: run_passk 结果} → {models, buckets, rows{model: {总分, 各桶 rate}}}。"""
    buckets = sorted({b for r in per_model.values() for b in r["by_bucket"]})
    rows = {}
    for m, r in per_model.items():
        row = {"总分": r["pass_at_k"]["rate"]}
        for b in buckets:
            row[b] = r["by_bucket"].get(b, {}).get("rate")
        rows[m] = row
    return {"models": list(per_model), "buckets": buckets, "rows": rows}


async def run_compare(cases, models: list[str], *, k=1, concurrency=5, as_of="20260612"):
    per_model = {}
    for m in models:
        per_model[m] = await run_passk(cases, k=k, concurrency=concurrency, as_of=as_of, model=m)
    return _compare_table(per_model)
```

CLI:`runner.py __main__` 加一个 `--compare m1,m2,...` 分支(或第 4 个 argv),跑 run_compare 打印表。

- [ ] **Step 4: 跑测试确认通过** — Run: `python -m pytest tests/eval/question_gen/test_runner_compare.py -q`

- [ ] **Step 5: 提交** — `feat(eval): runner 选模型 + run_compare 出"模型×桶"对比表`

---

### Task 6: 生产每会话模型(新表 + 请求 + 透传)

**Files:** Modify `backend/app/models/chat.py`、`backend/app/router/chat.py`、`backend/app/tasks/chat_runner.py`;Test `backend/tests/...`(模型表 + 透传)

- [ ] **Step 1: 写失败测试** — 建会话设 model="qwen-max" → chat_runner 读到并传给 ToolLoop;未设 → None(走默认)。

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`models/chat.py` 加新表(不 ALTER 旧表):

```python
class ChatSessionModel(Base):
    """每会话选定的底层模型(v0.9.x 约定:只加新表不 ALTER;create_all 幂等)。"""

    __tablename__ = "chat_session_model"

    session_id = Column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    model = Column(String(64), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

`router/chat.py`:`ChatRequest` 加 `model: str | None = None`;端点 enqueue 前,若 `req.model` 给了:`model_registry.spec(req.model)` 校验(不在清单 → 400),upsert `chat_session_model(session_id, model)`(首轮设定;已存不同值 → 以已存为准 + warn,保"每会话固定")。

`tasks/chat_runner.py`:建 ToolLoop 前按 session_id 读 `chat_session_model.model`(无则 None),`ToolLoop(..., model=that)`。

- [ ] **Step 4: 跑测试确认通过 + create_all 建新表冒烟**(起一次 app/测试 DB,确认 `chat_session_model` 表建出)

- [ ] **Step 5: 提交** — `feat(chat): 每会话模型(新表 + 请求字段 + chat_runner 透传)`

---

### Task 7: 全链路守护 + live 5 模型对比(deliverable)

**Files:** 无新增;跑套件 + live 对比。

- [ ] **Step 1: 跑 chatloop + services + eval 单元套件确认无回归**

Run: `python -m pytest tests/unit/chatloop tests/unit/services tests/eval/question_gen -q`
Expected: 全绿(尤其不传 model 时行为不变的回归断言)。

- [ ] **Step 2: mypy + ruff** — 改动文件全过。

- [ ] **Step 3: live 5 模型对比跑(deliverable)**

Run(WSL,TUSHARE_MODE=real + .env): `python -m eval.question_gen.runner data/computation_cases.jsonl 1 5 --compare deepseek-v4-flash,qwen-plus,qwen-max,qwen2.5-7b,qwen3-8b`
Expected:一张"模型×桶"对比表。**预期小模型(qwen2.5-7b/qwen3-8b)总分明显低于大模型,且差距集中在多步/工具可靠性桶(相关/筛选/排序)**——这就是"RL 要补的缺口"的量化。
把表落盘为报告(`docs/research/2026-06-18-model-comparison-passk.md` 或挂看板),供训练选模型。

- [ ] **Step 4: 不单独提交**(报告落盘单独 commit)。

---

## Self-Review

**Spec 覆盖**:① 覆盖口子(Task 3,spec §3.1)② 清单(Task 2,§3.2)③ 生产每会话(Task 6,§3.3)④ 评测对比(Task 5+7,§3.4)⑤ smoke 验证(Task 1,§4)。全覆盖。

**占位扫描**:dashscope_id 与 supports_tools 标注 Task 1 实测后校正(已显式标注,非占位);Task 3 测试给的是 fake-client 骨架(注明按现有 LLMService 测试模式写)——实施时一看便知。

**类型一致**:`model` 全链路为 `str | None`(registry key);registry key → dashscope_id 在 LLMService 单点映射;ToolLoop/runner/chat 透传的都是 registry key,只有 LLMService 出口映射成 dashscope id。回归不变量:`model=None` → 走 tier → deepseek-v4-flash,逐字不变。

---

## Execution Handoff

Plan 已存 `docs/superpowers/plans/2026-06-18-model-switching-and-comparison.md`。两种执行:
1. **Subagent-Driven(推荐)** — 每 task 派新 subagent,task 间 spec+质量 review。
2. **Inline** — 本 session 内逐 task 执行,带 checkpoint。

选哪个?(Task 1 smoke 是 gating,先跑它定 registry 的 ID/函数调用支持,再往下。)
