---
name: DD report eval Phase 2 (metric + ablation) landed
description: v1.x DD report quality eval Phase 2 — 5 metric + V0-V3 ablation framework ship, real dogfood numbers per actual run outcome
type: project
---

## v1.x DD report eval Phase 2 ship 完 (2026-05-17)

### 做了什么

**spec**: `docs/superpowers/specs/2026-05-17-dd-report-quality-eval-design.md` v1.1
**plan**: `docs/superpowers/plans/2026-05-18-dd-report-eval-phase-2-metrics-ablation.md`

12 task ship:
- T2.0 MetricProtocol + BacktestMetricScores + DB metric_scores_json 列
- T2.1 GroundTruthLoader fetch_post_cut_off_kline / anns 真实现
- T2.2 M1 CitationMetric (extraction F1: precision + citation_coverage)
- T2.3 M2 NumericalMetric (4 类指标 ±1% 容差 + 中文数字归一)
- T2.4 M3 RiskPairingMetric (4 bucket valid mitigation judge)
- T2.5 M4 PredictionMetric (direction + target_price_hit + risk_flag_rate)
- T2.6 M5 CompositeJudgeMetric (3 LLM majority + disagreement audit)
- T2.7 BacktestRunner wire MetricRegistry + LeakDetector + eval_results
- T2.8 DDReportPipelineAdapter (production ResearchAgent wrap abstraction)
- T2.9 AblationVariant V0-V3 + NullKBAdapter + SingleAgentPipeline
- T2.10 AblationRunner (4 variant × cases scheduler with fail-soft)
- T2.11 dogfood scaffold + production_factory + sediment

### 真跑出来的数字 (Phase 2 末 ablation dogfood)

| Variant         | M1     | M2     | M3     | M4     | M5     |
|-----------------|-------:|-------:|-------:|-------:|-------:|
| V0 baseline     | TBD    | TBD    | TBD    | TBD    | TBD    |
| V1 no RAG       | TBD    | TBD    | TBD    | TBD    | TBD    |
| V2 no MA        | TBD    | TBD    | TBD    | TBD    | TBD    |
| V3 no Critic    | TBD    | TBD    | TBD    | TBD    | TBD    |

dogfood deferred to user follow-up — framework + script ready at
`backend/scripts/run_phase2_ablation_dogfood.py`.

前置条件:
1. `OPENROUTER_API_KEY` in `backend/.env` (OpenRouter account needed)
2. `TUSHARE_TOKEN` in env (tushare Pro API key)
3. Production KB wire (Milvus collection loaded) — see deferred notes below
4. `unset all_proxy https_proxy http_proxy` before running

Run: `uv run python backend/scripts/run_phase2_ablation_dogfood.py`

### Why (技术亮点)

- **Hebbia 三段式 metric 分层** — extraction (M1 F1 程序化 + 小 LLM judge / M2 regex + tushare ±1%) / summarization (M3 LLM judge) / reasoning (M4 backtest 真股价 + M5 multi-LLM consensus)
- **5 metric 独立模块 + Protocol-injected DI** — MetricRegistry 串联,每 metric stateless 纯函数;依赖通过 MetricInputs bundle 注入
- **BacktestMetricScores 独立 schema** — 不污染 JudgeScores(Phase 1 sediment 教训:JudgeScores 字段是 factuality/coverage/structure/tool_correctness/report_markdown_quality,跟 Phase 2 5 metric 是不同维度体系)
- **V0-V3 ablation 控制变量** — PipelineFactory pattern + NullKBAdapter (V1) / SingleAgentPipeline (V2) / disable_critic flag (V3),生产 ResearchAgent 0 改动
- **fail-soft ablation** — 1 (variant, case) 失败不 abort 矩阵,T2.11 dogfood 30 case run 1 个 auth fail 不影响其他 29 case
- **3 forward sediment 应用一致** — M1 details key citation_coverage (T2.2 fix) / M2/M3 explicit is-None check 避免 0.0-or-1.0 inflate (T2.7 fix) / M5 partial-failure tolerance 神经分 5.0 + parse_failures counter (T2.6 fix)

### How to apply

