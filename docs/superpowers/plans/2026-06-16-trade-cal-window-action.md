# trade_cal `window` 复合动作 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 trade_cal 加第 7 个动作 `window`,一次把"今天 + 周期码"解析成交易日窗口({start, end, trading_days, anchor_is_open}),消除 agent 反复多次调 trade_cal 解析相对区间的啰嗦。

**Architecture:** 纯新增,不动现有 6 动作。先实现可单测的纯函数(周期码解析 `_parse_lookback` + 月/年回退 `_minus_months`/`_minus_years` + raw_start 解析 `_resolve_raw_start`);再加 async 的 `_handle_window`(取历法 → 算两端 → 组装),挂进 `handle` 分派;最后接线工具文档与 system_prompt 引导 agent 用它。日期一律由参数显式传入,handle 内绝不读时钟(与现有动作一致,确定性 / 可 cassette / 可 RL)。

**Tech Stack:** Python / pandas / pytest-asyncio;MCP TOOL_DEF + handle 模式;mock 模式走确定性历法 `build_calendar_df`。

**Spec:** `docs/superpowers/specs/2026-06-16-trade-cal-window-action-design.md`

---

## 文件结构

| 文件 | 责任 | 改动 |
|---|---|---|
| `backend/app/mcp_server/tools/trade_cal.py` | trade_cal 工具(TOOL_DEF + handle + 历法解析) | 加 `_WINDOW`、4 个纯函数、`_handle_window`、分派 + inputSchema/TOOL_DEF |
| `backend/tests/unit/mcp_server/test_trade_cal_tool.py` | trade_cal 工具单测 | 加纯函数测试 + window 动作 6 个用例 |
| `backend/app/chatloop/tool_docs.py` | chat 端工具渐进披露文档 | trade_cal `doc` 加 window 说明 + nudge |
| `backend/app/chatloop/system_prompt.py` | chat 系统提示 | 相对时间那句改指向 `window` |

**测试环境**:后端测试在 WSL `fria-venv` 跑(见 memory `backend-runtime-env-wsl-fria-venv`)。所有 `pytest` 命令在 `backend/` 目录下、fria-venv 内执行。git 操作走 Windows PowerShell(repo 在 `D:\mys\...`,git-bash/WSL 的 `/mnt/d` 是空桩)。

---

## Task 1: 周期码解析 + 月/年回退纯函数

**Files:**
- Modify: `backend/app/mcp_server/tools/trade_cal.py`(顶部 import + 模块级纯函数)
- Test: `backend/tests/unit/mcp_server/test_trade_cal_tool.py`(文件末尾追加)

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/unit/mcp_server/test_trade_cal_tool.py` 末尾追加(这些是同步纯函数测试,不需要 `@pytest.mark.asyncio`):

```python
def test_parse_lookback_valid():
    from app.mcp_server.tools.trade_cal import _parse_lookback

    assert _parse_lookback("1y") == ("y", 1)
    assert _parse_lookback("6m") == ("m", 6)
    assert _parse_lookback("30d") == ("d", 30)
    assert _parse_lookback("20td") == ("td", 20)
    assert _parse_lookback("ytd") == ("ytd", 0)


def test_parse_lookback_invalid():
    from app.mcp_server.tools.trade_cal import _parse_lookback

    for bad in ["", "0y", "abc", "y", "1ytd", "-3m", None]:
        with pytest.raises(ValueError):
            _parse_lookback(bad)


def test_minus_months_and_years_clamp():
    from app.mcp_server.tools.trade_cal import _minus_months, _minus_years

    assert _minus_years("20260616", 1) == "20250616"
    assert _minus_years("20240229", 1) == "20230228"  # 闰日夹到 2/28
    assert _minus_months("20260616", 6) == "20251216"
    assert _minus_months("20260331", 1) == "20260228"  # 日溢出夹到月末(2026 非闰)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/mcp_server/test_trade_cal_tool.py -k "parse_lookback or minus_months" -v`
Expected: FAIL — `ImportError: cannot import name '_parse_lookback'`(及 `_minus_months`/`_minus_years`)。

