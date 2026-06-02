# 对话 / 工具型 Agent 评估方法论（外部调研沉淀）

## 结论

评估对话 / agent **不是单一指标，而是四层正交体系**，评估时按需取层：

- **A 输出质量** — LLM-as-judge：G-Eval（rubric+CoT+概率加权 `Σp(sᵢ)·sᵢ`）、MT-Bench（1-10 绝对分 + reference-guided）、AlpacaEval 2.0（reference-based win rate + 长度去偏 LC）、Arena-Hard（pairwise + swap 去 position bias）。
- **B 任务完成** — τ-bench（**DB 终态匹配 + pass^k**）、BFCL（AST 参数比对 + Relevance 拒绝）、SWE-bench（FAIL→PASS 可执行单测）、WebArena（程序化 reward 查后端 state）、GAIA（quasi exact match）。
- **C 过程/轨迹** — LangChain agentevals 确定性 trajectory matching（strict/subset/superset + tool_args exact/ignore）、TRAJECT-Bench 分解式（工具名 EM / 参数 / 冗余）、step-level PRM。
- **D 生产/在线** — 用户 thumbs（稀疏）+ 隐式信号（retry/放弃率）+ 在线 judge（采样打分）+ guardrail（每请求 block/allow）+ A/B + cassette/golden 回归。
- **E RAG 专题** — RAGAS（faithfulness=被支持claim/总claim、answer relevancy、context precision/recall）、TruLens RAG triad、ALCE 引用核对。

两条暗线：**①LLM-judge 偏差（position/verbosity/self-enhancement）必须去偏；②趋势是"校验环境终态副作用"而非"匹配输出文本"，用 pass^k（连 k 次都成功）取代单次 accuracy 度量可靠性。**

## Why

项目现有 chat eval 是端到端 LLM-judge，`kb-eval-gaps` 卡已承认缺 component-level / 检索离线指标。这套四层体系给出了**可分层补口、且大多无需大量人工标注**的成熟方法，是把"个人作品"eval 做出技术深度的弹药库。校验过 22 条事实，无完全错误项（partly 多为数字微调），可放心引用。

## How to apply

按 aggressive minimalism 优先级落地（详见研报 F 节）：
1. 现有 eval 加 **pass^k 重复采样 + 工具调用终态断言**（最低成本最高收益，呼应 differential golden / DD V0-V3）。
2. 轨迹层接 **LangChain agentevals**：`forced_tool`/slash command 用 strict/superset 确定性回归（当前 `feat/chat-command-system` 分支）；"是否多调 memory/kb 工具"用 **subset 模式**（subset=实际⊆参考=不许多余；superset=允许多调，别说反）。
3. KB 离线指标用 **RAGAS** 补 `kb-eval-gaps` 缺口；金融零容忍幻觉 → faithfulness + ALCE 引用核对，复用 [[c5-plan4-mcp-tools-done]] 的 evidence_quote。
4. 前端 thumbs → Langfuse score 绑 trace_id（几乎零成本）；A/B 因流量不足只"留口子"。

完整研报（6 维方法 + 每法具体例子 + 来源 + 22 条校验）：`docs/research/2026-06-02-conversational-agent-evaluation-survey.md`。关联 [[kb-eval-gaps]] [[dd-report-eval-phase-2-landed]]。
