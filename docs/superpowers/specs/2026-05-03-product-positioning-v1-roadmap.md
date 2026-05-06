# Product Positioning v1.0 Roadmap — Agent 投研助手

**作者**:Talantan1102
**起草**:2026-05-03
**状态**:Spec 已对齐,作为 v1.0 长期愿景沉淀;不绑定具体 release
**类型**:产品定位 spec(非 implementation spec)

---

## § 0 元信息与范围

本文档是一次产品定位 brainstorming 的产物,沉淀**项目长期形态的判断**:目标用户是谁、解决什么问题、凭什么用我的、做到什么程度算 v1.0、怎么知道做到了。

**不是 implementation spec** —— 不进 writing-plans。具体每个 release 的 implementation spec 由 Spec B / C / D / ... 单独承载,引用本文档 § 9 路线图作为 anchor。

**触发动机**:v0.8.1 ship 后(2026-05-03),用户问"v0.8.2 做什么",对话过程中识别出**业务定义未沉淀**才是更根本问题,先于任何 infra 选型。本 spec 解决这个根本问题。

**关键 memory 引用**:
- `user_portfolio_target` — 作品定位与作者期望(LLM 应用算法 + infra 求职敲门砖)
- `project_dual_mode` — 研报模式 + 对话模式共享底座
- `project_scope_decisions` — 重构功能边界决议
- `project_tech_themes` — 技术亮点 A+D+E+F
- `project_memory_layer` — Memory 子系统四层定义
- `feedback_no_portfolio_simplification` — 每个非平凡决策必须按"工业级落地 + 业界 alternatives + 我们取舍"评估

---

## § 1 项目定位:投资研究 agent 平台 + 2 persona + 共享底座

**核心叙事**:"投资研究 agent 平台,服务两类用户 — 银行私行客户经理(假想 banking persona)做投资标的尽调 + 客户持仓监控 + 客户追问;散户投资者(作者本人)dogfood 短对话 + 个人持仓监控。两类用户共享同一套 agent 底座,只是 use case 频次和 surface 不同。"

| 层 | 内容 |
|---|---|
| **平台层(主角 — 共享底座)** | 投资研究 agent 平台:planner / agent 池 / tool registry / memory / context / observability / eval |
| **Persona 1 — 银行私行客户经理(假想)** | 主用:B-1 重仓股尽调 / B-3 客户预警 / B-7 追问报告;次用:C 端 chat 协助写客户简报 |
| **Persona 2 — 散户投资者(作者本人 dogfood)** | 主用:C-1~C-7 短对话 / C-4 持仓分析;次用:B-1 重仓股深调 / B-3 持仓预警(个人组合视角) |
| **共享相通** | 两个 persona 都需要:尽调 / 监控 / 短对话 三件事;共享 agent 底座是业务事实,不是工程巧合 |

**对比之前 v 单一 persona unify 方案**:reframe 不假装散户作者就是私行经理,承认两个真实 persona,但保留共享底座叙事。诚实性更高,简历讲故事时面试官不容易戳穿。

**绝不假装是真银行项目**。诚实声明个人 portfolio + 假想 persona,既保护甲方信息也体现工业级设计能力。

详见 § 4 模式映射图(完整 ASCII 视图)。

---

## § 2 用户画像

### 2.1 Persona 1 — 银行私行客户经理(假想 persona)

**画像**:
- 主流私行(招商私行 / 平安私行 / 中行私行 / 工行私行 等)中级客户经理
- 客户结构:600W ~ 3000W 可投资资产 HNW(高净值)客户;客户:经理比 50:1 ~ 100:1
- 日常工作流:KYC(了解客户) / 资产配置(大类比例) / 标的尽调(进个股 / 基金前) / 持仓监控(季度 review + 异动跟踪) / 客户沟通(每月简报 + 追问应答) / 风险预警(回撤超阈值 / 黑天鹅 / 政策变化)
- 工作产出:**客户层面的投资建议 + 标的尽调报告 + 持仓跟踪简报 + 风险预警通知**
- 决策影响:客户百万级以上账户的资产配置决策

**对工具的硬约束**:
- **数据合规**:严禁调通用云 LLM API on 客户数据;**必须本地部署 + 可审计**(监管要求,留 v1.x roadmap)
- **强引用 + 可追溯**:每条结论可追到原文(决策依据要能查);hallucination 是 PR 灾难
- **强结构化输出**:输出符合内部模板,可直接进现有 workflow(客户简报模板 / 投资建议表)
- **多角色协作**:客户经理起草 → 投顾 review → 合规盖章 → 客户呈递
- **模型偏好**:可控的小模型 / 私有化部署(Qwen 本地、ChatGLM、DeepSeek 本地);避免黑盒 API