- [ ] **Step 3: Implement the pure functions**

在 `backend/app/mcp_server/tools/trade_cal.py` 顶部 import 区,**在现有 import 基础上新增两行**(其余 import 一律保留,尤其 `from mcp.types import TextContent, Tool` 不要动):新增 `import re` 与 `from calendar import monthrange`。改完后顶部应为:

```python
import json
import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from mcp.types import TextContent, Tool
```

在 `_ACTIONS` 等常量之后、`TOOL_DEF` 之前,加模块级常量与纯函数:

```python
_LOOKBACK_RE = re.compile(r"^(\d+)(y|m|d|td)$")


def _parse_lookback(code: Any) -> tuple[str, int]:
    """周期码 → (kind, n)。'ytd' 返回 ('ytd', 0);Ny/Nm/Nd/Ntd 返回 (单位, N)。非法抛 ValueError。"""
    if code == "ytd":
        return ("ytd", 0)
    m = _LOOKBACK_RE.match(code if isinstance(code, str) else "")
    if not m or int(m.group(1)) <= 0:
        raise ValueError(f"非法 lookback: {code!r}(形如 1y/6m/30d/20td/ytd)")
    return (m.group(2), int(m.group(1)))


def _minus_months(ymd: str, n: int) -> str:
    """anchor 减 N 个月;日溢出夹到目标月末(如 3/31 −1 月 → 2/28)。"""
    y, mo, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
    total = y * 12 + (mo - 1) - n
    ny, nm = divmod(total, 12)
    nm += 1
    last = monthrange(ny, nm)[1]
    return date(ny, nm, min(d, last)).strftime("%Y%m%d")


def _minus_years(ymd: str, n: int) -> str:
    """anchor 减 N 年(复用月回退,闰日 2/29 自动夹到 2/28)。"""
    return _minus_months(ymd, n * 12)
```

> 注:正则 `(y|m|d|td)` 配 `$` 锚定,对 `20td` 先试 `y/m/d` 在 `t` 处失配,再命中 `td`;对 `30d` 在 `d` 处即命中。无歧义。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/mcp_server/test_trade_cal_tool.py -k "parse_lookback or minus_months" -v`
Expected: PASS(3 个测试)。

- [ ] **Step 5: Commit**

(Windows PowerShell, in `D:\mys\Financial-Research-Investment-Assistant`)
```powershell
git add -- backend/app/mcp_server/tools/trade_cal.py backend/tests/unit/mcp_server/test_trade_cal_tool.py
git commit -m "feat(trade_cal): 周期码解析 + 月/年回退纯函数(window 动作基件)"
```

---

## Task 2: `_handle_window` + 分派 + schema + window 动作单测

**Files:**
- Modify: `backend/app/mcp_server/tools/trade_cal.py`(`_WINDOW` 常量、`_ACTIONS`、inputSchema、TOOL_DEF.description、`_resolve_raw_start`、`_handle_window`、`handle` 分派)
- Test: `backend/tests/unit/mcp_server/test_trade_cal_tool.py`

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/unit/mcp_server/test_trade_cal_tool.py` 末尾追加(用现有 `_call` 帮手 + `_mock_mode` autouse fixture):

