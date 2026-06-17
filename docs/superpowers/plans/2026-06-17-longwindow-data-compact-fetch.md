# 长窗口取数紧凑取回 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拆掉 get_daily 的 260 行静默 tail——长窗口一次取全、完整数据进缓存、只回信息卡+取货单号,让 agent 凭 ref 走 run_python data_refs 算全量,从源头消除"预防性分段"导致的 CAGR/3y 战力断崖。

**Architecture:** 承 `docs/superpowers/specs/2026-06-17-longwindow-data-compact-fetch-design.md`。三刀:① get_daily 去 cap + 附紧凑 summary 信息卡;② 通用「摘要存活截断」让 summary 挺过超大截断;③ agent 面向文档(工具描述 + 系统提示)把"算长窗口指标=取 ref→沙箱 data_refs 算全量"立成默认正道。"存全量→只回单号→沙箱凭单号算全量"链路已验证现成(缓存 get_or_compute + data_refs _resolve_refs)。

**Tech Stack:** Python / pandas / pytest(asyncio)/ mypy / ruff;后端运行环境 = WSL fria-venv。

---

## File Structure

| 文件 | 责任 | 改动 |
| --- | --- | --- |
| `backend/app/mcp_server/tools/get_daily.py` | get_daily MCP 工具:DataFrame → 列式紧凑输出 | 删 `_MAX_ROWS` tail;加 `_summary()`;输出附 `summary` |
| `backend/tests/unit/mcp_server/test_get_daily_tool.py` | get_daily 纯函数单测 | 加"不再 tail / summary 字段正确"两测 |
| `backend/app/chatloop/loop.py` | ToolLoop:超大结果截断(`_cap_oversized_output`) | 截断时保留 `summary` 字段(替代粗暴 digest) |
| `backend/tests/unit/chatloop/test_loop_oversize_cap.py` | 超大截断单测 | 加"带 summary 的超大结果保留 summary"一测 |
| `backend/app/chatloop/tool_docs.py` | agent 看到的工具描述 | get_daily 描述去掉"260 超出截断",改述 ref/data_refs 取全量 |
| `backend/app/chatloop/system_prompt.py` | 稳定前缀系统提示 | 增补一条"长窗口指标走 ref→data_refs、别分段"规矩 |
| `backend/tests/unit/chatloop/test_longwindow_guidance.py`(新) | 守 agent 面向文档不回退 | 断言工具描述/系统提示含新引导、不含旧截断话术 |

执行环境提醒(跑测试):WSL fria-venv,`source /home/administrator/fria-venv/bin/activate && cd backend && python -m pytest ...`(不用 Windows .venv,不用 uv run)。

---

### Task 1: get_daily 去 cap + 附 summary 信息卡

**Files:**
- Modify: `backend/app/mcp_server/tools/get_daily.py:36-70`
- Test: `backend/tests/unit/mcp_server/test_get_daily_tool.py`

- [ ] **Step 1: 写失败测试(不再 tail + summary 字段)**

追加到 `backend/tests/unit/mcp_server/test_get_daily_tool.py`:

```python
def test_format_daily_no_tail_returns_full_range() -> None:
    # 旧 _MAX_ROWS=260 会把 300 行 tail 到 260;去 cap 后应原样返回全部
    n = 300
    df = pd.DataFrame(
        {
            "trade_date": [f"2025{i:04d}" for i in range(1, n + 1)],  # 唯一且可排序即可
            "open": [10.0] * n,
            "high": [11.0] * n,
            "low": [9.0] * n,
            "close": [10.0 + i * 0.01 for i in range(n)],
            "vol": [1000] * n,
            "pct_chg": [0.1] * n,
        }
    )
    out = _format_daily(df, "600519.SH")
    assert out["count"] == n
    assert len(out["close"]) == n  # 不再被 tail 到 260


def test_format_daily_summary_fields() -> None:
    df = pd.DataFrame(
        {
            "trade_date": ["20250101", "20250102", "20250103"],
            "open": [10.0, 10.1, 10.2],
            "high": [10.5, 12.0, 10.3],
            "low": [9.5, 9.0, 9.8],
            "close": [10.0, 11.0, 10.5],
            "vol": [1, 2, 3],
            "pct_chg": [0.0, 10.0, -4.5],
        }
    )
    s = _format_daily(df, "600519.SH")["summary"]
    assert s["count"] == 3
    assert s["date_start"] == "20250101" and s["date_end"] == "20250103"
    assert s["first_close"] == 10.0 and s["last_close"] == 10.5
    assert s["period_high"] == 12.0 and s["period_low"] == 9.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/mcp_server/test_get_daily_tool.py -q`
Expected: FAIL —— `test_format_daily_no_tail_returns_full_range` 得 260≠300;`test_format_daily_summary_fields` 报 KeyError: 'summary'。

