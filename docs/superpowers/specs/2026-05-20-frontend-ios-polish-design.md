# Frontend iOS Polish — Studio Direction Design

| field | value |
|---|---|
| 日期 | 2026-05-20 |
| 类型 | Spec(brainstorming 收口) |
| 范围 | 前端 chat 主路径视觉重塑 |
| 工期 | ~1.5-2 周 wall time(Phase A-G) |
| 数据层 | 零改动 |
| 设计风格 | iOS 简约淡雅(systemBlue + SF Pro + 大圆角 + 气泡 + 毛玻璃) |
| 上一版风格 | "AlphaScout Editorial × Terminal"(已废弃) |

---

## § 1 问题陈述

### 1.1 痛点

用户使用频次最高的 chat 主路径(`/chat/landing` + `/chat/:session_id`)视觉观感"不够精美",影响产品作为个人作品集的对外呈现质量。Brainstorm 阶段确认 3 个具体痛点(按致命度排序):

1. **(A · 致命)设计 token 几乎没被消费** — `frontend/src/styles/tokens.css` 写好了完整"AlphaScout Editorial × Terminal"设计语言(暖纸色 `#f8f5ee` + ink + accent + Fraunces 衬线),但 `frontend/src/styles/chat.module.scss` 实际使用 antd 默认蓝 `#1677ff` / 灰 `#d9d9d9` / 红 `#ff4d4f` 等硬编码颜色。设计语言挂在墙上,核心路径完全没接通。
2. **(B)Sidebar / TopBar 是裸 div + inline style** — `layout/app-shell/sidebar.tsx` 仅 `padding:12, gap:12, borderRight:'1px solid #eee'`;`top-bar.tsx` 是 `height:56, borderBottom:1px solid #eee` 加一行硬编码标题 + emoji icon。无任何字体/留白/层级设计,视觉气质等同 admin 后台。
3. **(C)消息流缺视觉层级** — 用户消息和 AI 消息无气泡区分;tool card 用 antd 灰 `#fafafa`,research report card 用 antd 蓝 `#f0f7ff`,系统消息又是另一套色 — 每种 message type 各自一套配色,串起来像"拼贴画"而非统一对话流。

### 1.2 根因

不是"没设计语言",是"已有设计语言没贯彻"。`tokens.css` 是 dead infrastructure;`chat.module.scss` 233 行 SCSS 没消费任何 token;`layout` 组件完全没接入 `themed-root` 的 antd ConfigProvider 之外的视觉系统。

### 1.3 风格方向决策

经 brainstorm visual companion 对比三个方向(Wire-up Polish / Editorial Polish / Studio Polish)后,**重新选择视觉锚** — 推翻"AlphaScout Editorial × Terminal"(Fraunces 衬线 + JetBrains Mono eyebrow + 暖纸色),用户明确拒绝该方向("太学术风"),改走 **iOS 简约淡雅风**(systemBlue + SF Pro + 大圆角 + 气泡 + 微妙阴影 + 毛玻璃)。Mockup 已被用户确认对味,见 `.superpowers/brainstorm/13649-1779290016/content/mockup-ios-v1.html`。

工作量档位选 **Studio Polish**(方向 3,~1.5-2 周),覆盖完整状态系统 + 杂质清理。

---

## § 2 设计目标 / 非目标

### 2.1 目标

| ID | 描述 |
|---|---|
| G1 | Chat 主路径(session + landing)整屏视觉达 iOS 简约淡雅水准 |
| G2 | Sidebar / TopBar 从"裸 div"升级到精修组件 |
| G3 | 消息流统一视觉语言(user 气泡 / AI 气泡 / tool / report / system 同一套色板与圆角) |
| G4 | 全套状态系统(Empty / Loading / Skeleton / Error)统一,替代当前各组件各写一套 |
| G5 | `tokens.css` 真正被消费,通过 CSS Module + antd ConfigProvider 双轨接通 |
| G6 | 杂质清理(emoji → SVG icon · debug log 移除 · 硬编码 antd 默认色清除) |

### 2.2 非目标(YAGNI)

