# Frontend iOS Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish chat 主路径(landing + session + sidebar + topbar + 所有 chat 组件 + 状态系统)到 iOS 简约淡雅风;数据层零改动。

**Architecture:** 两层接通 — `frontend/src/styles/tokens.css` 暴露 `--ios-*` CSS var 给 CSS Module 直接消费;`frontend/src/themes/tokens-retail.ts` 喂 antd ConfigProvider(chat 主路径走 retail theme)。新建 `frontend/src/components/states/*` 统一空/加载/错误/skeleton 视觉。复用全部现有 hook / valtio store / API / SSE 协议。

**Tech Stack:** React 19 + antd 5.24 + valtio 2 + Vite + vitest + Playwright + iOS HIG token system

**Spec:** `docs/superpowers/specs/2026-05-20-frontend-ios-polish-design.md`

**Important constraints:**
- 数据层零改动(`hooks/useChatSSE.ts` / `store/*` / `api/*` / `types/*` 不动)
- 现有 `data-testid` 锚定的 unit test 必须 100% 保持 PASS
- antd 主题切换走 dual theme 中的 `tokens-retail.ts`(`tokens-banking.ts` 不动 — 服务 monitoring/credit-report,不在本范围)
- Commit 类型用 `feat` / `chore` / `refactor`(非 `fix`),无须 `原因 layer:` 标记
- Token 数值唯一来源是 spec § 4.4,plan 引用 var 名,不重复值

---

## File Structure

### 新建文件

| 路径 | 责任 |
|---|---|
| `frontend/src/styles/app-shell.module.scss` | Sidebar / TopBar / 子组件 CSS module |
| `frontend/src/components/states/EmptyState.tsx` | 三态空状态(chat-empty / list-empty / search-empty) |
| `frontend/src/components/states/EmptyState.module.scss` | EmptyState 样式 |
| `frontend/src/components/states/Skeleton.tsx` | 列表 / 消息 / 卡片 skeleton |
| `frontend/src/components/states/Skeleton.module.scss` | Skeleton 样式(linear-gradient shimmer) |
| `frontend/src/components/states/ErrorState.tsx` | 错误展示 + 重试 + reset |
| `frontend/src/components/states/ErrorState.module.scss` | ErrorState 样式 |
| `frontend/src/components/states/LoadingDots.tsx` | iOS 跳动三点(单独抽出可复用) |
| `frontend/src/components/states/LoadingDots.module.scss` | LoadingDots 样式 |
| `frontend/src/components/states/__tests__/EmptyState.test.tsx` | RTL test |
| `frontend/src/components/states/__tests__/Skeleton.test.tsx` | RTL test |
| `frontend/src/components/states/__tests__/ErrorState.test.tsx` | RTL test |
| `frontend/src/components/states/__tests__/LoadingDots.test.tsx` | RTL test |
| `frontend/src/components/shared/Icon.tsx` | SF Symbols 风 SVG icon library(替 emoji 用) |

### 修改文件

| 路径 | 改动要点 |
|---|---|
| `frontend/src/styles/tokens.css` | 重写为 iOS token 表;`--as-*` 保留 fallback,新加 `--ios-*`;删除 `.as-display` / `.as-eyebrow` / `.as-shimmer` utility |
| `frontend/src/themes/tokens-retail.ts` | antd token 全替为 iOS HIG(`#007aff` / 灰阶 / 圆角 / 字体);新增 component-level override |
| `frontend/src/themes/tokens-base.ts` | 字体栈去 Microsoft YaHei,SF Pro 优先;`semantic.error` 改 `#ff3b30`(iOS red) |
| `frontend/src/index.css` | 字体栈 `font-family` 改为 `var(--ios-font)`;print 样式保留 |
| `frontend/src/layout/app-shell/sidebar.tsx` | inline style → `app-shell.module.scss` class;新结构(brand-row + search-box + new-chat + groups + nav + user-panel) |
| `frontend/src/layout/app-shell/top-bar.tsx` | inline style + emoji → CSS module + SVG icon-btn;title + sub 双行;backdrop-blur 毛玻璃 |
| `frontend/src/components/sidebar/chat-session-list.tsx` | `antd List` → 自渲染 div 列表;按日期 group(今天 / 昨天 / 上周 / 更早);每条显示 title + preview + meta |
| `frontend/src/components/sidebar/new-chat-button.tsx` | 文案 `+ New Chat` → `新对话` + plus icon + ⌘N 提示 |
| `frontend/src/components/sidebar/page-nav.tsx` | 卡片化容器(参考 mockup `nav-list` div)+ 蓝色 SVG icon |
| `frontend/src/components/sidebar/user-panel.tsx` | 渐变 avatar + 双行信息 + chevron icon |
| `frontend/src/styles/chat.module.scss` | 全 `#xxxxxx` 替为 `var(--ios-*)`;调整气泡、tool、report、composer、cost 等 25+ block |
| `frontend/src/components/chat/ChatPane.tsx` | 容器布局加 `cost-strip` 行(从 CostMeter 改用);消息区 `max-width: 760px` + 居中 |
| `frontend/src/components/chat/MessageList.tsx` | `ESTIMATE_ROW_HEIGHT = 96` → 校准到实际值;`gap` 14px;不改 react-window 主结构 |
| `frontend/src/components/chat/TextMessage.tsx` | user 气泡(`--ios-blue` 靠右) / AI 气泡(`--ios-surface` 靠左 + Analyst badge) |
| `frontend/src/components/chat/ToolCallCard.tsx` | iOS 圆角卡 14px + 蓝色 icon-box 28×28 + 状态绿点 + Mono 数字 |
| `frontend/src/components/chat/ResearchReportCard.tsx` | 渐变 logo icon 38×38 + 大圆角 16px + pill 按钮组 |
| `frontend/src/components/chat/SystemMessage.tsx` | 居中淡色气泡(secondary label + 圆角) |
| `frontend/src/components/chat/StreamingIndicator.tsx` | antd Spin → `LoadingDots`(iOS 跳动三点) |
| `frontend/src/components/chat/InputArea.tsx` | 胶囊 22px 输入框 + 圆形蓝色发送按钮 + escalate `<Icon>` 替代 ⚡;**清掉 5 处 `console.log('[DEBUG cancel-button]...')`** |
| `frontend/src/components/chat/CostMeter.tsx` | 改为顶栏底部 cost-strip(pill 形列表) |
| `frontend/README.md` | 设计语言段更新为 iOS 简约淡雅 |

### 删除内容(在文件内删,不删文件)

| 位置 | 删除什么 |
|---|---|
| `frontend/src/styles/tokens.css` | `.as-display` `.as-eyebrow` `.as-shimmer` utility class;`--as-font-display` Fraunces 字体定义;`@keyframes as-shimmer`(已不用)|
| `frontend/src/index.css` | `Inter, Pingfang SC, Microsoft Yahei` 字体栈 → 用 `var(--ios-font)` |
| `frontend/src/components/chat/InputArea.tsx` | 5 处 `console.log('[DEBUG cancel-button] ...')` |
| `frontend/src/layout/app-shell/top-bar.tsx` | `📋 我的画像` emoji → `<Icon name="user-circle" />` |
| `frontend/src/components/chat/InputArea.tsx` | button label `⚡ 升级到深度研究` emoji → `<Icon name="plus-circle" />` + 中文标签 |

---

## Phase A · Token Foundation

### Task 1: 重写 tokens.css → iOS 风

**Files:**
- Modify: `frontend/src/styles/tokens.css`

- [ ] **Step 1: 备份当前 tokens.css 关键 utility classes(grep 用法引用)**

```bash
grep -rE "(as-display|as-eyebrow|as-shimmer|as-numeric|as-rule)" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.scss" --include="*.css"
```

Expected: 应只剩 `.as-numeric` 有 ≥1 引用(用作 tabular-nums),其他全 0。若 grep 显示有引用,记录到下一步删除前替换。

- [ ] **Step 2: 重写 `frontend/src/styles/tokens.css` 全文**

完整内容(token 值来自 spec § 4.4):

```css
/**
 * iOS 简约淡雅 design token 系统(替代旧 AlphaScout Editorial).
 * Spec: docs/superpowers/specs/2026-05-20-frontend-ios-polish-design.md
 */

:root {
  /* ── Color · iOS HIG 浅色 ─────────────────────────── */
  --ios-bg: #ffffff;
  --ios-bg-grouped: #f2f2f7;
  --ios-bg-secondary: #f9f9fb;
  --ios-surface: #ffffff;
  --ios-surface-tinted: #fafafa;
  --ios-surface-hover: rgba(0, 0, 0, 0.025);

  --ios-label: #000000;
  --ios-label-secondary: rgba(60, 60, 67, 0.6);
  --ios-label-tertiary: rgba(60, 60, 67, 0.3);
  --ios-label-quaternary: rgba(60, 60, 67, 0.18);

  --ios-separator: rgba(60, 60, 67, 0.12);
  --ios-separator-opaque: #e5e5ea;

  --ios-blue: #007aff;
  --ios-blue-hover: #006fe6;
  --ios-blue-soft: #e8f1ff;
  --ios-indigo: #5856d6;
  --ios-green: #34c759;
  --ios-orange: #ff9500;
  --ios-red: #ff3b30;
  --ios-purple: #af52de;

  --ios-grad-primary: linear-gradient(135deg, #007aff 0%, #5856d6 100%);
  --ios-grad-warm: linear-gradient(135deg, #ff9500, #ff3b30);

  --ios-radius-sm: 8px;
  --ios-radius: 12px;
  --ios-radius-lg: 16px;
  --ios-radius-xl: 20px;
  --ios-radius-pill: 999px;

  --ios-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
  --ios-shadow: 0 2px 8px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.03);
  --ios-shadow-lg: 0 8px 24px rgba(0, 0, 0, 0.06), 0 2px 6px rgba(0, 0, 0, 0.04);
  --ios-shadow-accent: 0 2px 6px rgba(0, 122, 255, 0.3);

  --ios-glass-bg: rgba(255, 255, 255, 0.72);
  --ios-glass-blur: saturate(180%) blur(20px);

  --ios-font:
    -apple-system, 'SF Pro Text', 'SF Pro Display',
    'PingFang SC', 'Helvetica Neue', system-ui, sans-serif;
  --ios-font-mono:
    'SF Mono', ui-monospace, 'JetBrains Mono', 'Menlo', monospace;

  --ios-sidebar-w: 280px;
  --ios-topbar-h: 56px;
  --ios-chat-max-w: 760px;
  --ios-input-radius: 22px;

  /* ── Legacy(deprecated · fallback only) ──────────── */
  /* 旧 --as-* 命名空间保留作 fallback,新代码用 --ios-* */
  --as-bg: var(--ios-bg-grouped);
  --as-surface: var(--ios-surface);
  --as-ink: var(--ios-label);
  --as-text-secondary: var(--ios-label-secondary);
  --as-border: var(--ios-separator);
  --as-accent: var(--ios-blue);
}

/* ── Global typography baseline ─────────────────────── */
html, body {
  font-family: var(--ios-font);
  background: var(--ios-bg-grouped);
  color: var(--ios-label);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}

#root { min-height: 100vh; }

::selection { background: var(--ios-blue); color: #fff; }

/* ── Scrollbar(subtle) ──────────────────────────── */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--ios-separator-opaque);
  border: 2px solid var(--ios-bg-grouped);
  border-radius: 6px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--ios-label-tertiary);
}

/* ── Utility classes(retained) ──────────────────── */
.as-numeric {
  font-family: var(--ios-font-mono);
  font-feature-settings: 'tnum';
  font-variant-numeric: tabular-nums;
}
```

注意:删除原文件的 `.as-display` / `.as-eyebrow` / `.as-shimmer` / `@keyframes as-shimmer` / `@keyframes as-pulse` / `.as-rule` / `.as-rule-double` / 旧 `.ant-btn-primary` 等 editorial override block。仅保留 `.as-numeric`(被 chart/report 用),其他全删。

- [ ] **Step 3: 跑全套 unit test 看 baseline 不破**

Run: `cd frontend && npm test 2>&1 | tail -20`

Expected: 测试不应失败 — 只改 `tokens.css`,无组件依赖具体 `--as-*` selector(grep step 1 已验证)。若失败,记录失败 test 名 + 锚点,下一步前修。

- [ ] **Step 4: 在浏览器手动验证 chat 主路径 visual smoke**

Run: `cd frontend && npm run dev`,访问 `http://localhost:5173/chat/landing`。

Expected: 页面不应整体崩(token 改了但没有组件消费 `--ios-*`,所以视觉应跟之前差不多 — 主要是 body 背景从暖纸色 `#f8f5ee` 变为 iOS 灰阶 `#f2f2f7`,字体栈从 Fraunces fallback 变成系统字体)。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/tokens.css
git commit -m "$(cat <<'EOF'
refactor(frontend-tokens): 重写 tokens.css 为 iOS HIG 风 token 系统

