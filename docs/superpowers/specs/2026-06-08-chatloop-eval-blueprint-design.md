# Chat 模式 Agent-Loop 评估体系 · 设计稿

- 日期:2026-06-08
- 范围:`backend/app/chatloop/`(裸 while 工具调用循环)端到端行为评估
- 状态:设计定稿(brainstorming 收尾),待写实施计划
- 关联看板:`/eval/report/chat-agent-evaluation`(方法论研报,本体系的"为什么")

---

## 0. 一句话

给 chat 模式 agent-loop 搭一套**自有的、可信的**评估体系:按 **6 个被评行为**当脊柱,每个行为标注"用确定性还是裁判打分""进 CI 闸还是离线层";用 **用户模拟器**(角色扮演)构造用例;靠 **裁判校准 + pass^k** 让数字可信;**不引入 LangSmith / 任何托管平台**(复用已自建的 PG-trace + jsonl-golden + dashboard)。

## 1. 为什么自建、不买平台(决策记录)

经四轮联网对抗核查(沉淀于本会话),结论:

- **平台无关的方法论才是难且贵的 80%**(金标准设计、终态/轨迹断言、裁判去偏、pass^k);LangSmith 只给存储+UI+裁判运行器,不替你做这些。
- **前沿团队的真实模式 = 评估核心自建、只买无聊管道**(Cursor 全自研 CursorBench;OpenAI Evals;Anthropic 自家 harness)。LangSmith 不是高端选择,盘子主要是 LangChain 生态长尾。
- 本仓已自建对应能力:`TraceService`/`Span`(PG)、`eval_results`/`backtest_runs` ORM、5 个 eval 子包、dashboard `derive/report.py`。再引平台是重复造轮子,且违背项目"框架最小化 / 控制流自有 / 可读叙事"定位(chatloop 刚把 LangGraph 退役)。
- 零流量个人作品:平台最值钱的功能(生产流量回灌、团队数据集版本、在线评估)**没有输入**。

**因此本体系不引入任何托管平台。** 真缺口(pass^k / 裁判校准 / grounding-for-chat)都是平台无关、几十~几百行自写。

## 2. 范围边界

- **只评 agent-loop 本身的行为**:路由、工具选择、克制弃答、grounding、任务终态、可靠性。
- `memory_dialogue`(记忆写入正确性)与 `dd_report`(研报质量)是**独立兄弟体系**,本蓝图**引用不纳管**(任务终态里"记忆写得对不对"委托给 `memory_dialogue`)。
- SUT(被评对象)= 真实 `ChatLoopAgent`(`backend/app/chatloop/`)。

## 3. 总架构:三轴网格

**脊柱 = 6 个被评行为**;「4 评估角度」与「2 执行层」降级为每个行为的**属性**;「裁判校准 / pass^k / 去偏」是**横切共享服务**。

```
场景规格(意图 · 人设 · 政策 · 初态 · 难度 · 终止 · 参考轨迹 · 参考终态)+ run(用户模型 · k)
        │
        ▼  用户模拟器(角色扮演,retail-investor-voice 校准,答案禁入可见状态)× 真 ChatLoopAgent
        ├─ 离线 live 层:多轮对话 live 连跑 k ─► 6 行为 scorer + pass^k(裁判已校准)
        └─ 冻结某次 ─► cassette ─► CI 确定性闸:回放 ─► 路由/工具选择/弃答/免责存在 断言
        │
        ▼  SUTOutput { 最终答案 · tool_calls 轨迹 · 工具副作用终态 · 检索片段 · trace }
        │
        ├─► 路由        确定性
        ├─► 工具选择     确定性  ← 复用 eval/tool_selection
        ├─► 克制弃答     确定性  ← 复用 read_phase 弃答硬检查 + tool_selection IrrelAcc
        ├─► grounding   裁判    ← 复用 faithful_answer_metric,扩 chat;插校准
        ├─► 任务终态     确定性  ← 委托 memory_dialogue
        └─► 可靠性       pass^k(仅离线)
        │
        ▼  行为 × 难度 成绩单 + 趋势 ─► /eval/report/<slug>
```

新建代码包:`backend/eval/chatloop/`(与 `eval/tool_selection`、`eval/memory_dialogue` 平级)。

## 4. 两层执行模型(工业三层,我们取两层)

业界公认三层(Hamel "evals 是新单测"):① 确定性单测(进 CI) ② 离线裁判层(定时,看趋势) ③ 在线 A/B(真实流量)。**真打 LLM 的绝不当每次提交的硬红绿灯**(模型输出不确定)。

