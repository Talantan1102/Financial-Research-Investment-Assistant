---
title: 反向出题机 v2 — 从诊断级到 RL 训练级的可验证评估集（全意图铺开）
date: 2026-06-18
type: design-spec
status: 待评审
related:
  - docs/superpowers/specs/2026-06-17-question-gen-mvp-design.md   # v1 MVP（被本 spec 扩）
  - docs/superpowers/specs/2026-06-18-agentic-rl-pilot-design.md   # 评估集的下游消费者
  - docs/research/2026-06-16-deterministic-indicator-catalog.md    # 意图/oracle 全集来源
  - docs/research/2026-06-09-rl-readiness-audit.md                 # 确定性 oracle 边界
  - docs/research/2026-06-17-pre-rl-tooling-baseline.md            # 当前 141 题基线
  - backend/eval/indicator_oracle.py
  - backend/eval/question_gen/
---

# 反向出题机 v2

## 一句话

把现有反向出题机（v1 MVP，只会出「时序价格计算」一类题）扩成**覆盖确定性指标目录全意图、
且达到 RL 训练级**的可验证评估集生成器：加宽意图（取数 / 估值算式 / 持仓组合 / 时序难档）、
加难（难度带压向中/难）、加量并拆 train/eval（训练集另生成，现 141 题留作 held-out）。

这是 `2026-06-18-agentic-rl-pilot-design.md` 第七节「样本量与边缘难题」的独立承接 spec
（按用户决策，**不并入 RL pilot spec**）。

## 一、为什么：v1 是诊断级，喂不动 RL

v1 MVP（`2026-06-17-question-gen-mvp-design.md`）是为「诊断 pass@k 战力断崖」造的，本就把范围
钉在一条竖切：1 意图 × 5 个 close 基指标 × 3 窗口 × ~15 只手挑股。**实测现状（141 题）**：

| 维度 | 现状 | 对 RL 的问题 |
|---|---|---|
| **意图** | 全是「时序价格计算」（涨幅 54/相关 18/波动 15/回撤+波动 15/CAGR 15/回撤 15/涨幅+回撤 9） | 只覆盖目录 7 大类的第 ④ 类；模型会过拟合「调 get_daily→run_python 算时序」单一套路 |
| **难度** | 易 90（64%）/ 中 33 / 难 18 | 倒挂；RL 学习信号在「不稳定通过」的中/难带，现仅 51 条，太薄 |
| **量级** | 141 条且 gold 已钉死 | 这是 held-out 评估基准，**不能拿去训**（泄漏）；训练集得另生成几百~上千 |
| **股票池** | 16 只 | 模型易记住特定股数值；要扩 + 多窗口/多 as_of 逼真算 |

v1 自己的 deferred 清单（「其它意图 / PE 分位 / 规模化全市场 不做」）**正是本 spec 要补的**；
RL 训练级要求（难度再平衡 / 量级 / train-eval 拆分 / 奖励形态纪律）是 v1 没有的新视角。

## 二、目标意图全集（覆盖图）

承确定性指标目录（54 项 7 大类）。本 spec 把可验证轨的全部意图家族铺开：

| 意图家族 | 目录类 | 代表题 | oracle 来源 | 数据路 | 难度落点 |
|---|---|---|---|---|---|
| **时序价格计算**（v1 已有，加难档） | ④ | 涨幅/回撤/波动/相关/CAGR/PE分位/TWR/三层归因 | `indicator_oracle`（现成）+ 独立库 | get_daily 序列 | 多为 hard |
| **行情快照取数** | ② | PE/PB/换手/市值/股息率（某交易日） | **tushare daily_basic 预算字段**（直接当答案） | get_daily_basic | 多为 easy |
| **财报指标取数** | ③ | ROE/营收/净利/资产负债率/毛利率/同比增速 | **tushare fina_indicator 预算字段** 或两原值相除 | get_financials | easy~medium |
| **相对估值算式** | ① | PE/PB 理论价、EV/EBITDA、WACC | `valuation_helpers` 纯函数（现成） | 取 eps/bvps/行业倍数 → 算 | medium |
| **持仓/组合量** | ⑥ | 单仓市值/权重/浮盈、组合归因、HHI | `portfolio_analytics` 纯函数 + **合成持仓** | 合成 positions + 价格 | easy~hard |

**全类铺开天然修了「难度倒挂」**：取数类补 easy 的同时，估值/组合/时序难档补足 medium/hard。

## 三、架构改造：生成器从「单一时序」泛化为「按意图插件」

v1 的 `generator.py` **硬编码**为「取 close/pct_chg/dates → 派发到 `indicator_oracle`」单意图。
全类铺开的核心工程是把它**泛化成插件式**：每个意图家族注册三件事——

1. **取数适配**：这个意图要什么数据（快照字段 / 财报字段 / 价格序列 / 合成持仓）；
2. **oracle 派发**：算/取标准答案的函数（见第六节 per-family）；
3. **题面模板**：`intents.py` 里该家族的中文题面 + gold_shape。

`operators.py` 的组合层（rank/filter）保留，但要能架在**任意标量 oracle** 上（不只时序）。
`case.py` 的 `ComputationCase` schema 基本沿用（加 `intent_family` 字段区分）。

**新组件：持仓合成器**（`portfolio_synth.py`）。持仓类没有"真实仓位"可取，要**确定性合成**一批
账户（含 ts_code/qty/avg_cost/last_price），喂 `portfolio_analytics` 算 gold。合成必须可复现
（固定种子由 case_id 派生，不用随机时钟）。

## 四、RL 训练级新要求（v1 没有的部分）

