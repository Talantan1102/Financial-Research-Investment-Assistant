# 交易日历工具 + 参考日期注入 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 chatloop 补上时间感知:一个查 A 股交易日历的 `trade_cal` 工具,加上每轮把"今天几号"注入对话窗口。

**Architecture:** trade_cal 是只读 MCP 数据工具(六动作:is_open/latest/prev/next/count/list),底层包 tushare `trade_cal` API、纯函数不读墙上时钟;一个独立的确定性历法工具(静态节假日表+工作日规则)给 mock 用,保证离线可复现。参考日期经 ContextDeps 新字段注入尾部动态区,生产填 `date.today()`、eval/RL 填冻结 as-of。

**Tech Stack:** Python 3.12 / FastAPI / pandas / pytest;测试在 WSL fria-venv 跑(`mock-tushare-adapter-is-llm-backed` / `backend-runtime-env-wsl-fria-venv`)。

**spec:** `docs/superpowers/specs/2026-06-15-trade-cal-and-reference-date-design.md`

**运行测试的统一前缀**(WSL fria-venv): 各步 `Run:` 里的 `pytest ...` 实际以
`wsl bash -lc "cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && source <fria-venv>/bin/activate && TUSHARE_MODE=mock pytest ..."` 执行(fria-venv 具体路径执行时确认)。

---

## File Structure

- Create `backend/app/services/trade_calendar.py` — 纯历法工具:静态 A 股节假日表 + `build_calendar_df(start, end)`(确定性,工作日+节假日)。被 mock 与单测共用。
- Create `backend/app/mcp_server/tools/trade_cal.py` — MCP 工具:TOOL_DEF + `handle()` + 六动作解析(操作 service 返回的 DataFrame,与 real/mock 无关)。
- Modify `backend/app/services/tushare_service.py` — Protocol + RealTushareService 加 `get_trade_cal`。
- Modify `backend/app/services/tushare_mock_adapter.py` — `LegacyMockTushareAdapter.get_trade_cal` 调 `build_calendar_df`(确定性,绝不走 LLM)。
- Modify `backend/app/mcp_server/server.py` — `_CHAT_TOOL_MODULES` 加 `"app.mcp_server.tools.trade_cal"`。
- Modify `backend/app/chatloop/tool_docs.py` — TOOL_DOCS 加 trade_cal 条目 + DEFERRED_TOOLS 追加。
- Modify `backend/app/chatloop/context.py` — ContextDeps 加 `reference_date` 字段 + 尾部动态区拼"今天"。
- Modify `backend/app/chatloop/system_prompt.py` — 加一句日期纪律(静态,不含日期值)。
- Modify `backend/app/tasks/chat_runner.py:256` — 构造 ContextDeps 时填 `reference_date=date.today()`。
- Test: `backend/tests/unit/services/test_trade_calendar.py`、`backend/tests/unit/mcp_server/test_trade_cal_tool.py`、改 `backend/tests/unit/chatloop/test_progressive_disclosure.py`、`backend/tests/e2e/test_chatloop_cassette.py`、`backend/tests/unit/chatloop/test_context.py`。

---

## Task 1: 确定性历法工具(static holiday + build_calendar_df)

**Files:**
- Create: `backend/app/services/trade_calendar.py`
- Test: `backend/tests/unit/services/test_trade_calendar.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/services/test_trade_calendar.py
import pandas as pd
from app.services.trade_calendar import build_calendar_df

def test_weekend_closed():
    df = build_calendar_df("20260613", "20260615")  # 周六/周日/周一
    row = {r.cal_date: r.is_open for r in df.itertuples()}
    assert row["20260613"] == 0  # 周六
    assert row["20260614"] == 0  # 周日

def test_new_year_holiday_closed():
    df = build_calendar_df("20260101", "20260101")
    assert int(df.iloc[0]["is_open"]) == 0  # 元旦

def test_normal_weekday_open():
    df = build_calendar_df("20260310", "20260310")  # 周二,无节假日
    assert int(df.iloc[0]["is_open"]) == 1

def test_columns_and_pretrade():
    df = build_calendar_df("20260101", "20260105")
    assert set(["cal_date", "is_open", "pretrade_date"]).issubset(df.columns)
    # 元旦后第一个交易日的 pretrade_date 应指向上一个交易日(2025-12-31)
    jan2 = df[df["cal_date"] == "20260102"].iloc[0]  # 周五,开市
    assert jan2["pretrade_date"] == "20251231"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/services/test_trade_calendar.py -v`
