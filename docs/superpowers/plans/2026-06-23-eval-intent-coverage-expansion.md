# 评估集业务意图扩充 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给可验证评估集补齐缺失的业务意图（核对一个数 / 盯异动信号 / 现在算便宜还是贵 / 账户真实收益 / 赚钱来源拆解 / EV估值），并修复切分抽样，让 held-out 测试集真正能衡量「难题 + 全意图」的能力——而不是像现在这样 94% 是简单查数。

**Architecture:** 沿用 #178 已落地的数据管线（中证800 → 清洗 → 按股不相交切 train/val/test → 抽样 → generate）。本计划只动两处：①在 `generator.py` 里新增几个意图家族的 `build_*` 函数（每个复用一个**现成的独立 oracle**，不自造算法）；②修 `build_datasets.py` 的抽样与 `runner.py` 的判分，让新意图和难题真正落进测试集、且难题判分防"假算"。

**Tech Stack:** Python / pytest / 真 tushare（cassette 冻结）/ 现成 oracle：`indicator_oracle.pe_percentile`、`portfolio_analytics.compute_twr`、`portfolio_analytics.compute_daily_attribution`、`dd_report.metrics.numerical_metric`。

---

## 实施状态（2026-06-23，subagent 逐任务执行）

| 计划任务 | 状态 | 说明 |
|---|---|---|
| Task 1 财报核对 `financial_verify` | ✅ 已落地 | gold=真营收/净利(亿)，±1% |
| Task 2 异动信号 `trend_signal` | ✅ 已落地 | 营收/净利同比（tushare 预算字段）；股东户数/环比 留 follow-up |
| Task 6 `requires_run_python` 字段 | ✅ 已落地 | round-trip + 老数据缺键容错 |
| Task 3 PE历史分位 `valuation_percentile`（难档） | ✅ 已落地 | 复用 `pe_percentile`；**附带**给 `get_daily_basic` 增量加可选 `start_date/end_date`（Protocol+Real+mock+stub，向后兼容） |
| Task 4 TWR + 三层归因（难档） | ✅ 已落地 | 归因篮子改**跨板块**使行业超额非平凡 |
| Task 7 判分第二门 | ✅ 已落地 | `trace_has_run_python` + `judge_with_gate` 接入 runner；纯函数单测覆盖 |
| Task 8 抽样按行业保量 | ✅ 已落地 | `_sample_balanced` 让估值/组合题回到 val/test |
| **Task 5 EV/EBITDA 理论价** | ⛔ **DEFERRED** | tushare 集成无 `ebitda` 字段，生产估值路径自身 `ebitda=0.0` 跳过。生成可验证题需现编 EBITDA 口径（EBIT+折旧摊销，需新接字段）+ 冻口径 + 同行聚合，违反「gold 来自真 tushare、不编造」铁律。**需先单独定 EBITDA 口径 spec** 再做。 |

落地 5 个新业务意图（核对/同比/分位/TWR/归因）+ 判分第二门 + 抽样保量。难度配额再平衡、量级扩到训练级、live 重生成三套数据集（验收 §5 的 live 项）属下游 RL 步骤，本波不含。

---

## 一、现状（已核验 2026-06-23，基于 origin/main = #178 + #179）

### 已经做完的（#178 交付，不用再做）

| 维度 | 状态 |
|---|---|
| 股票池 | 15 只手挑 → **中证800**（`universe.py` 清洗剔 ST/次新，约 600–750 只），实际抽样 110 训练 / 12 验证 / 12 测试 |
| 切分 | `split.py` **按股票不相交**切 train/val/test，按行业分层；已验 `train∩test = train∩val = val∩test = 0` |
| 量级 | train **2315** 道 / val **220** / test **214**（spec 目标 ~2000，达标） |

### 还没解决的三个缺口（本计划要补）