### 2.2 Persona 2 — 散户投资者(作者本人 dogfood)

**画像**:
- 关心 A 股市场,有自己的重仓标的(3-5 个核心持仓)+ 长尾观察池(20-50 个 watch list)+ 行业兴趣(科技 / 消费 / 医药 等)
- 日常需求:**短对话**(个股研究、行业判断、事件追踪、财报快速解读、概念学习)+ **个人持仓监控**(回撤跟踪 / 仓位预警)+ 偶尔重仓股**深度调研**(进新仓前 / 卖出决策前)
- 决策影响:个人持仓的买卖判断
- 不是专业研究员,需要**口语化交互 + 短回答 + 简单图表 + 不放弃引用**

**对工具的需求**:
- **快速响应**:几秒到几十秒
- **多轮追问**:对话式,不是一次性长报告
- **引用回原文**:可追溯但不强制(质量加分项)
- **数据多样**:KB + 实时行情 + Web 新闻

**作者双角色 dogfood**:作者 dogfood 时既扮演"模拟客户经理"(用 B-1 / B-3 / B-7 走私行 workflow,验证 banking persona 端体验),也扮演"模拟 HNW 客户"(用 C 端 chat 验证散户体验);两个角色共用一套 agent 底座 + 数据源,只是入口和报告形态不同。

### 2.3 共享底座的合理性

两个 persona 在 surface 上完全不同(B 端长报告 + 客户视角 / C 端短对话 + 个人视角),但都需要**尽调 + 监控 + 短对话 三件事**(只是频次和入口不同):

- 私行客户经理:**主用尽调**(为客户决策)+ 主用监控(客户预警)+ 次用短对话(协助写客户简报)
- 散户投资者:主用短对话(快速答疑) + **主用监控**(个人持仓)+ 次用尽调(重仓股深调研)

共享 agent / planner / tool registry / context / memory / cost / observability 是**业务事实**,不是工程巧合。技术上落到同一套 LangGraph 编排 + tool 池 + sqlite memory + LLMService:

- planner / agent 池(retrieval / writer / critic / data_collector)
- 工具栈(KB 检索 / Web 搜索 / 行情 API)
- context 管理 + cost budget + observability + memory

只是**不同入口编排策略不同**:
- B-1 / B-3 / B-7 走研报 / 监控 / 追问编排(长流程 + Critic + Writer)
- C-1 ~ C-7 走对话编排(短流程 + 流式 + 自主调度工具)

---

## § 3 Use case(9 个 — 2 persona 合并表)

| ID | Use case | 输入 / 输出 | Persona 1<br/>私行经理 | Persona 2<br/>散户作者 | 模式 |
|---|---|---|---|---|---|
| **B-1** | **重仓股深度尽调**(InvestmentDueDiligenceReport) | 企业名 + 投资目标 / 时长 / 风险偏好 → 长报告:标的概况 / 法务资质 / 财务 / 行业 / 风险 / 投资建议 | ✓ 客户重仓股尽调 | △ 我的重仓股深度调研 | 研报 |
| **B-3** | **持仓预警跟踪**(ClientTrackingBrief) | 持仓 snapshot → 简报:新增信号 + 风险评级变化 + 跟进动作 | ✓ 客户持仓预警 | △ 个人组合预警 | 研报 + memory |
| **B-7** | **报告追问** | 自然语言问句 + report context → 流式回答 + 引用回原章节 | ✓ 客户对报告追问 | △ 散户偶尔追问 | 对话(接 report context) |
| **C-1** | 个股 / 标的研究 | "茅台最近怎么样" / "比亚迪 vs 宁德对比" → 几条要点 + 引用 + 图表 | △ 客户对话辅助 | ✓ | 对话 |
| **C-2** | 行业 / 主题判断 | "半导体下半年看法" → 几条要点 + 关键标的 | △ | ✓ | 对话 |
| **C-3** | 事件追踪 | "美联储议息后市场反应" / 新政影响 → 时间线 + 受影响标的 | △ | ✓ | 对话 |
| **C-4** | 持仓 / 组合分析(2026-05-04 拉回 v1.0) | 持仓 snapshot → 短对话 + 简表:仓位归因 + 风险分布 | △ | ✓ 个人组合归因 | 对话 + 简表 |
| **C-5** | 财报快速解读 | "茅台 Q3 亮点和雷点" → 财务要点 + 增长 / 风险 | △ | ✓ | 对话 |
| **C-7** | 概念 / 术语解释 | "什么是久期管理" → 定义 + 应用场景 + 例子 | △ 客户教育 | ✓ | 对话 |