删除 editorial 命名空间下的 utility class(.as-display / .as-eyebrow /
.as-shimmer / .as-rule),新增 --ios-* 命名空间作主入口,--as-* 留 fallback。
Spec § 4.4 完整 token 表。
EOF
)"
```

---

### Task 2: 重写 themes/tokens-retail.ts(antd retail theme)+ tokens-base.ts(字体栈)

**Files:**
- Modify: `frontend/src/themes/tokens-retail.ts`
- Modify: `frontend/src/themes/tokens-base.ts`

- [ ] **Step 1: 重写 `frontend/src/themes/tokens-base.ts`**

把字体栈中的 `Microsoft YaHei` 去掉,SF Pro 优先;`semantic.up/down/error` 校准:

```typescript
/**
 * Base design tokens — shared across banking and retail themes.
 * iOS HIG-aligned token values.
 */

export const baseTokens = {
  spacing: {
    xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48,
  },
  radius: {
    sm: 8, md: 12, lg: 16,  // iOS HIG 大圆角
  },
  motion: {
    fast: 150, base: 250, slow: 400,
  },
  fontFamily: {
    sans: '-apple-system, "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", system-ui, sans-serif',
    mono: '"SF Mono", ui-monospace, "JetBrains Mono", "Menlo", Consolas, monospace',
  },
  fontSize: {
    xs: 12, sm: 14, base: 15, lg: 17, xl: 22, xxl: 28,
  },
  semantic: {
    success: '#34c759',  // iOS systemGreen
    warning: '#ff9500',  // iOS systemOrange
    error: '#ff3b30',    // iOS systemRed
    info: '#007aff',     // iOS systemBlue
    // 中国市场涨跌(红涨绿跌)— 走 iOS 红绿但保中国惯例
    up: '#ff3b30',
    down: '#34c759',
  },
} as const;

export type BaseTokens = typeof baseTokens;
```

- [ ] **Step 2: 重写 `frontend/src/themes/tokens-retail.ts`**

```typescript
/**
 * Retail theme — iOS 简约淡雅 (替代 Perplexity-inspired 旧版).
 * 走 chat 主路径(/chat/* + 默认所有 non-banking route).
 */

import { theme } from 'antd';
import type { ThemeConfig } from 'antd';
import { baseTokens } from './tokens-base';

export const retailTokens = {
  background: {
    primary: '#ffffff',
    secondary: '#f2f2f7',   // iOS systemGroupedBackground
    tertiary: '#f9f9fb',
  },
  text: {
    primary: '#000000',
    secondary: 'rgba(60, 60, 67, 0.6)',
    tertiary: 'rgba(60, 60, 67, 0.3)',
  },
  border: {
    base: 'rgba(60, 60, 67, 0.12)',
    strong: '#e5e5ea',
  },
  accent: {
    primary: '#007aff',   // iOS systemBlue
    hover: '#006fe6',
    soft: '#e8f1ff',
  },
  numFontFamily: baseTokens.fontFamily.mono,
} as const;

export const retailThemeConfig: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: retailTokens.accent.primary,
    colorSuccess: baseTokens.semantic.success,
    colorWarning: baseTokens.semantic.warning,
    colorError: baseTokens.semantic.error,
    colorInfo: retailTokens.accent.primary,
    colorBgContainer: retailTokens.background.primary,
    colorBgLayout: retailTokens.background.secondary,
    colorBgElevated: retailTokens.background.primary,
    colorText: retailTokens.text.primary,
    colorTextSecondary: retailTokens.text.secondary,
    colorTextTertiary: retailTokens.text.tertiary,
    colorBorder: retailTokens.border.base,
    colorBorderSecondary: retailTokens.border.strong,
    fontFamily: baseTokens.fontFamily.sans,
    fontSize: baseTokens.fontSize.sm,
    borderRadius: baseTokens.radius.md,
    borderRadiusLG: baseTokens.radius.lg,
    borderRadiusSM: baseTokens.radius.sm,
  },
  components: {
    Button: {
      borderRadius: baseTokens.radius.sm,
      controlHeight: 36,
      fontWeight: 500,
    },
    Input: {
      borderRadius: baseTokens.radius.sm,
      controlHeight: 36,
    },
    Modal: {
      borderRadiusLG: baseTokens.radius.lg,
    },
    Card: {
      colorBgContainer: retailTokens.background.primary,
      borderRadiusLG: baseTokens.radius.lg,
    },
    Tag: {
      borderRadiusSM: baseTokens.radius.sm,
    },
    List: {
      itemPadding: '10px 12px',
    },
  },
};
```

- [ ] **Step 3: 跑全套 unit test**

Run: `cd frontend && npm test 2>&1 | tail -30`

Expected: 所有 test 应 PASS。若有 test 锚定具体颜色字符串(`#1890ff` 之类),改 test 用 `data-testid` 锚点。

- [ ] **Step 4: 浏览器 visual smoke — 检查 banking + retail 双 theme 都不破**

Run: `cd frontend && npm run dev`

访问:
1. `http://localhost:5173/chat/landing`(retail · iOS 蓝) — 检查 antd Button primary 应是 iOS 蓝 `#007aff`
2. `http://localhost:5173/monitoring`(banking · 深色 — 不动) — 检查仍是原 banking 视觉

Expected: retail 路径 antd primary 色从旧蓝 `#1890ff` 变 iOS 蓝 `#007aff`;banking 不动。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/themes/tokens-base.ts frontend/src/themes/tokens-retail.ts
git commit -m "$(cat <<'EOF'
refactor(frontend-theme): retail theme 切到 iOS HIG token 系统

