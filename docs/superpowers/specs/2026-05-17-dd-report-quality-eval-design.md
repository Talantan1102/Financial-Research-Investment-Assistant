# InvestmentDueDiligenceReport 质量评估体系 — 设计文档

| 字段 | 值 |
|---|---|
| 版本 | v1.1-draft |
| 状态 | brainstorm 完成,待 user review → writing-plans |
| 起草日期 | 2026-05-17 |
| 关联 use case | B-1 InvestmentDueDiligenceReport(v0.8.4 ship) |
| 关联 spec | `2026-05-04-v0.8.4-b1-single-deep-design.md` / `2026-04-30-dev-test-loop-C-eval-trace-infra.md` / `2026-05-10-c5-cross-session-memory-design.md` § Plan 5 / `2026-05-14-harness-board-v2-polish-design.md` |
| 简历定位 | LLM 应用算法的核心评估模块 — 撑起"算法纵深"叙事 |

---

## § 1 背景与问题定义

### § 1.1 当前痛点

B-1 use case 在 v0.8.4 已 ship `InvestmentDueDiligenceReport`(6 sections × `evidence: list[str]` 字段已埋 chunk_id 引用)。但**报告产出质量的判断完全靠肉眼**:

- 没有系统化打分机制 — 改 prompt / agent / RAG retrieval 后无法回归对比
- evidence 字段允许空,Critic factuality scorer 扣分但**没有 systematic citation precision/recall**
- 没有跟工业公开 benchmark 对标的数字(FinanceBench / Hebbia 等)
- 投资建议、目标价、风险 flag 这些**可证伪的预测**没有 ground truth 验证
- 改进无方向 — "报告变好了"没法量化证明

### § 1.2 为什么现在做

1. **B-1 use case 已 ship**:有完整 InvestmentDueDiligenceReport schema 作评估对象
2. **现有 eval infra 可复用**:`EvalRecorder` / `EvalResult` / `TraceService` / `EvalRunner` 五件契约已沉淀(Plan C)
3. **求职作品定位需要算法纵深**:user_portfolio_target 明确要求 LLM 算法 + 应用设计技术深度,评估体系是 LLM 应用算法的必备一环
4. **未来 use case 复用**:做这套体系也给后续 C-3 全市场扫描 / C-5 跨用户场景的 eval 留通用范式

### § 1.3 v1.x roadmap 定位

定位为 **核心算法模块** — 跟 c5 cross-session memory 同级别的"非平凡决策含量"模块。不是工具页,不是 utility。

---

## § 2 业界做法调研(2026-05-16 web research)

### § 2.1 5 业态评估流程对比

| 业态 | 审稿人 | 关键评判点 | 文档化 |
|---|---|---|---|
| VC 早期 | 投委会 (IC) | conviction 是否 stress-tested、风险是否配对 mitigation | 模板化但**反 checklist** — 太 checklist 化反而打回 |
| PE 控股 | IC + 外部 CDD + 财务 DD + 法律 DD | QoE 数字 reconcile、synergy 假设有 expert call 支撑 | 高,红旗 register 必备 |
| 投行 M&A | MD/Partner | **88-文档 checklist 文化最强** | 极高 |
| 四大财务 DD | EQR (独立 partner peer review) | **每个数字 trace 到 source**(合同/总账/银行流水) | 行业最高 |
| 中国券商投行 | 项目组→质控部→内核委员会,证监会现场检查 | 《保荐人尽职调查工作准则》强制底稿三段式 | 监管硬约束 |

**核心观察**:监管定义的"质量" ≠ 结论对错,而是 **程序合规 + 底稿可追溯**。对算法评估的启示:**citation/evidence 是跨业态共识的第一支柱**。

### § 2.2 工业 LLM eval benchmark 可对标的 3 个

| 厂商 / 项目 | 公开 dataset? | 可跑性 | 我们的处理 |
|---|---|---|---|
| **FinanceBench** (Patronus AI, MIT, 10231 SEC QA) | ✓ 英文 SEC + evidence string | **部分** — 原 dataset 英文,跟我们中文 KB corpus 失配 | Phase 4 **自建 ~50 case 中文版**(QA 结构 + 容差判分方法对齐原 paper),报告我们 pipeline 的绝对数字 — **不打榜**,corpus 不同不可比 |
| **Hebbia Financial AI Benchmark** | ✗ 商业内部 600+ task | **不能** — 没 dataset | 只**借鉴方法论**:三段式 extraction/summarization/reasoning + multi-LLM consensus("who evaluates the evaluator") |
| **JurisTech 2026 Hallucination Benchmark** | ✗ 厂商 blog 报告 | **不能** — 没 dataset | 只**借鉴指标视角**:incomplete-source 下 fabrication 率,M1 citation + M2 numerical 设计参考 |

**关键结论**:**3 个 benchmark 都不能直接"打榜对比"** — FinanceBench 不同 corpus,后两者无公开 dataset。我们能拿出来的"做得多好"证据靠的是**内部三维对比**(§ 4.7-4.8):ablation / 版本迭代 / cross-LLM。

### § 2.3 关键学术 / 监管基线

- 学术:DD report quality "incomplete, unreliable, of poor quality"(supply chain DD 文献综述)— 无 generally accepted measurement,**反过来说明做这套有空间**
- 监管:中国证监会《保荐人尽职调查工作准则》(2022) + 《工作底稿指引》强制底稿三段式 + 流程留痕。我们的 `trace_service` 已经在做类似事

### § 2.4 关键数字(对设计的硬约束)

- Finance 域 LLM hallucination 率 **41%**(JurisTech 2026)
- FinanceBench GPT-4-Turbo + RAG **81% 错或拒答**
- → **M1 citation + M2 numerical 必须做,且代价低、信号强**

---

## § 3 设计目标 + 边界

### § 3.1 In scope

