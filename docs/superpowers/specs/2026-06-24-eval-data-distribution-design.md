---
title: 评估/训练数据分布总体设计 — 一个候选池 → 通过率打标 → 三套派生（eval / SFT / RL）
date: 2026-06-24
type: design-spec
status: 待评审
related:
  - docs/superpowers/specs/2026-06-22-eval-data-pipeline-design.md          # #178 中证800→按股切 train/val/test（本 spec 的上游管线）
  - docs/superpowers/specs/2026-06-18-shorten-chains-and-rl-substrate-design.md  # RL 底料/轨迹采集（数据的下游消费者）
  - docs/superpowers/plans/2026-06-23-eval-intent-coverage-expansion.md     # 已 ship：补 5 业务意图 + 判分第二门 + 抽样保量（生成层基础）
  - docs/research/2026-06-16-deterministic-indicator-catalog.md             # 可验证意图全集来源
  - docs/research/2026-06-22-sft-warmstart-plan.md                          # SFT 暖启动
  - docs/research/2026-06-17-pre-rl-tooling-baseline.md                     # 141 题基线 / qwen3-8b 战力
  - backend/eval/question_gen/
---

# 评估/训练数据分布总体设计

## 一句话

把出题机产出的题，从"一锅生成、随手分"升级成**一个全谱候选池 → 跑模型按通过率打标 → 为三个不同消费者（评测基准 / SFT 暖启动 / RL 训练）各派生一套目标分布**。三套的分布互不相同，且 SFT/RL 两套的难度**由跑模型实测的通过率决定，不由生成时贴的标签决定**。

## 一、为什么需要总体设计

此前数据是"生成什么就用什么"，导致：意图覆盖窄、难度倒挂（test 94% 简单）、估值/组合在 test 里为 0、训练/评测靠抽样随机切。`2026-06-23` 那波已补齐生成层（5 新意图 + 判分第二门 + 按行业保量），但**"最终要什么分布"始终没有从系统层定义过**。本 spec 补这个总图：明确三个消费者各要什么、怎么从一个池子派生、各自规模多大、难度怎么定。

关键认知（贯穿全文）：**「最终分布」不是一个分布，是"一个池子 + 三套派生"。** 我们直接控的只有**生成层**（候选池的 job×难度×股票×量）；三套消费分布里，eval 靠分层抽样钉死，**SFT/RL 两套靠"跑模型测通过率"筛出来**——生成时贴的"简单/中等/复杂"只是旋钮数代理，跟"对基座到底难不难"是两回事。

## 二、整体框架（管线骨架）

```
中证800 成分股 → 清洗(剔 ST/次新) → 按股票不相交切两边
   ├─ 评测股(val+test stocks，与训练股 disjoint) ─→ 【评测基准】全谱、钉死、冻 cassette
   └─ 训练股 ───────────────────────────────────→ 【SFT+RL 候选池】全谱大量生成
                                                       │  一次性"跑模型打标"
                                                       ├─ 跑基座 qwen3-8b(N=8 rollout) → 测通过率 → 打 rl_band / too_easy / too_hard
                                                       └─ 跑强模型(k=5 + 两道闸)        → 打 sft_seed + 收干净轨迹
```

一道生成、两次"跑模型打标"、派生三套。一道题可同时带多个标（如既 `sft_seed` 又 `rl_band`）。

**红线（承 #178 / RL substrate spec）**：
1. 评测股与训练股**股票不相交**（held-out 测真泛化，杜绝背答案）；
2. **gold 与轨迹物理隔离**（`judgements.jsonl` 含 gold / `trajectories_raw.jsonl` 无 gold，防 SFT 泄漏）；
3. 所有 gold 用**真 tushare**（cassette 冻结），mock 一律不当 oracle；as_of 钉死 `20260612` 可复现。

## 三、候选池生成分布（生成层，我们直接控）

**轴一 = 业务 job（需求侧）× 指标**，每项标"能否进奖励轨"+"是否需 run_python"：

