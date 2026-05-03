# v0.8.x 业务梳理 Spec — "投资 = 投资"统一架构 + 9 sub-version 演进路线 + 前端 clean-room 化

**作者**: Talantan1102
**起草**: 2026-05-03
**状态**: 业务定位 spec, 已对齐;**不进 writing-plans**(同 Spec A)
**类型**: 定位 spec(业务 + 数据 + 架构演进路径), 非 implementation spec
**Roadmap anchor**: 本 spec 是 Spec A `2026-05-03-product-positioning-v1-roadmap.md` 的"业务边界 + 数据策略 + 架构演进路径 + 前后端协同 + 项目个人化"补完
**先决条件**: v0.8.2 PR #11 已合(`8733c91`)

---

## § 0 元信息与范围

### 0.1 触发动机

v0.8.2 ship 后(2026-05-03), user 询问"项目当下基础搭建还差什么", 对话过程中识别出比 infra 选型更前置的 4 个问题:

1. **业务定义未具象化** — Spec A 列了 8 use case + 5 差异化, 但每个 use case 的产品形态(用户旅程 / 输入输出 / 交互节点)没沉淀
2. **数据来源未锁定** — Spec A § 6 列了数据策略, 但个人开发者的现实约束(哪些 API 能拿到 / 哪些拿不到 / 替代方案)未沉淀
3. **单机 → multi-tenant 演进路径未规划** — Spec A 没碰 scalability
4. **前端协同未规划** — 之前所有 spec 全 focus 后端, 前端只在"SSE 推送"层面顺带提到

加 user 在 brainstorming 末段提的 **项目个人化**(去掉 legacy 公司痕迹), 共 5 个补完点。

### 0.2 本 spec 的定位

**业务定位 spec, 不是 implementation spec**:
- 本 spec **不进 writing-plans**, 不拆 step-by-step task
- 本 spec 锁定"做什么 / 不做什么 / 数据从哪来 / 怎么演进 / 前端怎么协同 / 项目元信息怎么个人化"
- 之后 9 个 sub-version 各自的 implementation spec 单独承载具体实施细节
- 跟 Spec A 关系: **补完, 不替代** — Spec A 提供 v1.0 长期愿景骨架, 本 spec 锁业务边界 + 数据 + 架构演进 + 前后端协同 + 个人化

### 0.3 关键 memory 引用

- `user_portfolio_target` — 作品定位与作者期望(LLM 应用算法 + infra 求职)
- `project_dual_mode` — 研报 + 对话双模式共享底座(本 spec § 1 升级版)
- `project_tech_themes` — 技术亮点 A+D+E+F
- `feedback_no_portfolio_simplification` — 工业级落地评估口径
- `feedback_design_doc_format` — 设计文档"四件套"格式(每个非平凡决策必须含问题陈述 + alternatives + tradeoff + 量化评估)
- **(本 spec 新落 4 个 memory)**:
  - `feedback_plain_language_for_industry_terms` — 跟 user 沟通的语言规范
  - `feedback_estimate_in_claude_code_walltime` — Claude Code wall time 估算口径
  - `reference_data_sourcing_channels` — 数据采购渠道(tushare 高积分会员 + Bocha API 来源)
  - `project_personal_portfolio_no_company_reference` — 项目完全个人化, 去掉 legacy 公司痕迹

---

## § 1 核心立论 — "投资 = 投资"统一架构

### 1.1 立论

**银行放贷 = 债权投资, 个人买股票 = 股权投资, 二者本质都是投资行为。**

| 维度 | B 端(银行放贷) | C 端(个人买股票) |
|---|---|---|
| 投资形式 | debt investment(债权投资) | equity investment(股权投资) |
| 期望回报 | 本金 + 利息 | 股价上涨 + 分红 |
| 决策依据 | 偿债能力 / 风险评估 | 盈利能力 / 增长 / 风险 |
| 关注偏好 | 下行风险(放贷不能爆雷) | 上行 + 下行平衡(risk-adjusted return) |
| **共享分析维度** | **基本面 / 财务 / 行业 / 风险 — 完全相同** | (同) |

两端共享分析维度, 只是回报模型 + decision threshold 不同。

### 1.2 立论的产品架构含义

B 端 use case 和 C 端 use case **不是两套独立产品**, 而是**同一套底层 capability 在不同 deliverable schema + 入口 UI 上的分叉**。

具体: B-1 信贷调查报告(B 端)和 C-1 个股研究(C 端)共用 90%+ 的:

- 数据源(KB + tushare + Bocha)
- 分析能力(基本面 / 财务比率 / 行业分析 / 风险评估)
- 5-agent 编排框架
- 评测 / 可观测 / cost / memory 横切

只在以下 3 层分叉:

| 分叉点 | B 端 | C 端 |
|---|---|---|
| **Writer schema** | `CreditInvestigationReport`(6 sections, 长报告) | `IndividualStockResearch`(轻量 schema, 短回答 + 卡片) |
| **入口 UI** | 长报告页(报告 viewer + 章节锚 + 引用跳转) | ticker page + chat |
| **触发上下文** | 信贷场景(贷款金额 / 期限 / 用途)| 个股查询(股票代码 / 自选股) |

### 1.3 立论对叙事的影响

**老叙事**(Spec A § 4):
> "我做了一个有 B 端研报模式 + C 端对话模式的 AI 助手, 共用一套 agent 底座。"

**新叙事**(本 spec 沉淀):
> "我做了一个 **AI 投研 copilot**, 把'投资分析'抽象成 3 个生命周期阶段(投前评估 / 投后监控 / 标的发现); B 端给银行做信贷调查 + 持仓预警, C 端给个人投资者做个股研究 + 自选股监控 + NL 选股; **同一套底层 capability + 不同 deliverable schema 服务两类用户**。"

新叙事在面试讲产品架构时更有说服力: 不是"做了两个产品", 而是"抽象了一个领域 + 做了两种用户形态"。

### 1.4 立论的 alternatives + 取舍

| Alternative | 描述 | 取舍 | 量化评估 |
|---|---|---|---|
| 真做两套独立系统(B 端 + C 端各 fork) | 各自有 agent / writer / 工具,不共用 | ❌ | 工程量 ~翻倍, 且违背"共享底座"叙事 |
| 共用 agent 但各自数据源 | B 端用银行内部数据, C 端用公开数据 | ❌ | B 端拿不到银行真实数据(本 spec § 5.3) |
| **统一架构 + Writer schema 分叉**(本 spec 选) | 共用底座, 只在输出 schema + UI 分叉 | ✅ | 工程量最优 + 叙事最锐利, 跟 user 洞察一致 |

---

## § 2 用户画像 + 5 use case 矩阵

### 2.1 B 端用户画像(假想 banking persona)

(沿用 Spec A § 2.1, 不重复细节)

**B 端 use case 终态**:

| ID | Use case | 描述 | 状态 |
|---|---|---|---|
| **B-1** | 信贷调查报告 | 输入企业 + 信贷场景 → 出 `CreditInvestigationReport`(6 sections + evidence) | ✅ v0.8.2 ship |
| **B-3** | 持仓预警 | 已放贷客户持续监控, 财务恶化 / 负面新闻 / 行业风险信号自动报警 | 🆕 v0.8.3 |
| **B-7** | 审批人对报告追问 | 看完报告后追问("应收账款波动原因") | 🆕 v0.8.5(由 C 端通用对话承载) |