| # | 模块 | 算法亮点 |
|---|---|---|
| 1 | **5 个 metric 集**(M1-M5,对齐 Hebbia 三段式) | citation 算法 / numerical fact-check / risk-mitigation pairing / backtest prediction / multi-LLM judge |
| 2 | **Pipeline-as-SUT backtest 框架** | 32 case × 3 LLM cross-check,leak-free 绝对数字 + 生产模型 sanity 副线趋同验证 |
| 3 | **内部三维对比**(量化"做得多好") | (a) **Ablation**:无 RAG / 无 multi-agent / 无 Critic — 量化每个组件贡献;(b) **版本迭代**:每次 backtest run 带 git_sha,dashboard 趋势线;(c) **Cross-LLM**:同 pipeline × N 个 LLM 矩阵 |
| 4 | **FinanceBench 中文子集**(reference 数字,**不打榜**) | 自建 ~50 case 中文版,方法论参照 FinanceBench;输出我们 pipeline 绝对数字作 reference |
| 5 | **Eval Dashboard**(harness-board § 07) | Hebbia 三段式骨架 + drill-down 详情 + 趋势线 + ablation 矩阵 + cross-LLM 矩阵,产品级 frontend |

### § 3.2 Out of scope(显式不做)

- 跨业态 rubric(VC / PE / 投行 / 银行四套独立 rubric)— 形态 3 抽象,Product-first 原则推迟
- 跨 use case 通用框架(C-3 全市场扫描 / 行业研究 eval 复用)— 第 2 个 use case 真撞上来再抽
- **投后真实回填**(等 3-6 月被动累积)— 跟 c5 Plan 5 posterior calibration runner 共用底座,但 v1.x 不主动 push
- **横向打榜对比**(vs TradingAgents / FinRobot / 等开源项目)— use case 错位 + 工业 reviewer 关注"组件贡献量化"而非"打榜赢",改用 ablation 替代
- 人工 conviction rating UI — dogfood 阶段如果需要再加

### § 3.3 简历叙事三支柱

| # | 支柱 | 工业对标 |
|---|---|---|
| 1 | **Pipeline-as-SUT backtest** — 评估的是 pipeline 不是 LLM,生产模型 swap 评估模型,leak-free | quant 圈 walk-forward backtest 范式 |
| 2 | **Hebbia 三段式 + multi-LLM consensus judge** — extraction/summarization/reasoning 分层,不是一锅 judge | Hebbia "who evaluates the evaluator" |
| 3 | **内部三维对比量化组件贡献** — Ablation(无 RAG / 无 multi-agent / 无 Critic)+ 版本迭代 git_sha 趋势 + Cross-LLM 模型矩阵,不靠外部打榜,靠控制变量内部数字 | 控制实验 + 工业 ML 工程严谨度 |

---

## § 4 核心算法设计(非平凡决策)

### § 4.1 决策 1:Pipeline-as-SUT backtest 框架

**问题陈述**:用历史时点数据生成报告 + 用之后真实数据验证,会被 LLM 训练 cutoff 污染 — 生产模型 deepseek-v4-flash cutoff **2026-04**,LLM "记得" 2024-2025 的市场实际表现,backtest 数字虚高。

**业界 alternatives**:

| 方案 | 做法 | 数据干净度 | 落地难度 |
|---|---|---|---|
| (a) **同模型 + prompt 锚定** | prompt 强制"只用工具数据" + ablation 测试 | 不可证伪,弱 | 简单 |
| (b) **cutoff-after 窗口** | 用生产模型在 cutoff 后窗口跑 backtest | 干净 | 简单但 **窗口太短**(今天 cutoff-after 只有 ~20 天) |
| (c) **swap 老 cutoff 模型做评估** | OpenRouter 接 GPT-4o-2024-05 / Qwen2.5-72B / DeepSeek-V3 跑同一 pipeline | 干净 | 中等(LLM swap + 跨 LLM 差异说明) |
| (d) **(b) + (c) 双轨** | 主线 (c) 大样本,副线 (b) 短窗口 sanity check | 最干净 | 工程量大 |

**Tradeoff matrix**:

| 方案 | leak-free | 样本量 | 反映生产? | 简历叙事强度 |
|---|---|---|---|---|
| (a) | ✗ | 不限 | ✓ | 弱 |
| (b) | ✓(窗口内) | 极小(~20 天 1-2 公司可验证) | ✓ | 中 |
| (c) | ✓ | 大(32+) | ✗(LLM 不同) | 强(quant walk-forward 范式) |
| (d) | ✓ | 大 + 小校验 | 部分 | **最强** |

**我们的选择**:**(d) 双轨**。理由:

1. **核心 framing**:**backtest 评估的是 pipeline(RAG + agent + prompt + tool),LLM 是 swap-in 组件**。这个 framing 让方案 (c) 完全合法 — "我们 backtest 的是 pipeline 质量,生产 LLM swap 评估 LLM 在工业 quant 圈是标准操作"
2. **副线 (b)** 提供与生产模型趋同性证明 — 解决 (c) 的"用的不是生产模型"质疑
3. **滚动窗口**:随时间推移,cutoff-after 窗口自然拉长(半年→ 6 月,一年→ 12 月),长期收敛到完整生产模型 backtest

**评估方法**:

- Backtest 主线 32 case 跑出 metric 数字
- Sanity check 副线 8 case 跑同样 metric
- 验证标准:**sanity 副线在各 metric 上不显著低于 backtest 基准的 90%**(若低于则报警 — 可能 LLM swap 选错了,或 pipeline 实际质量虚高)
- 长期(6/12 月后)用生产模型在拉长窗口跑全量,与 backtest 主线做最终一致性对照

**Caveat 必须在 spec / README / 简历讲清楚**:

> "因 LLM cutoff 限制无法直接用生产模型做大样本 leak-free backtest,采用 Pipeline-as-SUT 评估范式 — evaluation 用 cutoff < 2024 的 3 个 LLM cross-check,生产模型在 cutoff-after 窗口做 sanity 趋同验证。此承认局限并工程化处理的姿势,是个人项目中能做到的最干净 backtest 设计。"

### § 4.2 决策 2:Hebbia 三段式 metric 分层

**问题陈述**:整篇 LLM-as-judge 一锅打分 → 信号弱、不可解释、judge 自己也 hallucinate(meta-eval 问题)。