✓ = 主用(高频 + 深度);△ = 次用(共享底座顺带)

### 3.3 显式不做(YAGNI)

- B-2 行业准入研究(B-1 包含)、B-4 政策快速研判(ad-hoc 强不好做 demo)、B-5 同业对标(B-1 多 instance 扩展)、B-6 专题研究(太广)
- C-6 盘中实时盯盘(需行情 stream)
- 留 v0.9+ 或永远不做

> **2026-05-04 update**:**C-4 持仓 / 组合分析从 YAGNI 拉回 v1.0 范围**。reframe 后,C-4 的数据模型(持仓 snapshot + 异动检测)可 reuse B-3 monitoring 引擎,边际成本低 + 散户 dogfood 主用,留在 v1.0 散户 batch deep 阶段一并交付(详见 § 9 v0.8.6)。

---

## § 4 模式映射:平台 + 2 persona + 共享底座

```
                ┌─────────────────────────────────────────────┐
                │   投资研究 agent 平台(共享底座 — 主角)    │
                │   planner / agent 池 / tool registry /      │
                │   memory / context / observability / eval   │
                └─────────────────────────────────────────────┘
                           ↑                       ↑
                共享相通                   共享相通
                           │                       │
              ┌────────────┴───────┐  ┌────────────┴───────┐
              │ Persona 1:        │  │ Persona 2:         │
              │ 银行私行客户经理 │  │ 散户投资者         │
              │ (假想 banking)    │  │ (作者本人 dogfood) │
              ├────────────────────┤  ├────────────────────┤
              │ 主用:             │  │ 主用:             │
              │  ・B-1 重仓股尽调 │  │  ・C-1~C-7 短对话  │
              │  ・B-3 客户预警  │  │  ・C-4 持仓分析    │
              │  ・B-7 追问报告  │  │ 次用:             │
              │ 次用:             │  │  ・B-1 重仓股深调 │
              │  ・C 端 chat 协助│  │  ・B-3 持仓预警   │
              │   写客户简报      │  │   (个人组合视角)  │
              └────────────────────┘  └────────────────────┘
```

**讲故事时**:"我做了一个投资研究 agent 平台,服务两类用户 — 银行私行客户经理(假想 banking persona)+ 散户投资者(作者本人 dogfood)。两类用户共享同一套 agent 底座(planner / agent 池 / tool registry / memory / context / observability / eval),只是 use case 频次和 surface 不同:私行经理主用 B-1 重仓股尽调 / B-3 客户预警 / B-7 追问报告;散户主用 C-1~C-7 短对话 / C-4 持仓分析。共享底座是业务事实,因为两个 persona 都需要尽调 + 监控 + 短对话三件事。"

---

## § 5 差异化 / 价值主张

按 memory `feedback_no_portfolio_simplification` 要求,每个差异化必须有**问题陈述 / 业界 alternatives / 我们的取舍 / 量化评估方案**四件套。

### 5.1 D1 — 强引用 + 可追溯

**问题陈述**:LLM 输出 hallucination 是金融决策灾难。需要每条结论都能追到原文,审批人能 click 回去 verify。

**业界 alternatives**:
- ChatGPT / Claude / Gemini:无引用或引用质量不稳(Web search 引用经常牛头不对马嘴)
- Perplexity:有 inline citation 但精度仍有问题,不深度追溯到 chunk 级
- Bloomberg Terminal:有数据源标注但没 LLM 推理链可追
- 企业 RAG 通用做法:retrieve top-K → 全 K 个 chunk 拼 context → LLM 回答 → 标 source URL,但**chunk-to-claim** 的精确映射没做

**我们取舍**:
- 不做 inline citation in markdown(Perplexity 风格,UI 复杂)
- 做 **structured output with explicit citation field**:每个 claim 是 JSON 对象,带 `evidence: [chunk_id, ...]`
- UI 上 click 结论 → 跳转到原 PDF 段落(chunk_id → PDF page+bbox)

**量化评估**:
- citation precision:LLM-as-judge 评判"引用的 chunk 是否真支持结论",10 case spot check,目标 ≥ 0.85
- citation recall:actionable claim 中带引用的比例,目标 ≥ 0.95

### 5.2 D2 — 本地部署 / 私有化能力

