# 数据分布管线（打标 + 派生）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `2026-06-24-eval-data-distribution-design.md` 落地：建好"通过率打标 + 三套派生（eval/SFT/RL）"的**纯函数基建 + 编排代码**（CI 守护），并给出**需真 tushare/模型的 live 跑 runbook**（用户触发）。

**Architecture:** 复用已有件——`runner.run_passk`(已支持 `k` + `collect_dir` gold 隔离)、`build_datasets`(#178 中证800 按股切 + #183 `_sample_balanced`)、`difficulty_sort`。新增 4 个**纯函数/编排**模块：`band.py`(k→标)、`cleanliness.py`(SFT 第二道闸)、`tag_cases.py`(编排打标→写 manifest)、`derive_sets.py`(manifest→三套 jsonl)。纯逻辑全用合成数据单测，模型/tushare 的重跑只在 live runbook。

**Tech Stack:** Python / pytest / WSL fria-venv / 真 tushare(cassette 冻结) / 基座 qwen3-8b + 强模型(registry)。

---

## 现状（已核验）

**已有可复用**：
- `runner.run_passk(cases, *, k=1, concurrency, as_of, max_steps, model, answers_path, collect_dir)` → `{pass_at_k, by_bucket, per_case}`；`collect_dir` 给则写 `trajectories_raw.jsonl`(无 gold)+`judgements.jsonl`(gold) —— **gold 隔离 + k 重采底座已在**。内部 `per_run[cid]=[k 次 bool]`（pass 计数的来源）。
- `runner.judge_with_gate` / `trace_has_run_python`（#183 判分第二门）。
- `build_datasets.build_datasets(tushare, ..., train_sample, val_sample, test_sample, seed)` + `_sample_balanced`（#183 按行业保量）；`split.split_by_stock`（#178 按股不相交）；`generator.generate(pool=, tushare=)`（含 #183 新意图）。
- `case.ComputationCase`（含 `requires_run_python` / `intent` / `difficulty` / `stocks` / `gold` / `gold_shape`）；`case.load_jsonl` / `dump_jsonl`。

**全新建**：`band.py` / `cleanliness.py` / `tag_cases.py` / `derive_sets.py` + 各单测。

## 文件结构

| 文件 | 改/建 | 责任 |
|---|---|---|
| `backend/eval/question_gen/band.py` | 建 | 纯函数：N 次 rollout 的通过次数 k → 标 `too_hard/rl_band/too_easy` + 是否黄金带 |
| `backend/eval/question_gen/cleanliness.py` | 建 | 纯函数：一条轨迹(messages+halt_reason+步数) → SFT 第二道闸 bool + cleanliness_score |
| `backend/eval/question_gen/runner.py` | 改 | `run_passk` 返回值加 `per_case_counts`(case_id→通过次数)，供 band 打标；不动既有键 |
| `backend/eval/question_gen/tag_cases.py` | 建 | 编排：跑基座 N=8 出通过次数 + 跑强模型 k=5 出干净轨迹 → 组装 manifest 行；纯组装逻辑单测 |
| `backend/eval/question_gen/derive_sets.py` | 建 | 纯函数：candidate jsonl + manifest → 写 eval/sft_seeds/rl_train 三套(gold 隔离、SFT 每题≤2+job 上限、RL 仅 reward_eligible∩rl_band、股票不相交断言) |
| `backend/tests/eval/question_gen/test_band.py` 等 4 个 | 建 | 各模块单测 |

> 通用提交纪律（每个 Task 都照做）：worktree `core.autocrlf=true`，提交前在 WSL `sed -i 's/\r$//'` LF 化 → `git -c core.autocrlf=false add <文件>` → `git show --stat HEAD` 核行数。**推/合前必跑全 4 道 CI 闸**：`ruff format --check .`（独立于 `ruff check`，易漏）/ `ruff check .` / `mypy`（全项目无参）/ `pytest`。测试命令：
> `wsl bash -lc 'cd /mnt/d/mys/Financial-Research-Investment-Assistant/.claude/worktrees/eval-intent-coverage/backend && POSTGRES_PASSWORD=postgres123 /home/administrator/fria-venv/bin/python -m pytest tests/eval/question_gen/ -q >/dev/null 2>&1; echo PYTEST_EXIT=$?'`

---

## Phase 1 — 可建基建（CI 守护，纯函数为主）

### Task 1：band.py —— 通过次数 → RL 标（spec §4.1）

**Files:** Create `backend/eval/question_gen/band.py`; Test `backend/tests/eval/question_gen/test_band.py`

- [ ] **Step 1: 写失败测试**

```python
# test_band.py
from eval.question_gen import band

def test_classify_n8():
    # N=8: k=0 too_hard, k=8 too_easy, k∈{1..7} rl_band, k∈{3,4,5} 黄金带
    assert band.classify(0, n=8) == band.Tag(label="too_hard", in_rl=False, prime=False)
    assert band.classify(8, n=8) == band.Tag(label="too_easy", in_rl=False, prime=False)
    assert band.classify(1, n=8) == band.Tag(label="rl_band", in_rl=True, prime=False)
    assert band.classify(7, n=8) == band.Tag(label="rl_band", in_rl=True, prime=False)
    for k in (3, 4, 5):
        assert band.classify(k, n=8) == band.Tag(label="rl_band", in_rl=True, prime=True)

def test_classify_validates():
    import pytest
    with pytest.raises(ValueError):
        band.classify(9, n=8)   # k>n 非法
```

- [ ] **Step 2: 跑测试确认 FAIL**（`band` 未定义）
- [ ] **Step 3: 实现**

```python
# band.py
"""通过次数 k(共 N 次 rollout) → RL 难度标。spec §4.1：丢端点 k∈{0,N}，留 k∈{1..N-1}，黄金带中间三档。"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Tag:
    label: str   # too_hard / rl_band / too_easy
    in_rl: bool  # 是否进 RL 候选(丢端点后)
    prime: bool  # 是否黄金带(主喂)

def classify(k: int, *, n: int = 8) -> Tag:
    if not (0 <= k <= n):
        raise ValueError(f"k={k} 越界 [0,{n}]")
    if k == 0:
        return Tag("too_hard", False, False)
    if k == n:
        return Tag("too_easy", False, False)
    # 黄金带：中心 ±1（N=8 → {3,4,5}；N 偶数取 n/2-1..n/2+1）
    mid = n / 2
    prime = abs(k - mid) <= 1
    return Tag("rl_band", True, prime)
```

- [ ] **Step 4: 跑测试确认 PASS**
- [ ] **Step 5: commit** `feat(question_gen): band 通过次数→RL 难度标(丢端点+黄金带)`

### Task 2：cleanliness.py —— SFT 第二道闸（spec §4.2）

**Files:** Create `backend/eval/question_gen/cleanliness.py`; Test `test_cleanliness.py`

闸条件（承 substrate spec §2b）：`halt_reason=="natural"` ∧ 无系统熔断注入 ∧ 步数 ≤ 桶理想步数。轨迹结构 = `runner` collect 出的 `trajectories_raw.jsonl` 行：`{case_id, model, messages, n_steps, halt_reason}`。

- [ ] **Step 1: 写失败测试**

```python
# test_cleanliness.py
from eval.question_gen import cleanliness

def _traj(halt="natural", n_steps=3):
    return {"case_id": "c1", "messages": [{"role": "assistant", "content": "ok"}],
            "n_steps": n_steps, "halt_reason": halt}

def test_clean_pass():
    assert cleanliness.is_clean(_traj(), ideal_steps=5) is True

def test_halt_not_natural_fails():
    assert cleanliness.is_clean(_traj(halt="max_steps"), ideal_steps=5) is False

def test_over_ideal_steps_fails():
    assert cleanliness.is_clean(_traj(n_steps=9), ideal_steps=5) is False
```

- [ ] **Step 2: 跑确认 FAIL**
- [ ] **Step 3: 实现**

```python
# cleanliness.py
"""SFT 第二道闸：轨迹过程是否干净(承 RL substrate spec §2b)。"""
from __future__ import annotations

def is_clean(traj: dict, *, ideal_steps: int) -> bool:
    if traj.get("halt_reason") != "natural":
        return False
    n = traj.get("n_steps")
    if n is None or n > ideal_steps:
        return False
    return True
```

- [ ] **Step 4: 跑确认 PASS**
- [ ] **Step 5: commit** `feat(question_gen): cleanliness SFT 第二道闸(halt natural+步数≤理想)`

### Task 3：runner 暴露 per-case 通过次数

**Files:** Modify `backend/eval/question_gen/runner.py`(`_aggregate` + `run_passk` 返回值); Test `test_runner_counts.py`

- [ ] **Step 1: 写失败测试**

```python
# test_runner_counts.py
from eval.question_gen import runner

def test_aggregate_exposes_counts():
    per_run = {"a": [True, False, True], "b": [False, False, False]}
    out = runner._aggregate([], per_run)  # 空 cases 也应给 counts(用 per_run 的 key)
    assert out["per_case_counts"] == {"a": 2, "b": 0}
```

> 注：`_aggregate` 现签名 `(cases, per_run)` 且用 `by_id[cid]` 查 difficulty/indicator 分桶——空 cases 会 KeyError。本任务把 counts 计算挪到不依赖 `by_id` 的地方（直接 `sum(runs)`），并让分桶对缺失 case 容错跳过。

- [ ] **Step 2: 跑确认 FAIL**
- [ ] **Step 3: 实现**：`_aggregate` 加 `per_case_counts = {cid: sum(runs) for cid, runs in per_run.items()}` 进返回 dict；分桶循环对 `cid not in by_id` 用 `continue` 容错。`run_passk` 返回值天然带上(它 return `_aggregate(...)`)。
- [ ] **Step 4: 跑确认 PASS**
- [ ] **Step 5: commit** `feat(question_gen): run_passk 返回 per_case_counts(供 band 打标)`

### Task 4：tag_cases.py —— 编排打标 + manifest

**Files:** Create `backend/eval/question_gen/tag_cases.py`; Test `test_tag_cases.py`

职责：① 跑基座 N=8（`run_passk(cases, k=8, model=base)`）拿 `per_case_counts` → 经 `band.classify` 打 RL 标；② 跑强模型 k=5 collect 模式 → 读 `trajectories_raw.jsonl` 经 `cleanliness.is_clean` 数干净条数 → 打 `sft_seed`；③ 组装 manifest 行 `{case_id, p_base_k, n, tags{label,in_rl,prime}, reward_eligible, sft_clean_count}` 写 jsonl。**纯组装函数 `build_manifest_rows(counts, n, clean_counts, cases)` 单测；跑模型的 `run_tagging(...)` 是 live 编排（runbook 调）。**

- [ ] **Step 1: 写失败测试**（只测纯组装）

```python
# test_tag_cases.py
from eval.question_gen import tag_cases, case as case_mod

def _case(cid, intent="snapshot_quote", shape="scalar"):
    return case_mod.ComputationCase(case_id=cid, intent=intent, difficulty="简单",
        question="?", stocks=["600519.SH"], indicator="PE", window="snapshot",
        gold=1.0, gold_shape=shape, tolerance={"kind": "rel", "value": 0.01}, meta={})

def test_build_manifest_rows():
    cases = [_case("a"), _case("b", intent="stock_study", shape="ranking")]
    counts = {"a": 4, "b": 0}          # a 黄金带, b too_hard
    clean = {"a": 2, "b": 0}
    rows = {r["case_id"]: r for r in tag_cases.build_manifest_rows(counts, 8, clean, cases)}
    assert rows["a"]["tags"]["label"] == "rl_band" and rows["a"]["tags"]["prime"] is True
    assert rows["a"]["reward_eligible"] is True and rows["a"]["sft_clean_count"] == 2
    assert rows["a"]["intent"] == "snapshot_quote"   # manifest 行带 intent(供 derive 的 per-job 上限)
    assert rows["b"]["tags"]["label"] == "too_hard"
    assert rows["b"]["reward_eligible"] is False   # ranking/set 不进奖励
```

> manifest 行 schema：`{case_id, intent, n, pass_count, tags{label,in_rl,prime}, reward_eligible, sft_clean_count}`。`reward_eligible` 判定：`gold_shape in ("scalar","multi_scalar")`（ranking/set → False）；`intent` 取 `case.intent`（供 Task 5 `select_sft` 的 per-job 上限）。

- [ ] **Step 2: 跑确认 FAIL**
- [ ] **Step 3: 实现** `build_manifest_rows(counts, n, clean_counts, cases)`（纯组装，调 `band.classify` + `gold_shape` 判 reward_eligible）+ `dump_manifest(rows, path)`；`run_tagging(...)` 编排（import 在函数内，跑 `run_passk` 两次）留给 runbook，不进单测。
- [ ] **Step 4: 跑确认 PASS**
- [ ] **Step 5: commit** `feat(question_gen): tag_cases 组装打标 manifest(band+reward_eligible+sft)`

### Task 5：derive_sets.py —— manifest → 三套

**Files:** Create `backend/eval/question_gen/derive_sets.py`; Test `test_derive_sets.py`

职责（纯函数 + 文件写）：读 candidate cases + manifest →
- **rl_train**：`tags.in_rl` ∧ `reward_eligible` 的 case_id；
- **sft_seeds**：`sft_clean_count>0` 的 case，每题≤2 条轨迹 + 每 intent 设上限（如 ≤ `per_job_cap`）；
- **eval**：评测集独立来源（评测股生成的 cases），不依赖 manifest，但同样 gold 隔离。
断言：rl/sft 用的 case 股票 ∩ eval 股票 = ∅（防泄漏）。

- [ ] **Step 1: 写失败测试**

```python
# test_derive_sets.py
from eval.question_gen import derive_sets

def test_select_rl_ids():
    manifest = [
        {"case_id": "a", "tags": {"in_rl": True}, "reward_eligible": True},
        {"case_id": "b", "tags": {"in_rl": True}, "reward_eligible": False},  # ranking → 排除
        {"case_id": "c", "tags": {"in_rl": False}, "reward_eligible": True}, # 端点 → 排除
    ]
    assert derive_sets.select_rl_ids(manifest) == {"a"}

def test_select_sft_caps_per_case_and_job():
    manifest = [{"case_id": f"x{i}", "sft_clean_count": 5, "intent": "snapshot_quote"} for i in range(10)]
    picked = derive_sets.select_sft(manifest, per_case_cap=2, per_job_cap=6)
    assert sum(p["take"] for p in picked) == 6          # job 上限 6
    assert all(p["take"] <= 2 for p in picked)          # 每题≤2
```

- [ ] **Step 2: 跑确认 FAIL**
- [ ] **Step 3: 实现** `select_rl_ids(manifest)`、`select_sft(manifest, per_case_cap, per_job_cap)`、`write_sets(candidate_cases, manifest, eval_cases, out_dir, ...)`（写 `rl_train.jsonl`/`sft_seeds.jsonl`/`eval.jsonl`，gold 隔离沿用 runner 约定）+ `assert_stock_disjoint(train_cases, eval_cases)`。
- [ ] **Step 4: 跑确认 PASS**
- [ ] **Step 5: commit** `feat(question_gen): derive_sets manifest→eval/SFT/RL 三套(caps+股票不相交)`

---

## Phase 2 — Live runbook（需真 tushare + 模型，用户触发，不进 CI）

> 全程 `TUSHARE_MODE=real` + token + 代理（见记忆"接真 tushare"）；as_of=20260612；WSL fria-venv。每步落盘 + 冻 cassette。

1. **生成候选池 + 评测池**
   `python -m eval.question_gen.build_datasets`（train_sample 调到产 ~3000 候选；val/test 产 ~500 评测）→ 训练股候选 jsonl + 评测 jsonl + cassette。
2. **打标跑**（`tag_cases.run_tagging`）
   - 基座：`run_passk(candidate, k=8, model="qwen3-8b")` → `per_case_counts`。
   - 强模型：`run_passk(candidate, k=5, model="<最强>", collect_dir=...)` → `trajectories_raw.jsonl`。
   - 组装 → `manifest.jsonl`。
3. **派生三套**（`derive_sets.write_sets`）→ `rl_train.jsonl` / `sft_seeds.jsonl` / `eval.jsonl`（gold 隔离、股票不相交单测过）。
4. **评测重采**：`run_passk(eval_cases, k=16, answers_path=...)` 出按桶 pass@1。
5. 抽样人工核 5 条轨迹（tool 结果完整、无系统注入、无 gold 混入），再提数据 PR。

## 验收

- Phase 1：`band`/`cleanliness`/`per_case_counts`/`tag_cases.build_manifest_rows`/`derive_sets` 全单测绿；全 `tests/eval/question_gen/` 退出码 0；ruff format+check / mypy 全绿。
- Phase 2（live 后）：manifest 每题带 N=8 通过次数 + 标；三套规模达标（eval~500 可 k=16 重采 / RL 带内 >1000 / SFT~500）；股票不相交单测过；gold 与轨迹物理隔离。

## 明确不做

- 连续距离奖励 / reward 加权（RL 训练侧，承 substrate spec）。
- EV/EBITDA（DEFER，承 #183）。
- 不写死 0.2–0.8 窄带（用 band 的丢端点逻辑）。
