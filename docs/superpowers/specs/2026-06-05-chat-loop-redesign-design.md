# Chat 模式 Agent Loop 重设计 —— 裸 while 工具调用循环

- **日期**:2026-06-05
- **状态**:设计定稿,待实施计划
- **决策依据**:看板研报《Chat 模式 Agent Loop · 怎么做》(7 个设计决策框架)+ 本次三轮专项调研(上下文工程 8 路 / 周边接线 7 路 / 技能接线 5 路,均含对抗核查),调研沉淀见看板《Agent Loop 上下文工程 · 怎么做》《Agent Loop 周边接线 · 怎么做》
- **范围**:chat 模式 agent loop 核心全部重设;周边子系统(传输/持久化/记忆/知识库/技能/升级研究)内部不动、接线重做;research 深度研究子图不在范围
- **迁移策略**:直接替换,老图退役,无双路径并存期

---

## 0. 背景与决策总览

### 0.1 为什么重设

现状 chat 是 LangGraph supervisor 单程图:planner 一次 LLM 出结构化计划 → 纯函数路由 → 工具批量执行 → responder 第二个 LLM 合成回答。工具结果不回 planner。对照工业界研报的七个设计决策,现状有七个缺口:

1. 单轮骨架够不着"查了 A 才知道要查 B"的依赖型多跳(如:先查持仓清单,看到持仓里有哪几只,才知道要查谁的财报);
2. 无预算闸(按 token / 金额封顶的硬停);
3. 上下文管理只有超阈值才压缩,没有检索式选择;
4. 模型推理过程没有流式投射(direct_response 路径靠补发 hack 假装流式);
5. 打断只有取消整轮,没有"插话并入改方向"(steering);
6. 无审批门 hook;
7. 工具报错只能 responder 道歉,没有喂回重试的自纠回路。

### 0.2 骨架选型(已决)

经三方案对比(裸 while / LangGraph 双节点回环 / 事件溯源 reducer)与三镜头评审(可行性 / 研报对齐 / 作品价值),用户选定**裸 while 纯正派**:

- **单一 Python while 循环**承载整个 turn,控制流百分之百自有,无框架;
- **单 LLM**:planner / responder 双 LLM 合并——chat 模式不再有独立的规划者和应答者,一个模型在循环里既决策又说话;
- **LangGraph 完全退出 chat 路径**(research 子图继续用):它的四项职能逐项失效——控制流被收回;checkpoint 对裸 while 结构性无效(整 turn 一个节点,中间圈拿不到检查点),且生产 worker 路径现状本来就是 `checkpointer=None`(半接通);事件透出改为循环主动发射;interrupt 原语用不上;
- **turn 原子语义**(对齐 Claude Code):重试 = 整个 turn 从头重跑,不存在"恢复到第几圈";运行中插话 = 并入当前 turn,不是排队新问题。这条语义使"每圈 checkpoint"失去消费者,反过来坐实了裸 while 的合理性。

### 0.3 术语

- **turn**:一条用户消息到一个最终回答,对应一个 Celery task;
- **圈(iteration)**:turn 内 while 的一次"调 LLM → 执行工具"循环;
- **稳定前缀**:每圈请求开头逐字节不变的部分(吃 KV-cache 折扣,qwen 隐式缓存命中约按输入价两折计);
- **降级(digest)**:把窗口里的大块内容换成"摘要 + 可取回的缓存键";
- **熔断收尾**:升级提议发出后,循环代码强制下一圈禁调工具、只许生成收尾文字。

---

## 1. 循环核心

### 1.1 模块布局(新包 `backend/app/chatloop/`)

| 文件 | 职责 | 纯度 |
|---|---|---|
| `loop.py` | ToolLoop:while 本体(约 200 行),唯一有副作用的编排者 | 不纯壳 |
| `state.py` | ChatLoopState + ToolLedger(Pydantic) | 纯数据 |
| `context.py` | `assemble_context(state) -> messages`:每圈窗口组装 | 零 I/O 纯函数 |
| `gates.py` | 四道闸 + 打转检测 + 烧签名,每道独立谓词 | 零 I/O 纯函数 |
| `tool_hub.py` | 统一工具分发(MCP + in-process 双后端) | 不纯 |
| `events.py` | LoopEvent 统一信封 `{type, seq, step, ts, data}` | 纯数据 |

纯函数核 + 不纯壳:闸判定、窗口组装、状态折叠全部可在 L0 直测,不需要任何 runtime。

