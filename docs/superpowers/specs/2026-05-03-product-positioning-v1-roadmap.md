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

## § 1 项目定位:双重身份

| 维度 | 简历版本(对外讲故事) | 面试 / 实施版本(对内真实) |
|---|---|---|
| 项目名 | Agent 投研助手 | (同) |
| 交付对象 | 银行客户(假设性) | 个人作品集 |
| 用户场景 | 银行公司金融部 / 信贷研究 copilot | 个人投资研究 / 关心的标的和行业 |
| 数据 | 模拟银行内部 KB + 行情 + 监管文件 | 公开 PDF(已 ingest 13 篇) + tushare + Web |
| 设计哲学 | 按银行级约束:本地化、强引用、可追溯、可审计、流程化 | 用户=作者本人,但按上面那套约束做,体现技术能力 |
| 评估 | 假设的"业务规则 + 监管合规"(用公开数据模拟) | 作者 dogfood 能判断好坏 + 引用准确性 |

**面试讲法**:"我做的是 Agent 投研助手,我假想的用户 persona 是银行公司金融部的信贷研究分析师,我按 banking 的合规/可追溯/本地化约束设计;但作为个人项目,我 dogfood 用法是把自己当 C 端散户使用,验证产品质量。两种用户共享同一套 agent 底座。"

**绝不假装是真银行项目**。诚实声明个人 portfolio + 假想 persona,既保护甲方信息也体现工业级设计能力。

---

## § 2 用户画像

### 2.1 B 端 — 银行金融部 / 信贷研究分析师(假想 persona)

**画像**:
- 公司金融部 / 信贷审批中心 / 风险管理部
- 日常工作:为信贷决策提供研究支持(尽调、风险评估、存量跟踪)
- 工作产出:**结构化研究报告**(信贷调查报告、客户跟踪简报、行业准入报告)
- 决策影响:百万级以上信贷风险敞口

**对工具的硬约束**:
- **数据合规**:严禁调通用云 LLM API on 客户数据;**必须本地部署 + 可审计**(监管要求)
- **强引用 + 可追溯**:每条结论可追到原文(决策依据要能查);hallucination 是 PR 灾难
- **强结构化输出**:输出符合内部模板,可直接进现有 workflow(信贷审批表)
- **多角色协作**:分析师起草 → 风控 review → 合规盖章
- **模型偏好**:可控的小模型 / 私有化部署(Qwen 本地、ChatGLM、DeepSeek 本地);避免黑盒 API

### 2.2 C 端 — 个人投资者(作者本人 dogfood)

**画像**:
- 关心 A 股市场,有自己的投资标的和行业 watch list
- 日常需求:个股研究、行业判断、事件追踪、财报快速解读、概念学习
- 决策影响:个人持仓的买卖判断
- 不是专业研究员,需要**口语化交互 + 短回答 + 简单图表**

**对工具的需求**:
- **快速响应**:几秒到几十秒
- **多轮追问**:对话式,不是一次性长报告
- **引用回原文**:可追溯但不强制(质量加分项)
- **数据多样**:KB + 实时行情 + Web 新闻

### 2.3 双用户共享底座的合理性

两类用户在**形态上完全不同**(B 端长报告 / C 端短对话),但**底层能力可共享**:

- planner / agent 池(retrieval / writer / critic / data_collector)
- 工具栈(KB 检索 / Web 搜索 / 行情 API)
- context 管理 + cost budget + observability + memory

只是**不同入口编排策略不同**:
- B 端走 A 研报模式(长流程 + Critic + Writer)
- C 端走 B 对话模式(短流程 + 流式 + 自主调度工具)

---

## § 3 Use case(B + C 共 8 个)

### 3.1 B 端 use case