tokens-base 字体栈去 Microsoft YaHei,SF Pro 优先;semantic 色板对齐 iOS
system colors(systemBlue/Green/Orange/Red)。retail antd ConfigProvider 全
量 token 覆盖 + component overrides(Button/Input/Modal/Card/Tag/List)。
banking theme 不动(服务 monitoring/credit-report,非本范围)。
EOF
)"
```

---

### Task 3: 改 index.css(字体栈)+ 跑全站 smoke

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 改 `frontend/src/index.css` 字体栈**

```css
:root {
  background-color: var(--ios-bg-grouped);
  font-size: 14px;
  line-height: 1.5;
  font-family: var(--ios-font);

  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.scrollbar-style {
  scrollbar-width: thin;
}
.scrollbar-style::-webkit-scrollbar {
  width: 8px;
}

/* print 样式段保留不动(/* ─── Print stylesheet 段) — 不动 */
```

保留原 `@media print { ... }` 整个 block 不动。

- [ ] **Step 2: 全站 smoke 测试 — 跑所有 unit test**

Run: `cd frontend && npm test 2>&1 | tail -20`

Expected: 49 test files 全 PASS。

- [ ] **Step 3: 浏览器 smoke 跑每个 page,确认 antd theme 切换不破坏其他页面**

Run: `cd frontend && npm run dev`

访问列表:
1. `/login` — antd Form / Button 渲染正常,primary 色 iOS 蓝
2. `/chat/landing` — chat 入口 layout 不崩
3. `/research` — antd List / Card 渲染正常
4. `/monitoring` — banking 深色 theme 不破
5. `/memory` — Cytoscape + antd Tabs 渲染正常
6. `/knowledge` — antd Upload / Table 渲染正常
7. `/reports` — ReportDetailModal 渲染正常

Expected: 每个 page 都不应整体崩溃。视觉色彩有改变(retail 路径 antd primary 从老蓝换 iOS 蓝)— 这是预期。

- [ ] **Step 4: 跑 Playwright e2e 核心链路**

Run: `cd frontend && npx playwright test 2>&1 | tail -20`

Expected: e2e 全 PASS。若有 test 锚定具体 CSS class 失败,改用 `data-testid`。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/index.css
git commit -m "$(cat <<'EOF'
refactor(frontend-tokens): index.css 字体栈接入 var(--ios-font)

去掉 Inter / Microsoft Yahei 显式声明,统一走 var(--ios-font)。print 样式
段保留不动。Phase A token foundation 完。
EOF
)"
```

---

## Phase B · AppShell Rewrite

### Task 4: 新建 app-shell.module.scss + 重写 sidebar.tsx + top-bar.tsx

**Files:**
- Create: `frontend/src/styles/app-shell.module.scss`
- Modify: `frontend/src/layout/app-shell/sidebar.tsx`
- Modify: `frontend/src/layout/app-shell/top-bar.tsx`
- Test: `frontend/src/layout/app-shell/__tests__/sidebar.test.tsx`(已存在,不改 logic 测试 — 锚点用 `data-testid`)
- Test: `frontend/src/layout/app-shell/__tests__/top-bar.test.tsx`(已存在)

- [ ] **Step 1: 新建 `frontend/src/styles/app-shell.module.scss`**

完整内容(参考 mockup `.superpowers/brainstorm/13649-1779290016/content/mockup-ios-v1.html` 第 56-216 行 sidebar + topbar 部分;token 引用 `var(--ios-*)`):

```scss
/* ── Sidebar ─────────────────────────────────────────── */
.sidebar {
  background: var(--ios-bg-grouped);
  display: flex;
  flex-direction: column;
  padding: 14px 12px;
  gap: 14px;
  border-right: 1px solid var(--ios-separator);
  height: 100%;
  width: var(--ios-sidebar-w);
}

.brandRow {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
}
.brandMark {
  width: 28px; height: 28px;
  border-radius: 8px;
  background: var(--ios-grad-primary);
  display: flex; align-items: center; justify-content: center;
  color: #fff;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: -0.02em;
}
.brandName {
  font-size: 16px;
  font-weight: 600;
  color: var(--ios-label);
  letter-spacing: -0.01em;
}

.searchBox {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(118, 118, 128, 0.12);
  border-radius: 10px;
  padding: 7px 10px;
  margin: 0 2px;

  svg { width: 14px; height: 14px; color: var(--ios-label-secondary); flex-shrink: 0; }
  input {
    border: none; background: transparent; outline: none; flex: 1;
    font-family: inherit; font-size: 14px; color: var(--ios-label);

    &::placeholder { color: var(--ios-label-secondary); }
  }
}

.sessionsScroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.groupHeader {
  font-size: 11px;
  font-weight: 600;
  color: var(--ios-label-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 0 12px;
  margin: 12px 0 4px;
}

/* ── TopBar ──────────────────────────────────────────── */
.topbar {
  height: var(--ios-topbar-h);
  padding: 0 24px;
  background: var(--ios-glass-bg);
  backdrop-filter: var(--ios-glass-blur);
  -webkit-backdrop-filter: var(--ios-glass-blur);
  border-bottom: 1px solid var(--ios-separator);
  display: flex;
  align-items: center;
  gap: 14px;
  position: relative;
  z-index: 10;
}
@supports not (backdrop-filter: blur(20px)) {
  .topbar { background: var(--ios-surface); }
}

.topbarTitleWrap { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.topbarTitle {
  font-size: 15px; font-weight: 600;
  color: var(--ios-label);
  letter-spacing: -0.01em;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.topbarSub {
  font-size: 12px;
  color: var(--ios-label-secondary);
}

.topbarActions { display: flex; gap: 6px; }

.iconBtn {
  width: 34px; height: 34px;
  border-radius: 8px;
  background: transparent;
  border: none;
  color: var(--ios-blue);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.12s;

  &:hover { background: rgba(0, 122, 255, 0.08); }
  svg { width: 18px; height: 18px; }
}
```

- [ ] **Step 2: 重写 `frontend/src/layout/app-shell/sidebar.tsx`**

```tsx
import { useState } from 'react'
import { ChatSessionList } from '@/components/sidebar/chat-session-list'
import { NewChatButton } from '@/components/sidebar/new-chat-button'
import { PageNav } from '@/components/sidebar/page-nav'
import { UserPanel } from '@/components/sidebar/user-panel'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export function Sidebar() {
  const [query, setQuery] = useState('')

  return (
    <div className={styles.sidebar} data-testid="app-sidebar">
      <div className={styles.brandRow}>
        <div className={styles.brandMark}>α</div>
        <div className={styles.brandName}>AlphaScout</div>
      </div>

      <label className={styles.searchBox}>
        <Icon name="search" />
        <input
          placeholder="搜索对话..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          data-testid="sidebar-search-input"
        />
      </label>

      <NewChatButton />

      <div className={styles.sessionsScroll}>
        <ChatSessionList query={query} />
      </div>

      <PageNav />
      <UserPanel />
    </div>
  )
}
```

Note: `query` state 暂时只传到 ChatSessionList 做过滤,搜索功能在 Task 5 内联 filter。`Icon` 组件在 Task 6 新建,这里先 import — 如果先做 Task 4 实施,Icon 可以临时用 inline SVG。

- [ ] **Step 3: 重写 `frontend/src/layout/app-shell/top-bar.tsx`**

```tsx
import { useSnapshot } from 'valtio'
import { useParams } from 'react-router-dom'
import { currentChatState } from '@/store/current-chat'
import { chatSessionsState } from '@/store/chat-sessions'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export function TopBar() {
  const params = useParams<{ session_id?: string }>()
  const sessionId = params.session_id
  const snap = useSnapshot(currentChatState)
  const sessionsSnap = useSnapshot(chatSessionsState)
  const session = sessionId
    ? sessionsSnap.sessions.find((s) => s.id === sessionId)
    : null
  const title = session?.title ?? 'AlphaScout'
  const msgCount = snap.messages?.length ?? 0
  const sub = sessionId ? `${msgCount} turns` : '通用金融 agent 平台'

  return (
    <div className={styles.topbar} data-testid="app-topbar">
      <div className={styles.topbarTitleWrap}>
        <div className={styles.topbarTitle}>{title}</div>
        <div className={styles.topbarSub}>{sub}</div>
      </div>
      <div className={styles.topbarActions}>
        <button className={styles.iconBtn} aria-label="导出" title="导出">
          <Icon name="export" />
        </button>
        <a className={styles.iconBtn} aria-label="我的画像" title="我的画像" href="/memory#persona">
          <Icon name="user-circle" />
        </a>
      </div>
    </div>
  )
}
```

注意:`📋 我的画像` emoji 已移除。

- [ ] **Step 4: 跑 sidebar + topbar 测试**

Run: `cd frontend && npm test -- src/layout/app-shell 2>&1 | tail -30`

Expected: 现有 3 个 test file(index.test.tsx / sidebar.test.tsx / top-bar.test.tsx)全 PASS。`data-testid="app-sidebar"` / `data-testid="app-topbar"` 是新加的稳定锚点;若现有测试用 inline style 断言,改用 `data-testid` 锚。

- [ ] **Step 5: Visual smoke**

Run: `npm run dev`,访问 `/chat/landing` 看 sidebar + topbar 视觉。

Expected:
- Sidebar 暖白底,搜索框 iOS 风,顶部 brand 渐变 α icon
- TopBar 毛玻璃(Mac Safari/Chrome 看到 backdrop-blur 效果)+ SVG icon-btn 替代 emoji

- [ ] **Step 6: Commit**

```bash
git add frontend/src/styles/app-shell.module.scss \
        frontend/src/layout/app-shell/sidebar.tsx \
        frontend/src/layout/app-shell/top-bar.tsx
git commit -m "$(cat <<'EOF'
feat(frontend-app-shell): sidebar + top-bar 切到 iOS 风 CSS module

inline style 重构到 app-shell.module.scss;sidebar 加搜索框 + 渐变 brand
mark + 列表滚动区;top-bar 切毛玻璃 backdrop-blur + SVG icon-btn 替代
📋 emoji + 显示 session title + sub。Icon 组件依赖 Task 6 实现,过渡期
用临时 inline SVG。
EOF
)"
```

---

### Task 5: 重写 chat-session-list.tsx — 按日期分组 + preview + meta

**Files:**
- Modify: `frontend/src/components/sidebar/chat-session-list.tsx`
- Modify: `frontend/src/styles/app-shell.module.scss`(追加 session item 样式)
- Test: `frontend/src/components/sidebar/__tests__/chat-session-list.test.tsx`(已存在)

- [ ] **Step 1: 追加 session item 样式到 `app-shell.module.scss`**

在文件末尾追加:

```scss
.session {
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: background 0.12s ease;

  &:hover { background: var(--ios-surface-hover); }
  &.active {
    background: var(--ios-surface);
    box-shadow: var(--ios-shadow-sm);
  }

  .title {
    font-size: 14px;
    color: var(--ios-label);
    font-weight: 500;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    letter-spacing: -0.01em;
  }
  .preview {
    font-size: 12px;
    color: var(--ios-label-secondary);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .meta {
    font-size: 11px;
    color: var(--ios-label-tertiary);
    margin-top: 2px;
    font-family: var(--ios-font-mono);
  }
}
```

- [ ] **Step 2: 重写 `frontend/src/components/sidebar/chat-session-list.tsx`**

```tsx
import { useEffect, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import {
  chatSessionsActions,
  chatSessionsState,
} from '@/store/chat-sessions'
import type { ChatSession } from '@/types/chat'
import { Skeleton } from '@/components/states/Skeleton'
import { EmptyState } from '@/components/states/EmptyState'
import styles from '@/styles/app-shell.module.scss'

export interface ChatSessionListProps {
  query?: string
}

type DateGroup = '今天' | '昨天' | '上周' | '更早'

function dateGroupOf(iso: string): DateGroup {
  const d = new Date(iso)
  const now = new Date()
  const day = 86400000
  const diff = now.getTime() - d.getTime()
  if (now.toDateString() === d.toDateString()) return '今天'
  const yesterday = new Date(now.getTime() - day)
  if (yesterday.toDateString() === d.toDateString()) return '昨天'
  if (diff < 7 * day) return '上周'
  return '更早'
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  if (now.toDateString() === d.toDateString()) {
    return d.toTimeString().slice(0, 5)  // HH:mm
  }
  return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

export function ChatSessionList({ query = '' }: ChatSessionListProps) {
  const snap = useSnapshot(chatSessionsState)
  const navigate = useNavigate()
  const params = useParams<{ session_id?: string }>()

  useEffect(() => {
    if (snap.status === 'idle') {
      chatSessionsActions.loadSessions().catch(() => {})
    }
  }, [snap.status])

  const groups = useMemo(() => {
    const filtered = query
      ? snap.sessions.filter((s) =>
          s.title.toLowerCase().includes(query.toLowerCase()) ||
          (s.last_msg_preview ?? '').toLowerCase().includes(query.toLowerCase())
        )
      : [...snap.sessions]
    const acc: Record<DateGroup, ChatSession[]> = {
      '今天': [], '昨天': [], '上周': [], '更早': [],
    }
    for (const s of filtered) acc[dateGroupOf(s.last_active_at)].push(s)
    return acc
  }, [snap.sessions, query])

  if (snap.status === 'loading') {
    return <Skeleton variant="list" count={5} />
  }

  const totalShown = Object.values(groups).reduce((n, list) => n + list.length, 0)
  if (totalShown === 0) {
    return (
      <EmptyState
        variant="list-empty"
        title={query ? '无匹配会话' : '还没有对话'}
        description={query ? '换个关键词试试' : '点击「新对话」开始'}
      />
    )
  }

  return (
    <div data-testid="sidebar-chat-session-list">
      {(['今天', '昨天', '上周', '更早'] as DateGroup[]).map((g) => {
        const list = groups[g]
        if (list.length === 0) return null
        return (
          <div key={g}>
            <div className={styles.groupHeader}>{g}</div>
            {list.map((s) => (
              <div
                key={s.id}
                className={`${styles.session} ${params.session_id === s.id ? styles.active : ''}`}
                onClick={() => navigate(`/chat/${s.id}`)}
                data-testid={`session-item-${s.id}`}
              >
                <div className={styles.title}>{s.title}</div>
                {s.last_msg_preview ? (
                  <div className={styles.preview}>{s.last_msg_preview}</div>
                ) : null}
                <div className={styles.meta}>
                  {formatTime(s.last_active_at)} · {s.message_count} turns
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
```

注意:`<Skeleton>` 和 `<EmptyState>` 依赖 Phase E Task 12 创建。Task 5 实施时如果 Task 12 还没做,可临时 inline 替代;但执行顺序应保证 Phase E 早于此处依赖(见 Phase 顺序说明)。

- [ ] **Step 3: 跑 chat-session-list 测试**

Run: `cd frontend && npm test -- src/components/sidebar/__tests__/chat-session-list 2>&1 | tail -20`

Expected: 现有 test 锚定 `data-testid="sidebar-chat-session-list"` 与 navigate 行为,改 CSS / 重写 inner JSX 不应破坏。新增 `data-testid="session-item-{id}"` 锚便后续 e2e。

- [ ] **Step 4: Visual smoke**

Run: `npm run dev`,登录 → `/chat/landing` 看 sidebar 列表。

Expected: 至少 1 个 session 时显示分组 group header(今天/昨天/...)、title + preview + "HH:mm · N turns" 元信息;active session 有浮起卡片样式;hover 有淡背景。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/sidebar/chat-session-list.tsx \
        frontend/src/styles/app-shell.module.scss
git commit -m "$(cat <<'EOF'
feat(frontend-sidebar): chat session list 按日期分组 + preview + meta

抛弃 antd List,自渲染 div + CSS module;按 last_active_at 分今天/昨天/
上周/更早;每条 title + last_msg_preview + (HH:mm · N turns);active
session 浮起卡片;hover 淡背景;支持 query prop 过滤。Skeleton/EmptyState
依赖 Phase E。
EOF
)"
```

---

### Task 6: 重写 new-chat-button + page-nav + user-panel + 新建 Icon 组件

**Files:**
- Create: `frontend/src/components/shared/Icon.tsx`
- Modify: `frontend/src/components/sidebar/new-chat-button.tsx`
- Modify: `frontend/src/components/sidebar/page-nav.tsx`
- Modify: `frontend/src/components/sidebar/user-panel.tsx`
- Modify: `frontend/src/styles/app-shell.module.scss`(追加按钮 / nav-list / user-row 样式)

- [ ] **Step 1: 新建 `frontend/src/components/shared/Icon.tsx`**

SF Symbols 风 SVG icon library:

```tsx
import type { CSSProperties } from 'react'

type IconName =
  | 'plus' | 'plus-circle' | 'search' | 'send' | 'stop' | 'arrow-up'
  | 'chevron-right' | 'chevron-down' | 'check'
  | 'export' | 'edit' | 'more-horizontal' | 'close'
  | 'user-circle' | 'document' | 'bell' | 'book' | 'chart'
  | 'tool' | 'sparkle' | 'rocket'

const PATHS: Record<IconName, string> = {
  'plus':         '<path d="M8 3v10M3 8h10" stroke-width="2.4"/>',
  'plus-circle':  '<circle cx="10" cy="10" r="8"/><path d="M10 6v8M6 10h8" stroke-width="1.8"/>',
  'search':       '<circle cx="7" cy="7" r="5"/><path d="M14 14l-3-3"/>',
  'send':         '<path d="M8 12V3M4 7l4-4 4 4"/>',
  'stop':         '<rect x="4" y="4" width="8" height="8" rx="1"/>',
  'arrow-up':     '<path d="M10 14V6M6 10l4-4 4 4"/>',
  'chevron-right': '<path d="M6 4l4 4-4 4"/>',
  'chevron-down': '<path d="M4 6l4 4 4-4"/>',
  'check':        '<path d="M3 8l3 3 7-7"/>',
  'export':       '<path d="M10 13V3M6 8l4-5 4 5"/><path d="M4 14v2a1 1 0 001 1h10a1 1 0 001-1v-2"/>',
  'edit':         '<path d="M3 17h14M12 4l4 4-8 8H4v-4z"/>',
  'more-horizontal': '<circle cx="5" cy="10" r="1.5"/><circle cx="10" cy="10" r="1.5"/><circle cx="15" cy="10" r="1.5"/>',
  'close':        '<path d="M5 5l10 10M5 15L15 5"/>',
  'user-circle':  '<circle cx="10" cy="7" r="3"/><path d="M3 17c0-3.5 3-6 7-6s7 2.5 7 6"/><circle cx="10" cy="10" r="9"/>',
  'document':     '<path d="M5 3h7l3 3v11H5z M12 3v3h3 M7 10h6 M7 13h4"/>',
  'bell':         '<path d="M10 2v8l5 3"/><circle cx="10" cy="10" r="8"/>',
  'book':         '<path d="M4 4h12v12H4z M4 8h12"/>',
  'chart':        '<path d="M3 13L8 3l5 10M5 9h6"/>',
  'tool':         '<path d="M3 13L8 3l5 10M5 9h6"/>',
  'sparkle':      '<path d="M10 2l2 6 6 2-6 2-2 6-2-6-6-2 6-2z"/>',
  'rocket':       '<path d="M14 6l-8 8M14 6h-4M14 6v4M6 14l-3 3M10 10l4 4"/>',
}

export interface IconProps {
  name: IconName
  size?: number
  style?: CSSProperties
  className?: string
  'aria-hidden'?: boolean
}

export function Icon({ name, size = 16, style, className, ...rest }: IconProps) {
  const inner = PATHS[name]
  const viewBox = name === 'user-circle' || name === 'plus-circle' ? '0 0 20 20' :
                  name === 'export' || name === 'edit' || name === 'document' ||
                  name === 'book' || name === 'chart' || name === 'tool' ||
                  name === 'sparkle' || name === 'rocket' || name === 'arrow-up' ||
                  name === 'bell' || name === 'more-horizontal' ? '0 0 20 20' : '0 0 16 16'
  return (
    <svg
      width={size} height={size} viewBox={viewBox}
      fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round"
      style={style} className={className}
      aria-hidden={rest['aria-hidden'] ?? true}
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  )
}

export type { IconName }
```

- [ ] **Step 2: 追加按钮 / nav-list / user-row 样式到 `app-shell.module.scss`**

```scss
.newChat {
  margin: 4px 2px 0;
  background: var(--ios-blue);
  color: #fff;
  border: none;
  padding: 11px 14px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: flex; align-items: center; gap: 8px;
  box-shadow: var(--ios-shadow-sm);
  transition: transform 0.15s ease, box-shadow 0.15s ease;

  &:hover { transform: translateY(-1px); box-shadow: var(--ios-shadow); background: var(--ios-blue-hover); }
  &:active { transform: translateY(0); }

  .kbd {
    margin-left: auto;
    font-family: var(--ios-font-mono);
    font-size: 10px;
    color: rgba(255, 255, 255, 0.55);
  }
}

