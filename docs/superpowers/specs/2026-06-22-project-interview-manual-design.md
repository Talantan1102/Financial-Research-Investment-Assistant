# 设计方案:AlphaScout 项目面试通关手册

> 参考实物:`D:/t00937989/sglang-interview-site`(13 大类 × 57 题、单文件 `index.html`、双裁判质量闸)。
> 方法论:`building-illustrated-interview-manuals` skill。
> 定位(用户拍板):**项目深挖型 · 全量 13 类 ~61 题 · 沿用工程手册视觉风**。

## 摘要

把本项目做成一本"面试官拿着你的简历深挖这个项目"的题库。每题覆盖 7 个固定维度,配一张原创内联 SVG 图解,**所有机制/数字对照本仓真实代码与 spec 核实**。最大差异点:参考手册的"与 vLLM 对比"facet,在我们这里变成"**你为什么没选另一个方案**"——本项目每个 spec 都是决策评估,天生有被否决的替代方案,这是最强弹药。

产出一个自包含 HTML 站点,可直接用于面试前突击复习。

## ① 形态与产物

- **单文件 `index.html`** 自包含站点:内联 SVG,无 `<img>`/raster/外部图床;唯一外链 = 字体 CDN + highlight.js CDN(同参考模板)。
- **产物目录**:仓库根新建 `interview-manual/`:
  - `build/`:`build.js`(装配+校验)、`template_header.html`、`template_footer.html`、`inventory.json`(题目清单)、`judge-workflow.js`(双裁判循环)、`serve.js`(静态服务)。
  - `sections/`:`01-overview.html` … `13-frontend.html`,每文件一个分类。
  - `index.html`:build 产物。
  - `node_modules/` 进 `.gitignore`。
- 内容语言 zh-CN;品牌名 **AlphaScout · 项目面试通关手册**,副标 *Project Interview Field Guide*。

## ② 每题 7-facet schema(项目深挖版)

`build.js` 校验每题含 1 个 `q-title` + 6 个 `block-*`,缺任一 facet/图 build 即告警。

| # | facet | class | 项目深挖版含义 |
|---|---|---|---|
| 1 | **题目** | `q-title` | 面试官深挖口吻,非"什么是 X"。例:"你为什么把 chat loop 从 LangGraph supervisor 改成裸 Python while 循环?这个决策的收益和代价是什么?" |
| 2 | **考察点 + 追问** | `block-exam` | 面试官在探什么(真做过 vs 简历包装 / 懂不懂代价)+ 2-4 个追问 |
| 3 | **原理讲解** | `block-theory` | 机制 + 数据结构 + why,带 `<h5>` 小标题分层 |
| 4 | **示例 / 推演** | `block-example` | 真实代码片段或架构 + **带具体数字的推演** |
| 5 | **决策对比** | `block-vs` | ⚖️ **你为什么没选另一个方案** 或 与业界标准做法对比,表格 + 公允裁决,绝不稻草人 |
| 6 | **原创图解** | `block-diagram` | 内联 SVG,一图一意,画真实机制 |
| 7 | **总结** | `block-summary` | 3-5 速记 + 一句话记忆钩 + 真实来源(指向本仓 spec/代码 path 或 context 卡) |

题卡另带:难度星级(★1-5)、3-5 个 tag。`block-vs` 表头随题灵活——对手可以是"被否决的架构"或"业界默认做法"。

## ③ 13 大类完整题目清单(61 题)

> 每题给:id · 题面(面试官口吻)· 决策对比对手 · 主要来源(研究阶段必读)。难度后续在撰写时定。