```python
@pytest.mark.asyncio
async def test_window_1y():
    r = await _call({"action": "window", "anchor": "20260616", "lookback": "1y"})
    assert r["start"] == "20250616"
    assert r["end"] == "20260616"
    assert r["anchor_is_open"] is True
    # trading_days 与 count 动作自洽
    c = await _call({"action": "count", "start": "20250616", "end": "20260616"})
    assert r["trading_days"] == c["count"]


@pytest.mark.asyncio
async def test_window_ytd_snaps_forward_past_holiday():
    r = await _call({"action": "window", "anchor": "20260616", "lookback": "ytd"})
    assert r["start"] == "20260105"  # 0101/0102 元旦休 + 周末 → 顺延到 1/5
    assert r["end"] == "20260616"


@pytest.mark.asyncio
async def test_window_n_trading_days():
    r = await _call({"action": "window", "anchor": "20260616", "lookback": "20td"})
    assert r["trading_days"] == 20
    assert r["end"] == "20260616"
    assert r["start"] == "20260520"  # 从 6/16 倒数第 20 个交易日
    c = await _call({"action": "count", "start": r["start"], "end": r["end"]})
    assert c["count"] == 20  # start..end 恰好 20 个交易日


@pytest.mark.asyncio
async def test_window_anchor_on_weekend():
    r = await _call({"action": "window", "anchor": "20260620", "lookback": "1y"})  # 6/20 周六
    assert r["anchor_is_open"] is False
    assert r["end"] == "20260618"  # 6/19 端午休、6/20 周六 → 最近交易日 6/18


@pytest.mark.asyncio
async def test_window_bad_lookback():
    r = await _call({"action": "window", "anchor": "20260616", "lookback": "xy"})
    assert "参数校验失败" in r.get("error", "")


@pytest.mark.asyncio
async def test_window_missing_anchor():
    r = await _call({"action": "window", "lookback": "1y"})
    assert "参数校验失败" in r.get("error", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/mcp_server/test_trade_cal_tool.py -k window -v`
Expected: FAIL — window 未识别,`handle` 返回 `[参数校验失败] action 必须是 ...`(`start`/`end` KeyError 或断言失败)。

- [ ] **Step 3: Implement window action**

3a. 在 `trade_cal.py` 顶部常量处,加 `_WINDOW` 并并入 `_ACTIONS`:

```python
_SINGLE = {"is_open", "latest", "prev", "next"}
_RANGE = {"count", "list"}
_WINDOW = {"window"}
_ACTIONS = sorted(_SINGLE | _RANGE | _WINDOW)
_WINDOW_DAYS = 15  # 单日动作回看/前看窗口(覆盖最长节假日缺口)
_LIST_CAP = 260
```

3b. 更新 `TOOL_DEF`:`description` 补 window;`inputSchema.properties` 加 `anchor`/`lookback`:

```python
TOOL_DEF = Tool(
    name="trade_cal",
    description=(
        "A-share trading calendar. action one of: is_open/latest/prev/next (need `date`), "
        "count/list (need `start`+`end`), window (need `anchor`+`lookback`, resolves a "
        "relative window in one call). Dates YYYYMMDD. Pass today explicitly for relative queries."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": _ACTIONS},
            "date": {"type": "string", "description": "YYYYMMDD (single-date actions)"},
            "start": {"type": "string", "description": "YYYYMMDD (range actions)"},
            "end": {"type": "string", "description": "YYYYMMDD (range actions)"},
            "anchor": {"type": "string", "description": "YYYYMMDD (window action: today/as-of)"},
            "lookback": {"type": "string", "description": "window action: 1y/6m/30d/20td/ytd"},
        },
        "required": ["action"],
    },
)
```

3c. 在纯函数区(Task 1 加的函数之后)加 `_resolve_raw_start`:

```python
def _resolve_raw_start(anchor: str, kind: str, n: int) -> str:
    """日历型周期(y/m/d/ytd)的 raw_start(尚未顺延到交易日)。td 不走此函数。"""
    if kind == "ytd":
        return anchor[:4] + "0101"
    if kind == "y":
        return _minus_years(anchor, n)
    if kind == "m":
        return _minus_months(anchor, n)
    if kind == "d":
        return _shift(anchor, -n)
    raise ValueError(f"unexpected calendar kind: {kind}")
```

3d. 加 `_handle_window`(放在 `handle` 之前):