.navList {
  padding: 4px;
  background: var(--ios-surface);
  border-radius: 12px;
  box-shadow: var(--ios-shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.navItem {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--ios-label);
  font-size: 14px;
  font-weight: 400;
  text-decoration: none;

  &:hover { background: var(--ios-surface-hover); }
  svg { width: 18px; height: 18px; color: var(--ios-blue); flex-shrink: 0; }
}

.userRow {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  margin-top: 6px;
  border-radius: 12px;
  cursor: pointer;
  background: var(--ios-surface);
  box-shadow: var(--ios-shadow-sm);

  &:hover { background: var(--ios-surface-tinted); }

  .avatar {
    width: 36px; height: 36px;
    border-radius: 50%;
    background: var(--ios-grad-warm);
    color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 600;
  }
  .info { flex: 1; min-width: 0; }
  .info .name { font-size: 14px; font-weight: 600; color: var(--ios-label); }
  .info .role { font-size: 12px; color: var(--ios-label-secondary); }
  .chev { color: var(--ios-label-tertiary); }
}
```

- [ ] **Step 3: 重写 `frontend/src/components/sidebar/new-chat-button.tsx`**

```tsx
import { useNavigate } from 'react-router-dom'
import { chatSessionsActions } from '@/store/chat-sessions'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export function NewChatButton() {
  const navigate = useNavigate()
  async function handleClick() {
    const created = await chatSessionsActions.createAndAdd()
    navigate(`/chat/${created.id}`)
  }
  return (
    <button
      type="button"
      className={styles.newChat}
      data-testid="sidebar-new-chat-button"
      onClick={handleClick}
    >
      <Icon name="plus" size={14} />
      新对话
      <span className={styles.kbd}>⌘N</span>
    </button>
  )
}
```

- [ ] **Step 4: 重写 `frontend/src/components/sidebar/page-nav.tsx`**

```tsx
import { Link } from 'react-router-dom'
import { Icon, type IconName } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

const LINKS: { to: string; label: string; icon: IconName }[] = [
  { to: '/research', label: '研报中心', icon: 'document' },
  { to: '/reports', label: '报告中心', icon: 'document' },
  { to: '/portfolio', label: '持仓', icon: 'chart' },
  { to: '/monitoring', label: '监控告警', icon: 'bell' },
  { to: '/memory', label: '我的画像', icon: 'user-circle' },
  { to: '/knowledge', label: '知识库', icon: 'book' },
]

export function PageNav() {
  return (
    <nav
      className={styles.navList}
      data-testid="sidebar-page-nav"
    >
      {LINKS.map((l) => (
        <Link key={l.to} to={l.to} className={styles.navItem}>
          <Icon name={l.icon} size={18} />
          {l.label}
        </Link>
      ))}
    </nav>
  )
}
```

- [ ] **Step 5: 重写 `frontend/src/components/sidebar/user-panel.tsx`**

```tsx
import { useSnapshot } from 'valtio'
import { authState } from '@/store/auth'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/app-shell.module.scss'

export function UserPanel() {
  const snap = useSnapshot(authState)
  const name = snap.isLoggedIn && snap.user ? snap.user.username : 'anonymous'
  const initial = name.charAt(0).toUpperCase()
  return (
    <div
      data-testid="sidebar-user-panel"
      className={styles.userRow}
    >
      <div className={styles.avatar}>{initial}</div>
      <div className={styles.info}>
        <div className={styles.name}>{name}</div>
        <div className={styles.role}>Tier 1 · Analyst</div>
      </div>
      <Icon name="chevron-right" size={14} className={styles.chev} />
    </div>
  )
}
```

- [ ] **Step 6: 跑全部 sidebar test + visual smoke**

Run:
```bash
cd frontend && npm test -- src/components/sidebar 2>&1 | tail -30
```

Expected: 4 个 test file 全 PASS。`data-testid` 锚点保持(`sidebar-new-chat-button` / `sidebar-page-nav` / `sidebar-user-panel`)。

Visual smoke: `npm run dev` → `/chat/landing` 看 sidebar 完整(brand row + search + new chat button + session list + page nav + user panel)。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/shared/Icon.tsx \
        frontend/src/components/sidebar/new-chat-button.tsx \
        frontend/src/components/sidebar/page-nav.tsx \
        frontend/src/components/sidebar/user-panel.tsx \
        frontend/src/styles/app-shell.module.scss
git commit -m "$(cat <<'EOF'
feat(frontend-sidebar): new-chat / page-nav / user-panel iOS 风重写 + Icon 库

新建 components/shared/Icon — SF Symbols 风 SVG icon library(20+ icon),
new-chat 蓝按钮 + ⌘N kbd 提示,page-nav 卡片化 + 蓝 icon,user-panel 渐变
avatar + 双行信息 + chevron。Phase B AppShell rewrite 完。
EOF
)"
```

---

## Phase C · Message Stream Rewrite

### Task 7: 重写 chat.module.scss + TextMessage 气泡 + ChatPane 容器

**Files:**
- Modify: `frontend/src/styles/chat.module.scss`(全文重写)
- Modify: `frontend/src/components/chat/ChatPane.tsx`
- Modify: `frontend/src/components/chat/TextMessage.tsx`
- Test: `frontend/src/components/chat/__tests__/ChatPane.test.tsx`(已存在)
- Test: `frontend/src/components/chat/__tests__/TextMessage.test.tsx`(已存在)

- [ ] **Step 1: 重写 `frontend/src/styles/chat.module.scss`**

完整内容(全 token 化,删除 25 处硬编码颜色;参考 mockup 第 217-560 行):

```scss
.chatPane {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--ios-bg-grouped);
}

.costStrip {
  padding: 8px 24px;
  background: var(--ios-bg-grouped);
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  border-bottom: 1px solid var(--ios-separator);
  flex-shrink: 0;
}
.costPill {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--ios-surface);
  padding: 4px 10px;
  border-radius: var(--ios-radius-pill);
  color: var(--ios-label-secondary);
  box-shadow: var(--ios-shadow-sm);

  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ios-green); }
  .v {
    color: var(--ios-label);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    font-family: var(--ios-font-mono);
    font-size: 11.5px;
  }
}

.messagesRegion {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 24px 0 16px;
}
.chatContainer {
  max-width: var(--ios-chat-max-w);
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.emptyState {
  display: flex; align-items: center; justify-content: center;
  height: 100%;
  color: var(--ios-label-secondary);
}

/* ── User bubble ─────────────────────────────────── */
.rowUser { display: flex; justify-content: flex-end; }
.bubbleUser {
  background: var(--ios-blue);
  color: #fff;
  padding: 10px 14px;
  border-radius: 20px;
  border-bottom-right-radius: 6px;
  max-width: 75%;
  font-size: 15px;
  line-height: 1.45;
  box-shadow: var(--ios-shadow-sm);
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── AI bubble ───────────────────────────────────── */
.rowAi {
  display: flex; flex-direction: column;
  gap: 8px;
  align-items: flex-start;
  max-width: 92%;
}
.aiMeta {
  display: flex; align-items: center; gap: 8px;
  padding: 0 6px;
  font-size: 12px;
  color: var(--ios-label-secondary);
  font-weight: 500;
}
.aiBadge {
  background: var(--ios-blue-soft);
  color: var(--ios-blue);
  padding: 1px 8px;
  border-radius: var(--ios-radius-pill);
  font-size: 11px;
  font-weight: 600;
}
.bubbleAi {
  background: var(--ios-surface);
  color: var(--ios-label);
  padding: 14px 16px;
  border-radius: 18px;
  border-bottom-left-radius: 6px;
  font-size: 15px;
  line-height: 1.6;
  box-shadow: var(--ios-shadow-sm);
  max-width: 100%;

  p { margin: 0 0 8px 0; &:last-child { margin: 0; } }
  strong { font-weight: 600; }
  .num {
    font-family: var(--ios-font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 14px;
    font-weight: 500;
    color: var(--ios-blue);
  }
}

/* ── Tool card ───────────────────────────────────── */
.toolCard {
  background: var(--ios-surface);
  border-radius: var(--ios-radius-lg);
  box-shadow: var(--ios-shadow-sm);
  overflow: hidden;
  align-self: stretch;
  max-width: 100%;
}
.toolCardHeader {
  display: flex; align-items: center; gap: 10px;
  padding: 11px 14px;
  background: transparent;
  border: none;
  cursor: pointer;
  width: 100%;
  text-align: left;
}
.toolIcon {
  width: 28px; height: 28px;
  border-radius: 8px;
  background: var(--ios-blue-soft);
  color: var(--ios-blue);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.toolCardName {
  flex: 1 1 auto;
  font-size: 13px;
  font-weight: 600;
  color: var(--ios-label);
  letter-spacing: -0.01em;
}
.toolStatus {
  font-size: 11px;
  color: var(--ios-green);
  font-weight: 600;
  display: inline-flex; align-items: center; gap: 4px;

  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ios-green); }
}
.toolCardDuration {
  font-size: 11px;
  color: var(--ios-label-tertiary);
  font-family: var(--ios-font-mono);
}
.toolCardChevron {
  color: var(--ios-label-tertiary);
}
.toolCardError {
  .toolIcon { background: rgba(255, 59, 48, 0.1); color: var(--ios-red); }
  .toolStatus { color: var(--ios-red); .dot { background: var(--ios-red); } }
}
.toolCardBody {
  padding: 10px 14px 12px;
  border-top: 1px solid var(--ios-separator);
  font-size: 12px;
  color: var(--ios-label-secondary);
  line-height: 1.6;

  pre {
    margin: 4px 0;
    padding: 8px;
    background: var(--ios-bg-grouped);
    border: 1px solid var(--ios-separator);
    font-size: 11.5px;
    font-family: var(--ios-font-mono);
    border-radius: var(--ios-radius-sm);
    overflow-x: auto;
  }
}
.toolCardSection {
  margin-bottom: 6px;
  .k { color: var(--ios-label-tertiary); }
  .v { color: var(--ios-label); font-weight: 500; font-family: var(--ios-font-mono); font-size: 11.5px; }
}

.retryBtn {
  margin-top: 6px;
  border: 1px solid var(--ios-red);
  background: var(--ios-surface);
  color: var(--ios-red);
  padding: 5px 12px;
  border-radius: var(--ios-radius-sm);
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
}

/* ── Report card ─────────────────────────────────── */
.reportCard {
  background: var(--ios-surface);
  border-radius: var(--ios-radius-lg);
  padding: 18px 20px;
  box-shadow: var(--ios-shadow);
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-self: stretch;
}
.reportCardHead { display: flex; align-items: center; gap: 10px; }
.reportCardIconLarge {
  width: 38px; height: 38px;
  border-radius: 10px;
  background: var(--ios-grad-primary);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--ios-shadow-accent);
  flex-shrink: 0;
}
.reportCardHeadText { flex: 1; min-width: 0; }
.reportCardId {
  font-size: 11px;
  color: var(--ios-label-secondary);
  font-family: var(--ios-font-mono);
  margin-bottom: 2px;
}
.reportCardTitle {
  font-size: 16px;
  font-weight: 600;
  color: var(--ios-label);
  letter-spacing: -0.01em;
  line-height: 1.3;
}
.reportCardSummary {
  font-size: 14px;
  color: var(--ios-label);
  line-height: 1.6;
  opacity: 0.85;
}
.reportCardActions { display: flex; gap: 8px; flex-wrap: wrap; }
.pillBtn {
  padding: 7px 14px;
  border-radius: var(--ios-radius-pill);
  border: none;
  background: var(--ios-bg-grouped);
  color: var(--ios-blue);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.12s;

  &:hover { background: rgba(0, 122, 255, 0.08); }
  &.primary { background: var(--ios-blue); color: #fff; &:hover { background: var(--ios-blue-hover); } }
}

/* ── System message ──────────────────────────────── */
.systemMsg {
  align-self: center;
  background: var(--ios-bg-secondary);
  color: var(--ios-label-secondary);
  font-size: 12px;
  padding: 6px 12px;
  border-radius: var(--ios-radius-pill);
  border: 1px solid var(--ios-separator);
}

/* ── Streaming indicator(置于 chat 容器外,sticky 底部) ─── */
.streamingIndicator {
  position: sticky;
  bottom: 0;
  padding: 8px 12px;
  background: var(--ios-glass-bg);
  backdrop-filter: var(--ios-glass-blur);
  -webkit-backdrop-filter: var(--ios-glass-blur);
  border-top: 1px solid var(--ios-separator);
  font-size: 12px;
  color: var(--ios-label-secondary);
  display: flex;
  gap: 8px;
  align-items: center;
}
@supports not (backdrop-filter: blur(20px)) {
  .streamingIndicator { background: var(--ios-surface); }
}

/* ── Input region ────────────────────────────────── */
.inputRegion {
  flex-shrink: 0;
  padding: 12px 24px 20px;
  background: var(--ios-glass-bg);
  backdrop-filter: var(--ios-glass-blur);
  -webkit-backdrop-filter: var(--ios-glass-blur);
  border-top: 1px solid var(--ios-separator);
}
@supports not (backdrop-filter: blur(20px)) {
  .inputRegion { background: var(--ios-bg-grouped); }
}
.inputContainer { max-width: var(--ios-chat-max-w); margin: 0 auto; }
.composer { display: flex; align-items: flex-end; gap: 10px; }
.composerInput {
  flex: 1;
  background: var(--ios-surface);
  border: 1px solid var(--ios-separator-opaque);
  border-radius: var(--ios-input-radius);
  padding: 10px 16px;
  display: flex;
  align-items: flex-end;
  gap: 10px;
  transition: border-color 0.15s, box-shadow 0.15s;

  &:focus-within {
    border-color: var(--ios-blue);
    box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.12);
  }
}
.inputTextarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  resize: none;
  font-family: inherit;
  font-size: 15px;
  color: var(--ios-label);
  line-height: 1.5;
  max-height: 140px;
  padding: 4px 0;

  &::placeholder { color: var(--ios-label-secondary); }
}
.escalateBtn {
  border: none;
  background: transparent;
  color: var(--ios-label-secondary);
  cursor: pointer;
  padding: 4px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 50%;
  transition: background 0.12s;

  &:hover { background: var(--ios-surface-hover); color: var(--ios-blue); }
}
.sendBtn {
  width: 36px; height: 36px;
  border-radius: 50%;
  background: var(--ios-blue);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--ios-shadow-accent);
  transition: transform 0.15s, background 0.15s;
  flex-shrink: 0;

  &:hover { transform: scale(1.05); background: var(--ios-blue-hover); }
  &:disabled { background: var(--ios-label-quaternary); box-shadow: none; cursor: not-allowed; }
}
.cancelBtn {
  width: 36px; height: 36px;
  border-radius: 50%;
  background: var(--ios-red);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;

  &:hover { background: #e63b30; }
}

.inputActions {
  display: flex; gap: 6px;
}

.inputHint {
  text-align: center;
  font-size: 11px;
  color: var(--ios-label-tertiary);
  margin-top: 8px;

  kbd {
    background: var(--ios-surface);
    border: 1px solid var(--ios-separator);
    border-radius: 4px;
    padding: 1px 5px;
    font-family: var(--ios-font-mono);
    font-size: 10px;
    margin: 0 2px;
    box-shadow: 0 1px 0 var(--ios-separator-opaque);
    color: var(--ios-label-secondary);
  }
}

.charCounter {
  font-size: 11px;
  color: var(--ios-label-tertiary);
  padding: 2px 6px;

  &[data-warn='true'] {
    color: var(--ios-red);
    font-weight: 600;
  }
}

.pasteWarn {
  background: rgba(255, 149, 0, 0.08);
  border: 1px solid rgba(255, 149, 0, 0.3);
  padding: 4px 10px;
  border-radius: var(--ios-radius-sm);
  font-size: 12px;
  color: var(--ios-orange);
}
```

注意:删除全部硬编码 `#1677ff` / `#fafafa` / `#d9d9d9` 等。verify with grep step 4。

- [ ] **Step 2: 重写 `frontend/src/components/chat/TextMessage.tsx`**

(read current to preserve any prop signature first)

```tsx
import { useSnapshot } from 'valtio'
import type { ChatMessage } from '@/types/chat'
import { authState } from '@/store/auth'
import styles from '@/styles/chat.module.scss'

export interface TextMessageProps {
  message: ChatMessage
}

export function TextMessage({ message }: TextMessageProps) {
  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'
  const auth = useSnapshot(authState)

  if (isUser) {
    return (
      <div className={styles.rowUser} data-testid={`msg-user-${message.id}`}>
        <div className={styles.bubbleUser}>{message.content}</div>
      </div>
    )
  }
  if (isAssistant) {
    return (
      <div className={styles.rowAi} data-testid={`msg-ai-${message.id}`}>
        <div className={styles.aiMeta}>
          <span className={styles.aiBadge}>Analyst</span>
        </div>
        <div className={styles.bubbleAi}>{message.content}</div>
      </div>
    )
  }
  // system / fallback → 走 SystemMessage(在 MessageRouter 已分支)
  return null
}
```

注意:`auth` 只取 snapshot — 可后续在 user bubble 渲染头像或者 username。当前 mockup 不展示用户头像,留 hook。

- [ ] **Step 3: 重写 `frontend/src/components/chat/ChatPane.tsx`**

容器加 CostMeter 改为 cost-strip 行 + chatContainer 居中:

```tsx
import { useCallback, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useSnapshot } from 'valtio'
import { CostMeter } from './CostMeter'
import { InputArea } from './InputArea'
import { MessageList } from './MessageList'
import { StreamingIndicator } from './StreamingIndicator'
import { useDeferredMessages } from './useDeferredMessages'
import { useChatSSE } from '@/hooks/useChatSSE'
import { currentChatState } from '@/store/current-chat'
import { escalationState } from '@/store/escalation'
import { EmptyState } from '@/components/states/EmptyState'
import styles from '@/styles/chat.module.scss'

export interface ChatPaneProps {
  sessionId?: string
  activeTaskId?: string | null
}

export function ChatPane({
  sessionId: sessionIdProp,
  activeTaskId,
}: ChatPaneProps = {}) {
  const params = useParams<{ session_id: string }>()
  const sessionId = sessionIdProp ?? params.session_id ?? null
  const snap = useSnapshot(currentChatState)
  const messages = useDeferredMessages(snap.messages ?? [])
  const sse = useChatSSE({ sessionId })

  useEffect(() => {
    if (activeTaskId) {
      void sse.subscribeToTask(activeTaskId, '0')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTaskId])

  const pendingMessage =
    snap.streamingDraft && sessionId
      ? {
          id: '__pending_assistant__',
          session_id: sessionId,
          role: 'assistant' as const,
          content: snap.streamingDraft,
          message_type: 'text' as const,
          tool_call_data: null,
          research_report_id: null,
          research_report_summary: null,
          created_at: new Date().toISOString(),
        }
      : null
  const displayMessages = pendingMessage ? [...messages, pendingMessage] : messages

  const onSend = useCallback(
    (text: string) => {
      if (!sessionId) return
      void sse.sendMessage(text)
    },
    [sessionId, sse],
  )

  const onAbort = useCallback(() => sse.abort(), [sse])

  const onEscalate = useCallback(() => {
    if (escalationState.packet_draft) return
  }, [])

  const onContinueAsk = useCallback((_id: string) => {
    const ta = document.querySelector<HTMLTextAreaElement>('[data-testid="input-textarea"]')
    ta?.focus()
  }, [])

  const empty = displayMessages.length === 0
  return (
    <div className={styles.chatPane}>
      <CostMeter />
      <section role="region" aria-label="messages" className={styles.messagesRegion}>
        <div className={styles.chatContainer}>
          {empty ? (
            <EmptyState
              variant="chat-empty"
              title="开始一个新对话"
              description='试试问 "工商银行现价多少?"'
            />
          ) : (
            <MessageList
              messages={[...displayMessages]}
              onContinueAsk={onContinueAsk}
              onRetry={sse.retryTask}
            />
          )}
        </div>
        <StreamingIndicator />
      </section>
      <section role="region" aria-label="input" className={styles.inputRegion}>
        <div className={styles.inputContainer}>
          <InputArea
            sessionId={sessionId ?? undefined}
            onSend={onSend}
            onAbort={onAbort}
            onEscalate={onEscalate}
            onCancel={sse.cancelTask}
          />
        </div>
      </section>
    </div>
  )
}
```

`<EmptyState>` 依赖 Phase E。

- [ ] **Step 4: 跑 ChatPane + TextMessage test**

Run: `npm test -- src/components/chat/__tests__/(ChatPane|TextMessage)` (or use `--testPathPattern`)

Expected: 现有测试主要锚定 `role="region"` / message render / send 交互,改 CSS / 包裹 div 不应破坏。新加的 `data-testid="msg-user-{id}"` / `msg-ai-{id}` 是补丁。

- [ ] **Step 5: grep verify chat.module.scss 0 硬编码颜色**

Run: `grep -oE '#[0-9a-fA-F]{3,8}' frontend/src/styles/chat.module.scss | wc -l | tr -d ' '`

Expected: 0(全部走 var())

- [ ] **Step 6: Commit**

```bash
git add frontend/src/styles/chat.module.scss \
        frontend/src/components/chat/ChatPane.tsx \
        frontend/src/components/chat/TextMessage.tsx
git commit -m "$(cat <<'EOF'
feat(frontend-chat): chat.module.scss 全 token 化 + TextMessage 气泡

chat.module.scss 25 处硬编码颜色全替为 var(--ios-*);TextMessage 走 iOS
Messages 风气泡(user 蓝靠右 + AI 灰白靠左 + Analyst badge);ChatPane 加
chatContainer 居中 + 接 EmptyState。EmptyState 依赖 Phase E。
EOF
)"
```

---

### Task 8: 重写 ToolCallCard + SystemMessage + ResearchReportCard

**Files:**
- Modify: `frontend/src/components/chat/ToolCallCard.tsx`
- Modify: `frontend/src/components/chat/SystemMessage.tsx`
- Modify: `frontend/src/components/chat/ResearchReportCard.tsx`
- Test: 3 个对应 `__tests__/*.test.tsx`

- [ ] **Step 1: 读取 ToolCallCard 当前 prop & jsx 结构(verify before rewriting)**

Run: `cat frontend/src/components/chat/ToolCallCard.tsx | head -60`

记录 props / 内部 state(折叠展开)/ children 渲染逻辑,保持 API 不变。

- [ ] **Step 2: 重写 `frontend/src/components/chat/ToolCallCard.tsx`**

完整新版(保留 props API,只换 jsx 结构):

```tsx
import { useState } from 'react'
import type { ChatMessage } from '@/types/chat'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/chat.module.scss'

export interface ToolCallCardProps {
  message: ChatMessage
}

export function ToolCallCard({ message }: ToolCallCardProps) {
  const [open, setOpen] = useState(false)
  const data = message.tool_call_data
  if (!data) return null
  const isError = data.error != null
  const klass = `${styles.toolCard} ${isError ? styles.toolCardError : ''}`

  return (
    <div className={klass} data-testid={`tool-card-${message.id}`}>
      <button
        className={styles.toolCardHeader}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className={styles.toolIcon}>
          <Icon name="tool" size={14} />
        </div>
        <span className={styles.toolCardName}>{data.name}</span>
        <span className={styles.toolStatus}>
          <span className={styles.toolStatus}><span className={`${styles.dot}`}></span></span>
          {isError ? '失败' : '完成'}
        </span>
        {data.duration_ms != null ? (
          <span className={styles.toolCardDuration}>{data.duration_ms}ms</span>
        ) : null}
        <Icon name={open ? 'chevron-down' : 'chevron-right'} size={14} className={styles.toolCardChevron} />
      </button>
      {open ? (
        <div className={styles.toolCardBody}>
          {data.arguments ? (
            <div className={styles.toolCardSection}>
              <div className="k">参数</div>
              <pre>{JSON.stringify(data.arguments, null, 2)}</pre>
            </div>
          ) : null}
          {data.result ? (
            <div className={styles.toolCardSection}>
              <div className="k">返回</div>
              <pre>{typeof data.result === 'string' ? data.result : JSON.stringify(data.result, null, 2)}</pre>
            </div>
          ) : null}
          {data.error ? (
            <div className={styles.toolCardSection}>
              <div className="k">错误</div>
              <pre>{data.error}</pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
```

Note:Tool data shape is per `frontend/src/types/chat.ts:ChatMessage.tool_call_data`(verify; preserve fields).

- [ ] **Step 3: 重写 `frontend/src/components/chat/SystemMessage.tsx`**

```tsx
import type { ChatMessage } from '@/types/chat'
import styles from '@/styles/chat.module.scss'

export interface SystemMessageProps {
  message: ChatMessage
}

export function SystemMessage({ message }: SystemMessageProps) {
  return (
    <div className={styles.systemMsg} data-testid={`msg-system-${message.id}`}>
      {message.content}
    </div>
  )
}
```

- [ ] **Step 4: 重写 `frontend/src/components/chat/ResearchReportCard.tsx`**

(verify current prop signature first via cat)

```tsx
import { useNavigate } from 'react-router-dom'
import type { ChatMessage } from '@/types/chat'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/chat.module.scss'

export interface ResearchReportCardProps {
  message: ChatMessage
  onContinueAsk?: (messageId: string) => void
}

export function ResearchReportCard({ message, onContinueAsk }: ResearchReportCardProps) {
  const navigate = useNavigate()
  const reportId = message.research_report_id
  const summary = message.research_report_summary
  if (!reportId) return null

  return (
    <div className={styles.reportCard} data-testid={`report-card-${reportId}`}>
      <div className={styles.reportCardHead}>
        <div className={styles.reportCardIconLarge}>
          <Icon name="document" size={18} />
        </div>
        <div className={styles.reportCardHeadText}>
          <div className={styles.reportCardId}>RPT-{reportId} · Research Report</div>
          <div className={styles.reportCardTitle}>{message.content || '研报已生成'}</div>
        </div>
      </div>
      {summary ? <div className={styles.reportCardSummary}>{summary}</div> : null}
      <div className={styles.reportCardActions}>
        <button
          className={`${styles.pillBtn} ${styles.primary}`}
          onClick={() => navigate(`/research/${reportId}`)}
        >
          查看完整报告
        </button>
        <button
          className={styles.pillBtn}
          onClick={() => window.print()}
        >
          导出 PDF
        </button>
        <button
          className={styles.pillBtn}
          onClick={() => onContinueAsk?.(message.id)}
        >
          追问
        </button>
      </div>
    </div>
  )
}
```

注意:`message.research_report_summary` / `message.research_report_id` 字段从 `ChatMessage` 类型读取,verify。

- [ ] **Step 5: 跑相关测试**

Run: `npm test -- src/components/chat/__tests__/(ToolCallCard|SystemMessage|ResearchReportCard) 2>&1 | tail -30`

Expected: 3 个 test file PASS。若失败(prop 签名变了,断言用了旧 CSS class),改 test 用 `data-testid`。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/ToolCallCard.tsx \
        frontend/src/components/chat/SystemMessage.tsx \
        frontend/src/components/chat/ResearchReportCard.tsx
git commit -m "$(cat <<'EOF'
feat(frontend-chat): tool/system/report card iOS 圆角卡重写

ToolCallCard:14px 圆角 + 蓝色 icon-box 28×28 + 状态绿点 + Mono 数字;
SystemMessage:居中胶囊;ResearchReportCard:渐变 logo 38×38 + 大圆角
+ pill 按钮组(主蓝 + 次灰)。
EOF
)"
```

---

### Task 9: 校准 MessageList ESTIMATE_ROW_HEIGHT + 跑滚动 smoke

**Files:**
- Modify: `frontend/src/components/chat/MessageList.tsx`
- Test: `frontend/src/components/chat/__tests__/MessageList.test.tsx`

- [ ] **Step 1: 手测各类 message 实际渲染高度**

Run: `npm run dev` → 打开真 session 含混合 message。Browser DevTools 选每类元素测高度:
- user bubble:~50px
- AI bubble (短回复):~80px
- AI bubble (长回复 5+ 段):~280px
- tool card 折叠:~50px
- tool card 展开:~180px
- report card:~180px
- system msg:~35px

加权平均估算:约 120px。若实测显著不同,按实测加权改。

- [ ] **Step 2: 改 `frontend/src/components/chat/MessageList.tsx` ESTIMATE_ROW_HEIGHT**

```typescript
// 原:
const ESTIMATE_ROW_HEIGHT = 96
// 新:
const ESTIMATE_ROW_HEIGHT = 120
```

外加微调 row gap(在容器里 chat.module.scss 已设 14px gap,react-window 内部无 gap)— 保持 react-window 内部 height 由 itemSize 决定,gap 由外部 chat-container CSS 控制。

不动 react-window 主结构。

- [ ] **Step 3: 跑 MessageList test**

Run: `npm test -- src/components/chat/__tests__/MessageList 2>&1 | tail -20`

Expected: PASS。

- [ ] **Step 4: Visual smoke — 长会话滚动测试**

Run: `npm run dev` → 用包含 50+ 条混合消息的真 session(可用现有 dogfood session)滚动测试。

Expected: 滚动平顺,无可见跳动 / overscan 失败。如果有跳动,记下实际平均 row height 再调。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/chat/MessageList.tsx
git commit -m "$(cat <<'EOF'
chore(frontend-chat): MessageList ESTIMATE_ROW_HEIGHT 96→120 校准

气泡 / tool / report 渲染高度变化,react-window virtual scroll 估算值
基于真实测量加权平均。Phase C message stream rewrite 完。
EOF
)"
```