### 1.2 while 节拍

```python
async def run(self, state: ChatLoopState) -> ChatLoopState:
    while True:
        messages = assemble_context(state)                       # 组窗口(纯函数)
        step = await self.llm.stream_step(messages, self.tools,  # 单 LLM,流式
                                          tool_choice=state.tool_choice,
                                          on_delta=self.emit)
        state = apply_step(state, step)
        if not step.tool_calls:                                  # 闸一:自然停(主路径)
            return finalize(state)
        if (halt := check_gates(state)):                         # 闸二三 + 打转(纯谓词)
            self.emit(loop_halt(halt))
            return await self.force_conclude(state, halt)        # 逼模型基于已有信息收尾
        self.check_cancel_and_steer(state)                       # 取消 / 插话边界
        results = await self.tool_hub.dispatch(step.tool_calls)  # gather 并行 + 缓存 + 错误包装
        state = apply_results(state, results)                    # 折叠 + 台账记账
```

### 1.3 四道终止闸

| 闸 | 实现 | 默认 | 触发行为 |
|---|---|---|---|
| 自然停 | `not step.tool_calls` | — | 主路径,正常结束 |
| 硬迭代上限 | `state.step >= MAX_STEPS` | 12(六只持仓场景约五圈,留一倍垫) | 喂回"已达上限请基于已有信息作答"逼收尾 + SSE `loop_halt{max_steps}` |
| 预算闸 | 复用现有 CostBudget | 每 turn ¥0.10 + 12 万 token | 同上,`loop_halt{budget}`;压缩自身成本计入 |
| 回合边界 | while 天然语义 | — | turn 内自动喂回,turn 间停下等用户 |

加强项:**打转检测**——连续两圈 tool_calls 签名集(工具名+参数哈希)完全相同 → `loop_halt{spinning}`,用台账指纹做确定性外部裁判,零 LLM 调用(无外部反馈的纯自省在推理任务上不升反降,不靠模型自查);**烧签名**——同一(工具,参数哈希)失败三次标 burned,后续直接拒,防烧预算。到顶一律如实上报给用户,不静默截断、不抛裸异常。

### 1.4 错误自纠

工具失败包装成指导性错误喂回(继承现状 `_dispatch_one` 的包装,强化文案):`[ERROR] 错因:ts_code 格式应为 600519.SH。下一步:修正后重试,或用 web_search 先查代码`。模型带修正在下一圈重试;同签名两次内允许(改参数=新签名,计数重置,鼓励换法不死磕),第三次烧掉。

---

## 2. LLM 层扩展与上下文工程

### 2.1 `LLMService.stream_step`(唯一底座扩展)

旧 `chat(prompt) -> LLMResponse` 不动(research / 压缩摘要 / Judge / 标题生成继续用)。新增:

```python
async def stream_step(*, messages: list[dict], tools: list[dict] | None,
                      tool_choice: str = "auto", tier: Tier = "balanced",
                      request_id: str | None = None,
                      on_delta: Callable[[StepDelta], Awaitable] | None = None,
) -> StepResult   # {content, tool_calls, finish_reason, usage, cost_cny}
```

- `_OpenAIAdapter`:`stream=True` 迭代 chunk,累积 `delta.content` 与 `delta.tool_calls[i].function.arguments`(参数是跨 chunk 分片到达的 JSON 串,按 index 拼接——实现最磨人处);`stream_options={"include_usage":True}` 拿流式 usage 供预算闸;
- 成本 / trace 复用 compute_cost + CostBudget + 每圈一个 span(tool_calls 进 metadata,**新增记录 `cached_tokens` 做缓存命中率一等指标**);
- MockLLMClient 加脚本化多圈 mock(L1 测试用)。

**冒烟测试清单(实施第零步,任何循环代码动工前)**:① qwen 接受 `tools=` 且返回 `finish_reason=="tool_calls"`;② 流式 tool_call 分片形态;③ 一次回复多个 tool_calls(圈内并行);④ thinking 模式下工具轮 reasoning 是否必须回传(OpenAI 有此约束,不能想当然套 qwen);⑤ 流式 usage 可得;⑥ DashScope 隐式缓存真实命中(`cached_tokens` 回包)与计费口径核实;⑦ `tool_choice="none"`(熔断收尾依赖);⑧ 瘦 schema(开放参数声明)接受度。