**缺口 A — 意图广度仍是老 6 类，业务 job 缺 5 个。**
现有意图：`stock_study` / `snapshot_quote` / `financial_report` / `position_calc` / `portfolio_calc` / `valuation_calc`。
缺的业务 job（都属"有唯一答案、机器能判对错"，且 oracle 现成）：
1. **核对一个数**（财报对账，±容差）—— 零覆盖
2. **盯异动信号**（同比增速 / 环比变化 / 股东户数降幅）—— 零覆盖
3. **现在算便宜还是贵**（PE 历史分位）—— 零覆盖
4. **账户真实收益**（TWR）+ **赚钱来源拆解**（三层归因）—— `portfolio_calc` 只有市值/权重/集中度，缺这两样
5. **EV/EBITDA 理论价** —— `valuation_calc` 只有 PE/PB 理论价，缺这个

**缺口 B — 测试集测不出真实力。** test 214 道里 **202 简单 / 12 中等 / 0 难**（94% 简单），几乎全是"查个数"。一个没有难题的测试集，高分不代表会算难题。

**缺口 C — 按股切 + 小抽样把多股意图在 test 里清零了。** test 意图分布：`stock_study 84 / snapshot 47 / financial 59 / position 24 / valuation 0 / portfolio 0`。估值/组合题需要同行业凑 ≥2 只票，每份只抽 ~10 只 → 这两类在 val/test 蒸发。测试集**完全测不了**估值和组合能力。

**附带缺口 D — 判分只有一道门。** `judge.py` 只用正则抓数字比容差，**没有**"确认 AI 真用 `run_python` 算了"那道门。对需自算的难题（分位/TWR/归因），蒙一个数也可能命中容差 → 难题判分不可信。

---

## 二、设计取舍（why）

- **目标是喂 RL 训练**：学习信号在"有时过有时崩"的中/难带；简单查数题模型稳过=零梯度。所以本计划**不补简单取数**（市值/市销率等同属"查数"job，已覆盖），只补**新 job + 难题**。
- **意图 = 需求侧 job，不是供给侧指标**：按"用户要干的事"补，不是照指标目录逐项灌——否则换个指标当新意图，是历史返工的根因。
- **oracle 一律复用现成独立函数**：5 个新家族各对应一个已存在的纯函数/tushare 预算字段（见各 Task），不自造算法、不抄被测代码。
- **DCF / WACC / 资金流向不做**：DCF 循环 oracle、资金流向阈值主观（承指标目录 `2026-06-16-deterministic-indicator-catalog.md` 第 101 行的排除理由）。
- **排序/筛选(ranking/set)不进本计划的奖励统计**：judge 读自由名单不稳，留诊断轨。

---

## 三、文件结构

| 文件 | 改动 | 责任 |
|---|---|---|
| `backend/eval/question_gen/intents.py` | 改 | 新增 3 个意图常量 + 各家族中文题面函数 |
| `backend/eval/question_gen/operators.py` | 改 | 新增派发：`pe_percentile_lookup` / `ev_ebitda_value` / `portfolio_twr` / `portfolio_attribution` / `financial_verify_real` |
| `backend/eval/question_gen/generator.py` | 改 | 新增 `build_verify_cases` / `build_trend_cases` / `build_percentile_cases` / 扩 `build_portfolio_cases`（TWR+归因）/ 扩 `build_valuation_cases`（EV/EBITDA），并在 `generate()` 串入 |
| `backend/eval/question_gen/build_datasets.py` | 改 | 抽样改为"按行业保量"，保证 val/test 每份含 ≥1 个 ≥2 成员行业 + ≥1 个 ≥3 成员行业（让估值/组合/排序题能生成） |
| `backend/eval/question_gen/runner.py` | 改 | 加判分第二门：self-computed 意图，trace 无 `run_python` 调用 → 判 0（即便数字命中容差） |
| `backend/eval/question_gen/case.py` | 改（小） | `ComputationCase` 加 `requires_run_python: bool = False` 字段（标记需自算的家族） |
| `backend/tests/eval/question_gen/test_generator_verify.py` 等 | 新建 | 每个新家族一个生成器单测 |
| `backend/tests/eval/question_gen/test_runner_run_python_gate.py` | 新建 | 第二门单测 |

**意图命名**（自解释中文语义，沿用现有 `snake_case` 英文常量）：
- `financial_verify`（核对一个数）
- `trend_signal`（盯异动信号：同比/环比/股东户数）
- `valuation_percentile`（便宜还是贵：PE 历史分位）
- TWR / 归因 复用 `portfolio_calc` 意图，新增 `indicator`（"真实收益TWR" / "收益归因"）
- EV/EBITDA 复用 `valuation_calc` 意图，新增 `indicator`（"EV理论价"）