---

## Phase D · Input + Meter + Streaming

### Task 10: 重写 InputArea — 胶囊 + 圆形发送 + 清 DEBUG log

**Files:**
- Modify: `frontend/src/components/chat/InputArea.tsx`
- Test: `frontend/src/components/chat/__tests__/InputArea.test.tsx`

- [ ] **Step 1: 重写 `frontend/src/components/chat/InputArea.tsx`**

```tsx
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'
import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'
import { Icon } from '@/components/shared/Icon'
import styles from '@/styles/chat.module.scss'

export interface InputAreaProps {
  sessionId?: string
  onSend?: (text: string) => void
  onAbort?: () => void
  onEscalate?: () => void
  onCancel?: (taskId: string) => void
}

const MIN_HEIGHT = 24
const MAX_HEIGHT = 140
const MAX_CHARS = 4000

export function InputArea(props: InputAreaProps) {
  const [value, setValue] = useState('')
  const [pasteWarn, setPasteWarn] = useState<string | null>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const snap = useSnapshot(currentChatState)
  const streaming =
    snap.streaming_phase !== 'idle' || snap.streamingStatus === 'streaming'
  const messages = snap.messages ?? []
  const hasContext = messages.length > 0

  const autoResize = useCallback(() => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = 'auto'
    const next = Math.min(Math.max(ta.scrollHeight, MIN_HEIGHT), MAX_HEIGHT)
    ta.style.height = `${next}px`
  }, [])

  useEffect(() => {
    autoResize()
  }, [value, autoResize])

  const onPaste = useCallback((e: ClipboardEvent) => {
    const dt = e.clipboardData
    if (!dt) return
    const hasFile = Array.from(dt.items).some((it) => it.kind === 'file')
    if (hasFile) {
      setPasteWarn('暂不支持上传 (C.4 milestone)')
      e.preventDefault()
      setTimeout(() => setPasteWarn(null), 4000)
    }
  }, [])

  useEffect(() => {
    const ta = taRef.current
    if (!ta) return
    ta.addEventListener('paste', onPaste)
    return () => ta.removeEventListener('paste', onPaste)
  }, [onPaste])

  useEffect(() => {
    function onKeyGlobal(e: globalThis.KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        if (streaming) props.onAbort?.()
      }
    }
    window.addEventListener('keydown', onKeyGlobal)
    return () => window.removeEventListener('keydown', onKeyGlobal)
  }, [streaming, props])

  const send = useCallback(() => {
    const text = value.trim()
    if (!text) return
    props.onSend?.(text)
    setValue('')
  }, [value, props])

  const onKey = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault()
        send()
      }
    },
    [send],
  )

  const onCancelClick = () => {
    if (snap.active_task_id && props.onCancel) {
      void props.onCancel(snap.active_task_id)
    } else {
      props.onAbort?.()
    }
  }

  return (
    <div data-session={props.sessionId ?? ''}>
      <div className={styles.composer}>
        <div className={styles.composerInput}>
          {!streaming && hasContext ? (
            <button
              type="button"
              className={styles.escalateBtn}
              onClick={() => props.onEscalate?.()}
              aria-label="升级到深度研究"
              title="升级到深度研究"
            >
              <Icon name="plus-circle" size={18} />
            </button>
          ) : null}
          <textarea
            ref={taRef}
            data-testid="input-textarea"
            className={styles.inputTextarea}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKey}
            placeholder={
              streaming ? '正在生成中...' : '问点什么 (Enter 发送, Shift+Enter 换行)'
            }
            rows={1}
          />
        </div>
        {streaming ? (
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={onCancelClick}
            aria-label="停止生成"
            title="停止生成"
          >
            <Icon name="stop" size={14} />
          </button>
        ) : (
          <button
            type="button"
            className={styles.sendBtn}
            onClick={send}
            disabled={!value.trim()}
            aria-label="发送"
            title="发送"
          >
            <Icon name="arrow-up" size={16} />
          </button>
        )}
      </div>
      <div className={styles.inputHint}>
        <kbd>Enter</kbd> 发送 · <kbd>⇧</kbd> + <kbd>Enter</kbd> 换行 · <kbd>⌘</kbd> + <kbd>K</kbd> 停止
      </div>
      {value.length > MAX_CHARS / 8 ? (
        <div
          className={styles.charCounter}
          data-warn={value.length > MAX_CHARS}
        >
          {value.length} / {MAX_CHARS}
        </div>
      ) : null}
      {pasteWarn ? <div className={styles.pasteWarn}>{pasteWarn}</div> : null}
    </div>
  )
}
```

