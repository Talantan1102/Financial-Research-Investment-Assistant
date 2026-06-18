# 反向出题机 v2 · 波1a — 行情快照取数 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让反向出题机能产出「行情快照取数」意图的 case（贵州茅台在某交易日的 PE/PB/换手率/股息率是多少），oracle = 真 tushare `daily_basic` 字段，端到端可被现有 scalar 判分器判分。

**Architecture:** 不改 `ComputationCase` schema——复用现有 `intent` 字段填新意图值 `snapshot_quote`、`indicator` 填 PE/PB/换手率/股息率、`window` 填 `"snapshot"` 标记、`gold_shape="scalar"`。新增三处纯逻辑：`intents.q_snapshot` 题面、`operators.snapshot_lookup` 字段派发、`generator.build_snapshot_cases` 取数+组装（依赖注入 tushare，可单测）。真 gold 走 `TUSHARE_MODE=real` 离线生成；单测用固定 stub。

**Tech Stack:** Python 3.12、`@dataclass(frozen=True)`、pytest、pandas（仅 generator stub 测用）、`TushareService` Protocol（`get_daily_basic`）。

**承上下文：**
- 设计 spec：`docs/superpowers/specs/2026-06-18-question-gen-v2-eval-expansion-design.md`（波1 取数类）
- 铁律（`docs/research/2026-06-16-deterministic-indicator-catalog.md`）：**mock-tushare 非确定、不能当 oracle；真 gold 一律真 tushare 冻结**。故本计划的「真 gold 生成」走 `TUSHARE_MODE=real`，单测只用固定 stub 验生成逻辑、不当 oracle。
- 现有同构参照：`generator.py` 的简单档循环（行 92-150）、`intents.q_single`、`operators.single`。

---

## 文件结构

| 文件 | 改动 | 责任 |
|---|---|---|
| `backend/eval/question_gen/intents.py` | Modify | 加 `INTENT_SNAPSHOT` 常量 + `q_snapshot()` 题面 |
| `backend/eval/question_gen/operators.py` | Modify | 加 `_SNAPSHOT_COLUMNS` + `snapshot_lookup()` 字段派发 |
| `backend/eval/question_gen/generator.py` | Modify | 加 `_SNAPSHOT_INDICATORS`/`_SNAPSHOT_TOL` + `_fetch_snapshot()` + `build_snapshot_cases()`，并接进 `generate()` |
| `backend/tests/eval/question_gen/test_intents.py` | Modify | `q_snapshot` 题面单测 |
| `backend/tests/eval/question_gen/test_operators.py` | Modify | `snapshot_lookup` 派发单测 |
| `backend/tests/eval/question_gen/test_generator_snapshot.py` | Create | `build_snapshot_cases` 用 stub tushare 的离线单测 |
| `backend/tests/eval/question_gen/test_judge.py` | Modify | 快照 scalar case 判分回归（无实现改动） |

**不在本计划：** 财报取数（下一份计划）、股票池扩充（波4）、runner/对比表改动（snapshot 是 scalar，现有 runner 与 judge 直接吃，无需改）。

**测试环境（承 memory `backend-runtime-env-wsl-fria-venv`）：** WSL fria-venv，从 `backend/` 目录跑，命令形如 `cd backend && python -m pytest tests/eval/question_gen/<file>.py -v`（CWD=backend 让 `eval.*` / `app.*` 可导入）。纯函数测不触 PG。

---

## Task 1：`operators.snapshot_lookup` — 快照指标→字段派发

**Files:**
- Modify: `backend/eval/question_gen/operators.py`
- Test: `backend/tests/eval/question_gen/test_operators.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/eval/question_gen/test_operators.py` 末尾追加：

```python
def test_snapshot_lookup_maps_each_indicator():
    snap = {"pe": 25.3, "pb": 8.1, "turnover_rate": 1.5, "dv_ratio": 2.0}
    assert operators.snapshot_lookup("PE", snap) == 25.3
    assert operators.snapshot_lookup("PB", snap) == 8.1
    assert operators.snapshot_lookup("换手率", snap) == 1.5
    assert operators.snapshot_lookup("股息率", snap) == 2.0


def test_snapshot_lookup_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        operators.snapshot_lookup("未知指标", {"pe": 1.0})
```