**降级路径**:若 ① 失败,stream_step 内部改用 JSON 约束输出解析出同样的 StepResult——**循环及以上与 LLM 协议解耦于 StepResult 这一层**,降级只换内部实现;若 ⑦ 失败,收尾圈不传 tools 参数(协议允许,代价是该圈前缀缓存 miss 一次,可接受)。

### 2.2 窗口分区(按 KV-cache 与位置工程排序)

```
┌ 稳定前缀区(逐字节恒定,吃隐式缓存)─────────────────────┐
│ system₁:角色 + 工具纪律 + 记忆/知识库启发式(全用户共享)        │
│ system₂:persona(用户私有,会话内冻结;只放稳定部分:偏好/风险   │
│         画像/持仓标的清单——会过期的现价市值不进前缀,走行情工具) │
│ system₃:技能元数据清单(7 个技能 × 约 100 token)               │
│ tools:工具 schema(会话内绝不增删;三组渐进披露见 § 3.2)        │
├ 历史区(压缩边界后稳定)────────────────────────────┤
│ [对话摘要](一旦生成不再变,可被缓存)+ 最近 4 个 turn 原文        │
├ 本 turn 轨迹区(append-only)───────────────────────┤
│ user 问题 + assistant(tool_calls)/tool 消息对逐圈追加             │
│ (老圈大工具结果降级为 [已缓存@键]+摘要,消息骨架与配对不动)       │
├ 尾部动态区(每圈重写,只 miss 这一小段;也是召回最强位)────────┤
│ "第 N/12 步,预算剩 ¥x.xx" + 插话并入消息(若有)                │
└──────────────────────────────────────────┘
```

调研定调的三条铁律:**动态状态绝不进前缀**(每圈变一个字 = 从那个字起缓存全废,八路调研全票点名);**协议红线**——压缩/降级边界只许落在 user 消息前或完整工具序列后,降级只换 content 保留骨架与 tool_call_id 配对(切破对子 = 接口直接 400),用已处理消息标记集合防重复处理;**token 计数**——优先用 DashScope usage 回包真实值回填,估算 fallback 用中文每 1.65 字符一个 token(qwen 官方口径;现状会话内存的 2.5 系数系统性低估三到五成,独立于本设计也该修)。

### 2.3 压缩(两级,对齐任务边界)

| 级 | 触发 | 行为 |
|---|---|---|
| 跨 turn | rebuild 时估算超 70% 软阈值:**等本圈工具链跑完再压**(压在子任务中段是头号工业抱怨);90% 硬阈值强制 | LLM 总结老 turns 写入会话上下文表;结构化摘要模板:用户意图 / 已确认关键事实 / **每个定量数字带口径来源原样保留** / 错误与解法 / 未决问题 / 下一步 |
| turn 内 | 老圈工具结果超约 800 token | 降级为占位符 + 摘要 + 缓存键,模型可经 read_cached_result 取回(可逆,不是截断) |

**保护名单永不降级**:用户原始指令、失败轨迹(模型自纠靠读失败原文)、升级物料、关键定量数字、**活跃技能方法论**(见 § 3.4)。

### 2.4 ToolLedger(窗口外台账)

`{step, tool_name, args_hash, digest, success, cache_key, ts}` 的 append-only 列表,不进 LLM 窗口。一个抽象三用途:turn 内去重(查过的签名直接回缓存摘要)、打转指纹与烧签名、升级物料供给(EscalationExtractor 的 cached_tool_results 来源)。

---

## 3. 周边接线

接线总原则:**能建模成工具的全变工具,例外要有理由**——例外判据是 MCP 三原语的控制权分界:模型该决策何时用的做工具;应用该当背景喂的做注入(persona 即此类);用户该显式触发的留给前端。

### 3.1 工具清单:14 + 1 个

8 个金融只读(零改)+ memory_search / memory_write(六件套合并,见 § 3.3)+ load_skill / run_skill_script(三件套合并)+ offer_deep_research + read_cached_result + search_tools(§ 3.2)。

从最初 19 收敛到 14 的依据:阿里云官方红线"单次不超过 20 个工具"贴线 + 真杀手是语义重叠簇(六个记忆工具命名同族是最高危混淆区)。列表顺序按位置偏置:高频在前,read_cached_result 垫底。

**description 是一等设计物**,统一模板(关键规则前置):`[功能一句话]。何时用:[触发场景+金融触发词]。何时不用:[反例→指向相邻工具]。[硬约束]`。退役的记忆/知识库路由节点的"智能"全部活在 kb_search 与 memory_search 这对互斥描述里("公开市场信息" vs "用户个人的持仓/偏好/历史说过的话")。