| ID | 描述 | Why not |
|---|---|---|
| N1 | 暗色模式 | v0.9.x 仍 light-only;留 token hook,实现等明确需求 |
| N2 | 国际化设计 | 中文优先,Fraunces 衬线英文倾向是被拒因素之一 |
| N3 | 完整移动端响应式 | 桌面优先;monitoring 等少数页面已有 mobile fallback,不在本 polish 范围 |
| N4 | 自定义主题切换 UI | 用户没要求,且增加复杂度 |
| N5 | 数据层 / API 改动 | 零改动 — useChatSSE / valtio / Pydantic schema / SSE 协议全部保留 |
| N6 | research / monitoring / memory / knowledge / auth 页面 polish | 本轮范围只覆盖 user 选定的 chat session + sidebar + 组件级细节(B + C + J),其他页面留下一版 |

---

## § 3 设计风格决策

### 3.1 问题陈述

如何在已有 antd 5 + valtio + React 19 技术栈上落地 iOS 简约淡雅风?

### 3.2 业界 alternatives

| 选项 | 代表产品 | 字体 | 圆角 | 阴影 | accent | 适用 |
|---|---|---|---|---|---|---|
| A. iOS HIG 严格遵循 | Apple Notes / Messages / Calendar | SF Pro Display + SF Pro Text | 8-16px | 极细微 | systemBlue #007aff | macOS-first,主线选择 |
| B. iOS 启发 + 现代变体 | Linear / Things 3 / Bear | Inter / SF Pro | 6-12px | 中等 | 自定 indigo / purple | 跨平台稳定,字体兼容 |
| C. iOS + Material Hybrid | Notion / Craft | Inter / SF Pro | 8-12px | 中等 | brand 色 | 跨平台 + 富功能 |
| D. iOS Glassmorphism(iOS 17 风) | Apple Vision / iOS 17 settings | SF Pro | 12-20px | + backdrop-blur | 半透明 + accent | 视觉重,移动端首选 |

### 3.3 Tradeoff

- A 最贴近用户审美锚("Apple 简约淡雅"),但 SF Pro 在 Windows fallback 后字重略糙(可接受,macOS 用户占主)
- B 跨平台兼容性最好(Inter 是 web font),但视觉气质更"Linear 产品风"而非"Apple 产品风",偏离用户期望
- C 信息密度高,但视觉气质偏"工具",不够"淡雅"
- D 视觉最潮(iOS 17 风),但 backdrop-blur 在老硬件 fallback 后体验下降明显

### 3.4 我们的取舍

**选 A 为主线 + D 的局部毛玻璃**(仅 TopBar + Input region 用 `backdrop-filter: blur(20px)`,带 solid fallback)。理由:
- 用户作品集导向,macOS-first 部署(Codex / VSCode / Chrome on Mac)
- SF Pro 通过 `-apple-system` 系统字体降级,无需 web font 体积成本
- 局部 glassmorphism 提供"iOS 17 现代感",但不全屏使用避免性能/兼容问题

### 3.5 量化评估方案

| 指标 | 当前 | 目标 |
|---|---|---|
| `chat.module.scss` 硬编码颜色数 | 25 处(`#1677ff` / `#52c41a` / `#999` / `#d9d9d9` / `#eee` / `#f0f0f0` / `#f0f7ff` / `#fafafa` / `#ff4d4f` / `#ffe58f` / `#fff` / `#fff2f0` / `#fffbe6`,共 13 类) | 0(全部走 token) |
| `tokens.css` 实际被消费的 selector 数 | 极少 — `main.tsx` 已 import 但 `chat.module.scss` 等 0 次使用 `var(--as-*)` | ≥30 个 selector via `var(--ios-*)` 跨 5+ 文件 |
| `InputArea.tsx` DEBUG log | 5 处 | 0 |
| Emoji 在生产 jsx 中(本范围内 chat 主路径) | 2 处(`top-bar.tsx` 📋 / `InputArea.tsx` ⚡) | 0(全换 SVG icon) |
| Emoji 在非本范围(`research/new.tsx` backend summary prefix `📋`) | 2 处 | 保留(out of scope,且来源是 backend summary 字符串而非视觉系统) |
| `data-testid` 锚定的现有测试 PASS 率 | 100% | 100%(必须保持) |
| Dogfood "整屏第一印象" | "admin 后台" | "iOS Notes / Messages 级简洁感" |

---

## § 4 Token 系统重构

### 4.1 问题陈述

