# ETCLOVG Migration — Plan 2: 数据迁移 + 测试 Golden 同步

> Plan 2 已实施完成,本文档作 ship 记录(不作执行模板)。

**Spec:** [`docs/superpowers/specs/2026-05-20-harness-board-etclovg-migration-design.md`](../specs/2026-05-20-harness-board-etclovg-migration-design.md)
**Plan 1:** `2026-05-20-etclovg-migration-plan1-config-types.md`
**Plan 3:** `2026-05-20-etclovg-migration-plan3-ios-visual-and-templates.md`(后续)

**版本归位**: v0.9.x harness-board ETCLOVG migration · **分支**: `refactor/etclovg-migration` · **PR(合并 Plan 1+2+3 一个 PR)**

**Goal**: 把 jsonl seed 数据 + 11 个测试文件 golden 一次性切到新 ETCLOVG 7 维 cap_id。

---

## 实施总结

### 数据迁移(一次性脚本 → in-place rewrite → 删脚本)

| 文件 | 输入 | 输出 | 备注 |
|---|---|---|---|
| `dashboard/data/deep_cards_seed.jsonl` | 35 行 | 34 行 | `memory.session_checkpoint` 合并到 `lifecycle.session_checkpoint`(orchestration.sqlite_saver 卡片) |
| `dashboard/data/external_agent_survey.jsonl` | 53 行 | 53 行 | dimension 字段全 rewrite,无 drop |

**cap_id rename 规则**(节选,完整见 spec § 4):
- `prompt_context.*` / `memory.*` / `rag_knowledge.*` → `context.*`
- `tools_function.*` → `tool.*`
- `orchestration.*` → `lifecycle.*`
- `orchestration.sqlite_saver` + `memory.session_checkpoint` → `lifecycle.session_checkpoint`(合并)
- `guardrails.langgraph_retry` → `lifecycle.langgraph_retry`(retry edge 是 L 控制流)
- `guardrails.adversarial_test` → `verification.adversarial_test`(对抗测试归 V)
- `guardrails.*` 其余 → `governance.*`
- `eval_observability.eval_runner` / `llm_judge` / `golden_cases` / `cassette_l2` / `test_suite` / `ab_testing` → `verification.*`
- `eval_observability.trace_service` / `latency_p95` / `dashboard` → `observability.*`
- `cost_routing.*` → `observability.*`(其中 `max_tokens_calibration` → `context.*`)

### 测试 Golden 同步(11 个文件 / 36 fail → 0 fail)

| 文件 | 改动 |
|---|---|
| `test_path_router.py` | `test_loads_8_main_dims_and_6_app_shell` → `test_loads_7_main_dims_and_5_catch_all`;parameterized cases 全部更新到新 dim id;新增 execution/governance/docker-compose 测试用例 |
| `test_snapshot_builder.py` | `test_snapshot_has_8_layers` → `test_snapshot_has_7_layers`;`test_snapshot_total_62` → `test_snapshot_total_69`;lit anchor 30-40 → 36-48 |
| `test_capability_resolver.py` | `test_load_62_capabilities` → `test_load_69_capabilities`;fixture dimension="memory" → dimension="context";lit anchor 同上调整 |
| `test_decision_extractor.py` | keyword classification 切换 (Pydantic+auth → governance / TierRouter → observability) |
| `test_main_endpoint.py` | `memory.long_term_memory` → `context.long_term_memory`;layer 数 8→7;total 62→69 |
| `test_v2_modal_endpoint.py` | `prompt_context.skills_bundle` → `context.skills_bundle`;linked_capabilities 改新 id |
| `test_story_endpoint.py` | `prompt_context.constrained_schema` → `context.constrained_schema` |
| `test_seed_deep_cards.py` | expected_dims 8 → ETCLOVG 6 (execution 暂无 seed card,subset check) |
| `test_seed_ingest.py` | `memory.long_term_memory` → `context.long_term_memory`;`memory.session_checkpoint` → `lifecycle.session_checkpoint` |
| `test_graph_builder.py` | fixture dimension="prompt_context/tools_function/memory" 全替换;filter_dimensions test 改为跨 dim 过滤 |
| `test_story_builder.py` | 同上 + filter test 改为 context+lifecycle 双 dim |

### 迁移脚本(一次性,跑完即删)

`dashboard/scripts/migrate_to_etclovg.py` — Python 脚本含 `CAP_ID_MAP`(56 项) + `DROP_CAP_IDS` + `DIM_MAP`。
- 支持 `--dry-run` 预览
- 脚本本身不保留(YAGNI),不入 commit

---

## ship 验收

| 验收项 | 结果 |
|---|---|
| pytest dashboard | **0 fail / 3 skipped** (playwright + 2 milvus 环境,与 Plan 1 baseline 一致) |
| mypy dashboard 全量 | **0 errors / 76 source files** ✓ |
| ruff check + format | **all checks passed / 76 files formatted** ✓ |
| graph nodes (rebuild 后) | **69 nodes / 24 edges / 7 dim** ✓(对照 baseline 62/24/8) |
| dimension 分布 | execution=7 / tool=8 / context=22 / lifecycle=10 / observability=9 / verification=7 / governance=6 ✓ |
| total_lit | **42**(baseline 35 → +7,主要 E 层贡献) |
| seed jsonl drop | 35 → 34 行,1 drop(memory.session_checkpoint 合并) ✓ |
| survey jsonl | 53 → 53 行,53 个 dimension 字段全 rewrite ✓ |

---

## 关联

- 上游 Plan 1:`2026-05-20-etclovg-migration-plan1-config-types.md`
- 下游 Plan 3:`2026-05-20-etclovg-migration-plan3-ios-visual-and-templates.md`(mockup-v3 + iOS 视觉重做)
- 合并 PR 标题(3 plan 完工时):`feat(harness-board): ETCLOVG 7 维迁移 + iOS Calm Minimal 视觉重做`
