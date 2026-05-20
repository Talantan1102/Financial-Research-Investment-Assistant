# ETCLOVG Migration — Plan 3: iOS Calm Minimal 视觉重做 + 模板维度切换

> Plan 3 已实施完成,本文档作 ship 记录(不作执行模板)。

**Spec:** [`docs/superpowers/specs/2026-05-20-harness-board-etclovg-migration-design.md`](../specs/2026-05-20-harness-board-etclovg-migration-design.md)
**Plan 1:** `2026-05-20-etclovg-migration-plan1-config-types.md`
**Plan 2:** `2026-05-20-etclovg-migration-plan2-data-migration.md`

**版本归位**: v0.9.x harness-board ETCLOVG migration · **分支**: `refactor/etclovg-migration` · **PR(合并 Plan 1+2+3 一个 PR)**

**Goal**: 把视觉语言整套从 V2 Quiet Workshop 暖黑作坊切到 iOS Calm Minimal 浅色淡雅(spec § 4A)。Plan 1+2 完成信息结构层,Plan 3 完成视觉层。

---

## 实施总结

### 视觉切换核心策略:token-driven CSS 重做

不重写 2731 行 style.css 全文,而是**只换 `:root` token + 删 3 处装饰元素**,让现有所有 `var(--ink) / var(--fg) / var(--amber)` 调用通过 CSS 变量继承自动切到新调色。

**改动文件**:

| 文件 | 改动 |
|---|---|
| `dashboard/static/style.css` | `:root` 50 行 token 全替换 (浅色 + indigo + SF Pro + radius + shadow + blur);`body` baseline 从 `--ink` 改 `--bg`;删除 `body::before` grain overlay;`.layer .numeral { display: none }`;`.story-card .body p:first-of-type::first-letter` no-op;dot dim 7 维新 class + V2 alias 渐变 |
| `dashboard/static/overview.js` | `DIM_COLORS` 8 维替 7 维 iOS hues;`confidenceBorder` stops 从暖灰渐变改 iOS soft gradient |
| `dashboard/templates/_hero.html` | fingerprint SVG 重做:8 spoke → 7 spoke 等分 51.4°;V2 amber 高光维 (memory) → V3 indigo 高光维 (context);amber/teal 双色 → indigo 单色;Newsreader italic H → SF Pro 系统 H;hero pill "v0.9.6 · workshop" → "v0.9.7 · ETCLOVG";"8 维" 描述 → "ETCLOVG 7 维" |
| `dashboard/templates/overview.html` | `DIM_SHORT` 8→7 维新 ETCLOVG label |
| `dashboard/templates/story.html` | 同上 |
| `dashboard/templates/survey.html` | 同上 + 顶部注释 + sm-desc "8 维度" → "ETCLOVG 7 维度" |
| `dashboard/templates/_d_view.html` | 同上 + sm-title "8 维 × N" → "ETCLOVG 7 维 × N" |
| `dashboard/templates/flashcards_stats.html` | inline JS `DIM_COLORS` + `DIM_ORDER` 8→7;`gradeColor` 0/5 端点 V2 amber/sage → iOS orange/green |

### V2 token 别名兼容层(避免一次性全 sweep)

保留以下 V2 token 名指向新 iOS 调色:
- `--amber` → `#5E5CE6` (= --accent)
- `--teal` → `#6E6E73` (灰阶,不再是次强调)
- `--ink` → `#F5F5F7` (= --bg,V2 调用方仍能用)
- `--paper` → `#FFFFFF` (= --surface)
- `--dim-prompt` / `--dim-tools` / `--dim-orch` / `--dim-memory` / `--dim-rag` / `--dim-guard` / `--dim-eval` / `--dim-cost` → 映射到对应的新 ETCLOVG dim hue

这样:
- 2731 行 CSS 里使用 `var(--amber)` `var(--ink)` 等 V2 token 的 selector 自动继承新调色
- 不需要一次性 sweep 全 selector(YAGNI)
- 后续 Plan 4+ 可以渐进 sweep 把 V2 别名删掉

### 装饰元素策略(§ 4A.4)

| 元素 | V2 状态 | V3 处理 |
|---|---|---|
| Body grain overlay (SVG noise) | 0.035 opacity 全屏覆盖 | **删除** (`body::before` 整段移除) |
| Numeral 水印 (.layer .numeral, 86px serif) | top-right 卡片角落 paper-2 色 | **display: none** (保留 selector 避免模板引用报错) |
| Drop cap (.story-card .body ::first-letter, 56px italic amber) | 段首大字 | **no-op** (空规则块,删 CSS 但保 selector) |
| Hairline 虚线 | V2 用 dashed | **保留**(2731 行 selector 多处用 dashed,YAGNI 不一次清;视觉因 token 变浅 + bg 转白后整体已显著弱化) |
| Fingerprint SVG | 8 spoke amber+teal 双色 + Newsreader italic H | 7 spoke 单色 indigo + SF Pro 系统 H + context 维 indigo 高光(替换 memory amber 高光语义) |

---

## ship 验收

| 验收项 | 结果 |
|---|---|
| pytest dashboard | **0 fail / 3 skipped** ✓ |
| mypy dashboard 全量 | **0 errors / 74 source files** ✓ |
| ruff check + format | **all checks passed** ✓ |
| 6 页面渲染 (/ + /overview + /story + /survey + /flashcards/stats + /decisions) | **全 200**,无 5xx ✓ |
| graph json | 69 nodes / 24 edges / 7 ETCLOVG dim ✓ |
| fingerprint | 7 spoke 等分 51.4°,单色 indigo,context 维高光 ✓ |
| 视觉切换 | bg `#F5F5F7`,fg `#1D1D1F`,accent `#5E5CE6` indigo,SF Pro 字体生效 ✓ |
| 装饰移除 | grain overlay / numeral / drop-cap 全删 ✓ |
| V2 token 兼容 | `--amber` / `--ink` 等别名指向新色,V2 selector 继承不破坏 ✓ |

---

## 关联

- 上游 Plan 1:配置 + 类型 + 重归属
- 上游 Plan 2:数据迁移 + 测试 golden
- Memory 沉淀:`project_etclovg_migration_2026-05-20.md`(三 plan 整体闭环)
- 合并 PR 标题:`feat(harness-board): ETCLOVG 7 维迁移 + iOS Calm Minimal 视觉重做`

## 后续 v3 polish(本 plan 不做,留给 Plan 4)

- 2731 行 CSS 中 `var(--amber)` / `var(--teal)` / `var(--ink)` 等 V2 token 完整 sweep 改为 `var(--accent)` / `var(--bg)` 等新名(目前别名兼容,YAGNI)
- mockup-v3.html self-contained 视觉稿(本 plan 直接改 CSS + 模板,跳过 mockup 节省 0.5 天 — 但 spec § 4A.6 仍建议起草作为长期 design SoT)
- 13 个模板的 dashed border / serif 残留 selector 精修
- 鸟瞰 cytoscape 节点 hover overlay 用 indigo 替换 amber(目前 CSS variable 继承已切换,JS 层 hex 也已切;视觉对照可能仍需微调)
- Dark Mode (决议 § 10.Q1 明确不做,本期 YAGNI)
