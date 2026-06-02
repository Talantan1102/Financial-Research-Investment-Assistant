# 对话 / 工具型 Agent 怎么评估 —— 方法论深度研报

> 生成日期：2026-06-02
> 方法：Workflow fan-out 联网调研（6 维并行 WebSearch/WebFetch）+ 22 条事实对抗校验（每条方法独立联网核实，标注 confirmed / partly）
> 校验基线：全部 confirmed 或 partly（**无"完全错误"条目**）；partly 多为数字微调与个别张冠李戴，已在文中修正。

---

## 0. 一句话地图

评估对话 / agent 不是单一指标，而是**四层正交**的体系：

| 层 | 评什么 | 代表方法 | 判定形态 |
|---|---|---|---|
| **A. 输出质量** | 单条回答好不好 | LLM-as-judge（G-Eval / MT-Bench / AlpacaEval / Arena-Hard） | 1-5 分 / win rate / Elo |
| **B. 任务完成** | 任务有没有真做成 | τ-bench / SWE-bench / WebArena / GAIA / BFCL | 终态匹配、pass@1、pass^k、resolve rate |
| **C. 过程 / 轨迹** | 中间步骤对不对 | trajectory matching、step-level PRM、TRAJECT-Bench | 工具名 EM、参数匹配、冗余步骤、subset/superset |
| **D. 生产 / 在线** | 上线后真实表现 | 用户反馈、隐式信号、在线 judge、guardrail、A/B、cassette 回归 | thumbs、retry 率、采样打分、拦截率、CI 红绿 |

贯穿全局的两条暗线：
- **LLM-as-judge 的偏差**（position / verbosity / self-enhancement）与缓解（swap、长度去偏、CoT、多采样）。
- **从"匹配输出"转向"校验环境终态副作用"**，并用 **pass^k**（连做 k 次都成功）取代单次 accuracy 来度量可靠性。

---

## A 层 · LLM-as-a-Judge：用强模型当裁判

核心范式两族：**直接打分**（绝对分）vs **成对比较**（相对赢面）。打分又分 reference-based（有标准答案，适合数学）/ reference-free（只给 rubric，适合开放对话）。共识：好的 judge 设计能让 GPT-4 与人类一致率达 **80–90%**，甚至高于人类彼此之间的一致率。

### A1. G-Eval —— rubric 直接打分 + CoT + 概率加权 ✅ confirmed
三步机制：
1. **Auto-CoT**：把一条评估准则用 LLM 自动展开成结构化 evaluation steps。
2. **form-filling**：judge 顺着 steps 推理后给一个 1-5 整数分。
3. **概率加权**：不取整数，而取 LLM 对每个分数 token 的概率，算期望 `Σ p(sᵢ)·sᵢ`，把离散分变连续，缓解大量样本同分。

> **具体例子**：新闻原文 + 一条生成摘要，准则 = Coherence。judge 输出各分概率 `P(5)=0.6, P(4)=0.3, P(3)=0.1` → 加权分 `5×0.6+4×0.3+3×0.1 = 4.5`。在 SummEval 上 G-Eval-GPT-4 与人类的 Spearman 相关 **0.514**，大幅超过 ROUGE/BERTScore。
>
> ⚠️ 校验修正：SummEval 四个标准维度是 **coherence / consistency / fluency / relevance**，原文举例写的 "faithfulness" 不是其原始维度（应为 consistency）。机制与 0.514 数字均准确。

来源：arxiv.org/abs/2303.16634 · confident-ai.com/blog/g-eval-the-definitive-guide

### A2. MT-Bench single-answer grading（1-10 绝对分）✅ confirmed
80 道 2 轮题、8 类。GPT-4 judge 先写理由再输出 `Rating: [[8]]`。数学/推理类走 **reference-guided grading**：先让 judge 独立生成参考解再对照评，把 math/reasoning 的误判率从 ~70% 降到 ~15%。
> GPT-4 judge 与人类一致率（S2 去 tie）**85%**，高于人类彼此的 81%。

### A3. Pairwise + position-bias 缓解（Arena-Hard）⚠️ partly
judge 同看 prompt + 答案 A + 答案 B 选谁赢，聚合成 win rate / Elo。
- **swap & consistency** 去 position bias：交换 A/B 跑两遍，只有方向一致才算赢，否则判 tie。
- Arena-Hard-Auto 用 5 档标签（A≫B / A>B / A≈B / B>A / B≫B），大胜扣更多分提升可分性。

