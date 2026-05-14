# Harness Board V2 Polish ship 完(2026-05-14)

## 结论

V1(2026-05-12 ship 的 Review Mode)在用户 dogfood 时暴露 3 个不完善:界面单薄如 admin 工具 / 鸟瞰渲染空(35 张 seed 未自动加载)/ 无一键刷新入口。本轮 V2 polish 用 spec + 3 plan 把这三件事 + 整套 UI 表面美化作为一个 PR 一并交付。

## Why

- **UI 是 portfolio 的脸面**:Quiet Workshop 设计语言(暖黑作坊感)— Newsreader/Source Han Serif/Manrope/Geist Mono 字体栈 + 双强调(琥珀 amber `#c89456` × 古铜青 teal `#6f9494` 互补色)+ fingerprint SVG 签章 — 让 portfolio 看起来"作者认真对待自己作品"
- **鸟瞰空 = 数据流断裂**:`dashboard/data/deep_cards_seed.jsonl` 35 张 seed 是手动 CLI 工具,无自动加载机制;db 只有 3 张,其他 59 节点 confidence=0 + 无 edge + 虚线 + 0.4 透明度,视觉上是一片散落小灰点
- **`/refresh` 语义不完整**:旧 endpoint 只 invalidate snapshot 缓存 + 302 redirect;不刷 seed / decision / Milvus;且前端无按钮,需手动 curl POST。SSE 流式 5-step pipeline + nav-rail refresh button 是用户感知到的"一键更新"

## How to apply

下次相关改动看:
- **设计 source-of-truth**:`dashboard/static/mockup-v2.html`(完整 Quiet Workshop CSS + HTML 参考,2200 行 self-contained,留作 reference 不删)
- **Spec**:`docs/superpowers/specs/2026-05-14-harness-board-v2-polish-design.md`(547 行,§ 1 设计语言 / § 2 SSE pipeline / § 3 前端面板 / § 5 全 UI 表面 / § 6 测试 / § 8 验收)
- **3 个 plan**:`docs/superpowers/plans/2026-05-14-harness-board-v2-plan{1,2,3}-*.md`

## 3 Plan ship 概览

| Plan | 范围 | task | 关键 commit |
|---|---|---|---|
| **Plan 1** 后端 pipeline + 数据修复 | SeedIngestService + RefreshPipeline + SSE endpoint + lifespan + L0/L1 测试 | 12 | bcf55ff / 8d06247 / 2c5e169 / 74cec51 / 24d72b5 / d375a1e / 6ad028b |
| **Plan 2** 前端 Quiet Workshop 全 UI 重写 | style.css 879→2547 行 8 phase + 13 模板 + fingerprint Jinja + 5 全局组件(toast.js / modal.js / _refresh_panel.html / skeleton / empty/error state) | 20 | 6beca31~2b5e56a 20 commit |
| **Plan 3** 鸟瞰增强 + refresh JS + stats endpoint + e2e | graph edge weight + cytoscape glow + 自建 hover tooltip + 空状态浮条联动 + refresh-panel.js SSE 客户端 + /api/flashcards/stats.json + Playwright e2e(optional)| 10 | e8cd7ce / 67cd87e / 919885e / e432af9 / 215b60d / 538245b / c21236e / 3bed3e8 / cf5c2bc / d299c2c |

总 42 task / 43 commits(含 docs commit c79af26 + final fix d299c2c)。

## 关键决策 anchor

1. **`/refresh` 改 SSE in-process 而非 Celery**:5 step 加起来 1-5 秒,不值得引 Celery + Redis 异步基础;async generator + StreamingResponse 足够。spec § 2.1
2. **Milvus_reindex 单点可降级 4 种 skip 不阻断**:env 未设 / API key 缺 / 不可达 / embedding 失败 → step skip but pipeline 继续;snapshot_finalize 总是最后跑保证 chip 状态新鲜。spec § 2.3
3. **Seed ingest insert-if-missing 不 upsert**:保护用户手动编辑;CLI 退化为薄包装 + 新增 `--force` flag 给"强制重填"用途。spec § 2.5
4. **设计语言 Quiet Workshop = 暖黑作坊 + 双强调**:琥珀=行动/高光,古铜青=路径/数据/次级标签。Newsreader(可变 opsz)代替 Fraunces(更温和长文友好)。spec § 1.2 / § 1.3
5. **节点 glow 用 cytoscape `overlay-color` + `overlay-opacity`**:cytoscape 不原生支持 box-shadow,只 `node[status="lit"]` 触发(避免性能)。Plan 3 Task 2
6. **Edge confidence 加权 width**:两端 min(conf) ≥ 4 → 1.2 实线主线 / 否则 0.6 半透虚线。"主路径 vs 弱连接"视觉分层。spec § 4.2
7. **Refresh-panel.js ESC 关面板不取消 EventSource**:再次打开可恢复中途状态(从内存 buffer 还原)。spec § 3.4
8. **Flashcards stats 走 endpoint + inline JS hydrate**:不在 Jinja 算 stats(后端 view 简化为静态壳),前端 `fetch /api/flashcards/stats.json` 后用 DOM API 渲染 SVG 圆环 / 时间线 / 散点。Plan 3 Task 6/7
9. **fingerprint SVG 从 snap.layers 派生**:8 维放射 spoke,每维 5 dot 按 lit/wip/todo 数量分布,memory 维度用 amber 编号(高光维)。"每个 board 状态独一无二"的签章感
10. **CSS 单文件 8 phase 累积**:不拆多 css 文件;Phase 1-8 顺序追加;final 2547 行(spec 估 1500,实际 8 phase 累计 + 5 全局组件 + 微动画稍超)

## 验收 ship gate(spec § 8)— 全部 ✓

- ✅ `/overview` 渲染 62 nodes / 25 edges,memory 维度成簇,lit 节点 amber glow,hover tooltip
- ✅ nav-rail 底部琥珀 refresh 按钮 → 240×360 面板 5 step 逐行 ✓,无 milvus env 时第 4 行 ⊘ skip
- ✅ 5 视图 + DeepCard modal + flashcards_stats 视觉对照 mockup-v2.html
- ✅ pytest 211 passed / 3 skip(playwright + 2 milvus) / mypy 0 errors / ruff clean
- ✅ unset OPENAI_API_KEY + HARNESS_BOARD_MILVUS_HOST 跑 refresh 不挂(4 done + 1 skip)

## 工业难题撞上

- **API mismatch in Task 2**:首版 implementer 写了 `ingest(cards, force=False)`,不符合 plan 的 `run_once_if_underfilled()` + `run(force=False)`,通过 SendMessage 续接修。Lesson:plan 写 method 签名,implementer 不能"简化"
- **Plan subagent_type read-only**:Plan(架构 subagent type)没 Write 工具,只能输出 markdown — Plan 3 我手动落,Plan 1 用 Bash heredoc 变通 — Plan 2 落简化 task 索引版(完整 CSS 走 mockup SoT)。Lesson:dispatch subagent 时注意 subagent_type 的工具权限
- **mypy timeline sort key**:`dict[str, object]` 的 lambda x: x["date"] 返 object,object 不 implement `__lt__`,需 `str(x["date"])` 显式 coerce
- **Jinja2 include 不传播 loop 变量**:`_story_card.html` 用 `{{ loop.index }}` 失败,需在 parent for 内 `{% set sc_index = loop.index %}` 先捕获

## 不留 done 卡的"已完整完成"项

mockup-v2.html(plan 起草过程产物)留作 design SoT,不删除,后续 v3+ polish 改它做基底。
