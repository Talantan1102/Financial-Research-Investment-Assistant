# 设计:反向出题机 MVP(计算类验证集生成器 + 数值判分器,一条端到端竖切)

- 日期:2026-06-17
- 体裁:验证集基建实施设计(承 dashboard 报告 `verification-question-gates` + `indicator_oracle`)
- related: dashboard/data/reports/verification-question-gates.yaml;backend/eval/indicator_oracle.py;docs/superpowers/specs/2026-06-16-computation-caliber-freeze-design.md

## 为什么

`verification-question-gates` 报告把"反向出题 + 难度闸 + 真实性闸"的方法论讲透了,但落地只有 6 道手挑题 + 一个删掉的临时 B-harness。要拿统计意义的 pass@k(喂 RL 决策),得把 6 道扩成上万道——这需要一台**反向出题机**(意图模板 + 股票池 + 合法配对 + 组合算子 → 题集)+ 一个**数值判分器**。

关键约束(探现有框架得出):`backend/eval/chatloop/` 的 `Scenario`/scorer 判的是**工具选择 + grounding**(调了哪些工具、有没有瞎编),**不判"数值答案 vs gold"**。所以反向出题要走**新轨**:新 case 类型(题面 + 数值/结构 gold + 容差)+ 新判分器,跟现有 scenario-eval 并行,只复用 `sut_runner` 跑真 agent 那一截。

## 范围:MVP = 一条端到端竖切

**做**:1 个意图(个股/配对研究)× 5 个 close 基指标 × 3 个窗口 × ~15 只手挑股 × 难度三档(含复杂档的组合算子层)× 数值/结构判分器,产 ~100–200 道真题、跑出按档/指标分桶的真 pass@k。

**MVP 内不做(各自留后续一刀)**:
- PE 分位(需 PE 历史 `get_daily_basic`,另一条数据路);
- 其它意图(持仓体检 / 风险评估);
- 规模化到沪深300 全市场(MVP 手挑 15 只);
- 真实性闸第三层(裁判 + 流量对齐,要真实流量);
- 完整 method-B 重算判分(MVP 用 canonical gold + 窗口 sanity;假错出现再上)。

## 架构:新模块 `backend/eval/question_gen/`

数据流:**生成器**(离线跑一次)产出题集 jsonl → **runner** 跑真 agent × k 次 → **judge** 判 → pass@k 汇总。

| 文件 | 责任 | 依赖 |
|---|---|---|
| `stock_pool.py` | 15 只手挑股(ts_code/名/板块),板块分组供同板块配对 | 无 |
| `legality.py` | 窗口定义(3m/1y/3y)+ 合法配对矩阵(指标×窗口) | 无 |
| `operators.py` | 组合算子层(架在 indicator_oracle 上):rank / filter / aggregate → 结构化 gold | indicator_oracle |
| `case.py` | `ComputationCase` schema + jsonl IO | 无 |
| `intents.py` | 意图模板(个股/配对研究):题面模板 + 每档的组合形状 | 无 |
| `generator.py` | 主循环:意图×股票×指标×窗口 → 取数 → 算 gold → 套题面 → ComputationCase | 上 5 个 + TushareService + window 动作 + indicator_oracle |
| `judge.py` | 按 gold_shape 解析答案 + 容差判(scalar/ranking/set)+ 窗口 sanity | 无(纯解析) |
| `runner.py` | 批量:复用 `eval.chatloop.sut_runner` 跑真 agent(注 reference_date)× k + judge + pass@k 汇总 | sut_runner + judge + case |

## 题集 schema:`ComputationCase`

```
case_id        str   如 "qg-涨幅-600519-1y-001"
intent         str   "stock_study"
difficulty     str   简单 / 中等 / 复杂
question       str   题面(中文)
stocks         list  [ts_code, ...](单股 1 个,配对 2 个,组合 3-5 个)
indicator      str   涨幅 / 回撤 / 波动 / 相关 / CAGR(组合题 = 主指标)
window         str   3m / 1y / 3y
gold           any   scalar=float;multi_scalar={label: float}(双指标);ranking=[[name, value], ...];set=[name, ...](可空)
gold_shape     str   scalar / multi_scalar / ranking / set
tolerance      dict  {kind: "rel"|"abs", value: float}(scalar);ranking/set 精确
meta           dict  {板块, window_dates:[start,end], as_of}
```