Expected: FAIL（ModuleNotFoundError: app.services.trade_calendar）

- [ ] **Step 3: 写实现**

```python
# backend/app/services/trade_calendar.py
"""确定性 A 股交易日历(mock/离线用)。

绝不调 LLM、不读网络:工作日规则 + 静态节假日表。覆盖年份外回退纯工作日规则。
节假日表 = 中国 A 股(沪深)休市日中落在工作日的那些(周末本就由 weekday 规则盖)。
逐年需对官方交易日历校验更新;覆盖边界见 _HOLIDAYS 年份。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

# A 股工作日休市日(YYYYMMDD)。只列落在周一-周五的法定休市日;周末由规则覆盖。
# 来源口径:沪深交易所每年公告的休市安排。覆盖 2024-2026,逐年校验更新。
_HOLIDAYS: set[str] = {
    # 2024
    "20240101",  # 元旦
    "20240212", "20240213", "20240214", "20240215", "20240216",  # 春节
    "20240404", "20240405",  # 清明
    "20240501", "20240502", "20240503",  # 劳动节
    "20240610",  # 端午
    "20240916", "20240917",  # 中秋
    "20241001", "20241002", "20241003", "20241004", "20241007",  # 国庆
    # 2025
    "20250101",  # 元旦
    "20250128", "20250129", "20250130", "20250131", "20250203", "20250204",  # 春节
    "20250404",  # 清明
    "20250501", "20250502", "20250505",  # 劳动节
    "20250602",  # 端午
    "20251001", "20251002", "20251003", "20251006", "20251007", "20251008",  # 国庆+中秋
    # 2026
    "20260101", "20260102",  # 元旦
    "20260216", "20260217", "20260218", "20260219", "20260220",  # 春节
    "20260406",  # 清明
    "20260501",  # 劳动节
    "20260619",  # 端午
    "20260925",  # 中秋
    "20261001", "20261002", "20261005", "20261006", "20261007", "20261008",  # 国庆
}


def _is_open(d: date) -> bool:
    if d.weekday() >= 5:  # 5=周六 6=周日
        return False
    return d.strftime("%Y%m%d") not in _HOLIDAYS


def build_calendar_df(start: str, end: str) -> pd.DataFrame:
    """返回 [start, end] 闭区间每日一行:cal_date / is_open(0/1) / pretrade_date。

    pretrade_date = 该日(含)之前最近的一个交易日的前一交易日口径,对齐 tushare:
    tushare 的 pretrade_date 是"上一交易日"。这里对每一行给出严格早于 cal_date 的最近交易日。
    """
    s = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
    e = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    rows: list[dict] = []
    prev_open: str | None = None
    d = s
    while d <= e:
        ymd = d.strftime("%Y%m%d")
        is_open = _is_open(d)
        rows.append({"cal_date": ymd, "is_open": 1 if is_open else 0, "pretrade_date": prev_open})
        if is_open:
            prev_open = ymd
        d += timedelta(days=1)
    return pd.DataFrame(rows)
```

> 注:`test_columns_and_pretrade` 里 20260102 的 pretrade_date 期望 20251231。区间从 20260101 起,
> 20260101/0102 都在 `_HOLIDAYS`(休市),故区间内 prev_open 一直是 None。要让该断言成立,
> 实现需"种子化"区间起点前的最近交易日。**修正:** `build_calendar_df` 起点回看至多 10 天补种子 prev_open。

- [ ] **Step 3b: 修正 prev_open 种子(回看 10 天)**

在 `build_calendar_df` 进入主循环前,从 `s - 1 day` 往前最多回看 10 天,找到首个 `_is_open` 的日子作为初始 `prev_open`:

```python
    prev_open = None
    probe = s - timedelta(days=1)
    for _ in range(10):
        if _is_open(probe):
            prev_open = probe.strftime("%Y%m%d")
            break
        probe -= timedelta(days=1)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/services/test_trade_calendar.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/trade_calendar.py backend/tests/unit/services/test_trade_calendar.py
git commit -m "feat(chatloop): 确定性 A 股交易日历工具(静态节假日表+工作日规则)"
```

---

## Task 2: TushareService.get_trade_cal(Protocol + Real + Mock)

**Files:**
- Modify: `backend/app/services/tushare_service.py`(Protocol 段 ~line 60、RealTushareService 段 ~line 264 后)
- Modify: `backend/app/services/tushare_mock_adapter.py`(类内,~get_index_daily 旁 line 212-224)
- Test: `backend/tests/unit/services/test_trade_calendar.py`(追加 mock 适配器断言)

- [ ] **Step 1: 写失败测试(mock 适配器返回确定性日历)**

```python
# 追加到 test_trade_calendar.py
import pytest
from app.services.tushare_mock_adapter import LegacyMockTushareAdapter

@pytest.mark.asyncio
async def test_mock_adapter_get_trade_cal_deterministic():
    adapter = LegacyMockTushareAdapter()
    df1 = await adapter.get_trade_cal(start="20260101", end="20260110")
    df2 = await adapter.get_trade_cal(start="20260101", end="20260110")
    assert df1.equals(df2)                      # 确定性
    assert int(df1[df1["cal_date"] == "20260101"].iloc[0]["is_open"]) == 0  # 元旦休市
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/services/test_trade_calendar.py::test_mock_adapter_get_trade_cal_deterministic -v`
Expected: FAIL（AttributeError: get_trade_cal）

- [ ] **Step 3: 加 Protocol 方法**(tushare_service.py,`get_sw_index_daily` 后、`aclose` 前):

```python
    async def get_trade_cal(self, *, start: str, end: str) -> pd.DataFrame: ...
```

- [ ] **Step 4: 加 RealTushareService 实现**(`get_sw_index_daily` 实现后):

```python
    async def get_trade_cal(self, *, start: str, end: str) -> pd.DataFrame:
        # 交易日历:确定性历法,纯净(不读墙上时钟,日期由调用方显式传)。
        # tushare trade_cal 默认 exchange=SSE(沪),A 股沪深同历,取 SSE 即可。
        return await self._call_cached(
            "trade_cal",
            {"exchange": "SSE", "start_date": start, "end_date": end},
        )
```

- [ ] **Step 5: 加 Mock 适配器实现**(tushare_mock_adapter.py,`get_index_daily` 旁):

```python
    async def get_trade_cal(self, *, start: str, end: str) -> pd.DataFrame:
        # 交易日历是确定性历法,绝不走 LLM 生成(见 mock-tushare-adapter-is-llm-backed)。
        from app.services.trade_calendar import build_calendar_df

        return build_calendar_df(start, end)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/unit/services/test_trade_calendar.py -v`
Expected: PASS（全绿）

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/tushare_service.py backend/app/services/tushare_mock_adapter.py backend/tests/unit/services/test_trade_calendar.py
git commit -m "feat(chatloop): TushareService.get_trade_cal(real 包 tushare / mock 确定性历法)"
```

---

## Task 3: trade_cal MCP 工具(TOOL_DEF + handle 六动作)

**Files:**
- Create: `backend/app/mcp_server/tools/trade_cal.py`
- Test: `backend/tests/unit/mcp_server/test_trade_cal_tool.py`

设计要点:`handle` 收 `{action, date?, start?, end?}`;单日动作(is_open/latest/prev/next)按 `date` 取一个 ±15 天窗口(覆盖最长节假日缺口)在 DataFrame 上解析;区间动作(count/list)直接用 start/end。按 action 校验缺参 → 返回 `[参数校验失败]` 指导文案(对齐 get_market_indicators 在 handler 内校验的范式)。日期一律来自参数,handle 内不调 `datetime.now()`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/mcp_server/test_trade_cal_tool.py
import json
import pytest
from app.mcp_server.tools.trade_cal import handle

async def _call(args):
    out = await handle(args)
    return json.loads(out[0].text)

@pytest.mark.asyncio
async def test_is_open_weekend(monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    r = await _call({"action": "is_open", "date": "20260614"})  # 周日
    assert r["is_open"] is False

@pytest.mark.asyncio
async def test_latest_from_sunday(monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    r = await _call({"action": "latest", "date": "20260614"})  # 周日
    assert r["result_date"] == "20260612"  # 上一个周五

@pytest.mark.asyncio
async def test_prev_and_next(monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    assert (await _call({"action": "prev", "date": "20260615"}))["result_date"] == "20260612"
    assert (await _call({"action": "next", "date": "20260612"}))["result_date"] == "20260615"

@pytest.mark.asyncio
async def test_count_and_list(monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    c = await _call({"action": "count", "start": "20260601", "end": "20260607"})
    assert c["count"] == 5  # 周一到周日里 5 个交易日(无节假日)
    lst = await _call({"action": "list", "start": "20260601", "end": "20260607"})
    assert lst["count"] == 5 and len(lst["dates"]) == 5

@pytest.mark.asyncio
async def test_missing_param_guidance(monkeypatch):
    monkeypatch.setenv("TUSHARE_MODE", "mock")
    r = await _call({"action": "latest"})  # 缺 date
    assert "参数校验失败" in r.get("error", "")
```