### 01 · 项目总览与架构（overview，4 题）
- `overview-q1` AlphaScout 是什么?请从产品三支柱(深度研究 / 持仓监控 / 对话)和整体架构讲起。｜对比:单体 chatbot vs 多支柱架构｜来源:`v1-use-case-classification.md`、`product-minimalism-default.md`
- `overview-q2` 这是个人作品,你怎么权衡"生产级健壮"与"体现算法+应用设计深度"?哪些地方刻意做厚、哪些刻意留口子?｜对比:生产级 vs 作品级取舍｜来源:`user-portfolio-target.md`、`arch-prefers-own-control-flow`
- `overview-q3` 整个系统的技术栈与数据流:一条用户消息从前端到落库经过哪些组件?｜对比:框架编排 vs 自有控制流｜来源:`chat-loop-redesign-done.md`、`chat-session-persistence-done.md`
- `overview-q4` 项目里你最自豪 / 最难的技术点是什么?为什么难?｜对比:候选人自选 highlight｜来源:flagship 三类自选

### 02 · Chat Loop 引擎（loop，6 题，flagship）
- `loop-q1` 为什么把 chat loop 从 LangGraph supervisor 单程图退役成裸 Python while 循环?收益与代价各是什么?｜对比:LangGraph supervisor 图 vs 裸循环｜来源:`chat-loop-redesign-done.md`、`2026-06-05-chat-loop-redesign-design.md`
- `loop-q2` 你的循环有"四道终止闸",为什么需要四道而不是一道?各拦什么?｜对比:单一 max-steps vs 多道闸｜来源:`2026-06-11-chatloop-termination-gate-precision-design.md`
- `loop-q3` "窗口四区"(KV-cache 分区)是怎么切的?为什么这样切能省 token / 省钱、还能稳住 prefix cache?｜对比:整窗重拼 vs 分区固定前缀｜来源:`chat-loop-redesign-done.md`、`2026-06-12-chatloop-context-pressure-valve-design.md`
- `loop-q4` 工具渐进披露:为什么不一次把所有工具塞给模型?分档依据是什么?｜对比:全量工具 vs 渐进披露｜来源:`tool_docs.py`、`2026-06-11-chatloop-tool-guardrails-and-metrics-design.md`
- `loop-q5` steering(Redis List)+ turn 原子语义:用户在 agent 跑到一半插话,怎么不破坏状态?｜对比:打断重启 vs steering 注入｜来源:`2026-06-11-chatloop-steering-predispatch-checkpoint-design.md`
- `loop-q6` 用原生 function calling 而非框架的 tool 抽象,你踩过哪些坑?(qwen3 关思考 / tool_call args 合法化 / 非 deepseek 兼容)｜对比:框架 tool 层 vs 裸 OpenAI function calling｜来源:`openai_client` 提交 `26fdcc86`

### 03 · 跨会话记忆系统（memory，6 题，flagship）
- `memory-q1` 为什么用 MemGPT 分层 × Zep 双时态图杂交,而不是单纯抄其中一个?各取了什么、丢了什么?｜对比:纯 MemGPT vs 纯 Zep vs 杂交｜来源:`c5-cross-session-memory-done.md`
- `memory-q2` 双时态(bi-temporal)是什么?为什么记忆系统必须区分"事件发生时间"和"系统获知时间"?不区分会怎样?｜对比:单时间戳 vs 双时态｜来源:`c5-plan2a-write-pipeline-core-done.md`
- `memory-q3` 8 步写入 pipeline + 4 动作冲突消解:新记忆和旧记忆矛盾时怎么办?｜对比:覆盖写 vs 冲突消解四动作｜来源:`c5-plan2a-write-pipeline-core-done.md`
- `memory-q4` 读取侧 3-way 混合检索 + RRF v2 时间感知排序:怎么把图 / 向量 / 全文三路融合?为什么排序要感知时间?｜对比:单路向量检索 vs 三路 RRF｜来源:`c5-plan3-read-pipeline-done.md`
- `memory-q5` memory vs KB 路由:怎么判断一句话该查"用户上下文"还是"市场知识"?路由错了怎么兜底?｜对比:不分流全查 vs 触发词分类+LLM fallback｜来源:`c5-plan6-memory-kb-routing-done.md`
- `memory-q6` AGE 图 + Milvus + PG 三方存储,写入崩在中间怎么不脏?一致性怎么保证?｜对比:单库 vs 三方 + reconciliation｜来源:`c5-plan1a-foundation-schema-done.md`、`memory-dialogue-eval-harness-landed.md`(AGE 毒事务教训)

