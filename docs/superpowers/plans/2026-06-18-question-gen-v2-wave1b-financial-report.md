# 反向出题机 v2 · 波1b — 财报取数 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 让反向出题机能产出「财报取数」意图的 case(某股 2024 年年报的 ROE / 资产负债率 / 销售毛利率 / 营业收入 / 净利润),oracle = 真 tushare fina_indicator / income 字段,scalar 可判分。

**Architecture:** 沿用波1a 的多意图模式(零 schema 改动:`intent="financial_report"`、`indicator` 填指标名、`window` 填报告期标签如 `"2024年报"`、`gold_shape="scalar"`)。新增 `intents.q_financial` 题面、`operators.financial_lookup` 字段派发(含单位换算)、`generator.build_financial_cases` 取数组装(按 end_date 过滤选行 + 空值跳过),接进 `generate()`。

**Tech Stack:** Python 3.12、pytest、pandas、`TushareService.get_fina_indicator` / `get_income`。

## 关键设计决定(真数据探测后定,见探测证据)

1. **报告期钉 2024 年年报(end_date=20241231)**,不钉"最新"/2025:实测 income 最新只到 `20250930`(2025 年报未披露),且 fina_indicator 与 income 跨表不一致;2024 年报所有表稳定可得、完整年口径、可复现。
2. **两表都返回多期历史(100+ 行),必须按 `end_date` 过滤选目标行**,不能 `iloc[0]`(实测 income `iloc[0]` 是 20250930 而非请求期)。
3. **单位:营收/净利存成「亿元」**(`值_元 / 1e8`)、题面问"多少亿元";ROE/资产负债率/毛利率是 %,直取。如此绕开 judge 不解析「亿/万」的问题,scalar 容差直接可判。
4. **空值跳过**(承波1a Task6):某股某期某字段为 None/NaN → 跳过该题。

## 文件结构

| 文件 | 改动 | 责任 |
|---|---|---|
| `backend/eval/question_gen/operators.py` | Modify | 加 `_FINANCIAL_SPEC` + `financial_lookup(metric, snap)`(直取/亿换算/空值→None) |
| `backend/eval/question_gen/intents.py` | Modify | 加 `INTENT_FINANCIAL` + `q_financial(name, metric, period_label)` |
| `backend/eval/question_gen/generator.py` | Modify | 加 `_FINANCIAL_*` 常量 + `_fetch_financial` + `build_financial_cases`,接进 `generate()` |
| `backend/tests/eval/question_gen/test_operators.py` | Modify | `financial_lookup` 单测(直取/亿换算/空值) |
| `backend/tests/eval/question_gen/test_intents.py` | Modify | `q_financial` 题面单测(比率问"是多少"、金额问"多少亿元") |
| `backend/tests/eval/question_gen/test_generator_financial.py` | Create | `build_financial_cases` 用 stub tushare(多期 DataFrame,验过滤选行 + 单位 + 跳空) |
| `backend/tests/eval/question_gen/test_judge.py` | Modify | 财报 scalar 判分回归(营收亿元 / ROE%) |

**测试命令(WSL fria-venv;git 用 git-bash):**
```
wsl bash -lc 'source ~/fria-venv/bin/activate && set -a && source /mnt/d/mys/Financial-Research-Investment-Assistant/.env 2>/dev/null && set +a && export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 && cd /mnt/d/mys/Financial-Research-Investment-Assistant/.claude/worktrees/question-gen-v2-snapshot/backend && python -m pytest <TEST_ARGS> -q' 2>/dev/null
```

---

## Task 1：`operators.financial_lookup` — 财报字段派发 + 单位换算

**Files:** Modify `backend/eval/question_gen/operators.py`、`backend/tests/eval/question_gen/test_operators.py`

- [ ] **Step 1: 写失败测试**(追加到 test_operators.py 末尾)

```python
def test_financial_lookup_ratio_direct():
    snap = {"roe": 34.46, "debt_to_assets": 16.4, "grossprofit_margin": 91.2,
            "revenue": 170_900_000_000.0, "n_income": 86_000_000_000.0}
    assert operators.financial_lookup("ROE", snap) == 34.46
    assert operators.financial_lookup("资产负债率", snap) == 16.4
    assert operators.financial_lookup("毛利率", snap) == 91.2


def test_financial_lookup_amount_to_yi():
    snap = {"revenue": 170_900_000_000.0, "n_income": 86_000_000_000.0}
    assert operators.financial_lookup("营收", snap) == 1709.0
    assert operators.financial_lookup("净利", snap) == 860.0


def test_financial_lookup_none_and_unknown():
    import pytest

    assert operators.financial_lookup("ROE", {"roe": None}) is None
    nan = float("nan")
    assert operators.financial_lookup("营收", {"revenue": nan}) is None
    with pytest.raises(ValueError):
        operators.financial_lookup("未知", {})
```