> **具体例子**：Arena-Hard = 500 道从 Chatbot Arena 挖的难题，候选 vs 基线 GPT-4-0314，judge = GPT-4-Turbo，每题 swap 跑 2 遍。MT-Bench 实测 position bias：交换位置后只有 **65% 一致**，GPT-4 约 30% 偏好第一位。
>
> ⚠️ 校验修正：与 Chatbot Arena 人类排名一致率官方是 **89.1%**（非 90.8%）；成本约 **$25/模型**（非 $20）。可分性 87.4% 准确。

### A4. AlpacaEval 2.0 —— reference-based win rate + 长度去偏 ✅ confirmed
805 条指令，候选 vs 固定参考（GPT-4-Turbo）算 win rate。**Length-Controlled (LC) win rate**：对 judge 偏好做逻辑回归，把"输出长度差"当协变量，条件在"长度无差异"上预测，剥离 verbosity bias。
> LC 去偏后与 Chatbot Arena 的 Spearman 从 0.94 升到 **0.98**；跑完 < 3 分钟、< $10。

### A5. Bias 缓解工具箱 ⚠️ partly
叠加在上面方法之上的去偏组合：swap（位置）、length-controlled（冗长）、CoT-forcing（推理）、few-shot（一致性）、多采样投票（方差）。
> **实测数字**：verbosity 攻击（"重复列表"）下 GPT-3.5 / Claude-v1 失败率 **91.3%**，GPT-4 仅 8.7%。self-enhancement：GPT-4 评自己高约 10%、Claude 偏好自己约 25%。
>
> ⚠️ 校验修正：(1) self-enhancement 原论文自陈"数据有限、未能证实"，应标"倾向"而非定论；(2) self-consistency / 多采样投票**不是** MT-Bench 论文方法，属外部叠加，引用时注明出处不同。

---

## B 层 · 任务完成 Benchmark：从"看输出"到"校验终态"

7 个主流 agentic benchmark，按评估范式分三类：静态结构匹配（BFCL/ToolBench）、多轮+状态校验（τ-bench/BFCL V3）、端到端任务完成（SWE-bench/WebArena/GAIA）。**核心趋势：评"环境最终状态/副作用"而非"模型输出文本"。**

### B1. τ-bench（Sierra）—— 工具+用户+策略三方交互 ✅ confirmed
给定初始 DB + 用户意图（LLM user-simulator 逐步透露需求）。agent 在 ReAct 循环里调工具改 DB，遵守 policy 文档。**评估不看对话文本，而是结束后比对 DB 终态 vs 标注 goal state**。
- 创新指标 **pass^k**：同一 task 跑 k 次 i.i.d. 全部成功的概率（区别于 pass@k 的"至少一次"），度量可靠性。

> **具体例子**：airline 域，用户说想改签。agent 须问清订单、识别票种、按 policy（如 basic economy 不可改签）拒绝或执行 `update_reservation`。评估 = 跑完比对 DB 终态。结果：GPT-4o retail pass@1 ~61%、airline ~35%；**retail pass^8 跌破 25%** —— 暴露"偶尔做对"vs"稳定做对"的巨大差距。
> （2026-03 tau-knowledge：领先模型 pass@1 25.5%，但 Pass^4 仅 9.3%。）

### B2. BFCL（Berkeley Function Calling Leaderboard）✅ confirmed
单轮用 **AST 评估**：把模型输出的函数调用解析成抽象语法树，比对函数名、参数名、参数值/类型。另有 Executable（真跑）和 **Relevance Detection**（给无关工具看模型是否克制不调用）。V3 起加多轮 agentic，改 state-based 校验。

> **具体例子（AST）**：prompt="2020 年加州最高税率"，函数 `calculate_tax(income, state, year)`，gold = `calculate_tax(state='CA', year=2020)`。模型若输出 `state='California', year='2020'` → 值不匹配（'California'≠'CA'）+ 类型不匹配（str '2020' ≠ int 2020）判错。
> **Relevance 例**：只给 weather 工具却问数学题 → 模型不该调用任何函数，调用即扣分。