---

## 四、实施（四波，按 oracle 成本从低到高，每波独立可交付）

### Phase 1 — 补"核对 + 盯信号"两个新意图（最便宜，oracle = tushare 预算字段 / 两期相减）

#### Task 1：核对一个数（`financial_verify`）

**Files:**
- Modify: `backend/eval/question_gen/intents.py`、`operators.py`、`generator.py`
- Test: `backend/tests/eval/question_gen/test_generator_verify.py`（新建）

**oracle（现成）：** `dd_report/metrics/numerical_metric.py` 的真值取数 + `parse_chinese_number`；gold = tushare 真实 `income.revenue` / `income.n_income`（元→亿），容差 ±1%。题面嵌入一个"声称值"（gold ±5% 的扰动），让 agent 取真值核对。

- [ ] **Step 1: 写失败测试**

```python
# test_generator_verify.py
import asyncio
from eval.question_gen import generator, intents
from tests.eval.question_gen.conftest import StubTushare  # 复用既有 stub 模式

def test_verify_cases_gold_is_real_value():
    stub = StubTushare(income={"600519.SH": {"revenue": 1.5e11, "n_income": 6e10}})
    cases = asyncio.run(generator.build_verify_cases(stub, "20260612", "20241231", "2024年年报", _cid()))
    assert all(c.intent == intents.INTENT_FINANCIAL_VERIFY for c in cases)
    rev = next(c for c in cases if c.indicator == "营收核对")
    assert abs(rev.gold - 1500.0) < 1e-6          # gold = 真实值(亿), 不是声称值
    assert rev.gold_shape == "scalar"
    assert rev.requires_run_python is False        # 取数核对不强制 run_python
```

- [ ] **Step 2: 跑测试确认 FAIL**（`build_verify_cases` 未定义）
- [ ] **Step 3: 实现** `intents.INTENT_FINANCIAL_VERIFY = "financial_verify"` + 题面 `q_verify(name, indicator_label, claimed, period_label)`（如 `"有人说{name}{period}营收{claimed}亿,对不对?以财报为准。"`）+ `operators.financial_verify_real(indicator, snap)` 直取真值 + `generator.build_verify_cases(...)`（结构照 `build_financial_cases`，gold=真值，meta 存 `claimed`）。
- [ ] **Step 4: 跑测试确认 PASS**
- [ ] **Step 5: commit** `feat(question_gen): 新增财报核对意图 financial_verify`

#### Task 2：盯异动信号（`trend_signal`）

**Files:** 同上三文件 + `test_generator_trend.py`（新建）

**oracle（现成）：** tushare 预算字段 `q_sales_yoy`（营收同比）/`netprofit_yoy`（净利同比）；环比/股东户数走两期相减（`(本期−上期)` 或 `(prev−curr)/prev×100`，prev≤0 跳过）。难度=中等，gold_shape=scalar。

- [ ] **Step 1:** 写失败测试：`build_trend_cases` 产 `trend_signal` 意图，营收同比 gold == tushare `q_sales_yoy` 字段值，股东户数降幅 gold == `(prev−curr)/prev*100`。
- [ ] **Step 2:** 跑测试确认 FAIL。
- [ ] **Step 3:** 实现 `INTENT_TREND_SIGNAL` + 题面（"{name}{period}营收同比增长了百分之多少?" / "{name}股东户数比上期降了百分之多少?"）+ operators 派发 + `build_trend_cases`（同比直取预算字段；股东户数取 `holder_num` 两期）。
- [ ] **Step 4:** 跑测试确认 PASS。
- [ ] **Step 5:** commit `feat(question_gen): 新增异动信号意图 trend_signal(同比/环比/股东户数)`。

> Phase 1 验收：`generate()` 串入这两个 `build_*`；新增意图各 ≥3 道；既有生成器单测全绿。

---

### Phase 2 — 补难档自算意图（oracle = 现成独立函数，需 `run_python` 形态）