- **难度再平衡**：目标配额从「易 64%」压到 **易 ≤35% / 中 ≥40% / 难 ≥25%**（具体配额评审定）。
- **量级目标**：训练集 **~800–1500 道**跨意图；held-out 评估 **~200–300 道**。GRPO 每 prompt 多
  rollout 能省一些，但训练集必须远超现 141。
- **train/eval 拆分防泄漏**：**按股票池不相交**切（训练股 vs 评估股 disjoint）为主，辅以 as_of 隔离；
  **现 141 题并入 held-out**（gold 已钉死、可复现）。
- **奖励形态纪律**（承 RL pilot spec 第三节边界）：**只有 scalar / multi_scalar 进 RL 奖励**
  （纯程序判分）；**ranking / set 现靠 LLM 抽取判分，不进 reward**（引噪声、不可复现），留诊断/分析。
- **股票池扩充**：16 只 → **沪深300 子集 ~50–100 只**（多板块，够多样、cassette 量可控）。

## 五、oracle 策略（per family，全部 cassette 冻结）

| 家族 | oracle | 独立性 | 备注 |
|---|---|---|---|
| 时序计算 | `indicator_oracle`（numpy/pandas）从冻结真 tushare 价格算 | 独立（教科书定义，非抄被测代码） | 口径冻死：复权/对数vs简单/√252/ddof/分位 `<`vs`≤` |
| 快照取数 | **tushare daily_basic 字段本身** | 天然独立（tushare 算的 ≠ AI 算的） | 最干净一档；要给 trade_date |
| 财报取数 | **tushare fina_indicator 字段** 或两原值相除 | 天然独立 | 复用 `numerical_metric.py` 对账内核（±容差） |
| 估值算式 | `valuation_helpers`（compute_pe_value/compute_pb_value/ev_ebitda）纯函数 | 纯函数逐位可复现 | EV/EBITDA、WACC 须复用本仓经验系数（非教科书 CAPM） |
| 持仓组合 | `portfolio_analytics` 纯函数（权重/HHI/归因/TWR） | 纯算术/纯函数 | 输入=合成持仓 + 冻结价格 |

**铁律**：`mock-tushare` 是 LLM 伪造、非确定，**oracle 一律只能用真 tushare 值（cassette 固化）**，
不能用 mock。所有 oracle 真值在生成期落盘，runner/reward 阶段离线复现，零 live 网络。

## 六、分波实施（按 oracle 成本从低到高）

| 波 | 内容 | 为什么这个顺序 |
|---|---|---|
| **波 1：取数类** | 行情快照 + 财报取数；oracle = tushare 预算字段 + numerical_metric 对账内核 | 最便宜（oracle 基本现成，不用自己算）+ 最大覆盖增益，先验证生成器泛化架构 |
| **波 2：估值算式 + 时序难档** | PE/PB 理论价（valuation_helpers 现成）+ 时序的多票/长窗口难档 | 纯函数 oracle，工程量中等；补足 medium/hard |
| **波 3：持仓组合** | 持仓合成器 + portfolio_analytics 的权重/HHI/归因/TWR | 最难（要合成持仓状态 + 三层归因口径），放最后 |
| **波 4：量级 + 拆分 + 难度配额** | 扩股票池、跑到训练级量级、按配额平衡难度、切 train/eval | 前三波把"能出哪些题"铺齐后，最后统一调"出多少、怎么分" |

每波可各出独立 plan。波 1 跑通即可单独喂 RL pilot 的「量真基线」补意图维度。

## 七、明确不做（YAGNI）

- **DCF 全家不进可验证轨**：循环 oracle（标准答案只能照抄被测代码），见目录划掉理由。要进得先冻
  口径 + 建外部黄金集，本 spec 不做。
- **真实性闸第三层（裁判 + 流量对齐）不做**：仍无真实流量（承 v1）。
- **ranking / set 不进 RL 奖励**：LLM 抽取判分引噪声；留诊断。
- **大单资金净流向 / 估值一致性 CV 分级不做**：阈值主观或挂 DCF（目录已判确定性存疑）。
- **PE 历史分位**：归入波 2 时序难档（需 daily_basic 序列），非单独意图。

## 八、风险与阻塞

1. **持仓合成的真实性**：合成账户若不像真实持仓（权重畸形/标的不搭），题会失真。合成规则要带
   板块/权重合理性约束（类比 v1 的「相关仅同板块」realism gate）。
2. **cassette 覆盖扩张成本**：股票池 16→50–100 × 多接口（daily/daily_basic/fina_indicator）×
   多 as_of，cassette 量与固化工程显著增大；要批量预热 + 漂移告警。
3. **train/eval 泄漏**：按股票切分若某意图标的太少会失衡；切分逻辑要单测验证 disjoint。
4. **口径冻死**：时序/估值/归因的口径（复权、√252、经验系数、beta≈1 简化）必须冻进题面，否则
   agent 算对也被判错（承基线文档教训）。
5. **估值/归因的"循环 oracle"风险**：估值算式用 valuation_helpers 纯函数是合法独立 oracle，但若
   题目口径与被测代码完全同源，要警惕退化成"抄复印件"——估值类只取有教科书定义的 PE/PB，DCF 排除。

## 九、验收（v2 整体）

- 生成器能产出**五个意图家族**的 case，各家族 oracle 离线可复现、cassette 冻结、零 live 网络；
- 难度配额达标（易 ≤35% / 中 ≥40% / 难 ≥25%）；
- 训练集（~800–1500）与 held-out（~200–300，含原 141）**按股票 disjoint**，单测验证无泄漏；
- 奖励轨只含 scalar/multi_scalar；ranking/set 走诊断轨；
- 现有 eval 零回归；新增纯函数（各 oracle 派发 / 持仓合成 / 拆分逻辑）单测绿。