- [ ] **Step 2: 跑确认失败** — `<TEST_ARGS>` = `tests/eval/question_gen/test_operators.py -q`,预期 FAIL(no attribute 'financial_lookup')。

- [ ] **Step 3: 最小实现** — 在 `operators.py` 的 `_SNAPSHOT_COLUMNS` 之后加:

```python
# 财报取数指标 -> (字段, 单位)。ratio 直取(%);yi 元→亿(÷1e8)。
_FINANCIAL_SPEC: dict[str, tuple[str, str]] = {
    "ROE": ("roe", "ratio"),
    "资产负债率": ("debt_to_assets", "ratio"),
    "毛利率": ("grossprofit_margin", "ratio"),
    "营收": ("revenue", "yi"),
    "净利": ("n_income", "yi"),
}
```

在 `snapshot_lookup` 之后加:

```python
def financial_lookup(indicator: str, snap: dict) -> float | None:
    """财报取数:指标名 -> 字段值(营收/净利 元→亿)。

    字段缺失(None/NaN)→ 返回 None(调用方跳过)。未知指标 raise ValueError。
    """
    spec = _FINANCIAL_SPEC.get(indicator)
    if spec is None:
        raise ValueError(f"未知财报指标:{indicator!r}")
    col, unit = spec
    val = snap.get(col)
    if val is None or (isinstance(val, float) and val != val):  # None 或 NaN
        return None
    val = float(val)
    return val / 1e8 if unit == "yi" else val
```

把 `financial_lookup` 加进 `__all__`。

- [ ] **Step 4: 跑确认通过** — `<TEST_ARGS>` = `tests/eval/question_gen/test_operators.py -q`,全 PASS。

- [ ] **Step 5: 提交** — `git add operators.py test_operators.py && git commit -m "feat(question_gen): 加 financial_lookup 财报字段派发+单位换算"`,正文末尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。LF 行尾自查。

---

## Task 2：`intents.q_financial` — 财报取数题面

**Files:** Modify `backend/eval/question_gen/intents.py`、`backend/tests/eval/question_gen/test_intents.py`

- [ ] **Step 1: 写失败测试**(追加到 test_intents.py 末尾)

```python
def test_q_financial_ratio_and_amount():
    q_roe = intents.q_financial("贵州茅台", "ROE", "2024年年报")
    assert "贵州茅台" in q_roe and "2024年年报" in q_roe and "ROE" in q_roe
    q_rev = intents.q_financial("贵州茅台", "营收", "2024年年报")
    assert "营业收入" in q_rev and "亿元" in q_rev


def test_q_financial_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        intents.q_financial("贵州茅台", "未知", "2024年年报")
```

- [ ] **Step 2: 跑确认失败** — `<TEST_ARGS>` = `tests/eval/question_gen/test_intents.py -q`。

- [ ] **Step 3: 最小实现** — 在 `intents.py` 的 `_SNAPSHOT_LABELS` 之后加:

```python
INTENT_FINANCIAL = "financial_report"

_FINANCIAL_RATIO_LABELS = {"ROE": "ROE", "资产负债率": "资产负债率", "毛利率": "销售毛利率"}
_FINANCIAL_AMOUNT_LABELS = {"营收": "营业收入", "净利": "净利润"}
```

在 `q_snapshot` 之后加:

```python
def q_financial(name: str, indicator: str, period_label: str) -> str:
    """财报取数题面。比率类问"是多少?"(%);金额类问"是多少亿元?"。未知指标 raise ValueError。"""
    if indicator in _FINANCIAL_RATIO_LABELS:
        return f"{name}{period_label}的{_FINANCIAL_RATIO_LABELS[indicator]}是多少?"
    if indicator in _FINANCIAL_AMOUNT_LABELS:
        return f"{name}{period_label}的{_FINANCIAL_AMOUNT_LABELS[indicator]}是多少亿元?"
    raise ValueError(f"未知财报指标:{indicator!r}")
```

把 `INTENT_FINANCIAL` 和 `q_financial` 加进 `__all__`。

- [ ] **Step 4: 跑确认通过** — `<TEST_ARGS>` = `tests/eval/question_gen/test_intents.py -q`。

- [ ] **Step 5: 提交** — message `feat(question_gen): 加 q_financial 财报取数题面 + INTENT_FINANCIAL` + co-author 行。

---