> 这三个是测试集现在最缺的"难题"。生成器侧每个 case 标 `requires_run_python=True`，供 Phase 3 的第二门识别。

#### Task 3：现在算便宜还是贵（`valuation_percentile`，PE 历史分位）

**Files:** `intents.py` / `operators.py` / `generator.py` + `test_generator_percentile.py`

**oracle（现成）：** `indicator_oracle.pe_percentile(history: list[float], current: float) -> float`（分数 ∈[0,1]，不插值）。`history` = 该股近 N 年 `daily_basic.pe` 序列，`current` = as_of 当日 PE。难度=难，gold = `pe_percentile(...) * 100`（百分位）。

- [ ] **Step 1:** 写失败测试：

```python
def test_percentile_gold_matches_oracle():
    from eval import indicator_oracle
    hist = [10.0, 20.0, 30.0, 40.0]; cur = 25.0
    expected = indicator_oracle.pe_percentile(hist, cur) * 100   # = 50.0
    stub = StubTushare(pe_history={"600519.SH": hist}, pe_now={"600519.SH": cur})
    cases = asyncio.run(generator.build_percentile_cases(stub, "20260612", _cid()))
    c = cases[0]
    assert abs(c.gold - expected) < 1e-6
    assert c.requires_run_python is True
    assert c.intent == intents.INTENT_VALUATION_PERCENTILE
```

- [ ] **Step 2:** 跑测试确认 FAIL。
- [ ] **Step 3:** 实现 `INTENT_VALUATION_PERCENTILE = "valuation_percentile"` + 题面（"{name}现在的市盈率,放在过去三年里算什么分位?(百分之多少的时间比现在便宜)"，口径冻进题面：不插值、`<` 严格小于）+ `operators.pe_percentile_lookup(history, current)` 包 oracle + `build_percentile_cases`（取 `daily_basic.pe` 窗口序列 + 当日值；序列不足跳过）。
- [ ] **Step 4:** 跑测试确认 PASS。
- [ ] **Step 5:** commit `feat(question_gen): 新增PE历史分位意图 valuation_percentile(难档,run_python)`。

#### Task 4：账户真实收益(TWR) + 赚钱来源拆解(归因)（扩 `portfolio_calc`）

**Files:** `intents.py` / `operators.py` / `generator.py`（扩 `build_portfolio_cases`）+ `test_generator_portfolio_advanced.py`

**oracle（现成）：**
- TWR：`portfolio_analytics.compute_twr(snaps: list[DailySnap]) -> dict`，`DailySnap(date, holdings={ts_code:(qty,price)})`。合成 2–3 个交易日快照（固定 qty + 真收盘价），gold = `compute_twr(...)` 的链式收益。
- 归因：`portfolio_analytics.compute_daily_attribution(holdings: list[HoldingDaily]) -> AttributionResult`，`HoldingDaily(ts_code, market_value, asset_class, market_pct, sector_pct)`。gold = `AttributionResult.by_class`（multi_scalar）或 total（scalar）。

- [ ] **Step 1:** 写失败测试：合成持仓 → `compute_twr`/`compute_daily_attribution` 的返回值 == case.gold；TWR 为 scalar、归因为 multi_scalar；两者 `requires_run_python=True`。
- [ ] **Step 2:** 跑测试确认 FAIL。
- [ ] **Step 3:** 实现题面（TWR："某账户{基期持仓},经过{日期区间},剔除加减仓后的真实收益率是多少?"；归因："...这段时间整体涨跌里,大盘/行业/个股各贡献几个百分点?"，beta≈1 简化口径冻进题面）+ operators 两个包装 + 扩 `build_portfolio_cases` 用合成持仓 + 真价格。
- [ ] **Step 4:** 跑测试确认 PASS。
- [ ] **Step 5:** commit `feat(question_gen): portfolio_calc 扩 TWR+三层归因(难档,run_python)`。

#### Task 5：EV/EBITDA 理论价（扩 `valuation_calc`）

**Files:** `intents.py` / `operators.py` / `generator.py`（扩 `build_valuation_cases`）+ `test_generator_valuation.py`（扩）

