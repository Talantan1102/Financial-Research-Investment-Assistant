---
name: harness-board-review-mode-done
description: Harness Board Review Mode 复合型项目知识工具 ship 完 — 底座 DeepCard + 5 视图 + 35 张内容
type: project
---

Harness Board Review Mode ship 完 (2026-05-12, 3 plans / ~30h wall time, PR #48 + #49 + #50):

**底座**(sqlite + Milvus):
- `DeepCard` 字段:what / why / alternatives / chosen_alternative / tradeoff / lessons_learned / metrics / code_anchors / linked_decisions / linked_specs / linked_memories / linked_capabilities / srs_state / provenance / prefill_source / prefill_at / last_edited_at
- `Flashcard` 表:每 DeepCard 派生 0-3 张(tradeoff / alternatives / lessons)
- `Milvus` collection `harness_board_deepcards`(qwen v3 1024d)+ keyword fallback(`keyword_recommender.py`)
- 36 个新 Python module + 9 个 templates + 2 JS(overview.js / flashcards.js) + CSS 扩展

**5 视图**:
- V1 网格 `/` — chip 加完成度角标 + confidence 数字注入;edit dropdown 改 status
- V2 模块深读 `/cap/{id}` — chip→modal 双栏 + inline 编辑 + AI 草拟按钮 + provenance UI(orange/green/blue 3 色边框);`linked_capability` 链接到 `/overview#cap_{id}` 高亮回跳
- V3 系统鸟瞰 `/overview` — cytoscape cose-bilkent + 8 维染色 + 节点大小 = code_anchors+1 + 维度复选 + low_conf 过滤;失败回 `/overview/fallback` 卡片墙
- V4 故事时间线 `/story` — git commit-time + 三段式(problem|decision|outcome) = (why|tradeoff|lessons) + 维度复选 + 日期窗 + asc/desc
- V5 闪卡 SRS `/flashcards/today` + `/flashcards/stats` — SM-2 + 模板派生 + 新卡 5/日 + 到期 20/日 + 0-5 自评 + 学习统计页

**LLM 边界 = L2**:
- 一次性 prefill batch(LLM `prefill_deep_cards.py` 走 OPENAI_API_KEY)+ AI 草拟按钮(V2 modal 内按需)
- constrained JSON schema + provenance fuzzy match 校验,LLM 编造的 quote 在源文件找不到即 reject 该字段
- 不做在线对话(去 /chat)+ 不做闪卡 LLM 评分(SM-2 自评足够)
- 本机无 key 走 hand-curated seed CLI 路径(`seed_deep_cards.py` + jsonl)— 不阻塞演示

**跨视图联动** 5 条全确定性:
- V1 chip → V2 modal (`/cap/{id}` GET htmx swap)
- V3 节点 click → V2 modal
- V4 卡片 click → V2 modal
- V2 `linked_decisions` → `/decisions` 锚
- V2 `linked_capabilities` → `/overview#cap_{id}` 高亮 + center

**Why**:
- B(onboard 自己)+ C(系统化+模块化)+ A(面试讲项目)+ D(主动召回)四场景共享 DeepCard 底座
- `story.md` 不再过期 — 从 DeepCard 集合 render
- 复习内容长期增量填,不一晚填满;改代码 → 改 DeepCard → 闪卡 + 故事 + 鸟瞰 自动更新
- LLM L2 = 一次性 batch + 按需草拟,不在主路径,失败可回退手填

**How to apply**:
- 复习模块深度 → V2 modal
- 复习全局架构 → V3 鸟瞰
- 准备面试讲项目 → V4 故事时间线
- 主动召回知识 → V5 闪卡(SM-2 间隔重复)
- 新加 capability → `capabilities.yaml` + 跑 prefill batch(有 key)或加 seed jsonl 行(无 key)
- 改代码 → 改 V2 modal 字段 → 闪卡 自动 regenerate(保留 srs_state)
- LLM unavailable → V2 隐藏 AI 草拟按钮,功能退化为纯手编(不阻塞)
- Milvus unavailable → 相关推荐降级 `keyword_recommender` + banner 提示

**Ship 指标**:
- 测试:Plan 1 baseline 126 → Plan 2 154+2 → Plan 3 181+2 passed(+27 in Plan 3)
- mypy strict 通过 63 files,ruff format / check clean 66 files
- 内容:35 张 DeepCard 全 8 维覆盖 + 105 张闪卡入库
