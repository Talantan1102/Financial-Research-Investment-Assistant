# Design Tokens

本文档说明 frontend 的 design tokens 设计哲学 + B/C 双 theme 配色规范, 跟业务梳理 spec § 1.2 立论 (B 长报告 / C 短回答+列表 各自体验最优) 自然对齐。

**Source**: `frontend/src/themes/`(`tokens-base.ts` / `tokens-banking.ts` / `tokens-retail.ts` / `index.ts`)

## 设计哲学

按业务梳理 spec § 1.2 "Writer schema 分叉 + 入口 UI 分叉" — B/C 两端共用底层(底座 + 5 agent + 数据), 但 deliverable 形态(长报告 vs 短回答+列表)+ 入口 UI 风格分叉。Design tokens 同样:

- **共用 tokens(base)**: spacing scale / border radius / motion 时长 / font stack / font sizes / 语义色(success/warning/error/info, 涨跌色)
- **B 端 tokens(banking)**: Hebbia / Bloomberg-inspired 深色 navy + 金色 accent + monospace 数字。banking workflow 数据密度大, 深色减疲劳, 金色 accent 强调关键决策。
- **C 端 tokens(retail)**: Perplexity-inspired 浅色 + 蓝色 accent + sans-serif 现代。retail 用户偏好轻量交互, 浅色亲和力强, 蓝色 accent 中性。

## Theme 切换机制

路由级判断(`frontend/src/themes/index.ts` `useActiveTheme()`)。无用户主题切换 toggle (scope 不要 creep)。

| 路由前缀 | Theme |
|---|---|
| `/credit-report/*` | banking |
| `/portfolio-monitoring/*` | banking |
| `/monitoring/*` | banking |
| `/ticker/*` | retail |
| `/watchlist/*` | retail |
| `/screener/*` | retail |
| `/chat/*` | retail |
| `/`(landing) | retail(default) |

## 配色规范

### Banking 调色板(深色)

| 用途 | 值 |
|---|---|
| 背景主 | `#0a1929`(deep navy) |
| 背景次 | `#132f4c` |
| 背景三 | `#1e3a5f` |
| 文本主 | `#e7ebf0` |
| 文本次 | `#b2bac2` |
| 边框 | `#1e3a5f` |
| Accent | `#d4af37`(gold) |

### Retail 调色板(浅色)

| 用途 | 值 |
|---|---|
| 背景主 | `#ffffff` |
| 背景次 | `#f7f8fa` |
| 背景三 | `#eef0f3` |
| 文本主 | `#1a1d21` |
| 文本次 | `#5d6975` |
| 边框 | `#e5e8eb` |
| Accent | `#1890ff` |

### 涨跌色(共用, 中国标准)

| 状态 | 值 |
|---|---|
| 上涨 | `#f5222d`(red) |
| 下跌 | `#52c41a`(green) |

(注: 跟国际标准相反, 但符合 A 股用户习惯)

## Typography

### 字体栈

- **Sans-serif**(默认): `-apple-system, "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif`
- **Monospace**(banking 数字): `"SF Mono", "JetBrains Mono", "Cascadia Code", Consolas, monospace`

### 字号 scale

| Token | 值 | 用途 |
|---|---|---|
| `xs` | 12px | tag / label |
| `sm` | 14px | secondary text |
| `base` | 16px | body |
| `lg` | 18px | subtitle |
| `xl` | 24px | section title |
| `xxl` | 32px | page title |

## Spacing scale

8px base, sequence: 4 / 8 / 16 / 24 / 32 / 48

## Border radius

- `sm` 4px (banking 默认, 严肃感)
- `md` 8px (retail 默认)
- `lg` 12px (retail card)

## Motion 时长

- fast 150ms (微交互)
- base 250ms (默认)
- slow 400ms (页面切换)

## 不在本文档范围

- 完整 component library — 用 Antd 5 默认 + 上面 ConfigProvider 注入即可
- Storybook — scope 不要 creep, v1.x 评估
- Light/dark 用户切换 — 只走路由判断