### 04 · 知识库与 RAG（rag，5 题）
- `rag-q1` 类型路由切块:研报走 semantic、财报走 section、政策走 clause,为什么不能一刀切?｜对比:固定 size 切块 vs 类型路由｜来源:`kb-chunking-strategy.md`
- `rag-q2` Embedding 选型:为什么主力 qwen text-embedding-v3 而非 BGE-M3?"同维互换不重建 collection"是什么工程考量?｜对比:qwen v3 vs BGE-M3｜来源:`kb-embedding-choice.md`
- `rag-q3` 中文切块的坑:为什么要中文 separators + tiktoken 计数而不是按字符数?｜对比:字符切 vs token 感知切｜来源:`kb-chunking-strategy.md`
- `rag-q4` 你的 KB 评估只有 agent 端到端 LLM-judge,缺 chunking/embedding/检索的离线指标,为什么这是个缺口?该怎么补?｜对比:端到端 eval vs 分层离线指标｜来源:`kb-eval-gaps.md`
- `rag-q5` RAG vs 直接长上下文塞进去:你怎么权衡?什么时候不该用 RAG?｜对比:RAG vs 长上下文｜来源:`kb-chunking-strategy.md`、`v0.7-kb-search-milvus-design.md`

### 05 · 多模型估值与对抗（valuation，5 题）
- `valuation-q1` 多模型 cross-check:为什么用 4 个模型而不是 1 个跑估值?IndustryModelRouter 按什么选模型?｜对比:单模型 vs 4 模型 cross-check｜来源:`v1.x-multi-valuation-cross-check-landed.md`
- `valuation-q2` bull/bear 两轮对抗辩论:怎么用对抗结构防 hallucination?为什么两轮?｜对比:单 agent 写结论 vs 对抗辩论｜来源:`v1.x-bull-bear-debate-landed.md`
- `valuation-q3` "双 hallucination 防御"完整闭环是什么?cross-check 和 debate 各防哪一半?｜对比:单层防御 vs 双层｜来源:`v1.x-bull-bear-debate-landed.md`
- `valuation-q4` Critic 多维(7→8 维)裁判:维度怎么设计?加第 8 维加的是什么?｜对比:单分裁判 vs 多维 rubric｜来源:`v1.x-multi-valuation-cross-check-landed.md`、`v1.x-bull-bear-debate-landed.md`
- `valuation-q5` DCF 3 scenarios + OutlierDiagnosisAgent:模型给出的异常估值怎么诊断、怎么不被一个离谱值带偏?｜对比:取均值 vs 离群诊断｜来源:`v1.x-multi-valuation-cross-check-landed.md`

### 06 · 持仓监控引擎（monitor，4 题）
- `monitor-q1` 持仓监控和"对话研究"是怎么"一体两面"的?为什么选这个用例而不是另一个?｜对比:被否决的 use case vs 持仓监控｜来源:`v1.0-use-case-2-portfolio-monitoring.md`
- `monitor-q2` Celery + Redis + PG 怎么协作做定时监控?为什么需要独立 worker?｜对比:同进程定时 vs Celery 独立 worker｜来源:`v1.0-monitoring-engine-done.md`、`celery-redis-test-fixture-pattern.md`
- `monitor-q3` 5 类公告怎么分类、怎么从原始公告触发用户可读的提醒?｜对比:全量推送 vs 分类触发｜来源:`v1.0-monitoring-engine-done.md`
- `monitor-q4` 监控规则引擎:从原始市场数据到"该不该提醒用户"的判定链路怎么设计?｜对比:阈值硬编码 vs 规则引擎｜来源:`2026-05-08-v1.0-portfolio-monitoring-engine-design.md`

