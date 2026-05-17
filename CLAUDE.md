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
- [brainstorm 阶段每节 ~100 行,不做 spec dump](docs/claude-context/brainstorm-section-density.md) — code/prompt/trace/简历叙事推到 spec doc,chat 只对齐决策方向

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

### C.5 Cross-Session Memory(v1.x ship 完)
- [C.5 cross-session memory ship 完](docs/claude-context/c5-cross-session-memory-done.md) — 总卡, MemGPT hierarchical + Zep bi-temporal graph 杂交, 16 工业难题 + 6 算法深度补丁 ship
- [c5 Plan 1A foundation schema ship](docs/claude-context/c5-plan1a-foundation-schema-done.md) — 4 PG 表 + AGE 7v/11e + Milvus alias + app_main lifespan
- [c5 Plan 1B business foundation ship](docs/claude-context/c5-plan1b-business-foundation-done.md) — Memory Protocol + HierarchicalMemory 骨架 + working blocks + cold_start + reconciliation 入口
- [c5 Plan 2A write pipeline core ship](docs/claude-context/c5-plan2a-write-pipeline-core-done.md) — Path A 主体: 8-step pipeline + 4-action conflict + bi-temporal correctness + AGE/Milvus 三方一致性
- [c5 Plan 2B cross-turn write pipeline ship](docs/claude-context/c5-plan2b-write-pipeline-cross-turn-done.md) — cross_turn_grouper + Path B Celery + failure_matrix
- [c5 Plan 3 read pipeline ship](docs/claude-context/c5-plan3-read-pipeline-done.md) — 3-way hybrid retrieval + RRF v2 时间感知 ranking + persona auto-injection + 长尾召回监控
- [c5 Plan 4 MCP tools ship](docs/claude-context/c5-plan4-mcp-tools-done.md) — 6 memory MCP tool + memory profile + evidence_quote 校验 (algorithm 深度补丁 #2) + Tier 3 recall + tool routing 监控周报 SQL
- [c5 Plan 5 cost optimization ship](docs/claude-context/c5-plan5-cost-optimization-done.md) — 5 项 ladder + injection classifier 规则层 (algorithm 深度补丁 #2) + posterior calibration weekly job (algorithm 深度补丁 #3) + chat_memory_calibration_runs audit / 单 session $0.025 → $0.005
- [c5 Plan 6 memory vs kb routing ship](docs/claude-context/c5-plan6-memory-kb-routing-done.md) — supervisor router 节点 + 触发词分类(memory 13 / kb 11 / both 6) + prompt 区隔 [用户上下文] / [市场知识] + LLMRouterFallback default memory + 8 seed case + accuracy hook(Plan 8 收 50 case)
- [c5 Plan 7A /memory UI shell ship](docs/claude-context/c5-plan7a-memory-ui-shell-done.md) — 5 REST endpoint + memoryApi client + /memory page shell
- [c5 Plan 7B memory visualizations + onboarding ship](docs/claude-context/c5-plan7b-visualizations-onboarding-done.md) — Cytoscape graph viz + timeline + audit + onboarding modal + chat anchor + monthly digest
- [c5 Plan 8 eval + tests + docs 收束 ship](docs/claude-context/c5-plan8-eval-tests-docs-done.md) — 50 golden + 4 metric + bi-temporal differential + chaos + 投毒 30 case + eval_runner CLI + 总卡
- [c5 S1 injection_classifier 死代码修复](docs/claude-context/c5-injection-classifier-wired.md) — Plan 5 自卡声称已接但实际 0 调用点; 4 写入入口接通 + L0/L1/L2 e2e 守护

### Harness Board Review Mode(2026-05-12 ship 完)
- [Harness Board Review Mode 总卡](docs/claude-context/harness-board-review-mode-done.md) — 复合型项目知识工具 底座 DeepCard + 5 视图 + 35 张 seed + Milvus + LLM L2 + 跨视图联动
- [Plan 1 底座 + V2 模块深读 ship](docs/claude-context/harness-board-review-plan1-done.md) — DeepCard schema + sqlite v2 + provenance fuzzy match + Milvus collection + V2 modal + AI 草拟按钮
- [Plan 2 V3 鸟瞰 + V4 故事 ship](docs/claude-context/harness-board-review-plan2-done.md) — cytoscape graph + commit-time 抽取 + 三段式 story + Milvus 真路径 wire + 跨视图联动
- [Plan 3 V5 闪卡 + 全量 prefill + 收尾 ship](docs/claude-context/harness-board-review-plan3-done.md) — SM-2 SRS + 3 模板派生 + DeepCard 编辑 hook + /flashcards/today + /stats + 35 张 hand-curated seed

### Harness Board V2 Polish(2026-05-14 ship 完)
- [V2 Polish 总卡](docs/claude-context/harness-board-v2-polish-done.md) — Quiet Workshop UI 全重写 + SSE 5-step refresh pipeline + seed 自动 ingest 修鸟瞰空 + 双强调 amber × teal + Newsreader/Source Han Serif/Manrope/Geist Mono / 42 task / 43 commit / pytest+mypy+ruff 全绿;mockup-v2.html 留作 design SoT

### Chat 记忆分层 Phase 1(2026-05-16 ship 完)
- [Phase 1 self-managed wire ship](docs/claude-context/chat-memory-phase1-self-managed-wire-done.md) — memory_tool_usage prompt 拼回 chat_planner / agent self-managed 三要素全接通 / 24+ 新测试 / 601 PASS scope-clean / Phase 2-4 留 hook 等 dogfood

### v1.x A5a 多模型估值 cross-check(2026-05-16 ship 完)
- [v1.x A5a 多模型估值 cross-check ship](docs/claude-context/v1.x-multi-valuation-cross-check-landed.md) — 4 model cross-check + IndustryModelRouter + DCF 3 scenarios + OutlierDiagnosisAgent + Critic 7 维 + Writer prompt + retry edge / ~1700 行 / cassette+input wire 留 follow-up

### v1.x A5b bull/bear multi-agent debate(2026-05-16 ship 完)
- [v1.x A5b bull/bear debate ship](docs/claude-context/v1.x-bull-bear-debate-landed.md) — 2-round adversarial debate + Critic 第 8 维 + retry edge / "双 hallucination 防御"完整闭环 / ~1100 行 / dashboard tab 留 follow-up

### Chat Session 持久化(2026-05-17 ship 完 — 三卷)
- [Chat Session 持久化总卡](docs/claude-context/chat-session-persistence-done.md) — Plan 1+2+3 累计 ship,Spec § 1.2 三根因 3/3 全覆盖;DB-as-truth + Agent/Transport 解耦(Celery 独立进程)+ Redis Pub/Sub cancel + LangGraph checkpoint resume 四要素;6 状态 task lifecycle + stale scanner 自愈 + 3 differential golden;Plan 2 dogfood 6 round systematic-debugging 教训沉淀 `feedback_n_round_fix_means_phase1_redo`

### Persona Editable UI(2026-05-17 ship 完)
- [persona editable UI ship](docs/claude-context/persona-editable-ui-done.md) — /memory 加画像 tab + 双轨语义 + atomic 操作 + 升级动画 / 21 task ship

## 设计稿与实施计划

`docs/superpowers/specs/` 和 `docs/superpowers/plans/` 是更详细的决策评估和任务拆分。本仓库的设计语言：spec 评决策、plan 推实施、claude-context 沉淀长期 working memory。

## 跨机 / 多机开发

这个文件 + `docs/claude-context/` 跟代码一起 git push，多机开发 `git pull` 即同步。**用户私人偏好**（不应进项目仓的内容）留在 `~/.claude/projects/<project>/memory/`，可单独私有 repo 同步。