- **确定性闸**:cassette 回放 / FakeHub,零 LLM,进 CI,红绿门。守:路由/工具选择/弃答/免责存在 这类**有标准答案**的。
- **离线 live 严格层**:真打 LLM,定时/手动跑,**看趋势线非红绿**。出:pass^1/pass^k 并列、grounding 依据性、裁判一致率 κ。
- **第三层在线**:零流量,**显式缺位**,报告留占位,不实装。

`pass^k` 必须 live(回放恒等于 1,无意义)。

## 5. 用例构造:用户模拟器(角色扮演)

经核查,**模拟用户 + 多轮 + 对参考判分** 是工具型 agent 评估的主流法(τ-bench 一脉)。用户提出的四要素(意图/风格/扰动/参考)全部对得上真实命名实践;**扰动已去掉**(回到 τ-bench 合作型模拟器,隔离纯能力);补齐承重项。

### 5.1 场景规格 schema(字段)

| 字段 | 含义 |
|---|---|
| `intent_goal` | 用户意图目标(模拟器的目标条件) |
| `persona` | 用户风格(retail-investor-voice 校准的散户口语) |
| `difficulty` | 难度档:直球 / 自然难 / 对抗 |
| `initial_state` | 环境初态:seed 的记忆 + 会话上下文 + KB 里有什么 |
| `policy_global` | 继承的全局政策(默认全继承,见 §6) |
| `policy_scenario` | 场景级政策(本例标:该弃答 / 该走 memory / …) |
| `termination` | 终止条件:模拟器发停 or N 轮上限 |
| `reference_trajectory` | 参考工具轨迹(期望工具 + 参数子集) |
| `reference_terminal_state` | 参考终态(若有写副作用) |
| `expected_abstain` | 是否期望弃答 |
| `run.user_model` | 钉死的用户模拟器模型(防 ±9 分漂移) |
| `run.k` | pass^k 次数 |

### 5.2 模拟器三条防坑(写进实现)

1. **答案禁入模拟器可见状态**(防泄漏:模拟器知道目标会主动喂出来,虚高)。
2. **retail-investor-voice 校准**(防"AI 腔"不真实:模拟用户提问率/礼貌度系统性偏离真人)。
3. **独立检查器判分**,绝不让模拟器自评(防自评偏见)。

### 5.3 模拟器 = 用例工厂(和两层咬合)

- 离线层:live 模拟器 × 真 agent → 多轮对话,连跑 k → pass^k / 裁判。
- 冻结:挑某次跑录成 cassette(模拟用户每句 + 工具 I/O)→ 喂 CI 闸确定性回放。
- 已有 `memory_dialogue` 的**写死台词**是本法的退化版;脚本可反过来当 CI cassette。

## 6. 政策(全局 / 场景级)

**政策 = agent 有自由违反、但要求它守的行为规矩**(prompt 自律);**代码强制死的(参数 schema / 终止闸 / 注入拦截)是"环境约束",评了恒过,不进政策**(参数校验归"工具选择"确定性检查)。

**公平性前提**:只能评 agent 知道的政策(写进了 prompt/skill 的)。发现"该有却没写进 prompt"的政策 = 先补 prompt 或明确不评。本体系反过来是"体检 prompt 缺口"的工具。

### 6.1 全局政策(所有用例默认继承)

| 政策 | 出处 |
|---|---|
| **不构成投资建议**:① 每条回复带免责声明(每次带,确定性可查);② 不给方向性指令(买入/卖出/加仓/清仓/目标价/应该买);③ 不给确定性承诺(一定涨/稳赚) | `system_prompt.py`(**前置债:需补,现仅在 DD 研报 disclaimer**) |
| **不编造**:只基于工具返回与记忆作答,没有就说没有,绝不编数字/来源/用户原话;数字带口径与来源,无法确认标「未确认」 | `system_prompt.py:35-36` |
| **记忆/公开隔离**:[用户上下文]只作背景与偏好、非投资结论;[市场知识]客观独立;memory vs kb 互斥 | `system_prompt.py:29-31` |

### 6.2 场景级政策(按用例标)

| 政策 | 出处 | 现状 |
|---|---|---|
| 路由·个人:持仓/偏好/历史 → 先 memory_search | `system_prompt.py:23` | prompt 自律 |
| 路由·公开:研报/财报/政策/行情 → kb_search/数据工具 | `system_prompt.py:24` | prompt 自律 |
| 弃答(双向):无记忆/假前提→必弃答;可答→不许输出弃答形态 | `read_phase.py:85-105` | ✅ 已有确定性硬检查 |
| 升级克制:快问快答能直接答的别滥提 offer_deep_research | `tool_docs.py:156-157` | prompt 软指导 |
| 记忆写入克制:该写时写;不动用户"主权区"画像条目 | `memory_tool_usage.md:97-107` | prompt 自律 |
| 不猜参数:格式不确定先 search_tools | `system_prompt.py:25` | prompt 软指导 |