- [ ] **Step 3: 实现(删 tail,加 _summary,输出附 summary)**

`backend/app/mcp_server/tools/get_daily.py`:删掉 `_MAX_ROWS` 常量与 `_format_daily` 里的 tail 分支,加 `_summary`,并在 `_format_daily` 里附 `summary`。

删除:

```python
# 单次返回的最大行数(防时间序列过长撑爆上下文;超出取最近 N 个交易日)。
_MAX_ROWS = 260
```

以及 `_format_daily` 内:

```python
    if len(df) > _MAX_ROWS:
        df = df.tail(_MAX_ROWS)
```

新增 `_summary`(放在 `_format_daily` 之前):

```python
def _summary(df: Any, ts_code: str) -> dict[str, Any]:
    """从**完整** df 现算紧凑信息卡;超大截断后由 ToolLoop 保留(见 spec § 4.1/4.2)。

    去 cap 后长区间真取全量,完整序列过大会被换出上下文——这张卡是 agent 留在
    上下文里能核对范围/直接答简单问题的依据,体积小、廉价。
    """
    dates = [str(d) for d in df["trade_date"].tolist()]
    close = df["close"]
    return {
        "ts_code": ts_code,
        "count": int(len(df)),
        "date_start": dates[0],
        "date_end": dates[-1],
        "first_close": round(float(close.iloc[0]), 2),
        "last_close": round(float(close.iloc[-1]), 2),
        "period_high": round(float(df["high"].max()), 2),
        "period_low": round(float(df["low"].min()), 2),
    }
```

`_format_daily` 改为(非空分支附 summary;空分支不变):

```python
def _format_daily(df: Any, ts_code: str) -> dict[str, Any]:
    """DataFrame → 列式紧凑 dict(纯函数,可单测,不碰网络/LLM)。"""
    if df is None or getattr(df, "empty", True):
        return {"ts_code": ts_code, "count": 0, "dates": []}
    df = df.sort_values("trade_date")
    out: dict[str, Any] = {
        "ts_code": ts_code,
        "count": int(len(df)),
        "summary": _summary(df, ts_code),
        "dates": [str(d) for d in df["trade_date"].tolist()],
        "open": _round_list(df["open"]),
        "high": _round_list(df["high"]),
        "low": _round_list(df["low"]),
        "close": _round_list(df["close"]),
    }
    if "vol" in df.columns:
        out["vol"] = _round_list(df["vol"], 0)
    if "pct_chg" in df.columns:
        out["pct_chg"] = _round_list(df["pct_chg"])
    return out
```

模块头注释里"返回**列式**紧凑结构…比 list-of-dict 省 token"那段可保留;把文件顶部 docstring 里关于行数的暗示(若有)对齐为"长区间取全量"。

- [ ] **Step 4: 跑测试确认通过(含既有回归)**

Run: `python -m pytest tests/unit/mcp_server/test_get_daily_tool.py -q`
Expected: PASS —— 新 2 测 + 既有 3 测(columnar_and_sorted / empty / tool_def_shape)全绿。

- [ ] **Step 5: 提交**