**业界 alternatives**:

| 方案 | 做法 | 信号 / 可解释性 |
|---|---|---|
| (a) 单 judge 整篇打分 | 一个 LLM 看完整报告打 1-10 分 | 弱、不可解释 |
| (b) Rubric-based 多维 judge | LLM 按 rubric 5-10 维打分 | 中等,但仍依赖 LLM |
| (c) **Hebbia 三段式 + 程序化 + LLM judge 混合** | extraction(程序化为主)/ summarization(LLM judge)/ reasoning(backtest + multi-LLM consensus) | 强,可解释,**每段用最合适方法** |

**选 (c)**。5 个 metric 分配:

| # | Metric | 段位 | 算法 | Ground truth |
|---|---|---|---|---|
| **M1** | **Citation precision/recall** | extraction | 程序化:对每条声明的 evidence chunk_id,做 chunk lookup(存在性)+ 小 LLM judge 判 "chunk 内容 supports/not_supports 该声明" | KB 真实 chunk 库 |
| **M2** | **Numerical accuracy** | extraction | 程序化:regex 抽数字 + tushare 真实值对比,容差 ±1% | tushare 真实财务数据 |
| **M3** | **Risk-mitigation pairing** | summarization | LLM judge(单 judge,小 model): RiskItem.mitigations 是否非空 + mitigation 是否真能缓释 | LLM judge 共识 + 抽样人审 |
| **M4** | **Investment prediction accuracy** | reasoning | 程序化:投资建议方向 + 目标价区间 vs 后续 1/3/6/12 月真实股价 + 风险 flag 真实发生率 | tushare 后续股价 + 真实公告 |
| **M5** | **Composite quality**(Hebbia "who evaluates the evaluator")| reasoning | Multi-LLM judge:GPT-4o + Qwen2.5-Plus + DeepSeek-V3 各打 1-10 分,majority 取共识,disagreement 单独记录审计 | 跨 LLM consensus |

**关键设计**:

- M1+M2 程序化为主 → **客观、可重复、无 LLM judge 自己 hallucinate 问题**
- M3 用 LLM judge → 难程序化,小 model + 抽样人审做 sanity
- M4 是 backtest 主菜 → **客观最强**,但要小心 LLM leakage(决策 1 已处理)
- M5 是软维度兜底 → multi-LLM consensus 解决 single judge bias

**为什么是 5 个不是 3 个或 10 个**:

- 3 个太少 — citation/numerical/prediction 三个客观维度都没了
- 10 个太多 — 维度爆炸、解释成本高、互相 overlap、单维度信号弱
- 5 个 = Hebbia 三段式 × 多种算法范式(程序化 / 小 judge / multi-LLM)的最小完整集

### § 4.3 决策 3:Multi-LLM consensus judge(M5)细节

**问题陈述**:M5 用单 LLM judge → judge bias、judge model 训练分布偏移、不可证伪。

**业界 alternatives**:

| 方案 | 做法 | 缺陷 |
|---|---|---|
| (a) Single judge LLM | GPT-4 一个 model 打分 | judge bias、不可证伪 |
| (b) Pair-wise comparison | 报告 A vs 报告 B 让 LLM 选,Bradley-Terry 排名 | 需要 reference 报告对照,样本量爆炸 |
| (c) **Multi-LLM majority** | 3+ LLM 各打分,majority vote | Hebbia 范式 |
| (d) Human rating | 人审 | 慢、贵、个人项目不可持续 |

**选 (c)**。具体:

- 3 个 judge LLM:**GPT-4o-2024-05 / Qwen2.5-72B-Instruct / DeepSeek-V3**(跨厂商 + 跨训练分布)
- 1-10 打分 + 必须给 reasoning(让 LLM 解释为什么打这个分)
- **Disagreement 处理**:
  - 3 个分差 ≤ 2 → 取平均,正常 case
  - 3 个分差 > 2 → 标记 disagreement,导出到单独 audit list
  - 一致 ≤ 4 → 标记 low-quality case,push 到 dogfood loop
- **可重复性**:同 case 跑 3 次,验证 majority 决策稳定性 > 80%(< 80% 则换更大 model 或加 reasoning chain)

### § 4.4 决策 4:Golden case 选股 + 时点设计

**问题陈述**:backtest 选股不当 → 幸存者偏差(只选大白马),metric 数字虚高且不可信。

**选股原则**:覆盖收益分布全部象限,**必须包含暴雷/退市样本**(测系统是否能提前 flag)。

**8 公司选股**:

| # | 公司 | ts_code | 类型 | 入选理由 |
|---|---|---|---|---|
| 1 | 贵州茅台 | 600519.SH | 大白马稳健 | 基线,LLM 知识最熟,测最容易 case |
| 2 | 宁德时代 | 300750.SZ | 成长龙头(高波动) | 业绩起伏大,测 prediction 难度 |
| 3 | 中国神华 | 601088.SH | 周期股 | 周期翻转,测能否识别 cycle |
| 4 | 海航控股 | 600221.SH | 困境反转 | 测能否识别真实困境 |
| 5 | **康美药业** | 600518.SH | **暴雷/退市样本** | **关键 — 测系统是否提前 flag 财务造假** |
| 6 | 招商银行 | 600036.SH | 银行金融 | schema 特殊(资产负债结构) |
| 7 | 恒瑞医药 | 600276.SH | 医药 | 行业政策影响大 |
| 8 | 海康威视 | 002415.SZ | 科技 | 国际制裁因素 |

**4 时点**:2024-06-30 / 2024-12-31 / 2025-06-30 / 2025-12-31(中报/年报 ann_date 后 2 周,确保数据 available)。

**32 backtest case + 8 sanity case** = **2026-04-30 时点跑 8 公司**(生产模型在 cutoff-after 窗口的 sanity check)。

**Ground truth 数据源**:

- 后续股价:tushare `daily` 接口(已接,见 v0.8.3)
- 真实公告:tushare `disclosure` / `anns` 接口
- 财务真实值:tushare `income` / `balancesheet` / `cashflow` / `fina_indicator`
- **退市/暴雷 case**:康美 ann_date 完整数据可能滞后,需 spec 实施前 spike 验证可用性

### § 4.5 决策 5:Time-travel 数据控制

**问题陈述**:backtest 生成报告时,模型只能看 ≤ cut-off 数据 — 数据 leak 整个 backtest 报废。

**关键工业难题**:

| 数据源 | leak 风险 | 处理 |
|---|---|---|
| tushare 财务 | 中 | 按 `ann_date <= cut_off` 严格过滤(接口本身支持) |
| KB 文档(chunk) | 高 | ingest 时打 `publish_date` 元数据 → 检索时 filter |
| Bocha 新闻 | 中 | 按时间过滤(目前用 mock,真生产需 backend 改造) |
| **LLM 知识本身** | **极高** | 用 Pipeline-as-SUT swap 老模型(决策 1 已处理) |
| 公告/research notes | 中 | 同 KB,按 publish_date filter |

**实施细节**:

- `BacktestRunner` 必须接受 `cut_off_date` 参数,**所有下游 tool 调用一律带 `cut_off_date` filter**
- 添加 **leak detector**(integration test):跑 backtest 时把 KB chunk publish_date / tushare ann_date / Bocha 时间戳 dump 到 trace,**任何 > cut_off_date 的记录都让 test fail**
- KB schema 需要补 `publish_date` 字段(目前可能没有 → spec 实施 Phase 1 第一周确认)

### § 4.6 决策 6:与 c5 Plan 5 posterior calibration runner 共用底座

**问题陈述**:本 spec 副线 (b) 的"生产模型 cutoff-after sanity check",本质是 posterior calibration(模型预测 vs 后续真实)。c5 Plan 5 已经做过类似 calibration runner(`chat_memory_calibration_runs` audit job + posterior calibration weekly job),不该重复造轮子。

**共用方式**:

- **复用模式而非代码**:c5 Plan 5 已有 `chat_memory_calibration_runs` audit 表 + posterior calibration weekly job pattern,但代码上是否抽出 `CalibrationRunner` 基类未确认(grep 未找到该类名)
- **Phase 3 实施时两个路径选一**:
  - (a) 若 c5 Plan 5 已有可复用 base → 继承 `DDReportCalibrationRunner(继承 base)` + 写 `dd_report_calibration_runs` audit 表
  - (b) 若 c5 Plan 5 是 ad-hoc 实现 → 新建 `dd_report_calibration_runner.py`,同时**顺便抽出** `BaseCalibrationRunner`(若 abstraction 自然),让 c5 / dd_report 共用 — 但不强制 c5 重构,只留口
- 长期 backtest 验证(6/12 月窗口拉长)也走同一 runner,自动 trigger

**Trade-off**:c5 Plan 5 calibration 是为 memory injection classifier 设计,可能 abstraction leak — Phase 3 实施时不预判,以代码为准。

### § 4.7 决策 7:Ablation 变体设计(组件贡献量化)

**问题陈述**:外部横向对比(vs TradingAgents / FinRobot 等)use case 错位且 reviewer 关心的"组件贡献"答不上来。需要**控制变量**方式量化我们 pipeline 每个组件的实际贡献。

**业界 alternatives**:

| 方案 | 做法 | 信号强度 |
|---|---|---|
| (a) 横向打榜 | vs 开源同类项目跑同 case | use case 错位时数字噪音大 |
| (b) **Ablation 控制变量** | 拿掉 / 替换 pipeline 一个组件,跑同 case,数字差 = 该组件贡献 | **最强** — 控制变量,reviewer 直接信服 |
| (c) 跨时间内部对比 | 不同版本 metric 提升(决策 8 处理) | 进步叙事 |

选 **(b)**(决策 7)+ (c)(决策 8 处理)。

**4 个 Ablation 变体**:

| # | 变体 | 拿掉什么 / 替换什么 | 量化什么 |
|---|---|---|---|
| **V0 baseline** | 完整 pipeline | 5 metric 基线数字 |
| **V1 无 RAG** | RAG 检索 → 替换为 LLM 直接生成(无外部知识) | M1 citation / M2 numerical 的 RAG 增益 |
| **V2 无 multi-agent** | 5 agent → 合并成单 prompt(单 LLM 一次性出全报告) | M4 prediction / M5 composite 的 multi-agent 编排增益 |
| **V3 无 Critic 不 retry** | 拿掉 critic 反思循环(直接采纳 writer 首版) | M3 risk-pairing / M5 composite 的 critic 增益 |

**关键设计**:

- **Ablation 变体复用同一 backtest 框架** — `BacktestRunner` 接受 `ablation_variant` 参数,内部按变体名 swap pipeline 组件
- **跑的是同 32 case + 同 3 evaluator LLM** — 总 cost = 4 变体 × 之前 backtest cost ≈ 4 × $5 = $20/完整 ablation run
- **结果存进 `ablation_results` 表**(或扩 `backtest_runs.ablation_variant` 字段),dashboard 出对比矩阵

**实施位置**:Phase 2 metric 实现完成后,Phase 2 末尾跑一次完整 ablation(4 变体 × 32 case × 3 LLM cross-check)。

**简历叙事样本**(待真跑出数据后填):

> "Ablation 显示:RAG 让 M1 citation 从 X% → Y%(+Z pp),multi-agent 让 M4 prediction 从 X% → Y%(+Z pp),Critic 让 M3 risk-pairing 从 X% → Y%(+Z pp)。每个 pipeline 组件的贡献都被定量证伪。"

### § 4.8 决策 8:版本迭代趋势 + Cross-LLM 矩阵

**问题陈述**:除了"组件贡献"还需要回答两个问题 — (a) 我们 v1.x 实施过程中的迭代是否真的让 metric 提升?(b) 同一 pipeline 在不同 LLM 上的表现差异有多大?

#### § 4.8.1 版本迭代趋势

**做法**:

- 每次 `BacktestRunner` 跑完后,把 `git_sha` 写进 `backtest_runs.git_sha` 字段
- Dashboard 顶部 KPI 下方加**趋势线 panel**:M1-M5 按 `git_sha` + `created_at` 排序的折线图
- 简历叙事样本:"v1.x 实施过程 10 次迭代,M4 prediction 从 v0.8.4 的 X% → v1.x 末的 Y%(+Z pp)"

**关键工程**:

- **不强求跑历史 checkout**(v0.8.4 之前没 InvestmentDueDiligenceReport schema,跑不了)
- **从 v1.x Phase 2 起开始累积** — 每次 ablation run / 每次 prompt 迭代 / 每次 agent 改造完成 = 一次 backtest run
- Dashboard 折线图本质是"v1.x 实施过程的自我迭代曲线"

#### § 4.8.2 Cross-LLM 矩阵

**做法**:

- `LLMSwapper` 扩展 model list,加生产 deepseek-v4-flash 进 cross-LLM 横评(不进 backtest 主线)
- 同一套 32 case 跑 N 个 LLM,出 metric 矩阵
- N 的候选:
  - GPT-4o-2024-05(已在 backtest 主线)
  - Qwen2.5-72B-Instruct(已在 backtest 主线)
  - DeepSeek-V3(已在 backtest 主线)
  - **deepseek-v4-flash 生产模型**(新加,2026-04 cutoff)
  - Claude 3.5 Sonnet 或 Claude Sonnet 4(可选)
  - GPT-4-Turbo 或 GPT-4o-mini(可选)
- 重点:**生产模型必须进矩阵**,才能回答"生产实际跑出来跟 backtest 基准差多少"

**关键 caveat**:

- 加入生产模型(cutoff 2026-04)跑 2024-2025 backtest case 会有 leakage
- 解决:**Cross-LLM 矩阵只跑 sanity case(2026-04-30 cutoff 时点 8 case)**,backtest 主线仍用 3 cutoff < 2024 LLM
- 矩阵存进 `cross_llm_results` 表(或扩 `backtest_runs` 加 `llm_model` 字段)

**简历叙事样本**:

> "Cross-LLM 矩阵显示:在 sanity 8 case 上,生产 deepseek-v4-flash 的 M4 prediction 为 X%,GPT-4o-2024-05 为 Y%,Claude 4 Sonnet 为 Z% — 我们 pipeline 对 LLM 的依赖度量化为 (max - min) / mean = W%。"

---

## § 5 系统架构

### § 5.1 模块拆分

```
backend/eval/                   # 已有 — 跟 backend/eval/memory/ 同级
├── memory/                     # 已有(c5)
└── dd_report/                  # 新
    ├── __init__.py
    ├── backtest_runner.py      # 新 — time-travel data 控制 + 多 LLM swap orchestration
    ├── metrics/                # 新
    │   ├── __init__.py
    │   ├── base.py             # Metric Protocol(name / compute(report, case) -> MetricScore)
    │   ├── citation_metric.py  # M1
    │   ├── numerical_metric.py # M2
    │   ├── risk_pairing_metric.py  # M3
    │   ├── prediction_metric.py    # M4
    │   └── composite_judge.py  # M5(multi-LLM consensus)
    ├── golden/
    │   └── backtest_cases.jsonl    # 32 backtest + 8 sanity case
    ├── financebench_zh/        # 新 — Phase 4 单独
    │   ├── adapter.py          # 中文子集加载
    │   └── runner.py           # 单次 baseline 跑分,出 markdown report
    └── calibration/            # 新 — 跟 c5 calibration 共用 pattern(若有)
        └── dd_report_calibration_runner.py
```

### § 5.2 复用与新建

**复用**(不动):

- `EvalRecorder` / `EvalResult` / `JudgeScores` — eval_results 表 schema 扩展即可
- `TraceService` — request_id JOIN 不变
- `EvalRunner` — backtest_runner 可包装 EvalRunner 或并列

**新建**:

- `BacktestRunner` — orchestrate (case load → cut_off setup → pipeline run with swapped LLM → metric compute → store)
- `MetricRegistry` — 5 个 metric 的注册 + 顺序执行
- `LLMSwapper` — OpenRouter 客户端封装,支持运行时 model 切换
- `LeakDetector` — integration test 用的 trace 审查工具

**DB schema 扩展**:

- `eval_results` 表加列:`backtest_run_id` `cut_off_date` `evaluator_llm` `case_type`(backtest / sanity / financebench / cross_llm)
- 新建 `backtest_runs` 表:`run_id` `created_at` `case_count` `metric_summary_json` `status` `git_sha`(决策 8 版本迭代) `ablation_variant`(决策 7 ablation,值:V0_baseline / V1_no_rag / V2_no_multi_agent / V3_no_critic) `llm_model`(决策 8 cross-LLM 矩阵)
- 新建 `dd_report_calibration_runs` 表(跟 c5 同 schema 风格)

### § 5.3 LLM swap 机制

- 通过 OpenRouter 接 GPT-4o-2024-05 / Qwen2.5-72B-Instruct / DeepSeek-V3(backtest 主线 evaluator)
- **Cross-LLM 矩阵扩展**(决策 8.2):加生产 deepseek-v4-flash + 可选 Claude Sonnet 4 + GPT-4-Turbo,仅跑 sanity 8 case 矩阵
- **Evaluator 隔离**:`LLMSwapper` 只在 `BacktestRunner` 使用,生产 chat/research path 不影响
- **成本估算**:
  - **完整 backtest**:32 case × 3 evaluator × 6 agent call ≈ 576 call × 4k token = **~2.3M token**,按 OpenRouter 价格 → **~$5/run** ≈ 35 RMB
  - **Ablation**(决策 7,4 变体):**~$20/完整 ablation run** ≈ 140 RMB
  - **Cross-LLM 矩阵**(决策 8.2,8 sanity case × N 个 model):**~$3-5/run** ≈ 20-35 RMB
  - 完整一轮 dogfood(backtest + ablation + cross-LLM) = **~$28/run** ≈ 200 RMB