jsonl 落盘(`//` 注释行跳过,沿用 `scenario.load_scenarios` 风格);loader fail-loud + case_id 查重。

## 股票池(15 只,5 板块,每板块 ≥2 供同板块配对)

| 板块 | 标的 |
|---|---|
| 白酒 | 600519.SH 贵州茅台 / 000858.SZ 五粮液 / 000568.SZ 泸州老窖 / 002304.SZ 洋河股份 / 000596.SZ 古井贡酒 |
| 银行 | 600036.SH 招商银行 / 601398.SH 工商银行 / 000001.SZ 平安银行 |
| 新能源 | 002594.SZ 比亚迪 / 300750.SZ 宁德时代 / 002460.SZ 赣锋锂业 |
| 医药 | 600276.SH 恒瑞医药 / 300760.SZ 迈瑞医疗 |
| 电子 | 002475.SZ 立讯精密 / 000725.SZ 京东方A |

## 合法配对矩阵 + 窗口

窗口码(喂 `trade_cal` window 动作):`3m`=近三个月 / `1y`=近一年 / `3y`=近三年。

| 指标 | oracle 函数 | 合法窗口 | 理由 |
|---|---|---|---|
| 涨幅 | `interval_return` | 3m / 1y / 3y | 任意 |
| 回撤 | `max_drawdown` | 3m / 1y / 3y | 任意 |
| 波动 | `annual_volatility` | 3m / 1y / 3y | ≥3 月 |
| 相关 | `correlation` | 3m / 1y / 3y | ≥3 月;且**仅同板块两两配** |
| CAGR | `cagr` | **仅 3y** | 需 ≥2 年才有意义 |

## 意图模板 + 三档 + 组合算子

意图 `stock_study`(个股/配对研究)。题面模板(`{name}`/`{names}`/`{window_cn}` 填充;window_cn = 近三个月/近一年/近三年):

**简单档(`scalar`,拧 0 旋钮)** — 单股单指标:
- 涨幅:`"{name}最近{window_cn}涨了多少?"`
- 回撤:`"{name}最近{window_cn}的最大回撤是多少?"`
- 波动:`"{name}最近{window_cn}的年化波动率是多少?"`
- CAGR:`"{name}最近三年的复合年化收益率(CAGR)是多少?"`

**中等档(`scalar`,拧 1 旋钮)** — 单股双指标 / 同板块配对:
- 双指标(`multi_scalar`):`"{name}最近{window_cn}的最大回撤和年化波动率分别是多少?"`(gold = `{回撤: x, 波动: y}`,judge 对每个标签各比一次、全中才过)
- 相关:`"{name_a}和{name_b}最近{window_cn}的日收益率相关性是多少?"`

**复杂档(`ranking`/`set`,拧 2-3 旋钮)** — 多股 + 组合算子:
- 排序(`ranking`):`"{板块}板块这几只({names})里,最近{window_cn}涨幅最高的前三只是哪几只?"` → gold = 前三 `[[name, 涨幅], ...]`
- 筛选(`set`):`"{names} 这几只里,最近{window_cn}涨幅为正、且最大回撤小于20%的有哪几只?"` → gold = 满足的 `set`(可空集)
- 排序/筛选都在**单个 ≥3 只的板块内**出题(白酒5 / 银行3 / 新能源3;医药·电子各 2 只不够,不出复杂档)。

`operators.py`(确定性,架在 indicator_oracle 上):
- `rank_by(indicator, per_stock_data, window, top_k, descending=True)` → 有序 `[(name, value)]`;
- `filter_by(per_stock_data, predicates)` → 满足全部布尔条件的 name 集合(predicates 如 `涨幅>0`、`回撤<0.20`);
- `aggregate(indicator, per_stock_data, agg)` → scalar(MVP 暂不用,留接口)。

## 真实性闸(MVP 做前两层)

- **闸① 生成约束**:合法配对矩阵(上表)硬挡 CAGR×短窗口等;股票池就 15 只主流;相关/对比**仅同板块**配(`stock_pool` 的板块分组保证)。
- **闸② 意图锚定**:所有题从 `stock_study` 这个真实 job 实例化,不走裸笛卡尔积。
- 闸③(裁判 + 流量对齐)**不做**(本期无真实流量)。