> **Status(2026-05-04 update)**:**v1.0 不交付,v1.x roadmap**。理由:作者本地硬件性能受限,跑 BGE-M3 + 本地 7B LLM benchmark 不现实。架构上 LLMService 已通过 ChatClient Protocol 抽象,retrieval 层同样 protocol 化,**切本地实现不动调用方;口子留好不做实施**。简历仍保银行 persona,面试被追问时坦诚回答:"硬件限制,v1.0 只做云端 demo + 架构留口;v1.x roadmap"。

**问题陈述**:银行场景严禁数据出域。必须能跑本地 embedding + 本地 LLM。即使个人 dogfood 不需要,**作为差异化叙事**必须演示得了。

**业界 alternatives**:
- 全云方案(GPT/Claude/Qwen API):合规死路
- 全本地方案(Llama / Qwen-7B 本地):quality gap 较大
- 混合(本地 embed + 云 LLM):embed 数据量大也敏感,不行
- Private deployment of frontier model(GPT-4 Azure private / Claude AWS private):贵且复杂

**我们取舍(原计划 — v1.0 不执行,留 v1.x)**:
- ~~Embedding 做 BGE-M3 本地 spike~~ → 留 v1.x
- ~~LLM 做 DeepSeek / Qwen-7B-Chat 本地 spike~~ → 留 v1.x
- **架构留口子**(v1.0 已具备):LLMService 通过 ChatClient Protocol 注入;Retrieval 层同样 protocol 化;切本地实现不需动 caller

**量化评估**:留 v1.x 再补

### 5.3 D3 — 中文金融特化

**问题陈述**:通用 LLM / RAG 系统在中文金融场景有多个短板:中文 chunking 边界乱(中英文 token 比例不同)、财务术语命中弱(中文专业词)、监管文件 schema 特殊(条款编号)、中国会计准则跟 US GAAP 不同。

**业界 alternatives**:
- 通用 RAG(LangChain / LlamaIndex 默认配置):chunk_size 按英文调,中文场景 token 数翻 1.33 倍
- 通用 LLM(GPT-4 / Claude):英文金融语料丰富,中文 A 股 / 监管 / 会计准则场景偏弱
- 中文金融 LLM(朝阳永续 / i 问财):闭源不知道做了什么

**我们取舍**:
- **中文 chunking 已校准**(memory `feedback_chinese_chunk_size_calibration`,chunk_size=600 chars)
- **3 种 chunker 类型路由**(memory `project_v0.7_architecture_landed`):研报 SemanticChunker / 财报 SectionChunker / 政策 ClauseChunker
- **写 spec / 报告 prompt 时显式中文金融语境锚点**(资产负债表科目 / 国资委监管要求 / 央行政策口径)
- **不做 fine-tune**(数据量不够,YAGNI)

**量化评估**:
- 难定量。**主要靠 dogfood + spot check report**(写 markdown 文档化 5-10 个 corner case)
- 能定量的:中文财务术语 retrieval 命中率(20 个术语 query × top-5),目标 ≥ 90% recall

### 5.4 D4 — 结构化输出

**问题陈述**:B-1 / B-3 输出必须符合**银行内部业务模板**(投资标的尽调报告 / 客户跟踪简报),自由文本输出无法直接进 workflow。

**业界 alternatives**:
- 自由文本 + 模板 prompt("请按以下格式..."):LLM 不稳定,字段缺失常见
- JSON mode(OpenAI / DeepSeek):格式对了,语义不稳定
- Pydantic schema + structured output(Anthropic tool use / OpenAI structured output):格式 + 类型双保证,**业界 best practice**
- DSPy / 复杂框架:overkill

**我们取舍**:
- 用 **Pydantic schema + LLM structured output**(项目已有 LLMResponse + tier_router,扩 schema 即可)
- 定 2 种业务模板:`InvestmentDueDiligenceReport`(B-1)、`ClientTrackingBrief`(B-3)
- 每种模板有 5-10 个 sections,每个 section 有必填字段 + 可选字段
- writer agent 按 schema 输出,fail 时重试 + critic 检查

**量化评估**:
- schema validation pass rate:writer 输出 100% 符合 JSON schema(pydantic 强制)
- 必填字段完整率:报告 sections 必填字段非空率 ≥ 95%

### 5.5 D6 — 评测可观测

**问题陈述**:agent quality 是黑盒,改一个 prompt 不知道整体变好还是变差。需要 systematic eval 才能"知道我做的改进真的是改进"。