（文件顶部已 `from eval.question_gen import operators`；若无则确认 import。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/eval/question_gen/test_operators.py::test_snapshot_lookup_maps_each_indicator -v`
Expected: FAIL，`AttributeError: module 'eval.question_gen.operators' has no attribute 'snapshot_lookup'`

- [ ] **Step 3: 写最小实现**

在 `backend/eval/question_gen/operators.py` 的 `_CAGR_NAMES` 定义之后（约行 19 后）加常量，并在 `filter_by` 之后、`__all__` 之前加函数：

```python
# 行情快照指标 -> daily_basic 列名(直取,非计算)。换手率/股息率 tushare 已是百分数,不再 scale。
_SNAPSHOT_COLUMNS: dict[str, str] = {
    "PE": "pe",
    "PB": "pb",
    "换手率": "turnover_rate",
    "股息率": "dv_ratio",
}
```

```python
def snapshot_lookup(indicator: str, snap: dict) -> float:
    """行情快照取数:指标名 -> 直取 daily_basic 字段值。未知指标 raise ValueError。

    snap 形状: {"pe": float, "pb": float, "turnover_rate": float, "dv_ratio": float}。
    """
    col = _SNAPSHOT_COLUMNS.get(indicator)
    if col is None:
        raise ValueError(f"未知快照指标:{indicator!r}")
    return float(snap[col])