## 判分器(MVP:canonical gold + 容差 + 窗口 sanity)

`judge.py` 按 `gold_shape` 解析 agent 答案文本:
- **scalar**:正则 `-?\d[\d,]*\.?\d*` 抓数(去千分位),命中 = `any(|num − gold| ≤ tol)`;%-指标按绝对值比(沿用 6 题 harness 口径)。
- **multi_scalar**(双指标):gold 的每个标签(回撤/波动)各按 scalar 规则判一次,全中才算过。
- **ranking**:按题面给的候选股名在答案里的**出现顺序**抽出有序名单,与 gold 的前 N 名次序精确比。
- **set**:在答案里抽"被判定满足"的股名集合,与 gold 集合精确比(**空集是合法答案**,如四只全跌→空)。

容差(承 caliber-freeze):涨幅/回撤 ±0.5%(相对)、相关 ±0.01(绝对)、波动 ±2%(相对)、CAGR ±1%(相对);ranking/set 精确。

**窗口 sanity**:从 trace 提 agent 的 get_daily args,窗口 ≠ canonical 则该 case 标 `window_mismatch`(不静默误判,计入诊断)。**完整 method-B 重算**(从 trace 提 agent 数据用 oracle 重算)留作硬化项——口径冻死 + window 动作让 canonical 已基本对齐(6 题 harness 实测 5/6 即证),假错冒头再上。

> ranking/set 的自由文本解析是已知难点:MVP 先用"股名 + 顺序/集合"正则;若实测解析不稳(漏名/误名),硬化方案是加一个 LLM 抽取器把答案抽成结构再比(判分器内可换,不动上游)。

## 批量 runner + pass@k

`runner.py` 复用 `eval.chatloop.sut_runner.run_scenarios` 的 in-process agent 驱动(`async with MCPClient.from_subprocess` + ToolLoop,修过 cancel-scope),但:
- 注入 `reference_date`(冻结 as-of,如 2026-06-17),让 agent 的"近一年"落到与生成时同一窗口;
- 每 case 跑 k 次(独立 request_id),交给 `judge` 判;
- 汇总 pass@1 / pass@k,按 difficulty × indicator 分桶输出(找战力断崖)。

## 确定性 / reproducibility

- 生成 + 跑分用同一个冻结 `as_of`(默认 2026-06-17);
- 生成时 `generator` 经 `TushareService`(real + 缓存)取数算 gold,窗口由 window 动作确定化 → gold 落盘后离线可复现;
- 纯函数(operators/legality/generator 的出题逻辑/judge 解析)零随机、零时钟。

## 测试

- **纯函数单测**:`operators`(rank/filter/aggregate 在手写 per-stock 数据上确定性输出)、`legality`(合法配对矩阵 + 非法组合被挡)、`case`(jsonl round-trip + 查重 + fail-loud)、`judge`(scalar/ranking/set 各正负例 + 空集 + 双指标 + 容差边界);
- **generator 离线单测**:喂 mock TushareService → 出 N 道 case,断言档位/合法性/gold_shape/同板块约束;
- **小 live 冒烟**(隔离栈或 sut_runner):生成 ~10 道(各档/指标覆盖)→ 跑真 agent → 出 pass@k,人工核 2-3 道判分对(不进 CI,手动)。

## 验收

- `python -m eval.question_gen.generator` 产出 ~100–200 道 jsonl,合法性/同板块/档位配额自洽;
- `judge` 对 6 题 harness 同款样例(茅台涨幅/相关/回撤波动/排序/筛选)判分与手工一致;
- runner 跑一小批出按 difficulty×indicator 分桶的 pass@k,复杂档(排序/筛选)能跑出 ranking/set 判分;
- 全部新增纯函数单测绿;现有 eval 零回归。

## 阶段(供 plan 拆)

1. 底座纯函数:`stock_pool` + `legality` + `case` schema + 单测;
2. `operators` 组合算子层 + 单测(架在 indicator_oracle 上);
3. `intents` 模板 + `generator` 主循环(mock 取数单测 + 真取数产题集);
4. `judge` 数值/结构判分 + 窗口 sanity + 单测;
5. `runner` 批量 + pass@k 汇总(复用 sut_runner)+ 小 live 冒烟;
6. 收尾:跑出 ~100–200 道的真 pass@k 分桶,记一张战力断崖快照。
