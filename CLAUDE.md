# 项目级 Claude 上下文

## 这是什么

Claude Code 在本仓库工作时会自动加载这个文件。它是项目级**长期上下文**入口（决策的 *why* / 测试约定 / 已知坑），跟代码一起进 git，跨机/跨 session 共享。

## 项目知识卡片（`docs/claude-context/`）

短卡片，三段式（结论 + Why + How to apply）。详细规范见 `docs/claude-context/README.md`。

### 作者 / 作品定位
- [作品定位与作者期望](docs/claude-context/user-portfolio-target.md) — 项目是个人作品,不追求生产级,但要体现 LLM 算法+应用设计的技术深度

### 产品 / Use case 演进
- [v1.0 第二个 use case = 持仓监控](docs/claude-context/v1.0-use-case-2-portfolio-monitoring.md) — B-3 + C-4 一体两面;选 vs C-3 的理由;锚 `2026-05-07-v1.0-portfolio-monitoring-design.md`
- [9 个 use case 重新分类](docs/claude-context/v1-use-case-classification.md) — 3 支柱(B-1 / B-3+C-4 / C-3) + 组件群(B-7 / C-1 / C-5) + 显式不做(C-2 / C-7)
- [产品决策默认 aggressive minimalism](docs/claude-context/product-minimalism-default.md) — 推荐时默认走克制版本,v1.x escape hatch 走架构留口子,不破坏已定的"不做"决策

### KB（知识库）子系统
- [KB 切块策略](docs/claude-context/kb-chunking-strategy.md) — 类型路由：研报 semantic / 财报 section / 政策 clause；中文 separators + tiktoken 计数 + 关键参数
- [KB Embedding 选型](docs/claude-context/kb-embedding-choice.md) — qwen text-embedding-v3 主力（1024d），BGE-M3 stub 留 v0.9；batch=10 / 同维互换不重建 collection
- [KB 评估缺口](docs/claude-context/kb-eval-gaps.md) — 当前 eval 是 agent 端到端 LLM-judge，缺 chunking/embedding/检索的离线指标；v0.8 调优 spec 是补口位置

### 工程约定与 dep 管理
- [重型 deps 走 optional extras](docs/claude-context/optional-extras-for-heavy-deps.md) — base 留 core，重型/可选进 `[project.optional-dependencies]`
- [import 链假设要 smoke test 验](docs/claude-context/verify-import-chain-with-smoke-test.md) — spec 谈"X import 会 fail"必须先 `python -c "from X import"` 实测，grep 看不到 lazy/transitive/subprocess

### 测试 / DB
- [测试 DB 分层策略](docs/claude-context/test-db-layered-strategy.md) — L0/L1 sqlite-override，L2.5 真 PG fixture 守护 serve path
- [容器化依赖 fixture 模式](docs/claude-context/pg-test-container-pattern.md) — session-scoped + 外部已起则复用 / 自起则负责拆

### v0.9.x 阶段性里程碑
- [v0.9.x 不引 alembic](docs/claude-context/v0.9.x-no-alembic-until-db-unify.md) — schema 用 `create_all()` 幂等；alembic 推到 #3.5 DB 统一
- [v0.9.x #2.5 PG + CI ship 完](docs/claude-context/v0.9.x-pg-ci-done.md) — PR #21 ship，serve path 已被 CI e2e 守护
- [v0.9 skill loader L1+L2+L3a ship 完](docs/claude-context/v0.9-skill-loader-l1-l2-l3a-landed.md) — Plan 2a; 7 skill L1 + risk_assessment L3a demo; S2/S3/S4/S5/S10 撞透; L3b 留 Plan 2b

### v1.0 ship
- [v1.0 持仓监控引擎 + 5 类公告 ship 完](docs/claude-context/v1.0-monitoring-engine-done.md) — Celery + Redis + PG 统一 / 5 决策落地
- [Celery + Redis 测试 fixture pattern](docs/claude-context/celery-redis-test-fixture-pattern.md) — L0/L1 eager + L2 worker subprocess
- [v0.9 chat frontend foundation landed](docs/claude-context/v0.9-chat-frontend-foundation.md) — Plan 4a ship,AppShell + 240px Sidebar + 3 valtio stores + useChatSSE(F6/F8);Plan 4b 填 ChatPane / EscalationConfirmDialog
- [v0.9 chat plan 4b frontend chatpane ship](docs/claude-context/v0.9-chat-plan4b-architecture.md) — ChatPane + EscalationConfirmDialog + Reports + F1-F10 polish landed (e2e deferred)
- [v0.9 chat C.1+C.2 ship](docs/claude-context/v0.9-chat-c1c2-architecture.md) — production-style chat: LangGraph supervisor + MCP + Skill L1/L2/L3 + Escalation + chat-first frontend / 30 工业难题 P0+P1 全撞 / cassette+dogfood manual follow-up

## 设计稿与实施计划

`docs/superpowers/specs/` 和 `docs/superpowers/plans/` 是更详细的决策评估和任务拆分。本仓库的设计语言：spec 评决策、plan 推实施、claude-context 沉淀长期 working memory。

## 跨机 / 多机开发

这个文件 + `docs/claude-context/` 跟代码一起 git push，多机开发 `git pull` 即同步。**用户私人偏好**（不应进项目仓的内容）留在 `~/.claude/projects/<project>/memory/`，可单独私有 repo 同步。
