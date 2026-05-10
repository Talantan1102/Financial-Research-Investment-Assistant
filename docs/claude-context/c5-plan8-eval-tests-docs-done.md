---
name: c5-plan8-eval-tests-docs-done
description: C.5 Plan 8 Eval + Tests + Docs 收束 ship — 50 golden + 4 metric + bi-temporal differential + chaos + 投毒 + 总卡
type: project
---

C.5 Plan 8 (Eval + Tests + Docs 收束) ship — 2026-05-11.

## ship 范围

**Eval Pipeline (`backend/eval/memory/`)**:
- 50 golden case (`c5_memory_golden.jsonl`) — 检索 20 / routing 20 / 抽取 10
- 30 投毒 attack 测试集 (`poison_attacks_golden.jsonl`) — 20 攻击 + 10 safe, 6 类 pattern
- 20 跨轮抽取 case (`cross_turn_extraction_golden.jsonl`) — 8 单 / 6 跨2 / 4 跨3 / 2 非连续
- bi-temporal 5 session 序列 case (`differential_holding_evolution.jsonl`)
- 4 metric impl:
  - `recall_precision_metric.py` — LLM-judge ≥ 0.7
  - `temporal_correctness_metric.py` — 确定性 bi-temporal ≥ 0.95
  - `faithful_answer_metric.py` — claim grounding + provenance ≥ 0.85
  - `routing_accuracy_metric.py` — subset-match memory + KB 共用 ≥ 0.85
- `long_tail_monitor.py` — P90 min-age ≥ 7d + 周报 SQL
- `eval_runner.py` CLI — `--metric all --strict` PR gate
- `_runner_deps.py` — live LLM judge wiring (haiku) + planner/retriever placeholder

**Tests 收束** (`backend/tests/`):
- L0 unit 31+ new test:
  - `test_recall_precision_metric.py` (5)
  - `test_temporal_correctness_metric.py` (8)
  - `test_faithful_answer_metric.py` (11)
  - `test_routing_accuracy_subset_match.py` (7)
  - `test_long_tail_monitor_eval.py` (7)
- L1 integration:
  - `test_eval_runner_e2e.py` (6) — 跑 50 golden mock-deps full path
- L2 e2e:
  - `test_bi_temporal_differential.py` — spec § 12 5 session 1:1 实现 (真 PG)
  - `test_chaos_three_way_consistency.py` — 4 scenario (Milvus outbox / reconciliation /
    幂等键 / no_op rollback)
  - `test_poison_attacks.py` — 30 case ≥ 0.95 拦截率 + ≤ 0.20 误杀率
- `coverage_audit.md` — L0/L1 跨 Plan 1-7 audit (58% L0 unit, L1 全模块至少 1 case)

**Docs 收束**:
- Plan 1A / 2B / 7A 自卡(实施期未写, Plan 8 收束补)
- Plan 8 自卡 (本文档)
- 总卡 `c5-cross-session-memory-done.md` (8 plan ship 范围 + 关键决策 + 6 算法深度补丁 + 简历叙事段)
- CLAUDE.md 加 C.5 整段索引

## 关键决策(实施期撞实)

- **eval threshold 进 PR gate, 不只 nightly**: `eval_runner --strict` 模式 exit non-zero
- **bi-temporal differential test 不简化**: spec § 12 5 session 完整 1:1 实现, 跟真 PG + ConflictResolver 交互
- **chaos test 4 scenario**: 不止 happy path — Milvus fail fallback / 进程重启 reconciliation /
  幂等键 IntegrityError / no_op 无孤儿
- **投毒 30 case 含 10 safe 对照**: 防止过拟合, 误杀率 ≤ 0.20 (Plan 5 阶段 0.85 收紧到 0.95)
- **L2 cassette 留 dogfood 期录**: 每 cassette 需 real LLM key, 跟 v0.8.x cassette 同 pattern
  作者本地录 + commit, 不在 Plan 8 范围

## 跟 spec 决策对齐

- spec § 10 Eval Pipeline 全部 ✓ (50 golden + 4 metric + routing accuracy + 跑频次)
- spec § 12 Test Strategy 全部 ✓ (L0/L1/L2 + bi-temporal differential + chaos + 投毒)
- spec § 14 v1.x Ship Checklist 全勾 ✓ (Task 15)
- spec § 11 算法深度补丁 收束 ✓ (#2 投毒 30 case / #3 长尾 P90 / #5 三方一致性)

## 偏离 plan

- Task 11 `_runner_deps.py` planner/retriever 是 placeholder (raise to remind) —
  真 CLI 跑前需 wire HierarchicalMemory + chat agent factory(留 dogfood 期 wire)
- Task 13 L2 cassette 5 representative 未录 — spec § 14 标 "Manual Followup(不阻塞 ship)"
- Task 15 dogfood 周报 + spec § 14 inplace edit + PR — main agent 处理(本 subagent 不 push)

## 关键文件 ref

- `backend/eval/memory/c5_memory_golden.jsonl` 50 case
- `backend/eval/memory/poison_attacks_golden.jsonl` 30 case
- `backend/eval/memory/differential_holding_evolution.jsonl` 5 session
- `backend/eval/memory/cross_turn_extraction_golden.jsonl` 20 case
- `backend/eval/memory/recall_precision_metric.py` + 3 metric files
- `backend/eval/memory/long_tail_monitor.py`
- `backend/eval/memory/eval_runner.py` (CLI + --strict)
- `backend/eval/memory/_runner_deps.py` (live wiring stub)
- `backend/eval/memory/coverage_audit.md`
- `backend/tests/e2e/memory/test_bi_temporal_differential.py`
- `backend/tests/e2e/memory/test_chaos_three_way_consistency.py`
- `backend/tests/e2e/memory/test_poison_attacks.py`
