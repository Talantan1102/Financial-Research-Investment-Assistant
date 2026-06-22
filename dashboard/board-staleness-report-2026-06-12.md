<!-- 自动生成:board-staleness-reconcile workflow / 2026-06-12 / 扫 #126-#157 共 24 PR / 85 agents / 52 条已对抗验证发现。逐条审完手改,改完跑 `make board-refresh`。 -->

# 研发看板过期核对 & 补全报告(近一周 #126-#157)

## 1. 一句话总览

近一周 chat 模式从「LangGraph supervisor 单程图」整体重设计成「裸 Python while 工具调用循环」(`backend/app/chatloop/`,PR #127 + #135/#136/#139/#141/#143-#157 一连串),外加跨会话记忆接通(#151)、可观测补齐(#152/#155)、对话评估体系(#135)、auth 接真 JWT(#156),导致看板 **52 条**(去重后 **51 条**,见下)git-tracked 真源出现过期或缺口:14 条 `manual` 应翻「已实现」、12 条缺新能力卡、9 处过期数字、9 处描述已退役架构、2 处名称漂移、2 篇研报未接入维度页。其中 **14 条 manual→lit 改完 `make board-refresh` 即自动从「未开发」翻「已实现」**,零额外手工。

> 去重说明:`observability.trace_service`(第 46 行 code_anchor 漂移)与 `observability` 维度其余条目分属不同 target,不合并;`tool.code_interpreter` 与 `execution.code_interpreter` 是两个不同维度的独立新 cap(同一 run_python 工具在 tool 维和 execution 维各立一条),按原始 52 条保留。下文 **51 条** = 52 条原始发现中,`context.skills_bundle` 的 capabilities.yaml 数字(label_drift)与 deep_cards_seed.jsonl 叙事(stale_arch)是同卡两文件、不合并,故仍为 52 条逐条;此处「51」为笔误修正——**全部 52 条均逐条列出**。

### 摘要表 A:按 file_to_edit 分组

| 目标文件 | 条数 | 说明 |
|---|---|---|
| `dashboard/config/capabilities.yaml` | 31 | derive_rule 翻 lit / 新增 cap / 数字订正 |
| `dashboard/data/deep_cards_seed.jsonl` | 16 | 新增 DeepCard / 修过期叙事与 code_anchor |
| `dashboard/server.py` | 3 | 接入研报 + 入口文案订正(其中 1 条实际改 eval.html 模板) |
| `dashboard/config/dimensions.yaml` | 1 | lifecycle paths 加 `backend/app/chatloop/**` |
| `dashboard/templates/eval.html` | (1,计入 server.py 那 3 条之一) | /eval 深度报告区入口 |

> 注:有 8 条 missing_cap 同时落 `capabilities.yaml`(新 cap 块)+ `deep_cards_seed.jsonl`(新 DeepCard);上表按 finding 的主 `file_to_edit` 计,实际两文件都要改。

### 摘要表 B:按性质(kind)分组

| 性质 | 条数 | 占比要点 |
|---|---|---|
| manual 应翻「已实现」(manual_now_lit) | 14 | 改完刷新即自动翻牌,最高性价比 |
| 缺新能力(missing_cap) | 12 | chatloop / 子 agent / 代码解释器 / 评估簇等本周工程深度无处安放 |
| 已退役架构叙事(stale_arch) | 9 | chat supervisor 退役 / checkpoint 退役 / auth 反转 + code_anchor 漂移 |
| 过期数字(stale_count + label_drift 数字类) | 11 | 维度头注释项数 / 「8/12+/289+/17-component」等写死数字 |
| 名称漂移(label_drift 措辞类) | 4 | path_glob 指错目录 / 「chat 子图循环」措辞 / dimensions paths |
| 研报未接入(unwired_report) | 2 | chatloop-runtime-optimization / chatloop-eval-scorecard 入口缺失 |

(kind 合计 52;部分 finding 跨 kind,按主性质归类。)

---

## 2. 按文件分章

### 2.1 `dashboard/config/capabilities.yaml`

#### 【high】沙箱抽象层 — manual 应翻「已实现」(execution.sandbox_abstraction)

- **现状**:第 52-55 行 `id: sandbox_abstraction`,`derive_rule: { type: manual }`,看板顽固显示「未开发」。
- **应改成**:PR #143 真落地了沙箱执行后端抽象层(`ExecutorBackend` Protocol + `SkillExecutorBackend` 实现,Docker 后端留 v1.x 口),与 cap 名「沙箱抽象层」精确对应。改成命中真实代码的 code_grep,刷新即翻 lit。
- **证据**:#143;`backend/app/skills/executor_backend.py:16`(`class ExecutorBackend(Protocol)`)、`:24`(`class SkillExecutorBackend`);`backend/app/chatloop/code_interpreter_tool.py:20,49` 依赖该 Protocol。验证者实测 grep 命中 line 16,resolver 返回 lit;首次出现于 commit `0ef9799`(#143)。
- **可直接落地的改动**:把第 55 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: 'class ExecutorBackend\(Protocol\)', path_glob: 'backend/app/skills/executor_backend.py' }
```
- **置信度**:high。

#### 【high】并行 tool calls — manual 应翻「已实现」(tool.parallel_tool_calls)

- **现状**:第 95-98 行 `id: parallel_tool_calls`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:裸 while 循环的 ToolHub 已真用 `asyncio.gather` 并行分发单步多工具(#127),子 agent 扇出(#144)亦用 gather。改 code_grep 命中 `tool_hub.py`。
- **证据**:#127、#144;`backend/app/chatloop/tool_hub.py:232`(`await asyncio.gather(*(self._dispatch_one(call, state) for call in calls))`)、`subagent.py:220`。验证者实跑 resolver → lit。
- **可直接落地的改动**:把第 98 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: 'asyncio\.gather', path_glob: 'backend/app/chatloop/tool_hub.py' }
```
- **置信度**:high。

#### 【high】8→11 个金融工具 — 写死数字过期(tool.financial_tools)

- **现状**:第 83-86 行 `name_cn: "8 个金融工具"` / `name_en: "8 financial tools"`,但 derive_rule 的 glob `backend/app/tools/get_*.py` 实际命中 11 个 `class X(Tool)`。
- **应改成**:数字改 11,与 derive_rule 命中数和 DeepCard(第 7 行已写 11)对齐。derive_rule 状态不变(已 lit)。
- **证据**:#146;glob 实测 11 文件(get_balance_sheet/cashflow/daily_basic/dividend_history/financials/forecast/holder_change/money_flow/news/pe_history/stock_quote),逐文件确认各含 `class X(Tool)`;`get_daily` 在 `mcp_server/tools/` 不在此 glob,正确排除。
- **可直接落地的改动**:把第 83-86 行替换为
```yaml
      - id: financial_tools
        name_cn: "11 个金融工具"
        name_en: "11 financial tools"
        derive_rule: { type: code_grep, pattern: 'class\s+\w+\(Tool\)', path_glob: 'backend/app/tools/get_*.py' }
```
- **置信度**:high。

#### 【high】上下文压缩 — manual 应翻「已实现」(context.ctx_compression)

- **现状**:第 162-166 行 `id: ctx_compression`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:裸 while 循环已落地两条压缩算法(老圈大工具消息降级为 ref+digest 的 `_downgrade_old_tool_messages`,以及「上下文压力安全阀」逐级收紧阈值)。改 code_grep 命中 `chatloop/context.py`。
- **证据**:#127、#155;`backend/app/chatloop/context.py:127`(`_downgrade_old_tool_messages`)、`:77`(`max_context_tokens`)、`:235`(安全阀);`state.py:160-161`(记账字段)。验证者实跑 resolver → lit,称「本维度最强、最确定的翻牌」。
- **可直接落地的改动**:把第 166 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: '_downgrade_old_tool_messages|max_context_tokens', path_glob: 'backend/app/chatloop/context.py' }
```
- **置信度**:high。

#### 【high】情景记忆 — manual 应翻「已实现」(context.episodic_memory)

- **现状**:第 183-187 行 `id: episodic_memory`,`derive_rule: { type: manual }`,而第 18 行 DeepCard 已详写该能力。
- **应改成**:#151 把 `write_episode` 从死代码接进 live chat(`run_chat_async` 收尾经 `persist_episode_and_trigger` 调 `write_episode` 落 per-turn episode)。改 code_grep 命中 `chat_memory_hook.py`。
- **证据**:#151、#141;`backend/app/tasks/chat_memory_hook.py:51`(`persist_episode_and_trigger`)、`:77`(`next_episode_index`);触发自 `chat_runner.py:349`。验证者确认此前 `write_episode` 零生产调用,刚接通。
- **可直接落地的改动**:把第 187 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: 'persist_episode_and_trigger|next_episode_index', path_glob: 'backend/app/tasks/chat_memory_hook.py' }
```
- **置信度**:high。

#### 【high】长期记忆 — manual 应翻「已实现」(context.long_term_memory)

- **现状**:第 168-172 行 `id: long_term_memory`,`derive_rule: { type: manual }`,而第 16 行 DeepCard 已写 C.5 MemGPT+Zep 杂交。
- **应改成**:#151 把长期记忆写入触发(`extract_session_episodes_async` 新增 `'post_turn'` 档)接进每轮 fire-and-forget;HierarchicalMemory 本就 ship。改 code_grep。注:anonymous 守卫下 pre-auth 真实落库仍休眠,但代码路径已存在。
- **证据**:#151、#141、#139;`chat_memory_hook.py:30`、`tasks/memory.py:36-38`(合法 trigger 含 `'post_turn'`)、`hierarchical.py:693`(`write_episode`)。验证者实跑 recursive glob → lit。
- **可直接落地的改动**:把第 172 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: 'persist_episode_and_trigger|extract_session_episodes_async', path_glob: 'backend/app/tasks/**' }
```
- **置信度**:high。

#### 【high】Skills bundle 数字 17→13 — 名称漂移(context.skills_bundle)

- **现状**:第 134 行 `name_cn: "Skills bundle (17-component)"`。
- **应改成**:#136 把 financial_research skill 从 17 件砍到 13(删 2 rules.yaml + 2 scripts:classify_recommendation/compute_position_size)。SKILL.md 现 `component_count: 13`。只改显示数字,derive_rule(file_exists)状态不变。
- **证据**:#136;`SKILL.md:14`(`component_count: 13`)、`:28`、`:55`;git `2e8e086` 删两脚本两 rules。被删脚本只剩 `__pycache__` 里陈旧 `.pyc`。
- **可直接落地的改动**:把第 134 行替换为
```yaml
        name_cn: "Skills bundle (13-component)"
```
(name_en 无数字,不动。)
- **置信度**:high。

#### 【high】Human-in-the-loop — manual 应翻「已实现」(lifecycle.human_in_the_loop)

- **现状**:第 284-287 行 `id: human_in_the_loop`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:chatloop 已有真实人在环路插话/转向(steering):圈首 pop_all + 工具分发前两点并入,改方向型插话立取消整批工具。改 code_grep。
- **证据**:#127、#150;`loop.py:159,161`(pop_all + steer_merged)、`:241-250`(分发前检查点)、`:390`(`_steer_interrupted_result`);`worker_wiring.py:266,277`。验证者用 venv python 实跑 resolver → lit。
- **可直接落地的改动**:把第 287 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: 'steer_merged|_steer_interrupted_result', path_glob: 'backend/app/chatloop/**' }
```
(用 `_steer_interrupted_result` 而非泛词 `pop_all`,避免误命中。)
- **置信度**:high。

#### 【high】Agent handoff — manual 应翻「已实现」(lifecycle.agent_handoff)

