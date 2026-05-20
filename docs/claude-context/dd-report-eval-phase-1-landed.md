---
name: DD report eval Phase 1 (backtest infra) landed
description: v1.x DD report quality eval Phase 1 — backtest infra ship 完, 40 golden case + DB schema + LLMSwapper + 数据 leak detector
type: project
---

## v1.x DD report eval Phase 1 ship 完 (2026-05-17)

### 做了什么

**spec**: `docs/superpowers/specs/2026-05-17-dd-report-quality-eval-design.md` v1.1
**plan**: `docs/superpowers/plans/2026-05-17-dd-report-eval-phase-1-backtest-infra.md`

9 个 task ship (含 review fix loop):

- T1.0 模块骨架 + KB schema spike + .env OPENROUTER_API_KEY
- T1.1 DB schema (eval_results 加 4 列 + backtest_runs 新表 含 git_sha/ablation_variant/llm_model + 修了 legacy 8 列 DB migrate bug)
- T1.2 LLMSwapper OpenRouter wrapper (3 backtest evaluator + 6 cross-LLM model 白名单 + httpx trust_env=False)
- T1.3 KB Chunk schema 加 publish_date 字段 + pipeline 层 model_copy 注入 + ISO Milvus 行同步
- T1.4 TushareBacktestAdapter (双层 cut_off 防御 — 注入参数 + 二次过滤 + 缺字段哨兵 silent drop)
- T1.5 KBBacktestAdapter (lenient/strict 模式过滤 publish_date + k*2 over-fetch)
- T1.6 BacktestRunner skeleton (装配 adapter + LLM swap + backtest_runs 写入 + try/finally 错误路径写 status=failed)
- T1.7 LeakDetector (扫 tushare rows / KB chunks / prompt text 三层) + assertion helper + 2 integration smoke
- T1.8 32 backtest + 8 sanity golden case 数据 + ground_truth_loader stub

### Why (技术亮点)

- **Pipeline-as-SUT 范式落地** — BacktestRunner 装配 adapter + EvaluatorClient 给 pipeline, pipeline 接什么就跑什么, 不耦合生产 LLM (生产用 dashscope, eval 用 OpenRouter swap)
- **双层 leak 防御** — tushare adapter 注入 end_date 参数 + 收到行二次 ann_date 过滤; KB adapter publish_date 过滤 + lenient/strict 二档
- **legacy DB migrate** — `_maybe_add_column` ALTER TABLE 迁移 helper, 解决 `CREATE TABLE IF NOT EXISTS` 不加列的坑
- **Credential safety** — EvaluatorClient.api_key `field(repr=False)` 防 log 泄露

### How to apply

- Phase 2 起, 所有 metric 走 BacktestRunner pipeline, 通过 adapter 拿数据
- 新 ablation 变体走 `ablation_variant` 字段标记, 同 case 跑多变体写多 backtest_runs 行
- cross-LLM 矩阵走 `llm_model` 字段标记, sanity case 跑生产模型
- 怀疑 leak 时, 用 `LeakDetector.scan_tushare_rows / scan_chunks / scan_prompt_text` 三层扫
- Phase 2 wire LeakDetector 进 BacktestRunner.run_one 内部 (Phase 1 是独立工具未 wire)
- ground_truth_loader 留了 NotImplementedError stub, Phase 2 M4 prediction metric 实现具体方法

### 撞到的工业问题 (Phase 2/3 撞 LLM cutoff 准备)

- **LLM cutoff 是真问题** — deepseek-v4-flash cutoff 2026-04, 短窗口几乎无法做 leak-free backtest, 必须 swap 老 cutoff LLM 评估
- **SOCKS proxy 干扰** — 测试机 socks5://127.0.0.1:7897 系统 proxy 会 break OpenAI() 构造, trust_env=False 解决但牺牲大陆 HTTP proxy 可达性 (docstring 已警告)
- **JudgeScores schema 不对齐** — spec 假设的 `factual_accuracy` 等 actual 是 `factuality / coverage / structure` (+ evidence) — Phase 2 metric 实现要注意复用现有字段而非新建
