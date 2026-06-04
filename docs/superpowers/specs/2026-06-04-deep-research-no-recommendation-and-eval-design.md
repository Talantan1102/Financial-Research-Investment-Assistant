# 深度研报「去推荐性」改造 + 评估体系激活 — 设计 spec

- 日期:2026-06-04
- 状态:待评审(本 spec 不含任何代码改动,仅决策 + task 拆分 + 影响清单)
- 关联:
  - 调研锚:`dashboard/data/reports/deep-research-report-eval.yaml`(深度研报评估 7 维 + benchmark)
  - 现有评估:`docs/claude-context/dd-report-eval-phase-1-landed.md` / `dd-report-eval-phase-2-landed.md`(⚠️ 后者"production_factory 用 SingleAgentPipeline fallback / V0≈V2"已**过时**,见 § 7)
  - 现有 SUT:`backend/app/orchestration/research_graph.py`(planner→collector→analyst→writer→critic)→ `InvestmentDueDiligenceReport`

---

## 1. 决策

**D1 — 深度研报不应有推荐性。** 报告从「投资尽调建议」重定位为「深度研究」:移除买卖评级、(作为建议的)目标价、建议仓位、止损位等 prescriptive 内容;**保留**估值区间(它值多少,作为分析结论)与多空双方论点(A5b 辩论,呈现两面、不下买卖结论)。

**D2 — 评估删除 M4 预测回测。** 报告不再做预测/推荐,M4(方向/目标价命中/风险预警回测)无评测对象,整把尺子下线。「5 把尺子 → 4 把尺子」(M1 引用 / M2 数值 / M3 风险配对 / M5 综合裁判)。

**D3 — 评估体系不重做,走"激活 + 补"。** 现有回测/消融/持久化基建扎实且已接真 SUT,只缺"喂活输入 + 跑 + 护栏";survey 7 维按"复用 / 借方法薄写 / 显式不做"分类推进,坚决不引 RAGAS/DeepEval/TruLens 框架。

### 决策依据(Why)

- **更贴主流。** survey 7 维里①忠实度②原子事实③引用④数值⑥裁判⑦RACE 全评*研究质量*,只有⑤预测是评*押注*。DeepResearch Bench / GAIA / RACE 等通用深度研究基准无一评投资预测。删 M4 让评估回到通用深度研究评估主航道,与调研中心对齐。
- **顺手解决最大 leak 头疼。** M4 是唯一需要"截止日之后真相"打分的尺子,正因它,历史线(2024-2025)裁判模型 cutoff≥2024"记得未来"才致命。删 M4 后,M1/M2/M3/M5 评的是"报告对其当时材料忠不忠实/准不准/全不全",与裁判是否知道后续涨跌基本无关 → **40 个 golden case 全部可用**(不再只有 8 个 sanity 能报真数),且 M4 的 anchor 注入与 `GroundTruthLoader` 整块消失。
- **诚实代价。** M4 是唯一"不靠 LLM 裁判、拿客观未来真相打分"的尺子。删后金融差异化主要靠 M2(数值 vs tushare 真值)+ 领域内容 + A5a 估值撑;A5b 辩论成为压轴。可接受,且更自洽(`DEFAULT_DISCLAIMER` 本就写"不构成投资建议或具体买卖指令")。

---

## 2. 报告侧改动(SUT)

### 2.1 §6 schema 去推荐版(草案)

`backend/app/agents/investment_dd_schema.py`,`InvestmentRecommendation` → 重命名 `InvestmentSynthesis`(「综合研判」)。

**移除字段(prescriptive):**
- `recommendation`(5 档评级)
- `recommended_position_size_pct`
- `recommended_holding_period`
- `recommended_entry_price_range`
- `recommended_stop_loss_price`
- `estimated_target_price_range` ← 作为"建议目标价"删;估值区间仍在 §3 `ValuationAnalysis`
- `position_management_conditions`

**保留 / 新增:**