- **现状**:第 288-291 行 `id: agent_handoff`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:#144 落地子 agent 派发/交接原语 `dispatch_subagents`(`SubagentFactory.spawn_one` 起独立子 ToolLoop 并发跑只读子任务)。改 code_grep 命中 `subagent.py`。
- **证据**:#144;`subagent.py:100`(`class SubagentFactory`)、`:129`(`spawn_one`)、`:265`(`DispatchSubagentsTool`);`worker_wiring.py:36,246`;git `9291ff5`。验证者实跑 → lit。
- **可直接落地的改动**:把第 291 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: 'class SubagentFactory|def spawn_one', path_glob: 'backend/app/chatloop/subagent.py' }
```
- **置信度**:high。

#### 【high】LangGraph 骨架 path_glob 指错目录 — 名称漂移(lifecycle.langgraph_skeleton)

- **现状**:第 252-255 行 `derive_rule: { type: code_grep, pattern: 'StateGraph', path_glob: 'backend/app/agents/**' }`。
- **应改成**:#127 删了 `agents/` 下所有含 StateGraph 的源(chat_graph/chat_agent)。现在 StateGraph 仅在 `orchestration/research_graph.py` 与 `critic_subgraph.py`(research 图仍有效)。当前规则只靠残留 `__pycache__/chat_agent.cpython-312.pyc` 侥幸命中,**clean checkout 后会从 lit 误翻 todo**。path_glob 改到 `orchestration/**`。
- **证据**:#127;验证者用 venv python 复刻 resolver:`agents/**` 仅脏 .pyc 命中、git grep 源码 0 命中;`orchestration/**` 命中 2 个真 .py 源(research_graph + critic_subgraph),clean checkout 也稳。
- **可直接落地的改动**:把第 255 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: 'StateGraph', path_glob: 'backend/app/orchestration/**' }
```
- **置信度**:high。

#### 【high】p95 latency 监控 — manual 应翻「已实现」(observability.latency_p95)

- **现状**:第 307-310 行 `id: latency_p95`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:#152 chatloop 工具聚合 SQL 用 `percentile_cont(0.95)` 算每工具 p95,看板模板按 p95 画排行。改 code_grep 命中 `trace_analytics.py`。
- **证据**:#152;`backend/app/services/trace_analytics.py:23`(`percentile_cont(0.95) ... AS p95_ms`)、`:78`、`:125`;模板 `chatloop_observability.html:40,49`。验证者实测 → lit。
- **可直接落地的改动**:把第 307-310 行替换为
```yaml
      - id: latency_p95
        name_cn: "p95 latency 监控"
        name_en: "p95 latency monitoring"
        derive_rule: { type: code_grep, pattern: 'percentile_cont|p95_ms', path_glob: 'backend/app/services/trace_analytics.py' }
```
- **置信度**:high。

#### 【high】跨系统统一可观测 — manual 应翻「已实现」(observability.unified_observability)

- **现状**:第 340-343 行 `id: unified_observability`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:#152 把工具 span(`name LIKE 'tool:%'`)与 LLM span(`name='LLMService.stream_step'`)用同一 request_id 落同张 trace_spans 表,再用聚合 SQL 跨两类 span 同表关联——这就是跨系统 trace 关联。改 code_grep。
- **证据**:#152;`trace_analytics.py:40,61`(同表同查两类 span);工具 span 由 `tool_hub.py:274` 写、同 request_id(`:272`),LLM span 由 `llm_service.py:226`。验证者实测 → lit。
- **可直接落地的改动**:把第 340-343 行替换为
```yaml
      - id: unified_observability
        name_cn: "跨系统统一可观测"
        name_en: "Unified observability"
        derive_rule: { type: code_grep, pattern: 'LLMService\.stream_step', path_glob: 'backend/app/services/trace_analytics.py' }
```
- **置信度**:high。

#### 【high】对抗测试 — manual 应翻「已实现」(verification.adversarial_test)

- **现状**:第 379-382 行 `id: adversarial_test`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:#135 chatloop 评估 `scenarios.jsonl` 有 9 条 `difficulty=对抗` 场景(注入/越权/方向性诱导)。改 code_grep 命中。
- **证据**:#135;`backend/eval/chatloop/golden/scenarios.jsonl` 实测 9 条 `"difficulty": "对抗"`(cl-018~030 等);git `78d86b7`。验证者实跑 → lit。
- **可直接落地的改动**:把第 382 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: '"difficulty":\s*"对抗"', path_glob: 'backend/eval/chatloop/golden/*.jsonl' }
```
- **置信度**:high。

#### 【high】A/B testing — manual 应翻「已实现」(verification.ab_testing)

- **现状**:第 375-378 行 `id: ab_testing`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:#135 chatloop SUT runner 支持传 `system_prompt` 覆盖做提示词 A/B 消融,落库 `system_prompt_sha` 区分两组。改 code_grep。
- **证据**:#135;`sut_runner.py:48`(`system_prompt` 形参,`:52` 注释「prompt 消融」)、`run_eval.py:87`(`system_prompt_sha`)。验证者实跑 → lit,命中 4 文件。
- **可直接落地的改动**:把第 378 行替换为
```yaml
        derive_rule: { type: code_grep, pattern: 'prompt 消融|system_prompt_sha|system_prompt:\s*str\s*\|\s*None', path_glob: 'backend/eval/chatloop/*.py' }
```
- **置信度**:high。

#### 【high】失败溯因 — manual 应翻「已实现」(verification.failure_attribution)

- **现状**:第 389-392 行 `id: failure_attribution`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:#135 chatloop 首跑把 26 个失败 case 归因到「过度路由 memory_search」单一根因,用 per-case pass^k 双峰证明系统性。改 file_exists 命中归因报告(或 code_grep 命中 passk.py)。
- **证据**:#135;`backend/eval/chatloop/RESULTS-2026-06-08.md`(14801B,归因报告)、`passk.py:20`(`def pass_power_k`);git `78d86b7`。验证者两种 rule 都实测 → lit。
- **可直接落地的改动**:把第 392 行替换为
```yaml
        derive_rule: { type: file_exists, path: 'backend/eval/chatloop/RESULTS-2026-06-08.md' }
```
- **置信度**:high。

#### 【high】审计基础设施 — manual 应翻「已实现」(governance.audit_infrastructure)

- **现状**:第 434-437 行 `id: audit_infrastructure`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:#144 落地首个项目自有不可变审计表 `subagent_dispatch_runs` + `SubagentAuditRepo.record_batch` best-effort 落库。改 code_grep。
- **证据**:#144;`backend/app/models/subagent_dispatch.py:17`(`__tablename__ = "subagent_dispatch_runs"`)、`subagent_audit.py:33`(`record_batch`);worker_wiring.py:234 实例化、subagent.py:239 调用(非死代码);git `9291ff5`。验证者实测 → lit。
- **可直接落地的改动**:把第 434-437 行替换为
```yaml
      - id: audit_infrastructure
        name_cn: "审计基础设施"
        name_en: "Audit infrastructure"
        derive_rule: { type: code_grep, pattern: 'subagent_dispatch_runs', path_glob: 'backend/app/models/*.py' }
```
- **置信度**:high。(本条配套需补一张 DeepCard,见 §2.2 对应条。)

#### 【medium】幻觉检测 — manual 应翻「已实现」(governance.hallucination_check)

- **现状**:第 419-422 行 `id: hallucination_check`,`derive_rule: { type: manual }`(注:第 27 行 DeepCard 写的是 prefill quote 校验,与生产合规检测两码事,cap 三色仍 todo)。
- **应改成**:#135 为裸 while 循环落地合规/幻觉校验:免责合规 scorer + 方向性建议违例 scorer + system_prompt「合规底线」禁词段。改 code_grep 命中 eval scorers。证据偏评估侧(非生产实时拦截),故 medium。
- **证据**:#135;`scorers.py:106`(`score_disclaimer`)、`:111`(`score_advice`)、`:98`(`advice_violation`);`system_prompt.py:40-44`(合规底线);git `78d86b7`。验证者实测 → lit。
- **可直接落地的改动**:把第 419-422 行替换为
```yaml
      - id: hallucination_check
        name_cn: "幻觉检测"
        name_en: "Hallucination check"
        derive_rule: { type: code_grep, pattern: 'def score_disclaimer|def score_advice', path_glob: 'backend/eval/chatloop/*.py' }
```
- **置信度**:medium。

#### 【medium】Capability-Control 授权 gate — manual 应翻「已实现」(governance.capability_control_gate)

- **现状**:第 444-447 行 `id: capability_control_gate`,`derive_rule: { type: manual }`,显示「未开发」。
- **应改成**:#144 的 `dispatch_subagents` 落地 per-action 授权 gate:子循环只能用受限只读白名单 `READONLY_SUBAGENT_TOOLS`(不含 offer_deep_research/dispatch_subagents,禁串门禁递归),`register_subset` 收窄子 hub。改 code_grep。证据真实但偏「最小工具权限」语义,故 medium。
- **证据**:#144;`subagent.py:34`(白名单)、`:96`(`hub.register_subset`)、`tool_hub.py:109`(`def register_subset`);git `9291ff5`。验证者实测 → lit。
- **可直接落地的改动**:把第 444-447 行替换为
```yaml
      - id: capability_control_gate
        name_cn: "Capability-Control 授权 gate"
        name_en: "Capability-control gate"
        derive_rule: { type: code_grep, pattern: 'READONLY_SUBAGENT_TOOLS', path_glob: 'backend/app/chatloop/subagent.py' }
```
- **置信度**:medium。

---

以下为 **新增 cap(missing_cap)** —— capabilities.yaml 加 cap 块 + deep_cards_seed.jsonl 加 DeepCard 行,逐条给两段落地代码。

#### 【high】代码解释器 run_python(execution 维)— 缺新能力(NEW: execution.code_interpreter)

- **现状**:capabilities.yaml + dimensions.yaml 全文搜 plotly/run_python/代码解释 零命中。#143 run_python 代码解释器 + #146 自动画图捕获 harness 无处安放。
- **应改成**:execution 维新增一条,derive_rule 命中 `CodeInterpreterTool`。配 DeepCard 写清三决策(复用 SkillExecutor 沙箱 / ExecutorBackend 留 Docker 口 / figures 旁路不进上下文)。
- **证据**:#143、#146、#147;`code_interpreter_tool.py:44-45`(`class CodeInterpreterTool` / `name = "run_python"`)、`skill_executor.py:223`(`execute_source`)、`skill_safety.py:11`、`tool_docs.py:443`、`worker_wiring.py:245`。验证者实跑 → lit。
- **可直接落地的改动**:
  (a) capabilities.yaml — 在 execution 维末尾(`sandbox_escape_defense` 之后,第 60 行后)追加:
```yaml
      # 论文 §3.2.x - 沙箱化代码解释器 (run_python: LLM 写 Python → SkillExecutor 沙箱执行)
      - id: code_interpreter
        name_cn: "代码解释器 (run_python)"
        name_en: "Code interpreter (run_python)"
        derive_rule: { type: code_grep, pattern: 'name = "run_python"', path_glob: 'backend/app/chatloop/code_interpreter_tool.py' }
```
  同时把第 9 行头注释改为 `# 01 Execution Environment & Sandbox (12 项,预期 8 lit) §3`(基线 11 + 本条 = 12)。
  (b) deep_cards_seed.jsonl — 追加一行 DeepCard,其 `linked_specs` 用**真实存在**的 spec(原 finding 猜测文件名不存在):
```json
{"cap_id": "execution.code_interpreter", "what": "对外工具 run_python:LLM 当场写完整 Python 脚本,经复用的 SkillExecutor 沙箱(subprocess + rlimit + AST 黑名单 + 断网,execute_source 内联入口)执行,plotly 产交互图;figures 在 ToolLoop dispatch→apply_results 间被剥离(绝不进 LLM 上下文),旁路走 chart SSE 事件渲染前端。沙箱底座抽象成 ExecutorBackend Protocol(SkillExecutorBackend 当前实现,DockerExecutorBackend 留 v1.x 口)。", "why": "金融分析常需二次数值计算与自定义可视化,固化成 N 个画图工具既穷举不完又僵硬;让 LLM 写 Python 当场算/画,沙箱保证安全,plotly 产交互图,既灵活又可控。", "alternatives": [{"name": "固化 N 个画图工具", "brief_tradeoff": "穷举不完,新图型要改代码"}, {"name": "LLM 写 Python 进沙箱执行", "brief_tradeoff": "灵活但要把好沙箱安全闸"}, {"name": "直接 eval 不隔离", "brief_tradeoff": "任意代码执行,安全灾难"}], "chosen_alternative": "LLM 写 Python 进沙箱执行", "tradeoff": "复用既有 SkillExecutor 沙箱零新增隔离面;figures 旁路 chart 事件不进上下文,省 token 又能渲染交互图;代价是模型偶尔写错代码,靠 while 循环天然自纠(stderr 截 500 字回喂)。沙箱黑名单补封 os.popen/os.fdopen。", "lessons_learned": "plotly 必须用 dist-min/factory 避 mapbox 重依赖;沙箱内 OpenBLAS 须设单线程避 OOM;figures 一旦进 LLM 上下文会瞬间炸窗,务必在 dispatch→apply 之间剥离。", "metrics": {}, "code_anchors": [{"file": "backend/app/chatloop/code_interpreter_tool.py", "line": 45, "note": "name = \"run_python\" — InProcessTool,run_with_state 调 backend.run_code"}, {"file": "backend/app/chatloop/worker_wiring.py", "line": 245, "note": "CodeInterpreterTool(backend=SkillExecutorBackend(...)) 注册进 chatloop ToolHub"}, {"file": "backend/app/skills/executor_backend.py", "line": 1, "note": "ExecutorBackend Protocol — 沙箱底座抽象,SkillExecutorBackend 实现"}], "linked_specs": ["docs/superpowers/specs/2026-06-11-code-interpreter-tool-design.md", "docs/superpowers/specs/2026-06-11-charting-skill-and-harness-design.md"], "linked_capabilities": ["tool.parallel_tool_calls"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high(adjusted:linked_specs 已从不存在的 `2026-06-11-code-interpreter-run-python-design.md` 改为真实存在的 `2026-06-11-code-interpreter-tool-design.md`)。

#### 【high】代码解释器 run_python(tool 维)— 缺新能力(NEW: tool.code_interpreter)

- **现状**:tool 维 11 条 cap 无一覆盖「代码解释器 / LLM 当场写可执行代码 / 交互图生成」。
- **应改成**:tool 维新增一条(与上条 execution.code_interpreter 是不同维度的两条独立 cap,run_python 既是「执行环境」也是「工具」)。
- **证据**:#143、#146;`code_interpreter_tool.py:45`、`worker_wiring.py:245`、`tool_docs.py:363`。验证者实测 file_exists/code_grep 均 → lit,JSON 经 ConvertFrom-Json 校验通过。
- **可直接落地的改动**:
  (a) capabilities.yaml — 在 tool 维末尾(`chat_slash_command` 之后,第 113 行后)追加:
```yaml
      - id: code_interpreter
        name_cn: "代码解释器 (run_python)"
        name_en: "Code interpreter (run_python)"
        derive_rule: { type: file_exists, path: 'backend/app/chatloop/code_interpreter_tool.py' }
```
  (b) deep_cards_seed.jsonl — 追加一行(`cap_id: tool.code_interpreter`,内容同上 execution 卡可复用一份独立叙事;按 finding 原文):
```json
{"cap_id": "tool.code_interpreter", "what": "对外工具 run_python:LLM 当场写完整 Python 脚本,经复用的 SkillExecutor 沙箱(subprocess + rlimit + AST 黑名单 + 断网)执行,把图赋给 fig/figures、结论赋给 result,执行器自动序列化 + 套统一 plotly 主题。figures 在 ToolLoop 的 dispatch→apply_results 之间被剥离(绝不进 LLM 上下文),旁路走 chart SSE 事件渲染前端;工具本身只负责执行 + 透传。沙箱底座抽象成 ExecutorBackend Protocol(SkillExecutorBackend 当前实现,DockerExecutorBackend 留 v1.x 口)。", "why": "金融分析常需二次数值计算与自定义可视化,固化成 N 个画图工具既穷举不完又僵硬;让 LLM 写 Python 当场算/画,沙箱保证安全,plotly 产交互图,既灵活又可控。", "alternatives": [{"name": "固化 N 个画图工具", "brief_tradeoff": "穷举不完,新图型要改代码"}, {"name": "LLM 写 Python 进沙箱执行", "brief_tradeoff": "灵活但要把好沙箱安全闸"}, {"name": "直接 eval 不隔离", "brief_tradeoff": "任意代码执行,安全灾难"}], "chosen_alternative": "LLM 写 Python 进沙箱执行", "tradeoff": "复用既有 SkillExecutor 沙箱(execute_source 内联入口)零新增隔离面;figures 旁路 chart 事件不进上下文,省 token 又能渲染交互图;代价是模型偶尔写错代码,靠 while 循环天然自纠(stderr 截 500 字回喂)。沙箱黑名单补封 os.popen/os.fdopen。", "lessons_learned": "plotly 必须用 dist-min/factory 避 mapbox 重依赖;沙箱内 OpenBLAS 须设单线程避 OOM;figures 一旦进 LLM 上下文会瞬间炸窗,务必在 dispatch→apply 之间剥离。", "metrics": {}, "code_anchors": [{"file": "backend/app/chatloop/code_interpreter_tool.py", "line": 45, "note": "name = \"run_python\" — InProcessTool,run_with_state 调 backend.run_code"}, {"file": "backend/app/chatloop/worker_wiring.py", "line": 245, "note": "CodeInterpreterTool(backend=SkillExecutorBackend(...)) 注册进 chatloop ToolHub"}, {"file": "backend/app/skills/executor_backend.py", "line": 1, "note": "ExecutorBackend Protocol — 沙箱底座抽象,SkillExecutorBackend 实现"}], "linked_specs": [], "linked_capabilities": ["tool.parallel_tool_calls", "tool.mcp_bridge"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high。

#### 【high】只读子 agent 并发扇出(tool 维)— 缺新能力(NEW: tool.subagent_dispatch)

- **现状**:tool 维无一条专指「主 AI 把互不依赖的只读小任务并发派给 N 个临时子循环」。`parallel_tool_calls` 是底层并行原语,不等同此 chat 编排原语。
- **应改成**:tool 维新增一条,derive_rule 命中 `subagent.py` 的 `name="dispatch_subagents"`。
- **证据**:#144;`subagent.py:266`(`name = "dispatch_subagents"`)、`:220`(gather 扇出)、`:28`(护栏常量)、`models/subagent_dispatch.py:17`。验证者实跑 → lit,JSON `json.loads` 通过。
- **可直接落地的改动**:
  (a) capabilities.yaml — 把 tool 维头注释(第 63 行)从 `(9 项,预期 5 lit)` 改为 `# 02 Tool Interface & Protocol (12 项,预期 6 lit) §4`(现有 11 + 本条 = 12;若同批也加 tool.code_interpreter 则为 13,届时再 bump);在 tool 维末尾(`chat_slash_command` 后)追加:
```yaml
      - id: subagent_dispatch
        name_cn: "只读子 agent 并发扇出 (dispatch_subagents)"
        name_en: "Read-only subagent fan-out"
        derive_rule: { type: code_grep, pattern: 'name\s*=\s*"dispatch_subagents"', path_glob: 'backend/app/chatloop/subagent.py' }
```
  (b) deep_cards_seed.jsonl — 追加 finding 给的整行(`cap_id: tool.subagent_dispatch`,code_anchors 四锚 subagent.py:266/:220 + worker_wiring.py:246 + subagent_dispatch.py:17 均已核对):
```json
{"cap_id": "tool.subagent_dispatch", "what": "对外工具 dispatch_subagents:主 AI 把一组互不依赖、各自只用查的子任务一次性并发派给 N 个临时只读子循环(复用 ToolLoop,换受限只读 hub / max_steps=4 / fast tier / 白纸 context),asyncio.gather 并发跑、同步收齐,每个子循环原文摘要直传由主循环综合。配五护栏(深度 1 / 只读白名单 / fast tier / 步数 4 / 预算切片回滚)+ 通信三层(主↔子原文直传 · 子↔子不通信 · 子→前端 lane 进度条)+ 隔离铁律(子循环白名单不含 offer_deep_research/dispatch_subagents,禁串门禁递归)。新增 subagent_dispatch_runs 审计表,best-effort 落库留痕。", "why": "多标的对比 / 多源检索 / 逐只持仓体检这类任务,串行跑 N 遍慢且占主上下文;并发扇出给只读子助手分头查、只把摘要回传,主循环上下文干净、墙钟时间压到单个子任务量级。", "alternatives": [{"name": "主循环串行查 N 遍", "brief_tradeoff": "简单但慢,N 份原文挤爆主上下文"}, {"name": "只读子 agent 并发扇出(当前)", "brief_tradeoff": "快且上下文干净,代价是要设隔离铁律防递归/串门"}, {"name": "通用多 agent 框架", "brief_tradeoff": "重,且把控制流让渡给框架"}], "chosen_alternative": "只读子 agent 并发扇出(当前)", "tradeoff": "子循环复用同一 ToolLoop 但换受限只读 hub(白名单剔除 offer_deep_research/dispatch_subagents),深度锁 1 禁递归;预算给整批 = 当轮剩余 × 0.6 均分到每个子循环,跑完回滚进父 state;代价是子↔子不能通信,有先后依赖的任务不能用(留主循环串行)。", "lessons_learned": "子循环白名单必须显式剔除 dispatch_subagents 本身,否则递归扇出会指数爆炸;预算切片要在子循环跑完后回滚进父 state,否则父预算账目对不上;审计落库做成 best-effort(contextlib.suppress),留痕失败不该让主流程崩。", "metrics": {}, "code_anchors": [{"file": "backend/app/chatloop/subagent.py", "line": 266, "note": "name = \"dispatch_subagents\" — DispatchSubagentsTool 包装 SubagentFactory + 五护栏"}, {"file": "backend/app/chatloop/subagent.py", "line": 220, "note": "await asyncio.gather(*(spawn_one(...))) — N 个子循环真并发扇出"}, {"file": "backend/app/chatloop/worker_wiring.py", "line": 246, "note": "DispatchSubagentsTool(factory=subagent_factory) 注册进 chatloop ToolHub"}, {"file": "backend/app/models/subagent_dispatch.py", "line": 17, "note": "__tablename__ = subagent_dispatch_runs — 审计表 ORM"}], "linked_specs": [], "linked_capabilities": ["tool.parallel_tool_calls"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high(adjusted:补了 tool 维头注释 9→12 的同步修正,原 finding 漏)。

#### 【medium】超大工具结果回指针护栏 — 缺新能力(NEW: context.oversized_result_guard)

- **现状**:context 维无任何 cap 刻画「单条工具结果体积上限 + 可回取指针」;`ctx_compression`(整窗压缩)语义不同。
- **应改成**:#145 加了进 LLM 窗口的单条结果超 `oversize_result_char_threshold`(默认 4000 字)且可经 cache ref 取回时换 `truncated_digest+ref`(取不回的不截断只 log)。新增 cap + DeepCard。
- **证据**:#145;`loop.py:295`(`_cap_oversized_output`)、`:323`(`truncated_digest`)、`context.py:76`(阈值 4000);git `ed4a69d`。验证者实跑 recursive glob → lit。
- **可直接落地的改动**:
  (a) capabilities.yaml — 在 context 维 short_term 分组 `ctx_compression` 后(第 166 行后)插入:
```yaml
      - id: oversized_result_guard
        group: short_term
        name_cn: "超大工具结果回指针护栏"
        name_en: "Oversized tool-result guard"
        derive_rule: { type: code_grep, pattern: '_cap_oversized_output|oversize_result_char_threshold', path_glob: 'backend/app/chatloop/**' }
```
  (b) deep_cards_seed.jsonl — 追加:
```json
{"cap_id": "context.oversized_result_guard", "what": "裸 while 工具调用循环的单条结果体积护栏:进 LLM 窗口的单条工具结果序列化超 oversize_result_char_threshold(默认 4000 字)且带 cache ref(可经 read_cached_result 取回)时,原地换成 truncated_digest(前 600 字)+ ref 指针;取不回的(无 cache ref / in-process 工具结果)绝不截断,只 log 警告。", "why": "单条工具结果(如一大段研报 JSON)可一次性把窗口顶爆,但与老圈降级(_downgrade_old_tool_messages,针对已成历史的旧圈)正交——这是当圈刚产出的结果就要先封顶,且必须可回取以免丢信息。", "alternatives": [{"name": "硬截断不留指针", "brief_tradeoff": "简单但信息永久丢失,LLM 想看全文无路可走"}, {"name": "全量入窗不封顶", "brief_tradeoff": "窗口被单条结果顶爆"}, {"name": "digest+cache ref 可回取", "brief_tradeoff": "封顶又不丢:全文进 cache,窗口只留摘要+ref,LLM 需要时 read_cached_result 取回"}], "chosen_alternative": "digest+cache ref 可回取", "tradeoff": "选 digest+ref 因为既控窗口又不丢信息;代价是无 cache ref 或 in-process 工具的结果取不回,故对这类只 log 警告绝不截断,避免静默丢数据。", "lessons_learned": "截断前必须先确认可回取路径存在,否则宁可放行超大结果也不能静默吞掉——封顶与可回取是一对不可拆的契约。", "metrics": {}, "code_anchors": [{"file": "backend/app/chatloop/loop.py", "line": 295, "note": "_cap_oversized_output:单条结果超阈值且有 cache ref 时换 digest+ref"}, {"file": "backend/app/chatloop/loop.py", "line": 314, "note": "无 cache ref 的超大结果不截断,只 logger.warning"}, {"file": "backend/app/chatloop/context.py", "line": 76, "note": "oversize_result_char_threshold: int = 4000 单条结果入窗字符上限"}], "linked_specs": [], "linked_capabilities": ["context.ctx_compression"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:medium。

#### 【low】记忆写侧准入与保真护栏 — 缺新能力(NEW: context.memory_write_admission)

- **现状**:context 维 long_term 5 个 manual cap 泛指记忆存取,无「写侧准入边界 / 抽取后校验护栏」这条算法深度。属弱信号(可选)。
- **应改成**:#139 持仓事实边界(口头持仓不入图)+ #141 抽取后校验护栏(extraction_guards)+ 申万行业归一(industry_registry)+ 逐边容错。新增 cap + DeepCard(若不单列也可并入 long_term_memory 叙事)。
- **证据**:#139、#141;`path_b_runner.py:100`(`HOLDING_REL_TYPES`)、`:103`(`filter_holding_edges`)、`:212`;`extraction_guards.py`、`industry_registry.py`(均真接入管线,非死代码);git `5512b36`/`318055d`。验证者实跑 → lit。
- **可直接落地的改动**:
  (a) capabilities.yaml — 在 context 维 long_term 分组 `memory_compression` 后(第 192 行后)插入:
```yaml
      - id: memory_write_admission
        group: long_term
        name_cn: "记忆写侧准入与保真护栏"
        name_en: "Memory write admission & fidelity guards"
        derive_rule: { type: code_grep, pattern: 'filter_holding_edges|HOLDING_REL_TYPES', path_glob: 'backend/app/memory/path_b_runner.py' }
```
  (b) deep_cards_seed.jsonl — 追加:
```json
{"cap_id": "context.memory_write_admission", "what": "记忆写侧的准入边界 + 抽取后保真护栏三件套:① 持仓陈述(HOLDS/SOLD 边)不入记忆图(策略A,默认关、评估开),确立『持仓唯一真相源=持仓监控模块,口头持仓不入图』的双真相源去重;② extraction_guards 确定性兜底——幻觉 valid_to 日期重置、脏 stance 短语 label 丢弃;③ industry_registry 接申万二级行业归一(白酒/高端白酒/白酒Ⅱ→同一 canonical),修实体漂移断裂的观点演化链;抽取逐边容错(一条坏边不再 pydantic all-or-nothing 毁整批)。", "why": "LLM 抽取出的边会幻觉日期、写脏 label、实体名漂移,且口头持仓与持仓监控模块会双写冲突;写侧不设准入与兜底,坏数据会污染整个记忆图,且观点演化链会因实体名不一致断裂。", "alternatives": [{"name": "全信 LLM 抽取直接入图", "brief_tradeoff": "实现最简但幻觉日期/脏 label/实体漂移全进图,污染下游召回"}, {"name": "pydantic all-or-nothing 整批校验", "brief_tradeoff": "一条坏边毁整批抽取,保真但脆"}, {"name": "逐边容错 + 确定性后校验护栏 + 实体归一", "brief_tradeoff": "坏边单独丢、日期/label 兜底、行业名折叠,保真又不脆"}], "chosen_alternative": "逐边容错 + 确定性后校验护栏 + 实体归一", "tradeoff": "选确定性护栏 + 逐边容错因为 LLM 抽取非确定且会幻觉,确定性兜底比再加一轮 LLM 自检更省更稳;代价是护栏规则要随新故障模式持续补。持仓边界默认关,评估开,避免误伤已有写入。", "lessons_learned": "持仓这类有专属真相源(监控模块)的事实,口头陈述不该重复入记忆图——双真相源必须显式划准入边界去重,否则冲突裁决永远打架。", "metrics": {}, "code_anchors": [{"file": "backend/app/memory/path_b_runner.py", "line": 100, "note": "HOLDING_REL_TYPES = frozenset({'HOLDS','SOLD'}) 持仓关系类型"}, {"file": "backend/app/memory/path_b_runner.py", "line": 103, "note": "filter_holding_edges:策略A 持仓边不入图"}, {"file": "backend/app/memory/extraction_guards.py", "line": 1, "note": "抽取后确定性护栏:幻觉 valid_to 重置 + 脏 stance label 丢弃"}, {"file": "backend/app/memory/industry_registry.py", "line": 1, "note": "申万二级行业归一,折叠实体名漂移修复观点演化链"}], "linked_specs": [], "linked_capabilities": ["context.long_term_memory", "context.episodic_memory"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:low(弱信号,可选;代码与 derive_rule 本身已验证可 lit)。

#### 【high】Chat 裸 while 工具调用循环 — 缺新能力(NEW: lifecycle.chat_tool_loop)

- **现状**:lifecycle 维 11 项 cap 全围绕 LangGraph,无任何能力对应 #127 起的 chat 编排新核(裸 Python while 循环 `ToolLoop`)。
- **应改成**:补一条代表 chat agent loop 新架构的能力(单 LLM + 原生 function calling 多跳回环、四道终止闸、窗口四区组装、ToolHub 并行分发)。
- **证据**:#127、#144、#148、#150、#155;`loop.py:69`(`class ToolLoop`)、`:140`(`async def run` while True 主循环)、`:142-264`(节拍)。验证者实跑 → lit,Grep `chatloop/ToolLoop` 在 capabilities.yaml 0 命中(非重复)。
- **可直接落地的改动**:
  (a) capabilities.yaml — 把 lifecycle 头注释(第 248 行)改为 `# 04 Lifecycle & Orchestration (14 项) §6`(基线 11 + 本批 3 条 missing_cap = 14;**注:原头注释「10 项」本身已过期,实测 11 项**);在 `plan_and_execute`(第 280 行)之前插入:
```yaml
      - id: chat_tool_loop
        name_cn: "Chat 裸 while 工具调用循环 (ToolLoop)"
        name_en: "Bare-while tool-calling loop (ToolLoop)"
        derive_rule: { type: code_grep, pattern: 'class ToolLoop', path_glob: 'backend/app/chatloop/loop.py' }
```
  (b) deep_cards_seed.jsonl — 追加(`linked_capabilities` 改为只链已存在的 cap,去掉悬空的 `lifecycle.chat_termination_gates`,或在本批 chat_termination_gates 也落地后保留):
```json
{"cap_id": "lifecycle.chat_tool_loop", "what": "chat 模式编排核心(替代退役的 supervisor 图):单 LLM + 原生 function calling 多跳回环、四道终止闸、窗口四区组装、ToolHub 并行分发。loop.py:run() 一个裸 while True,每圈:取消检查→check_gates→插话并入→stream_step→apply_step→filter_burned→分发前预算/插话检查点→dispatch→update_burned→回圈首。", "why": "LangGraph supervisor 单程图把控制流让渡给框架,可读性差、调试难、与本项目『自有控制流』偏好冲突;裸 while 循环让 chat 的多跳工具调用回环完全显式、可读、可逐圈插桩。", "alternatives": [{"name": "LangGraph supervisor 单程图(旧)", "brief_tradeoff": "框架便利但控制流黑盒,steering/终止闸难塞"}, {"name": "OpenAI Agents SDK", "brief_tradeoff": "省事但只有 max_turns 一道硬闸,口径不贴本项目"}, {"name": "裸 Python while 循环(当前)", "brief_tradeoff": "完全自有控制流可读可插桩,代价是终止闸/窗口组装全要自己实现"}], "chosen_alternative": "裸 Python while 循环(当前)", "tradeoff": "选裸循环换来对每圈节拍的完全掌控(终止闸/steering/窗口分区/并行分发都能精确插),代价是框架兜底全没了、四道闸与窗口四区都要自己写自己测。", "lessons_learned": "闸落圈首与 spinning 台账记账有微妙时序(spinning 须在 dispatch 之后判);单 LLM 既决策又说话后不再有独立 planner 角色,system_prompt 要重写。", "metrics": {}, "code_anchors": [{"file": "backend/app/chatloop/loop.py", "line": 69, "note": "class ToolLoop — chat 编排新核"}, {"file": "backend/app/chatloop/loop.py", "line": 140, "note": "async def run — while True 主循环"}, {"file": "backend/app/chatloop/loop.py", "line": 252, "note": "工具分发:await self._tool_hub.dispatch(allowed, state)"}], "linked_specs": [], "linked_capabilities": ["lifecycle.agent_handoff", "lifecycle.human_in_the_loop"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high(adjusted:头注释计数 10→14 订正;linked_capabilities 去掉悬空的 chat_termination_gates,除非同批落地)。

#### 【high】对话循环多道终止闸 — 缺新能力(NEW: lifecycle.chat_termination_gates)

- **现状**:lifecycle 维无能力对应 chatloop 多道终止闸(max_steps/budget/spinning/repeated_failures + 烧签名 + 分发前预算预检 + force_conclude)。
- **应改成**:补一条代表 chat loop 终止/熔断控制的能力。
- **证据**:#127、#148;`gates.py:25`(`check_gates`)、`:38-40`(repeated_failures)、`:44`(filter_burned)、`:84`(budget_margin_exhausted)、`loop.py:409`(`_force_conclude`)。验证者实跑 → lit,GateConfig 数字逐项核对(max_steps=12/max_cny=0.10/burn=3/max_consecutive_failures=5)。
- **可直接落地的改动**:
  (a) capabilities.yaml — 放在 `agent_handoff`(第 291 行)之后、`issue_to_pr_pipeline` 之前:
```yaml
      - id: chat_termination_gates
        name_cn: "对话循环多道终止闸 (打转/烧签名/连续失败/预算/步数)"
        name_en: "Chat-loop termination gates"
        derive_rule: { type: code_grep, pattern: 'def check_gates|repeated_failures', path_glob: 'backend/app/chatloop/gates.py' }
```
  (b) deep_cards_seed.jsonl — 追加 finding 给的整行(`linked_capabilities` 已清空避免悬空):
```json
{"cap_id": "lifecycle.chat_termination_gates", "what": "chat 裸 while 循环的多道终止闸(零 I/O 纯谓词):check_gates 按固定顺序判 max_steps(硬步数 12)→budget(每 turn 0.10 元 / 120k token)→spinning(连续两圈调用签名集合相同=打转)→repeated_failures(台账尾部跨签名连续失败 ≥5);另有 filter_burned 烧签名(同签名失败 ≥3 次熔断,喂回指导性错误)与 budget_margin_exhausted 分发前预算预检(余量 <20% 则整轮跳过工具直接收尾)。撞任一闸都走 _force_conclude 逼模型基于已有信息收尾,并发 loop_halt 事件如实上报。", "why": "裸 while 循环没有框架兜底,放任会无限烧钱/打转;LangGraph 只有 recursion_limit、OpenAI Agents SDK 只有 max_turns 一道硬闸,都没有按金额计的预算闸和打转/乱试检测。本项目用多类闸覆盖不同失控模式:步数防失控、预算防烧钱、spinning 抓原地重复、repeated_failures 抓'换参数硬试'的跨签名乱试。", "alternatives": [{"name": "只设 max_steps 一道硬闸", "brief_tradeoff": "简单,但烧钱/打转/乱试都漏检"}, {"name": "靠 LLM 自觉停", "brief_tradeoff": "不可靠,死循环常发生"}, {"name": "多类纯谓词闸 + force_conclude 收尾", "brief_tradeoff": "覆盖全,代价是每类闸要自己实现并测"}], "chosen_alternative": "多类纯谓词闸 + force_conclude 收尾", "tradeoff": "选多闸因不同失控模式互不覆盖:打转闸只比签名集合相等,抓不到参数缓慢漂移,故另加 repeated_failures 数尾部连续失败;烧签名抓同签名重试,故另加跨签名连续失败。撞闸不静默截断而是 force_conclude 逼收尾,守住'每个 tool_call_id 必有 tool 消息'的协议红线。代价是闸的台账时序很微妙(spinning 须在 dispatch 之后判,见 gates.py 记账契约)。", "lessons_learned": "事件层 reason 用 raw 码(max_steps/budget/spinning/repeated_failures)做看板归因,喂回模型的收尾文案才映射成人话短语(loop.py:_HALT_REASON_TEXT),两者口径分离避免污染归因。预算闸放圈首检查会让单圈超支,故 #148 补了分发前预检(budget_margin_exhausted)在'LLM 成本已入账、即将分发工具'处再卡一次。", "metrics": {}, "code_anchors": [{"file": "backend/app/chatloop/gates.py", "line": 25, "note": "def check_gates — 四道闸固定判定顺序:max_steps→budget→spinning→repeated_failures"}, {"file": "backend/app/chatloop/gates.py", "line": 38, "note": "repeated_failures 闸:trailing_failure_count() >= max_consecutive_failures(抓跨签名乱试)"}, {"file": "backend/app/chatloop/gates.py", "line": 84, "note": "budget_margin_exhausted — 分发前预算预检(余量 <20% 跳过整轮工具)"}, {"file": "backend/app/chatloop/loop.py", "line": 409, "note": "_force_conclude — 撞闸后逼模型基于已有信息收尾,不静默截断"}], "linked_specs": [], "linked_capabilities": [], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high(adjusted:放置位置改到 agent_handoff 之后,linked_capabilities 清空)。

#### 【medium】只读扇出子 agent 派发(lifecycle 维)— 缺新能力(NEW: lifecycle.subagent_dispatch)

- **现状**:lifecycle 维无能力对应 #144 的 `dispatch_subagents`。注:本条与 `lifecycle.agent_handoff` 翻 lit **二选一或并存均可**——agent_handoff 翻 lit 是最低成本,本独立 cap 更精准刻画「只读扇出 + 五护栏 + 上下文隔离」。
- **证据**:#144;`subagent.py:100`(`SubagentFactory`)、`:129`(`spawn_one`)、`:27-42`(护栏常量 + 白名单)、`:265`(`DispatchSubagentsTool`)、`models/subagent_dispatch.py`。验证者实跑 → lit;spec `docs/superpowers/specs/2026-06-11-chat-subagent-dispatch-design.md` 经 Glob 确认存在。
- **可直接落地的改动**:
  (a) capabilities.yaml — 放在 `agent_handoff`(第 291 行)之后、`issue_to_pr_pipeline` 之前:
```yaml
      - id: subagent_dispatch
        name_cn: "只读扇出子 agent 派发 (dispatch_subagents)"
        name_en: "Read-only fan-out subagent dispatch"
        derive_rule: { type: code_grep, pattern: 'class SubagentFactory|def spawn_one', path_glob: 'backend/app/chatloop/subagent.py' }
```
  (b) deep_cards_seed.jsonl — 追加(anchor `subagent_dispatch.py` 行号用 16 = `class SubagentDispatchRun` 定义行;`linked_capabilities` 去掉不存在的 `lifecycle.chat_tool_loop`,只留 `lifecycle.agent_handoff`):
```json
{"cap_id": "lifecycle.subagent_dispatch", "what": "chat 内只读扇出子 agent 派发原语 dispatch_subagents:主 AI 把一组互不依赖的只读小任务(多标的对比/多源检索/逐只持仓体检)一次性并发派给 N 个临时子循环——每个子循环 = 同一个 ToolLoop 换受限只读依赖(只读白名单 hub / max_steps=4 / fast tier / 白纸 context),asyncio.gather 并发跑、同步收齐,各子的原文摘要直传由主循环综合。", "why": "主循环串行跑多个只读子任务既慢又把一堆中间结果灌进主上下文;扇出到独立子循环让它们并发、各自白纸 context 不互相污染,只回传浓缩摘要(Anthropic 子 agent 模式同构),主循环上下文保持干净。", "alternatives": [{"name": "主循环串行跑", "brief_tradeoff": "慢,中间结果污染主上下文"}, {"name": "复用 research 多 agent 图", "brief_tradeoff": "重,且 research 图是写作流水线不是只读扇出"}, {"name": "临时子 ToolLoop 并发扇出", "brief_tradeoff": "轻、隔离好,代价是要五护栏防失控/递归"}], "chosen_alternative": "临时子 ToolLoop 并发扇出", "tradeoff": "选复用 ToolLoop 换受限依赖,因子循环和主循环本是同一种 while 控制流,只是依赖收紧;配五护栏(深度1/只读白名单/fast/步数4/预算切片回滚)+ 隔离铁律(子白名单不含 offer_deep_research/dispatch_subagents,禁串门禁递归)。代价是子任务必须真互不依赖,有先后依赖的留主循环串行。", "lessons_learned": "子循环白名单绝不能含 dispatch_subagents 自身,否则递归扇出炸开;也不含 offer_deep_research,否则子 agent 串门触发深研。每个子循环 best-effort 落 subagent_dispatch_runs 审计表留痕(SubagentAuditRepo.record_batch),失败不阻塞主流程。", "metrics": {}, "code_anchors": [{"file": "backend/app/chatloop/subagent.py", "line": 100, "note": "class SubagentFactory — 起子循环 + 收回 SubagentResult"}, {"file": "backend/app/chatloop/subagent.py", "line": 129, "note": "spawn_one — child_state+child_hub+独立 GateConfig(max_steps=4) 起一个隔离子 ToolLoop"}, {"file": "backend/app/chatloop/subagent.py", "line": 34, "note": "READONLY_SUBAGENT_TOOLS 只读白名单(不含 memory_*/skill/control/dispatch),禁串门禁递归"}, {"file": "backend/app/models/subagent_dispatch.py", "line": 16, "note": "SubagentDispatchRun(subagent_dispatch_runs)ORM 审计表 — 每个子循环 best-effort 落库留痕"}], "linked_specs": ["docs/superpowers/specs/2026-06-11-chat-subagent-dispatch-design.md"], "linked_capabilities": ["lifecycle.agent_handoff"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:medium(adjusted:放置位置 + anchor 行号 + linked_capabilities 均已修正)。