**显式砍掉**(out of scope, brainstorming 决议):
- **KYC 反洗钱客户尽调**(对应 Moody's Agentic Solutions 之一) — 跟"投资分析"主题脱钩, 本 spec 砍

### 2.2 C 端用户画像(作者本人 dogfood)

(沿用 Spec A § 2.2)

**C 端 use case 终态**:

| ID | Use case | 描述 | 状态 |
|---|---|---|---|
| **C-1** | 个股研究 | 输入股票代码 → 出 `IndividualStockResearch`(基本面 + 财务 + 行业 + 风险) | 🆕 v0.8.5 |
| **C-2** | 自选股监控 | 自选 watchlist 持续监控, 复用 B-3 监控引擎 | 🆕 v0.8.5 |
| **C-3** | NL 选股 | 自然语言 → tushare 全市场扫描("市盈率 < 10 的银行股") | 🆕 v0.8.5 |
| **通用对话** | 多轮追问 | 基于报告 / 个股上下文追问 | 🆕 v0.8.5(同时承载 B-7) |

### 2.3 投资生命周期 3 阶段交叉矩阵

按 § 1 立论, 5 use case 按"投资生命周期"3 阶段统一组织:

| 阶段 | B 端 | C 端 | 共用底层 capability |
|---|---|---|---|
| **投前评估** | B-1 信贷调查报告 ✅ | C-1 个股研究 🆕 | 基本面 + 财务比率 + 行业分析 + 风险评估 |
| **投后监控** | B-3 持仓预警 🆕 | C-2 自选股监控 🆕 | 持续扫描 + 信号检测 + alert 触发 |
| **标的发现** | (银行不需要,客户已定) | C-3 NL 选股 🆕 | screener + 多条件筛选 |
| **追问** | B-7 审批人追问 🆕 | C-端通用对话 🆕 | 多轮对话 + 引用回原文 |

---

## § 3 工业界 benchmark 总结

### 3.1 4 款 benchmark 产品 + 各自定位

| 产品 | 定位 | 核心特征 | 我们对照 |
|---|---|---|---|
| **Hebbia Matrix** | B 端 enterprise general research, ~$700M valuation, $15T AUM 客户 | 多文档并行 Q&A spreadsheet UI + chunk-level citation + Excel/PPT 自动生成 | **不学** — 我们走 Moody's 路线 |
| **Moody's CreditView + Agentic Solutions** | B 端 banking 信贷垂直 | workflow 内置(信贷调查 / 持仓预警 / KYC), 集成 Claude Desktop / MS 365 Copilot | **核心借鉴**(砍 KYC, 留信贷调查 + 持仓预警) |
| **Perplexity Finance** | C 端 international, 2025 上线 | ticker page Q&A + earnings AI 摘要 + multi-turn | C 端通用对话 + 个股研究借鉴 |
| **同花顺 i问财** | C 端国内 A 股, 2014 起 | NL 选股招牌 + AI 深度推理 + 基本面/技术面/资金面分析 | **C 端核心借鉴**(NL 选股 + 个股研究, 对齐 dogfood A 股) |

### 3.2 Comparison matrix(11 能力维度 × 4 产品 + 我们)

| 功能维度 | Hebbia | Moody's | Perplexity | 同花顺 | **我们 v0.8.2** |
|---|---|---|---|---|---|
| 多文档 NL Q&A | ✅ | ✅ | ✅ | ✅ | ✅ KB+13 PDF |
| 引用可追溯 | ✅ chunk 级 | 🟡 | ✅ inline | 🟡 | ✅ section 级 schema(UI 待 v0.8.6) |
| 结构化报告输出 | ✅ Excel/PPT/Word | ✅ credit memo | 🟡 文本 | 🟡 | ✅ B-1 信贷调查报告 |
| Excel / Office 集成 | ✅ 深度 | ✅ MS 365 Copilot | ❌ | ❌ | ❌(留 v1.x) |
| 实时行情数据 | 🟡 | ✅ | ✅ | ✅ | ❌ mock(v0.8.3 真接) |
| Earnings AI 摘要 | ✅ | ✅ | ✅ 15min refresh | ✅ | 🟡 KB 含财报但无 event 触发 |
| **持续监控 / 周期任务** | 🟡 | ✅ Early Warning | 🟡 alerts | 🟡 自选股 | ❌(v0.8.3 B-3 补) |
| 多 agent 编排 | ✅ N×M 并行 | ✅ Agentic | 🟡 | 🟡 | ✅ 5-agent + Critic Send |
| 信贷专业 workflow | 🟡 | ✅ memo + KYC | ❌ | ❌ | ✅ B-1 schema |
| NL 选股 / screener | 🟡 | 🟡 | 🟡 | ✅ 招牌 | ❌(v0.8.5 C-3 补) |
| Multi-tenant / scale | ✅ 1B pages | ✅ 全球 | ✅ consumer | ✅ 国内大流量 | ❌ 单进程(v1.1 补) |

### 3.3 5 个核心 insight

1. **B 端"工具派 vs workflow 派"分野**: Hebbia(generic 工具)vs Moody's(业务流程内置), **我们走 Moody's**(跟 v0.8.2 已 ship 的 B-1 一致)
2. **C 端"国际 vs 国内"分野**: Perplexity(国际 SEC filings)vs 同花顺(国内 A 股 NL 选股), **我们走同花顺**(对齐 dogfood A 股)
3. **基础能力 4 款都做**: 多文档 NL Q&A + 引用追溯 + 结构化报告 + 多 agent — 我们除"实时数据"全部已做(v0.8.3 补 tushare)
4. **真正差距 = 产品形态而非技术**: 4 款都有"持续监控"产品形态(Moody's Early Warning Signals / Perplexity earnings push / 同花顺自选股), 我们当前只能"问一次答一次", 无周期性 — 这是 v0.8.3 B-3 持仓预警要补的核心
5. **Multi-tenant / scale 是基础设施级能力**, 4 款都做; 不是差异化卖点而是"门票", 但要做(本 spec § 7 v1.1 全做)

---

## § 4 功能 inventory + 取舍

### 4.1 共用 capability 清单(B/C 100% 共享)

| Capability | 实现层 | 状态 |
|---|---|---|
| 5-agent 编排(planner / data_collector / analyst / critic / writer) | `app/agents/` `app/orchestration/` | ✅ v0.5 ship |
| KB 检索(Milvus + 13 PDF + 3 chunker 路由) | `app/services/kb_search_service.py` | ✅ v0.7 ship |
| 实时数据(tushare Pro) | `app/services/tushare_*` | 🆕 v0.8.3 真接(替换 mock) |
| Web 搜索(Bocha) | `app/services/bocha_*` | ✅ v0.6 ship |
| Memory 子系统(语义层 + 流程层) | `app/services/memory_*` | 🆕 v0.8.4 |
| 评测 / 可观测(Trace / EvalRunner / Judge) | `app/services/{trace,eval,judge}_*` | ✅ Plan C/D 部分 ship; 🆕 v0.8.6 升 agent-level |
| Cost budget + tier router | `app/services/{cost,tier}_*` | ✅ Plan D ship |
| **监控引擎**(后台周期任务 + 信号检测 + alert) | `app/services/monitoring_*` | 🆕 v0.8.3(B-3 + C-2 共用) |

### 4.2 B/C 分叉点(Writer schema + 入口 UI)

| Schema | use case | 实现 |
|---|---|---|
| `CreditInvestigationReport` | B-1 | ✅ v0.8.2 ship |
| `PortfolioWarningReport` | B-3 | 🆕 v0.8.3 |
| `IndividualStockResearch` | C-1 | 🆕 v0.8.5 |
| `WatchlistAlertReport` | C-2 | 🆕 v0.8.5(可能复用 PortfolioWarningReport) |
| `ScreenerResult` | C-3 | 🆕 v0.8.5 |
| `ChatResponse`(已有) | B-7 + C-端通用对话 | 🆕 v0.8.5 增强(加 reference link) |

### 4.3 显式砍 / 缩

| 项 | 决议 | 理由 |
|---|---|---|
| KYC 反洗钱客户尽调 | **砍** | 跟"投资分析"主题脱钩 |
| Hebbia Matrix UI(N×M spreadsheet)| **不做** | 我们走 Moody's 路线, scope 收得住 |
| Excel/PPT 自动生成 | v1.x future | 工程量大, 不是核心叙事 |
| Perplexity earnings 15min push | v1.x future | 需要实时财报推送 infra |
| 多公司对比 Matrix(B-5)| 砍 | YAGNI |
| 持仓 / 组合分析(C-4)| 砍 | 需要 portfolio 数据 |
| 盘中实时盯盘(C-6)| 砍 | 需要行情 stream |

---

## § 5 数据策略

### 5.1 Use case ⇄ 数据需求映射

| Use case | 需要的数据 | 数据来源 |
|---|---|---|
| B-1 信贷调查报告 | 公司基本面 / 财务 / 行业 / 政策 / 不良记录 | tushare(v0.8.3 真接)+ 已 ingest 13 PDF + Bocha web |
| B-3 持仓预警 | 客户财务持续更新 / 负面新闻 / 行业风险信号 | tushare(分钟 + 季度更新)+ Bocha 实时 + cron 触发 |
| C-1 个股研究 | A 股行情 + 财报 + 财务比率 | tushare(同 B-1) |
| C-2 自选股监控 | 同 B-3, 散户视角 | 复用 B-3 引擎 |
| C-3 NL 选股 | A 股全市场扫描(算 PE/ROE 等) | tushare daily_basic(全市场) |

### 5.2 数据来源 inventory + 个人开发者可行性

| 来源 | 给什么数据 | 个人能拿 | cost |
|---|---|---|---|
| tushare Pro 高积分会员 | A 股行情 / 财报 / 全市场扫描 / 高频 / 北向 / 龙虎榜 / 基金持仓 / 衍生品 | ✅ | 已采购 |
| Bocha 搜索 API | Web 实时新闻 / 公开信息 | ✅ | 已采购 |
| cninfo 巨潮资讯 | A 股公告 PDF | ✅ | 0(已 ingest 13 篇) |
| 政府公开网站 | 政策文件 PDF | ✅ | 0(部分已 ingest) |

(数据采购渠道不在本 spec 写, memory `reference_data_sourcing_channels` 已声明)

### 5.3 Out of reach(数据 gap)

| 来源 | 给什么 | 不可行原因 | 替代方案 |
|---|---|---|---|
| 天眼查 / 企查查 API | 未上市公司 / 股东穿透 / 司法 | 企业级 API, 个人买不到 | demo 公司选上市公司, dodge |
| 司法执行公开网 | 不良记录 | 不开放 API | Web search 间接 + 报告诚实声明 |
| Wind / 同花顺 iFinD | 全市场专业数据 | 机构级, ¥几万-几十万/年 | 用 tushare 替代 |

### 5.4 数据策略决议

**沿用 Spec A 隐式路线 + 显式声明 — 上市公司 demo + tushare + Bocha + 已 ingest KB**:

- **demo 公司全部上市**(茅台 / 宁德 / 比亚迪 / 招商银行 / 中芯国际)
- **未上市公司数据 gap 用 dodge**: 在 v0.8.2 已 ship 的 `CreditInvestigationReport` schema 增加(v0.8.3-pre 改) `data_sources: list[str]` + `data_limitations: list[str]` 字段, writer 自动声明
- **不良记录用 Web search 替代** + schema field 声明
- **C-3 NL 选股用 tushare daily_basic** 扫全市场

**显式声明** : 本项目数据来源 spec / public 文档 / 简历 / blog / GitHub repo 写 "tushare Pro(高积分会员)+ Bocha API + 已 ingest 公开 PDF",**不写采购渠道细节**。

### 5.5 Alternatives + 取舍

| Alternative | 描述 | 取舍 | 量化评估 |
|---|---|---|---|
| 接付费天眼查 / 企查查 API | 拓展未上市公司 demo | ❌ 路径不通 | 个人买不到企业级 API |
| 砍掉 banking 叙事 | 只演示上市公司, 弱化"信贷"叙事 | ❌ | 失去核心差异化 |
| **dodge + 诚实声明**(本 spec 选) | 用上市公司 demo + 报告写明 data limitation | ✅ | 唯一可行路径 + 诚实声明本身是叙事亮点 |

---

## § 6 技术架构 — 共用底座 + 分叉点

### 6.1 共用底座(单进程, v1.0 ship 形态)

```
┌─────────────────────────────────────────────────────────────┐
│                     共用底座(单进程)                       │
│                                                             │
│  ┌────────────────────┐       ┌──────────────────────┐      │
│  │  5-agent 编排       │ ←→   │  Writer schema 工厂   │      │
│  │  - planner         │       │  - credit_report      │      │
│  │  - data_collector  │       │  - portfolio_warning  │      │
│  │  - analyst         │       │  - stock_research     │      │
│  │  - critic          │       │  - watchlist_alert    │      │
│  │  - writer          │       │  - screener_result    │      │
│  │                    │       │  - chat_response      │      │
│  └────────────────────┘       └──────────────────────┘      │
│         ↓                                                   │
│  ┌────────────────────────────────────────────────────┐     │
│  │  Tools / Services 层                                │     │
│  │  - KB(Milvus 13 PDF) - tushare - Bocha           │     │
│  │  - Memory(语义+流程) - Monitoring engine         │     │
│  │  - Trace - Eval - Judge - Cost - Tier             │     │
│  └────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
                       ↑
        ┌──────────────┴──────────────┐
        │                             │
   ┌────┴─────┐                  ┌────┴─────┐
   │  B 端入口 │                  │  C 端入口 │
   │          │                  │          │
   │ 信贷报告页│                  │ ticker页 │
   │ 监控列表 │                  │ watchlist│
   │          │                  │ NL 选股  │
   │          │                  │ chat     │
   └──────────┘                  └──────────┘
```

### 6.2 单机 → multi-tenant 演进路径(v1.1 全做)

**Stage 0(v1.0 ship 形态)**: 单机 + sqlite + 单 Milvus collection + 单 process FastAPI

**Stage 1(v1.1.0)**: 进程模型 + 数据库迁移
- A1. 单 process → multi-process(uvicorn workers + Celery / arq 任务队列)
- A2. sqlite → Postgres + tenant_id 列 + 数据迁移脚本

**Stage 2(v1.1.1)**: 数据隔离 + 缓存 + 鉴权
- A3. Milvus 单 collection → per-tenant collection
- A4. Redis 缓存(LLM / KB 检索 / embedding 结果)
- A5. OAuth + tenant 注册 + 鉴权中间件(可用 Clerk / Auth0 SaaS 简化)

**Stage 3(v1.1.2 = v1.1 ship)**: 限流 + 验证 + 部署
- A6. per-tenant rate limit + cost_budget(扩已有 cost_budget)
- A7. Load test 跑 100/1000/10000 并发(locust / k6)
- A8. docker-compose multi-service / k8s manifest
- A9. architecture-evolution doc + 简历更新

### 6.3 Alternatives + 取舍

| Alternative | 描述 | 取舍 | 量化评估 |
|---|---|---|---|
| 不做 multi-tenant(只写 spec 提一下)| 0 工期 | ❌ | 跟 user "在技术上做优化"诉求矛盾 |
| 架构 ready + spike + 数据(只跑 baseline + 写 doc) | +2-3 天 wall time | ❌ | "纸面 architecture"叙事弱于真做 |
| **真做 multi-tenant + 高并发**(本 spec 选) | A 路线 9 模块完整 | ✅ | +4-6 周 wall time, 有真实代码 + load test 数据, 简历叙事最硬 |

(参见 brainstorming Q6 排期方案讨论, 选了"v1.0 业务先 ship 单机版 + v1.1 多租户升级"两段 ship)

---

## § 7 9 sub-version ship plan

### 7.1 v0.8.3-pre — 前端 audit + 清理 + 项目个人化(2.5-3.5 天)

按 memory `project_personal_portfolio_no_company_reference`, 执行 clean-room 化。

**子任务清单**:

1. **批量删 156 文件 legacy copyright header**(完整 string 见 memory `project_personal_portfolio_no_company_reference`):
   - 用 sed 脚本批量处理 + git diff verify
   - 范围: 前端几乎所有 .tsx/.ts(~95 文件)+ 后端 legacy 模块(`app/core/* / app/config/* / app/models/*` ~20 文件) + 其他(.html / .json ~40 文件)
2. **重写 frontend/README.md**: 当前是"行业信息助手"(legacy 项目名), 重写成"AI 投研 copilot(个人 portfolio)"
3. **改 VITE_TITLE env / index.html `%VITE_TITLE%`**: 改成产品名
4. **改 frontend/package.json name**: "gsk"(legacy 内部代号)→ "financial-research-frontend"
5. **砍 legacy 上一代 pages**(bidding 等), 评估其余 pages reuse 范围
6. **后端 legacy 模块评估**: `app/core/* / app/config/* / app/models/*` grep 看仍在用否, 不用就连模块一起删
7. **设计语言对齐**: 参考 Perplexity Finance / 同花顺 / Hebbia 选风格基调

**Out of scope**:
- 任何 legacy 公司痕迹必须**全部移除**(各 string 变体见 memory `project_personal_portfolio_no_company_reference`)
- spec / PR / 简历 / blog / GitHub repo 名 / project-story / favicon / page meta 都不能出现 legacy 公司名

### 7.2 v0.8.3 — tushare 真接入 + B-3 持仓预警(7-12 天)

**后端**:
- tushare 真接入(替换 mock skill, 见 `app/service/mock_tushare.py` legacy)
- 监控引擎(后台周期任务 + 信号检测 + alert schema)— B-3 + C-2 共用底层
- B-3 schema(`PortfolioWarningReport`)+ Writer 改造
- B-3 prompt 调优 + dogfood

**前端**:
- 监控列表页(Antd Table + 状态 / 等级 / trigger time)
- alert 详情页(复用 markdown + reference)
- 触发器配置页(简化版: 客户列表 + 监控频率 + 信号阈值)

### 7.3 v0.8.4 — Memory 子系统 v1(4-6 天)

**后端**:
- 语义层(用户研究历史 embedding + 摘要)
- 流程层(workflow snapshot)
- 集成进 agent(B-3 触发时召回相关历史; C-1 / C-2 同样)

**前端**:
- memory 页(已有, 适配新 API)+ 历史研究列表 + 摘要展示

### 7.4 v0.8.5 — C 端 4 件套(7-10 天)

**后端**:
- C-1 个股研究: schema(`IndividualStockResearch`)+ Writer 复用 B-1 分析能力
- C-2 自选股监控: 复用 B-3 监控引擎, 改 trigger 源 + schema
- C-3 NL 选股: NL → 筛选条件 → tushare query 工具 + Writer
- 通用对话入口(B-7 + C 端追问共用): 复用现有 chat agent + 加 reference link 增强

**前端**:
- ticker page(类 Perplexity Finance, 复用 stock-card + chart + chat sender)
- watchlist 页(复用 Antd Table + notification)
- screener 页(NL 输入 + 结果列表 + 排序筛选 + 加自选)
- chat 页增强(reference hover/jump)

### 7.5 v0.8.6 — D1 引用 UI + D6 eval 升级(7-9 天)

**后端**:
- D1: chunk_id → PDF page+bbox 映射(扩 KB ingest 时记录 bbox)
- D6: golden set 40 case + LLM-as-judge rubric + dashboard backend API + PR regression gate(CI 集成)

**前端**:
- 报告 reference link 跳转(集成 react-pdf 或类似)
- dashboard 页(trace tree + cost / latency / score 可视化, 复用 ECharts)

### 7.6 v0.8.7 = v1.0 ship — D2 本地化 spike + dogfood + 简历(5-8 天)

**后端**:
- D2: BGE-M3 本地 embed spike + benchmark(retrieval recall@5 BGE vs 云端 Qwen embed, 50 query 数据)
- D2: 1 个本地 LLM(DeepSeek 或 Qwen-7B)spike + benchmark(B-1 task 5 case 跑分对比)
- env switch 加 option(云端默认 + 本地可选)

**端到端**:
- dogfood 5 case(B-1 / B-3 / C-1 / C-2 / C-3)
- project-story 更新 + 简历更新

### 7.7 v1.1.0 — 进程模型 + 数据库迁移(8-11 天)

**后端**:
- A1: multi-process + 任务队列(Celery / arq, worker 进程异步执行长任务)
- A2: sqlite → Postgres + tenant_id 列 + 数据迁移脚本

**前端**: minor adjustments(API 鉴权 header 预留)

### 7.8 v1.1.1 — 数据隔离 + 缓存 + 鉴权(10-14 天)

**后端**:
- A3: Milvus per-tenant collection(改 KbSearchService Protocol)
- A4: Redis 缓存(LLM 调用 / KB 检索 / embedding 结果, TTL + invalidation 策略)
- A5: OAuth + tenant 注册 + 鉴权中间件(用 Clerk / Auth0 SaaS 简化, 或自建 JWT)

**前端**:
- 用户中心 + 租户切换 + API key 管理(复用 auth + Antd Form)
- OAuth 登录页扩 / 适配

### 7.9 v1.1.2 = v1.1 ship — 限流 + 验证 + 部署(7-11 天)

**后端**:
- A6: per-tenant rate limit + cost_budget(扩已有 cost_budget 加 tenant 维度)
- A7: Load test(locust/k6 跑 100/1000/10000 并发, 收集 latency p50/p99 + throughput + error rate + cost-per-tenant)
- A8: docker-compose multi-service(Postgres / Redis / Milvus / backend / worker / scheduler) + 可选 k8s manifest

**端到端**:
- A9: architecture-evolution doc + load test report + 简历更新

---

## § 8 工期估算(Claude Code wall time)

按 memory `feedback_estimate_in_claude_code_walltime` 口径, 假设每天 4-6 小时投入。

| 阶段 | sub-version | wall time |
|---|---|---|
| v0.8.3-pre 清理 + 个人化 | 1 | 2.5-3.5 天 |
| v0.8.3 tushare + B-3 | 1 | 7-12 天 |
| v0.8.4 Memory v1 | 1 | 4-6 天 |
| v0.8.5 C 端 4 件套 | 1 | 7-10 天 |
| v0.8.6 D1 + D6 | 1 | 7-9 天 |
| v0.8.7 = v1.0 ship | 1 | 5-8 天 |
| **v1.0 累计** | **6** | **32-48 天 = 7-10 周** |
| v1.1.0 进程 + DB | 1 | 8-11 天 |
| v1.1.1 隔离 + 缓存 + 鉴权 | 1 | 10-14 天 |
| v1.1.2 = v1.1 ship | 1 | 7-11 天 |
| **v1.1 累计** | **3** | **25-36 天 = 5-8 周** |
| **总累计** | **9** | **57-84 天 = 12-17 周(~3-4 个月 wall time)** |

### 8.1 估算口径区分

- **Claude Code 加速段**(写代码 / boilerplate / refactor / 测试代码生成): wall time 约纯人工的 1/2 ~ 1/3
- **人-bound 段**(spec brainstorming / spec review / dogfood 评判 / prompt 调优 / 调试 production-only bug / 等 cassette / 等 Milvus 启动 / 等 pip install): 不打折

### 8.2 节奏对照

| 阶段 | wall time | 项目历史对照 |
|---|---|---|
| v1.0 6 个 sub-version | 7-10 周 | 跟 v0.5/v0.6/v0.7/v0.8.1/v0.8.2 节奏一致(每个 1-7 天) |
| v1.1 3 个 sub-version | 5-8 周 | 单段稍长但分了 3 段, 平均 ~1.5-2.5 周 |
| 平均每 sub-version | ~1-1.5 周 | 跟项目节奏匹配 |

### 8.3 排期 Alternatives + 取舍

(参见 brainstorming Q6.1 详细讨论, 选定"v1.0 单机 ship → v1.1 multi-tenant 升级"两段 ship 路线)

---

## § 9 量化质量标准

(基本沿用 Spec A § 8, v1.1 加新行)

| 维度 | 指标 | 数据集 | 阈值 |
|---|---|---|---|
| D1 强引用 | citation precision | 10 case spot check | ≥ 0.85 |
| D1 强引用 | citation recall | 同上 | ≥ 0.95 |
| D2 本地 embed | retrieval recall@5 (BGE vs Qwen) | 50 query golden set | gap < 5% |
| D2 本地 LLM | task quality(本地 vs 云端 B-1) | 5 case judge | gap < 10% |
| D3 中文金融术语 | retrieval 命中率 | 20 术语 query × top-5 | ≥ 90% recall |
| D4 结构化输出 | schema validation pass rate | writer 全部输出 | 100% |
| D4 结构化输出 | 必填字段完整率 | sections 必填 | ≥ 95% |
| D6 agent eval | golden set 规模 | — | B-1 ≥ 10 / B-3 ≥ 10 / C 端 ≥ 20 |
| D6 agent eval | judge rubric 维度 | — | 完整性 / 准确性 / 引用 / 风险 / 相关性 |
| D6 agent eval | PR regression gate | golden set | 不让 score 下降 > 5% |
| 系统 latency p50 | 实测 | dogfood | B-1 ≤ 5min / B-3 ≤ 2min / C ≤ 30s |
| 系统 cost / case | 实测 | dogfood | B-1 ≤ ¥0.50 / B-3 ≤ ¥0.10 / C ≤ ¥0.05 |
| 系统 cost daily | 已 set | (Plan D 已落) | ¥20 / day |
| **(v1.1 新)multi-tenant load test** | latency p50/p99 + throughput + cost-per-tenant | locust/k6 @ 100/1000/10000 并发 | 出 baseline 数据即可 |

---

## § 10 Out of scope

### 10.1 Use case
- B-2 行业准入研究 / B-4 政策快速研判(独立) / B-5 同业对标 / B-6 专题研究
- **B-? KYC 反洗钱客户尽调**(本 spec 显式砍, 跟"投资分析"主题脱钩)
- C-4 持仓 / 组合分析 / C-6 盘中实时盯盘

### 10.2 数据
- 天眼查 / 企查查 / Wind / 同花顺 iFinD 付费数据
- 自建公告 / 新闻爬虫
- 雪球 / 股吧社交数据
- 扩 KB corpus(13 PDF 已够 dogfood)
- **数据采购渠道细节** — spec / public 文档 / 简历都不写(memory `reference_data_sourcing_channels` 已声明)

### 10.3 技术
- Memory 跨用户缓存层 / 评测层(只做语义 + 流程两层)
- BGE / 本地 LLM 全切(只 spike + option)
- Fine-tune 任何模型
- Multi-tenant 真灰度 / A/B 测试基础设施
- 真生产部署到云(只做 docker-compose / k8s manifest 可演示)
- Hebbia Matrix 风 N×M spreadsheet UI / Excel & PPT 自动生成 / Earnings 实时 push

### 10.4 项目元信息
- **公司 / 学院 / legacy 来源信息**(本 spec § 7.1 v0.8.3-pre 清理 + memory `project_personal_portfolio_no_company_reference`)
- 多 tenant 真客户接入 / SLA 承诺
- 任何商业化 / 收费 / 用户运营

### 10.5 流程
- 本 spec 不进 writing-plans(同 Spec A)
- 9 个 sub-version 各自的 implementation spec 由对应日期单独写

---

## § 11 Memory cross-references

### 已有 memory
- `user_portfolio_target` — 作品定位(LLM 应用算法 + infra)
- `project_dual_mode` — 双模式共享底座(本 spec § 1 升级版)
- `project_tech_themes` — 技术亮点 A+D+E+F
- `project_eval_pipeline_contract` — 评测 pipeline(D6 基础)
- `project_v0.5_architecture_landed` — 5-agent + Critic Send(共用底座基础)
- `project_v0.6_architecture_landed` — Bocha web search
- `project_v0.7_architecture_landed` — KB + Milvus + 13 PDF
- `feedback_no_portfolio_simplification` — 工业级落地评估口径
- `feedback_design_doc_format` — 设计文档"四件套"格式
- `feedback_chinese_chunk_size_calibration` — 中文 chunking(已落)

### 本 spec 新落 memory(brainstorming 沉淀)
- `feedback_plain_language_for_industry_terms` — 跟 user 沟通的语言规范
- `feedback_estimate_in_claude_code_walltime` — Claude Code wall time 估算口径(本 spec § 8)
- `reference_data_sourcing_channels` — 数据采购渠道(本 spec § 5.4)
- `project_personal_portfolio_no_company_reference` — 项目完全个人化(本 spec § 7.1)

### 跨 spec 关系
- Spec A `2026-05-03-product-positioning-v1-roadmap.md` — 本 spec 是其"业务边界 + 数据 + 架构演进 + 前后端协同 + 个人化"补完

---

## § 12 Self-review

| 检查 | 结果 |
|---|---|
| Placeholder scan | 无 TBD / TODO; 9 个 sub-version 各自细节留 implementation spec 承载, 本 spec 显式标注 |
| 内部一致性 | § 1 立论 / § 2 use case / § 6 架构 / § 7 排期 / § 8 工期 互引正确;术语一致;Writer schema 命名 § 1.2 / § 4.2 / § 7 三处 align |
| Scope check | 本 spec 是定位 spec, 不进 plan, scope 合理;9 个 sub-version 各自 implementation spec 单独承载 |
| Ambiguity check | "持续监控产品形态"(B-3/C-2)的具体触发频率 / alert 渠道留 v0.8.3 implementation spec 决定, 本 spec 显式声明留白 |
| 跟 Spec A 一致 | 本 spec 沉淀 brainstorming 共识, **修订 Spec A 关于 KYC / 数据策略 / 架构演进路径 / 工期口径的部分**(KYC 砍, 数据策略写明 dodge + 诚实声明, 架构演进路径明确为 v1.1 单独 ship, 工期口径用 Claude Code wall time, 排期细分 9 个 sub-version) |
| 公司痕迹清理 | 本 spec 全文不出现 legacy 公司名(具体 string 见 memory); v0.8.3-pre 排期专门做清理(§ 7.1) |
| 数据采购渠道 | 本 spec 不出现采购渠道细节; § 5.4 + § 10.2 显式声明 spec/public 文档不写, 渠道详情见 memory |
| 四件套格式(memory `feedback_design_doc_format`) | § 1.4 立论 / § 5.5 数据 / § 6.3 multi-tenant 演进 三处含 alternatives + tradeoff;§ 9 量化质量标准全表 |

---

## § 13 Handoff

- **本 spec(定位 spec)**:不进 writing-plans, 作为 v0.8.3-pre / v0.8.3 ~ v1.1.2 共 9 个 sub-version 的业务依据
- **9 个 sub-version 的 implementation spec**: 各自由对应日期单独 brainstorming + 写 spec, 引用本 spec § 4 / § 5 / § 6
- **每个 sub-version implementation spec 写完后**: 走 `superpowers:writing-plans` skill 拆 step-by-step plan, 然后 `superpowers:subagent-driven-development` 或顺序实施
- **简历更新节奏**: v0.8.5 ship 后简历可以更新一次(C 端 4 件套都跑通), v1.0 ship(v0.8.7)再更新, v1.1 ship(v1.1.2)再更新