**业界 alternatives**:
- 无 eval(直接信感觉):反面教材
- LangSmith / Langfuse:SaaS,数据出域(银行不能用)
- 自建 trace + eval(Plan C/D 已部分落):memory `project_eval_pipeline_contract`
- LLM-as-judge:业界标配,有 limitation 需要校准

**我们取舍**:
- **已有基础**(memory `project_eval_pipeline_contract`):TraceService + EvalRecorder + EvalRunner + Judge + GoldenCase + cost budget + nightly CI
- **v0.8.x 升级到 agent-level**:从 LLMService SUT 升到整 ResearchAgent SUT
- **Golden set ≥ 10 B-1 + 10 B-3 + 20 C 端**:覆盖典型查询
- **Judge rubric 多维度**:完整性 / 准确性 / 引用质量 / 风险识别(B-1/B-3) / 相关性(C 端)
- **Dashboard 可视化**:trace tree / cost / latency / score 可看
- **PR regression gate**:不让 golden score 下降 > 5%

**量化评估**:见上(自评)

### 5.6 显式 not-differentiator(隐含/副产品)

- **共享底座**:是 organizing principle 不是 feature,讲架构时讲,不单独做事
- **Multi-agent**:已经做了(v0.5 5-agent),不是新的差异化
- **RAG**:已经做了(v0.7),不是新的差异化(D1 引用质量是 RAG 的延伸)

---

## § 6 数据策略

### 6.1 数据源 inventory

| 数据维度 | 来源 | 当前状态 | v1.0 目标状态 |
|---|---|---|---|
| 本地 KB 存量(PDF) | cninfo.com.cn / 政府官网 / 卖方研报 | ✅ 13 篇 / 6016 chunks | 维持 13 篇,不扩 corpus |
| 实时财务 API | tushare(免费版) | 🟡 只有 mock | **真接 tushare**(v0.8.x) |
| Web 搜索 | Bocha API | ✅ production(v0.6) | 加 user 开关 + 主路径常开 |
| 持久 memory | sqlite(自建) | ❌ 未做 | **memory 子系统 v1**(语义+流程层,v0.8.x) |
| 本地 embedding | BGE-M3 | ❌ stub | **v1.0 不做,v1.x roadmap**(2026-05-04 砍,本地硬件受限;retrieval protocol 留口) |
| 本地 LLM | DeepSeek / Qwen-7B | ❌ 未做 | **v1.0 不做,v1.x roadmap**(2026-05-04 砍,本地硬件受限;ChatClient Protocol 留口) |
| 公告增量 ingest | tushare 公告接口 | ❌ | YAGNI 留 v0.9+ |
| 实时新闻 API | 财新 / 第一财经 | ❌ | YAGNI(Web search 覆盖) |

### 6.2 数据策略原则

1. **不扩 corpus**:13 篇够 dogfood;扩 corpus 是 ingest 工程,不是 portfolio 卖点
2. **mock → real 渐进替换**:tushare 优先(v0.8.x);其余视需要
3. **本地能力 v1.0 不做(D2 dropped 2026-05-04)**:作者本地硬件受限;架构上保留 ChatClient Protocol + retrieval protocol 口子,v1.x 再补 spike
4. **持久 memory 限两层**:语义层(用户研究历史 embedding + 摘要)+ 流程层(workflow snapshot);跨用户缓存层 + 评测层留 v0.9+

### 6.3 显式 out of scope(数据)

- Wind / 同花顺 iFinD 等付费数据(cost 不在 scope)
- 雪球 / 股吧 / 微博等社交数据(噪声大不值得)
- 自建 PDF 抓取 pipeline(已有 13 篇够)

---

## § 7 MVP 完成定义(v1.0)

跨多个 sub-version 累积达成的"v1.0 ship"标志:

| # | 完成定义 |
|---|---|
| **1** | **B-1 端到端**:输入企业名 + 投资目标 / 时长 / 风险偏好 → 跑完整投资标的尽调 → 输出 [投资标的尽调报告] 模板的结构化报告 |
| **2** | **B-3 端到端**:对已研究客户 / 个人组合跑客户持仓预警跟踪 → 输出 [客户跟踪简报] 显示 delta + 风险评级变化(私行客户经理视角 + 散户个人组合视角共享同一引擎) |
| **3** | **B-7 端到端**:私行经理 / 散户对生成的报告追问 → chat 答出引用回原章节 |
| **4** | **C 端 6 case 都跑通**:C-1 个股 / C-2 行业 / C-3 事件 / C-4 持仓 / C-5 财报 / C-7 概念 |
| **5** | **D1 强引用**:每条结论可点回原文 PDF 段落(UI + trace) |
| ~~**6**~~ | ~~**D2 本地化**~~:**v1.x roadmap,v1.0 不交付**(2026-05-04 决定,作者本地硬件受限;架构 protocol 口子已留) |
| **6** | **D4 结构化输出**:[投资标的尽调报告] / [客户跟踪简报] 至少 2 种业务模板的 JSON schema + writer agent 出符合 schema 的报告 |
| **7** | **D6 agent-level eval**:golden set ≥ 10 case + LLM-as-judge rubric + dashboard 可看 score / cost / latency |