- 单次可接受;Phase 5 dogfood 跑 5-10 轮 → ~1000-2000 RMB,在 cost budget 内

### § 5.4 FinanceBench 中文子集集成(reference 数字,**不打榜**)

- 上游 dataset 是 Patronus AI 英文 SEC QA(MIT license)— 跟我们中文 KB corpus 不匹配,**确定走自建路径**(不再 spike 选项)
- **自建 50 case 中文版**:从 tushare 公告 + 招股书 + 财报抽真实问题,QA 结构 + evidence string + 容差判分方法 **结构对齐** FinanceBench 原 paper
- **明确不可"打榜对比"**:corpus 不同,数字不可比。我们只报告自己 pipeline 在该 reference set 上的绝对数字
- 单次跑分,不进 production pipeline,输出 markdown report 进 `docs/eval-reports/`
- **简历叙事用法**:"参照 FinanceBench 方法论(QA + evidence + 容差判分)自建 50 case 中文 reference set,GPT-4o-2024-05 + 我们 RAG pipeline 在该 set 上 citation precision X%、numerical accuracy Y%"— 诚实建立 reference,不假打榜

---

## § 6 前端设计(产品级 quality)

### § 6.1 视觉语言

沿用 **harness-board V2 Quiet Workshop**(2026-05-14 ship):
- 主色:amber `#b8722a` × teal `#2a8e8e` 双强调
- typography:Newsreader / Source Han Serif 标题 + Manrope / Geist Mono 数据
- 留白:克制,大量 line-height 而非边框
- 不引入新 design system

### § 6.2 信息架构(C 骨架 + A drill-down)

```
[ harness-board § 07 — Eval Dashboard ]

┌─────────────────────────────────────────────────────────┐
│ TOP — Hebbia 三段式段位 KPI(横向三栏)                  │
│ ┌─────────────┬─────────────┬─────────────┐             │
│ │ EXTRACTION  │ SUMMARIZATION│ REASONING   │             │
│ │  93%        │  79%         │  72%        │             │
│ │ M1+M2 细分  │ M3 细分      │ M4+M5 细分  │             │
│ └─────────────┴─────────────┴─────────────┘             │
├─────────────────────────────────────────────────────────┤
│ MIDDLE — Case 列表(table, 32 backtest + 8 sanity)     │
│ ┌────┬───────┬──────────┬───────┬───────┬──────┬─────┐  │
│ │ #  │ 公司  │ 时点      │ Ext   │ Sum   │ Reas │ 综合 │
│ │ 01 │ 茅台  │ 2025-06  │ ●●●●○ │ ●●●○○ │ ●●●○○│ 0.82 │
│ │ 02 │ 宁德  │ 2025-06  │ ●●●●● │ ●●●○○ │ ●●○○○│ 0.74 │
│ │ ...│ ...   │ ...      │ ...   │ ...   │ ...  │ ...  │
│ └────┴───────┴──────────┴───────┴───────┴──────┴─────┘  │
│                                                          │
│ [Click 一行展开 detail panel]                            │
├─────────────────────────────────────────────────────────┤
│ BOTTOM(drill-down 详情,可折叠)                         │
│ ┌─ Selected: 茅台 · 2025-06 ──────────────────────────┐  │
│ │ M1 Citation: 24/26 = 92% │ failed cites: [...]    │  │
│ │ M2 Numeric:  18/20 = 90% │ wrong values: [...]    │  │
│ │ M3 Risk-Mit: 5/7 paired  │ unpaired flags: [...]  │  │
│ │ M4 Prediction: 目标价命中,风险 flag 1/2 真发生     │  │
│ │ M5 Judges: GPT-4o 8 · Qwen 7 · DSv3 7 → 7.3       │  │
│ │ ▶ View full report + trace                         │  │
│ └────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

side filter:[時點][Case type][LLM evaluator][score range]
```

### § 6.3 关键交互

- **跨段联动**:点击 case 行,三段 KPI 高亮该 case 在每段的贡献(highlight bar)
- **Trace JOIN**:每 case 详情面板有 "View trace" 按钮,跳转 `/runs/<request_id>` 看完整 agent trace
- **Sanity vs Backtest tab**:顶部 toggle 切换"backtest 主线 32 case" / "sanity 副线 8 case" / "合并"
- **趋同警报**:如果 sanity 副线低于 backtest 基准 90%,顶部红色 banner

### § 6.4 三段式之外的 3 个对比 panel(决策 7-8 可视化)

```
┌─────────────────────────────────────────────────────────┐
│ PANEL — 版本迭代趋势(决策 8.1)                          │
│ M1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 折线        │
│ M2 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 折线        │
│ M3-M5 ...                                                │
│ X 轴:git_sha (短) + created_at                          │
│ Y 轴:metric 数字                                         │
│ hover 显示该 commit 的 metric 详情 + 一行 commit message │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ PANEL — Ablation 对比矩阵(决策 7)                       │
│ ┌──────────┬───────┬───────┬───────┬───────┬───────┐    │
│ │ Variant  │  M1   │  M2   │  M3   │  M4   │  M5   │    │
│ │ V0 base  │  92%  │  91%  │  79%  │  72%  │  81%  │    │
│ │ V1 no RG │  45%  │  91%  │  78%  │  60%  │  68%  │    │
│ │ V2 no MA │  85%  │  84%  │  61%  │  58%  │  62%  │    │
│ │ V3 no Cr │  92%  │  91%  │  61%  │  72%  │  74%  │    │
│ └──────────┴───────┴───────┴───────┴───────┴───────┘    │
│ Δ 列高亮:RAG +47pp / MA +14pp / Cr +18pp 等             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ PANEL — Cross-LLM 矩阵(决策 8.2)                        │
│ ┌──────────────┬───────┬───────┬───────┬───────┬─────┐   │
│ │ Model        │  M1   │  M2   │  M3   │  M4   │ Avg │   │
│ │ DSv4-flash 生│  88%  │  90%  │  72%  │  68%  │ 80% │   │
│ │ GPT-4o-24-05 │  93%  │  92%  │  79%  │  73%  │ 84% │   │
│ │ Qwen2.5-72B  │  90%  │  89%  │  74%  │  70%  │ 81% │   │
│ │ DSv3         │  91%  │  88%  │  73%  │  70%  │ 81% │   │
│ │ Claude 4 Son │  92%  │  91%  │  77%  │  74%  │ 84% │   │
│ └──────────────┴───────┴───────┴───────┴───────┴─────┘   │
│ 量化"对 LLM 的依赖度":(max - min)/mean = W%             │
└─────────────────────────────────────────────────────────┘
```