### B3. ToolBench / ToolLLM（OpenBMB, ICLR'24 spotlight）✅ confirmed
16464 个 RapidAPI 真实 API / 3451 tools / 49 类。用 **DFSDT**（深度优先搜索决策树）标注解路径。**ToolEval** 两指标：Pass Rate（限定预算内是否完成，ChatGPT 判）、Win Rate（两条解路径偏好比较，基线 ChatGPT-ReACT）。
> ToolLLaMA+DFSDT 平均 Pass 66.7% / Win 67.3%，远超 Text-Davinci-003（22.6%/16.5%）。

### B4. SWE-bench（Princeton, ICLR'24 oral）✅ confirmed
每实例 = 真实 GitHub issue + 解决它的真实 PR（自带 FAIL_TO_PASS 单测）。**评估完全可执行**：应用模型 patch → 跑测试，要求 FAIL_TO_PASS 全转 PASS 且 PASS_TO_PASS 不回归，才判 resolved。SWE-bench Verified = OpenAI 雇 93 人筛出的 500 题干净子集。
> **具体例子**：django 某 issue。agent 产出 diff patch → 应用后跑 PR 附带回归测试 FAIL→PASS 且全量不挂 → resolved/unresolved 布尔，聚合成 % Resolved。
> ⚠️ 时效：原文举"60%+"偏低，2025 年底 Verified SOTA 已 ~88%（Claude Opus 4.x 级）。

### B5. WebArena（CMU, ICLR'24）✅ confirmed
可自托管真实网站（电商 / 论坛 / **真实 GitLab** / CMS）+ 812 长程任务。**程序化 reward 函数**判功能正确：信息抽取类比对答案字符串，状态改变类查后端 state。
> **具体例子**："在 GitLab 给 repo X 建名为 bug 的 issue 并指派给 Y" → 校验函数查 GitLab 后端确认 issue 存在且 assignee=Y。原论文 GPT-4 agent 仅 **14.41%**，人类 78.24%；2025 新方法（IBM CUGA ~61.7%）已升至 ~60%。

### B6. GAIA（Meta/HF/AutoGPT, ICLR'24）⚠️ partly
466 题，3 级难度，每题唯一答案。用 **quasi exact match**（规整化后精确比对），不需 LLM judge。
> 人类 92% vs GPT-4+plugins 仅 15%，凸显 agent 与人类差距。
> ⚠️ 校验修正：原文"山峰海拔+论文图2"例子是杜撰的，论文真实 Level 2 样例是黄油脂肪含量题（ground truth +4.6）。答案格式不限于单数字，也可是少量词/逗号列表。

### B7. AgentBench（清华, ICLR'24）⚠️ partly
8 个差异化环境（OS / DB-SQL / 知识图谱 / 卡牌 / ALFWorld / WebShop / 浏览 / 谜题），各用环境特定指标，归一化汇总。
> ⚠️ 校验修正：**DB 环境主指标是 success rate，不是 F1**（原文张冠李戴）。

---

## C 层 · 轨迹 / 过程评估：中间步骤对不对

三流派：确定性 trajectory matching（LangChain agentevals）、分解式指标（TRAJECT-Bench）、step/trajectory-level reward 模型（ToolPRMBench / Plan-RewardBench）。gold 轨迹缺失时 fallback 到 LLM-as-judge。

### C1. Trajectory Matching（LangChain agentevals）⚠️ partly
把 agent 输出和参考都格式化成 OpenAI message dict，用 `create_trajectory_match_evaluator(trajectory_match_mode=...)` 比对。四种模式 + 独立的 `tool_args_match_mode`（exact / ignore / subset / superset，可对特定工具传自定义比较函数）。纯规则、零 LLM、确定且便宜。

> **具体例子**：用户问 "weather in SF"，agent 调 `get_weather({city:'SF'})`，参考调 `get_weather({city:'San Francisco'})`。**strict 模式** → `{'score': False}`（'SF'≠'San Francisco' 精确不等）；改 `tool_args_match_mode='ignore'` 只校验工具名 → `True`。
>
> ⚠️ 校验修正（重要，方向曾说反）：**subset = 实际轨迹 ⊆ 参考（确保没调多余工具）；superset = 实际 ⊇ 参考（允许多调）**。"检测有无多余工具"应用 subset（要求实际不超出参考），不是反过来。