## Task 3：`generator.build_financial_cases` — 取数(过滤选期)+ 组装

**Files:** Modify `backend/eval/question_gen/generator.py`;Create `backend/tests/eval/question_gen/test_generator_financial.py`

- [ ] **Step 1: 写失败测试**(新建 test_generator_financial.py)

```python
"""build_financial_cases 离线单测:stub 返回多期 DataFrame,验过滤选期 + 单位 + 跳空。"""

import asyncio

import pandas as pd

from eval.question_gen import generator, intents, stock_pool


class _StubTushare:
    """fina_indicator / income 都返回多期历史(含 20241231),验生成器按 end_date 选行。"""

    async def get_fina_indicator(self, *, ts_code, end_date=None):
        return pd.DataFrame([
            {"end_date": "20250930", "roe": 99.9, "debt_to_assets": 99.9, "grossprofit_margin": 99.9},
            {"end_date": "20241231", "roe": 34.46, "debt_to_assets": 16.4, "grossprofit_margin": 91.2},
        ])

    async def get_income(self, *, ts_code, end_date=None):
        return pd.DataFrame([
            {"end_date": "20250930", "revenue": 1.0, "n_income": 1.0},
            {"end_date": "20241231", "revenue": 170_900_000_000.0, "n_income": 86_000_000_000.0},
        ])


def _run():
    return asyncio.run(
        generator.build_financial_cases(_StubTushare(), "20241231", "2024年年报", lambda tag: f"qg-{tag}")
    )


def test_build_financial_cases_count_shape_period():
    cases = _run()
    assert len(cases) == len(stock_pool.POOL) * 5  # 5 指标
    for c in cases:
        assert c.intent == intents.INTENT_FINANCIAL
        assert c.gold_shape == "scalar"
        assert c.window == "2024年年报"
        assert c.meta["period_end"] == "20241231"


def test_build_financial_cases_selects_right_period_and_unit():
    cases = _run()
    roe = next(c for c in cases if c.indicator == "ROE")
    assert roe.gold == 34.46  # 选 20241231 行,不是 20250930 的 99.9
    rev = next(c for c in cases if c.indicator == "营收")
    assert rev.gold == 1709.0  # 元→亿
    assert "亿元" in rev.question
```

- [ ] **Step 2: 跑确认失败** — `<TEST_ARGS>` = `tests/eval/question_gen/test_generator_financial.py -q`(no attribute 'build_financial_cases')。

- [ ] **Step 3: 最小实现** — 在 `generator.py` 的 `_SNAPSHOT_COLS` 之后加:

```python
_FINANCIAL_INDICATORS = ("ROE", "资产负债率", "毛利率", "营收", "净利")
_FINANCIAL_TOL = {ind: {"kind": "rel", "value": 0.01} for ind in _FINANCIAL_INDICATORS}
_FINA_COLS = ("roe", "debt_to_assets", "grossprofit_margin")
_INCOME_COLS = ("revenue", "n_income")
```

在 `build_snapshot_cases` 之后加:

```python
def _select_period_row(df, end_date: str):
    """从多期历史 DataFrame 里选 end_date 匹配的那一行;无则 None。"""
    if len(df) == 0 or "end_date" not in df.columns:
        return None
    rows = df[df["end_date"].astype(str) == end_date]
    return None if len(rows) == 0 else rows.iloc[0]


async def _fetch_financial(tushare, ts_code: str, end_date: str) -> dict:
    """取 fina_indicator + income,按 end_date 选行 → 合并 snap dict(值可能 None/NaN)。"""
    fi = await tushare.get_fina_indicator(ts_code=ts_code, end_date=end_date)
    inc = await tushare.get_income(ts_code=ts_code, end_date=end_date)
    snap: dict = {}
    frow = _select_period_row(fi, end_date)
    if frow is not None:
        for c in _FINA_COLS:
            snap[c] = frow[c] if c in fi.columns else None
    irow = _select_period_row(inc, end_date)
    if irow is not None:
        for c in _INCOME_COLS:
            snap[c] = irow[c] if c in inc.columns else None
    return snap


async def build_financial_cases(tushare, period_end: str, period_label: str, cid) -> list[case.ComputationCase]:
    """财报取数(简单档):每股取 period_end 期的 fina_indicator/income → 5 个直取指标。

    tushare 依赖注入;空值指标跳过(承波1a)。营收/净利 gold 已是亿元。
    """
    out: list[case.ComputationCase] = []
    for st in stock_pool.POOL:
        snap = await _fetch_financial(tushare, st.ts_code, period_end)
        for ind in _FINANCIAL_INDICATORS:
            gold = operators.financial_lookup(ind, snap)
            if gold is None:
                continue
            out.append(
                case.ComputationCase(
                    case_id=cid(f"财报{ind}-{st.ts_code}"),
                    intent=intents.INTENT_FINANCIAL,
                    difficulty="简单",
                    question=intents.q_financial(st.name, ind, period_label),
                    stocks=[st.ts_code],
                    indicator=ind,
                    window=period_label,
                    gold=gold,
                    gold_shape="scalar",
                    tolerance=_FINANCIAL_TOL[ind],
                    meta={"period_end": period_end, "period_label": period_label},
                )
            )
    return out
```