- Phase 3 接 dashboard + cross-LLM 矩阵 + sanity 副线:`eval_results.metric_scores_json` (per case) + `backtest_runs.metric_summary_json` (per run) 已可读;query SQL 见 dogfood script `_print_ablation_matrix`
- 新 ablation 变体加在 `AblationVariant` 枚举 + `build_pipeline_for_variant` 加 if branch
- 新 metric 加在 `metrics/` 下实现 `MetricProtocol` + 注入 MetricRegistry + 扩 BacktestMetricScores schema 字段
- M4 horizon 默认 90 天,Phase 3 可扩 180/365 走多 PredictionMetric instance 不同 horizon
- T2.11 production_factory 当前用 SingleAgentPipeline fallback (V0 ≈ V2);真接生产 ResearchAgent 推 user follow-up,需要按 build_research_graph + 5 agents 模式 wire

### 撞到的工业问题 (Phase 2 implementation 撞实并 fix)

- **M1 details key 命名误导 (T2.2 review)** — 原计划名 `recall` 但实际只是 evidence 非空检查,不调 judge,跟 IR-recall 不同。改名 `citation_coverage` + docstring 警告;BacktestMetricScores.m1_citation_recall schema 字段保留 spec 一致。
- **M2/M3 0.0-or-1.0 silent inflate (T2.7 review)** — `(m.value if m else 1.0) or 1.0` 在 m.value=0.0 时返 1.0 (falsy or short-circuit),silent 给 0 分案例 1.0 总分。改 `is None` 显式 check。
- **M5 partial-failure tolerance (T2.6 review)** — 1 个 judge auth fail 时整个 compute() 之前会 raise (try/except 缺);改为 client.chat() 异常 + 解析失败均计入 parse_failures + 默认 5.0,3-judge 共识仍能算。
- **CitationMetric ablation denominator bug (T2.2 review)** — recall 分母原是 present sections 而非 required sections,V1/V2 stripped 报告 silent 高分。改 `len(self.section_paths)` 固定分母,ablation 对比有意义。
- **PredictionMetric target_price 命中谓词 plan bug (T2.5 review)** — 原 `or float(h) >= low` 让任何 high≥low 都命中 (即使破上界),违 spec "区间触及"。改 `low<=h<=high` 严格包含。
- **LLM judge classes 误放 test (T2.2 review)** — `_EvaluatorJudge` / `_EvaluatorPairingJudge` 原在 test 文件,T2.7/T2.11 无法 import。移到 prod metric module。
- **`fetch_post_cut_off_kline` 默认 descending 不 sort (T2.1 review)** — tushare daily 默认 descending,`kline[-1]` 拿到最早一天非最末;defensive sort ascending 后取 [-1] = horizon 末。
- **`case_type: str` vs Literal (T2.7 review)** — 原 `str` 触发 `# type: ignore[arg-type]`,改 Literal narrow 后 ignore drop。
- **AblationRunner fail-soft 0 test coverage (T2.10 review)** — except Exception 是核心 value 但无 test,T2.11 dogfood 1 个 auth fail 后回归会静默 break。补 fail-soft test。

### 已知 deferred (T2.11 dogfood + 真接生产 ResearchAgent)

1. **真接 build_research_graph + 5 agents**:T2.11 production_factory 用 SingleAgentPipeline fallback (`app/eval/dd_report_production_factory.py`)。真接生产 pipeline 推 user follow-up,T2.8 已探索入口:`app/orchestration/research_graph.py::build_research_graph(planner, collector, analyst, writer, critic, *, checkpointer)`。
2. **真 dogfood 4×8 ablation 数字**:dogfood script `backend/scripts/run_phase2_ablation_dogfood.py` ship 完;真跑需 OPENROUTER_API_KEY + TUSHARE_TOKEN + KB wire + 生产 pipeline。预算 ~28 RMB / 一轮。
3. **康美 (600518.SH) 暴雷 case spike**:T2.5 留待 T2.11 dogfood 验,实际是否 cut_off=2024-06-30 后 180 天公告里有"退市/造假"关键词命中。
4. **request_id collision (T2.7 review forward warn)**:同 case_id 在多 ablation variant 下复用,dashboard JOIN on request_id 会返多行;T2.11 dashboard 需用 backtest_run_id 区分。
5. **Production KB wire**:`_build_kb_client()` + `_build_kb_lookup()` 在 dogfood script 中显式 raise NotImplementedError;用户接通后需要按 `app/kb/` 实际入口拼 Milvus client + chunk dict。