**D3 中文金融特化**:贯穿 1-7 全部,不是单独一项 deliverable

---

## § 8 量化质量标准(v1.0 ship gate)

| 维度 | 指标 | 数据集 | 阈值 |
|---|---|---|---|
| D1 强引用 | citation precision | 10 case × LLM-as-judge spot check | ≥ 0.85 |
| D1 强引用 | citation recall | 同上 | ≥ 0.95 |
| ~~D2 本地~~ | — | — | **v1.x roadmap,v1.0 不交付**(2026-05-04 砍,本地硬件受限) |
| D3 中文金融(可量化部分) | 中文财务术语 retrieval 命中率 | 20 个术语 query × top-5 | ≥ 90% recall |
| D3 中文金融(qualitative) | spot check report | 5-10 个 corner case | 文档化 |
| D4 结构化输出 | schema validation pass rate | writer 全部输出 | 100%(pydantic 强制) |
| D4 结构化输出 | 必填字段完整率 | 报告 sections 必填字段 | ≥ 95% |
| D6 agent eval | golden set 规模 | — | B-1 ≥ 10 / B-3 ≥ 10 / C 端 ≥ 20 |
| D6 agent eval | judge rubric 维度 | — | 完整性 / 准确性 / 引用 / 风险识别(B-1/B-3) / 相关性(C 端) |
| D6 agent eval | PR regression gate | golden set | 不让 score 下降 > 5% |
| 系统 latency p50 | 实测 | dogfood | B-1 ≤ 5 min / B-3 ≤ 2 min / C 端 ≤ 30s |
| 系统 cost per case | 实测 | dogfood | B-1 ≤ ¥0.50 / B-3 ≤ ¥0.10 / C 端 ≤ ¥0.05 |
| 系统 cost daily budget | 已 set | (v0.8.0 已落) | ¥20 / day |

---

## § 9 路线图(v0.8.x → v1.0)

### v0.8.2-β:信贷调查报告 schema + writer 改造 + B-1 跑通 1 家公司 demo

- 工作量:~1 周
- 出货:可以 demo "选定一家公司,跑出一份信贷调查报告"
- 内容:
  - 信贷调查报告 schema(Pydantic)
  - writer agent 接 schema,structured output
  - 选 1-2 家 KB 已 ingest 的公司(候选:茅台 / 宁德 / 比亚迪 / 招商银行 / 中芯国际)
  - 端到端 dogfood + L0/L1/L2 测试
- **本 spec 的 Spec B 单独承载**

### v0.8.3:memory 子系统 v1 + B-3 存量预警

- 工作量:~3 周
- 出货:可以 demo "之前研究过 X,重新跑只看 delta"
- 内容:
  - memory 子系统 v1(语义层 + 流程层)
  - B-3 端到端:对已研究客户跑 delta 检测
  - 客户跟踪简报 schema + writer
  - 测试覆盖

### v0.8.4:B-1 single deep + 产品定位 reframe

> **2026-05-04 范围调整**:原计划 D2 本地化 + D6 agent eval 一起做(D2 已砍留 v1.x)。Q3 audit 揭示 v0.8.2 ship 的 B-1 backend 半装饰(input 字段不真驱动 5 agent prompt),先做 D6 评测变成"给半成品做评测"。**v0.8.4 调整为 B-1 single deep — 一个 use case 极致 polish + 同步做产品定位 reframe(平台 + 2 persona + 共享底座)**;D6 agent eval 顺延到 v0.8.5。