`tokens.css` 现存语义命名(`--as-bg` `--as-ink` `--as-accent` `--as-gold` `--as-font-display`)绑定 editorial 设计语言。改风格需要决定:**完全重写命名空间 vs 保留命名换值**。

### 4.2 alternatives

| 选项 | 操作 | 影响范围 |
|---|---|---|
| A. 重写命名(`--as-*` → `--ios-*`) | 全站 grep + 替换 | 假设当前 `--as-*` 引用数 ≤ 5,代价小;但破坏 `tokens.css` 现有 utility class(`.as-display` / `.as-eyebrow` / `.as-numeric`)语义 |
| B. 保留命名 + 重定义值 + 重命名语义 | 只改 `tokens.css` 内部 | 不改 import / 不改引用,但命名(`--as-gold`)和实际值(iOS 蓝)语义错位,后期维护混乱 |
| C. 保留 `--as-*` 命名空间 + 新增 `--ios-*` 命名空间 | 双系统并存,旧 token 留 fallback | 命名清晰,但增加冗余;antd ConfigProvider 走 `--ios-*` |

### 4.3 我们的取舍

**选 C(双命名空间)+ 删除明显冲突的旧 utility class**。理由:
- 当前 `--as-*` 几乎没人用(grep 验证),保留作 v0 fallback 风险低
- `--ios-*` 新命名空间语义清晰,后续所有新代码统一走该命名
- 删除 `tokens.css` 中的 `.as-display`(Fraunces serif 触发 web font 不必要请求)、`.as-eyebrow`(editorial 专用)、`.as-shimmer`(用 iOS 风 skeleton 替代);保留 `.as-numeric`(改值为 SF Mono)

### 4.4 完整 token 表

```css
/* === iOS 简约淡雅 token 系统 === */
:root {
  /* ── Color · iOS HIG 浅色模式 ─────────────────────────── */
  --ios-bg: #ffffff;                       /* primary background */
  --ios-bg-grouped: #f2f2f7;               /* systemGroupedBackground */
  --ios-bg-secondary: #f9f9fb;             /* tertiary surface */
  --ios-surface: #ffffff;
  --ios-surface-tinted: #fafafa;
  --ios-surface-hover: rgba(0, 0, 0, 0.025);

  --ios-label: #000000;                    /* primary text */
  --ios-label-secondary: rgba(60, 60, 67, 0.6);
  --ios-label-tertiary: rgba(60, 60, 67, 0.3);
  --ios-label-quaternary: rgba(60, 60, 67, 0.18);

  --ios-separator: rgba(60, 60, 67, 0.12);
  --ios-separator-opaque: #e5e5ea;

  --ios-blue: #007aff;                     /* systemBlue */
  --ios-blue-hover: #006fe6;
  --ios-blue-soft: #e8f1ff;
  --ios-indigo: #5856d6;
  --ios-green: #34c759;                    /* systemGreen */
  --ios-orange: #ff9500;
  --ios-red: #ff3b30;                      /* systemRed */
  --ios-purple: #af52de;

  /* gradient(logo/icon) */
  --ios-grad-primary: linear-gradient(135deg, #007aff 0%, #5856d6 100%);
  --ios-grad-warm: linear-gradient(135deg, #ff9500, #ff3b30);

  /* ── Radius ──────────────────────────────────────────── */
  --ios-radius-sm: 8px;
  --ios-radius: 12px;
  --ios-radius-lg: 16px;
  --ios-radius-xl: 20px;
  --ios-radius-pill: 999px;

  /* ── Shadow ─────────────────────────────────────────── */
  --ios-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
  --ios-shadow: 0 2px 8px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.03);
  --ios-shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.06), 0 2px 6px rgba(0, 0, 0, 0.04);
  --ios-shadow-accent: 0 2px 6px rgba(0, 122, 255, 0.3);  /* send button */

  /* ── Glassmorphism(局部) ───────────────────────────── */
  --ios-glass-bg: rgba(255, 255, 255, 0.72);
  --ios-glass-blur: saturate(180%) blur(20px);

  /* ── Typography ──────────────────────────────────────── */
  --ios-font:
    -apple-system, 'SF Pro Text', 'SF Pro Display',
    'PingFang SC', 'Helvetica Neue', system-ui, sans-serif;
  --ios-font-mono:
    'SF Mono', ui-monospace, 'JetBrains Mono', 'Menlo', monospace;

  /* ── Layout(语义化) ─────────────────────────────── */
  --ios-sidebar-w: 280px;
  --ios-topbar-h: 56px;
  --ios-chat-max-w: 760px;
  --ios-input-radius: 22px;  /* 胶囊输入框 */

  /* ── Legacy(deprecated · 仅 fallback) ──────────────── */
  /* 留住 --as-* 命名空间避免突然断;新代码不要用,见 § 4.3 */
}
```