```python
async def _handle_window(tushare: Any, args: dict[str, Any]) -> list[TextContent]:
    anchor = args.get("anchor")
    if _bad_ymd(anchor):
        return _err("[参数校验失败] window 需要 anchor(8 位 YYYYMMDD)")
    try:
        kind, n = _parse_lookback(args.get("lookback"))
    except ValueError:
        return _err("[参数校验失败] lookback 形如 1y/6m/30d/20td/ytd")

    if kind == "td":  # 计数型:从 end 倒数 N 个交易日
        df = await tushare.get_trade_cal(start=_shift(anchor, -(n * 2 + 30)), end=anchor)
        opens = _open_dates(df)
        le = [d for d in opens if d <= anchor]
        if not le:
            return _err("[数据为空] 该区间无交易日")
        window = le[-n:]
        start, end, trading_days = window[0], le[-1], len(window)
    else:  # 日历型:raw_start 顺延到首个交易日
        raw_start = _resolve_raw_start(anchor, kind, n)
        df = await tushare.get_trade_cal(start=raw_start, end=anchor)
        opens = _open_dates(df)
        if not opens:
            return _err("[数据为空] 该区间无交易日")
        start, end, trading_days = opens[0], opens[-1], len(opens)

    return _ok(
        {
            "action": "window",
            "anchor": anchor,
            "lookback": args.get("lookback"),
            "start": start,
            "end": end,
            "trading_days": trading_days,
            "anchor_is_open": anchor in opens,
        }
    )
```

3e. 在 `handle` 里更新 action 校验并加 window 分派。把:

```python
    action = args.get("action")
    if action not in _SINGLE and action not in _RANGE:
        return _err(f"[参数校验失败] action 必须是 {_ACTIONS} 之一")

    tushare = build_tushare_service()

    if action in _SINGLE:
```

改为:

```python
    action = args.get("action")
    if action not in _ACTIONS:
        return _err(f"[参数校验失败] action 必须是 {_ACTIONS} 之一")

    tushare = build_tushare_service()

    if action in _WINDOW:
        return await _handle_window(tushare, args)

    if action in _SINGLE:
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/mcp_server/test_trade_cal_tool.py -v`
Expected: PASS(原 8 + 新 9 = 17 个全过)。

- [ ] **Step 5: Commit**

```powershell
git add -- backend/app/mcp_server/tools/trade_cal.py backend/tests/unit/mcp_server/test_trade_cal_tool.py
git commit -m "feat(trade_cal): window 动作(今天+周期码 一次解析交易日窗口)"
```

---

## Task 3: 工具文档 + system_prompt 接线(引导 agent 用 window)

**Files:**
- Modify: `backend/app/chatloop/tool_docs.py`(trade_cal 的 `doc`)
- Modify: `backend/app/chatloop/system_prompt.py`(相对时间那句)

- [ ] **Step 1: 更新 tool_docs**

在 `backend/app/chatloop/tool_docs.py` 的 `trade_cal` ToolDoc 里,把 `doc` 字段(现以 `action(str,必填,枚举)…… count(区间交易日数)/list(区间交易日列表)。` 结尾的那段)改为加入 window 动作与 nudge。具体:

把:
```python
            "  action(str,必填,枚举)—— is_open(某天是否开市)/latest(≤该日的最近交易日)/"
            "prev(上一交易日)/next(下一交易日)/count(区间交易日数)/list(区间交易日列表)。\n"
            "  date(str,条件必填)—— is_open/latest/prev/next 用,YYYYMMDD;相对查询时传'今天'"
            "(见尾部动态区给的今天)。\n"
            "  start/end(str,条件必填)—— count/list 用,YYYYMMDD。\n"
            "示例:trade_cal(action='latest', date='20260614') / "
            "trade_cal(action='count', start='20260101', end='20260331')。\n"
            "硬约束:date 一律显式传(工具不假设'今天');list 最多返回最近 260 个交易日。"
```
改为:
```python
            "  action(str,必填,枚举)—— window(相对区间一次解析,**优先用**)/is_open(某天是否开市)/"
            "latest(≤该日的最近交易日)/prev(上一交易日)/next(下一交易日)/count(区间交易日数)/"
            "list(区间交易日列表)。\n"
            "  anchor + lookback(window 用)—— anchor=今天(YYYYMMDD,见尾部动态区);"
            "lookback=周期码 1y/6m/3m/1m/30d/20td/ytd。一次返回 {start,end,trading_days,anchor_is_open}。\n"
            "  date(str,条件必填)—— is_open/latest/prev/next 用,YYYYMMDD;相对查询时传'今天'。\n"
            "  start/end(str,条件必填)—— count/list 用,YYYYMMDD。\n"
            "示例:trade_cal(action='window', anchor='20260616', lookback='1y') / "
            "trade_cal(action='latest', date='20260614')。\n"
            "硬约束:date/anchor 一律显式传(工具不假设'今天');算相对区间(近一年/近N月/年初至今)"
            "**优先用 window 一次拿全,别 is_open+latest 拆成多次调**;list 最多返回最近 260 个交易日。"
```