数字均为示意 — 具体由 Phase 5 dogfood 跑出。

### § 6.5 SSE refresh pipeline 复用

harness-board V2 已有 5-step SSE refresh pipeline(2026-05-14 ship),eval dashboard 复用 — `BacktestRunner` 跑完后 emit `eval.updated` event,前端订阅自动刷新。

### § 6.6 视觉细节须 frontend-design skill 在 plan 阶段 polish

本 spec 只锁定信息架构 + 视觉基线,具体 mockup 高保真 + 交互细节 → plan 阶段调用 `frontend-design` skill 单独迭代。

---

## § 7 测试策略

### § 7.1 分层

- **L0 unit**:每个 metric 独立 unit test(给假报告 + 假 chunk → 验证 score)
- **L1 integration**:`BacktestRunner` 单 case 走通(mock tushare + mock KB)
- **L2 e2e**:`BacktestRunner` 跑 2 case full pipeline + 真 LLM(cassette 录制)
- **L2.5 leak detection**:integration test 跑 backtest,断言 trace 中所有数据时间戳 ≤ cut_off

### § 7.2 复用 fixture pattern

- 沿用 `feedback_pytest_layer_env` autouse fixture + monkeypatch.setenv
- 沿用 `pg-test-container-pattern`(若需要 PG;当前 eval 用 sqlite,不强需)
- LLM 测试沿用 cassette pattern(`feedback_cassette_dynamic_prompt_values` 教训:prompt 内的动态值要 strip)

### § 7.3 多 LLM judge 可重复性测试

新增专项 test:**同 case 跑 M5 共识 3 次,验证 majority 决策稳定 > 80%**。temperature=0 强制,如果仍 < 80%,说明 prompt 模糊或 model 能力不够,需迭代。

### § 7.4 Backtest 数据 leak detector

`tests/eval/test_leak_detector.py` — 跑 backtest with cut_off=2024-06-30,断言:
- 所有 tushare 调用 trace 中 `ann_date <= 2024-06-30`
- 所有 KB chunk trace 中 `publish_date <= 2024-06-30`
- 所有 LLM prompt 中**不出现** `> 2024-06-30` 的具体股价/事件(regex 扫描)

---

## § 8 工期估算(wall time, 假设 4-6 h/day)

| Phase | 内容 | 时长 |
|---|---|---|
| **Phase 1** | backtest infra: BacktestRunner + LLMSwapper + LeakDetector + Time-travel data control + golden case 32 个采集 + DB schema(`git_sha` / `ablation_variant` / `llm_model` 字段) | **1.5 周** |
| **Phase 2** | 5 个 metric 实现 + L0/L1 测试:M1 citation / M2 numerical / M3 risk-pairing / M4 prediction / M5 multi-LLM judge + **Phase 2 末跑 ablation V0-V3 完整一轮**(决策 7) | **1.5 周 + 1 天 ablation 跑分** |
| **Phase 3** | Sanity check 副线(8 case 跑生产模型) + eval dashboard frontend(harness-board § 07,frontend-design polish,三段式 + 趋势线 + ablation 矩阵 + cross-LLM 矩阵 4 个 panel) + SSE wire + **Cross-LLM 矩阵实际跑分**(决策 8.2) | **1 周 + 1 天 cross-LLM 跑分** |
| **Phase 4** | FinanceBench 中文子集自建 50 case + 跑分 + markdown report | **3-5 天** |
| **Phase 5** | dogfood:跑 5-10 轮全套(每轮 ~200 RMB),撞问题,记录 git_sha 进 backtest_runs 形成版本迭代趋势数据(决策 8.1),sediment 到 docs/claude-context + 简历叙事打磨 + README 同步 | **3-5 天** |
| **总计** | | **~4.7-5.7 周**(原 4.5-5.5 + ~1-1.5 天 ablation/cross-LLM 跑分) |

**关键工期假设**:

- Phase 1 第一周必须 spike:KB schema 是否已有 `publish_date`(若没有则需 reingest,加 0.5 周)
- Phase 1 第二周必须 spike:康美/康得新等暴雷 case tushare 后续数据是否完整(若不完整需换 case)
- Phase 4 spike 必须先做:FinanceBench 中文版本不存在则走"自建 50 case"路径,工期不变

---

## § 9 已知风险 + 未决问题

| # | 风险 | 缓解 |
|---|---|---|
| 1 | **LLM swap 后 pipeline 表现差异** — backtest 用的 GPT-4o-2024-05 跟生产 deepseek-v4-flash 能力不同,backtest 数字不能直接代表生产 | Sanity check 副线 + 趋同验证标准(90%);简历叙事明确 caveat |
| 2 | **32 case 样本量是否足够** — 统计 power 不足时数字置信度低 | Phase 5 dogfood 时算 confidence interval,若过宽则下版本扩到 64+ |
| 3 | **退市暴雷 case 数据完整性** — tushare 退市后数据可能缺 | Phase 1 spike 验证,缺则换案例(可加 *ST 长油 等) |
| 4 | **FinanceBench 中文子集存在性** | Phase 4 第一天 spike,不存在则自建 50 case |
| 5 | **KB chunk publish_date 缺失** | Phase 1 第一周 spike,缺则 reingest |
| 6 | **Multi-LLM judge cost** | 单次 ~35 RMB,weekly 一年 1750 RMB,可接受;Phase 3 加 cost guardrail |
| 7 | **dashboard 跟 harness-board 视觉漂移** | 沿用 V2 design token,frontend-design skill 在 plan 阶段强制 review |