变化点:
1. **5 处 `console.log('[DEBUG cancel-button] ...')` 全清** — `onCancelClick` 写成精简函数,不留诊断日志
2. `⚡ 升级到深度研究` 替为 `<Icon name="plus-circle" />` 圆形按钮(放入 composer 内左侧)
3. button → 圆形 sendBtn / cancelBtn
4. antd Button 全替原生 button
5. 文案 hint 用 kbd 元素

- [ ] **Step 2: 跑 InputArea test**

Run: `npm test -- src/components/chat/__tests__/InputArea 2>&1 | tail -30`

Expected:
- "renders textarea + send button" — PASS (textarea + role=button + aria-label=发送 仍在)
- "Enter sends message; clears textarea" — PASS
- "Shift+Enter inserts newline; does NOT send" — PASS
- "auto-resizes textarea height" — PASS
- "hides send button and shows 中断 when streaming" — 需检查 — 老 test 锚 `/发送|send/i` 和 `/停止|cancel/i`,新版仍有这两个 aria-label,应 PASS
- "renders ⚡ Escalate button when not streaming and chat has at least 1 message" — 老 test 锚 `/Escalate|升级到深度研究|⚡/i`(or-pattern 之一),新版 aria-label `升级到深度研究`,应 PASS(⚡ 分支不再匹配但 or-pattern 中 `升级到深度研究` 匹配)

若有 test 失败,修 test 用 `data-testid` 锚点。

- [ ] **Step 3: grep verify 0 DEBUG log**

Run: `grep -c "DEBUG" frontend/src/components/chat/InputArea.tsx`

Expected: 0

- [ ] **Step 4: grep verify 0 emoji in InputArea**

Run: `grep -E '⚡|📋' frontend/src/components/chat/InputArea.tsx`

Expected: 无输出

- [ ] **Step 5: Visual smoke**

`npm run dev` → 输入框胶囊 22px,左侧 plus 圆 icon(有 context 时),右侧圆形蓝色发送按钮,streaming 时换红色 stop 按钮。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/InputArea.tsx
git commit -m "$(cat <<'EOF'
feat(frontend-chat): InputArea iOS 风胶囊 composer + 清 DEBUG log

胶囊 22px 输入框 + 左侧 plus icon(escalate)+ 右侧圆形蓝色发送按钮(streaming
时换红色 stop)。5 处 console.log('[DEBUG cancel-button]') 全清,emoji ⚡
换 Icon plus-circle。aria-label 中文保留以支持 i18n 友好测试匹配。
EOF
)"
```

---

### Task 11: 重写 CostMeter(pill 形)+ StreamingIndicator(iOS 跳动三点)

**Files:**
- Modify: `frontend/src/components/chat/CostMeter.tsx`
- Modify: `frontend/src/components/chat/StreamingIndicator.tsx`
- Test: `frontend/src/components/chat/__tests__/CostMeter.test.tsx` + `StreamingIndicator.test.tsx`

- [ ] **Step 1: 读现有 CostMeter API + state shape**

Run: `cat frontend/src/components/chat/CostMeter.tsx`

记录 props + 内部 valtio 接入(从 cost-related store)+ 折叠展开逻辑。

- [ ] **Step 2: 重写 `frontend/src/components/chat/CostMeter.tsx`**

```tsx
import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'
import styles from '@/styles/chat.module.scss'

export function CostMeter() {
  const snap = useSnapshot(currentChatState)
  const cost = snap.total_cost_usd ?? 0
  const tokensIn = snap.total_tokens_in ?? 0
  const tokensOut = snap.total_tokens_out ?? 0
  const model = snap.current_model ?? '—'

  return (
    <div className={styles.costStrip} data-testid="cost-meter">
      <span className={styles.costPill}>
        <span className={styles.dot} />
        在线 · {model}
      </span>
      <span className={styles.costPill}>
        Tokens <span className={styles.v}>{tokensIn.toLocaleString()} in / {tokensOut.toLocaleString()} out</span>
      </span>
      <span className={styles.costPill}>
        已耗 <span className={styles.v}>${cost.toFixed(4)}</span>
      </span>
    </div>
  )
}
```

注意:`snap.total_cost_usd` / `snap.total_tokens_in` / `snap.total_tokens_out` / `snap.current_model` 等字段需 verify存在于 `currentChatState`。若不存在改用真实字段名(grep 当前 CostMeter 用了什么)。

- [ ] **Step 3: 重写 `frontend/src/components/chat/StreamingIndicator.tsx`**

```tsx
import { useSnapshot } from 'valtio'
import { currentChatState } from '@/store/current-chat'
import { LoadingDots } from '@/components/states/LoadingDots'
import styles from '@/styles/chat.module.scss'