### 07 · 代码解释器与工具沙箱（sandbox，4 题）
- `sandbox-q1` 为什么让 LLM 写 Python 跑(run_python),而不是给一堆固定计算工具?边界在哪?｜对比:固定工具 vs LLM 写代码｜来源:`code-interpreter-run-python-done.md`
- `sandbox-q2` run_python 怎么复用 SkillExecutor 沙箱(execute_source 内联入口)?怎么隔离、怎么留 Docker 口子?｜对比:新建沙箱 vs 复用 SkillExecutor｜来源:`2026-06-11-code-interpreter-tool-design.md`
- `sandbox-q3` 为什么 plotly 交互图走 chart 事件而不进 LLM 上下文?进了会怎样?｜对比:图 JSON 进上下文 vs chart 事件旁路｜来源:`code-interpreter-run-python-done.md`
- `sandbox-q4` 你踩的两个坑:plotly 用 dist-min/factory 避 mapbox、沙箱 OpenBLAS 单线程避 OOM,各是怎么定位的?｜对比:默认配置 vs 调优后｜来源:`code-interpreter-run-python-done.md`

### 08 · 会话持久化与可靠性（persist，5 题）
- `persist-q1` 会话会丢 / 卡 / 不一致的三个根因是什么?你怎么逐个根治?｜对比:内存态会话 vs DB-as-truth｜来源:`chat-session-persistence-done.md`
- `persist-q2` DB-as-truth + Agent/Transport 解耦(Celery 独立进程):为什么要这么拆?解耦买到了什么?｜对比:agent 跑在请求线程 vs 独立进程｜来源:`chat-session-persistence-done.md`
- `persist-q3` Redis Pub/Sub 取消 + LangGraph checkpoint resume:用户点取消、或服务重启,怎么干净中断和恢复?｜对比:硬杀进程 vs pub/sub + checkpoint｜来源:`2026-05-16-chat-session-persistence-design.md`
- `persist-q4` 6 状态任务生命周期 + stale scanner 自愈:任务怎么不会永远卡在中间态?｜对比:无状态机 vs 6 态 + 扫描自愈｜来源:`chat-session-persistence-done.md`
- `persist-q5` 你沉淀过一条教训"第 n 轮修复 = phase1 重做",这是什么意思?systematic debugging 在这里教了你什么?｜对比:打补丁 vs 重做第一阶段｜来源:`chat-session-persistence-done.md`(`feedback_n_round_fix_means_phase1_redo`)

### 09 · Agent 评估方法论（eval，6 题，flagship）
- `eval-q1` 对话 / 工具型 Agent 怎么评估?你用了哪四个相互独立的角度?为什么要独立?｜对比:单一 LLM-judge vs 四角度｜来源:`conv-agent-evaluation-methods.md`、`2026-06-02-conversational-agent-evaluation-survey.md`
- `eval-q2` 反向出题 + pass@k:怎么自动造金融计算题、怎么判分?为什么是反向?｜对比:人工出题 vs 反向生成 + oracle｜来源:`2026-06-17-question-gen-mvp-design.md`、`exhaustive-axis-not-seed-list`
- `eval-q3` LLM-judge 的坑:set/ranking 自由文本判分、judge 抽取抖动,你怎么治?｜对比:正则判分 vs LLM 抽取判分｜来源:`pre-rl-tooling-baseline.md`
- `eval-q4` DD 报告质量 eval:5 个 metric + V0-V3 ablation 控制变量,为什么要 ablation?｜对比:单分打分 vs 消融控制变量｜来源:`dd-report-eval-phase-2-landed.md`
- `eval-q5` 记忆对话 eval:双层断言体系怎么搭?首跑就抓出 5 个系统级 bug(生产 Path B 抽取从未工作 / AGE 毒事务等),说明了什么?｜对比:端到端断言 vs 双层(终态+轨迹)｜来源:`memory-dialogue-eval-harness-landed.md`
- `eval-q6` eval gold 随实时数据漂移、复权≠价格回报,这两个口径坑你怎么发现和钉死的?｜对比:as_of=今天 vs 钉死交易日;复权 vs 价格回报｜来源:`eval-gold-staleness-live-data`、`eval-adjusted-vs-price-return`