| job 类 | 意图 / 指标 | reward_eligible | run_python |
|---|---|---|---|
| 时序计算 | 涨幅 / 回撤 / 波动 / 相关 / CAGR / 双指标 | ✅ scalar·multi | 是 |
| 快照取数 | PE / PB / 换手 / 股息（市值待补） | ✅ scalar | 否 |
| 财报取数 | ROE / 资产负债率 / 毛利率 / 营收 / 净利 | ✅ scalar | 否 |
| 核对 | 营收核对 / 净利核对 | ✅ scalar | 否 |
| 同比信号 | 营收同比 / 净利同比 | ✅ scalar | 否 |
| 持仓 | 单仓市值 / 浮盈 | ✅ scalar | 否 |
| 组合 | 权重 / HHI | ✅ scalar | 否 |
| 估值算式 | PE 理论价 / PB 理论价 | ✅ scalar | 否 |
| 难自算 | PE 历史分位 / TWR / 三层归因 | ✅ scalar·multi | **是** |
| 排序筛选 | 板块内排序 / 多条件筛选 | ❌ **诊断轨**（LLM 抽取判，不进奖励） | 是 |

**轴二 = 难度**：生成时贴"简单/中等/复杂"（旋钮数代理），**真难度由第四节跑基座测的通过率定**。

**轴三 = 股票**：训练股侧用全部训练股 × 上表全部意图 × 合法窗口**全量铺**（量大无妨，靠通过率筛）；评测股侧按行业保量抽（承 `_sample_balanced`），保证每意图都生成得出。

**生成纪律**：排序筛选照生成、照进评测，但生成时即 `reward_eligible=false`，绝不混进 RL 奖励统计。

**明确不做（YAGNI，承指标目录排除项）**：DCF 全家（循环 oracle）、EV/EBITDA（tushare 无 ebitda 字段，需先定口径 spec，见 `2026-06-23` 计划的 DEFER）、WACC、估值一致性 CV、大单资金净流向。

## 四、通过率打标（选择层，跑模型实测）

候选池生成 + 冻 cassette 后，做一次性"跑模型打标"，产出清单 `case_id → {p_base, sft_clean_count, tags}`。

### 4.1 基座通过率 → RL 标（文献校准，**非固定 0.2–0.8 窄带**）

跑基座 qwen3-8b，**每题 N=8 rollout**，得通过次数 k：

| k（N=8） | 通过率 | 标 | 去向 |
|---|---|---|---|
| k ∈ {0} | 0（全错） | `too_hard` | **丢出 RL**；留评测 + 未来课程 |
| k ∈ {8} | 1（全对） | `too_easy` | **丢出 RL**；只留评测 |
| k ∈ {1,2,6,7} | 偏斜但非退化 | `rl_band`（次优先） | 进 RL（可后续重采）|
| k ∈ {3,4,5} | 0.375–0.625 | `rl_band`（**黄金带，主喂**） | 进 RL，最高学习信号 |

**机理（数学事实，不随版本变）**：GRPO 每条 rollout 优势 `A_i=(r_i−mean)/std`，组内 reward 全同（全对/全错）→ 分子=0 → 优势=0 → **梯度消失**；学习信号正比伯努利方差 `p(1−p)`，0.5 处最大。所以**只硬丢两个退化端点 k∈{0,8}，保留 k∈{1..7}，主喂 k∈{3,4,5}**——比 0.2–0.8 窄带更宽、更贴工业真做法。仅 `reward_eligible=true` 的题进 RL 奖励（排序筛选即便在带内也不进）。

> 依据：DAPO（Dynamic Sampling 排除端点，2503.14476）/ DEPO（μ=0.5 高斯软加权，2509.01321）/ Online Difficulty Filtering（p(1−p) 下界，EACL2026 2504.03380）/ Baidu Rollout Pass-Rate Control（N=8 只丢 k∈{0,8}、黄金带 k∈{3,4,5}，2605.05112）/ DeepSeek-R1 GRPO 公式（2501.12948）。