---

## § 10 关联文档

### § 10.1 项目内

- B-1 use case spec:`2026-05-04-v0.8.4-b1-single-deep-design.md`
- Eval infra 五件契约:`2026-04-30-dev-test-loop-C-eval-trace-infra.md`
- c5 Plan 5 calibration:`2026-05-10-c5-cross-session-memory-design.md` § Plan 5
- Harness-board V2 视觉基线:`2026-05-14-harness-board-v2-polish-design.md`
- B-1 schema 文件:`backend/app/agents/investment_dd_schema.py`

### § 10.2 项目知识卡片(claude-context)

- 工作底稿规范同构:`docs/claude-context/c5-plan8-eval-tests-docs-done.md`(eval_runner CLI pattern 参考)
- Pipeline 评估范式:`docs/claude-context/v0.9-chat-c1c2-architecture.md`(LangGraph supervisor + Skill L1/L2/L3 pipeline)
- 测试 fixture:`docs/claude-context/test-db-layered-strategy.md` / `docs/claude-context/celery-redis-test-fixture-pattern.md`

### § 10.3 外部资料

- **FinanceBench**:[arXiv 2311.11944](https://arxiv.org/abs/2311.11944) / [GitHub MIT dataset](https://github.com/patronus-ai/financebench)
- **Hebbia**:[Financial AI Benchmark blog](https://www.hebbia.com/blog/which-model-will-give-me-the-edge) / [Who Evaluates the Evaluator](https://www.hebbia.com/blog/who-evaluates-the-evaluator-reaching-autonomous-consensus-on-agentic-outputs)
- **JurisTech 2026**:[Hallucination benchmark](https://juristech.net/best-llm-tools-for-financial-analysis-2026/)
- **FailSafeQA**:[Financial LLM benchmark analysis](https://ajithp.com/2025/02/15/failsafeqa-evaluating-ai-hallucinations-robustness-and-compliance-in-financial-llms/)
- **证监会底稿规范**:[保荐人尽职调查工作准则](http://www.csrc.gov.cn/csrc/c100028/c3048134/content.shtml) / [证券公司投资银行类业务内部控制指引](https://www.sse.com.cn/lawandrules/regulations/csrcannoun/c/10117407/files/44caa087f57449b7a409c6278052cc91.pdf)
- **LLM cutoff 数据**:[HaoooWang/llm-knowledge-cutoff-dates](https://github.com/HaoooWang/llm-knowledge-cutoff-dates)

---

## § 11 简历叙事样本(供 README / blog / 面试参考)

**短版(1 句)**:

> 为 InvestmentDueDiligenceReport 设计了基于 Hebbia 三段式 + Pipeline-as-SUT 范式的 backtest 评估体系,5 个 metric(citation / numerical / risk-pairing / prediction / multi-LLM consensus)分层评分,内部三维对比(Ablation + 版本迭代 + Cross-LLM)量化每个组件贡献,自建 FinanceBench 中文 reference set 报告绝对数字(不打榜)。

**中版(3 句)**:

> 我设计并实现了金融研究助手 v1.x 的尽调报告质量评估体系。算法上分三层:(1) **Pipeline-as-SUT backtest** — 评估的是 RAG + agent + prompt 整体 pipeline,LLM 是 swap-in 组件,用 cutoff < 2024 的 3 个 LLM(GPT-4o / Qwen2.5 / DeepSeek-V3)cross-check 跑 32 case 历史 backtest,leak-free;生产模型在 cutoff-after 窗口做 sanity 副线验证趋同。(2) **Hebbia 三段式 metric 分层** — extraction(citation precision + numerical accuracy 程序化)/ summarization(risk-mitigation pairing LLM judge)/ reasoning(投资 prediction backtest + multi-LLM consensus judge),不同段位用最合适的算法,而不是一锅 LLM-as-judge。(3) **内部三维对比量化组件贡献** — Ablation(无 RAG +X pp / 无 multi-agent +Y pp / 无 Critic +Z pp)+ 版本迭代趋势(git_sha 趋势线追踪 v1.x 迭代曲线)+ Cross-LLM 矩阵(8 case × 5 LLM 量化对 LLM 的依赖度),不靠外部打榜,靠控制变量内部数字 — 工业 LLM 应用算法 reviewer 关注的"组件贡献量化"直接答透。

**长版**:留 plan 阶段或 dogfood 完成后写 blog,基于真实跑出的数字。建议三段:(a) 为什么需要这个 eval — 业界 5 业态调研 + 3 个 benchmark 不可直接打榜的诚实评估;(b) 算法纵深 — Pipeline-as-SUT + Hebbia 三段式 + multi-LLM consensus 三个非平凡决策的 alternatives + tradeoff;(c) 量化"做得多好" — 内部三维对比真实数字 + caveat。

---

## § 12 版本与变更历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0-draft | 2026-05-17 | brainstorm 收口,所有决策点用 alternatives + tradeoff + 选择 + 评估方法的四件套写出 |
| v1.1-draft | 2026-05-17 | (a) § 2.2 benchmark 表加"可跑性"列,明确 3 个 benchmark 都不可直接打榜对比;(b) § 3.1 In scope 加内部三维对比;(c) § 3.2 Out of scope 加"横向打榜对比"(use case 错位);(d) § 3.3 简历叙事第 3 支柱重写为"内部三维对比";(e) § 4 加决策 7(Ablation 变体设计)+ 决策 8(版本迭代 + Cross-LLM 矩阵);(f) § 5 架构 — `backtest_runs` 加 `git_sha` / `ablation_variant` / `llm_model` 字段,LLMSwapper 扩 model list + cost 重算;(g) § 5.4 FinanceBench 明确"自建,不打榜";(h) § 6 dashboard 加版本趋势线 + ablation 矩阵 + cross-LLM 矩阵 3 个 panel;(i) § 8 工期微调 +1-1.5 天(原 4.5-5.5 → ~4.7-5.7 周);(j) § 11 简历叙事三版本重写,去掉"打榜"措辞,加内部三维对比叙事 |