### 10 · RL 准备与工具可靠性（rl，4 题）
- `rl-q1` 你的结论是"先修工具比上 RL 更对症",怎么论证断崖是工具问题而非模型能力问题?｜对比:直接上 RL vs 先修工具｜来源:`2026-06-17-pre-rl-tooling-baseline.md`
- `rl-q2` pre-RL 基线:CAGR 桶 13%→100% 是怎么定位真凶的(get_daily 静默 tail cap)?为什么"agent 预防性分段"不是坏习惯是被逼的?｜对比:加预算刷分 vs 修静默 cap｜来源:`pre-rl-tooling-baseline.md`
- `rl-q3` SFT 底料采集:为什么轨迹要 gold 隔离、关降级、只收 halt_reason==natural?三个坑各是什么?｜对比:落末次答案 vs 完整干净轨迹｜来源:`2026-06-18-shorten-chains-and-rl-substrate-design.md`
- `rl-q4` 修完工具后,为什么 RL 该瞄"工具调用可靠性 / 多步编排"而不是"计算能力"?这个靶子怎么定出来的?｜对比:RL 学算指标 vs RL 学稳编排｜来源:`pre-rl-tooling-baseline.md`

### 11 · 检索与深度研究（research，4 题）
- `research-q1` deep research 模式为什么刻意"不给投资建议"?这个产品决策背后的考量?｜对比:给建议 vs 只给研究｜来源:`2026-06-04-deep-research-no-recommendation-and-eval-design.md`
- `research-q2` bocha 搜索集成:为什么引外部搜索、怎么把搜索结果喂进研究链路?｜对比:纯 KB vs KB+实时搜索｜来源:`2026-05-01-v0.6-bocha-search-integration-spec.md`
- `research-q3` deep research 的编排:多源检索→深读→引用合成,怎么保证有据可查、不编来源?｜对比:一次性生成 vs 多阶段带引用｜来源:`v0.5-research-mode-spec.md`
- `research-q4` 研究产物怎么评估质量?(承接 DD 报告 eval 在研究体裁上的应用)｜对比:主观看 vs metric 化｜来源:`dd-report-eval-phase-1-landed.md`

### 12 · 工程基础设施（infra，4 题）
- `infra-q1` PG-only 迁移:为什么从 sqlite / 多 with_variant 统一到全 PG?迁移踩了什么?｜对比:sqlite+PG 双轨 vs 全 PG｜来源:`pg-only-migration-pr-a-landed.md`、`pg-only-migration-pr-b-landed.md`
- `infra-q2` 分层测试 DB 策略:为什么所有层都连真 PG + transaction rollback isolation?容器化 fixture 怎么复用?｜对比:mock/sqlite 测试 vs 真 PG + rollback｜来源:`test-db-layered-strategy.md`、`pg-test-container-pattern.md`
- `infra-q3` 模型 registry / allowlist:为什么需要、怎么做模型切换与"模型×桶"对比?｜对比:硬编码模型 vs registry 切换｜来源:`2026-06-18-model-switching-and-comparison-design.md`
- `infra-q4` 依赖管理:为什么重型 / 可选依赖走 optional extras 而非全塞 base?import 链假设为什么要 smoke test?｜对比:全量 base deps vs optional extras｜来源:`optional-extras-for-heavy-deps.md`、`verify-import-chain-with-smoke-test.md`

### 13 · 前端与产品工程（frontend，4 题）
- `frontend-q1` chat-first 前端:AppShell + valtio stores + SSE(useChatSSE)怎么组织?为什么是 chat-first?｜对比:表单式 UI vs chat-first｜来源:`v0.9-chat-frontend-foundation.md`、`v0.9-chat-plan4b-architecture.md`
- `frontend-q2` /memory 图可视化:Cytoscape 图 + timeline + audit 怎么把记忆系统可视化给用户?｜对比:列表展示 vs 图谱可视化｜来源:`c5-plan7b-visualizations-onboarding-done.md`
- `frontend-q3` persona 可编辑 UI:双轨语义 + atomic 操作 + 升级动画,用户改画像怎么不和系统自动学习打架?｜对比:只读画像 vs 可编辑双轨｜来源:`persona-editable-ui-done.md`
- `frontend-q4` 研发看板(Harness Board review mode):为什么给自己的项目做一个知识沉淀工具?DeepCard + 5 视图怎么联动?｜对比:README 文档 vs 交互看板｜来源:`harness-board-review-mode-done.md`