| ID | Use case | 触发 | 输入 | 输出形态 | 模式 |
|---|---|---|---|---|---|
| **B-1** | **企业信贷尽调研究** | 客户申请贷款 → 信贷部要研究 | 企业名 + 贷款金额/期限/用途 | "信贷调查报告":主体资格 / 财务 / 行业地位 / 风险 / 建议 | A 研报 |
| **B-3** | **存量客户预警跟踪** | 季度/月度 review 已放贷客户 | 企业名(已是客户) | "客户跟踪简报":新增信号 + 风险评级变化 + 跟进动作 | A 研报 + memory |
| **B-7** | **审批人对报告的多轮追问** | 审批人 review 报告时遇到疑问 | 自然语言问句("XX 应收账款波动原因") | 流式回答 + 引用回原章节 | B 对话(接 report context) |

### 3.2 C 端 use case

| ID | Use case | 输入 | 输出 |
|---|---|---|---|
| **C-1** | 个股 / 标的研究 | "茅台最近怎么样" / "比亚迪 vs 宁德对比" | 几条要点 + 引用 + 图表 |
| **C-2** | 行业 / 主题判断 | "半导体下半年看法" | 几条要点 + 关键标的 |
| **C-3** | 事件追踪 | "美联储议息后市场反应" / 新政影响 | 时间线 + 受影响标的 |
| **C-5** | 财报快速解读 | "茅台 Q3 亮点和雷点" | 财务要点 + 增长 / 风险 |
| **C-7** | 概念 / 术语解释 | "什么是久期管理" | 定义 + 应用场景 + 例子 |

### 3.3 显式不做(YAGNI)

- B-2 行业准入研究(B-1 包含)、B-4 政策快速研判(ad-hoc 强不好做 demo)、B-5 同业对标(B-1 多 instance 扩展)、B-6 专题研究(太广)
- C-4 持仓 / 组合分析(需 portfolio 数据)、C-6 盘中实时盯盘(需行情 stream)
- 留 v0.9+ 或永远不做

---

## § 4 模式映射

```
                    ┌───────────────────────────────────┐
                    │         共享底座(单进程)         │
                    │  planner / agent 池 / 工具栈      │
                    │  context / cost / observability   │
                    │  memory(语义层 + 流程层)        │
                    └───────────────────────────────────┘
                              ↑                ↑
                              │                │
              ┌───────────────┘                └───────────────┐
              │                                                │
   ┌──────────┴──────────┐                          ┌──────────┴──────────┐
   │  A 研报模式入口     │                          │  B 对话模式入口     │
   │  (长流程 + Critic   │                          │  (流式 + 自主调度)  │
   │   + Writer + chart) │                          │                     │
   └──────────┬──────────┘                          └──────────┬──────────┘
              │                                                │
   ┌──────────┴──────────┐                          ┌──────────┴──────────┐
   │   B 端              │                          │  B 端 secondary +   │
   │   ・B-1 信贷尽调   │                          │  C 端 primary       │
   │   ・B-3 存量预警   │                          │  ・B-7 审批人追问  │
   │                     │                          │  ・C-1 个股研究    │
   │                     │                          │  ・C-2 行业判断    │
   │                     │                          │  ・C-3 事件追踪    │
   │                     │                          │  ・C-5 财报解读    │
   │                     │                          │  ・C-7 概念解释    │
   └─────────────────────┘                          └─────────────────────┘
```

**讲故事时**:"我做了一个 Agent 投研助手,有研报模式和对话模式两种形态,共享同一套 agent 底座。研报模式产出银行内部需要的结构化报告(信贷调查 / 客户跟踪),对话模式服务个人用户的快速问答。两种模式的 planner 接口一致,只是编排策略不同。"

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

**问题陈述**:B-1 / B-3 输出必须符合**银行内部业务模板**(信贷调查报告 / 客户跟踪简报),自由文本输出无法直接进 workflow。

**业界 alternatives**:
- 自由文本 + 模板 prompt("请按以下格式..."):LLM 不稳定,字段缺失常见
- JSON mode(OpenAI / DeepSeek):格式对了,语义不稳定
- Pydantic schema + structured output(Anthropic tool use / OpenAI structured output):格式 + 类型双保证,**业界 best practice**
- DSPy / 复杂框架:overkill