### 3.2 工具渐进披露(一等设计,用户裁决)

tools 参数三组、会话内恒定:

- **核心组(6,完整 schema)**:get_stock_quote / financial_statements / kb_search / memory_search / load_skill / offer_deep_research——高频数据工具 + 控制关键工具;
- **延迟组(8,瘦条目)**:名字 + 一句话触发描述 + 开放参数声明(每个约 30-60 token);
- **search_tools(1)**:BM25/关键词确定性检索(零 LLM),返回目标工具完整使用文档(参数 schema + 硬约束 + 示例 + 何时用/不用),以 tool_result 进 messages(append-only,不碰 tools 参数,不破缓存)。

裸调延迟工具参数错 → dispatch 按真实 schema 校验 → 喂回"请先 search_tools('×') 获取参数文档" → 自纠回路接住。同 turn 已检索文档由台账记录,重复检索直接回缓存。

这个设计解开"描述要写厚 vs 常驻 token 要省"的矛盾(厚的进按需文档,零常驻成本),并使增长就绪:新数据源 = 一个瘦条目 + 一份文档;工具 14 → 40,常驻块只涨约 1.5K token。与技能渐进披露(元数据常驻 + 正文按需)形成对称结构。核心组圈定用现有工具调用统计数据驱动调整(配置生效于部署,会话内不变)。

诚实标注:14 个工具启用此机制低于工业"值得"阈值的典型场景,代价是延迟组每 turn 首次使用多一圈往返;这笔账在"工具必然增长"的产品预期下成立,机制总成本约百行。

**增长设计纪律**:加能力前先问是数据源、方法论还是确定性计算——只有数据源配新工具名额;方法论进技能(约 100 token 元数据),计算进技能脚本(零名额)。

### 3.3 记忆:双轨 + 合并 + in-process

**读**:persona 开场确定性注入稳定前缀(复用 populate_persona_on_session_start),会话内冻结,更新走新 turn 边界;长尾记忆 = memory_search 工具按需调,system 纪律写明"涉及持仓/偏好/历史观点先查记忆"。记忆/知识库路由节点整个退役。

**写**:cross-turn 异步抽取管线(Path B)触发点与内部零改;模型主动写经 memory_write。

**合并 schema**:

```python
memory_search(query, scope: archival|recall|graph = archival, k=5)
memory_write(action: core_append|core_replace|archival_insert, content,
             block=None, old_content=None, evidence_quote=None)  # 条件必填,dispatch 校验
```

注入分类器收口:模型侧写流量唯一入口 memory_write 的 dispatch 分支(防护面从四个入口收窄到一个);evidence_quote 逐字校验保留。条件必填填错 → 指导性错误喂回自纠。

**部署形态**:六个方法包装成 in-process Tool 注册 ToolHub(worker 已持 HierarchicalMemory 实例);`profile="memory"` 的 MCP 子进程代码保留但 chat worker 不再启动。该不该进 MCP 的判据:碰 harness 内部状态(记忆实例/loop state/SSE)的工具 in-process,纯外部数据连接的走 MCP——与 Claude Code 内建 vs MCP 的分界同构。

### 3.4 技能:图回环 → 工具循环

- 元数据清单(7 个技能名 + 触发描述)进稳定前缀;描述写成触发判据("当用户问持仓风险/集中度/回撤/敞口时使用"),第三人称,技能间边界互斥;
- `load_skill(name, resource=None)`:返回 SKILL.md 全文 + 附属资源清单(目录页设计);资源引用强约束一级深;专用图节点与回环边消失,渐进装载由循环天然承载;
- **活跃技能方法论不降级**(三路调研一致判定原"可降级"为最危险设计):当前任务在用的 SKILL.md 全文常驻;切换技能后旧方法论才降级,降级时硬规则条款保留原文,配"历史方法论勿重新执行"标记。认知更正:技能失效通常不是内容被压,而是模型选了别的路——第一对策是强化描述;
- `run_skill_script`:独立工具(执行语义不同);失败回喂结构化三元组(stdout/stderr/return_code)+ 错误码枚举(超时/输出超限),脚本内部自带错误处理,大输出强制写缓存返回摘要+键;
- "该装载没装载"守护:描述工程 + 触发离线评测(每技能 ≥3 条金标准 query,含共享关键词的近似负例,训练/验证切分)+ 尾部动态区可选相关技能提示(中文不用子串匹配);
- 清单生成抽成函数,写死逃生口:技能 ≥15 或选错率抬头时切两层(高频常驻 + 其余检索)。