**合计:4+6+6+5+5+4+4+5+6+4+4+4+4 = 61 题。**

## ④ 内容准确性策略(本手册最关键的质量杠杆)

参考手册对照 sglang 源码核实;**我们对照本仓真实代码 + spec + context 卡**。

- 研究阶段每个分类的 author agent **必须实读**对应 `docs/superpowers/specs/`、`docs/claude-context/`、相关 `backend/` 代码(清单见各题"来源")。机制 / 数字 / 接口名不许凭记忆编。
- 技术裁判 lens 拿本仓 file 核验机制是否属实;**编造的机制 = critical 一票否决**(面试里当场翻车)。
- 拿不准 / 来不及核实的数字,标"量级估计"而非伪精确。

## ⑤ 构建流水线(building-illustrated-interview-manuals 方法论)

1. **先搭脚手架 + 一个金样分类端到端**:从参考 `build/` 复制并改品牌/标题/`block-vs` 表头语义;**先把 flagship「Chat Loop 引擎」整类(6 题)做完**,跑通 build + 浏览器自检 → 给用户看一眼定调,确认 7-facet + SVG 形态。
2. **研究→撰写→校验**:其余 12 类,每类一个 author agent 并行(读真实代码),一个 agent 一个文件(绝不并发改同一文件)。
3. **双裁判循环**:技术准确(对照本仓 file)× 教学/完整性,各打 0-100 加权 rubric,均分到 ≥92;critical 一票否决;fix→rejudge 最多 2-3 轮,卡住就手改。
4. **浏览器自检**(HTTP 起 serve.js):getBBox 查每个 SVG `<text>`/`<tspan>` 不溢出 viewBox、横向溢出、计数(卡片/分类/表/图)、搜索过滤、滚动高亮、0 console error;`?v=N` 破缓存。
5. **精简 pass**(单独一步,只删不加):砍到面试复述粒度——删私有符号 / 源码行号 / 公式推导 / 穷举枚举 / 冗余佐证;保留核心概念 + 关键 tradeoff + 每点一个头条数字 + 图;去多余加粗(≤1 bold/句)。

## ⑥ 内容铁律

- **不用内部代号**:题面 / 正文绝不出现 `B-3`/`C.5`/`A5a`/`L3a`/`#118` 这类代号(面试官看不懂),一律自解释中文名。HTML 锚点 id(`loop-q1`)是内部标识不算。
- **面试官口吻**:题目是深挖追问,不是"什么是 X"。
- **数字全部来自真实 spec / 代码**,不可手搓;无据标"量级估计"。
- **决策对比绝不稻草人**:被否决的方案也给公允评价,说清它好在哪、我们为什么仍不选。
- **每题一图**,画真实机制(窗口四区 / 8 步写入 / 双时态图 / 任务状态机 / 四道闸……),非装饰。

## ⑦ 边界 / YAGNI

- **不做**:多语言(只 zh-CN)、后端 / 数据库(纯静态站)、登录、可编辑 / 评论、自动从代码生成题(题是人工策划 + agent 撰写)。
- **不改**本项目任何 backend / 前端代码;手册是只读旁观者,产物完全隔离在 `interview-manual/`。
- 分类 11(检索与深度研究)与 04(RAG)有少量主题相邻,但 deep research 的"不给建议 / 多源编排 / 带引用合成"与 KB 切块/embedding 是不同考点,保持分开。

## 关键来源索引

- 参考实物:`D:/t00937989/sglang-interview-site/`(`build/inventory.json`、`build/template_header.html`、`sections/02-radix.html` 为样板)。
- 方法论:`building-illustrated-interview-manuals` skill + 其 `assets/`(genericized 脚手架)+ `workflow-recipes.md`。
- 内容来源:`docs/claude-context/`(项目知识卡片)、`docs/superpowers/specs/` 与 `plans/`(决策评估与实施)、`backend/`(真实代码核验)。