### 4.5 antd ConfigProvider 主题映射

`themes/index.tsx` 输出的 `ThemeConfig.token`:

```typescript
{
  colorPrimary: '#007aff',          // iOS blue
  colorSuccess: '#34c759',
  colorWarning: '#ff9500',
  colorError: '#ff3b30',
  colorBgBase: '#ffffff',
  colorBgLayout: '#f2f2f7',
  colorBorder: 'rgba(60, 60, 67, 0.12)',
  colorBorderSecondary: '#e5e5ea',
  colorText: '#000000',
  colorTextSecondary: 'rgba(60, 60, 67, 0.6)',
  borderRadius: 10,
  borderRadiusLG: 14,
  borderRadiusSM: 8,
  fontFamily: "-apple-system, 'SF Pro Text', 'PingFang SC', 'Helvetica Neue', system-ui, sans-serif",
  fontSize: 14,
}
```

外加 component-level overrides(`components.Button` `components.Input` `components.Modal`):borderRadius 校准、Button height、Input padding 等。

---

## § 5 组件清单 + 设计契约

### 5.1 改写清单(13 个)

| 文件 | 改写要点 |
|---|---|
| `layout/app-shell/sidebar.tsx` | inline style → CSS module;加搜索框、按日期分组 session、活跃 session 卡片化、卡片化 nav 与 user-panel |
| `layout/app-shell/top-bar.tsx` | inline style + emoji → CSS module + SVG icon-btn;title + sub 双行结构;毛玻璃 backdrop-blur |
| `components/sidebar/chat-session-list.tsx` | 按"今天 / 昨天 / 上周 / 更早" group_header 分组;每条 session 显示 title + preview + meta(时间 · turn 数) |
| `components/sidebar/new-chat-button.tsx` | iOS blue 主按钮 + plus icon + ⌘N 键提示 |
| `components/sidebar/page-nav.tsx` | 卡片化容器 + 蓝色 SF Symbols 风 icon |
| `components/sidebar/user-panel.tsx` | 渐变 avatar + 双行信息 + chevron icon |
| `components/chat/ChatPane.tsx` | 容器布局加 cost-strip 行;消息区 max-width 760 + 居中 |
| `components/chat/MessageList.tsx` | react-window 保留;`ESTIMATE_ROW_HEIGHT` 从 96 调到约 120(气泡高度变化);row 间距改 14px gap |
| `components/chat/TextMessage.tsx` | user → 蓝气泡靠右(底右尖角);AI → 灰白气泡靠左 + Analyst badge eyebrow |
| `components/chat/ToolCallCard.tsx` | iOS 圆角卡 14px + 蓝色 24×24 icon-box + 状态绿点 + Mono 数字 |
| `components/chat/ResearchReportCard.tsx` | 渐变 logo icon 38×38 + 大圆角 16px + 胶囊 pill 按钮组 |
| `components/chat/SystemMessage.tsx` | 居中淡色气泡(灰白 + secondary label) |
| `components/chat/StreamingIndicator.tsx` | iOS 跳动三点动画(替换 antd Spin)+ secondary label 文案 |
| `components/chat/InputArea.tsx` | 胶囊 22px 输入框 + 圆形蓝色发送按钮 + escalate 改 SVG icon-btn;**清掉 6 处 DEBUG console.log** |
| `components/chat/CostMeter.tsx` | 胶囊 pill 列表(green dot + label + tabular-nums 数字),非折叠展开,顶栏底部固定一带 |

### 5.2 新建清单(4 个状态组件)

新目录 `frontend/src/components/states/`:

