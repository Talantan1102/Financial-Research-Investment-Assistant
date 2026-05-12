---
name: harness-board-review-plan3-done
description: Plan 3 ship — V5 闪卡 SRS + 35 张 hand-curated seed + Review Mode 收尾
type: project
---

Plan 3 ship 内容 (10 tasks, +27 tests, all green):

- **SM-2 SRS 算法** — `dashboard/derive/srs.py`,Wozniak 1990 经典公式,`SrsAlgo` Protocol 为 v1.x 升级 FSRS 预留;`SM2Algo.apply(state, grade, now)` 纯函数,`schedule_next_review` 便捷 wrapper(now=UTC);EF 下限 1.3,grade<3 重置 repetition,grade>=3 推进 1→6→prev*ef
- **闪卡 3 类模板派生** — `dashboard/derive/flashcard_generator.py`,机械模板无 LLM:`tradeoff` 模板永远生成 / `alternatives` 仅当 `chosen_alternative` 在 alternatives.name 中时生成(运行时校验,跳过编造)/ `lessons` 仅 lessons_learned 非空时生成;id 格式 `"{cap_id}::{template_kind}"`
- **DeepCard 编辑 hook** — `regenerate_flashcards_for(cap_id, dc_repo, fc_repo, cap_name_cn)` in `repositories.py`:取旧 srs_state 按 template_kind 索引 → delete_by_cap_id → upsert 新集合(匹配 kind 复用旧 srs_state / created_at / last_reviewed_at);挂 `_regenerate_flashcards_if_known(cap_id)` 在 V2 `post_field_update` + `post_ai_draft` 末尾
- **GET `/flashcards/today` 主入口** — 新卡 ≤5 + 到期 ≤20,沿用 base.html + nav;模板 `flashcards.html` + `_flashcard_review.html` partial;翻面 = JS toggle answer / grade-row display
- **POST `/flashcards/{id:path}/review` 0-5 自评** — schedule_next_review (SM-2) → upsert srs_state,response 含 `X-Reviewed: 1` header 驱动前端 `flashcards.js` 推下一张;invalid grade → 400,unknown id → 404;path 类型转换器 `:path` 因 id 含 `::`
- **GET `/flashcards/stats` 学习统计** — sqlite `json_extract(srs_state, '$.repetition' / '$.confidence')` 聚合 total / new_n / mastered(conf≥4) / avg_conf + 维度分布 substr 聚合
- **nav 加 🎴 闪卡** — `_board_nav.html` 5 入口:网格 / 鸟瞰 / 故事 / 闪卡 / 决策
- **35 张 hand-curated DeepCard seed** — `dashboard/data/deep_cards_seed.jsonl`,8 维全覆盖(prompt_context 4 / tools_function 5 / orchestration 6 / memory 5 / rag_knowledge 4 / guardrails 4 / eval_observability 4 / cost_routing 3);新 CLI `backend/app/scripts/seed_deep_cards.py --seed --db --regenerate-flashcards` 一键载入 + 触发 105 张闪卡

**Why**:
- Plan 1+2 已闭合 B(onboard)/ C(系统化)/ A(讲项目) 三场景,Plan 3 = D 主动召回闭合
- SM-2 是 Anki / SuperMemo 经典,Wozniak 1990 公式 50 行 Python 即可,无外部 deps;SrsAlgo Protocol 让 v1.x 换 FSRS 不破坏调用方
- 闪卡 = 机械模板 无 LLM,不引入新幻觉路径;新加 cap 改 DeepCard,闪卡自动重生成(srs_state 保留),复习连续性不断
- 本机无 OPENAI_API_KEY → 走 hand-curated seed 路径(plan 内 fallback 指示),35 张全 8 维覆盖,质量人工对齐,长期 seed-from-version-control 跨机一键重建

**How to apply**:
- 主动召回知识 → `/flashcards/today`
- 看学习进度 → `/flashcards/stats`
- 改 DeepCard 内容 → V2 modal 内编辑 → 闪卡自动重生成(SRS 保留)
- 跨机切换 → `git pull` 后跑一次 seed CLI 重建 board.db
- 升级 FSRS → 新增 `dashboard/derive/srs.py::FSRSAlgo: SrsAlgo` 同 Protocol,server endpoint 不变

**测试**:181 passed + 2 skipped(Plan 1+2 baseline 154 + Plan 3 增 27:7 SRS L0 / 8 generator L0 / 3 hook L1 / 7 endpoint L1 / 2 seed L1),mypy strict 通过 63 files,ruff format / check clean 66 files。

**已知简化**:
- L2 cassette prefill 未录(本机无 LLM key);LLM prefill CLI `prefill_deep_cards.py` 仍可用,有 key 时按 plan Step 2 跑一遍即可补真 LLM 路径
- /flashcards/today 拉全量后 Python 过滤(简化);N>1k 闪卡再加 sqlite 索引利用
- 维度分布 substr 聚合就 `cap_id` 前缀(`memory.x` → `memory`),不读 yaml,够用