- [ ] **Step 4: 跑确认通过** — `<TEST_ARGS>` = `tests/eval/question_gen/test_generator_financial.py -q`(2 个 PASS)。

- [ ] **Step 5: 接进 `generate()`** — 在 `generate()` 里、波1a 的 `cases.extend(await build_snapshot_cases(...))` 那行之后,加:

```python
    # ---- 财报取数(简单档,2024 年年报)----
    cases.extend(await build_financial_cases(tushare, "20241231", "2024年年报", cid))
```

- [ ] **Step 6: 跑全目录无回归** — `<TEST_ARGS>` = `tests/eval/question_gen/ -q`。`generate()` 本身依赖真 tushare,不在单测覆盖,确认 import 不报错 + 新测试过 + 无回归即可。

- [ ] **Step 7: 提交** — message `feat(question_gen): 加 build_financial_cases 财报取数(2024年报)+ 接进 generate` + co-author 行。新建文件查 CRLF。

---

## Task 4：judge 财报 scalar 判分回归(无实现改动)

**Files:** Modify `backend/tests/eval/question_gen/test_judge.py`

- [ ] **Step 1: 写测试**(追加)

```python
def test_judge_financial_revenue_yi():
    # 营收 gold=1709(亿),答案 "约1709亿元" 命中(rel 1%)
    tol = {"kind": "rel", "value": 0.01}
    assert judge.judge(1709.0, "scalar", tol, "2024 年营业收入约 1709 亿元", ["贵州茅台"]) is True
    assert judge.judge(1709.0, "scalar", tol, "约 1500 亿元", ["贵州茅台"]) is False


def test_judge_financial_roe_percent():
    tol = {"kind": "rel", "value": 0.01}
    assert judge.judge(34.46, "scalar", tol, "ROE 约 34.46%", ["贵州茅台"]) is True
```

- [ ] **Step 2: 跑确认通过**(预期无需改 judge) — `<TEST_ARGS>` = `tests/eval/question_gen/test_judge.py -q`。若 FAIL 才最小改 judge.py 并说明。

- [ ] **Step 3: 提交** — message `test(question_gen): 财报 scalar 判分回归` + co-author 行。

---

## Task 5：真 gold 离线冒烟(手动,不进 CI)

**Files:** 无代码改动(运行 + 人工核)

- [ ] **Step 1: 真 tushare 跑 build_financial_cases**(WSL fria-venv + `TUSHARE_MODE=real`),对 600519.SH 等核 2024 年报 ROE/营收/净利,确认按 end_date 选对期、单位是亿、空值跳过工作。
- [ ] **Step 2: 跨池抽查若干股 20241231 是否齐**(fina_indicator + income 都有该期),记录哪些股某指标因空值/缺期被跳。
- [ ] **Step 3:(可选)记一笔财报取数子集的覆盖数**,供后续多模型 bake-off 引用。

---

## Self-Review

**Spec 覆盖:** 实现 spec 波1 的「财报取数」(③类):✅ 题面(T2)、✅ 字段派发+单位(T1)、✅ 取数按期过滤+组装(T3)、✅ 判分复用(T4)、✅ 真值冒烟(T5)。营收同比/净利同比(需两期)、毛利率以外的派生留后续。

**Placeholder 扫描:** 无 TBD;每步完整代码 + 确切命令。

**类型一致性:** `financial_lookup(indicator, snap)→float|None`、`q_financial(name, indicator, period_label)`、`build_financial_cases(tushare, period_end, period_label, cid)`、`_fetch_financial`、`_select_period_row` 跨任务签名一致;`_FINANCIAL_SPEC`(operators,字段+单位)与 `_FINA_COLS`/`_INCOME_COLS`(generator,取数列)职责分离不冲突;沿用 `intent`/`window` 字段不触 schema。

**已知限制:** 钉 2024 年报(非最新);某股若 20241231 缺期或字段空 → 该题跳过(承波1a 空值策略);营收/净利要求 agent 把元换算成亿元回答(题面已明示"亿元")。