```python
class InvestmentSynthesis(BaseModel):
    """§ 6 综合研判 — 陈列多空逻辑与估值背景,呈现两面、不下买卖结论。

    去推荐改造(2026-06-04):报告定位从"尽调建议"转为"深度研究";
    A5b 多空辩论成为本节主体。
    """

    model_config = ConfigDict(extra="ignore")

    narrative: str = Field(description="200-400 字综合研判:综合投资逻辑与估值背景,不给买卖评级/目标价")
    key_judgment_factors: list[str] = Field(
        default_factory=list,
        description="影响判断的关键变量(留给读者自行决策,非买卖指令)",
    )
    valuation_context: str | None = Field(
        default=None,
        description="呼应 §3 估值区间的研判,如'当前价位于内在价值区间下沿'(描述,非目标价建议)",
    )
    evidence: list[str] = Field(default_factory=list, description="引用 chunk_id 列表")

    # v1.x A5b: bull/bear debate(去推荐后为本节主体)
    bull_case: list[str] = Field(default_factory=list, max_length=5)
    bear_case: list[str] = Field(default_factory=list, max_length=5)
    strongest_bull_point: str | None = Field(default=None, max_length=300)
    strongest_bear_point: str | None = Field(default=None, max_length=300)
```

主 schema `InvestmentDueDiligenceReport`:字段 `investment_recommendation` → `investment_synthesis`(类型随改)。`target_close_price_at_gen` 保留为快照元数据(M4 删后非必需,但无害)。

> 备选(降 churn):保留字段名 `investment_recommendation` 仅改类内容——不推荐,语义误导。

### 2.2 §3 估值 — **不动**

`ValuationAnalysis`(A5a 多模型 cross-check:`pe_value/pb_value/dcf_base/bull/bear`、`valuation_consistency`、`outlier_diagnosis`)全部保留——"它值多少"是研究结论。A5a 算法深度完整保留。
- 注:`pe_historical_percentile_value` 注释标"(numeric for classify_recommendation)",其下游 `classify_recommendation` 将下线(见 2.4),字段可留作分析信息。

### 2.3 Writer / Renderer / Critic

- `backend/app/agents/writer.py`
  - `post_process_writer_output`(:581-599 + 推荐/辩论 update 逻辑 :625-665):删除写死评级 + 仓位的确定性覆盖逻辑;保留 A5a 估值覆盖 + A5b 辩论注入。
  - `build_investment_dd_prompt` §6 prompt 块(:407-491):从"给出评级/目标价/仓位"改写为"综合多空逻辑、陈列关键判断变量、不下买卖结论"。
  - `target_close_price_at_gen`(:313 prompt 写死 null):M4 删后无需回填,保持 null 即可(也可整段移除)。
- `backend/app/agents/investment_dd_renderer.py`:§6 渲染标题「投资建议」→「综合研判」,移除评级/目标价/仓位/止损渲染块,多空双方论点升为主体。
- `backend/app/agents/critic_subagents/input_context_scorer.py`(Critic 第6维 `input_context_appropriateness`):**重构不删**。删掉"仓位匹配风险偏好 / 持有期匹配 horizon"判定(随推荐消失);保留"研究重心是否贴合客户目标"(保守型多讲下行/风险、成长型多讲增长驱动)。客户画像输入(aum/objective/horizon/risk)仍保留,只是不再驱动仓位数字。
- A5b `dialectical_balance`(第8维)与 A5a `valuation_consistency`(第7维):**保留**。`dialectical_balance` 成为新定位的核心守卫(两面是否公平呈现)。

### 2.4 financial_research skill bundle — 推荐引擎下线

`backend/app/skills/financial_research/` 的推荐决策能力整体退役(这是一次真实的产品能力移除,非纯 schema 裁剪):
- `scripts/classify_recommendation.py` → 死代码(删)
- `scripts/compute_position_size.py` → 死代码(删)
- `references/recommendation_rules.yaml` → 删
- `methodology/decision_framework.md` → 删或改写为"研判框架(无买卖结论)"
- `SKILL.md` → 更新,移除推荐工具描述
- `backend/app/agents/schemas.py` / `app/skills/financial_research/__init__.py`:解除对上述脚本的注册/引用

