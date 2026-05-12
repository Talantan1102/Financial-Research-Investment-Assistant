---
name: harness-board-review-plan1-done
description: Plan 1 ship — DeepCard 底座 + V2 模块深读 modal + LLM L2 prefill + Milvus collection
type: project
---

Plan 1 ship 内容 (~3-4h Claude Code wall time):

- **sqlite v2 schema** — `deep_cards` / `flashcards` / `prefill_log` 三表 (deep_cards 用单 JSON payload column 简化 Pydantic roundtrip,sqlite < 1M 行性能足够)
- **`backend/app/scripts/prefill_deep_cards.py`** batch CLI + constrained Pydantic schema (`PrefillResponse` 全字段 + per-field `*_provenance`) + provenance fuzzy match 校验(markdown-aware,normalize 后 substring 命中)+ `prefill_log` 表追踪 success / rejected / skipped / llm_error
- **Milvus collection `harness_board_deepcards`**(qwen v3 1024d)+ embedding source 组合 (name_cn + what + why + tradeoff) + **keyword fallback**(`recommend_by_keyword` sum-of-token-length 评分,跟 `classify_layer` 同款逻辑)
- **V1 chip 角标**:`completion_level`(empty/partial/full 灰/黄/绿,基于 4 必填字段填充比)+ `confidence` 0-5 SRS 数字
- **V2 模块深读 modal**:`GET /cap/{cap_id}` 双栏布局(左内容 / 右链接图)+ inline 编辑(`POST /cap/{cap_id}/field/{name}` + prefill_source 自动转换 llm→hybrid)+ AI 草拟按钮(`POST /cap/{cap_id}/ai_draft/{name}` + provenance 校验 + 422/503 边界)
- **`GET /cap/{cap_id}/related`** Milvus + keyword fallback,`X-Milvus-Status` header 区分
- **provenance UI 着色**:`prefill_source = llm` 橙边框、`hybrid` 蓝、`manual` 绿
- **3 张样本 DeepCard seed** 入库 + `dashboard/data/deep_cards_seed.jsonl` 入 git(constrained_schema / research_5agent / milvus_3_collections)

**Why**:
- 覆盖复习场景 B(onboard)+ C(模块化),作为 Plan 2 (V3 鸟瞰 + V4 故事) / Plan 3 (V5 闪卡) 的内容地基
- LLM 用法严格 L2(一次性 batch + 按需草拟按钮),provenance 校验防幻觉,跟项目 Constrained Router taste 一致
- DeepCardRepo 单 JSON payload + Pydantic model 简化 schema 演进(spec § 6.1 分列 lock,实施时调整;后续 spec 自审会注明)

**How to apply**:
- 看某 capability 的深度 → 直接访问 `/cap/{cap_id}`(主页 chip click 入口在 Plan 2 跨视图联动时 wire,当前保留 inline edit)
- 新 cap prefill → `uv run --project backend python -m app.scripts.prefill_deep_cards --caps <id1>,<id2>`
- LLM unavailable → AI 草拟按钮返回 503,inline 编辑仍可用(不阻塞)
- Milvus unavailable → 相关推荐自动 keyword fallback,`X-Milvus-Status: fallback` header 提示
- 测试:127 passed + 1 skipped(Milvus 真服务),mypy strict 全 dashboard + backend/app/scripts 通过

**已知简化(留 Plan 2/3 补全)**:
- chip click → V2 modal entry 未 wire(保留 inline edit dropdown)
- Milvus 真路径在 `_try_milvus_related` 中是 stub("milvus_search_not_wired_plan1")— Plan 2 Task 6 wire
- L2 cassette 推迟到 Plan 3 全量 prefill 时一并录
- 大规模 prefill (~50 cap) 推到 Plan 3 Task 8
- 决策来源 enrichment(linked_specs / decisions_summary 自动推断) 留 Plan 2 完善
