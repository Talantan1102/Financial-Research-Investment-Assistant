# 缩工具链(get_daily 内联窗口)+ SFT 轨迹采集 第一批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** get_daily 内联 `anchor+lookback`,把"先 trade_cal 定窗→再 get_daily 取数"的两步并一步、消灭"漏 anchor 就放弃"整类失败;runner 加采集模式,落完整解题轨迹、隔离 gold、关降级,为 SFT 热启动备干净种子。

**Architecture:** 承 `docs/superpowers/specs/2026-06-18-shorten-chains-and-rl-substrate-design.md` 落地步 1+2 的**已确认部分**。讨论后两处收窄:**get_daily_batch(批量取数)砍掉**(原子性 + 避免用工具绕过模型的编排弱点);**连续距离判分(原 score.py)推到 RL 阶段**(它是 reward shaping,属 RL,不是 SFT 料)。全部改动在工具/eval 侧,**零侵入 loop/state/tool_hub**。窗口解析复用 trade_cal 同源逻辑,gold 不变。

**Tech Stack:** Python / MCP tools / asyncio / pytest;后端运行环境 = WSL fria-venv(`source /home/administrator/fria-venv/bin/activate && cd backend`,测试/服务需 `source .env`)。

---

## File Structure

| 文件 | 改动 |
| --- | --- |
| `backend/app/mcp_server/tools/trade_cal.py` | 加公开纯函数 `resolve_calendar_window(anchor, lookback) -> (start,end)`(组合现有 `_parse_lookback`+`_resolve_raw_start`,日历型 only;**不动** `_handle_window`) |
| `backend/app/mcp_server/tools/get_daily.py` | `start/end` 改可选 + 加 `anchor+lookback`(日历型走 resolve_calendar_window;td → 报错引导先用 trade_cal);其余不动 |
| `backend/app/chatloop/tool_docs.py` | get_daily 文档补一句"可传 anchor+lookback 让工具自己定窗口,免先调 trade_cal" |
| `backend/eval/question_gen/runner.py` | run_one 返回带 final state;采集模式关降级 + 落 trajectories_raw(无 gold)+ judgements(gold 隔离) |
| `backend/tests/...` | 各 task 配套 |

---

### Task 1: trade_cal 加公开纯函数 resolve_calendar_window

**Files:** Modify `backend/app/mcp_server/tools/trade_cal.py`;Test `backend/tests/unit/mcp_server/test_trade_cal_tool.py`

**背景(已核验真实代码):** 完整窗口解析 `_handle_window`(`:114-151`)**要查日历 I/O**(顺延到真实交易日 / `td` 倒数 N 交易日),**不是纯函数**。但日历型 lookback(y/m/d/ytd)的起点是纯计算——`_parse_lookback`(`:32`)与 `_resolve_raw_start`(`:101`)已存在且纯。本 task 只新增一个**组合这两个现成纯函数**的公开纯函数给 get_daily 复用,**不碰 `_handle_window`**(其测试保持绿)。