### C2. 分解式轨迹指标（TRAJECT-Bench）✅
把轨迹拆成多维：**Exact Match**（工具名序列，不看参数）、**Inclusion**（必需工具覆盖率）、**Tool Usage**（参数 schema/格式/值约束）、**Final Accuracy**。诊断四类失败：相似工具混淆、参数盲选、冗余调用、意图误判。
> Claude-4 在 simple 变体 EM=0.846，harder 变体掉到 0.445 —— 定位弱点在 tool selection 与 parameter inference。

### C3. Step-level Process Reward（ToolPRMBench）✅
把轨迹拆成单步决策点，PRM 在两个候选动作里选对的那个（二元判别）。错误类型：选错工具 / 参数错 / 该调工具却用自然语言回复 / 违反状态约束。
> **具体例子**：要把文件复制到本地目录。Rejected = 直接用绝对路径 `cp`（违反"源和目的须在当前工作目录内"约束）；Chosen = 先 `cd` 再复制。PRM 须指向 Chosen。

### C4. τ-bench pass^k（可靠性）
见 B1 —— 用结果状态匹配 + pass^k 把"是否**可靠地**调对工具/改对状态"量化，是轨迹评估里"一致性"维度的来源。

---

## D 层 · 生产 / 在线评估：上线后闭环

核心是"在真实流量上闭环"。**guardrail（每请求都跑、要快/确定、产生 block/allow）和 eval（批量/抽样诊断 drift）是两个不同执行层。**

### D1. 用户显式反馈（thumbs / 星级）
前端每条消息挂 thumbs，点击后把 score 绑到 trace_id（Langfuse/LangSmith 支持 NUMERIC/CATEGORICAL/BOOLEAN）。低分 trace flag 进 review 或回灌离线 dataset。**稀疏信号**（<5% 用户点），需配隐式信号。

### D2. 隐式反馈（retry / 放弃 / 追问率）
> **具体例子**：用户连发 "特斯拉财报怎么样" → "我是说最新一季毛利率" → 关闭会话。规则引擎判第二条为 retry（意图改写）、session 以 abandonment 收尾 → dashboard 显示"估值类 retry 率 18% vs 资讯类 6%"，定位短板。覆盖全量、无需用户配合，但有噪声。

### D3. 在线 LLM-as-judge（按采样率打分）⚠️ partly
配 evaluator：过滤条件 + 采样率（如 10-15% 控成本），把生产 trace 的 input/output/context 填进 judge prompt，score 写回 trace。失败 trace 自动入离线 dataset 成闭环。
> **具体例子**：Arize Phoenix HallucinationEvaluator，输入三元组（问题、AI 回答、检索到的研报片段），judge 问"答案是否仅基于 reference、有无编造" → label ∈ {factual, hallucinated}。某条虚构了营收数字 → hallucinated，标红回灌。

### D4. 实时 Guardrail / 幻觉拦截（每请求 block/allow）
pre-LLM 拦越界 query（要快/确定，用规则/小分类器）；post-LLM 比对输出 claims 与检索 context，拦未 grounded 的幻觉。可用 RAGTruth 微调小模型做低延迟检测。
> **具体例子**：用户问目标价，LLM 生成上下文里没有的 "$420" → groundedness guardrail 实时比对判 hallucinated → block，替换为"依据现有资料无法给出"。

### D5. 线上 A/B（业务指标判定）⚠️ partly
control vs treatment 随机分流，主指标（留存/会话长度/成功率）+ guardrail 指标（latency/error），power analysis 定样本量 + t-test/chi-square 判显著。
> ⚠️ **代理指标陷阱**：单纯优化"留存/会话长度"可能让模型学会"黏住"而非"帮到"用户，需任务成功率兜底。

### D6. 回归 eval：golden set + cassette ⚠️ partly
两条腿：(1) **golden set**——从失败 trace 沉淀 (input, 期望判定)，CI 跑（RAGTruth 18k 条带 word-level 幻觉标注，可微调小模型逼近 GPT-4）；(2) **cassette**——录制一次真实 LLM/工具调用响应到磁盘，CI 回放不真打 API，保证确定性、零成本、无网络可测。
> **具体例子**：把"估值 agent 对某 input 的工具调用序列"录成 cassette，CI 回放断言序列不变；序列变了 → CI 红灯阻止 regression。

---

## E 专题 · RAG / 检索增强对话的评估

两个轴：**retrieval 质量**（context precision/recall）与 **generation 质量**（faithfulness/groundedness、answer relevance）。

