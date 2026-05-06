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

## Design tokens

双 theme(B 端 banking 深色 / C 端 retail 浅色)tokens 在 `src/themes/`, 设计规范 + 配色 / typography / spacing 详见 [docs/design-tokens.md](../docs/design-tokens.md).

## Page mapping

现有 pages 跟 v0.8.x 5 use case 的映射 + 待新建 pages 见 [docs/frontend-page-mapping.md](../docs/frontend-page-mapping.md).

## 跟 backend 协同

- backend 默认起在 `http://localhost:8000`
- frontend dev server proxy 配置见 `vite.config.ts`
- API 类型定义在 `src/api/`
