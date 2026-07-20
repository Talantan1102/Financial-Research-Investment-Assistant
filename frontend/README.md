# AI 投研 copilot — 前端

个人 portfolio 项目, 服务"投资生命周期"3 阶段(投前评估 / 投后监控 / 标的发现), 同时支持 B 端 banking 用户(信贷调查报告 / 持仓预警)和 C 端散户(个股研究 / 自选股监控 / NL 选股)。

详见 [业务梳理 spec](../docs/superpowers/specs/2026-05-03-business-clarification-v1-design.md)。

## 技术栈

| 类别 | 技术 |
|---|---|
| Framework | React 19 + Vite 6 |
| Language | TypeScript 5.7 |
| UI | Antd 5(双 theme: banking / retail, 路由级切换) |
| Charts | ECharts 5 |
| Routing | React Router 6 |
| State | valtio |
| HTTP | axios |
| Markdown | marked |

## 环境要求

- Node.js >= 18
- npm >= 9

## 启动

```bash
# 1. 安装依赖
npm install --legacy-peer-deps

# 2. 启动开发服务器
npm run dev
```

访问 http://localhost:5173/

## Build

```bash
npm run build
```

构建产物在 `dist/`.

## Lint

```bash
npm run lint
```

## Tests

前端测试基础设施(v0.9.x 加入 — 解决 dogfood 时 401 → API exception → SSE 500 → UI 不渲染多层 bug 没被 build 阶段拦住的根因)。

### Vitest 单元测试

覆盖 `store/` `api/` `api/request/plugins/` 三层关键逻辑(SSE event 解析、CRUD URL/payload、401 拦截器),不依赖真 backend / dev server / 浏览器。

```bash
npm run test          # 单次跑(CI 模式)
npm run test:watch    # 文件变化即重跑(开发模式)
```

### Playwright e2e

最小化 frontend 回归网 — 启 `vite` dev server, 拿 `page.route()` mock 后端, 跑 chromium。**不真启 backend / 不真调 LLM**。

```bash
# 第一次运行需装 chromium(已装过可跳)
npx playwright install chromium

npm run test:e2e
```

测试在 `tests/e2e/`:landing.spec.ts 覆盖 `/login` `/register` `/` 三页基本渲染 + AlphaScout brand assertion。

### CI 集成(后续)

vitest + playwright 已 self-contained 不依赖 backend, 后续可加到 GitHub Actions(本 task 范围外):

```yaml
# .github/workflows/frontend-test.yml(草稿,后续 task)
- run: cd frontend && npm install --legacy-peer-deps
- run: cd frontend && npm run build
- run: cd frontend && npm run test
- run: cd frontend && npx playwright install --with-deps chromium
- run: cd frontend && npm run test:e2e
```

## 设计语言

iOS 简约淡雅风(2026-05-20 起;先前 AlphaScout Editorial × Terminal 已废弃)。

- **字体栈**:`-apple-system, "SF Pro Text", "SF Pro Display", "PingFang SC", "Helvetica Neue", system-ui, sans-serif`
- **配色锚**:iOS systemBlue(`#007aff`)/ systemGray 阶 / 大圆角(12-16px)/ 微妙阴影 / 毛玻璃 backdrop-blur
- **核心特征**:
  - 消息气泡(user iOS 蓝靠右 / AI 灰白靠左)
  - 胶囊输入框(22px radius)+ 圆形发送按钮
  - 毛玻璃 TopBar / InputRegion(`backdrop-filter: blur(20px)` + solid fallback)
  - SF Symbols 风 SVG icon(`components/shared/Icon.tsx`,20 个 icon)
- **Token 入口**:
  - `styles/tokens.css` → `--ios-*` namespace(CSS Module 消费)+ `--as-*` legacy fallback(non-chat 页 e.g. research detail)
  - `themes/tokens-retail.ts` → antd ConfigProvider(retail · `/chat/*` + 默认 route)
  - `themes/tokens-banking.ts` → antd ConfigProvider(banking · `/monitoring`/`credit-report` — 不动)