| 文件 | 职责 |
|---|---|
| `EmptyState.tsx` | 三态 variant:`chat-empty`(新会话引导)/ `list-empty`(无 session/告警/报告)/ `search-empty`(检索无果)。共享:80px illustration icon + title + description + optional CTA |
| `Skeleton.tsx` | 两态 variant:`list`(sidebar session list / report list)/ `message`(AI 回复 loading)。iOS 风 shimmer linear-gradient |
| `ErrorState.tsx` | 通用错误展示:icon + 标题 + 描述 + 重试按钮 + reset 链接。陪 ErrorBoundary 使用 |
| `LoadingDots.tsx` | iOS 风三点跳动(单独抽出,StreamingIndicator / 未连接态 / 复用) |

### 5.3 删除清单

| 文件 / 内容 | 原因 |
|---|---|
| `chat.module.scss` 中所有硬编码颜色 | 全替 token |
| `InputArea.tsx` 6 处 `console.log('[DEBUG cancel-button]...')` | 诊断残留 |
| `top-bar.tsx` 中 `'📋 我的画像'` emoji | 替 person.crop icon SVG |
| `InputArea.tsx` 中 `'⚡ 升级到深度研究'` emoji | 替 plus.circle icon SVG |
| `tokens.css` 的 `.as-display` / `.as-eyebrow` / `.as-shimmer` utility class | editorial 专用,删 |
| `tokens.css` 的 `--as-font-display: Fraunces` font-family | 避免不必要 web font 请求 |
| `index.css` 中 `font-family: Inter, Pingfang SC, Microsoft Yahei` | 与新 token 字体栈冲突,改 var(--ios-font) |
| `frontend/src/components/chat/__tests__/InputArea.test.tsx` 中 button name 正则匹配 `/Escalate\|升级到深度研究\|⚡/i` 的 `⚡` 分支 | 切到 SVG icon 后,⚡ 不再是按钮文本一部分;test 的 ⚡ 分支保留作历史兼容(`\|` or-pattern 含旧 emoji 不影响匹配新 button name `升级到深度研究`)|

---

## § 6 状态系统

### 6.1 问题陈述

当前各组件各写一套 loading / empty / error,导致:
- `ChatPane.tsx` empty 是字符串 "开始一个新对话 — 试试问 '工商银行现价多少?'"
- `MessageList` 没 empty
- `chat-session-list` 列表 loading 是 antd Spin
- Tool card 错误是红边 + 红底
- Research report 加载用 progress overlay

需要统一。

### 6.2 设计

`EmptyState` API:

```typescript
interface EmptyStateProps {
  variant: 'chat-empty' | 'list-empty' | 'search-empty'
  title: string
  description?: string
  cta?: { label: string; onClick: () => void; primary?: boolean }
  icon?: ReactNode  // 默认走 variant 内置 icon
}
```

`Skeleton` API:

```typescript
interface SkeletonProps {
  variant: 'list' | 'message' | 'card'
  count?: number  // 默认 3
  height?: number
}
```

`ErrorState` API:

```typescript
interface ErrorStateProps {
  title?: string  // 默认 "出错了"
  description?: string
  onRetry?: () => void
  onReset?: () => void  // 重置上下文 / 回到列表
}
```

### 6.3 接入点

| 接入位置 | 组件 | variant |
|---|---|---|
| ChatPane empty | `EmptyState` | chat-empty,带 4 个推荐 prompt CTA |
| MessageList 加载中(GET /chats/{sid}) | `Skeleton` | message,3 条 |
| chat-session-list 加载中 | `Skeleton` | list,5 条 |
| ToolCallCard 错误 | `ErrorState` | inline 简版 + 重试 |
| ResearchReportCard 错误 | `ErrorState` | 大版 + 重试 + reset |
| 全局 ErrorBoundary | `ErrorState` | 大版 |

---

## § 7 数据层 / 测试 / 可访问性

### 7.1 数据层 — 零改动

- `frontend/src/hooks/useChatSSE.ts` — 完整保留
- `frontend/src/store/current-chat.ts`、`escalation.ts`、`chat-sessions.ts` — 完整保留
- `frontend/src/api/chatApi.ts` — 完整保留
- 后端 `app/sse/`、`app/agents/`、`app/persistence/` — 零改动

CSS Module + 视觉重构**只动渲染层**,不动 hook / store / api / type。

### 7.2 测试策略