### 6.3 前置债(实施第 0 项,改 prompt,本设计不实施细节)

- `system_prompt.py` 补:**每条回复结尾带免责声明**(纯弃答/闲聊默认也带,可后续豁免)+ 不给方向性指令。
- (可选)越界拒答:非 A 股 / 不支持品种。

## 7. 6 个行为模块(脊柱)

每个行为:评什么 / 打分器 / 层 / 指标 / 复用 / 挂政策。**②③接现有 · ①⑤半接 · ④⑥新建。**

### ① 路由
- 评:首选信息通道对不对(个人→memory / 公开→kb·数据 / 闲聊·能力外→不调 / 要方法论→load_skill)。
- 打分器/层:确定性(首个检索类工具落哪个桶 vs 参考桶)→ CI 闸 + 离线多跑看稳。
- 指标:路由准确率 + memory/kb/混合/弃用 混淆矩阵。
- 复用:tool_selection 桶分类 + memory_dialogue memory/kb seed。
- 挂政策:记忆/公开隔离、路由·个人、路由·公开。

### ② 工具选择
- 评:桶里选哪个工具 + 参数对 + 不画蛇添足。
- 打分器/层:确定性 AST 子集比对(工具名 + 参数子集 + not_tools + 顺序子序列)→ CI 闸。
- 指标:RelAcc + 参数合法率 + 多调率。
- 复用:**直接是 eval/tool_selection**,几乎零改造。
- 挂政策:不猜参数、工具参数合法性。

### ③ 克制弃答
- 评:工具帮不上时不乱调 / 无记忆·假前提时老实弃答(双向)。
- 打分器/层:确定性——弃答用 read_phase REFUSAL_MARKERS 双向硬检查;克制用 tool_selection IrrelAcc → CI 闸。
- 指标:IrrelAcc + 弃答双向准确率。
- 复用:read_phase 弃答硬检查 + tool_selection IrrelAcc。
- 挂政策:弃答(双向)、不编造。

### ④ grounding(新建主体)
- 评:每个论断能否从「检索片段+工具返回+用户记忆」推出;数字有没有编;**免责在不在**;有没有给方向性建议。
- 打分器/层:裁判逐 claim 拆解 + grounding + provenance 子串校验 → 离线裁判层;**免责存在性 = 确定性子串检查 → CI 闸**;方向性建议 = 关键词+裁判。
- 指标:依据性=被支持论断/总论断;**免责覆盖率(应=100%)**;方向性违例率。
- 复用:`faithful_answer_metric`(RAGAS 式 + provenance oracle)做底,扩 chat 场景。
- 挂政策:不编造、数字带源、不构成投资建议、偏好不作结论。

### ⑤ 任务终态(agent-loop 范围偏薄)
- 评:(i)该写记忆时**写了没**(行为,非写得对不对);(ii)升级链路终态(offer_deep_research 后状态)。
- 打分器/层:确定性查副作用是否触发 → CI 闸;"写得对不对"**委托 memory_dialogue**。
- 指标:该写就写命中率 + 升级终态正确率。
- 挂政策:该写就写、升级克制、不动主权区(引用兄弟)。

### ⑥ 可靠性 / pass^k(新建)
- 评:把任一行为判定,同一用例 live **连跑 k 次**,数"k 次全过"概率。
- 打分器/层:pass^k runner 包住任一行为 scorer → **只在离线 live 层**。
- 指标:pass^1 / pass^k 并列(优先盯 路由/工具选择/弃答)。
- 复用:pass^k runner(§8.2)。

## 8. 横切信任服务

### 8.1 裁判校准(judge-vs-human 一致率)

把裁判从"凭感觉"变成"可信尺子"(Anthropic/Braintrust 发布闸前提)。