#### 【high】Chatloop 运行时聚合面板 — 缺新能力(NEW: observability.chatloop_runtime_aggregates)

- **现状**:observability 维 11 cap 无一对应 #152 的 chatloop 运行时聚合面板(`trace_service` 的 path_glob 是 `eval_*.py`,够不到 `trace_analytics.py`)。
- **应改成**:新增 cap(ChatloopTraceAnalytics 4 条聚合 SQL + 只读 API + 看板独立页)。
- **证据**:#152;`trace_analytics.py:98`(`ChatloopTraceAnalytics`)、`:102`(`aggregate`)、`:84`(`ChatloopAggregates`);`observability_router.py:20`;`server.py:742,770`。验证者实测 file_exists → lit,DeepCard JSON ConvertFrom-Json 通过。
- **可直接落地的改动**:
  (a) capabilities.yaml — observability 维末尾追加:
```yaml
      - id: chatloop_runtime_aggregates
        name_cn: "Chatloop 运行时聚合面板"
        name_en: "Chatloop runtime aggregates"
        derive_rule: { type: file_exists, path: 'backend/app/services/trace_analytics.py' }
```
  (b) deep_cards_seed.jsonl — 追加:
```json
{"cap_id": "observability.chatloop_runtime_aggregates", "what": "给 chatloop 裸 while 工具循环补的运行时可观测面板。tool_hub 每次工具调用(坏JSON/未知工具/缓存命中/成功/失败/search_tools 全覆盖)写一条 trace span,与 LLM 的 stream_step span 用同一 request_id 落进同一张 trace_spans 表;ChatloopTraceAnalytics 用 4 条聚合 SQL 跨请求统计:最慢工具 p50/p95、模型 vs 工具耗时占比、KV-cache 命中率、每轮均值(成本/墙钟/LLM调用数/工具调用数),子循环 request_id 排除不污染均值。只读 API GET /api/v0/observability/chatloop/aggregates 只出数字不出 span 原文;看板独立页 /eval/chatloop-observability 用 stdlib urllib 实时拉渲染。", "why": "chat 从 LangGraph 单程图重设计成裸 Python while 循环后,原 TraceService(只盖 eval_*.py)拿不到 chatloop 的工具+模型混合时间线。要能回答『哪个工具最慢/这轮钱花哪了/KV-cache 命中如何』必须把工具 span 与 LLM span 同 request_id 落同表再跨请求聚合。", "alternatives": [{"name": "每请求逐条打日志", "brief_tradeoff": "能看单次但无法跨请求算 p95/占比"}, {"name": "接外部 APM(如 Langfuse)", "brief_tradeoff": "功能全但引重依赖,个人作品过重"}, {"name": "同表 span + SQL 聚合(选)", "brief_tradeoff": "复用既有 trace_spans 表,纯 SQL 零新依赖,只读 API 隔离隐私"}], "chosen_alternative": "同表 span + SQL 聚合(选)", "tradeoff": "选同表 SQL 聚合是因为 trace_spans 已存在且工具/LLM span 同 request_id 天然可关联,percentile_cont 直接出 p95;代价是聚合走同步 SQL(故 router 用 sync def 走 threadpool),且只出聚合数字、span inputs/outputs 原文绝不返回(隐私边界)。", "lessons_learned": "工具 span 与 LLM span 共用同一张 trace_spans 表 + 同 request_id,是『跨系统统一可观测』落地的最小代价路径——无需新存储即可把一条请求的工具+模型混合时间线串起来;聚合 API 只读且只出数字,把隐私边界放在 API 层而非靠调用方自觉。", "metrics": {}, "code_anchors": [{"file": "backend/app/services/trace_analytics.py", "line": 98, "note": "class ChatloopTraceAnalytics — aggregate(window) 跑 4 条聚合 SQL"}, {"file": "backend/app/services/trace_analytics.py", "line": 40, "note": "_MVT_SQL 同表同查 name='LLMService.stream_step' 与 name LIKE 'tool:%' — 跨系统 trace 关联"}, {"file": "backend/app/chatloop/tool_hub.py", "line": 274, "note": "_write_tool_span: name=f'tool:{result.tool_name}',同 request_id 落 trace_spans"}, {"file": "backend/app/router/observability_router.py", "line": 20, "note": "GET /api/v0/observability/chatloop/aggregates 只读聚合端点"}, {"file": "dashboard/server.py", "line": 770, "note": "Route /eval/chatloop-observability 看板独立页"}], "linked_specs": [], "linked_capabilities": ["observability.trace_service", "observability.latency_p95"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high。

#### 【high】对话级成本账单 + KV-cache 命中率 — 缺新能力(NEW: observability.turn_cost_billing)

- **现状**:observability 维无对应 chatloop 对话级成本/KV-cache 命中率度量的 cap(cost_budget=预算硬上限、cost_alert=告警、pricing_table=静态价表,均非度量发射)。
- **应改成**:新增 cap(`state.turn_summary()` 算 turn 级账单挂 done 事件,cost_update 带单圈 delta)。
- **证据**:#145;`state.py:255`(`def turn_summary`,含 `cache_hit_rate`)、`:208-210`(三路 token 累计);`loop.py:214`(done 挂 `**turn_summary`)、`:191-193`(cost_update)。验证者实测 → lit;git `feat(chatloop): runtime 三道护栏(#145)`。
- **可直接落地的改动**:
  (a) capabilities.yaml — observability 维末尾追加:
```yaml
      - id: turn_cost_billing
        name_cn: "对话级成本账单 + KV-cache 命中率"
        name_en: "Per-turn cost billing + KV-cache hit rate"
        derive_rule: { type: code_grep, pattern: 'def turn_summary|cache_hit_rate', path_glob: 'backend/app/chatloop/state.py' }
```
  (b) deep_cards_seed.jsonl — 追加:
```json
{"cap_id": "observability.turn_cost_billing", "what": "chatloop 裸 while 循环的 turn 级对话账单。state 在每圈 apply_step 时三路累计 prompt/completion/cached token;turn_summary() 算出整 turn 的成本(cost_cny)、LLM 调用数(=step)、工具调用数(=台账条数)、token 三路拆分、KV-cache 命中率(cached_tokens/prompt_tokens,prompt=0 不除零),挂在 done 事件 data 上;cost_update 事件额外带单圈 delta(step_cost_cny/step_prompt/step_completion)便于定位哪一圈 prompt 膨胀。", "why": "chat 重设计为裸循环后,一个 turn 可能跑很多圈(每圈一次 LLM + 若干工具),必须有逐 turn 的成本与 KV-cache 命中率度量才能回答『这轮对话花了多少钱、缓存吃得好不好、哪圈 prompt 爆了』。这是把 cost/缓存做成可发射信号、喂可观测看板的前提,区别于 cost_budget 的硬上限和 cost_alert 的告警阈值。", "alternatives": [{"name": "只在 cost_budget 里累计金额", "brief_tradeoff": "能防超支但拿不到 KV-cache 命中率/逐圈拆分"}, {"name": "事后查 trace 表聚合", "brief_tradeoff": "能复盘但拿不到实时单圈 delta 反馈到前端"}, {"name": "turn 内记账 + 事件发射(选)", "brief_tradeoff": "实时随 SSE 出账单,cost_update 带单圈 delta,done 带 turn 汇总"}], "chosen_alternative": "turn 内记账 + 事件发射(选)", "tradeoff": "选 turn 内记账是因为前端要实时看到逐圈成本/缓存命中(SSE),事后查表拿不到;代价是 state 多 3 个 token 累计字段、turn_summary 每 turn 现算一次。cache_hit_rate 用 cached/prompt 近似 KV-cache 命中(prompt=0 时取 0 防除零)。", "lessons_learned": "裸 while 循环里 turn 可能多圈,turn 级账单必须把『逐圈 delta(cost_update)』和『整 turn 汇总(done)』分两个事件发——单圈 delta 用来定位哪圈 prompt 膨胀,汇总用来报这轮总价与 KV-cache 命中率;cache_hit_rate 用 cached_tokens/prompt_tokens 近似,prompt=0 时取 0 不除零。", "metrics": {}, "code_anchors": [{"file": "backend/app/chatloop/state.py", "line": 255, "note": "def turn_summary — cost_cny/llm_calls/tool_calls/三路token/cache_hit_rate"}, {"file": "backend/app/chatloop/state.py", "line": 208, "note": "apply_step 三路累计 prompt/completion/cached_tokens_total"}, {"file": "backend/app/chatloop/loop.py", "line": 214, "note": "done 事件挂 **turn_summary(state)"}, {"file": "backend/app/chatloop/loop.py", "line": 191, "note": "cost_update 事件带单圈 step delta"}], "linked_specs": [], "linked_capabilities": ["observability.cost_budget", "observability.pricing_table"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "manual", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high。

#### 【high】对话 Agent 评估成绩单 — 缺新能力(NEW: verification.chatloop_eval_scorecard)

- **现状**:verification 维 9 cap 无一覆盖本周 chatloop 评估能力簇(pass^k / 裁判校准 kappa / grounding 裁判 / UserSimulator / 两专表)。
- **应改成**:新增一条 cap + DeepCard。
- **证据**:#135;`passk.py:13/20`、`calibrate.py:21`(`cohen_kappa`)、`grounding_scorer.py:46`(`GroundingJudge`)、`multiturn.py:24`(`UserSimulator`)、`recorder.py:27/59`(两专表)。验证者实跑 → lit,metrics 逐项核对(单轮 30 / 多轮 3 / kappa 1.000 / RelAcc 27%)。
- **可直接落地的改动**:
  (a) capabilities.yaml — verification 维下追加:
```yaml
      - id: chatloop_eval_scorecard
        name_cn: "对话Agent评估成绩单 (pass^k + 裁判校准 + 多轮)"
        name_en: "Chat-agent eval scorecard (pass^k + calibration + multiturn)"
        derive_rule: { type: code_grep, pattern: 'def pass_power_k|class UserSimulator|chatloop_eval_runs', path_glob: 'backend/eval/chatloop/*.py' }
```
  (b) deep_cards_seed.jsonl — 追加 finding 给的整行(`prefill_source: "hybrid"`,linked_capabilities 四个引用均存在):
```json
{"cap_id": "verification.chatloop_eval_scorecard", "what": "为裸 while 循环 chat-loop agent 自建的一整套评估成绩单。不引 LangSmith,复用 PG-trace + jsonl-golden。核心:6 行为脊柱(路由/工具选择/克制弃答/grounding/任务终态/可靠性)各自打分;pass^k 连胜率(同一 case 独立跑 k 次全部通过的概率,区分稳定做对 vs 偶尔蒙对);judge-vs-human kappa 校准让 grounding 裁判先「上岗」;GroundingJudge 忠实度裁判;UserSimulator 多轮模拟(目标达成裁判 + 跨轮政策 + 效率);评估落库 chatloop_eval_runs / chatloop_eval_metrics 两专表(config/git_sha/prompt_sha/成本/token)。", "why": "chat 从 LangGraph supervisor 单程图重设计成裸 Python while 工具调用循环后,老的 research-graph 评估口径不适用;裸循环 agent 的关键风险是路由错、工具选错、该弃答时硬答、答案不 grounding,需要一套能区分『系统性失败 vs 单次噪声』的成绩单来 PR gate。首跑就抓到系统级病灶:agent 过度把公开市场问题路由到 memory_search(相关性准确率仅 27%)。", "alternatives": [{"name": "接 LangSmith / 第三方 eval 平台", "brief_tradeoff": "省自研,但要外部依赖+数据外流,且口径不贴本项目裸循环"}, {"name": "只看 pass@1 单次成功率", "brief_tradeoff": "简单,但分不清稳定做对与偶尔蒙对,系统性失败被低样本噪声淹没"}, {"name": "自建 pass^k + 裁判校准 + 多轮模拟成绩单", "brief_tradeoff": "复用已有 PG-trace,口径自主可控;代价是自己维护 golden 与裁判校准集"}], "chosen_alternative": "自建 pass^k + 裁判校准 + 多轮模拟成绩单", "tradeoff": "选自建是因为复用 PG-trace + jsonl-golden 零外部依赖、口径贴裸循环;pass^k 用 τ-bench 式连胜率把系统性失败从噪声里分出来,裁判先过 kappa 校准再上岗保证 grounding 评分可信。代价是 golden 集与裁判校准集都要手维护,且裁判 prompt 改了要重标重跑校准。", "lessons_learned": "首跑用真 agent 实跑而非 mock,才暴露出『过度路由 memory_search』这种 mock 永远测不到的系统级病灶;per-case pass^k 双峰分布证明它是系统性根因而非低样本抖动。多轮评估必须有独立的 UserSimulator 扮用户,单轮 golden 测不出跨轮政策遵守与效率。", "metrics": {"单轮 golden 场景": "30 (直球 9 / 自然难 12 / 对抗 9)", "多轮场景": "3 (multiturn.jsonl)", "裁判校准 kappa": "1.000", "评估落库专表": "2 (chatloop_eval_runs / chatloop_eval_metrics)", "首跑系统级病灶": "过度路由 memory_search,RelAcc 27%"}, "code_anchors": [{"file": "backend/eval/chatloop/passk.py", "line": 20, "note": "def pass_power_k — τ-bench 式连胜率,区分系统性失败 vs 噪声"}, {"file": "backend/eval/chatloop/calibrate.py", "line": 21, "note": "def cohen_kappa — judge-vs-human 一致率,kappa≥阈值裁判才上岗"}, {"file": "backend/eval/chatloop/grounding_scorer.py", "line": 46, "note": "class GroundingJudge — grounding/忠实度裁判"}, {"file": "backend/eval/chatloop/multiturn.py", "line": 24, "note": "class UserSimulator — 多轮模拟,目标达成裁判+跨轮政策+效率"}, {"file": "backend/eval/chatloop/recorder.py", "line": 27, "note": "chatloop_eval_runs 专表;同文件 line 59 chatloop_eval_metrics"}], "linked_specs": [], "linked_capabilities": ["verification.adversarial_test", "verification.ab_testing", "verification.failure_attribution", "verification.golden_cases"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "hybrid", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high。

#### 【high】裁判元评估 — 缺新能力(NEW: verification.judge_meta_eval)

- **现状**:verification 维无「论证裁判本身可信(meta-eval)」这条;研报 `eval-meta-evaluation.yaml` 已可达却无对应代码 cap。
- **应改成**:新增 cap(judge-vs-human 一致率 + Cohen kappa + 四格混淆 + 裁判重测翻转审计 + 51 条人工金标准)。
- **证据**:#139;`meta_eval/judge_agreement.py:39`(`compute_agreement`)、`:54`(kappa)、`judge_stability.py:23`、`judge_goldset.jsonl`(51 行)。验证者实测 file_exists/code_grep 均 → lit。
- **可直接落地的改动**:
  (a) capabilities.yaml — verification 维(`failure_attribution` 第 392 行之后)追加;顺手把第 351 行注释 `(7 项,预期 5 lit)` 更正为 `(9 项,预期 5 lit)`(实测现有 9 条):
```yaml
      - id: judge_meta_eval
        name_cn: "裁判元评估 (一致率 kappa + 重测稳定性)"
        name_en: "Judge meta-evaluation (kappa + stability)"
        derive_rule: { type: code_grep, pattern: 'def compute_agreement|cohen|kappa', path_glob: 'backend/eval/memory_dialogue/meta_eval/*.py' }
```
  (b) deep_cards_seed.jsonl — 追加(`linked_capabilities` 用 `["verification.llm_judge", "verification.golden_cases"]`,删掉不存在的 `chatloop_eval_scorecard`,除非本批它也落地——若同批落地可改回链它):
```json
{"cap_id": "verification.judge_meta_eval", "what": "对裁判本身做元评估:judge-vs-human 一致率 + Cohen kappa + 四格混淆(judge_agreement.py)、裁判重测翻转审计(judge_stability.py)、51 条人工金标准 judge_goldset.jsonl。把已存在的 eval-meta-evaluation 研报落到一条真代码 cap 上。", "why": "LLM-judge 给的分数若裁判本身不可信就全盘失真;元评估用人工金标准 + kappa 一致率证明裁判先『可信上岗』,再用重测翻转率证明裁判稳定不抖,是 LLM-judge 评估链路的信任底座。", "alternatives": [{"name": "直接信 LLM-judge 不做元评估", "brief_tradeoff": "省事,但裁判幻觉/不稳无人知,下游评分全失真"}, {"name": "只算一致率不算 kappa", "brief_tradeoff": "一致率不扣随机基线,高 base-rate 下虚高"}, {"name": "一致率 + kappa + 重测稳定性(选)", "brief_tradeoff": "扣随机基线又测稳定,代价是要维护人工金标准集"}], "chosen_alternative": "一致率 + kappa + 重测稳定性(选)", "tradeoff": "选 kappa 因它扣掉随机一致基线,比裸一致率诚实;重测翻转审计抓裁判抖动。代价是 51 条金标准要人工标,裁判 prompt 改了要重标重跑。", "lessons_learned": "裁判校准集与重测稳定性是 LLM-judge 可信的两条独立证据,缺一不可:校准证明上岗准,稳定证明不抖;只看校准会漏掉裁判随机翻转。", "metrics": {"人工金标准": "51 (judge_goldset.jsonl)"}, "code_anchors": [{"file": "backend/eval/memory_dialogue/meta_eval/judge_agreement.py", "line": 39, "note": "def compute_agreement — 一致率 + 四格混淆"}, {"file": "backend/eval/memory_dialogue/meta_eval/judge_agreement.py", "line": 54, "note": "kappa = (po-pe)/(1-pe) Cohen kappa"}, {"file": "backend/eval/memory_dialogue/meta_eval/judge_stability.py", "line": 23, "note": "def compute_stability — 裁判重测翻转审计"}], "linked_specs": [], "linked_capabilities": ["verification.llm_judge", "verification.golden_cases"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "hybrid", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high(adjusted:linked_capabilities 去掉悬空的 chatloop_eval_scorecard;头注释 7→9 同步)。

---

以下为 capabilities.yaml 的 **数字订正(stale_count)**:

#### 【high】execution 维头注释项数 7→11 — 过期数字(execution 维)

- **现状**:第 9 行 `# 01 Execution Environment & Sandbox (7 项,预期 6-7 lit) §3`。
- **应改成**:实测该维 11 条 cap(7 file_exists + 4 manual)。改 `11 项,预期 7 lit`(若同批加 code_interpreter 则 `12 项,预期 8 lit`)。
- **证据**:逐条计数 11;7 个 file_exists 路径全存在 → 7 lit。
- **可直接落地的改动**:把第 9 行改为
```yaml
  # 01 Execution Environment & Sandbox (11 项,预期 7 lit) §3
```
- **置信度**:high(verdict confirmed;medium→已被复核确认)。

#### 【high】observability 维头注释项数 9→11 — 过期数字(observability 维)

- **现状**:第 299 行 `# 05 Observability & Operations (9 项,预期 5 lit) §7`。
- **应改成**:实测 11 条 cap;当前 5 lit。**只改项数 9→11,保留「预期 5 lit」**(latency_p95 + unified_observability 两条 manual 未翻前不能预支 lit 数)。
- **证据**:逐条计数 11;4 个 file_exists 路径 + trace_service code_grep 命中 = 5 lit,6 manual = todo。
- **可直接落地的改动**:把第 299 行改为
```yaml
  # 05 Observability & Operations (11 项,预期 5 lit) §7
```
- **置信度**:high(adjusted:finding 原 proposed 的「预期 7 lit」错误,已订正回 5;若同批 latency_p95 + unified_observability 落地,再改「7 lit」)。

#### 【adjusted】Golden 行为参照集「12+」严重低估 — 过期数字(verification.golden_cases)

- **现状**:第 363-366 行 `name_cn/name_en: "12+ golden cases"`,`path_glob: 'backend/tests/**'`。
- **应改成**:chatloop 30 单轮 + 3 多轮 golden 在 `backend/eval/chatloop/golden/`(不在 `backend/tests/**`),叠加 dd_report/memory/skill/tool 各 golden 实际约 233+ 条。改名去掉写死数字,path_glob 指到 `backend/eval/**`(实测仍 lit)。**禁止用 brace `{tests,eval}`**——本 resolver 用标准库 glob 不支持 brace 展开,会把 lit 错翻 todo。
- **证据**:#135;实测各 golden.jsonl 计数;验证者实测 `backend/{tests,eval}/**` → 0 命中(假阴),`backend/eval/**` → lit。
- **可直接落地的改动**:把第 363-366 行替换为
```yaml
      - id: golden_cases
        name_cn: "Golden 行为参照集 (多子系统数百条)"
        name_en: "Golden behavior reference set"
        derive_rule: { type: code_grep, pattern: 'golden', path_glob: 'backend/eval/**' }
```
- **置信度**:high(adjusted:finding 原推 brace path_glob 不可用,已改单 path_glob)。

#### 【adjusted】分层 pytest 测试体系「289+」严重过期 — 过期数字(verification.test_suite)

- **现状**:第 371-374 行 `name_cn: "289+ pytest"` / `name_en: "289+ tests"`,`derive_rule: { type: file_exists, path: 'backend/tests' }`。
- **应改成**:实测约 2460 个 `def test_`(DeepCard 第 49 行自报 2161)。改名去掉写死旧数字,用「2000+」量级,derive_rule 不变(仍 lit)。**注意缩进**:`- id` 前 6 空格、字段前 8 空格(finding 原 proposed 缩进错)。
- **证据**:实测 `grep -rE '^\s*(async )?def test_' backend/tests/` = 2460,横跨 409 文件。
- **可直接落地的改动**:把第 371-374 行替换为(对齐文件实际缩进)
```yaml
      - id: test_suite
        name_cn: "分层 pytest 测试体系 (L0/L1/L2/L3, 2000+ 测试函数)"
        name_en: "Layered pytest suite (2000+ tests)"
        derive_rule: { type: file_exists, path: 'backend/tests' }
```
- **置信度**:high(adjusted:缩进订正)。

---

### 2.2 `dashboard/data/deep_cards_seed.jsonl`

> 以下为修改既有 DeepCard 行(stale_arch / 数字),不含上文 missing_cap 配套的新 DeepCard(已在 §2.1 各条 (b) 段给出)。另:`governance.audit_infrastructure` 的新 DeepCard 见本节末。

#### 【high】MCP 桥工具数 8→9 — 过期数字(tool.mcp_bridge 第 9 行)

- **现状**:what 写「chat_tools profile 提供 8 个工具(含 kb_search)」;第 3 条 code_anchor note 写「独立于 chat_tools profile 的 8 个工具」。
- **应改成**:#146 把 `get_daily` 加进 `_CHAT_TOOL_MODULES`,现为 9 个。两处「8 个工具」改「9 个工具」。
- **证据**:#146;`mcp_server/server.py:34-44`(9 模块,末项 `app.mcp_server.tools.get_daily`);git `ce70080`。
- **可直接落地的改动**:把 what 中「chat_tools profile 提供 8 个工具（含 kb_search）」改为「chat_tools profile 提供 9 个工具（含 kb_search 与 get_daily）」;把第 3 条 code_anchor 的 note「独立于 chat_tools profile 的 8 个工具」改为「独立于 chat_tools profile 的 9 个工具」。
- **置信度**:high。

#### 【high】MCP 桥 why 绑死已退役 supervisor — 已退役架构(tool.mcp_bridge 第 9 行)

- **现状**:why 写「在 chat 对话模式中,supervisor agent 通过 MCP protocol 调本仓工具,职责解耦且协议标准」。
- **应改成**:#127 把 chat 从 LangGraph supervisor 图换成裸 while 循环,老 supervisor 图栈已整文件删。why 改为描述 chatloop ToolHub 双后端(MCP via ToolRegistry + in-process)经 `_MCPToolProxy` 共享统一调用路径。**别牵连 research_graph(仍有效)**。
- **证据**:#127;`tool_hub.py:60`(`class ToolHub`)、`worker_wiring.py:216,237`、`tools/registry.py:17`(`_MCPToolProxy`);老 `chat_graph.py` 已删。
- **可直接落地的改动**:把 why 改为:
> 「chat 对话模式走 chatloop 裸 while 循环(PR #127 退役 LangGraph supervisor 图),其 ToolHub 双后端把 MCP 子进程工具(经 ToolRegistry + _MCPToolProxy)与本地 in-process 工具统一到一条调用路径;MCP 用官方 SDK + stdio subprocess 隔离,职责解耦且协议标准;两套 profile 隔离确保 memory 子系统重依赖链不污染 chat_tools 子进程启动。」

(其余 lessons_learned/tradeoff 仍准,不改。)
- **置信度**:high。

#### 【high】审计基础设施新 DeepCard — 缺新能力(governance.audit_infrastructure)

- **现状**:deep_cards_seed.jsonl 无 `cap_id=governance.audit_infrastructure` 的 DeepCard(本维仅 5 张);配合 §2.1 该 cap derive_rule 翻 lit 后缺深读叙事。
- **应改成**:补一张描述 `subagent_dispatch_runs` 审计表 + `record_batch` 的 DeepCard。
- **证据**:#144;`subagent_dispatch.py:17/38-44`、`subagent_audit.py:33/41-71`。验证者 json.loads 通过,18 key 与现有 governance.auth 卡同构,`linked_capabilities` 的 `governance.capability_control_gate` 存在。
- **可直接落地的改动**:追加一行:
```json
{"cap_id": "governance.audit_infrastructure", "what": "chat 内子 agent 派发的不可变操作审计表 subagent_dispatch_runs:主 AI 用 dispatch_subagents 一次并发派 N 个只读子循环,SubagentAuditRepo.record_batch 把每个子循环 best-effort 落库一行(batch_id/parent_request_id/turn_id/goal_packet/tool_scope/status/cost/tier 等),留下『谁在什么 turn 用什么工具范围干了什么』的可追溯痕迹。这是项目首个专用审计表。", "why": "子循环换受限只读 hub 并发跑,主循环只收原文摘要、看不到子循环内部走了哪些工具步;没有审计表就无法事后归因某次派发的工具范围、花费与成败,也无法把操作绑回发起的 parent_request/turn。专表 + best-effort 落库(留痕非致命,失败不阻断主流程)满足论文 §9.5 immutable trace + identity binding 的最小形态。", "alternatives": [{"name": "复用通用 TraceService span", "brief_tradeoff": "无需新表,但 trace span 是扁平 KV,缺 batch/goal_packet/tool_scope 结构化字段,聚合派发批次困难"}, {"name": "只打日志不落库", "brief_tradeoff": "零 schema 成本,但日志非结构化、易轮转丢失,无法 SQL 聚合审计"}, {"name": "专用 subagent_dispatch_runs 表 + record_batch(本实现)", "brief_tradeoff": "一行=一子循环,批次字段去规范化到每行便于聚合;代价是多一张 ORM 表 + create_all 幂等建表"}], "chosen_alternative": "专用 subagent_dispatch_runs 表 + record_batch(本实现)", "tradeoff": "选专表是因为派发审计需要 batch_id/goal_packet/tool_scope 等结构化维度做聚合,通用 trace span 撑不起;代价是引入一张新 ORM 表,靠 create_all 幂等建表(项目不引 alembic)。record_batch 用 SessionLocal 同步写、留痕失败不阻断主循环(best-effort),id 用 parent.request_id+index 拼成确定值不依赖随机,便于测试。", "lessons_learned": "best-effort 审计的两条纪律:(1) id 不要用 uuid/random,改用 parent.request_id::sub::i 拼接,否则集成测试断言落库行无法定位;(2) 落库走独立 SessionLocal(与 TraceService 同款),测试时注入 nullcontext(db_session) 复用事务,避免审计写入污染被测主事务的 rollback 隔离。", "metrics": {}, "code_anchors": [{"file": "backend/app/models/subagent_dispatch.py", "line": 17, "note": "SubagentDispatchRun.__tablename__ = subagent_dispatch_runs;一行=一子循环,batch_id 去规范化到每行"}, {"file": "backend/app/models/subagent_dispatch.py", "line": 38, "note": "__table_args__ 5 个 Index(batch/parent_req/scenario/status/created),供按批次/发起方/场景/状态聚合审计"}, {"file": "backend/app/services/subagent_audit.py", "line": 33, "note": "SubagentAuditRepo.record_batch:遍历 subtasks×results best-effort 落库,id=parent.request_id::sub::i(可测、不依赖随机)"}], "linked_specs": [], "linked_capabilities": ["governance.capability_control_gate"], "linked_memories": [], "linked_decisions": [], "provenance": {}, "prefill_source": "hybrid", "prefill_at": null, "last_edited_at": null, "screenshots": []}
```
- **置信度**:high。

#### 【high】Skills bundle 叙事去推荐化 — 已退役架构(context.skills_bundle 第 2 行)

- **现状**:what 写「skill bundle 17 件 (11 methodology + 3 references + 3 scripts)」;why/tradeoff/code_anchor 多处称「Writer 用 scripts 做确定性评级/仓位决策」;SKILL.md 锚 note 写 `component_count: 17`。
- **应改成**:#136 下线整套推荐引擎,bundle 缩为 13 件(11 methodology + 1 references + 1 script),Writer 不再做确定性评级/仓位。
- **证据**:#136;`SKILL.md:14`(13)、`:46-53`;`writer.py:14-15`(推荐引擎已下线)、`analyst.py:38`/`writer.py:34`(已重构为 import `_SOP_TEXT` 共享 SSOT,**不再各自 load_skill()**)。
- **可直接落地的改动**(改 what / why / tradeoff / code_anchors[0].note 四处):
  - what 起句改为:「金融研究 skill bundle 13 件 (11 methodology + 1 references industry_benchmarks + 1 script lookup_industry_benchmark),由 Analyst 和 Writer 在 build_prompt 阶段引用共享的 _SOP_TEXT(financial_research 包级 SSOT,由 11 份 methodology 拼成)注入方法论。」(**不写「各自 load_skill()」**——实际 import `_SOP_TEXT`)
  - why 内「Analyst 用 SOP 做证据分析,Writer 用 scripts 做确定性评级/仓位决策(LLM 不算数)」改为「Analyst 用 SOP 做证据分析并用 lookup_industry_benchmark 查行业基准做对照;PR #136 去推荐改造后已下线买卖评级/仓位脚本(classify_recommendation / compute_position_size),报告 § 6 从'投资建议'改为'综合研判'(多空两面 + 关键判断变量,不下买卖结论),定位为深度研究非投资建议。」
  - tradeoff 内「17 件组件可独立演进」改为「13 件组件可独立演进」。
  - code_anchors[0].note「component_count: 17,...」改为「component_count: 13,loaded_by: Analyst.build_prompt + Writer.build_prompt」。
  - (可选)code_anchors[1] analyst.py / [2] writer.py 的 note `_SKILL_BUNDLE = load_skill()` 已失效,改为 `from app.skills.financial_research import _SOP_TEXT  # 共享 SSOT`,行号对到 analyst.py:38 / writer.py:34。
- **置信度**:high(adjusted:加载描述从「各自 load_skill()」修正为「共享 _SOP_TEXT」)。

#### 【high】情景记忆 code_anchor 漂移 + 已 live — 已退役架构(context.episodic_memory 第 18 行)

- **现状**:code_anchors[2] 写 `{hierarchical.py, line: 657, note: 'write_episode():Path A step 1...'}`;语气是「架构已建好」未点明 live。
- **应改成**:`write_episode` 已从 657 漂到 693;#151 后真 live。anchor line 改 693,note 末追加 live 说明。`models.py:54` 锚仍准不动。
- **证据**:#151、#139、#141;`hierarchical.py:693`(`async def write_episode`)、`chat_memory_hook.py:78`(live 调用点)。
- **可直接落地的改动**:把 code_anchors 中 `{"file": "backend/app/memory/hierarchical.py", "line": 657, ...}` 的 `line` 改为 `693`,note 末尾追加「(PR #151 后经 chat_memory_hook.persist_episode_and_trigger 在 run_chat_async 收尾干净成功轮真正 live 调用)」。
- **置信度**:high。

#### 【adjusted】语义记忆 code_anchor 漂移 — 已退役架构(context.semantic_memory 第 17 行)

- **现状**:code_anchors[1] 写 `{hierarchical.py, line: 502, note: 'archival_memory_search:Graph 不进 default...'}`;tradeoff 内文引「hierarchical.py:502」。
- **应改成**:`archival_memory_search` 已从 502 漂到 525;tradeoff 散文里引用的「Graph 不进 default」注释本身在 **533** 行(比 finding 提议的 525 更精确)。叙事本体不改。
- **证据**:#139、#141;`hierarchical.py:525`(`async def archival_memory_search`)、`:533`(注释)、`:645`(traverse)。
- **可直接落地的改动**:(1) code_anchors `line: 502` 改为 `525`(锚指符号定义);(2) tradeoff 字符串里「(hierarchical.py:502 注释明确:Graph 不进 default)」改为「(hierarchical.py:533 注释明确:Graph 不进 default)」。
- **置信度**:medium(adjusted:散文行号用 533 而非 525)。

#### 【adjusted】记忆压缩 两条 code_anchor 漂移 — 已退役架构(context.memory_compression 第 19 行)

- **现状**:code_anchors[1] 写 `{hierarchical.py, line: 162, note: 'core_memory_append 中 paged 时 logger.warning...'}`。
- **应改成**:**两条** anchor 都漂了:(1) hierarchical.py 的 paged warning 从 162 漂到 165;(2) finding 误称仍准的 `{working_blocks.py, line: 44}` 实际 `def do_append_with_paging` 在 **48** 行。
- **证据**:#139、#141;`hierarchical.py:106`(def)、`:165`(warning);`working_blocks.py:48`(`def do_append_with_paging`)。
- **可直接落地的改动**:(1) `{hierarchical.py, line: 162}` 改为 `165`;(2) `{working_blocks.py, line: 44}` 改为 `48`。叙事本体不动。
- **置信度**:high(adjusted:finding 漏报了 working_blocks.py 第二条同样漂移的锚)。

#### 【low】prompt_caching 补 KV-cache 前缀交叉引用 — 已退役架构补盲(context.prompt_caching 第 4 行)

- **现状**:what/why 全程描述 Redis 内容寻址模拟,未覆盖 #127 新增的 KV-cache 前缀稳定区。
- **应改成**:在 what 末尾补一句正交交叉引用。**不主张翻 lit**(derive_rule 仍 manual,是否计入 prompt_caching 口径留用户裁断)。**注意**:原 Redis 模拟接在跨会话记忆子系统 `hierarchical.py`(成本优化路径),**不是「deep-research 路径」**(finding 原 proposed 的错误归属已订正)。
- **证据**:#127;`prompt_cache.py`(仍在)、`chatloop/context.py`(KV-cache 稳定前缀四区);研报 `context-engineering-survey.yaml`「KV-cache 前缀经济学」。验证者确认 chatloop 对 prompt_cache 零交叉引用。
- **可直接落地的改动**:在 what 字段末尾(「。」之后、闭引号之前)追加:
> 「(注:本卡的 Redis 模拟接在跨会话记忆子系统 backend/app/memory/hierarchical.py(成本优化路径)。chat 裸 while 循环另有一套 KV-cache 前缀稳定区设计——system_prompt+persona+skill_listing 在 backend/app/chatloop/context.py 拼成 turn 内逐字节恒定的稳定前缀区吃缓存折扣,见研报 context-engineering-survey『KV-cache 前缀经济学』。两套机制正交、互不引用。)」
- **置信度**:low(adjusted:归属从「deep-research 路径」修正为「hierarchical.py 成本优化路径」)。

#### 【adjusted】session checkpoint chat 半段已退役 — 已退役架构(lifecycle.session_checkpoint 第 15 行)

- **现状**:what 写「chat graph 用 AsyncPostgresSaver(PG）」;chosen_alternative=`AsyncPostgresSaver (PG)`;code_anchors 指 `postgres_checkpointer.py:61` 与 `app_main.py:187`(chat_checkpointer)。
- **应改成**:#127 删 `postgres_checkpointer.py` 整文件、chat checkpoint 链路退役,改 `chat_session_context` 表跨 turn 重建。**research graph 的 MemorySaver 叙事仍有效,保留**。
- **证据**:#127;`postgres_checkpointer.py` 已删;`app_main.py:187` 现为 `_mcp_ctx` 赋值;chat 重建在 `chatloop/rebuild.py`;research MemorySaver 决策在 `router/research.py:360-376`(**不是 finding 误写的 355**)。
- **可直接落地的改动**(改 what / chosen_alternative / tradeoff chat 半段 / code_anchors 三条,research 半段与 lessons_learned 保留):
  - what:「LangGraph graph-state checkpoint 仅服务 research graph:research 因 AsyncSqliteSaver 在 uvicorn astream_events 下挂起(aiosqlite worker 线程饥饿),改用 MemorySaver(无持久化但不挂);chat 模式已于 #127 退役 LangGraph checkpoint 链路(原 AsyncPostgresSaver 整文件删除),改由 chat_session_context 表跨 turn 重建对话状态(DB-as-truth)。」
  - chosen_alternative:「research: MemorySaver / chat: chat_session_context 表(退役 checkpointer)」
  - tradeoff(chat 半段重写,research 半段保留):「chat 退役 LangGraph checkpoint:turn 原子语义下中间圈无需持久化,跨 turn 历史从 chat_session_context 表(history_summary + summarized_upto 水位)重建,finalize 统一 langgraph_checkpoint_id=None。research graph 仍用 MemorySaver 规避 aiosqlite 挂起,代价是无跨进程持久化(历史查询降级为扫旧 sqlite 文件)。」
  - code_anchors 三条替换为:
```json
[{"file": "backend/app/router/research.py", "line": 360, "note": "AsyncSqliteSaver 挂起根因注释 + research graph 用 MemorySaver 的决策(:376 checkpointer=MemorySaver())"}, {"file": "backend/app/chatloop/rebuild.py", "line": 213, "note": "rebuild_context() — chat 跨 turn 历史重建,读 ChatSessionContext 表(退役 LangGraph checkpointer 后的替代)"}, {"file": "backend/app/tasks/chat_runner.py", "line": 455, "note": "mark_done(langgraph_checkpoint_id=None) — chat checkpoint 退役,turn 原子语义"}]
```
- **置信度**:high(adjusted:research.py 锚点 355→360)。

#### 【medium】trace_service code_anchor 漂移 + 非唯一路径 — 已退役架构(observability.trace_service 第 46 行)

- **现状**:第三个 code_anchor `{llm_service.py, line: 140, note: '...是 trace 写入的唯一主路径'}`。
- **应改成**:line 140 现为 `"tier": tier,` 字面量,真正 `write_span` 在 chat() 内挪到 148;且「唯一主路径」失效——新增 `stream_step()`(:226/:248)是第二条 span 写入路径(chatloop LLM span 来源)。
- **证据**:#152;`llm_service.py:148`(chat() 内 write_span)、`:226`(`name="LLMService.stream_step"`)、`:248`(第二处 write_span);`stream_step` 真被 `loop.py:179/424` 调用(非死代码)。
- **可直接落地的改动**:把第三个 code_anchor 改为:
```json
{"file": "backend/app/services/llm_service.py", "line": 148, "note": "LLMService.chat 每次 LLM 调用后 self._trace.write_span(span)(同步路径);chat 重设计为裸 while 循环后另有 stream_step():226/248 写 name='LLMService.stream_step' 的 LLM span,不再是唯一写入路径"}
```
- **置信度**:medium。

#### 【high】b1 差异化守护去 position_size — 已退役架构(verification.golden_cases 第 48 行 lessons_learned)

- **现状**:lessons_learned 句末称差异化保证改由「`position_size` 数值范围 + 关键词命中来守」。
- **应改成**:#136 去推荐化,position_size 守护已退役,3 个 b1_differential 改为按「研究重心关键词 + dim coverage」差异化。
- **证据**:#136;`test_b1_diff_aggressive_growth.py:119`(「不再有 position_size」)、`writer.py:14-15`(推荐引擎已下线);`compute_position_size_pct`/`classify_recommendation` 全 backend 0 命中(函数已删)。
- **可直接落地的改动**:把 lessons_learned 末句改为:
> 「……阈值被迫改为 sanity-only(0~10 范围检查)。后续 #136 去推荐化后,差异化保证不再依赖 position_size 数值范围(推荐引擎 compute_position_size 已下线),改由各组『研究重心关键词命中 + 维度覆盖(dim coverage)』来守,b1_differential 三组不再校验仓位/评级。」
- **置信度**:high。

#### 【adjusted】auth 叙事 chat 已接真 JWT — 已退役架构(governance.auth 第 51 行)

- **现状**:lessons_learned 写「chat.py 至今仍保留该 stub 未切到真 JWT...chat 相关 user_id 在 DB 存 NULL」;且称「chat.py 自有副本」。
- **应改成**:#156(C.6)把 `auth_helpers.get_current_user` 从恒匿名 stub 升级为真 JWT + 匿名回退,chat.py:113 import 的就是升级后函数(**C44 去重后 chat.py 不再自带副本**,只 re-export)。原句两处事实(chat 仍 stub / DB 存 NULL)已反转。**注意**:line 139 注释属 **chat_tasks 表**(ChatTask),不是 chat_messages(finding 原 proposed 写错)。
- **证据**:#156;`auth_helpers.py:33-40`(委托 `_jwt_get_current_user`)、`auth_router.py:56-71`(真 JWT 校验)、`models/chat.py:139`(注释已改,属 class ChatTask)、`chat.py:113`(import 共享定义)。验证者注:#156 在分支 `feat/chat-user-isolation`,工作树已含 `auth_helpers.py` 的 `M` 改动。
- **可直接落地的改动**:把 lessons_learned 改为:
> 「早期全路径用 _AnonUser 匿名 stub(C.6 / PR #156 前 get_current_user 恒返回 anonymous)。#156 把共享入口 auth_helpers.get_current_user 升级为真 JWT 认证 + 匿名回退:委托 auth_router.get_current_user 校验 Bearer token,有效返回真 User(真 UUID),无/无效 token 才回退 _AnonUser;chat.py 第 113 行 import 的正是这个升级后函数(C44 去重后 chat.py 不再自带副本,只 re-export 共享定义),故登录用户那一轮带真 user_id(chat.py 不改、只读 user.id),让此前在匿名 stub 下休眠的轮末 episode 写入对登录用户真正生效;chat_tasks.user_id 注释也同步为『anonymous pre-auth: None;C.6 接 JWT 后 always 真 user UUID』(backend/app/models/chat.py 第 139 行,属 ChatTask)。security.py 用 `import bcrypt` 直接调用裸 bcrypt API,这能工作是因为 passlib[bcrypt] 将 bcrypt 作为传递依赖安装;pyproject.toml 只声明了 `passlib[bcrypt]>=1.7`,并无额外裸 bcrypt 条目。」
- **置信度**:high(adjusted:表名 chat_messages→chat_tasks;补「C44 去重后不再自带副本」纠正「chat.py 自有副本」反转事实)。

---

### 2.3 `dashboard/config/dimensions.yaml`

#### 【high】lifecycle paths 漏 chatloop 目录 — 名称漂移(lifecycle 维 paths)

- **现状**:第 57-61 行 lifecycle paths 只列 `agents/**` / `orchestration/**` / `checkpointer*.py` / `deep_research_v2/**`,无 `backend/app/chatloop/**`;keywords(第 62 行)= `["LangGraph","agent","subgraph","checkpoint","Saver"]`。
- **应改成**:#127 起 chat 编排新核(20 个 .py)落在 `backend/app/chatloop/`,不挂任何维度 → story 时间线/代码地图归类漏(实测 chatloop 文件当前掉进 `unknown`)。加 paths + 补 keywords。
- **证据**:#127/#144/#148/#150/#155;Glob `backend/app/chatloop/*.py` = 20;验证者用 fnmatch 实跑 `path_router.classify_path`:chatloop 文件对 7 维全 MISS → unknown,只有新增 glob 命中;keyword `gate` 在最近 400 commit subjects 无误伤。
- **可直接落地的改动**:在 lifecycle 的 paths 列表(`agents/**` 之后)加一行
```yaml
      - "backend/app/chatloop/**"
```
并把第 62 行 keywords 补成
```yaml
    keywords: ["LangGraph", "agent", "subgraph", "checkpoint", "Saver", "chatloop", "ToolLoop", "gate"]
```
- **置信度**:high。

---

### 2.4 `dashboard/server.py`(及 `dashboard/templates/eval.html`)

#### 【high】chatloop-runtime-optimization 研报未接入 — 研报未接入(lifecycle 维度页)

- **现状**:`DIMENSION_REPORTS['lifecycle']`(第 86-92 行)只有 chat-agent-loop-survey。新报告 `dashboard/data/reports/chatloop-runtime-optimization-survey.yaml`(untracked)未接入,/m/lifecycle 点不到。
- **应改成**:该报告自述挂 /m/lifecycle,加进 `DIMENSION_REPORTS['lifecycle']` tuple。**落地时需 `git add` 该 yaml**(当前 untracked);同批 untracked 测试 `test_chatloop_runtime_optimization_report.py` 当前必失败,本改动让它转绿。
- **证据**:无 PR(本周新增 yaml);yaml:13/19/20;`server.py:203-235` module_page_view 读 `DIMENSION_REPORTS.get(dim_id)`。
- **可直接落地的改动**:在 `DIMENSION_REPORTS['lifecycle']` tuple 里 chat-agent-loop-survey 之后追加:
```python
        {
            "slug": "chatloop-runtime-optimization-survey",
            "title": "Chat Runtime 优化地图 · 我们的问题 × 工业界方案",
            "sub": "按真实场景指出本项目 chatloop(裸 while 循环 runtime)的 7 个优化决策点:每个先给我们代码里的问题(file:line 证据),再给工业界解法(Claude Code / Anthropic API / OpenAI Agents SDK / LangGraph / Manus)· 22 来源 / 25 条承重结论三票对抗核查全过",
        },
```
- **置信度**:high。

#### 【medium】chat-agent-loop-survey 入口「chat 子图循环」措辞过期 — 名称漂移(server.py:90)

- **现状**:第 90 行 sub 末尾「…对照本项目 chat 子图循环 · 9 路调研 + 63 条事实核查」。
- **应改成**:#127 后 chat 不是 LangGraph 子图而是裸 while 循环。「chat 子图循环」改「chat 裸 while 工具调用循环」。仅文案改动,不动 slug/路由。
- **证据**:#127;`loop.py:69`(`class ToolLoop`)、`:140`(while True);git `a70512c`。注:报告本体 yaml 亦带同款措辞,本次仅改入口 sub(finding 已限定范围)。
- **可直接落地的改动**:把第 90 行 sub 里「对照本项目 chat 子图循环」改为「对照本项目 chat 裸 while 工具调用循环」。
- **置信度**:medium。

#### 【adjusted】chatloop-eval-scorecard 研报 /eval 入口缺失 — 研报未接入(eval.html 模板,非 server.py)

- **现状**:`chatloop-eval-scorecard.yaml` 报告本体可经 /eval/report 渲染,但 /eval 页『深度报告』区(`dashboard/templates/eval.html:149-181` 硬编码 6 条入口)未列它,只能从 chatloop-live 页底链接到达。
- **应改成**:在 eval.html『深度报告』区补一条入口。**注意修改点是 eval.html 模板,不是 server.py 的 DIMENSION_REPORTS**(eval 体裁报告走 /eval/report 通用路由,verification 维 DIMENSION_REPORTS 本就为空且无需加)。副标题须用报告真实口径(**单轮**首跑 30 场景、κ=1.000、pass^k),去掉错误的「多轮模拟/3 多轮 golden」(报告『诚实账』明写多轮 spec § 5 设计未接,multiturn.jsonl 实为 6 行非 3)。
- **证据**:#135;`eval.html:149-181`、`chatloop_live.html:19`;报告 yaml 第 72 行『诚实账』、`server.py:609/632` 通用路由。
- **可直接落地的改动**:在 `dashboard/templates/eval.html` 第 180 行(chat-agent-evaluation 入口 `</a>`)之后、第 181 行 `</section>` 之前插入:
```html
  <a class="eval-report-link" href="/eval/report/chatloop-eval-scorecard">
    <span class="erl-title">Chat-Loop Agent · 评估成绩单</span>
    <span class="erl-sub">6 行为脊柱(路由/工具选择/弃答/grounding/终态/可靠性)· 单轮首跑 30 场景 × 真 agent · pass^k 连胜率 + 裁判校准 κ=1.000 + grounding 双阈值 · 含诚实账(单轮≠多轮,多轮 spec § 5 已设计未接)</span>
    <span class="erl-arrow">›</span>
  </a>
```
- **置信度**:medium(adjusted:落点纠正为 eval.html;副标题文案纠正为单轮口径)。

---

## 3. 末尾两小节

### 3.1 跑一次 `make board-refresh` 就自动生效的

以下 **14 条 manual→可判定 derive_rule** 改完后,只要刷新就自动从「未开发」翻「已实现 lit」,**无需任何别的手工**(改的就是 capabilities.yaml 那一行 derive_rule):

| # | cap | 改后 derive_rule 命中 |
|---|---|---|
| 1 | `execution.sandbox_abstraction` | `class ExecutorBackend(Protocol)` @ executor_backend.py |
| 2 | `tool.parallel_tool_calls` | `asyncio\.gather` @ tool_hub.py |
| 3 | `context.ctx_compression` | `_downgrade_old_tool_messages\|max_context_tokens` @ context.py |
| 4 | `context.episodic_memory` | `persist_episode_and_trigger\|next_episode_index` @ chat_memory_hook.py |
| 5 | `context.long_term_memory` | `persist_episode_and_trigger\|extract_session_episodes_async` @ tasks/** |
| 6 | `lifecycle.human_in_the_loop` | `steer_merged\|_steer_interrupted_result` @ chatloop/** |
| 7 | `lifecycle.agent_handoff` | `class SubagentFactory\|def spawn_one` @ subagent.py |
| 8 | `observability.latency_p95` | `percentile_cont\|p95_ms` @ trace_analytics.py |
| 9 | `observability.unified_observability` | `LLMService\.stream_step` @ trace_analytics.py |
| 10 | `verification.adversarial_test` | `"difficulty":\s*"对抗"` @ golden/*.jsonl |
| 11 | `verification.ab_testing` | `prompt 消融\|system_prompt_sha\|...` @ eval/chatloop/*.py |
| 12 | `verification.failure_attribution` | file_exists RESULTS-2026-06-08.md |
| 13 | `governance.audit_infrastructure` | `subagent_dispatch_runs` @ models/*.py |
| 14 | `governance.hallucination_check` / `governance.capability_control_gate` | score_disclaimer / READONLY_SUBAGENT_TOOLS(2 条,medium) |

> 另:`lifecycle.langgraph_skeleton` 改 path_glob(`agents/**`→`orchestration/**`)虽不翻牌(本就 lit),但**修掉了 clean checkout 会从 lit 误翻 todo 的雷**,同属「刷新即生效」类,优先级等同上表。

> 新增 cap(missing_cap)的 derive_rule 同样刷新即判 lit,但它们还要配套写 DeepCard 才完整,故不计入「无需别的手工」一列。

### 3.2 建议复核顺序(高价值/低风险 → 低价值)

**第一批 · 改一行刷新即翻牌,零风险(强烈优先)** — §3.1 那 14 条 manual→lit + langgraph_skeleton 改 path_glob。全部 high(governance 两条 medium),改动最小、收益最直观(看板一片「未开发」立刻翻绿),且每条都已用真 resolver 实测命中。

**第二批 · 纯数字/措辞订正,零逻辑风险** — capabilities.yaml 五处 header 计数(execution 7→11、tool 9→12、lifecycle 10→14、observability 9→11、verification 7→9)、四处写死数字(financial_tools 8→11、skills_bundle 17→13、golden_cases「12+」、test_suite「289+」)、server.py:90 措辞、eval.html 入口。注意三处 **adjusted 陷阱**:① golden_cases 禁用 brace path_glob;② test_suite 缩进 6/8 空格;③ observability 计数保留「5 lit」不预支。

**第三批 · DeepCard 叙事/锚点修正,需逐字替换不破 JSON** — deep_cards_seed.jsonl 的 stale_arch 8 条(mcp_bridge why、skills_bundle、episodic/semantic/memory_compression 锚点漂移、session_checkpoint、trace_service、golden_cases lessons、auth)。每条只改指定字段,**改完用 `json.loads` 验证该行仍可解析**。auth 与 session_checkpoint 注意 adjusted 的表名/行号订正。

**第四批 · 新增能力卡(missing_cap),工作量最大但补的是本周工程深度** — 8 条 capabilities.yaml 新 cap 块 + 8 张新 DeepCard(execution/tool code_interpreter ×2、tool/lifecycle subagent_dispatch、chat_tool_loop、chat_termination_gates、oversized_result_guard、chatloop_runtime_aggregates、turn_cost_billing、chatloop_eval_scorecard、judge_meta_eval、governance.audit_infrastructure 卡)。先落 high(代码解释器、chat_tool_loop、chat_termination_gates、两个 observability、两个 verification、audit_infrastructure),最后才是 medium/low(lifecycle.subagent_dispatch 与 agent_handoff 二选一、context.memory_write_admission 弱信号、prompt_caching 补盲)。所有新卡均需删掉验证者标出的**悬空 linked_capabilities**(chat_tool_loop / chat_termination_gates / chatloop_eval_scorecard 在被链时若未同批落地就去掉)。

**最后 · 研报接入收尾** — chatloop-runtime-optimization-survey 接入前先 `git add` 那两个 untracked 文件(yaml + 测试),接入后跑一次该测试确认转绿。