> 注:20260612 是否为周五、20260601 周一须按真实星期;若与历法不符,执行时用 `build_calendar_df` 实跑校正断言日期(不臆测)。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/mcp_server/test_trade_cal_tool.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 写实现**

```python
# backend/app/mcp_server/tools/trade_cal.py
"""MCP tool — trade_cal(A 股交易日历:开市判断/最近交易日/区间交易日)。

六动作:is_open / latest / prev / next / count / list。
日期一律由参数显式传入,handle 内绝不读 datetime.now()(确定性,可 cassette/可 RL)。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from mcp.types import TextContent, Tool

_SINGLE = {"is_open", "latest", "prev", "next"}
_RANGE = {"count", "list"}
_LIST_CAP = 260

TOOL_DEF = Tool(
    name="trade_cal",
    description=(
        "A-share trading calendar. action one of: is_open/latest/prev/next (need `date`), "
        "count/list (need `start`+`end`). Dates YYYYMMDD. Pass today explicitly for relative queries."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": sorted(_SINGLE | _RANGE)},
            "date": {"type": "string", "description": "YYYYMMDD (single-date actions)"},
            "start": {"type": "string", "description": "YYYYMMDD (range actions)"},
            "end": {"type": "string", "description": "YYYYMMDD (range actions)"},
        },
        "required": ["action"],
    },
)


def _err(msg: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"error": msg}, ensure_ascii=False))]


def _ok(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, default=str))]


def _shift(ymd: str, days: int) -> str:
    d = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])) + timedelta(days=days)
    return d.strftime("%Y%m%d")


async def handle(args: dict[str, Any]) -> list[TextContent]:
    from app.services.tushare_factory import build_tushare_service

    action = args.get("action")
    if action not in (_SINGLE | _RANGE):
        return _err(f"[参数校验失败] action 必须是 {sorted(_SINGLE | _RANGE)} 之一")

    tushare = build_tushare_service()

    if action in _SINGLE:
        qdate = args.get("date")
        if not qdate:
            return _err("[参数校验失败] is_open/latest/prev/next 需要 date(YYYYMMDD)")
        # ±15 天窗口覆盖最长节假日缺口
        df = await tushare.get_trade_cal(start=_shift(qdate, -15), end=_shift(qdate, 15))
        opens = [r["cal_date"] for r in df.to_dict("records") if int(r["is_open"]) == 1]
        if action == "is_open":
            return _ok({"action": action, "date": qdate, "is_open": qdate in opens})
        if action == "latest":  # ≤ qdate 的最近交易日
            le = [d for d in opens if d <= qdate]
            return _ok({"action": action, "query_date": qdate,
                        "result_date": max(le) if le else None,
                        "is_open_on_query": qdate in opens})
        if action == "prev":  # 严格早于
            lt = [d for d in opens if d < qdate]
            return _ok({"action": action, "query_date": qdate, "result_date": max(lt) if lt else None})
        gt = [d for d in opens if d > qdate]  # next
        return _ok({"action": action, "query_date": qdate, "result_date": min(gt) if gt else None})

    # range: count / list
    start, end = args.get("start"), args.get("end")
    if not start or not end:
        return _err("[参数校验失败] count/list 需要 start 与 end(YYYYMMDD)")
    df = await tushare.get_trade_cal(start=start, end=end)
    opens = sorted(r["cal_date"] for r in df.to_dict("records") if int(r["is_open"]) == 1)
    if action == "count":
        return _ok({"action": action, "start": start, "end": end, "count": len(opens)})
    truncated = len(opens) > _LIST_CAP
    dates = opens[-_LIST_CAP:] if truncated else opens
    return _ok({"action": action, "start": start, "end": end,
                "count": len(opens), "dates": dates, "truncated": truncated})
```