- [ ] **Step 2: 更新 system_prompt**

在 `backend/app/chatloop/system_prompt.py`,把:
```python
    "- 相对时间(近一年/上季度/最近)按尾部给的「今天」换算;要交易日/最近交易日调 trade_cal,别自己猜。\n"
```
改为:
```python
    "- 相对时间(近一年/上季度/最近)按尾部给的「今天」换算;要把相对区间落成交易日窗口,"
    "用 trade_cal 的 window 动作(给今天 anchor + 周期码 lookback)一次拿全,别自己减日期或拆多次调。\n"
```

- [ ] **Step 3: 跑工具文档相关测试,确认无回归**

Run: `python -m pytest tests/unit/chatloop/test_progressive_disclosure.py tests/unit/test_mcp_server_profiles.py -v`
Expected: PASS(window 是 trade_cal 内新增动作,不新增顶层工具,故 profile 计数不变;若有断言精确匹配 trade_cal doc 文本则同步更新该断言)。

- [ ] **Step 4: Commit**

```powershell
git add -- backend/app/chatloop/tool_docs.py backend/app/chatloop/system_prompt.py
git commit -m "docs(chatloop): trade_cal window 文档 nudge + system_prompt 指向 window"
```

---

## Task 4: 全量回归 + live 抽测

**Files:** 无新增;验证 + 收尾。

- [ ] **Step 1: 跑 trade_cal 全量 + 历法 + MCP 相关回归**

Run:
```bash
python -m pytest tests/unit/mcp_server/test_trade_cal_tool.py \
  tests/unit/services/test_trade_calendar.py \
  tests/unit/mcp_server/test_mcp_tools.py \
  tests/unit/test_mcp_server_profiles.py \
  tests/unit/chatloop/test_progressive_disclosure.py -v
```
Expected: 全 PASS,无回归。

- [ ] **Step 2: ruff format/lint(对齐 CI)**

Run: `ruff format backend/app/mcp_server/tools/trade_cal.py backend/tests/unit/mcp_server/test_trade_cal_tool.py backend/app/chatloop/tool_docs.py backend/app/chatloop/system_prompt.py && ruff check backend/app/mcp_server/tools/trade_cal.py`
Expected: 无改动 / 无告警(若 format 有改动,`git add` 后补提交)。

- [ ] **Step 3: live 抽测一道「近一年」(隔离栈 + 真 tushare)**

> 这步用 WSL 起隔离栈(backend :8001 + worker + MCP,Redis DB 9/10/13),走真 tushare,问一道"贵州茅台近一年涨了多少",看 trace 里日期解析是否从多次 trade_cal 收成 1 次 `window`(adoption 由 nudge 引导,允许偶尔多调)。属人工验证,不阻塞合入;栈起法见上轮 pass@k 隔离栈记录。
> 验收:trace 出现 `trade_cal(action='window', lookback='1y')` 且该窗口未再分多次 is_open/latest;答案 −10.63% 不变。

- [ ] **Step 4: 收尾 commit(若 ruff 有 format 改动)**

```powershell
git add -- backend/
git commit -m "style(trade_cal): ruff format(window 动作收尾)"
```

---

## 完成后

按 `superpowers:finishing-a-development-branch` 收束(本特性挂在 `feat/portfolio-overview` 分支随行;PR 前按 memory `shared-checkout-git-head-collision` 查 `origin/main..HEAD` 有无他人提交污染)。
