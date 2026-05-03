# Frontend Pages → v0.8.x Use Case Mapping

本文档列出 `frontend/src/pages/` 当前所有 page 跟 v0.8.x 5 个 use case(B-1 信贷调查报告 / B-3 持仓预警 / C-1 个股研究 / C-2 自选股监控 / C-3 NL 选股 + 通用对话)的映射关系, 作为 v0.8.3 / v0.8.4 / v0.8.5 implementation spec 的前端基础参考。

**Spec anchor**: `docs/superpowers/specs/2026-05-03-business-clarification-v1-design.md`

## 现有 Pages

| 现有 page | 当前用途 | v0.8.x mapping | 行动 / 实施 sub-version |
|---|---|---|---|
| `pages/index/` | 首页(legacy) | landing page | v0.8.5 改造(显示 5 use case 入口卡片, B/C 各 ~) |
| `pages/auth/login` | 登录页 | v1.1.1 OAuth 升级前的占位 | 暂留, v1.1.1 升级 |
| `pages/chat/` | 通用对话 | **B-7 + C 端通用对话** | v0.8.5 改造扩 reference link |
| `pages/knowledge/` | KB 管理 | KB 管理 + 信贷调查报告 viewer | v0.8.5 拆: KB 管理 + 报告 viewer |
| `pages/memory/` | memory 页 | v0.8.4 Memory v1 实施时复用 | v0.8.4 适配新 API |
| `pages/news/` | 新闻 | v0.8.x 不直接需要(Bocha 集成在 chat 内) | v0.8.5 评估砍 or 留作 dashboard |
| `pages/database/` | 数据库管理 | legacy, 不在 v0.8.x scope | 暂留, v1.x 评估砍 |
| `pages/bidding/` | 招标 | legacy, 完全砍 | **v0.8.3-pre T2 已砍** |
| `pages/404/` | 404 | 通用 | 留 |

## 新建 Pages(对应 v0.8.x 5 use case)

| 新建 page | 对应 use case | 实施 sub-version | 入口 theme |
|---|---|---|---|
| `pages/credit-report/` | B-1 信贷调查报告 viewer | v0.8.5(后端 v0.8.2 已 ship, 前端待) | banking |
| `pages/portfolio-monitoring/` | B-3 持仓预警 监控列表 + alert 详情 | v0.8.3 | banking |
| `pages/ticker/` | C-1 个股研究(Perplexity Finance 风) | v0.8.5 | retail |
| `pages/watchlist/` | C-2 自选股监控 | v0.8.5 | retail |
| `pages/screener/` | C-3 NL 选股(同花顺 i问财 风) | v0.8.5 | retail |

## 设计语言映射

按 `docs/design-tokens.md` 双 theme:
- banking 入口(`/credit-report` / `/portfolio-monitoring` / 任何 `/monitoring/*`):深色 navy + 金色 accent + monospace 数字
- retail 入口(`/ticker` / `/watchlist` / `/screener` / `/chat`):浅色 + 蓝色 accent + sans-serif 现代
- landing page (`/`):默认 retail theme

## Edge case
- chat 页同时服务 B-7 (审批人对报告追问) 和 C 端通用对话: 默认 retail theme, 但跳转自 banking 入口时(URL 带 `?from=banking`)切换 banking theme(v0.8.5 实施细节)