```

并把 `snapshot_lookup` 加进 `__all__`：

```python
__all__ = ["single", "correlation_pair", "rank_by", "filter_by", "snapshot_lookup"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/eval/question_gen/test_operators.py -v`
Expected: PASS（新增 2 个 + 原有全绿）

- [ ] **Step 5: 提交**

```bash
git add backend/eval/question_gen/operators.py backend/tests/eval/question_gen/test_operators.py
git commit -m "feat(question_gen): 加 snapshot_lookup 行情快照字段派发"
```

---

## Task 2：`intents.q_snapshot` — 快照取数题面

**Files:**
- Modify: `backend/eval/question_gen/intents.py`
- Test: `backend/tests/eval/question_gen/test_intents.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/eval/question_gen/test_intents.py` 末尾追加：

```python
def test_q_snapshot_renders_date_and_label():
    q = intents.q_snapshot("贵州茅台", "PE", "20260612")
    assert "贵州茅台" in q
    assert "2026年06月12日" in q
    assert "市盈率" in q


def test_q_snapshot_unknown_indicator_raises():
    import pytest

    with pytest.raises(ValueError):
        intents.q_snapshot("贵州茅台", "未知", "20260612")
```

（文件顶部已 `from eval.question_gen import intents`；若无则确认 import。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/eval/question_gen/test_intents.py::test_q_snapshot_renders_date_and_label -v`
Expected: FAIL，`AttributeError: ... has no attribute 'q_snapshot'`

- [ ] **Step 3: 写最小实现**

在 `backend/eval/question_gen/intents.py` 的 `INTENT = "stock_study"` 之后加常量，并在 `q_filter` 之后、`__all__` 之前加函数：

```python
INTENT_SNAPSHOT = "snapshot_quote"

_SNAPSHOT_LABELS = {
    "PE": "市盈率(PE)",
    "PB": "市净率(PB)",
    "换手率": "换手率",
    "股息率": "股息率",
}
```

```python
def q_snapshot(name: str, indicator: str, trade_date: str) -> str:
    """行情快照取数题面;trade_date 形如 "20260612" → "2026年06月12日"。未知指标 raise ValueError。"""
    label = _SNAPSHOT_LABELS.get(indicator)
    if label is None:
        raise ValueError(f"未知快照指标:{indicator!r}")
    d = f"{trade_date[:4]}年{trade_date[4:6]}月{trade_date[6:]}日"
    return f"{name}在{d}的{label}是多少?"
```

并更新 `__all__`：

```python
__all__ = [
    "INTENT",
    "INTENT_SNAPSHOT",
    "q_single",
    "q_dual",
    "q_corr",
    "q_rank",
    "q_filter",
    "q_snapshot",
]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/eval/question_gen/test_intents.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/eval/question_gen/intents.py backend/tests/eval/question_gen/test_intents.py
git commit -m "feat(question_gen): 加 q_snapshot 行情快照题面 + INTENT_SNAPSHOT"
```

---

## Task 3：`generator.build_snapshot_cases` — 取数 + 组装 case

**Files:**
- Modify: `backend/eval/question_gen/generator.py`
- Test: `backend/tests/eval/question_gen/test_generator_snapshot.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/eval/question_gen/test_generator_snapshot.py`：

```python
"""build_snapshot_cases 离线单测:用固定 stub tushare(非 oracle,只验生成逻辑)。"""

import asyncio

import pandas as pd

from eval.question_gen import generator, intents


class _StubTushare:
    """固定返回一行 daily_basic 的 stub —— 确定性,仅供测生成逻辑,非真值 oracle。"""

    async def get_daily_basic(self, *, ts_code, trade_date=None):
        return pd.DataFrame(
            [{"pe": 25.0, "pb": 8.0, "turnover_rate": 1.5, "dv_ratio": 2.0}]
        )


def _run():
    return asyncio.run(
        generator.build_snapshot_cases(_StubTushare(), "20260612", lambda tag: f"qg-{tag}")
    )


def test_build_snapshot_cases_count_and_shape():
    cases = _run()
    # 15 股 × 4 指标
    assert len(cases) == 60
    for c in cases:
        assert c.intent == intents.INTENT_SNAPSHOT
        assert c.difficulty == "简单"
        assert c.gold_shape == "scalar"
        assert c.window == "snapshot"
        assert c.meta["trade_date"] == "20260612"


def test_build_snapshot_cases_pe_gold_and_question():
    cases = _run()
    pe = next(c for c in cases if c.indicator == "PE")
    assert pe.gold == 25.0
    assert "市盈率" in pe.question
    assert len(pe.stocks) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/eval/question_gen/test_generator_snapshot.py -v`
Expected: FAIL，`AttributeError: module 'eval.question_gen.generator' has no attribute 'build_snapshot_cases'`

- [ ] **Step 3: 写最小实现**

在 `backend/eval/question_gen/generator.py` 的 `_PCT_INDICATORS` 定义之后（约行 33 后）加常量：

```python
_SNAPSHOT_INDICATORS = ("PE", "PB", "换手率", "股息率")
_SNAPSHOT_TOL = {
    "PE": {"kind": "rel", "value": 0.01},
    "PB": {"kind": "rel", "value": 0.01},
    "换手率": {"kind": "rel", "value": 0.02},
    "股息率": {"kind": "rel", "value": 0.02},
}
_SNAPSHOT_COLS = ("pe", "pb", "turnover_rate", "dv_ratio")
```

在 `_scale` 函数之后（约行 60 后）加两个函数：

```python
async def _fetch_snapshot(tushare, ts_code: str, trade_date: str) -> dict:
    """取真 tushare daily_basic 的某交易日一行 → {pe, pb, turnover_rate, dv_ratio}。"""
    df = await tushare.get_daily_basic(ts_code=ts_code, trade_date=trade_date)
    if len(df) == 0:
        raise RuntimeError(f"daily_basic 无数据:{ts_code} @ {trade_date}")
    row = df.iloc[0]
    return {col: float(row[col]) for col in _SNAPSHOT_COLS}


async def build_snapshot_cases(tushare, as_of: str, cid) -> list[case.ComputationCase]:
    """行情快照取数(简单档,无窗口):每只股取 as_of 当日 daily_basic → 4 个直取指标。

    tushare 依赖注入(可塞 stub 单测);cid 是 case_id 生成器 callable。
    gold = 直取字段值(换手率/股息率 tushare 已是百分数,不 scale)。
    """
    out: list[case.ComputationCase] = []
    for st in stock_pool.POOL:
        snap = await _fetch_snapshot(tushare, st.ts_code, as_of)
        for ind in _SNAPSHOT_INDICATORS:
            gold = operators.snapshot_lookup(ind, snap)
            out.append(
                case.ComputationCase(
                    case_id=cid(f"快照{ind}-{st.ts_code}"),
                    intent=intents.INTENT_SNAPSHOT,
                    difficulty="简单",
                    question=intents.q_snapshot(st.name, ind, as_of),
                    stocks=[st.ts_code],
                    indicator=ind,
                    window="snapshot",
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_SNAPSHOT_TOL[ind],
                    meta={"trade_date": as_of, "as_of": as_of},
                )
            )
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/eval/question_gen/test_generator_snapshot.py -v`
Expected: PASS（2 个测试）

- [ ] **Step 5: 接进 `generate()`**

在 `generate()` 里、简单档 `for st in stock_pool.POOL:` 大循环结束之后（现行 150 之后、`# ---- 中等档 ----` 行 152 之前）插入一行：

```python
    # ---- 行情快照取数(简单档,无窗口)----
    cases.extend(await build_snapshot_cases(tushare, as_of, cid))
```

（`tushare`/`as_of`/`cid` 均在 `generate()` 作用域内已定义,行 68/64/83。）

- [ ] **Step 6: 跑全套 question_gen 单测确认无回归**

Run: `cd backend && python -m pytest tests/eval/question_gen/ -v`
Expected: PASS（含新增；`generate()` 本身因依赖 trade_cal + 真 tushare 不在单测覆盖，由 Task 5 live 验）

- [ ] **Step 7: 提交**

```bash
git add backend/eval/question_gen/generator.py backend/tests/eval/question_gen/test_generator_snapshot.py
git commit -m "feat(question_gen): 加 build_snapshot_cases 行情快照取数 + 接进 generate"
```

---

## Task 4：judge 快照 scalar 判分回归（无实现改动）

**Files:**
- Test: `backend/tests/eval/question_gen/test_judge.py`

- [ ] **Step 1: 写测试（验证现有 scalar judge 直接吃快照）**

在 `backend/tests/eval/question_gen/test_judge.py` 末尾追加：

```python
def test_judge_snapshot_pe_scalar():
    # 快照 PE：gold=25.3，答案含 "25.3" 命中（rel 1%）
    tol = {"kind": "rel", "value": 0.01}
    assert judge.judge(25.3, "scalar", tol, "茅台当日市盈率约为 25.3 倍", ["贵州茅台"]) is True
    assert judge.judge(25.3, "scalar", tol, "市盈率约 30 倍", ["贵州茅台"]) is False


def test_judge_snapshot_dv_ratio_percent():
    # 股息率：gold=2.0(%)，答案 "2.0%" 命中
    tol = {"kind": "rel", "value": 0.02}
    assert judge.judge(2.0, "scalar", tol, "股息率约 2.0%", ["贵州茅台"]) is True
```

（文件顶部已 `from eval.question_gen import judge`；若无则确认 import。）

- [ ] **Step 2: 跑测试确认通过（无需改实现）**

Run: `cd backend && python -m pytest tests/eval/question_gen/test_judge.py -v`
Expected: PASS（现有 scalar 容差逻辑直接支持；若 FAIL 则说明 `hit_scalar` 对快照值有口径问题，需在本 task 内补——预期不会）

- [ ] **Step 3: 提交**

```bash
git add backend/tests/eval/question_gen/test_judge.py
git commit -m "test(question_gen): 快照 scalar 判分回归"
```

---

## Task 5：真 gold 离线生成 + 小 live 冒烟（手动，不进 CI）

> 承 MVP 约定与铁律：真 gold 必须真 tushare 冻结。本 task 手动跑，验证端到端，不进 CI。

**Files:** 无代码改动（运行 + 人工核对）

- [ ] **Step 1: 真 tushare 离线生成题集**

承 memory `tushare-real-data-via-proxy`：设 `TUSHARE_MODE=real` + token/BASE_URL（`tu.brze.top/dataapi`），从 `backend/` 跑：

```bash
cd backend && TUSHARE_MODE=real python -m eval.question_gen.generator
```

Expected: stdout 的 `_summary` 里指标计数多出 `PE/PB/换手率/股息率` 各 15（共 +60 道）；`data/computation_cases.jsonl` 含 `intent: "snapshot_quote"` 行。

- [ ] **Step 2: 人工核 2-3 条 gold**

挑 1-2 只股（如 600519.SH 贵州茅台），到 tushare 或行情软件查 2026-06-12 的 PE/PB，比对生成的 jsonl 里对应 `gold`，确认数值与单位一致（PE/PB 为倍数原值，换手率/股息率为百分数）。

- [ ] **Step 3: 小 live 冒烟跑 agent（可选，需真栈）**

若要端到端验 agent 能答快照取数：用 `eval.question_gen.runner` 跑生成出的快照子集 k 次，看 pass@k 与 `判分=True` 数量，人工核 1-2 道判分对（命令形态参照 `runner.py` 的 `_main`；live 不进 CI）。

- [ ] **Step 4: 记一笔基线（可选）**

把快照子集的 pass@k 按 `indicator` 记进一份 dogfood note，作为后续多模型 bake-off（model-switching spec）量基线时的快照意图覆盖证据。

---

## Self-Review

**1. Spec 覆盖：** 本计划实现 spec 波1 的「行情快照取数」家族（②类）：✅ 题面（Task 2）、✅ oracle 直取字段（Task 1）、✅ 生成（Task 3）、✅ 判分复用（Task 4）、✅ 真值 cassette 走 real 模式（Task 5）。财报取数（③类）显式留作下一份计划——属波1 但独立可测，符合分拆约定。难度/量级/拆分（spec 第四节）属波4，不在本计划。

**2. Placeholder 扫描：** 无 TBD/TODO；每个代码 step 给了完整代码与确切命令/预期。

**3. 类型一致性：** `snapshot_lookup(indicator, snap)`、`q_snapshot(name, indicator, trade_date)`、`build_snapshot_cases(tushare, as_of, cid)`、`_fetch_snapshot(tushare, ts_code, trade_date)` 在 Task 1/2/3 定义并在 Task 3/测试中调用，签名一致；`_SNAPSHOT_COLUMNS`（operators，列映射）与 `_SNAPSHOT_COLS`（generator，取数列元组）名字不同、职责不同，无冲突；`intent="snapshot_quote"` 走现有 `intent` 字段，`window="snapshot"` 走现有 `window` 字段，均不触 `ComputationCase` schema 改动（`case.py` `_REQUIRED_KEYS` 不含新键，向后兼容现有 141 题文件）。

**4. 已知限制：** `_fetch_snapshot` 对空 DataFrame fail-loud（as_of 须为已落定交易日，已钉 20260612）；PE 取 `pe`（静态）非 `pe_ttm`，题面以「市盈率(PE)」标明口径，避免歧义。