**oracle（现成）：** `valuation_helpers.ev_ebitda.compute_ev_ebitda_value(*, ebitda, net_debt, shares_outstanding, industry_ev_ebitda_avg, industry_ev_ebitda_median) -> float`。

- [ ] **Step 1:** 写失败测试：给定 ebitda/net_debt/shares + 行业倍数 avg/median，case.gold == `compute_ev_ebitda_value(...)`；indicator == "EV理论价"；难度=中等。
- [ ] **Step 2:** 跑测试确认 FAIL。
- [ ] **Step 3:** 实现 `q_valuation` 扩 EV 分支（题面明示可比篮子 + EV/EBITDA 口径）+ `operators.ev_ebitda_value(...)` + 扩 `build_valuation_cases`。**Step 3a（研究步）：确认 ebitda / net_debt / shares 的 tushare 来源字段**——查 `app/services/tushare_client.py` 与 `valuation_helpers/ev_ebitda.py` 的既有调用点，确定从 `income`/`balancesheet`/`fina_indicator` 哪些字段拼 ebitda 与 net_debt（缺字段则该股跳过，照现有 `_finite_positive` 模式）。
- [ ] **Step 4:** 跑测试确认 PASS。
- [ ] **Step 5:** commit `feat(question_gen): valuation_calc 扩 EV/EBITDA 理论价`。

---

### Phase 3 — 判分第二门：难题必须真用 `run_python` 算（防"假算"）

#### Task 6：`case.py` 加 `requires_run_python` 字段

- [ ] **Step 1:** 写失败测试：`ComputationCase(..., requires_run_python=True)` round-trip jsonl 后字段保留；默认 `False`。
- [ ] **Step 2:** 跑测试确认 FAIL。
- [ ] **Step 3:** 给 dataclass 加 `requires_run_python: bool = False`，dump/load 带上。
- [ ] **Step 4:** 跑测试确认 PASS。
- [ ] **Step 5:** commit `feat(question_gen): ComputationCase 加 requires_run_python 标记`。

#### Task 7：runner 加第二门

**Files:** `backend/eval/question_gen/runner.py` + `test_runner_run_python_gate.py`（新建）

**逻辑：** 判分时，若 `case.requires_run_python` 为真，则除数字命中容差外，还须从 agent trace 中检出至少一次 `run_python` 工具调用；否则该 case 记为**未过**（即便数字对），并打 `reason="no_run_python"`。trace 里工具名的提取点复用 `runner` 现有的 trace 解析（与窗口 sanity 同源）。

- [ ] **Step 1:** 写失败测试：

```python
def test_self_computed_without_run_python_fails():
    case = make_case(requires_run_python=True, gold=50.0, gold_shape="scalar")
    trace_no_py = [{"tool": "get_daily_basic"}]      # 没调 run_python
    trace_with_py = [{"tool": "get_daily_basic"}, {"tool": "run_python"}]
    assert runner.judge_with_gate(case, answer="50.0", trace=trace_no_py) is False
    assert runner.judge_with_gate(case, answer="50.0", trace=trace_with_py) is True
    # 非自算意图不受影响
    case2 = make_case(requires_run_python=False, gold=50.0, gold_shape="scalar")
    assert runner.judge_with_gate(case2, answer="50.0", trace=trace_no_py) is True
```

- [ ] **Step 2:** 跑测试确认 FAIL。
- [ ] **Step 3:** 实现 `judge_with_gate(case, answer, trace)`：先调既有 `judge.judge(...)`；若 `case.requires_run_python` 且 trace 内无 `run_python` 工具名 → 返回 False。串入 runner 主循环并把 `no_run_python` 计入分桶诊断。
- [ ] **Step 4:** 跑测试确认 PASS。
- [ ] **Step 5:** commit `feat(question_gen): 判分第二门—自算意图须 trace 见 run_python`。

---

### Phase 4 — 修测试集组成：让全意图 + 难题真正落进 val/test

#### Task 8：抽样改"按行业保量"

**Files:** `backend/eval/question_gen/build_datasets.py` + `test_build_datasets_composition.py`（扩/新建）