- [ ] **Step 4: 跑测试确认通过(必要时用 build_calendar_df 校正断言日期)**

Run: `pytest tests/unit/mcp_server/test_trade_cal_tool.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Commit**

```bash
git add backend/app/mcp_server/tools/trade_cal.py backend/tests/unit/mcp_server/test_trade_cal_tool.py
git commit -m "feat(chatloop): trade_cal MCP 工具(六动作,纯函数不读墙上时钟)"
```

---

## Task 4: 接线(server 注册 + tool_docs + 测试计数)

**Files:**
- Modify: `backend/app/mcp_server/server.py`(`_CHAT_TOOL_MODULES`,~line 34-47)
- Modify: `backend/app/chatloop/tool_docs.py`(TOOL_DOCS dict 末尾 + DEFERRED_TOOLS)
- Modify: `backend/tests/unit/chatloop/test_progressive_disclosure.py`(计数 21→22 / 13→14)
- Modify: `backend/tests/e2e/test_chatloop_cassette.py`(`_FAKE_RESULTS` 加 trade_cal + 改陈旧计数注释)

- [ ] **Step 1: server.py 注册** — `_CHAT_TOOL_MODULES` 列表加一行 `"app.mcp_server.tools.trade_cal",`(紧跟 get_index_daily/get_sector_daily 等同族)。

- [ ] **Step 2: tool_docs.py 加条目** — TOOL_DOCS dict 末尾(get_portfolio_positions 后):

```python
    "trade_cal": ToolDoc(
        name="trade_cal",
        group="deferred",
        brief="查 A 股交易日历(某天开市吗/最近交易日/区间交易日)。算相对日期、定 trade_date 时用。",
        doc=(
            "查 A 股交易日历(沪深同历)。\n"
            "何时用:用户说相对时间(近一年/上季度/最近)需换算成交易日;周末/节假日要找最近一个开市日;"
            "给其它工具填 trade_date/start/end 前确认是真实交易日;算区间内有多少个交易日。\n"
            "何时不用:已知确切交易日直接用;查行情/财务走对应数据工具。\n"
            "参数:\n"
            "  action(str,必填,枚举)—— is_open(某天是否开市)/latest(≤该日的最近交易日)/"
            "prev(上一交易日)/next(下一交易日)/count(区间交易日数)/list(区间交易日列表)。\n"
            "  date(str,条件必填)—— is_open/latest/prev/next 用,YYYYMMDD;相对查询时传'今天'(见尾部)。\n"
            "  start/end(str,条件必填)—— count/list 用,YYYYMMDD。\n"
            "示例:trade_cal(action='latest', date='20260614') / "
            "trade_cal(action='count', start='20260101', end='20260331')。\n"
            "硬约束:date 一律显式传(工具不假设'今天');list 最多返回最近 260 个交易日。"
        ),
        thin_required={"action": "string"},
    ),
```

DEFERRED_TOOLS 列表末尾加 `"trade_cal",`。

- [ ] **Step 3: 改测试计数** — `test_progressive_disclosure.py`:`len(TOOL_DOCS) == 21` → `== 22`;`len(DEFERRED_TOOLS) == 13` → `== 14`。**先读文件确认真实断言值再改**(可能有 schemas_for_llm 总数 22→23 的断言)。

- [ ] **Step 4: 补 _FAKE_RESULTS** — `test_chatloop_cassette.py` 的 `_FAKE_RESULTS` dict 加:

```python
    "trade_cal": {"action": "latest", "query_date": "20260614", "result_date": "20260612"},
