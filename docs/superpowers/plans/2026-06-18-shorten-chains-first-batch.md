# 缩工具链 + RL 底料 第一批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 缩链两工具(get_daily 内联窗口 + get_daily_batch 批量取数对齐)把"2+N 步随股票数膨胀"的链压成 2–3 步;判分 0/1 改连续距离 + runner 落完整轨迹并隔离 gold —— 为训练侧备好稠密信号与干净 SFT 轨迹的底座。

**Architecture:** 承 `docs/superpowers/specs/2026-06-18-shorten-chains-and-rl-substrate-design.md` 落地步 1+2。全部改动在工具/eval 侧,**零侵入 loop/state/tool_hub**。口径零漂移(窗口/对齐均与现有同源)。

**Tech Stack:** Python / MCP tools / asyncio / pytest;后端运行环境 = WSL fria-venv(`source /home/administrator/fria-venv/bin/activate && cd backend`,测试/服务需 `source .env`)。

---

## File Structure

| 文件 | 改动 |
| --- | --- |
| `backend/app/mcp_server/tools/trade_cal.py` | 把 window 解析(`:114-151`)抽成可复用纯函数 `resolve_window(anchor, lookback) -> (start,end)` |
| `backend/app/mcp_server/tools/get_daily.py` | 加可选 `anchor+lookback`(给了则 resolve_window 再取数);提案 2 |
| `backend/app/mcp_server/tools/get_daily_batch.py`(新) | 批量取多股 + 按 trade_date 对齐 + summary;提案 1 |
| `backend/app/mcp_server/server.py` | 注册 get_daily_batch |
| `backend/app/chatloop/tool_docs.py` | get_daily_batch 进 DEFERRED,文档写"多股排序/筛选/相关用本工具,别逐只 get_daily" |
| `backend/eval/question_gen/score.py`(新) | 连续距离判分(scalar_distance / ranking_partial / set_jaccard);不动 judge.py |
| `backend/eval/question_gen/runner.py` | run_one 返回带 final state;采集模式关降级 + 落 trajectories_raw(无 gold)+ judgements(gold 隔离) |
| `backend/tests/...` | 各 task 配套 |

---

### Task 1: 抽 trade_cal 窗口解析为共享纯函数

**Files:** Modify `backend/app/mcp_server/tools/trade_cal.py`;Test `backend/tests/unit/mcp_server/test_trade_cal_tool.py`(已存在 window 测试,加共享函数测试)

- [ ] **Step 1: 读** `trade_cal.py:114-151`(现 window action 的解析逻辑:anchor + lookback 周期码 → (start,end))。
- [ ] **Step 2: 写失败测试** —— 直接测新纯函数:
```python
from app.mcp_server.tools.trade_cal import resolve_window
def test_resolve_window_1y():
    s, e = resolve_window("20260616", "1y")
    assert e == "20260616" and s == "20250616"  # 与现 window action 同结果(对照现有 test_trade_cal 的 window 用例)
```
- [ ] **Step 3: 实现** —— 把 `:114-151` 的解析体抽成模块级 `def resolve_window(anchor: str, lookback: str) -> tuple[str, str]`(纯函数,不碰 I/O);原 window action 的 handle 改为调它。**行为逐字不变**(原 window 测试必须仍绿)。
- [ ] **Step 4: 跑** `pytest tests/unit/mcp_server/test_trade_cal_tool.py -q` → 既有 window 测试 + 新测试全绿。
- [ ] **Step 5: 提交** `refactor(trade_cal): window 解析抽成共享纯函数 resolve_window`

---

### Task 2: get_daily 加 anchor+lookback(提案 2)

**Files:** Modify `backend/app/mcp_server/tools/get_daily.py`、`backend/app/chatloop/tool_docs.py`;Test `backend/tests/unit/mcp_server/test_get_daily_tool.py`

- [ ] **Step 1: 写失败测试**(纯函数层,不打网络)—— 断言"给 anchor+lookback 时,handle 解析出的 (start,end) 等于 resolve_window 的结果"(可对 handle 做参数解析的薄单测,或抽一个 `_resolve_range(args)->(start,end)` 纯函数单测)。
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现** —— get_daily inputSchema 加可选 `anchor`/`lookback`;handle 里:`if args 给了 anchor+lookback: start,end = trade_cal.resolve_window(anchor,lookback)` 否则用 `start/end`(二选一,都没给 → 报错指导)。其余取数/格式化不变。tool_docs 的 get_daily 文档补一句"也可传 anchor+lookback 让工具自己定窗口,免先调 trade_cal"。
- [ ] **Step 4: 跑** get_daily 单测 + 既有回归全绿。
- [ ] **Step 5: 提交** `feat(get_daily): 内联 anchor+lookback 窗口(免先调 trade_cal)`

---

### Task 3: get_daily_batch 批量取数 + 对齐(提案 1)

**Files:** Create `backend/app/mcp_server/tools/get_daily_batch.py`;Modify `server.py`、`tool_docs.py`;Test `backend/tests/unit/mcp_server/test_get_daily_batch_tool.py`