**Unit / Component 测试(vitest + RTL)**:
- 现有 `__tests__/*.test.tsx` 全部跑过 — 锚点用 `data-testid`,改 CSS 不应破坏
- 改写过的组件如果有断言依赖 inline style 或 class name,改 `data-testid`(预计 ≤5 处)
- 新建组件 `EmptyState` / `Skeleton` / `ErrorState` / `LoadingDots` 各写 1-2 个最小测试(渲染 + props)

**E2E 测试(Playwright)**:
- 现有 chat 主路径(login → new chat → send → stream → escalate → cancel)跑一遍,不应破坏
- 不新增 E2E case(视觉回归靠 dogfood)

**视觉回归**:
- 无自动测,完全靠 dogfood
- Phase G 投入 1 天 dogfood:每个 page 跑一遍核心 user journey,人眼审视

### 7.3 可访问性

- 所有现有 `aria-label` / `role` 保留
- 新增组件遵循 ARIA:`EmptyState` role=region,`Skeleton` role=status + aria-live=polite,`ErrorState` role=alert
- 颜色对比度:`--ios-label-secondary`(rgba 60% 黑) vs 白底 = 8.6:1,通过 WCAG AAA;`--ios-blue` vs 白底 = 4.5:1,通过 AA
- 键盘导航:Sidebar session 用 `<a>` 走 React Router,Tab 顺序与现有保持

---

## § 8 工作量分解

### 8.1 Phase 分解

| Phase | 任务范围 | 工期 | 依赖 |
|---|---|---|---|
| **A · Token foundation** | 重写 `tokens.css`、`themes/index.tsx` ConfigProvider token、`index.css` 字体栈、更新 `frontend/CLAUDE.md` 设计语言说明 | ~2 天 | — |
| **B · AppShell rewrite** | `sidebar.tsx` + `top-bar.tsx` + 4 个 sidebar 子组件 + CSS module 新建 | ~2 天 | A |
| **C · Message stream rewrite** | `ChatPane` + `MessageList` + `TextMessage` + `ToolCallCard` + `ResearchReportCard` + `SystemMessage` | ~2-3 天 | A, B |
| **D · Input + meter + streaming** | `InputArea`(含 debug log 清理) + `CostMeter` + `StreamingIndicator` | ~1 天 | A |
| **E · State system** | 新建 `EmptyState` / `Skeleton` / `ErrorState` / `LoadingDots` + 全站接入点替换 | ~1-2 天 | A |
| **F · Cleanup** | emoji → SVG icon · 硬编码 antd 色清扫 · legacy utility class 删除 · index.css 字体栈刷新 | ~0.5 天 | A-E |
| **G · Dogfood + README + 视觉调优** | 完整用户旅程跑 3 轮 / 截屏对比 / 刷 frontend README / 微调字号间距 | ~1 天 | A-F |
| **总计** | | **~9.5-11.5 天** | |

按 user 长程任务三段式槽位 + Claude Code wall time 加速(写代码 ~2-3x),实际人 wall time 可压缩到 ~1.5 周。

### 8.2 Phase 依赖图

```
A(Token) ──→ B(AppShell) ──┐
        ├──→ C(Messages) ──┤
        ├──→ D(Input)──────┤
        └──→ E(States)─────┤
                            ├──→ F(Cleanup) ──→ G(Dogfood + Ship)
```

A 是关键路径前置;B/C/D/E 可在 A 完成后并行(若多机/多 session);F/G 串行收尾。

---

## § 9 风险与缓解

| ID | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R1 | antd ConfigProvider 切换破坏其他 antd 组件视觉(其他页面不在本范围,但 antd 主题全站生效) | 中 | 中 | 切换后 smoke 跑全站每个 page(research / monitoring / memory / knowledge / auth),发现破坏 inline override |
| R2 | `MessageList` react-window `ESTIMATE_ROW_HEIGHT` 失准 → 滚动跳动 / overscan 失效 | 中 | 中 | Phase C 重新校准估算值,跑 5 类 message 实际渲染高度 |
| R3 | `backdrop-filter: blur` 在 Firefox/Safari 老版本 fallback 后变 solid 失真 | 低 | 低 | `@supports` query 双 fallback:不支持时降到纯色 |
| R4 | SF Pro 在 Windows 用户机器降级显示糙 | 低 | 低 | macOS-first 接受;Windows 兜底字体栈 'Segoe UI' |
| R5 | 测试 fixture 依赖 inline style 或 class name(`#1677ff` / `#fafafa` 等具体值)→ 改色后 break | 中 | 低 | Phase A 完成后跑全套 unit test,失败的逐个改 `data-testid` 锚点 |
| R6 | dogfood 阶段发现 mockup 与实际渲染细节差异(字号/间距/微动画)→ 反复回滚 | 高 | 低 | Phase G 留 1 天专门微调,接受 80/20 — 不追求像素级完美 |
| R7 | tokens.css 残留 utility class(`.as-numeric` 等)在其他文件被引用 | 低 | 低 | grep 全站 `as-numeric` / `as-display` 等,确认引用数 |