```

并把"14 个业务工具"类陈旧注释改成正确数量。

- [ ] **Step 5: 跑相关测试**

Run: `pytest tests/unit/chatloop/test_progressive_disclosure.py tests/unit/mcp_server -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/mcp_server/server.py backend/app/chatloop/tool_docs.py backend/tests/unit/chatloop/test_progressive_disclosure.py backend/tests/e2e/test_chatloop_cassette.py
git commit -m "feat(chatloop): 注册 trade_cal(server+tool_docs)+同步工具计数测试(22→23)"
```

---

## Task 5: 参考日期注入(ContextDeps + 尾部 + chat_runner + 系统提示)

**Files:**
- Modify: `backend/app/chatloop/context.py`(ContextDeps line 65-79、`_assemble_regions` line 204-207)
- Modify: `backend/app/chatloop/system_prompt.py`(CHAT_SYSTEM_PROMPT 加一句)
- Modify: `backend/app/tasks/chat_runner.py:256`(填 reference_date)
- Test: `backend/tests/unit/chatloop/test_context.py`

- [ ] **Step 1: 写失败测试**

```python
# 追加到 test_context.py(沿用该文件既有 state/deps fixture 构造方式)
from datetime import date
from app.chatloop.context import ContextDeps, assemble_context

def test_reference_date_in_tail(make_state):  # make_state: 既有构造 ChatLoopState 的 helper
    state = make_state()
    deps = ContextDeps(system_prompt="x", reference_date=date(2026, 6, 15))
    msgs = assemble_context(state, deps)
    tail = msgs[-1]["content"]
    assert "2026-06-15" in tail and "今天" in tail

def test_reference_date_none_backward_compatible(make_state):
    state = make_state()
    deps = ContextDeps(system_prompt="x")  # reference_date 默认 None
    tail = assemble_context(state, deps)[-1]["content"]
    assert "今天" not in tail  # 不传则尾部不变(向后兼容)
```

> 执行时按 test_context.py 现有 fixture 命名对齐(可能不是 `make_state`),不臆造。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/unit/chatloop/test_context.py -k reference_date -v`
Expected: FAIL（TypeError: unexpected keyword 'reference_date'）

- [ ] **Step 3a: ContextDeps 加字段**(context.py,import 加 `from datetime import date`;dataclass 字段区):

```python
    reference_date: date | None = None  # 会话参考日期;生产=今天,eval/RL=冻结 as-of;None=不注入(向后兼容)
```

- [ ] **Step 3b: 尾部拼"今天"**(`_assemble_regions`,区四):

```python
    remaining = max(0.0, deps.max_cny - state.budget_spent_cny)
    _wk = "一二三四五六日"
    if deps.reference_date is not None:
        rd = deps.reference_date
        today = f"今天 {rd.isoformat()} 周{_wk[rd.weekday()]}。"
    else:
        today = ""
    tail_content = f"({today}第 {state.step + 1}/{deps.max_steps} 步,预算剩 ¥{remaining:.2f}。)"
    result.append({"role": "user", "content": tail_content})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/unit/chatloop/test_context.py -k reference_date -v`
Expected: PASS

- [ ] **Step 5: 系统提示加纪律**(system_prompt.py,"## 工具使用纪律"段末加一条 bullet,纯静态不含日期值):

```python
    "- 涉及相对时间(近一年/上季度/最近)以尾部给出的「今天」为基准换算;需判断某天是否开市、"
    "最近交易日、区间交易日时调 trade_cal,不要自行猜测交易日。\n"
```

- [ ] **Step 6: chat_runner 填 reference_date**(chat_runner.py:256 的 `ContextDeps(...)` 加一行;文件顶部确认 `from datetime import date` 已 import 或补):

```python
        reference_date=date.today(),
```

- [ ] **Step 7: 跑 context + 系统提示稳定性测试**