```bash
git add backend/app/mcp_server/tools/get_daily.py backend/tests/unit/mcp_server/test_get_daily_tool.py
git commit -m "feat(get_daily): 去 260 行静默 tail + 附 summary 信息卡

长区间真取全量(完整版由 chat 侧缓存存下);附紧凑 summary(首末日/首末收盘/
区间高低)供超大截断后留在上下文。spec 2026-06-17-longwindow-data-compact-fetch §4.1。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 超大截断保留 summary 字段

**Files:**
- Modify: `backend/app/chatloop/loop.py:295-332`(`_cap_oversized_output`)
- Test: `backend/tests/unit/chatloop/test_loop_oversize_cap.py`

- [ ] **Step 1: 写失败测试(带 summary 的超大结果保留 summary)**

追加到 `backend/tests/unit/chatloop/test_loop_oversize_cap.py`:

```python
async def test_oversize_with_summary_preserves_summary() -> None:
    events: list[LoopEvent] = []
    loop = _loop(events, threshold=200)
    st = _state()
    args = {"ts_code": "600519.SH", "start": "20230101", "end": "20260101"}
    summary = {
        "ts_code": "600519.SH",
        "count": 725,
        "date_start": "20230101",
        "date_end": "20260101",
        "first_close": 1678.0,
        "last_close": 1502.0,
        "period_high": 1900.0,
        "period_low": 1402.0,
    }
    big = {"summary": summary, "close": list(range(2000))}  # 远超 200 字
    st.ledger.record(
        step=1,
        tool_name="get_daily",
        args=args,
        digest="d",
        success=True,
        cache_key="u::get_daily::abc",
    )
    results = [
        ToolResult(tool_name="get_daily", args=args, success=True, output=big, latency_ms=5)
    ]
    await loop._extract_and_emit_charts(results, st)
    out = results[0].output
    assert isinstance(out, dict)
    assert out["summary"] == summary  # 信息卡存活
    assert out["ref"] == "u::get_daily::abc"
    assert "data_refs" in out["note"]
    assert "truncated_digest" not in out  # 有 summary 就不用粗暴 600 字 digest
    assert "close" not in out  # 完整数组换出
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/chatloop/test_loop_oversize_cap.py::test_oversize_with_summary_preserves_summary -q`
Expected: FAIL —— 当前实现总写 `truncated_digest`、不写 `summary`,断言不满足。

- [ ] **Step 3: 实现(截断时优先保留 summary)**

`backend/app/chatloop/loop.py` `_cap_oversized_output` 末段(clear+update 那块)改为:先取出 summary,有则保留、无则退回原 digest 行为:

```python
        # ToolResult 是 frozen,但 output dict 可变 —— 原地 clear+update(同既有 figures 剥离手法)
        summary = r.output.get("summary")
        r.output.clear()
        capped: dict[str, Any] = {
            "note": (
                "结果过大已截断,完整数据已缓存(见 ref)。要对它做计算,"
                "用 run_python 传 data_refs={变量名: 上面的 ref} 把完整数据一次灌进沙箱算全量——"
                "别用 read_cached_result 分页翻取(大数据翻页会耗尽预算);只想看少量原文才用 read_cached_result。"
            ),
            "ref": cache_key,
            "original_chars": len(serialized),
        }
        if isinstance(summary, dict):
            capped["summary"] = summary  # 工具自带信息卡 → 存活,优于粗暴 digest
        else:
            capped["truncated_digest"] = serialized[:600]
        r.output.update(capped)
```

(`Any` 已在文件顶部 import;`capped` 的类型标注用 `dict[str, Any]`。)

- [ ] **Step 4: 跑测试确认通过(含既有回归)**

Run: `python -m pytest tests/unit/chatloop/test_loop_oversize_cap.py -q`
Expected: PASS —— 新测 + 既有(`test_oversize_with_ref_is_truncated` 无 summary 仍走 `truncated_digest`、`data_refs` in note 等)全绿。

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/loop.py backend/tests/unit/chatloop/test_loop_oversize_cap.py
git commit -m "feat(chatloop): 超大截断保留工具自带 summary 字段

带 summary 的超大结果(get_daily 长区间)截断后保留信息卡 + ref,取代对结构化
数据不友好的前 600 字 digest;无 summary 的退回原行为。spec §4.2。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: agent 面向文档——工具描述 + 系统提示立正道

**Files:**
- Modify: `backend/app/chatloop/tool_docs.py:407-410`(get_daily `doc`)
- Modify: `backend/app/chatloop/system_prompt.py:22-31`(工具使用纪律段)
- Test: `backend/tests/unit/chatloop/test_longwindow_guidance.py`(新建)

- [ ] **Step 1: 写失败测试(新建 guidance 守护测试)**

新建 `backend/tests/unit/chatloop/test_longwindow_guidance.py`:

```python
"""守护 agent 面向文档不回退:长窗口取数引导走 ref/data_refs,不再教"分段/260 截断"。"""

from __future__ import annotations

from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT
from app.chatloop.tool_docs import TOOL_DOCS


def test_get_daily_doc_steers_to_data_refs_not_chunking() -> None:
    doc = TOOL_DOCS["get_daily"].doc
    assert "data_refs" in doc  # 指向沙箱引用取全量
    assert "260" not in doc  # 旧"单次最多 260 超出截断"话术已移除(它是分段源头)


def test_system_prompt_has_longwindow_ref_rule() -> None:
    assert "data_refs" in CHAT_SYSTEM_PROMPT  # 长窗口指标走引用算全量的规矩在位
```

> 注:已确认 `tool_docs.py:49` 导出 `TOOL_DOCS: dict[str, ToolDoc]`,条目有 `.doc` 属性,上面 import 与取值精确可用。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/unit/chatloop/test_longwindow_guidance.py -q`
Expected: FAIL —— 当前 get_daily doc 含 "260"、不含 "data_refs";系统提示不含 "data_refs"。

- [ ] **Step 3: 实现(改两处文案)**

`backend/app/chatloop/tool_docs.py` get_daily 的 `doc`,把 `返回:` 那两行 + `硬约束:` 那行(对应 407-410)替换为:

```python
            "返回:列式数组 {ts_code, count, dates[], open[], high[], low[], close[], vol[], "
            "pct_chg[]} —— 可直接喂 run_python 的 go.Candlestick(x=dates, ...) 或折线。\n"
            "长区间(超过约一年)结果过大时改回 {ts_code, count, summary{...}, ref}:完整序列已缓存,"
            "在 run_python 里用 data_refs={变量名: ref} 一次灌进沙箱算全量(年化/波动/回撤等),"
            "不要分段多次取、不要拿 summary 估算。\n"
            "示例:get_daily(ts_code='600519.SH', start='20250101', end='20250601')。\n"
            "硬约束:ts_code 带后缀;日期 YYYYMMDD;长区间一次取全(不再只给最近一年)。"
```

`backend/app/chatloop/system_prompt.py`,在"## 工具使用纪律"段(trade_cal window 那条之后)插入一条:

```python
    "- 算需要整段长序列的指标(年化收益/波动率/最大回撤等近一年以上窗口)时,取数过大会回一个"
    "数据引用(ref);在 run_python 里用 data_refs={变量名: ref} 把完整序列一次灌进沙箱算全量,"
    "别把日线分段读进对话、也别拿摘要估算。\n"
```

(插在 line 30 那条 trade_cal 规则之后、`"\n"` 段落分隔之前。保持静态、无日期,守逐字节稳定铁律。)

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/unit/chatloop/test_longwindow_guidance.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/app/chatloop/tool_docs.py backend/app/chatloop/system_prompt.py backend/tests/unit/chatloop/test_longwindow_guidance.py
git commit -m "feat(chatloop): 工具描述+系统提示把长窗口指标引向 ref/data_refs

get_daily 描述去掉"单次最多 260 超出截断"(分段源头),改述长区间取全量+ref;
系统提示增补"长窗口指标走 data_refs 算全量、别分段"规矩。spec §4.1/§4.3。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 全链路守护 + 回归验证

**Files:** 无新增;跑既有套件 + live 回归。

- [ ] **Step 1: 跑 chatloop + mcp_server 单元套件确认无回归**

Run: `python -m pytest tests/unit/chatloop tests/unit/mcp_server -q`
Expected: 全绿(尤其 `test_loop_oversize_cap.py` 既有断言、`test_get_daily_tool.py` 既有断言不被新行为破坏)。

- [ ] **Step 2: 跑 e2e cassette 确认 get_daily 形状变更不破回放**

Run: `python -m pytest tests/e2e/test_chatloop_cassette.py -q`
Expected: 全绿(cassette 录制的 get_daily 响应行数小,去 cap 不改回放;新增 summary 键不被断言排斥)。
若 cassette 断言了 get_daily 输出精确 dict → 需补 summary 键,按实际报错对齐。

- [ ] **Step 3: mypy + ruff**

Run: `python -m mypy app/mcp_server/tools/get_daily.py app/chatloop/loop.py && ruff check app/mcp_server/tools/get_daily.py app/chatloop/loop.py app/chatloop/tool_docs.py app/chatloop/system_prompt.py`
Expected: 0 error。

- [ ] **Step 4: live 回归——重跑 CAGR/3y 桶**

(需 `TUSHARE_MODE=real` + DASHSCOPE,见 backend 运行环境)。先单跑两道 3y CAGR 题确认 agent 走"一次取全→data_refs→算"路径、不再分段:

Run(WSL,source .env):
`TUSHARE_MODE=real python -m eval.question_gen.runner data/computation_cases.jsonl 1 5`

Expected: CAGR/3y 桶较 ~40% 明显上行(真正拆断崖,区别于上轮加 max_steps 的治标)。记录新分桶。
注:本修复生效后,runner `max_steps=26` 的治标余量可按需回调(非本 plan 必做)。

- [ ] **Step 5: 不单独提交**(本 task 仅验证;如需调 cassette 断言,并入对应修复 commit)。

---

## Self-Review

**Spec 覆盖**:① 去 cap + summary(Task 1,spec §4.1)② 摘要存活截断(Task 2,spec §4.2)③ 工具描述+系统提示(Task 3,spec §4.1/§4.3)④ 分块代数护栏 = spec §4.4 纯文档,已在 spec 内,无代码任务。回归验证(Task 4,spec §5)。全覆盖。

**占位扫描**:各 step 均有真实代码/命令/预期。`tool_docs.py` 导出名已核实为 `TOOL_DOCS`(line 49),无占位。

**类型一致**:`_summary` 返回 `dict[str, Any]`、`summary` 键全流程为 dict;`_cap_oversized_output` 的 `summary = r.output.get("summary")` + `isinstance(summary, dict)` 守卫与 Task 1 产出的 summary 形状一致;测试里的 summary dict 字段与 `_summary` 实现逐字段对齐。

---

## Execution Handoff

Plan 已存 `docs/superpowers/plans/2026-06-17-longwindow-data-compact-fetch.md`。两种执行方式:

1. **Subagent-Driven(推荐)** —— 每 task 派新 subagent,task 间两段式 review,快速迭代。
2. **Inline Execution** —— 本 session 内逐 task 执行,带 checkpoint。

选哪个?
