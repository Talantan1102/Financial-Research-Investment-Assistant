# Chat Loop 上下文压力安全阀 设计(决策点①)

> 来源:`dashboard/data/reports/chatloop-runtime-optimization-survey.yaml` 决策点①(上下文溢出与压缩)。
> 本 spec 只覆盖①里**现在就该做、改动小**的那块:总量压力安全阀。研报开的"第二步(跨 turn clearing)"经核对对本架构是空方子(见下),"完整 compaction"(第三步)等 dogfood 数据,本次都不做。

## 现状核对(为什么只做这一块)

研报①给了三步药,代码审读后:

- **第二步「把跨 turn 压缩改成 Anthropic clearing 同款:清旧工具结果、保留最近 N 个」**:对本架构是**空方子**。`rebuild.py` 的跨 turn 历史**压根不带工具结果**——老 turn 只保留 assistant 结晶终答 + 一个滚动摘要,最近 4 轮原文永远保留(`RECENT_TURNS=4`)。"清旧工具结果"在跨 turn 这里没有对象可清;它真正对应的是 turn 内 `context.py` 的降级,而那个**已经在跑**。不动。
- **第三步「完整 compaction(窗口满了让模型把历史总结成块、重开)」**:等 dogfood 数据显示真实对话经常逼近窗口才值得做,且会引入新摘要 LLM 调用。本次不做。
- **第一步「token 总量预估检查 + 动态降级」**:**真正的缺口,本次做**。

## 缺口与场景

现在的降级(`context.py:_downgrade_old_tool_messages`)按**单条大小**触发:一条 tool 消息 content 超 1320 字符才换成 `[全文已缓存 ref=...] + 200 字摘要`。问题是**没有任何人看"拼完一圈的总量"**。

具体场景:

```
用户问"分析宁德时代",模型一圈里同时调了三个工具——
财报查询(返回 ~1000 字)/ 同业对比(~1000 字)/ 知识库检索(~1000 字)。
每一条都没到 1320 字降级线 → 一条都不降级。
但三条 + 跨 turn 历史 + 系统提示拼起来,这一圈发出去的请求悄悄超过模型窗口。
用户看到的不是"内容被压缩了",而是一个莫名其妙的请求报错,整个 turn 报废。
```

很多"中等个头"的消息能合谋把窗口撑爆,而按单条阈值的降级一次都不响。这就是研报 setup 里"请求直接报错"那一幕。

**注:大窗口模型下"真溢出"是低频事件**(与用户对齐:单轮输入几十 k 不是问题)。本安全阀的主价值其实是**成本**:窗口装得下时,每转一圈把前面几千字老结果**原样全价**再发一遍,转五六圈就是同一份大结果被全价计费五六次;按总量触发的降级把这个反复全价重发压下去。它是个**只在压力真大时才启动的安全阀**,平时不响。

## 改动:总量压力安全阀(单点,在 `assemble_context` 内)

**核心**:把降级从"单条阈值"升级成"按总量收紧的压力闸",**全程不删消息、不丢可恢复内容**(降级永远留 `ref=`,全文还在缓存里能取回),**最近一圈永远全文保护**(放弃边缘情况的激进手段,与用户对齐)。

**机制(在 `assemble_context` 里,降级与拼装之间)**:

1. 先按基准阈值(`downgrade_char_threshold=1320`)降级一次(现状,不变)。
2. 拼出四区 `result`,估算总 token(`estimate_tokens` 逐条求和,含 tool_calls 文本的粗估)。
3. 若 `max_context_tokens > 0` 且 `总量 > context_pressure_ratio * max_context_tokens`(默认 0.85,留 completion 余量):进入收紧循环——
   - 把降级阈值**减半**(下限 `downgrade_floor_threshold=200`),用更小阈值再降级一遍(老圈里更小的结果也被降级;`downgraded_msg_indices` 幂等,已降的跳过);
   - 重拼、重估;
   - 直到 `总量 ≤ 目标` 或 `阈值已到下限`。
4. 收紧循环每多跑一轮,`state.context_pressure_passes += 1`。
5. 退出循环后若**仍超目标**(榨干所有老圈到下限还塞不下,大窗口下几乎不可能):置 `state.context_pressure_floor_hit = True`,**best-effort 照发**(不硬截断、不动最近一圈、不报 RuntimeError)。