- 工作量:~3-5 周
- 出货:可以 demo "私行客户经理 / 散户从 landing 进 `/research`,填 6 字段表单,看 5-agent 流式跑出投资标的尽调报告,带 disclaimer + 引用 + 投资建议"
- 内容:
  - 产品定位 reframe:roadmap spec § 1-12 narrative 重写(本 PR)
  - B-1 schema 改名为 `InvestmentDueDiligenceReport`(字段重新设计 + § 6 InvestmentRecommendation 5 档卖方研报标准化术语 + disclaimer 固定字段),旧 v0.8.2 schema 全 repo 替换
  - Backend 5-agent prompt 改造:Planner / DataCollector / Analyst / Writer / Critic 全部 condition on 6 input 字段(`target_ts_code` / `client_total_aum` / `client_existing_position` / `investment_objective` / `investment_horizon` / `risk_tolerance`)
  - 3 differential golden case(同 ts_code,3 组 input variation,LLM-as-judge "input_context_appropriateness" ≥ 0.85)— D6 SUT seed
  - Frontend `/research` 完整 user journey:路由 + B-1 6 字段表单 + 历史列表 + C2 流式 progress + D output 渲染(TL;DR + outline + evidence 侧栏 + disclaimer)+ 错误兜底
  - dogfood ≥ 10 个真实标的 + 修 bug
- ref `docs/superpowers/plans/2026-05-04-v0.8.4-b1-single-deep.md`(7-task implementation plan,通过 `superpowers:writing-plans` 已拆)

### v0.8.5:Constrained LLM router + Anthropic Skills bundle + self-correcting retry edge(2026-05-05 ship)

- 工作量:~1.5 周(实际 wall time)
- 出货:planner 从自由生成 ResearchPlan 改为 schema-constrained 4 选 1 router + 17-component financial_research skill bundle + 第 7 critic LLM-as-judge + retry edge max 2 轮;dogfood 揭示的 plan-driven 不稳问题(prompt 微调 plan 走样)修复
- 内容:
  - **Constrained router**:Planner 收 6 字段 form → LLM 4 选 1 plan_id Literal(`capital_preservation` / `balanced` / `aggressive_growth` / `event_driven`)+ rationale ≤200 字符;subtask templates hardcode 在 `plan_registry`(4 plan × 4 subtask)
  - **Anthropic Skills bundle**:`backend/app/agents/research/financial_research/` 17 components — 11 methodology .md(solvency / profitability / growth / cashflow_quality / valuation / industry / shareholder_governance / short_term_capital_flow / event_driven / risk_factors / decision_framework)+ 3 references(industry_benchmarks.json + recommendation_rules.yaml + position_size_rules.yaml)+ 3 Python helpers(`compute_position_size` / `classify_recommendation` / `lookup_industry_benchmark` 纯函数)
  - **第 7 critic plan_correctness**:LLM-as-judge,0-10,threshold 8.5
  - **LangGraph self-correcting retry edge**:plan_correctness < 8.5 AND retry_count < 2 → 回 `research_planner_node` 收 critic feedback 重选,max 2 轮硬上限
  - **Tool inventory 5 → 13**:加 8 个 tushare-backed(balance_sheet / cashflow / daily_basic / pe_history / forecast / dividend / holder_change / money_flow + 派生 signal)
  - **Writer 调 Python helper 替代 LLM 算数字**:仓位 + 评级 hardcode 在 Python(deterministic),LLM 仅 narrative + footer "Python 决定论修正"
  - **测试**:base + 60+ new(router 18 + plan_registry 15 + skill helpers 20 + scorer 4 + retry 3 + new tool 21 + writer post_process 13);4 differential golden(含 1 retry-trigger pending Phase 9b cassette)
  - **D6 agent-level eval / B-3 narrative / B-7 follow B-1**:从 v0.8.5 移到 v0.8.6+(本次 v0.8.5 聚焦 router + skill bundle + retry,先解决 plan-driven 不稳的根本问题)
  - ref `docs/superpowers/specs/2026-05-05-v0.8.5-constrained-router-design.md`
  - ref `docs/superpowers/plans/2026-05-05-v0.8.5-constrained-router-implementation.md`(10 task,Phase 10b dogfood + cassette 重录由 user 手跑)

### v0.8.6:C 端 5+1 use case batch deep follow B-1 模板

- 工作量:~3 周
- 出货:C 端完整体验,散户作者 dogfood 主入口
- 内容:
  - C-1 / C-2 / C-3 / C-4(2026-05-04 拉回) / C-5 / C-7 共 6 个 use case follow B-1 5 维 user journey 模板
  - C-4 持仓 / 组合分析:reuse B-3 monitoring 引擎,加散户简表 UI + 仓位归因
  - 测试覆盖 + dogfood

### v0.9:整体收尾 + v1.0 ship gate

- 工作量:~1 周
- 出货:v1.0 ship 准备就绪
- 内容:
  - performance 收紧(p50 latency / cost per case 达 § 8 阈值)
  - 简历 / project-story.md update(v1.0 实际能力反映)
  - dogfood report markdown 文档化 5-10 个 corner case
  - v1.0 ship gate 检查(§ 8 量化质量标准全部达标)