Run: `pytest tests/unit/chatloop/test_context.py tests/unit/chatloop/test_system_prompt.py -v`
Expected: PASS（若无 test_system_prompt.py 则只跑 test_context.py;系统提示是 str 常量改动,确认无测试断言其逐字内容,有则同步）

- [ ] **Step 8: Commit**

```bash
git add backend/app/chatloop/context.py backend/app/chatloop/system_prompt.py backend/app/tasks/chat_runner.py backend/tests/unit/chatloop/test_context.py
git commit -m "feat(chatloop): 参考日期注入尾部动态区(生产=today/eval=冻结as-of)+ 日期纪律"
```

---

## Task 6: 全量回归 + 浏览器端到端

- [ ] **Step 1: 后端全量回归**(WSL fria-venv)

Run: `pytest tests/unit/chatloop tests/unit/mcp_server tests/unit/services tests/e2e/test_chatloop_cassette.py -q`
Expected: 全 PASS,无 scope 外回归。

- [ ] **Step 2: ruff + mypy 门**

Run: `ruff check backend/app/services/trade_calendar.py backend/app/mcp_server/tools/trade_cal.py backend/app/chatloop/context.py; ruff format --check ...; mypy ...`
Expected: clean(对齐 CI 门)。

- [ ] **Step 3: 浏览器端到端(claude-in-chrome)**

启动后端 + 前端(serve path,见 v0.9.x-pg-ci-done / chatloop-agent-needs-worker-for-mcp:脚本跑需 worker 保活 ctx),在聊天 UI 真实问一句"今天是哪天?最近一个交易日是哪天?"与一个相对日期问法("最近一周大盘表现"),用 claude-in-chrome 截图验证:
  - 模型回答里"今天"对得上注入日期;
  - 周末/节假日能落到正确最近交易日(看 trace 里 trade_cal 调用 + result_date);
  - 录一段 gif 留证。
Expected: 端到端表现正确,trade_cal 真被调起。

> 浏览器端到端失败/卡 2-3 次按"避免兔子洞"约定停下报告,不空转。

- [ ] **Step 4: review** — 用 superpowers:requesting-code-review 对全 diff 走一遍;按 receiving-code-review 处理反馈。

---

## Task 7: PR + CI + 合入

- [ ] **Step 1: 提 PR 前查污染**(shared-checkout-git-head-collision):`git log origin/main..HEAD --oneline` 确认只含本功能 commit;若混入并发 session commit,按 stacked-pr-squash-merge-playbook cherry-pick 到基于 origin/main 的干净分支重开。
- [ ] **Step 2: push 干净分支 + `gh pr create`**(标题/正文中文,附 spec/plan 链接 + 验收点)。
- [ ] **Step 3: 盯 CI**(`gh pr checks --watch`);红了定位修到绿。
- [ ] **Step 4: CI 全绿后合入**(按仓库惯例 squash);合入后确认 main 绿。

---

## Self-Review(对 spec 核对)

- spec「组件一 trade_cal」→ Task 1/2/3/4 ✓(六动作、纯函数、deferred、cassette、mock 真历法)。
- spec「组件二 参考日期注入」→ Task 5 ✓(ContextDeps 字段 + 区四 + chat_runner today + eval/RL 冻结 as-of 经默认值机制)。
- spec「组件三 系统提示纪律」→ Task 5 Step 5 ✓(静态不含日期值)。
- spec「确定性铁律」→ Task 2/3 ✓(get_trade_cal 不读 now;handle 不读 now;mock 不走 LLM)。
- spec「接线 + 测试 四处」→ Task 4 ✓(server / tool_docs / progressive_disclosure / _FAKE_RESULTS)+ 新单测。
- spec「不做边界」→ 计划未触披露日解析 / 注入不预算最近交易日 / 无 LLM·无墙上时钟 ✓。
- 类型一致性:`get_trade_cal(*, start, end) -> pd.DataFrame` 在 Protocol/Real/Mock 三处签名一致;`build_calendar_df(start, end)` 列 cal_date/is_open/pretrade_date 与 handle 消费字段一致 ✓。
- 待执行时校正项:断言里的具体星期日期(20260612 等)用 build_calendar_df 实跑核对;test_progressive_disclosure 真实断言值、test_context fixture 名执行时读文件确认,不臆造。