**`max_context_tokens` 来源**:`ContextDeps` 新增字段,默认 `0`(= 安全阀关闭,保持 `subagent` / 既有测试行为不变);`chat_runner` 构造 `ContextDeps` 时从 settings 传入模型窗口实际值。

**压力信号上抛**:`assemble_context` 不发事件(它无 emitter,且 force_conclude / subagent 也调它)。改在 `state` 上记账:每次 `assemble_context` 开头把 `context_pressure_passes` 重置为 0、`context_pressure_floor_hit` 重置为 False;收紧时累加。`loop.run()` 在 `assemble_context` 之后读到 `passes > 0` 即 `_emit("context_pressure", step, passes=..., est_tokens=..., ceiling=..., floor_hit=...)`——喂 ⑦ 看板,让"有对话在逼近窗口/在反复降级烧钱"可观测、可归因。

## 不变量(已验证)

- **不删消息、不动 role/tool_call_id**:只改 tool 消息的 content(降级现状红线),收紧只是把这条红线用更小阈值多跑几遍。OpenAI 协议(assistant(tool_calls) 后跟全部 tool 消息)不破。
- **最近一圈永远全文**:收紧循环只调既有 `_downgrade_old_tool_messages`,它本就保护 `_last_round_boundary` 之后的消息;阈值再小也不碰最近一圈。
- **失败消息 / load_skill 永不降级**:既有保护名单不变。
- **幂等**:`downgraded_msg_indices` 保证同一条不重复降级;收紧用更小阈值只会**新增**被降级的条目,不回改已降的。
- **安全阀关闭时零行为变化**:`max_context_tokens=0`(默认)→ 跳过总量检查,等价于现状。`subagent.py` / 既有 `test_context.py` 不传该字段,行为不变。
- **不死循环**:阈值每轮严格减半且有下限,收紧循环至多 `log2(1320/200) ≈ 3` 轮即到底。
- **不引新 LLM 调用**:全程纯本地字符串操作 + token 估算,无网络。

## 测试策略

L0 单测(`backend/tests/unit/chatloop/test_context.py`),复用既有 `ChatLoopState` / `ContextDeps` 构造。

- `test_pressure_valve_off_by_default`:`max_context_tokens=0` → 多条中等 tool 消息全不降级,行为同现状(回归)。
- `test_pressure_valve_squeezes_old_rounds`:`max_context_tokens` 设小、构造多条"中等个头(<1320 但合计超窗)"的老圈 tool 消息 + 一圈最近的 → 断言:老圈中等消息被降级(content 变 `[全文已缓存 ...]`)、最近一圈全文不动、`context_pressure_passes > 0`、总量降到目标下。
- `test_pressure_valve_protects_recent_round`:最近一圈的大 tool 消息即便总量超标也保持全文(断言其 content 未变 + `context_pressure_floor_hit` 可能为 True)。
- `test_pressure_valve_floor_hit_best_effort`:只有最近一圈一条超大消息、老圈无可榨 → 收紧到底仍超 → `context_pressure_floor_hit=True` 且函数正常返回(不抛异常)。
- `test_estimate_messages_tokens`:总量估算 helper 的基本正确性(CJK/ASCII 混合)。

loop 侧(`backend/tests/unit/chatloop/test_loop.py`):
- `test_context_pressure_event_emitted`:注入会触发收紧的 deps/state → 断言事件流里有 `context_pressure` 事件且带 `passes`/`floor_hit` 字段。
- 回归:不触发收紧时无 `context_pressure` 事件。

## 验收

- `pytest backend/tests/unit/chatloop/ -q` 全绿(含新增 + 既有 test_context / test_loop 回归)。
- `ruff format --check` + `ruff check` + `mypy`(app + 测试文件)无新增问题。
- 不改任何既有事件 schema;新增 `context_pressure` 事件为纯增量。
- 浏览器实测:用专用队列 worker 起一轮多工具对话,确认正常对话不误触发安全阀、turn 正常收尾(安全阀本身大窗口下大概率不响,实测主要验"没引入回归")。