- [ ] **Step 1: 写失败测试**
```python
import pytest
from app.mcp_server.tools.trade_cal import resolve_calendar_window
def test_resolve_calendar_window_1y():
    assert resolve_calendar_window("20260616", "1y") == ("20250616", "20260616")
def test_resolve_calendar_window_ytd():
    assert resolve_calendar_window("20260616", "ytd") == ("20260101", "20260616")
def test_resolve_calendar_window_td_raises():
    with pytest.raises(ValueError):
        resolve_calendar_window("20260616", "20td")
```
- [ ] **Step 2: 跑测试确认失败**(`ImportError`)。
- [ ] **Step 3: 实现** —— 在 trade_cal.py 加(复用现有私有纯函数,零重复、不碰 `_handle_window`):
```python
def resolve_calendar_window(anchor: str, lookback: str) -> tuple[str, str]:
    """日历型相对窗口 → (raw_start, anchor) 纯解析(不查日历)。

    仅支持日历型 lookback(y/m/d/ytd);交易日计数型 td 需查日历倒数,不在纯路径,抛 ValueError。
    raw_start 未顺延到首个交易日,但 get_daily(start=raw_start, end=anchor) 取回的 K 线与
    trade_cal.window 顺延后的窗口逐根相同(raw_start 与首个交易日之间本无交易日)。
    """
    if _bad_ymd(anchor):
        raise ValueError("anchor 需 8 位 YYYYMMDD")
    kind, n = _parse_lookback(lookback)
    if kind == "td":
        raise ValueError("td(交易日计数)需查日历,请用 trade_cal action=window")
    return _resolve_raw_start(anchor, kind, n), anchor
```
- [ ] **Step 4: 跑** `pytest tests/unit/mcp_server/test_trade_cal_tool.py -q`(经 WSL fria-venv,见文末)→ 新测试 + 既有全绿。
- [ ] **Step 5: 提交** `feat(trade_cal): 加公开纯函数 resolve_calendar_window(日历型窗口纯解析)`

---

### Task 2: get_daily 加 anchor+lookback

**Files:** Modify `backend/app/mcp_server/tools/get_daily.py`、`backend/app/chatloop/tool_docs.py`;Test `backend/tests/unit/mcp_server/test_get_daily_tool.py`

**口径说明:** 日历型窗口下 `get_daily(start=raw_start, end=anchor)` 与 gold 走 `trade_cal.window` 顺延后的窗口取回**逐根相同的 K 线**(见 Task 1),指标计算与 gold 一致,gold 不变。

- [ ] **Step 1: 写失败测试**(纯函数层,不打网络):
```python
import pytest
from app.mcp_server.tools.get_daily import _resolve_range
def test_resolve_range_explicit():
    assert _resolve_range({"start": "20250101", "end": "20251231"}) == ("20250101", "20251231")
def test_resolve_range_anchor_lookback():
    assert _resolve_range({"anchor": "20260616", "lookback": "1y"}) == ("20250616", "20260616")
def test_resolve_range_td_raises():
    with pytest.raises(ValueError):
        _resolve_range({"anchor": "20260616", "lookback": "20td"})
def test_resolve_range_missing_raises():
    with pytest.raises(ValueError):
        _resolve_range({"ts_code": "600519.SH"})
```
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现**
  - inputSchema:`start`/`end` 从 `required` 移除(改 optional),加 `anchor`/`lookback`;`required` 只留 `ts_code`;描述补"二选一:显式 start+end,或 anchor+lookback(日历型 1y/6m/3m/ytd 自动定窗,免先调 trade_cal)"。
  - 加纯函数 `_resolve_range(args)`:显式 `start`+`end` 优先;否则 `anchor`+`lookback` 走 `trade_cal.resolve_calendar_window`;都没有 → `raise ValueError`。
  - handle 改为 `try: start,end = _resolve_range(args) except ValueError as e: return _err(str(e))`(加一个与 trade_cal 同形的 `_err`),其余 `_format_daily` 不变。
  - tool_docs.py 的 get_daily 文档补一句"可传 anchor+lookback(日历型)让工具自己定窗口,免先调 trade_cal;过去 N 个交易日(td)仍需先 trade_cal"。
- [ ] **Step 4: 跑** get_daily 单测 + 既有回归全绿。
- [ ] **Step 5: 提交** `feat(get_daily): start/end 可选 + 内联 anchor+lookback 窗口(免先调 trade_cal)`

---

### Task 3: runner 落完整轨迹 + 隔离 gold + 采集模式关降级(SFT 底座)

**Files:** Modify `backend/eval/question_gen/runner.py`;Test `backend/tests/eval/question_gen/test_runner_trajectory.py`