### 总历时

v0.8.4 ~3-5 周 + v0.8.5 ~3 周 + v0.8.6 ~3 周 + v0.9 ~1 周 = ~10-12 周。**v1.0 ship 估 2026-06 → 2026-07 中下(~2-3 个月,wall time)**。

### 版本号语义注释

v0.8.x 系列在历史上是 1 周内 ship 的小迭代(v0/0.5/0.6/0.7 各 1 天-1 周)。本 roadmap 4 个 sub-version 加起来 ~10-12 周,严格按历史语义应该叫 v0.9 / v0.10 / v0.11 / v1.0。但为保持本文档已写的命名一致,沿用 v0.8.4 ~ v0.9。**ship v0.9 后 = v1.0 ship**。

---

## § 10 Memory cross-references

- `user_portfolio_target` — 作品定位与作者期望
- `project_dual_mode` — 研报 + 对话 双模式共享底座
- `project_scope_decisions` — 重构功能边界决议(KB / Web / Auth 都有保留理由)
- `project_tech_themes` — 技术亮点 A+D+E+F
- `project_memory_layer` — Memory 子系统四层定义(本 spec § 6.2 限两层)
- `project_eval_pipeline_contract` — 评测 pipeline 契约(D6 基础)
- `project_v0.5_architecture_landed` — 5-agent + Critic Send API(B-1 复用)
- `project_v0.6_architecture_landed` — Bocha web search(C-3 / B-3 数据源)
- `project_v0.7_architecture_landed` — KB + Milvus + 13 PDF + chunker 路由
- `feedback_no_portfolio_simplification` — 工业级落地评估 + alternatives + 取舍要求
- `feedback_chinese_chunk_size_calibration` — 中文 chunking 校准(D3 已落)
- `feedback_account_migration_blast_radius` — 模型/账户切换 blast radius(D2 本地 LLM 切换需注意)

---

## § 11 Out of scope(显式 YAGNI)

跟本 spec / v1.0 ship 无关的事,留 v1.x / v2.0 / 永远不做:

### 数据
- Wind / 同花顺 iFinD 付费数据
- 自建公告 / 新闻爬虫
- 雪球 / 股吧社交数据
- 扩 KB corpus 到 30+ PDF

### Use case
- B-2 行业准入研究
- B-4 政策快速研判(独立)
- B-5 同业对标研究
- B-6 专题研究 / 行业 outlook(独立)
- C-6 盘中实时盯盘
- **私募基金 / 信托产品尽调**(80% 数据需 mock,v1.x 处理)
- ~~C-4 持仓 / 组合分析~~(2026-05-04 拉回 v1.0,详见 § 9 v0.8.6)

### 技术能力
- Memory 跨用户缓存层
- Memory 评测层
- **D2 整体本地化(BGE / 本地 LLM)v1.0 不做**(2026-05-04 调整,作者本地硬件受限;架构 protocol 口子已留,v1.x roadmap)
- Fine-tune 任何模型
- Multi-tenant / RBAC
- 灰度 / A/B 测试基础设施

### 工程
- legacy `app/service/*` 大规模清理(15K LOC,留 v1.1+ 卫生迭代)
- Milvus → PG 元数据双写(原 v0.8 候选,本次决定不做,等真有 case 再说)

---

## § 12 Handoff

- **本 spec(Spec A)不进 writing-plans**:它是 v1.0 长期蓝本,沉淀产品判断
- **v0.8.2 切片 spec(Spec B)由 `2026-05-03-v0.8.2-credit-research-report-design.md` 单独承载**,写完后过 writing-plans 拆 implementation plan
- **v0.8.4 实施按 `docs/superpowers/plans/2026-05-04-v0.8.4-b1-single-deep.md`,通过 `superpowers:writing-plans` 已拆 task-level plan**(7 task,backend → frontend → integration 顺序);spec 由 `docs/superpowers/specs/2026-05-04-v0.8.4-b1-single-deep-design.md` 承载产品定位 reframe + B-1 schema + 5 维 user journey 决策
- **v0.8.5 / v0.8.6 / v0.9 spec 留到对应时间点单独 brainstorming + 写**,本 roadmap § 9 提供 anchor 但不预先冻结具体实施细节
- **简历更新**:本 spec ship 后,简历"投资研究 agent 平台 - 服务私行客户经理 + 散户双 persona"标题下可补充 functions 描述(从 § 3 use case + § 5 差异化里提取 3-4 个 bullet)
