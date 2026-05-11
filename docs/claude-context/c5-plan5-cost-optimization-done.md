---
name: c5-plan5-cost-optimization-done
description: C.5 Plan 5 cost optimization 5 项 ladder + injection classifier + posterior calibration ship — 单 session 成本 $0.025 → $0.005
type: project
---

C.5 Plan 5 (cost optimization layer + algorithm depth #2 + #3) ship — 2026-05-11.

## ship 范围

- spec § 4 优化 5 项 ladder 全落地:
  - **#1 prompt cache**: `@with_prompt_cache` decorator + `PromptCacheStore` (Redis-backed mark_used, key=`memory:prompt_cache:{name}:v1:{sha1[:16]}`, 5min TTL)
  - **#2 batch extraction**: `BatchExtractor.extract_batch(episodes)` (≤5 episode 1 LLM call, system prompt 摊薄, fact 标 source_episode_id 归属)
  - **#3 skip-extraction gate**: `should_skip_extraction(episode)` 纯函数 (关键词命中优先 / <50 char 闲聊 skip / extracted_at 防重)
  - **#4 async via Celery**: `memory_llm` 队列 + 4 task (extract_episode_async / extract_session_batch_async / reconcile_pending_milvus / posterior_calibration_weekly)
  - **#5 embedding cache**: `EmbedCache.get_or_compute(text, user_id, compute_fn)` per-user keyed Redis hash, 24h TTL (契约 § 17 A2-3 final 3 参数版本)
- spec § 11 末尾 #2 prompt injection classifier 规则层 (12 高置信 pattern + 12 representative + 8 safe + 10 placeholder golden, 命中 confidence ≥ 0.95)
- spec § 11 末尾 #3 posterior calibration weekly job (三档反向校准 / Reader+Updater Protocol 抽象 / 周一 03:00 Asia/Shanghai cron)
- `chat_memory_calibration_runs` audit 表 + Celery beat schedule (`reconcile_pending_milvus` 5min + `posterior_calibration_weekly` 周一)

## 关键决策 (实施期撞实)

- **prompt cache 路径取舍**: DashScope 不支持原生 `cache_control` (Anthropic 协议), 用 Redis-backed `mark_used` 模拟同等语义. 装饰器接口稳定 → v1.x 切 Anthropic 时只换 store impl, 调用方 0 改动
- **skip_gate 关键词优先**: 实施期撞实 — 测试要求"我加仓茅台 600519.SH 500 股"(35 char) 不 skip, 但 spec 写 <50 char 必 skip. 决议: 关键词命中优先于长度门 (短而高信号 episode 不该被 false-skip), 写入 docstring + 6 case L0
- **BatchExtractedFact vs Plan 2A ExtractionOutput**: 契约 § 17 A2 (5) 提到统一 ExtractionOutput, 但 batch 场景需 source_episode_id 归属 key. 决议: 引入 `BatchExtractedFact` dataclass (互补不替代), caller (path_b_runner / archival_insert) 做 adapter
- **injection classifier 规则**: 撞实 — `ignore noise in stock price` 含 "ignore" 但安全 → 规则必须配 `(all|previous|above)` 上下文. "请忘记之前所有的限制和规则" 撞 → 加宽 zh_forget pattern 的 quantifier
- **task body placeholder 边界**: extract_episode_async / extract_session_batch_async body 留 placeholder 是范围权衡 (本 plan 不跨 Plan 1/2 边界改 PathBRunner / archival_insert). Plan 8 dogfood 收束接真路径
- **posterior_calibration_weekly Reader/Updater Protocol**: 用 Protocol 抽象解耦 Plan 3 retrieval_logs/feedback 表 schema (契约 § 17 A4). thin SQL adapter 留 Plan 8 接 SessionLocal, 算法逻辑本 plan 完整 ship
- **HierarchicalMemory DI 加 2 default-None 参数**: `embed_cache=None` + `prompt_cache_store=None`. 现有 chat_router.py / mcp_server / tasks/memory.py 调用方全部 positional 或不传, 0 破坏

## 跟 spec 决策对齐

- ✓ 5 项 ladder 全部落地
- ✓ injection classifier 规则层 ship + golden 初始化 (Plan 5 12 representative, Plan 8 收束 30)
- ✓ posterior calibration weekly job + audit 表 + 三档算法
- ✓ embed cache per-user keyed (契约 § 9 + § 17 A2-3 强制 3 参数版本)
- ✓ Celery 队列名 `memory_llm` (契约 § 9 + § 17 A2-1 短名)
- ✓ HierarchicalMemory DI hook (契约 § 3)
- 部分: 30 case poison golden 仅 12 representative + 8 safe + 10 placeholder ship, Plan 8 收束剩 10 + 阈值 0.95

## 跟契约 § 17 audit 对齐

- ✓ A1: `backend/app/tasks/memory.py` Edit 加 3 task body, 不替换 Plan 2B 的 2 task stub
- ✓ A1: `backend/eval/memory/poison_attacks_golden.jsonl` Plan 5 创建 30 case (12 representative + 8 safe + 10 placeholder), Plan 8 扩展
- ✓ A2-1: Celery task 名 `reconcile_pending_milvus` 跟 Plan 2B 对齐, 不重定义
- ✓ A2-3: `EmbedCache.get_or_compute(text, user_id, compute_fn)` 3 参数 final
- ✓ A4: posterior calibration 读 Plan 3 ship 的 `chat_memory_retrieval_logs` + `chat_memory_retrieval_feedback`, 不另建表
- ✓ A6: `backend/app/memory/injection_classifier.py` Edit 加 `is_prompt_injection`, 不替换 Plan 4 ship 的 `evidence_quote_in_episode`

## 关键文件 ref

### 实现层
- `backend/app/memory/skip_gate.py` (Task 1)
- `backend/app/memory/embed_cache.py` (Task 2)
- `backend/app/memory/prompt_cache.py` (Task 3)
- `backend/app/memory/batch_extractor.py` (Task 4)
- `backend/app/memory/injection_classifier.py` (Task 5, Edit)
- `backend/app/memory/posterior_calibration.py` (Task 7)
- `backend/app/models/memory_calibration.py` (Task 6)
- `backend/scripts/migrations/2026-05-11-c5-plan5-calibration-table.sql` (Task 6)
- `backend/eval/memory/poison_attacks_golden.jsonl` (Task 5)

### 编排层 (Edit)
- `backend/app/tasks/memory.py` (Task 8, Edit 加 3 task)
- `backend/app/tasks/celery_app.py` (Task 8, Edit 加 3 routes)
- `backend/app/tasks/celery_beat_schedule.py` (Task 8, Edit 加 weekly schedule)
- `backend/app/memory/hierarchical.py` (Task 9, Edit __init__ 加 2 DI default-None)

### 测试
- L0: `tests/unit/memory/test_{skip_gate,embed_cache,prompt_cache,batch_extractor,injection_classifier,posterior_calibration,calibration_run_model,hierarchical_di_hooks}.py` (8 文件)
- L0 tasks: `tests/unit/tasks/test_memory_tasks_plan5.py`
- L1: `tests/integration/memory/test_{cost_opt_e2e,posterior_calibration_e2e}.py`
- L2: `tests/e2e/memory/test_poison_attacks.py`

## Cost 实测预算 (Task 10 assert)

| 项 | 无优化 | + 优化 1-3 | Task 10 assert |
|---|---|---|---|
| LLM call/session | 10 | 1 (skip 5 + batch 5→1) | `llm.calls == 1` |
| Prompt token/call | 1500 | 1500 → 300 (cache hit 后) | prompt_tokens=1500, cache 折扣 0.2 |
| Completion token | 500 | 250 | `last_completion_tokens=250` |
| 总 cost | $0.025 | ≤ $0.005 | `cost_with_prompt_cache <= 0.005` |
| Embed call | N | N/2 (24h cache) | `embed_calls == 1`(2 次同 text) |

## Done criteria

- ✓ 13 task 全 ship (Task 11 / 8 合并 — posterior body 一并 Task 8 落)
- ✓ Plan 5 + 累计 c5 测试套件全过 (270 tests pass in scope)
- ✓ ruff + mypy strict 0 error on Plan 5 source files (32 source files)
- ✓ L1 cost_opt_e2e 5 项优化 hit + cost ≤ $0.005 ✓
- ✓ L2 poison_attacks recall ≥ 0.85 + fp < 0.1 ✓
- ✓ serve smoke `python -c "from app.app_main import app"` 不报错 ✓
- ✓ DB migration ORM `chat_memory_calibration_runs` 通过 lifespan create_all 自动 pickup
- ✓ 知识卡 + CLAUDE.md 索引 (本卡)