### 3.5 升级深度研究:信号工具 + 熔断收尾

```
模型调 offer_deep_research(reason)
→ dispatch:幂等(同 turn 第二次拒) → 置 escalate_offered + SSE escalate_request
→ tool_result:"escalation_proposed=true。本轮工具通道已关闭,请基于已有信息简要作答。"
→ 下一圈 tool_choice="none"(代码强制,非文案自律)→ 模型流式收尾 → 自然停
→ finalize 后跑 EscalationExtractor(history=messages, cached_tool_results=ledger 视图)
→ create_draft → SSE escalate_packet_draft → 确认框 / POST /chat/escalate / research 子图零改
```

全链路唯一真改动:Extractor 物料来源从 state.tool_results 换成台账(自带去重 + cache_key 不可编造)。

---

## 4. 持久化与恢复

### 4.1 真相分层

| 层 | 内容 | 备注 |
|---|---|---|
| PG chat_messages | 对话唯一真相(user/assistant/工具卡片) | 零改 |
| PG chat_tasks | 六状态生命周期 | 停写 langgraph_checkpoint_id(列保留标死字段) |
| PG **chat_session_context(新表)** | history_summary + summarized_upto 水位 | create_all 只建新表不 ALTER,合规 |
| PG ToolResultCache | 工具结果原文(取回源 + 重跑命中源) | 零改 |
| Redis Streams | LoopEvent 投影,SSE 转发与重连 | 零改 |
| Redis **chat:steer:{tid}(新,List)** | 待并入插话 | turn 内 |
| 内存 ChatLoopState | 本 turn 全部状态 | **不持久化**——turn 原子语义下中间圈状态无消费者 |

### 4.2 跨 turn 重建

`rebuild_context(session)` = 摘要(若有)+ 最近 4 turn 的 user + assistant 终答 + 本 turn 输入。**老 turn 的多圈工具轨迹不重建**(终答已是结晶;要旧数字则重调工具 cache 命中,或 read_cached_result)。压缩在 rebuild 时触发,水位防重复总结。

### 4.3 取消 / 重试 / 插话 / 自愈

- **取消**:现有 pub/sub 零改;检查粒度变细(圈边界 + LLM 流式 delta 间 + gather 后);已流出文字落库标 partial——**仅供展示,不是恢复点**;
- **重试**:整 turn 重跑。端点删"checkpoint 非空"守卫(worker 路径上它本来就是坏的);输入 = 原 user 消息 + 该 turn 已并入的全部插话(行为不漂移);历史取到上 turn 为止(partial 不进窗口);工具全 cache 命中,真实重花只有 LLM 调用;
- **插话(steering,新链路)**:前端 streaming 中发送 → `POST /chat/steer/{task_id}` → ① 先落库 chat_messages(崩溃/重跑不蒸发)② LPUSH steer List ③ task 已终态则转普通新 turn。worker 圈边界 RPOP 全部 pending 按序并入 messages 尾部 → SSE steer_merged。**List 不用 pub/sub**:worker 在流式输出的几秒里不在监听,pub/sub 会丢,插话不可丢;cancel 保持 pub/sub(丢了用户会再按);
- **崩溃自愈**:stale scanner 零改 → 标 partial → 重试按钮 → 整 turn 重跑。比现状更诚实(现状声称 checkpoint resume 实际半残)。

### 4.4 final_state 简化红利

`final = await tool_loop.run(state)` 函数返回值直接进 finalize——老路径"事件流捞 on_chain_end + 节点名匹配 + aget_state 再查"三接缝一起消失,direct_response 补发 hack 随之删除。

---

## 5. SSE 协议、前端、测试评测、迁移

> 本节以后端为主;前端改动刻意收敛为适配性(事件映射 + 一个新交互),量小。

### 5.1 SSE 事件(统一信封 {type, seq, step, ts, data})

新增:`step_start{step,max_steps}` / `tool_call{step,tool,args}`(替代 plan)/ `tool_error{error,hint}` / `steer_merged{preview}` / `loop_halt{reason}` / `approval_request`(留口);扩展:`tool_end` 加 cached 标志、`cost_update` 加 cached_tokens;沿用:token / tool_start / skill_load / escalate_* / done / error / cancelled / error_done。传输层(XADD/XREAD/重连/终止判定)零改。