export function StreamingIndicator() {
  const snap = useSnapshot(currentChatState)
  const phase = snap.streaming_phase
  if (phase === 'idle') return null

  const label =
    phase === 'thinking' ? '正在思考...' :
    phase === 'tool_calling' ? '调用工具中' :
    phase === 'streaming' ? '生成回复中...' :
    '处理中...'

  return (
    <div className={styles.streamingIndicator} data-testid="streaming-indicator">
      <LoadingDots />
      <span>{label}</span>
    </div>
  )
}
```

`<LoadingDots>` 依赖 Phase E Task 12 创建。

- [ ] **Step 4: 跑 CostMeter + StreamingIndicator test**

Run: `npm test -- src/components/chat/__tests__/(CostMeter|StreamingIndicator) 2>&1 | tail -30`

Expected: PASS(锚 data-testid)。

- [ ] **Step 5: Visual smoke**

`npm run dev` → 顶栏底下 cost-strip 显示 pill 列表;streaming 时底部 sticky indicator iOS 跳动三点。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/chat/CostMeter.tsx \
        frontend/src/components/chat/StreamingIndicator.tsx
git commit -m "$(cat <<'EOF'
feat(frontend-chat): CostMeter pill 形 + StreamingIndicator iOS 跳动三点

CostMeter 重塑为顶栏下方 cost-strip(在线状态 / Tokens / 已耗 三 pill);
StreamingIndicator 改用 LoadingDots(Phase E)+ phase 标签语义化文案。
Phase D input/meter/streaming 完。LoadingDots 依赖 Phase E。
EOF
)"
```

---

## Phase E · State System(TDD)

### Task 12: 新建 states/ — EmptyState + Skeleton + ErrorState + LoadingDots

**Files:**
- Create: `frontend/src/components/states/LoadingDots.tsx` + `.module.scss` + test
- Create: `frontend/src/components/states/EmptyState.tsx` + `.module.scss` + test
- Create: `frontend/src/components/states/Skeleton.tsx` + `.module.scss` + test
- Create: `frontend/src/components/states/ErrorState.tsx` + `.module.scss` + test
- Create: `frontend/src/components/states/__tests__/*.test.tsx`

- [ ] **Step 1: Write failing test for `LoadingDots`**

`frontend/src/components/states/__tests__/LoadingDots.test.tsx`:

```tsx
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LoadingDots } from '../LoadingDots'

describe('<LoadingDots>', () => {
  it('renders 3 dot spans', () => {
    const { container } = render(<LoadingDots />)
    const dots = container.querySelectorAll('span span')
    expect(dots.length).toBeGreaterThanOrEqual(3)
  })

  it('respects role status for screen readers', () => {
    const { getByRole } = render(<LoadingDots />)
    expect(getByRole('status')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test → expect FAIL**

Run: `npm test -- src/components/states/__tests__/LoadingDots 2>&1 | tail -10`

Expected: FAIL — module not found `../LoadingDots`.

- [ ] **Step 3: Create `LoadingDots.tsx` + `LoadingDots.module.scss`**

`frontend/src/components/states/LoadingDots.tsx`:

```tsx
import styles from './LoadingDots.module.scss'

export function LoadingDots({ ariaLabel = 'Loading' }: { ariaLabel?: string }) {
  return (
    <span className={styles.dots} role="status" aria-label={ariaLabel}>
      <span></span>
      <span></span>
      <span></span>
    </span>
  )
}
```

`frontend/src/components/states/LoadingDots.module.scss`:

```scss
.dots {
  display: inline-flex;
  gap: 3px;
  align-items: center;

  span {
    display: inline-block;
    width: 5px; height: 5px;
    border-radius: 50%;
    background: var(--ios-label-secondary);
    animation: bounce 1.2s ease-in-out infinite;
  }
  span:nth-child(2) { animation-delay: 0.15s; }
  span:nth-child(3) { animation-delay: 0.3s; }
}

@keyframes bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-3px); opacity: 1; }
}
```

- [ ] **Step 4: Run test → expect PASS**

Run: `npm test -- src/components/states/__tests__/LoadingDots`

Expected: PASS.

- [ ] **Step 5: Write failing test for `EmptyState`**

`frontend/src/components/states/__tests__/EmptyState.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { EmptyState } from '../EmptyState'

describe('<EmptyState>', () => {
  it('renders title + description', () => {
    render(<EmptyState variant="chat-empty" title="Start chat" description="Try asking" />)
    expect(screen.getByText('Start chat')).toBeInTheDocument()
    expect(screen.getByText('Try asking')).toBeInTheDocument()
  })

  it('fires CTA click', async () => {
    const cta = vi.fn()
    const user = userEvent.setup()
    render(
      <EmptyState
        variant="chat-empty"
        title="Empty"
        cta={{ label: 'Start', onClick: cta, primary: true }}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Start' }))
    expect(cta).toHaveBeenCalled()
  })

  it('three variant data-testid', () => {
    const { rerender } = render(<EmptyState variant="chat-empty" title="x" />)
    expect(screen.getByTestId('empty-chat-empty')).toBeInTheDocument()
    rerender(<EmptyState variant="list-empty" title="x" />)
    expect(screen.getByTestId('empty-list-empty')).toBeInTheDocument()
    rerender(<EmptyState variant="search-empty" title="x" />)
    expect(screen.getByTestId('empty-search-empty')).toBeInTheDocument()
  })
})
```

- [ ] **Step 6: Run test → expect FAIL**

Run: `npm test -- src/components/states/__tests__/EmptyState`

Expected: FAIL — module not found.

- [ ] **Step 7: Create `EmptyState.tsx` + scss**

`frontend/src/components/states/EmptyState.tsx`:

```tsx
import type { ReactNode } from 'react'
import { Icon, type IconName } from '@/components/shared/Icon'
import styles from './EmptyState.module.scss'

export interface EmptyStateProps {
  variant: 'chat-empty' | 'list-empty' | 'search-empty'
  title: string
  description?: string
  cta?: { label: string; onClick: () => void; primary?: boolean }
  icon?: ReactNode
}

const DEFAULT_ICON: Record<EmptyStateProps['variant'], IconName> = {
  'chat-empty': 'sparkle',
  'list-empty': 'document',
  'search-empty': 'search',
}

export function EmptyState({ variant, title, description, cta, icon }: EmptyStateProps) {
  return (
    <div className={styles.empty} data-testid={`empty-${variant}`} role="region">
      <div className={styles.icon}>
        {icon ?? <Icon name={DEFAULT_ICON[variant]} size={32} />}
      </div>
      <div className={styles.title}>{title}</div>
      {description ? <div className={styles.desc}>{description}</div> : null}
      {cta ? (
        <button
          type="button"
          className={`${styles.cta} ${cta.primary ? styles.primary : ''}`}
          onClick={cta.onClick}
        >
          {cta.label}
        </button>
      ) : null}
    </div>
  )
}
```

`frontend/src/components/states/EmptyState.module.scss`:

```scss
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  gap: 12px;
  color: var(--ios-label-secondary);
}

.icon {
  width: 64px; height: 64px;
  border-radius: var(--ios-radius-lg);
  background: var(--ios-bg-grouped);
  display: flex; align-items: center; justify-content: center;
  color: var(--ios-label-tertiary);
}

.title {
  font-size: 16px;
  font-weight: 600;
  color: var(--ios-label);
  letter-spacing: -0.01em;
}

.desc {
  font-size: 13px;
  color: var(--ios-label-secondary);
  text-align: center;
  max-width: 320px;
}

.cta {
  margin-top: 12px;
  padding: 8px 16px;
  background: var(--ios-bg-grouped);
  color: var(--ios-blue);
  border: none;
  border-radius: var(--ios-radius-pill);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.12s;

  &:hover { background: rgba(0, 122, 255, 0.08); }
  &.primary {
    background: var(--ios-blue); color: #fff;
    &:hover { background: var(--ios-blue-hover); }
  }
}
```

- [ ] **Step 8: Run test → expect PASS**

Run: `npm test -- src/components/states/__tests__/EmptyState`

Expected: PASS.

- [ ] **Step 9: Write failing test for `Skeleton`**

`frontend/src/components/states/__tests__/Skeleton.test.tsx`:

```tsx
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Skeleton } from '../Skeleton'

describe('<Skeleton>', () => {
  it('renders 3 bars by default', () => {
    const { container } = render(<Skeleton variant="list" />)
    expect(container.querySelectorAll('[data-testid="skeleton-bar"]').length).toBe(3)
  })

  it('respects count', () => {
    const { container } = render(<Skeleton variant="list" count={5} />)
    expect(container.querySelectorAll('[data-testid="skeleton-bar"]').length).toBe(5)
  })

  it('three variants render', () => {
    const { rerender, container } = render(<Skeleton variant="list" />)
    expect(container.querySelector('[data-testid="skeleton-list"]')).toBeInTheDocument()
    rerender(<Skeleton variant="message" />)
    expect(container.querySelector('[data-testid="skeleton-message"]')).toBeInTheDocument()
    rerender(<Skeleton variant="card" />)
    expect(container.querySelector('[data-testid="skeleton-card"]')).toBeInTheDocument()
  })
})
```

- [ ] **Step 10: Run test → expect FAIL**

- [ ] **Step 11: Create `Skeleton.tsx` + scss**

`frontend/src/components/states/Skeleton.tsx`:

```tsx
import styles from './Skeleton.module.scss'

export interface SkeletonProps {
  variant: 'list' | 'message' | 'card'
  count?: number
  height?: number
}

export function Skeleton({ variant, count = 3, height }: SkeletonProps) {
  const bars = Array.from({ length: count }, (_, i) => i)
  return (
    <div className={styles[variant]} data-testid={`skeleton-${variant}`} role="status" aria-live="polite">
      {bars.map((i) => (
        <div
          key={i}
          className={styles.bar}
          data-testid="skeleton-bar"
          style={height ? { height: `${height}px` } : undefined}
        />
      ))}
    </div>
  )
}
```

`frontend/src/components/states/Skeleton.module.scss`:

```scss
@keyframes shimmer {
  0% { background-position: -800px 0; }
  100% { background-position: 800px 0; }
}

.bar {
  background: linear-gradient(
    90deg,
    var(--ios-bg-grouped) 0%,
    var(--ios-bg-secondary) 40%,
    var(--ios-bg-grouped) 80%
  );
  background-size: 800px 100%;
  animation: shimmer 2s linear infinite;
  border-radius: var(--ios-radius-sm);
  height: 14px;
}

.list {
  display: flex; flex-direction: column;
  gap: 12px;
  padding: 12px;

  .bar { height: 44px; border-radius: 10px; }
}

.message {
  display: flex; flex-direction: column;
  gap: 14px;

  .bar { height: 80px; border-radius: 18px; }
}

.card {
  display: flex; flex-direction: column;
  gap: 10px;

  .bar { height: 120px; border-radius: var(--ios-radius-lg); }
}
```

- [ ] **Step 12: Run test → expect PASS**

- [ ] **Step 13: Write failing test for `ErrorState`**

`frontend/src/components/states/__tests__/ErrorState.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ErrorState } from '../ErrorState'