- **状态系统**:`components/states/` — EmptyState / Skeleton / ErrorState / LoadingDots
- **Spec & Plan**:`docs/superpowers/specs/2026-05-20-frontend-ios-polish-design.md` + `docs/superpowers/plans/2026-05-20-frontend-ios-polish-plan.md`

## Page mapping

现有 pages 跟 v0.8.x 5 use case 的映射 + 待新建 pages 见 [docs/frontend-page-mapping.md](../docs/frontend-page-mapping.md).

## 跟 backend 协同

- backend 默认起在 `http://localhost:8000`
- frontend dev server proxy 配置见 `vite.config.ts`
- API 类型定义在 `src/api/`
- 当前执行面使用 Run Control Plane 的六个操作：创建 Run、查询 Run、events SSE 快照、trace、cancel、resume；前端不再调用旧 `/api/v0/chat` 执行路由。
- Scheduler、Dispatcher 和 Worker 是独立后端进程；浏览器请求不会持有模型执行生命周期。

下方 v0.9 chat-first 小节保留的是页面组件和交互设计背景，不代表仍注册旧 chat runner 或旧 chat SSE API。

## v0.9 chat-first frontend foundation (Plan 4a)

Routes:
- `/` → redirect `/chat`
- `/chat` ChatLandingPage (auto-creates session + redirects)
- `/chat/:session_id` ChatSessionPage (Plan 4a foundation; Plan 4b fills ChatPane)
- `/reports` ReportsListPage (placeholder)
- `/research` `/research/new` `/research/:id` (preserved)
- `/portfolio` `/monitoring` `/knowledge` `/auth/*` (preserved)

Stores: `chatSessionsStore` / `currentChatStore` / `escalationStore` (valtio).
Hook: `useChatSSE({ sessionId })` returns `{ sendMessage, abort, status }` with F6 reconnect (last_event_id, 1s/2s/4s/8s/30s cap) and F8 multi-chat abort-on-swap.
Layout: `AppShell` (TopBar 56px + Sidebar 240px + Main).

Run tests:
```
npm test
```

## v0.9 chat-first dashboard (Plan 4b ship)

ChatPane internals:
- `<MessageList>` — react-window virtualized list, routes by `message_type`
- `<TextMessage>` — marked + highlight.js + KaTeX + ECharts (chart_specs)
- `<ToolCallCard>` — Cursor-style tri-state (collapsed / expanded / error+retry)
- `<ResearchReportCard>` — summary + 展开 / 跳转 Reports / 继续提问
- `<StreamingIndicator>` — phase bar (思考 / 调工具 / 写回答 / research_*)
- `<InputArea>` — auto-resize + Enter/Shift+Enter + Cmd+K abort + ⚡ Escalate
- `<CostMeter>` — cross-mode breakdown (chat $ + research $)

EscalationConfirmDialog:
- 4 sub-forms (ExplicitTask / ChatDerivedSignals / KnownFacts / SessionMetadata)
- InlineEditField — pencil → input → save → FieldEdit traced into escalationStore.user_edits
- MissingFieldBanner — ⚠️ + LLM 反问 per field
- Confirm → POST `/api/v0/chat/escalate` (Plan 3 endpoint)

Reports page: full impl at `/reports` (list + filter + detail modal + chat deep link).

F1-F10 industry polish:
- F1 token render perf (virtualized + useDeferredValue + memo)
- F2 tool tri-state
- F3 scroll auto-stick
- F4 input UX (4 channels)
- F5 EscalationConfirmDialog inline edit
- F7 markdown + KaTeX + chart_specs
- F9 cost meter cross-mode
- F10 long prompt + paste 占位 (real upload deferred to C.4)
- F6 + F8 from Plan 4a (SSE reconnect + multi-chat lifecycle)