- [ ] **Step 1: 写失败测试**(mock LLM/hub,跑一道,断言)—— 采集模式下:① 产出 `trajectories_raw` 记录含 `messages`(完整多轮)且**不含 gold/passed**;② `judgements` 记录含 gold/passed;③ 采集模式构造的 deps `downgrade_char_threshold` 是大值(关降级)。
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现**:
  - `run_one` 返回值带上 `final`(ChatLoopState),不再只回答案;
  - 加 `collect: bool=False` 参数:`collect=True` 时 deps 传 `downgrade_char_threshold=10**9`(关降级,堵"坑一"轨迹被毁)+ 落两个文件:`trajectories_raw.jsonl`(每条 `{case_id, model, messages, n_steps, halt_reason}`,**无 gold**)与 `judgements.jsonl`(`{case_id, model, passed, gold, ...}`,gold 只在此);
  - 既有 `_dump_answers`(含 gold,`:209`)保持不变给离线重判用,但**采集产物物理分离**;非 collect 路径行为逐字不变(回归)。
- [ ] **Step 4: 跑** runner 相关单测 + 既有 `test_runner_compare`/`test_runner_trajectory` 全绿;非 collect 路径行为不变。
- [ ] **Step 5: 提交** `feat(eval): runner 采集模式落完整轨迹+隔离 gold+关降级(SFT 底座)`

---

### Task 4: 全链路守护 + 缩链效果回归(deliverable)

**Files:** 无新增;跑套件 + live 回归。

- [ ] **Step 1: 跑** `pytest tests/unit/mcp_server tests/eval/question_gen tests/unit/chatloop -q` + e2e cassette,确认无回归。
- [ ] **Step 2: mypy + ruff** 改动文件全过。
- [ ] **Step 3: live 缩链效果** —— 用**现有全量题集**重跑 deepseek(对照最近一次基线),重点看:① 总分无回归;② **用到窗口的计算题平均步数 −1**(trade_cal 那步被 get_daily 吸收);③ qwen3-8b 上"漏 anchor 就放弃"这类失败是否减少。对比 模型×桶 表落盘。
- [ ] **Step 4: 不单独提交**(报告落盘单独 commit)。

---

## Self-Review

**Spec 覆盖(收窄后)**:get_daily 内联窗口(Task 1+2)、轨迹落盘+gold 隔离+关降级(Task 3)、回归(Task 4)。**经讨论砍/推迟**:get_daily_batch(砍)、连续距离判分(推到 RL)、compute_indicator(原本就缓做)、trace_signals + SFT 导出(第二批)。

**红线对齐**:gold 不进 trajectories_raw(Task 3);未引入 compute_indicator(不碰 oracle 同源);改完跑全量回归(Task 4)。

**口径零漂移**:窗口解析(Task 1/2)复用 trade_cal 现有同源逻辑,gold 不变。

**类型一致**:`resolve_calendar_window` 与 `_resolve_range` 均返回 `tuple[str,str]`;get_daily 经 `_resolve_range` 调 `resolve_calendar_window`。

## 运行环境(subagent 必读)

测试经 WSL fria-venv 跑。**`.env` 在仓库根、是 `KEY=val` 格式,要 `set -a` 才进 os.environ**(否则 `KeyError: POSTGRES_PASSWORD`):
```
wsl bash -lc "source /home/administrator/fria-venv/bin/activate && cd /mnt/d/mys/Financial-Research-Investment-Assistant && set -a && source .env && set +a && cd backend && python -m pytest <测试路径> -q"
```
退出码 0 = 全绿(`wsl` 启动有一行 localhost/NAT 告警是噪声,忽略)。git 操作走 Windows PowerShell(仓库是 LF,提交前确认无 CRLF 污染:`git diff --cached --stat` 看行数不异常)。

---

## Execution Handoff

两种执行:**1. Subagent-Driven(推荐)** —— 每 task 派新 subagent + 两段式 review(spec 合规 → 代码质量);**2. Inline**。