**前端改动**:dispatchEvent 删 plan 分支、加五个新分支;ToolCallCard 加 cached/error 样式;StreamingIndicator 的 phase 推导从节点名改事件类型;InputArea streaming 中发送默认走 steer、菜单可选排队为新消息。

### 5.2 测试与评测

- **L0**(纯函数):四道闸谓词 / 打转 / 烧签名 / 窗口分区与配对红线 / 压缩边界 / 熔断 / 插话顺序;
- **L1**(MockLLMClient 脚本化多圈 + 真 PG):持仓多跳 / 报错自纠 / 裸调延迟工具自纠 / 插话改向 / 撞闸收尾 / 升级熔断;
- **L2**(cassette):单工具 / 多跳 / 升级三条主路径重录;**差分 golden 三条 turn 原子语义**(取消 partial 仅展示 / 重试含插话 / steer 竞态转新 turn);
- **冒烟测试 8 项是实施第零步的闸**;
- **评测换靶**:SUTOutput 的 tool_calls 从台账抽(原从 plan 抽);新增工具选择专项(AST 比对 + 该调时调/不该调时弃权双指标 + memory/kb 分桶混淆 + 多轮口径)、技能触发评测、延迟工具三类 case;记忆路由评测换靶为"该查记忆时查了吗"(8 个 seed case 改造)。

### 5.3 实施分期(plan 的骨架)

```
0  冒烟测试 8 项(一切的闸,失败项触发既定降级路径)
1  LLM 层:stream_step + Mock 扩展(纯新增,独立可测)
2  chatloop 核心:循环 + 四道闸 + 窗口组装(L0 全绿)
3  ToolHub:MCP 接入 + in-process 记忆/技能 + 渐进披露 + description 全套
4  传输替换:chat_runner 换引擎 + 新 SSE + steer 端点 + retry 改造(切换点)
5  前端适配:事件映射 + steer 交互
6  评测收束:golden 迁移 + 新专项 + cassette 重录
7  退役清理:删老图 + claude-context 总卡沉淀
```

1-3 期不碰现有路径,4 期才切换,风险靠分支隔离。

### 5.4 退役清单

删除:`chat_graph.py` 整图 / `nodes.py` 三节点 / `context_node.py` / `memory_kb_router_node.py` / ChatPlanner.run chat 路径与 planner 模板 / Responder.run chat 路径 / Plan schema 的 chat 字段 / chat_runner 的事件适配与 token 补发 hack / chat 路径 checkpointer 接线。

保留:research 子图全套(ChatPlanner/Responder 的 step() 留给它)、LLMService.chat 旧接口、传输与持久化全部资产、前端框架。

---

## 6. 风险与降级汇总

| 风险 | 等级 | 缓解 / 降级 |
|---|---|---|
| qwen 原生 function calling 能力不达预期 | 高 | 冒烟测试前置;StepResult 解耦层,内部退 JSON 约束输出,循环不动 |
| 单 LLM 既决策又说话,参数保真度回退 | 中 | 工具 schema 强约束 + dispatch 校验喂回;工具选择离线评测守护;可按是否带 tools 分 tier |
| 检索式记忆冷启动(忘了查) | 中 | persona 确定性注入兜底 + system 纪律 + "该查没查"金标准评测 |
| 多圈成本/延迟高于单程双 LLM | 中 | 四道闸封顶;简单问题一圈自然停;ToolResultCache 去重;缓存命中率一等观测 |
| 破坏性替换回归面 | 中 | 分期实施,1-3 期纯新增;差分 golden 锁行为;cassette 重录 |
| 打转检测只开精确环,漏语义环 | 低 | 上限闸 + 预算闸兜底必停;语义环留 flag,诚实标注为成本取舍 |

## 7. 作品叙事(为什么这套设计有深度)

把六节点框架图重构成自有控制流的原生工具调用循环,对标工业事实标准;四道终止闸 + 复利可靠性衰减的量化论据,闸触发是一等可观测行为;窗口四区分治直击 KV-cache 前缀经济学与 context rot 实证;万物皆工具的收敛美学(技能图回环塌缩成工具自然循环、路由节点降级为描述纪律)配上有据可依的例外判据(MCP 控制权分界);工具与技能的对称渐进披露为增长而设计;自纠依赖确定性外部裁判而非模型自省;每一处偏离工业主流的设计(如低于阈值启用延迟加载)都带着诚实标注的 trade-off。三轮共 20 路对抗核查调研沉淀为三份看板研报,设计裁决全部可溯源。