### 4.2 强模型 → SFT 标

跑 registry 里能跑本 harness 的最强模型（如 deepseek），**k=5**、过**两道闸**——① 判对（收紧容差复判防蒙）② 过程干净（`halt_reason==natural` ∧ 全步 success ∧ 无打转/熔断 ∧ 步数≤桶理想）。至少 1 条干净轨迹则打 `sft_seed`，**每题最多收 2 条**。轨迹必须经本 harness 工具/循环产出（形态对齐 qwen3-8b 推理），不用自蒸馏、不凭空造。

## 五、三套派生目标分布（标准档，文献校准）

| 套 | 量 | 分布规则 | 怎么得到 |
|---|---|---|---|
| **候选池**（训练股） | ~3000 | 全谱（三轴铺开） | 生成层产出 |
| **RL 训练** | 预计带内 **>1000** | 丢 k∈{0,8}、留 k∈{1..7}、主喂 k∈{3,4,5}；仅 reward_eligible；带内宽 job 覆盖保泛化 | 4.1 打标筛 |
| **SFT 种子** | **~500**（保底 250，目标冲 500） | 按 job 形态铺（学全工具用法），每题≤2、每 job 设上限防独大 | 4.2 强模型筛 |
| **评测 held-out** | **~500**（val+test），**每题重采 k=16** 读 pass@1 | 全意图 × 全难度 + 排序筛选 + 难自算都进（照天花板）；钉死冻结 | 评测股分层抽样 |

**规模定位（文献对标）**：~3000 池 / >1000 RL / ~500 SFT / ~500 eval —— 方向与工业一致、量级偏小一档但完全合理。SFT ~500 对标 LIMO ~800（数百精选驱动强推理已被验证）、DeepSeek-R1 cold-start "数千"，属同量级偏小端，对个人作品级足够。eval ~500 对标 MATH-500；**关键不是桶多大而是每题重采 16 次压方差**（AIME 仅 30 题靠每题采 16–64 次读稳）。

> 依据：LIMO（~800 精选，2502.03387）/ DeepSeek-R1 cold-start "thousands"（2501.12948 §2.3.1）/ DeepScaleR（每题采 16，OpenReview I6GzDCne7U）。

## 六、验收（本设计落地后应满足）

1. **生成层**：候选池含第三节全部意图；排序筛选 `reward_eligible=false`；难自算 `requires_run_python=true`；评测股侧每意图都有题（含估值/组合，承 `_sample_balanced`）。
2. **打标层**：产出 `case_id → {p_base(N=8), sft_clean_count, tags}` 清单；RL 标按"丢 k∈{0,8}、留 k∈{1..7}"实现（**不写死 0.2–0.8**）；reward_eligible=false 的题永不进 RL 奖励集。
3. **派生层**：eval ~500（每题 k=16 重采可读 pass@1）、RL 带内 >1000、SFT ~500（每题≤2、job 覆盖全）；三套与训练股**股票不相交**单测守护；gold 与轨迹物理隔离。
4. **可复现**：as_of 钉死、cassette 冻结、零 live 网络重跑。

## 七、实施分波提示（留给 writing-plans）

1. **生成候选池**：训练股侧全谱 live 生成（复用现有 build_*；含 `2026-06-23` 已 ship 的新意图）+ 评测股侧分层抽样生成 + cassette 冻结。
2. **打标基建**：N=8 跑基座出 `p_base` + 强模型 k=5 出干净轨迹 → 写 manifest（复用 runner，承 RL substrate spec 的轨迹落盘 + gold 隔离改造）。
3. **派生器**：按 manifest tags 切出 eval / SFT / RL 三套 jsonl（eval 标注 k=16 重采、SFT 每题≤2+job 上限、RL 仅 reward_eligible∩rl_band）。
4. **守护**：股票不相交 / gold 隔离 / reward_eligible 不漏 的单测。