---

## § 10 评估指标

### 10.1 客观可量化

| 指标 | 当前 | 目标 | 验证方式 |
|---|---|---|---|
| `chat.module.scss` 硬编码颜色实例数 | 25(13 类色值) | 0 | `grep -oE '#[0-9a-fA-F]{3,8}' frontend/src/styles/chat.module.scss \| wc -l` |
| `var(--ios-*)` 在 frontend/src/styles 与组件 CSS module 内被引用 selector 数 | 0 | ≥30 跨 ≥5 文件 | `grep -rE 'var\(--ios-' frontend/src/ \| wc -l` |
| `InputArea.tsx` DEBUG log | 5 | 0 | `grep -c "DEBUG" frontend/src/components/chat/InputArea.tsx` |
| Emoji 在 chat 主路径生产 jsx(top-bar + InputArea) | 2(📋 + ⚡) | 0 | `grep -E '[📋⚡]' frontend/src/layout/app-shell/top-bar.tsx frontend/src/components/chat/InputArea.tsx` |
| Unit test PASS 率 | 100% | 100% | `npm test` |
| E2E PASS 率 | 100% | 100% | `npx playwright test` |
| WCAG AA 对比度通过率 | 部分 | 100%(主色板) | manual via Chrome DevTools |

### 10.2 主观(dogfood)

- "第一眼印象"测试:在新会话窗口打开 `/chat/landing`,3 秒内观感 — 应感觉"iOS Notes / Messages 级简洁感",而非"admin 后台"
- 完整用户旅程:登录 → 新对话 → 发送 → 看 stream → tool 调用 → research card 出现 → escalate → cancel → 回历史 → 重命名 — 每一环都没违和感
- 长会话滚动:50+ 条消息混合 user / AI / tool / report,滚动顺滑,无视觉跳跃

---

## § 11 决策日志(brainstorming 浓缩)

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| D1 | 设计风格方向 | iOS 简约淡雅(Apple HIG-leaning) | user 明确拒绝 editorial / 学术风;偏好 Apple Notes / Messages 感 |
| D2 | 工作量档位 | Studio Polish(方向 3) | 覆盖完整状态系统 + 杂质清理,作品集级精细;接受 ~1.5 周投入 |
| D3 | Token 命名空间 | `--ios-*` 新空间 + `--as-*` legacy 保留 fallback | 命名清晰,迁移成本低 |
| D4 | antd theme 接管 | ConfigProvider 全量 token override + component overrides | 一处改全站生效;无需逐组件 wrap |
| D5 | 消息形态 | iOS Messages 风气泡(用户蓝靠右 / AI 灰白靠左) | 视觉层级最强,user 已接受 mockup |
| D6 | 毛玻璃使用范围 | 局部(TopBar + InputRegion) + solid fallback | 兼顾现代感与兼容性 |
| D7 | 状态系统 | 抽出 4 个新组件统一接入 | 当前各组件各写一套,统一可省维护成本 |
| D8 | 数据层改动 | 零改动 | 视觉重塑只动 render,不动 hook/store/api |
| D9 | 范围 | chat session + sidebar + chat 组件(对应 user 选 B+C+J) | research / monitoring / memory 等留下一版,避免范围爆炸 |
| D10 | 工期估算口径 | wall time + Claude Code 加速 | 9.5-11.5 calendar 天 → ~1.5 周 wall time |

---

## § 12 下一步

本 spec 写完后:
1. `commit` to git
2. user review spec
3. 通过后调用 `writing-plans` skill 起草 14-task 左右的 implementation plan(对应 Phase A-G)
4. plan 通过后进入 executing-plans

writing-plans 不在本 spec 范围。