---

## 3. 评估侧改动

### 3.1 删除 M4 链路

- `backend/eval/dd_report/metrics/prediction_metric.py` → 删
- `backend/eval/dd_report/golden/ground_truth_loader.py` → 删(仅 M4 使用)
- `backend/eval/dd_report/metrics/base.py`:`MetricInputs.ground_truth` 字段 → 移除
- `backend/eval/dd_report/metric_scores.py`:`BacktestMetricScores` 的 `m4_*` 字段 → 移除
- `backend/eval/dd_report/metrics/__init__.py`:注销 M4
- `backend/scripts/run_phase2_ablation_dogfood.py`:`MetricRegistry([...])` 去掉 M4
- `backend/eval/dd_report/backtest_runner.py`:去掉 m4 聚合 + `target_close_price_at_gen` 依赖
- `backend/eval/dd_report/ablation/null_adapters.py` `_minimal_stub` + `backend/tests/fixtures/investment_dd_fixtures.py`:按新 §6 schema 重建(去掉必填的推荐字段)

### 3.2 激活 4 尺子(P0,详见 § 4)

喂活 M1 `kb_lookup` 真查 + M2 真值(`fina_indicator`/`balancesheet`)+ vacuous 1.0→None + `request_id` 复合化 + leak 默认开扩扫。然后跑第一份 **4 尺子 × 40 case** 真矩阵。

---

## 4. 复用 vs 自建 路线图(M4 删除后)

| survey 维度 | 裁决 | 动作 |
|---|---|---|
| ③引用溯源(ALCE) | 复用 M1 + 升级 | 补 citation_recall 凑真 ALCE F1 |
| ④数值(GAIA硬匹配) | 复用 M2 + 补真值 | ROE/负债率接 `fina_indicator`/`balancesheet`(带 leak 防御新 endpoint) |
| ⑤预测回测 | ❌ **删除** | 产品无推荐性,无对象 |
| ⑥裁判+去偏(G-Eval) | 扩展 M5 | judge≠writer + 两档化 + 1 异源裁判 |
| ①忠实度(RAGAS) | 自建(借方法不引框架) | `claim_decompose` + 逐条判被 material 支撑 |
| ⑦报告级 RACE | 自建(最强叙事) | 对照参考研报 4 维相对打分 |
| ②原子事实核查 | ⚫ 显式不做 | 需自发联网核查,与 leak 防御冲突;最有用的"只核可核事实"被①的 verifiable 标签吸收 |
| ④检索质量(qrels) | 留口 → KB 子系统 | 但其"研报为何漏召回 chunk"属智能体层属性,spec 留对口位 |

### 实施阶段

- **P0 · 地基(~2.5-3d,已比删 M4 前更轻)**:喂活 M1 kb_lookup + M2 真值;vacuous 1.0→None;`request_id=f'{case_id}:{variant}'`;`enable_leak_detection` 默认 True 且扩扫 key_metrics/evidence;跑 4 尺子 × 40 case 真矩阵落库,沉淀真实数字替换 TBD。e2e smoke + 重录 b1 cassette + `eval_regression_gate`(M5<6.0 / V0 不优于 V2 告警)。
- **P1 · 裁判去偏(~1.5d)**:`_judge_debias.py`(正反位置 + 两档化);`assert writer_model ∉ judge_models`;白名单加 1 异源裁判(⚠️ 不设为 CI 必需 secret);看板渲 V0-V3 矩阵 + 成本/延迟列(注:`judge_cost_cny/judge_latency_ms` 当前写死 0,需先接 usage 采集或标注"未采集")。
- **P2 · 算法深度自建(~3d)**:`FaithfulnessMetric`(claim_decompose + VeriScore verifiable 标签 + supported/contradicted)+ M1 ALCE recall 升级。一处拆分喂①③。
- **P3 · 报告级 + 元评估(压轴)**:`RaceMetric`(4 维 pairwise,**进 MetricRegistry+CI,非手动 CLI**)+ 8 份参考研报语料(⚠️ 唯一人工数据瓶颈,P0 即并行采集);`MetaEvalMetric`(judge vs 人工 Spearman + 重复方差 + ARES CI)+ 人工抽检采样(从 `unsupported_cites`/`wrong_values` 现成日志抽)。

