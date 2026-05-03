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

## Design tokens

双 theme(B 端 banking 深色 / C 端 retail 浅色)tokens 在 `src/themes/`, 设计规范 + 配色 / typography / spacing 详见 [docs/design-tokens.md](../docs/design-tokens.md).

## Page mapping

现有 pages 跟 v0.8.x 5 use case 的映射 + 待新建 pages 见 [docs/frontend-page-mapping.md](../docs/frontend-page-mapping.md).

## 跟 backend 协同

- backend 默认起在 `http://localhost:8000`
- frontend dev server proxy 配置见 `vite.config.ts`
- API 类型定义在 `src/api/`