| 指标 | 测什么 | 例子 |
|---|---|---|
| **RAGAS Faithfulness** ✅ | 答案每个 claim 能否由 context 推断（NLI），分数=被支持claim数/总claim数 | Context 写 "born 14 March 1879"，答案说 "20th March 1879" → claim 出生德国✓、3月20日✗ → **faithfulness=1/2=0.5** |
| **RAGAS Answer Relevancy** ✅ | 答案是否切题（不评对错）。反向生成：从答案反推 N 个问题，与原问题算 cosine 均值 | 答案漏掉首都 → 反推问题覆盖不全 → 分数下降 |
| **Context Precision/Recall** ✅ | 检索端：相关 chunk 是否排前 / 是否覆盖全 | 相关 chunk 排第一 → Precision≈1.0；排第二 → ≈0.5 |
| **TruLens RAG Triad** ✅ | Context Relevance + Groundedness + Answer Relevance 三维定位故障在检索还是生成 | Groundedness=0.6 → 约 40% 断言找不到支持 = 幻觉风险 |
| **ALCE Citation Precision/Recall** ✅ | 行内 [1][2] 引用是否真支持其断言（NLI 逐句核对） | 句子引 [3][5]，[5] 移除后仍被支持 → [5] 计 precision 失分 |
| **FACTS Grounding / FaithJudge** ⚠️ | 用人工标注幻觉当 ground truth，反过来评 judge 本身准不准；多 judge 集成降噪、few-shot 锚定 | 30k token 财报 + "总结营收驱动" → 两阶段 judge（是否答了请求 + 是否全 grounded）→ factuality 分 |

结论：LLM judge 仍是当前最佳但远不完美，金融数字幻觉代价高，需 few-shot 锚定 + 多 judge 集成。

---

## F · 贴合本项目（chat + MCP + LangGraph supervisor）的落地建议

按"个人作品 / aggressive minimalism"定位，**优先级从高到低**：

1. **【最低成本最高收益】** 现有 chat eval（端到端 LLM-judge）加两项：
   - **pass^k 重复采样**（同一 golden case 跑 k 次看 Pass^k），守护 supervisor 路由 + 工具调用一致性 —— 直接呼应已有 differential golden / DD report V0-V3 ablation。
   - **工具调用 state 断言**（τ-bench 思路）：给每个 golden case 标注"对话结束后期望的 DB/工具副作用终态"，评终态而非对话文本。

2. **轨迹层接 LangChain agentevals**（轨迹天然是 LangGraph message+tool_call 序列）：
   - `forced_tool` / slash command 必须命中某工具 → **strict/superset** 确定性回归（呼应当前 `feat/chat-command-system` 分支）。
   - "agent 是否多调了 memory/kb 工具" → **subset 模式**量化多余步骤（呼应 memory vs kb routing）。
   - 加一维 **BFCL Relevance/拒绝**：给不该触发工具的 query，考核 supervisor 是否克制不乱调用。

3. **RAG/KB 离线指标**（补 `kb-eval-gaps` 卡缺口）：RAGAS retrieval 轴（context precision/recall）+ generation 轴（faithfulness）上 CI，无需大量人工标注。金融零容忍幻觉 → 优先 Faithfulness（claim 级）+ ALCE 式引用核对，复用 c5 Plan 4 已有的 evidence_quote 校验。

4. **生产在线（低成本先行）**：前端 thumbs → Langfuse BOOLEAN score 绑 trace_id（几乎零成本拿金标）；session 级埋 retry/abandonment 隐式信号按 use case 分桶；RAG 链路把 groundedness 做 post-LLM guardrail（小模型保延迟）。**A/B 因个人作品流量不足，建议"架构留口子"而非现在实装。**

5. **judge 去偏纪律**：金融报告易长 → 内建 position 双跑 + verbosity 去偏；警惕"judge 与被评 agent 同模型"的 self-enhancement bias，考虑换不同家模型当 judge。

---

## 附 · 关联项目知识卡

- `kb-eval-gaps.md` —— 现有 eval 缺 chunking/embedding/检索离线指标，本研报 E 节 + F.3 是补口位置。
- `c5-plan4-mcp-tools-done.md` —— evidence_quote 校验机制，可复用做 ALCE 式引用核对。
- `dd-report-eval-phase-2-landed.md` —— V0-V3 ablation，对应 F.1 的 pass^k / pairwise。
- `chat-session-persistence-done.md` —— DB-as-truth，对应 D 节 trace 级在线评估。
