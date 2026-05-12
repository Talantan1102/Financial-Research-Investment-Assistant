---
name: harness-board-review-plan2-done
description: Plan 2 ship — V3 cytoscape 鸟瞰 + V4 故事时间线 + Milvus 真路径 + 跨视图联动
type: project
---

Plan 2 ship 内容 (11 tasks, +28 tests, all green):

- **V3 `/overview` cytoscape 鸟瞰** — `dashboard/derive/graph_builder.py` 构造 nodes/edges JSON;cose-bilkent 布局 + 8 维染色 + 节点大小 = code_anchors+1 + 边框 = confidence + 边线 = `linked_capabilities`(无向 dedupe + self-loop 去除);工具栏维度复选 + `low_conf<3` 过滤
- **V3 fallback** — `cytoscape` 数据失败时前端自动 `fetch('/overview/fallback')` 替换 DOM,后端返回 8 维卡片墙(`overview_fallback.html`),保证图加载失败不死站
- **V4 `/story` 故事时间线** — `dashboard/derive/commit_time_extractor.py` 抽 git log `--diff-filter=A --reverse` 首个 commit + `dashboard/derive/story_builder.py` 构造三段式 `(problem|decision|outcome) = (why|tradeoff|lessons_learned)` + 时间归属 fallback chain(commit_time → `DeepCard.prefill_at` → no_time_group 尾置);工具栏维度复选 + 日期窗 + asc/desc
- **Milvus 真路径 wire** — `_try_milvus_related` 从 stub 接通:取 pivot DeepCard → `embedding_text` → qwen embed → Milvus search → 过滤 self;新增 `POST /admin/milvus/reindex` 显式批量同步
- **顶部 nav** — `_board_nav.html` 4 入口(网格 / 鸟瞰 / 故事 / 决策),`active_nav` ctx flag 高亮当前页
- **跨视图联动闭环** — V2 modal 新增 `linked_capability` 块,链接到 `/overview#cap_{id}`;`overview.js` `hashchange` 监听 → cy.center + flashClass highlight

**Why**:
- V3 给"系统化视角"(C 复习场景)+ V4 给"故事弧线"(A 面试讲项目)
- 两视图都跳 V2 modal 形成闭环 — 复合工具的"系统/模块/叙事"三视角联动
- commit_time 抽取走 subprocess 而不是 PyGit2 — 零额外依赖,Plan 3 改 cache 即可
- graph_builder + story_builder 都是纯函数 — 测试 100% L0 unit,无 IO mock 复杂度

**How to apply**:
- 看全局架构 → `/overview` 鸟瞰图
- 准备面试讲项目 → `/story` 三段式时间线,按时间或维度 filter
- 跨节点跳转 → modal 内 linked_capability → `/overview#cap_{id}` 高亮 + center
- 真 Milvus 推荐 → 启 docker compose milvus + 设 `HARNESS_BOARD_MILVUS_HOST`,然后 `POST /admin/milvus/reindex` 一次

**测试**:154 passed + 2 skipped(Milvus 真服务 + Milvus reindex),mypy strict 通过,ruff format / check clean。

**已知简化(留 Plan 3 补全)**:
- commit_time 抽取无 cache — 每次 `/story` 现抽(单页 ~62 cap × git log 慢),Plan 3 加后台 cron job
- V3 cytoscape 失败 fallback 是 client-side(JS 抛 → fetch fallback);无 server-side UA 检测
- L2 cassette 仍推到 Plan 3 全量 prefill 时一并录