**问题：** 现 `_sample` 从每个 split 随机抽 10 只 → 同行业凑不够 2/3 只 → 估值/组合/排序题在 val/test 蒸发。
**方案：** 抽样时保证每份（尤其 val/test）至少含**一个 ≥3 成员的行业**和**一个 ≥2 成员的行业**（其余名额随机补足），使多股意图与排序题在每份都能生成。确定性（固定 seed）。

- [ ] **Step 1:** 写失败测试：

```python
def test_val_test_contain_multistock_intents():
    universe = make_universe(sectors={"白酒":6,"银行":4,"医药":3,"电子":2,"其他":20})
    paths = asyncio.run(build_datasets(StubTushare(universe), val_sample=10, test_sample=10))
    for split in ("val","test"):
        rows = load_jsonl(paths[split])
        intents = {r["intent"] for r in rows}
        assert "valuation_calc" in intents      # 估值题必须出现
        assert "portfolio_calc" in intents      # 组合题必须出现
```

- [ ] **Step 2:** 跑测试确认 FAIL（现随机抽样不保证）。
- [ ] **Step 3:** 改 `_sample` → `_sample_balanced(stocks_by_sector, n, seed)`：先各取一个 ≥3 行业的 3 只 + 一个 ≥2 行业的 2 只，再随机补到 n。
- [ ] **Step 4:** 跑测试确认 PASS。
- [ ] **Step 5:** commit `fix(question_gen): 抽样按行业保量—估值/组合题回到 val/test`。

#### Task 9：live 重生成三套数据集 + 难度落点核验

> 需 `TUSHARE_MODE=real` + .env（WSL fria-venv，见项目记忆）。非 CI，手动跑一次落盘。

- [ ] **Step 1:** 跑 `python -m eval.question_gen.build_datasets` 重生成 train/val/test。
- [ ] **Step 2:** 跑核验脚本断言（见下"验收标准"全部命中）：test 含全部 8 类意图、含难档（`requires_run_python=True`）≥1 类、三套股票仍不相交。
- [ ] **Step 3:** commit 数据 `chore(question_gen): 重生成评估集—补5意图+难档进 test`。

---

## 五、验收标准

**生成器（离线，CI 守护）**
1. 新增 3 个意图（`financial_verify` / `trend_signal` / `valuation_percentile`）+ `portfolio_calc` 的 TWR/归因 + `valuation_calc` 的 EV 理论价，各有生成器单测，绿。
2. 每个新家族的 gold **完全等于其现成 oracle 的输出**（`pe_percentile` / `compute_ev_ebitda_value` / `compute_twr` / `compute_daily_attribution` / `numerical_metric` 真值），单测逐位比对。
3. 难档家族（分位/TWR/归因）的 case `requires_run_python == True`；取数/核对类为 `False`。

**判分第二门**
4. `judge_with_gate`：`requires_run_python=True` 的 case，trace 无 `run_python` → 判未过（即便数字命中容差）；`False` 的 case 不受影响。单测覆盖正负例。

**测试集能评真实力（缺口 B/C 关闭，live 数据核验）**
5. `test.jsonl` 含**全部 8 类意图**（原 6 + 至少 `valuation_calc`、`portfolio_calc` 不再为 0），且新增意图各 ≥1 道。
6. `test.jsonl` 含**难档** case（`requires_run_python=True`）≥ 1 类、≥ N 道（建议 N≥10，评审定）；即 test 难题占比从 0 抬升到可测水平。
7. train/val/test **股票仍两两不相交**（回归 #178 红线）。

**零回归**
8. 既有 question_gen 全套单测 + chatloop eval 无回归；`ruff` / `mypy` 绿。

---

## 六、明确不做（YAGNI，承指标目录排除项）

- DCF 全家（循环 oracle）、WACC 单独成题（DCF 输入、经验系数同源）、估值一致性 CV（阈值主观）、大单资金净流向（阈值缺/贴噪声）。
- ranking/set（排序/筛选）不纳入本计划奖励统计（judge 读自由名单不稳，留诊断轨）。
- 难度按 pass-rate 筛"学得动区间"（0.2–0.8）是下游 RL 步骤（#178 spec 标的 Task 19），本计划只负责让难题**存在且进 test**，不负责按通过率分流。