---

## 5. 测试 / cassette 影响清单(blast radius)

**生产代码:** `investment_dd_schema.py` / `writer.py` / `investment_dd_renderer.py` / `critic_subagents/input_context_scorer.py` / `app/router/reports.py` / `app/router/research.py` / `app/agents/schemas.py` / `app/skills/financial_research/*`

**单元测试(需改):** `test_investment_dd_schema.py`、`test_writer_post_process.py`、`test_writer_field_mapping.py`、`test_investment_dd_renderer.py`、`test_writer_alert_mode.py`、`test_debate_schemas.py`、`test_classify_recommendation.py`(删)、`test_compute_position_size.py`(删)、`test_financial_research_loader.py`

**评估测试:** `test_prediction_metric.py`(删)、`test_ground_truth_loader.py`(删)、`test_metric_scores_schema.py`、`test_backtest_runner_metric_wire.py`、`test_pipeline_adapter.py`、`test_ablation_runner.py`

**集成:** `test_writer_investment_dd.py`、`test_analyst_valuation_integration.py`、`test_analyst_debate_integration.py`

**E2E / golden(本就 skip,顺势重录):** `test_b1_maotai_investment_dd_cassette.py` + 3 个 `b1_differential/*` + 对应 cassette(`test_b1_*_茅台.yaml`)+ `fixtures/llm_mocks/agent_decisions.yaml` + `fixtures/investment_dd_fixtures.py`

**结论:** 改 §6 schema 必带一轮 writer/critic hot-path 测试修复 + cassette 重录(重录需 Mac 真 LLM,见 `test_b1_diff_*.py:43-48`,Windows/WSL 做不完——外部依赖,需排期)。

---

## 6. 顺带要定的小决定(open questions)

1. **§6 命名**:`InvestmentSynthesis`「综合研判」(推荐,字段连改)vs 保留 `investment_recommendation` 字段名仅改内容(降 churn,语义误导)。
2. **`input_context_appropriateness` 第6维**:重构(推荐)vs 直接删。
3. **`target_close_price_at_gen`**:留作快照 vs 整段移除。
4. **financial_research skill 推荐脚本**:整删 vs 改写为"研判框架"(保留 decision_framework 叙事但去买卖结论)。

---

## 7. 顺带修正 / 安全

- **过时卡片**:`docs/claude-context/dd-report-eval-phase-2-landed.md` 的"production_factory 用 SingleAgentPipeline fallback(V0≈V2)/ 真接生产 ResearchAgent 推 user follow-up"已过时——核查 `backend/app/eval/dd_report_production_factory.py:329`,真 `build_research_graph`(5 agent + 7 scorer)已接,`run_phase2_ablation_dogfood.py:101` 已用;V0=真 graph、V2=SingleAgentPipeline、V3=NoOpCritic 均 by-design。建议更新该卡。
- **泄露密钥**:`docs/04-功能模块/deepresearch快速开始.md:15` 含疑似真 `DASHSCOPE_API_KEY`(已进 git,挂在 legacy `deep_research_v2` 上)。建议轮换 + 删文档明文。

---

## 8. 不做 / 留口

- ②原子事实核查(FActScore/SAFE 自发联网核查):不做,v1.x 接离线财报快照源再议。
- ④检索质量(qrels/recall@k/nDCG):划归 KB 子系统 v0.8 调优 spec,本轮留对口位。
- ⑤乐观偏差统计检验:随 M4 一并下线(且 n=8 统计功效近零)。
- 组合回测扣交易成本(Barber 2001):留口 v1.x。
- 跨厂商裁判完全去同源:单 provider 硬约束,只做 judge≠writer 弱去偏 + 1 异源裁判,`llm_swapper` docstring 诚实标注 caveat。