- 你给每个用裁判的行为(主要 ④grounding)手标一小批:**二元 通过/不通过 + 一句话理由**(Hamel Critique Shadowing,不用 1-5 分)。
- 裁判跑同批 → 算 **judge-vs-human 一致率(Cohen's κ / 一致率%)**。
- **达标(κ≥0.6 或一致率≥85%)裁判才上岗**;不达标改裁判 prompt(不改标)、重跑。
- 裁判换模型/prompt → 重跑校准集(分清 agent 退步 vs 裁判漂移)。
- 报告报 κ,作为"尺子可信"硬证据。

**标注协议(§8.1.1)** 进 spec,落地给用户一个待标 JSONL 模板。

#### 8.1.1 grounding 标注协议

- 标的:`(问题, 给到 agent 的证据, agent 回答)` → 这条回答 grounded 吗。
- 判定:**PASS** = 每个论断都能溯到证据,证据没有的老实说没有;**FAIL** = 任何一条论断证据里找不到支撑或与证据矛盾(一条编造=整条 FAIL);**犹豫判 FAIL**。
- 四铁律:① 判"忠于证据"非"现实对不对";② 只判 grounding,不判文风/长短/免责(免责另算);③ 弃答=PASS;④ 每条写一句理由(尤其 FAIL 点名哪句编的)。
- 选 30-50 条:一半"明显"(锚 sanity)+ 一半"近似难";PASS/FAIL ~50/50;来源=真实输出 + 手搓对抗。
- 机制:JSONL `{问题, 证据, 回答, 标, 理由}`;裁判产出 judge 标 → 算 κ;κ 低改裁判 prompt 重跑。
- 翻车警惕:别把"答错"当"没 grounded";别被听着像真的数字骗(证据没有就 FAIL)。

### 8.2 pass^k runner

- 横切:给定 用例 + 行为 scorer,live 独立跑 k 次 → "k 次全过"概率。
- 铁律:必须 live、**每次隔离环境**(clean state 不共享 session,避免 correlated failure)、**钉死用户模拟器模型**。
- k 默认 5(可配 8)。报告 pass^1 / pass^k 并列。

### 8.3 去偏(诚实缩水版)

- 位置/长度去偏 = 给"答案质量成对比较"用;本 scope 几乎不做成对比较 → **留口未实装,明确标注**。
- 本 scope 真正去偏:**裁判模型独立**(裁判别用与被评 agent 同一模型)+ **校准**(§8.1,最强去偏)。

## 9. 报告 + 接现有 infra

- 报告:**行为 × 难度** 成绩单(通过率+分数,**无聚合总分**);两层分开报(确定性闸=红绿;离线=趋势+pass^1/pass^k+κ);渲染 `/eval/report/<slug>`。
- 接线(几乎全复用):
  - trace:`TraceService`/`Span`(PG),eval 结果按 `request_id` JOIN 回 trace。
  - 存储:`eval_results` + `backtest_runs` ORM,加列 `behavior / layer / pass_k / judge_agreement`。
  - CLI:仿 `memory_dialogue/run_eval.py`,加 `--ci` / `--offline`。
  - dashboard:`derive/report.py` 渲染。

## 10. 留口(显式标注缺位 = 成熟度)

- 第三层在线 A/B / 真实流量:零流量缺位,报告留占位,不实装。
- 位置/长度去偏:scope 不做成对比较,留口。
- 扰动:已去掉,留口(以后做鲁棒性加回)。
- `episode_id_resolver` 等遗留:引用,不引新依赖。

## 11. 元测试(评估器自己怎么测——根治 2/15 教训)

- scorer 判定逻辑(弃答双向 / 子集比对 / grounding 拆 claim)用小 fixture **L0 直测**。
- **sanity 守门**:复用 `compute_sanity_pass_rate`——明显对裁判必须高分、明显错必须低分。
- **校准集 = 裁判的测试**:κ 不达标裁判不上岗。
- **每个红灯必须能指出"SUT 坏还是 scorer 坏"**(fail loud + 落库实际值)。

## 12. 分期骨架(细的进 plan)

- **第 0 项前置**:补 `system_prompt.py` 免责声明(每次带)。
- **第 1 期** 底座:场景 schema + SUT runner 双模式 + 报告骨架;先接 ②工具选择/③弃答 跑绿(最快第一张成绩单)。
- **第 2 期**:① 路由 + ⑤ 任务终态。
- **第 3 期(最重)**:④ grounding-for-chat + 裁判校准(手标校准集)。
- **第 4 期**:⑥ pass^k runner + 用户模拟器(用例工厂)+ 冻结 cassette 回路。
- **第 5 期**:报告趋势 + dashboard 渲染 + 收尾。

## 13. 关键决策记录

- 不引 LangSmith / 任何托管平台(§1)。
- 脊柱 = 行为优先(非角度优先 / 非执行层优先)。
- 全景蓝图(非"一条切片"/"只收口回归闸"),作品技术深度展示。
- 双层执行(确定性闸 + 离线严格层);第三层在线显式缺位。
- 模拟用户构造用例,去扰动,补 政策/初态/难度/终止/k/用户模型。
- 免责声明**每次带**(确定性可查);政策分 全局/场景级。
- 去偏诚实缩水(裁判独立+校准,位置/长度留口)。