describe('<ErrorState>', () => {
  it('renders default title + description', () => {
    render(<ErrorState description="Network error" />)
    expect(screen.getByText('出错了')).toBeInTheDocument()
    expect(screen.getByText('Network error')).toBeInTheDocument()
  })

  it('fires onRetry click', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    render(<ErrorState onRetry={onRetry} />)
    await user.click(screen.getByRole('button', { name: '重试' }))
    expect(onRetry).toHaveBeenCalled()
  })

  it('fires onReset click', async () => {
    const onReset = vi.fn()
    const user = userEvent.setup()
    render(<ErrorState onReset={onReset} />)
    await user.click(screen.getByRole('button', { name: '重置' }))
    expect(onReset).toHaveBeenCalled()
  })

  it('role alert for screen readers', () => {
    render(<ErrorState />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})
```

- [ ] **Step 14: Run test → expect FAIL**

- [ ] **Step 15: Create `ErrorState.tsx` + scss**

`frontend/src/components/states/ErrorState.tsx`:

```tsx
import { Icon } from '@/components/shared/Icon'
import styles from './ErrorState.module.scss'

export interface ErrorStateProps {
  title?: string
  description?: string
  onRetry?: () => void
  onReset?: () => void
}

export function ErrorState({
  title = '出错了',
  description,
  onRetry,
  onReset,
}: ErrorStateProps) {
  return (
    <div className={styles.error} data-testid="error-state" role="alert">
      <div className={styles.icon}>
        <Icon name="close" size={20} />
      </div>
      <div className={styles.title}>{title}</div>
      {description ? <div className={styles.desc}>{description}</div> : null}
      {(onRetry || onReset) ? (
        <div className={styles.actions}>
          {onRetry ? (
            <button
              type="button"
              className={`${styles.btn} ${styles.primary}`}
              onClick={onRetry}
            >
              重试
            </button>
          ) : null}
          {onReset ? (
            <button
              type="button"
              className={styles.btn}
              onClick={onReset}
            >
              重置
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
```

`frontend/src/components/states/ErrorState.module.scss`:

```scss
.error {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 24px;
  gap: 10px;
}

.icon {
  width: 48px; height: 48px;
  border-radius: 50%;
  background: rgba(255, 59, 48, 0.1);
  color: var(--ios-red);
  display: flex; align-items: center; justify-content: center;
}

.title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ios-label);
}

.desc {
  font-size: 13px;
  color: var(--ios-label-secondary);
  text-align: center;
}

.actions {
  display: flex;
  gap: 8px;
  margin-top: 6px;
}

.btn {
  padding: 7px 16px;
  border-radius: var(--ios-radius-pill);
  border: none;
  background: var(--ios-bg-grouped);
  color: var(--ios-blue);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;

  &:hover { background: rgba(0, 122, 255, 0.08); }
  &.primary {
    background: var(--ios-blue); color: #fff;
    &:hover { background: var(--ios-blue-hover); }
  }
}
```

- [ ] **Step 16: Run test → expect PASS**

Run: `npm test -- src/components/states 2>&1 | tail -20`

Expected: 全 PASS(4 个 test file)。

- [ ] **Step 17: Commit**

```bash
git add frontend/src/components/states/
git commit -m "$(cat <<'EOF'
feat(frontend-states): 新建 state 系统四件套 — Empty/Skeleton/Error/LoadingDots

EmptyState 三变体(chat-empty / list-empty / search-empty)+ default icon +
optional CTA;Skeleton 三变体(list / message / card)+ shimmer 动画;
ErrorState 通用错误 + retry + reset;LoadingDots 跳动三点。全 TDD,
4 个 test file,11 个 assertion。
EOF
)"
```

---

### Task 13: 全站 state 接入点替换

**Files:**
- Modify: `frontend/src/components/chat/ChatPane.tsx`(已在 Task 7 接 EmptyState)
- Modify: `frontend/src/components/sidebar/chat-session-list.tsx`(已在 Task 5 接 Skeleton + EmptyState)
- Modify: `frontend/src/components/chat/ToolCallCard.tsx`(error 状态升级为 ErrorState inline)
- Modify: `frontend/src/components/chat/ResearchReportCard.tsx`(error 状态升级)
- Modify: `frontend/src/components/chat/StreamingIndicator.tsx`(已接 LoadingDots in Task 11)

- [ ] **Step 1: 检查所有接入点 import 完成**

Run: `grep -r "from '@/components/states/" frontend/src/ | head -20`

Expected: 至少 5 个文件 import(`ChatPane` / `chat-session-list` / `StreamingIndicator` / 后续 `ToolCallCard` / `ResearchReportCard`)

- [ ] **Step 2: ToolCallCard error 状态接 ErrorState(可选 — 当前 inline `toolCardError` class 已足够小)**

判断:错误展示如果只是 "失败" 字样 + 红 icon,inline class 即可,不必引 `ErrorState`(大组件,占空间)。Skip 此步,保留 Task 8 的 inline 处理。

- [ ] **Step 3: ResearchReportCard 错误状态 — 同上,skip(大错误展示不在本范围,留 dogfood 反馈)**

- [ ] **Step 4: Visual smoke 跑接入点**

Run: `npm run dev`

测试:
1. 登录后 `/chat/landing` 空状态 → `<EmptyState variant="chat-empty">` 显示
2. Sidebar 加载中 → `<Skeleton variant="list" count={5}>`
3. Streaming → `<LoadingDots>` 跳动
4. 新 session 0 消息 → empty state 显示

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/components/chat/ChatPane.tsx \
        frontend/src/components/chat/StreamingIndicator.tsx \
        frontend/src/components/sidebar/chat-session-list.tsx
git commit -m "$(cat <<'EOF'
feat(frontend-states): wire EmptyState/Skeleton/LoadingDots 到接入点

ChatPane empty → EmptyState chat-empty;chat-session-list loading →
Skeleton list 5 条;chat-session-list empty → EmptyState list-empty;
StreamingIndicator → LoadingDots phase 文案。ToolCallCard / ResearchReport
错误展示仍用 inline class(小展示无须大 ErrorState)。Phase E 完。
EOF
)"
```

---

## Phase F+G · Cleanup + Dogfood

### Task 14: 清杂质 + dogfood 跑 3 轮 + 刷 README

**Files:**
- Verify: 全 frontend
- Modify: `frontend/README.md`

- [ ] **Step 1: grep 所有遗留 emoji in frontend/src(production)**

Run:
```bash
grep -rE '[📋⚡📁📊📈📉]' frontend/src/ --include='*.tsx' --include='*.ts' --exclude-dir='__tests__'
```

Expected: 仅剩 `research/new.tsx` 2 处(backend summary prefix,out of scope per spec § 10.1)。其他全 0。

- [ ] **Step 2: grep 所有 `var(--ios-*)` selector 跨文件**

Run:
```bash
grep -rE 'var\(--ios-' frontend/src/ --include='*.scss' --include='*.css' --include='*.tsx' | wc -l | tr -d ' '
```

Expected: ≥30(spec § 10.1 evaluation criterion)。

Run:
```bash
grep -rlE 'var\(--ios-' frontend/src/ | wc -l | tr -d ' '
```

Expected: ≥5 文件(spec § 10.1)。

- [ ] **Step 3: grep 所有 chat.module.scss 硬编码颜色 → 应为 0**

Run: `grep -oE '#[0-9a-fA-F]{3,8}' frontend/src/styles/chat.module.scss | wc -l | tr -d ' '`

Expected: 0(spec § 10.1)。

- [ ] **Step 4: grep 所有 DEBUG console.log in InputArea → 应为 0**

Run: `grep -c "DEBUG" frontend/src/components/chat/InputArea.tsx`

Expected: 0(spec § 10.1)。

- [ ] **Step 5: 跑全部 unit test 与 Playwright e2e**

```bash
cd frontend && npm test 2>&1 | tail -5
cd frontend && npx playwright test 2>&1 | tail -10
```

Expected: 两者全 PASS。

- [ ] **Step 6: Dogfood 完整用户旅程跑 3 轮**

User journey:
1. login → `/chat/landing` empty state
2. 新对话 → 发送 "工商银行现价多少?"
3. 看 stream (LoadingDots + 打字)
4. 看 tool card 出现(tushare 调用)
5. 看 research report card 出现(escalate 触发后)
6. 升级深度研究 → confirm dialog
7. 取消生成
8. 重命名 session
9. 切换 session → 看 active 卡片样式
10. logout

每轮 dogfood 记录 1-3 个微调点(字号 / 间距 / 色彩偏冷/暖 / hover 反馈不够 / 动效迟滞 ...)。

- [ ] **Step 7: 根据 dogfood 反馈微调**

主要可能改的:
- chat.module.scss 中 `gap` / `padding` / `font-size`
- app-shell.module.scss 中 sidebar item gap
- 动效 transition duration(150ms vs 250ms)

每个微调一个独立 commit。

- [ ] **Step 8: 刷 `frontend/README.md` 设计语言段**

```bash
cat frontend/README.md
```

如果有 "Design language" / "Styling" / "Theme" / "设计语言" 段,改为:

```markdown
## 设计语言

iOS 简约淡雅风(2026-05-20 起;先前 AlphaScout Editorial × Terminal 已废弃)。

- **字体栈**:`-apple-system, "SF Pro Text", "PingFang SC", "Helvetica Neue", system-ui, sans-serif`
- **配色锚**:iOS systemBlue(`#007aff`)/ systemGray 阶 / 灰阶 label / 大圆角(12-16px)/ 微妙阴影
- **核心特征**:
  - 消息气泡(user iOS 蓝靠右 / AI 灰白靠左)
  - 胶囊输入框(22px radius)+ 圆形发送按钮
  - 毛玻璃 TopBar / InputRegion(`backdrop-filter: blur(20px)` + solid fallback)
  - SF Symbols 风 SVG icon(参 `components/shared/Icon.tsx`)
- **Token 入口**:
  - `styles/tokens.css` → `--ios-*` namespace(CSS Module 消费)
  - `themes/tokens-retail.ts` → antd ConfigProvider(retail · `/chat/*` 等)
  - `themes/tokens-banking.ts` → antd ConfigProvider(banking · `/monitoring`/`credit-report` — 不动)
- **状态系统**:`components/states/` 含 EmptyState / Skeleton / ErrorState / LoadingDots

详见 `docs/superpowers/specs/2026-05-20-frontend-ios-polish-design.md`。
```

如果 README 没有相应段,在 "Tech Stack" 段后插入。

- [ ] **Step 9: Final commit + push**

```bash
git add frontend/README.md
git commit -m "$(cat <<'EOF'
docs(frontend): README 设计语言段切到 iOS 简约淡雅

iOS HIG token 系统 / 消息气泡 / 胶囊输入 / SF Symbols icon / 毛玻璃
TopBar 列入 README。dogfood 3 轮通过,所有 spec § 10.1 量化指标达标
(0 硬编码颜色 / ≥30 selector 跨 ≥5 文件 / 0 DEBUG log / 0 emoji in
chat 主路径)。Phase F+G + 全 plan 完。
EOF
)"
```

完成全 plan。

---

## Self-Review

### 1. Spec coverage check

| Spec 章节 | 对应 task |
|---|---|
| § 1 问题陈述(A/B/C 痛点)| Task 1(A)+ 4-6(B)+ 7-8(C)|
| § 2 G1 chat 主路径整屏 iOS 风 | Task 1-11 全套 |
| § 2 G2 Sidebar/TopBar | Task 4-6 |
| § 2 G3 消息流统一视觉 | Task 7-8 |
| § 2 G4 状态系统 | Task 12-13 |
| § 2 G5 tokens.css 真正被消费 | Task 1 + Task 14 verify |
| § 2 G6 杂质清理 | Task 10(DEBUG)+ Task 14(emoji / verify)|
| § 3 设计风格 Apple HIG-leaning + 局部毛玻璃 | tokens.css + chat.module.scss + app-shell.module.scss |
| § 4 Token 系统重构 | Task 1-3 |
| § 5 组件清单(13 改写 + 4 新建)| Task 4-13 |
| § 6 状态系统 EmptyState/Skeleton/ErrorState/LoadingDots | Task 12 |
| § 7.1 数据层零改动 | (验证)所有 task 不动 hook/store/api/types — verify by grep diff |
| § 7.2 测试策略 unit + e2e + dogfood | Task 14 step 5 + 6 |
| § 7.3 可访问性 | LoadingDots role=status + ErrorState role=alert + EmptyState role=region |
| § 8 工作量分解 7 phase | Plan 7 phase = A/B/C/D/E/F/G,task 14 = 7 phase mapping |
| § 9 风险 R1-R7 | R1 → Task 2/3 全站 smoke;R2 → Task 9 校准;R3 → Task 4 @supports fallback;R5 → 各 task data-testid;R6 → Task 14 dogfood |
| § 10 评估指标 | Task 14 step 1-4 |

无 gap。

### 2. Placeholder scan

- 无 "TBD / TODO / FIXME / 后补"
- 所有 step 含完整代码 / 完整 grep 命令 / 完整 commit 信息
- "依赖 Phase E" 注释是 ordering 提示,不是 placeholder

### 3. Type consistency

- `EmptyState` props 统一 `variant: 'chat-empty' | 'list-empty' | 'search-empty'`(Task 12 + ChatPane + chat-session-list 一致)
- `Skeleton` props 统一 `variant: 'list' | 'message' | 'card'`
- `ErrorState` props 统一 `{ title?, description?, onRetry?, onReset? }`
- `Icon` props 统一 `{ name, size?, style?, className? }` + IconName enum
- `ChatSessionListProps` 加 `query?: string`(Task 5 add,sidebar.tsx Task 4 传入)

类型一致。

### 4. 执行顺序提示

部分 task 引用尚未存在的组件(`<EmptyState>` `<Skeleton>` `<LoadingDots>` `<Icon>`)。建议执行顺序:

```
Task 1 → 2 → 3                   (Phase A · 串行)
Task 6 (先做 Icon)               (Task 6 step 1 = Icon)
Task 12 (Phase E · 先做 state 系统)
Task 4 → 5                       (Phase B · Sidebar 需要 Icon + State)
Task 7 → 8 → 9                   (Phase C · 不依赖 state — 但 ChatPane 依赖 EmptyState)
Task 10 → 11                     (Phase D)
Task 13                          (Phase E · wire — 各 task 已 inline 完成,Task 13 简化为 verify)
Task 14                          (Phase F+G)
```

如果严格顺序按 Task 编号执行,Task 4-5 实施时 `EmptyState` / `Skeleton` 尚不存在 → 临时 inline placeholder,等 Task 12 完成后回填。或采用上面顺序(先 Icon + State 再 sidebar)。subagent-driven mode 下推荐后者。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-20-frontend-ios-polish-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — 我 dispatch fresh subagent per task,review between tasks,fast iteration。适合本 plan 因为多个 task 视觉改动可视审验,subagent 跑完后 review 可加视觉对比。

**2. Inline Execution** — 在本 session 用 executing-plans,batch 执行 + checkpoint 间 review。

**Which approach?**