- [ ] **Step 1: 读** `compare_stocks.py:42-62`(asyncio.gather 并行聚合多股的现成范式)+ `get_daily.py:_format_daily`(列式+summary)。
- [ ] **Step 2: 写失败测试**(纯函数层,mock/手写 df)—— 测对齐纯函数 `_align_by_date(by_code) -> (aligned_dates, by_code_trimmed)`:给两只交易日不同的序列,断言交集对齐、各序列按交集裁齐、顺序升序。
- [ ] **Step 3: 实现** —— 新 MCP tool `get_daily_batch`:
  - 入参 `ts_codes:list[str](2–10)` + `start/end`(或 `anchor/lookback` 复用 Task 1 的 resolve_window);
  - 内部 `rows = await asyncio.gather(*[tushare.get_daily(ts_code=c,start=s,end=e) for c in ts_codes])`,每只过 `_format_daily`;
  - `_align_by_date`:取各 code trade_date 交集排序,各 `close/pct_chg` 按交集裁齐;
  - 返回 `{start,end, aligned_dates, by_code:{code:{dates,close,pct_chg,summary{first_close,last_close,count}}}}`;
  - server.py 注册;tool_docs 进 DEFERRED + 触发词文档("算多股排序/筛选/相关用本工具,不要逐只 get_daily")。
- [ ] **Step 4: 跑** 新单测 + `tests/integration/test_mcp_client_e2e.py`(工具计数会变,按实际 +1 更新断言)。
- [ ] **Step 5: 提交** `feat(get_daily_batch): 一次取多股+按交易日对齐(缩多股链 2+N→3)`

---

### Task 4: score.py 连续距离判分

**Files:** Create `backend/eval/question_gen/score.py`;Test `backend/tests/eval/question_gen/test_score.py`

- [ ] **Step 1: 写失败测试** —— `scalar_distance(answer, gold, tol)` 返回最近数的距离(复用 judge 的 rel_mult/rel/abs 口径,`judge.py:31-48`):
```python
from eval.question_gen.score import scalar_distance, set_jaccard
def test_scalar_distance_picks_nearest():
    assert scalar_distance("涨幅 -10.2%", -10.0, {"kind":"rel_mult","value":0.005}) < scalar_distance("涨幅 5%", -10.0, {"kind":"rel_mult","value":0.005})
def test_set_jaccard():
    assert set_jaccard({"a","b"}, {"a","b"}) == 1.0
    assert set_jaccard({"a"}, {"a","b"}) == 0.5
```
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现** —— `score.py` 纯函数,**不动 judge.py**(pass@k 口径冻结):`scalar_distance`(抓数取最近、按 tol 口径算归一距离)、`ranking_partial`(top-k 命中数 / Kendall-tau)、`set_jaccard`(交并比)。复用 `judge.nums` 抓数。
- [ ] **Step 4: 跑** `pytest tests/eval/question_gen/test_score.py -q`。
- [ ] **Step 5: 提交** `feat(eval): score.py 连续距离判分(0/1 之外的稠密信号,不动 judge)`

---

### Task 5: runner 落完整轨迹 + 隔离 gold + 采集模式关降级

**Files:** Modify `backend/eval/question_gen/runner.py`;Test `backend/tests/eval/question_gen/test_runner_trajectory.py`

- [ ] **Step 1: 写失败测试**(mock LLM/hub,跑一道,断言)—— 采集模式下:① 产出 `trajectories_raw` 记录含 `messages`(完整多轮)且**不含 gold/passed**;② `judgements` 记录含 gold/passed;③ 采集模式构造的 deps `downgrade_char_threshold` 是大值(关降级)。
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现**:
  - `run_one` 返回值带上 `final`(ChatLoopState),不再只回答案;
  - 加 `collect: bool=False` 参数:`collect=True` 时 deps 传 `downgrade_char_threshold=10**9`(关降级,堵"坑一"轨迹被毁)+ 落两个文件:`trajectories_raw.jsonl`(每条 `{case_id, model, messages, n_steps, halt_reason}`,**无 gold**)与 `judgements.jsonl`(`{case_id, model, passed, gold, ...}`,gold 只在此);
  - 既有 `_dump_answers`(含 gold,`:209`)保持不变给离线重判用,但**采集产物物理分离**;非 collect 路径行为不变(回归)。
- [ ] **Step 4: 跑** runner 相关单测 + 既有 `test_runner_compare`/`test_runner_trajectory` 全绿;非 collect 路径逐字不变。
- [ ] **Step 5: 提交** `feat(eval): runner 采集模式落完整轨迹+隔离 gold+关降级(SFT/奖励底座)`

---

### Task 6: 全链路守护 + 缩链效果回归(deliverable)

**Files:** 无新增;跑套件 + live 回归。

- [ ] **Step 1: 跑** `pytest tests/unit/mcp_server tests/eval/question_gen tests/unit/chatloop -q` + e2e cassette,确认无回归。
- [ ] **Step 2: mypy + ruff** 改动文件全过。
- [ ] **Step 3: live 缩链效果** —— 用现成 141 题全量重跑 deepseek(基线 126/141),**重点看每题平均步数下降**(排序/筛选桶尤甚)+ qwen3-8b 重跑看筛选/排序桶因编排变短是否回升。对比 模型×桶 表落盘。
- [ ] **Step 4: 不单独提交**(报告落盘单独 commit)。

---

## Self-Review

**Spec 覆盖**:提案 1(Task 3)、提案 2(Task 1+2)、连续距离判分(Task 4)、轨迹落盘+gold 隔离+关降级(Task 5)、回归(Task 6)。落地步 1+2 全覆盖;步 3(trace_signals + SFT 导出)、步 4(compute_indicator)留第二批。

**红线对齐**:gold 不进 trajectories_raw(Task 5);未引入 compute_indicator(不碰 oracle 同源);改完跑全量回归(Task 6)。

**口径零漂移**:窗口解析(Task 1/2)与对齐(Task 3)均复用现有同源逻辑,gold 不变。

**类型一致**:resolve_window 返回 `tuple[str,str]` 全链一致;score.py 复用 judge 的 tol dict 形状。

---

## Execution Handoff

两种执行:**1. Subagent-Driven(推荐)** —— 每 task 派新 subagent + 两段式 review;**2. Inline**。选哪个?
