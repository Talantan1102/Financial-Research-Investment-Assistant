# Chat Loop 分发前插话检查点 设计(决策点⑤)

> 来源:`dashboard/data/reports/chatloop-runtime-optimization-survey.yaml` 决策点⑤(插话与中断)。
> 本 spec 只覆盖⑤里**唯一仍有价值**的一块:分发前插话检查点。其余三条经核对已做或在本架构 non-issue(见下)。

## 现状核对(为什么只做这一块)

研报⑤给了 4 条建议,代码审读后:

- **rec 2「不做流式中途注入」**:本就不做(文本场景业界共识),保持现状,无改动。
- **rec 4「partial 落库统一以已发射 token 为准」**:**已实现**。`chat_runner.py` 有 `emitted_tokens` 累加器,`_finalize` 落库取 `max(len(final_text), len(emitted_text))`,取消在 apply_step 前抛也有兜底。
- **rec 3「有未消费插话时取消的语义未定义」**:本架构基本 non-issue。steer key = `chat:steer:{task_id}`,每 turn 一个新 task_id,TTL 1h;取消后残留插话自然过期,**不跨 turn 泄漏**(Claude Code 那个坑源于跨 turn 复用队列,本项目不复用)。不做。
- **rec 1「插话注入点加密到工具边界」**:本项目工具是**并行批量 dispatch**(`asyncio.gather`),"一批工具跑完"的边界 = 圈首(`loop.py:156` 的 pop_all 就在"上一圈工具批完成、下一次 LLM 前")。研报 rec 字面写的"gather 返回后、下次 LLM 前 pop_all"在本架构里就是圈首,等于没加。**真正的缺口**是另一处:插话在"LLM 已决定本轮工具、工具批尚未 dispatch"的缝隙到达时,没有检查点——本 spec 补这一处。

## 缺口与场景

`loop.run()` 当前每圈只在**圈首**(`loop.py:155-158`)`pop_all()` 一次。一个有工具的圈节拍:

```
t0      圈首 pop_all
t0-t8   LLM 流式输出,决定 dispatch 本轮工具
t8-t25  并行跑工具批(gather,以最慢工具为准)
t25     回圈首,下一圈 pop_all 才读到插话
```

用户在 t3(LLM 流中)插话"只看高端白酒,别碰区域酒企",要等到 t25 才被读到——这中间 t8-t25 整批(可能已不需要的)工具照跑,token 白烧,用户眼睁睁看模型在错方向上走完一整圈。

## 改动:分发前插话检查点(单点)

**位置**:`loop.run()` 中,`filter_burned`(步 11)→ 预算预检(步 11.5,④b)之后、`dispatch`(步 12)之前,插入步 11.6。置于预算预检之后:预算不足时已 force_conclude 返回,插话无意义。

**逻辑**:
```
allowed, _rejected = filter_burned(...)
if budget_margin_exhausted(...): ...return force_conclude     # 11.5 已有
steers = await self._steer.pop_all() if self._steer else []   # 11.6 新增
if steers:
    # 有插话:取消本轮工具批,把插话并入,回圈首让模型重新决定
    skipped = [self._steer_interrupted_result(c) for c in step_result.tool_calls]
    state = apply_results(state, skipped, step_result.tool_calls)  # 协议红线
    for msg in steers:
        state.messages.append({"role": "user", "content": msg})
        await self._emit("steer_merged", state.step + 1, preview=msg[:80])
    continue                                                  # 不 dispatch,回圈首重规划
results = await self._tool_hub.dispatch(allowed, state)        # 12 原样
```

**占位结果**:新增静态方法 `_steer_interrupted_result(call)`(仿 `_budget_skipped_result`),`success=False, error=_STEER_INTERRUPT_ERROR`;模块常量 `_STEER_INTERRUPT_ERROR = "用户插话,本轮工具未执行,请结合新指令重新决定"`(不带 `[ERROR]`,`apply_results` 会加)。

**为什么是"取消批+重规划"而非"等批跑完再注入"**:后者(=圈首现状)对改方向型插话省不下白跑的工具;前者把延迟从"整圈"缩到"当前 LLM 流"那段,并立省一整批工具。代价:追加型插话("也看负债率")会把刚决定的工具批也取消、多花一轮 LLM 重新决定(结果正确,仅多一次调用)。无法廉价区分两类插话,取"改方向型净赚、追加型小亏"的折中。

## 不变量(已验证)

- **占位结果不进 ledger**(ledger 仅由 `ToolHub.dispatch` 记账;此路径跳过 dispatch)→ 不影响 ④(a) `trailing_failure_count`、不误触发 `repeated_failures`。
- **协议红线**:assistant(tool_calls) 后每个 tool_call_id 必有 tool 消息——占位结果经 `apply_results` 逐一折叠保证。
- **被取消圈的 LLM 成本**已由步 7 `apply_step` 入账;重规划是新一圈,正常计步与计费。
- **不死循环**:每圈都有真实 LLM 调用推进 + `pop_all` 排空;`pop_all` 幂等(RPOP 循环,空则 []);`max_steps` 兜底。
- **圈首 pop_all 保留不动**:它负责"上一圈工具批执行期间到达的插话";新检查点负责"本圈 LLM 流期间到达的插话"。两点互补。

## 测试策略

L0 编排单测(`backend/tests/unit/chatloop/test_loop.py`),复用既有 `FakeLLM`/`FakeToolHub`/`FakeSteerSource`/`_Collector`。

**必须处理的回归**:新增分发前 pop_all 后,**每个有工具的圈调用 `pop_all` 两次**(圈首 + 分发前)。现有 `FakeSteerSource(per_round=[...])` 按"每圈一次"喂,会错位。改法:把 `FakeSteerSource` 改成按**调用序**喂(`per_call` 列表,第 N 次 `pop_all` 返回第 N 项,越界返回 []),同步改 `test_scenario_6_steering` 的喂值与断言(圈首注入仍走第 1 次调用)。

**新增**:
- `test_steer_predispatch_cancels_batch_and_replans`:第 1 圈圈首无插话、LLM 出 tool_calls,分发前 pop_all 返回 ["只看高端"] → 断言:该圈 `hub.dispatch` **未收到本圈调用**(`dispatched_calls` 对应位为空/批被跳过)、本圈每个 tool_call 有 `[ERROR]...未执行` 占位 tool 消息、发了 `steer_merged`、下一圈 LLM 被调用(重规划)、最终 natural 收尾。
- `test_no_steer_predispatch_dispatches_normally`:分发前 pop_all 返回 [] → 正常 dispatch(回归)。

## 验收

- `pytest backend/tests/unit/chatloop/ -q` 全绿(含改后的 scenario_6)。
- `ruff format --check` + `ruff check` + `mypy`(app + 测试文件)无新增问题。
- 不改任何事件 schema(复用 `steer_merged`);不动圈首 pop_all、预算预检、终止闸。
