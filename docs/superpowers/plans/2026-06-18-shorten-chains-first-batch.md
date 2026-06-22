# 缩工具链(get_daily 内联窗口)+ SFT 轨迹采集 第一批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** get_daily 内联 `anchor+lookback`,把"先 trade_cal 定窗→再 get_daily 取数"的两步并一步、消灭"漏 anchor 就放弃"整类失败;runner 加采集模式,落完整解题轨迹、隔离 gold、关降级,为 SFT 热启动备干净种子。

**Architecture:** 承 `docs/superpowers/specs/2026-06-18-shorten-chains-and-rl-substrate-design.md` 落地步 1+2 的**已确认部分**。讨论后两处收窄:**get_daily_batch(批量取数)砍掉**(原子性 + 避免用工具绕过模型的编排弱点);**连续距离判分(原 score.py)推到 RL 阶段**(它是 reward shaping,属 RL,不是 SFT 料)。全部改动在工具/eval 侧,**零侵入 loop/state/tool_hub**。窗口解析复用 trade_cal 同源逻辑,gold 不变。

**Tech Stack:** Python / MCP tools / asyncio / pytest;后端运行环境 = WSL fria-venv(`source /home/administrator/fria-venv/bin/activate && cd backend`,测试/服务需 `source .env`)。

---

## File Structure

| 文件 | 改动 |
| --- | --- |
| `backend/app/mcp_server/tools/trade_cal.py` | 把 window 解析(`:114-151`)抽成可复用纯函数 `resolve_window(anchor, lookback) -> (start,end)` |
| `backend/app/mcp_server/tools/get_daily.py` | 加可选 `anchor+lookback`(给了则 resolve_window 再取数);其余不动 |
| `backend/app/chatloop/tool_docs.py` | get_daily 文档补一句"可传 anchor+lookback 让工具自己定窗口,免先调 trade_cal" |
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

### Task 2: get_daily 加 anchor+lookback

**Files:** Modify `backend/app/mcp_server/tools/get_daily.py`、`backend/app/chatloop/tool_docs.py`;Test `backend/tests/unit/mcp_server/test_get_daily_tool.py`

- [ ] **Step 1: 写失败测试**(纯函数层,不打网络)—— 断言"给 anchor+lookback 时,handle 解析出的 (start,end) 等于 resolve_window 的结果"(抽一个 `_resolve_range(args)->(start,end)` 纯函数单测,或对 handle 的参数解析做薄单测):
```python
def test_get_daily_anchor_lookback_resolves_window():
    s, e = _resolve_range({"anchor": "20260616", "lookback": "1y"})
    assert (s, e) == ("20250616", "20260616")
def test_get_daily_explicit_start_end_unchanged():
    s, e = _resolve_range({"start": "20250101", "end": "20251231"})
    assert (s, e) == ("20250101", "20251231")
```
- [ ] **Step 2: 跑测试确认失败。**
- [ ] **Step 3: 实现** —— get_daily inputSchema 加可选 `anchor`/`lookback`;handle 里:`if 给了 anchor+lookback: start,end = trade_cal.resolve_window(anchor,lookback)` 否则用 `start/end`(都没给 → 报错指导文案)。其余取数/格式化不变。tool_docs 的 get_daily 文档补一句"也可传 anchor+lookback 让工具自己定窗口,免先调 trade_cal"。
- [ ] **Step 4: 跑** get_daily 单测 + 既有回归全绿。
- [ ] **Step 5: 提交** `feat(get_daily): 内联 anchor+lookback 窗口(免先调 trade_cal)`

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

**类型一致**:`resolve_window` 返回 `tuple[str,str]`,get_daily 的 `_resolve_range` 复用同签名。

---

## Execution Handoff

两种执行:**1. Subagent-Driven(推荐)** —— 每 task 派新 subagent + 两段式 review(spec 合规 → 代码质量);**2. Inline**。