**我们取舍**:
- 用 **Pydantic schema + LLM structured output**(项目已有 LLMResponse + tier_router,扩 schema 即可)
- 定 2 种业务模板:`CreditInvestigationReport`(B-1)、`ClientTrackingBrief`(B-3)
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
| **1** | **B-1 端到端**:输入企业名 → 跑完整尽调研究 → 输出 [信贷调查报告] 模板的结构化报告 |
| **2** | **B-3 端到端**:对已研究过的客户跑预警 → 输出 [客户跟踪简报] 显示 delta + 风险评级变化 |
| **3** | **B-7 端到端**:审批人对生成的报告追问 → chat 答出引用回原章节 |
| **4** | **C 端 5 case 都跑通**:C-1 个股 / C-2 行业 / C-3 事件 / C-5 财报 / C-7 概念 |
| **5** | **D1 强引用**:每条结论可点回原文 PDF 段落(UI + trace) |
| ~~**6**~~ | ~~**D2 本地化**~~:**v1.x roadmap,v1.0 不交付**(2026-05-04 决定,作者本地硬件受限;架构 protocol 口子已留) |
| **6** | **D4 结构化输出**:[信贷调查报告] / [客户跟踪简报] 至少 2 种业务模板的 JSON schema + writer agent 出符合 schema 的报告 |
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

### v0.8.4:agent-level eval 升级(D6 单做)

> **2026-05-04 范围调整**:原计划 D2 本地化 + D6 agent eval 一起做,因作者本地硬件受限,**砍 D2 留 v1.x**,本版本只做 D6。工期从 ~2.5 周收到 ~1-1.5 周。

- 工作量:~1-1.5 周
- 出货:可以 demo "改 prompt 立刻看 golden set 跑分变化 + dashboard 看 cost/latency/score"
- 内容(待 v0.8.4 brainstorming 收紧):
  - D6 agent-level eval:golden set ≥ B-1 ×10 + B-3 ×10 + C 端 ×20
  - SUT 从 LLMService 升到 ResearchAgent(整 agent run 的 trace)
  - LLM-as-judge rubric 多维度(完整性 / 准确性 / 引用质量 / 风险识别 [B-1/B-3] / 相关性 [C 端])
  - Dashboard 可视化(reuse trace-view CLI 或加 web UI — brainstorming 决定)
  - PR regression gate:golden score 下降 > 5% 不让 merge
  - Cost budget:30+ case 跑一次的预算 — brainstorming 估算

### v0.8.5:B-7 追问 + D1 引用 UI + C 端打磨

- 工作量:~2 周
- 出货:完整 v1.0 demo
- 内容:
  - B-7 审批人追问:chat 接生成的报告上下文
  - D1 引用 UI:前端点击结论 → 跳转 PDF chunk
  - C 端 chat UI 打磨 + Web search 开关
  - 测试覆盖

### 总历时

砍 D2 后:v0.8.4 ~1-1.5 周 + v0.8.5 ~2 周 = 剩余 ~3-4 周(原计划 ~4.5 周)。**v1.0 ship 估 1.5-2 个月**(2026-05 → 2026-06/07)。

### 版本号语义注释

v0.8.x 系列在历史上是 1 周内 ship 的小迭代(v0/0.5/0.6/0.7 各 1 天-1 周)。本 roadmap 4 个 sub-version 加起来 ~9 周,严格按历史语义应该叫 v0.9 / v0.10 / v0.11 / v1.0。但为保持本文档已写的命名一致,沿用 v0.8.2 ~ v0.8.5。**ship v0.8.5 后 = v1.0 ship**。

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
- C-4 持仓 / 组合分析
- C-6 盘中实时盯盘

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
- **v0.8.3 / v0.8.4 / v0.8.5 spec 留到对应时间点单独 brainstorming + 写**,本 roadmap 提供 anchor 但不预先冻结具体实施细节
- **简历更新**:本 spec ship 后,简历"Agent 投研助手 - 面向银行客户交付"标题下可补充 functions 描述(从 § 3 use case + § 5 差异化里提取 3-4 个 bullet)
