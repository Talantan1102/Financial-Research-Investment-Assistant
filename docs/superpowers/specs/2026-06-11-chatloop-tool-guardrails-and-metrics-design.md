# Chatloop 工具护栏与对话账单 — 设计

> 日期:2026-06-11
> 范围:chatloop runtime 优化地图(`/eval/report/chatloop-runtime-optimization-survey`)里
> 判定为"现在就做、改动小、低风险"的三件——工具超时、工具结果上限、对话账单(度量)。
> 大子系统(完整 compaction、子 agent 隔离)与中等项(终止闸精度、插话粒度)不在本 spec,
> 等这三件落地跑出数据再回头。

## 1. 背景:为什么是这三件

研报对照工业界(Claude Code / Anthropic / OpenAI Agents SDK / LangGraph / Manus)审出 7 个
runtime 缺口。本 spec 只收其中三件,它们的共同点:**独立、改动小、低风险、不依赖 dogfood 数据
就能判断该做**。其余四件要么是子系统级(等数据),要么涉及语义重新定义(插话/取消)。

三件里 ② ③ 落在工具执行路径(`tool_hub._dispatch_one_inner`)、是同一族"工具执行护栏";
⑦ 落在 loop/state/events、是"把已有数据显出来"。

### 一个跨三件的事实底座(已核对真实代码)

生产里工具结果缓存是**全接通**的:`ToolResultCache(session_factory)`(PG-backed)在
`worker_wiring.build_turn_components` 注入进 ToolHub,且已注册 `ReadCachedResultTool` 让模型
凭 ref 取回全文。`tool_hub` 去重命中路径与 `context.py` 老消息降级都已在用
`{cached_digest/note/ref}` 这套形状 + `ref=cache_key`。**② 的"截断后回指针"因此是复用既有闭环,
不是新建机制。**

---

## 2. ③ 工具超时

### 决策

单一默认超时(30s)**只施加给数据类(MCP/registry 后端)工具**;in-process 工具
(记忆/技能/控制类)**豁免**。Celery 任务级超时作为兜底。

### 为什么这样

- `dispatch` 已是 per-call 并行:每个 call 一个独立 `_dispatch_one` 协程,`asyncio.gather`
  收齐(`tool_hub.py:221-223`)。所以超时天然是 **per-call 粒度**——一个工具超时不拖累同圈
  其他工具(研报担心的"整 gather 超时误伤同圈快工具"在本架构下本就不存在)。
- `_guidance_error` **已有** `asyncio.TimeoutError/TimeoutError → "[超时] 稍后重试或换数据源"`
  的映射(`tool_hub.py:444-445`)。给执行包一层 `wait_for`,超时会**自动落进现成的指导性错误
  路径**(记账 / `tool_error` 事件 / 喂回模型自纠),无新机制。
- in-process 豁免的理由:它们是本地操作 + **状态变更**(`memory_write` / `load_skill` /
  `offer_deep_research`)。给状态变更工具加硬超时会撞研报点名的坑——超时≠没执行,模型重试
  可能双写。豁免直接绕开这个语义难题;它们也不是"网络无限挂起"的风险源。真有 in-process
  慢(如记忆写涉及重活)是"该转异步"的问题,不是超时该解的。

### 落点

`tool_hub._dispatch_one_inner` step 5(`tool_hub.py:308-333`)。现状:

```python
if self._cache is not None and not is_inprocess:
    output, cache_status = await self._cache.get_or_compute(...)   # 数据工具走缓存
else:
    output = await _compute()                                      # in-process / 无缓存
```

改为:数据工具分支(`not is_inprocess` 那条)用 `asyncio.wait_for(..., timeout=T)` 包住;
in-process 分支保持裸 `await`(豁免)。超时抛 `TimeoutError` → 现有 `except BaseException`
分支 → `_guidance_error` 出"[超时]"文案。

- 超时常量:`ToolHub` 构造参数 `tool_timeout_s: float = 30.0`(模块级默认常量;
  `build_turn_components` 造 hub 时不传即用默认);可配但单值,不分档(YAGNI;分档等真有
  证据某类工具需要不同阈值再说)。
- `search_tools` 内置工具是本地确定性检索,不包超时(与 in-process 同理)。

### 边界 / 测试

- 数据工具超时 → 返回 `success=False`、error 以 `[超时]` 开头、记一条 fail 台账、发 `tool_error`。
- 同圈一个工具超时、另一个正常 → 正常那个结果不受影响(per-call 隔离)。
- in-process 工具耗时超过 30s → **不**被超时打断(豁免验证)。
- 超时的工具签名累计失败,与烧签名机制叠加(连续失败 3 次熔断,现有行为)。

---

## 3. ② 工具结果上限

### 决策

只截断**有 cache ref(能取回全文)的**成功结果;阈值默认 **4000 字符**,放进 `ContextDeps`
可配。取不回的(无 ref)**不截**,留全文 + log 警告。

### 安全不变量(本设计的核心)

**绝不截断取不回的内容。** 没 ref 就不截——宁可那一次大一点,也不给模型一个取不回的死指针、
更不丢它刚要来的新数据。这条不变量同时白送两个好处:

1. **无需让 loop 认识工具类型。** loop 只拿到 `ToolResult`,不知道 in-process vs MCP。
   但"有没有 ref"恰好是完美代理:in-process 工具 `cache_key=None` → 无 ref → 自动豁免;
   `load_skill`(技能方法论不可截)→ 无 ref → 自动豁免;测试无缓存 → 不误伤。
2. 那条"有大输出却没 ref"的 log 警告,反而成了"该给哪个工具补缓存"的信号。

### 为什么落在 loop 而不是 hub

数据流:hub 造 `ToolResult(output=全量,含 figures)` → loop `_extract_and_emit_charts`
**剥离 figures**(figures 走 chart 事件旁路,几 KB,绝不进窗口,`loop.py:203-224`)→
`apply_results` 把 output json.dumps 成 tool 消息。

figures 在 hub 之后才剥。若在 hub 量体积,figures 会虚高、误触发截断。所以 ② 必须落在
**剥完 figures 之后**量"真正进窗口"的体积——直接并进 `_extract_and_emit_charts` 那趟遍历
(剥 figures → 量大小 → 超限截断),同一类"把工具输出整形成喂给 LLM 的样子"的活,单趟完成。

### 落点

`loop._extract_and_emit_charts`(`loop.py:203-224`)末尾,对每个 `r`(成功、dict 输出、
figures 已剥)追加:

1. 量 `len(json.dumps(r.output, ensure_ascii=False))`,≤ 阈值跳过。
2. 反查 ref:`state.ledger.find_success(tool_name=r.tool_name, args=r.args)` → `entry.cache_key`
   (与 `context.py:151` 降级同款查法)。`cache_key is None` → 跳过(不截,log 警告)。
3. 截断:`r.output` 换成
   ```python
   {"truncated_digest": <前 ~600 字>,
    "note": "结果过大已截断,完整内容见 ref,需要更多可调 read_cached_result 取回",
    "ref": cache_key,
    "original_chars": N}
   ```

阈值:`ContextDeps` 加 `oversize_result_char_threshold: int = 4000`(与现有
`downgrade_char_threshold=1320` 并列;4000 ≈ 6 条 KB chunk,够模型判断命中、远高于老消息
降级线;上线后按 trace 里结果体积分布调)。`_extract_and_emit_charts` 需能拿到该阈值——
ContextDeps 已注入 loop(`self._deps`),直接读。

注:`_extract_and_emit_charts` 职责从"抽图"扩为"输出整形(抽图 + 控大小)",方法可改名
`_shape_tool_outputs` 或保留原名加注释;二选一在实现时定,不影响设计。

### 边界 / 测试

- 12000 字 KB 结果 + 有 cache_key → 截成 ~600 字 digest + ref;本 turn 后续圈只重读 ~600 字。
- 截断后模型调 `read_cached_result(ref)` → 取回全文(端到端验证闭环)。
- 大输出但 `cache_key=None`(模拟无缓存/in-process)→ **不截**,全文留存,log 一条警告。
- figures 大但正文小 → 剥 figures 后正文不超阈值 → 不截(验证 figures 不计入体积)。
- `load_skill` 输出超 4000 字 → 不截(无 ref 自动豁免)。
- 失败结果(error)→ 不进截断路径(只整形 success+dict)。

---

## 4. ⑦ 对话账单(度量)

### 决策

算全:① state 加两个累计器解锁缓存命中率 → ② turn 汇总塞进现有 `done` 事件(**不新增事件
类型**)→ ③ `cost_update` 加单圈 delta → ④ 加"稳定前缀逐字节恒定"CI 回归测试。
token 估算回校 loop、看板/告警接线**留 follow-up**(本轮只把数据发出来,消费是后续)。

### 为什么必须加 state 累计器

缓存命中率 = `cached_tokens / prompt_tokens`,是验证"窗口四区稳定前缀"这个核心省钱设计
有没有生效的唯一数字。但现状 state 只有 `budget_spent_tokens`(= prompt+completion 混在一起,
拆不开,`state.py:186`),每圈的 `cached_tokens` 只在 `cost_update` 事件里飞过、从不入 state。
**所以现在这个核心指标根本算不出来。** `StepResult` 每圈其实都有
`prompt_tokens/completion_tokens/cached_tokens/cost_cny`(`llm_step.py:43-52`),只是没累计。

### 落点

**(1) state 累计器** — `state.py` `ChatLoopState` 加字段 + `apply_step` 累加:
```python
# 字段
prompt_tokens_total: int = 0
cached_tokens_total: int = 0
completion_tokens_total: int = 0   # 顺带,turn 汇总要拆 prompt/completion
# apply_step 内,紧随现有 budget_spent_tokens 累加之后
state.prompt_tokens_total     += step_result.prompt_tokens
state.completion_tokens_total += step_result.completion_tokens
state.cached_tokens_total     += step_result.cached_tokens
```
`budget_spent_tokens` 保留(其它地方在用),不动其语义。

**(2) done 事件加 turn 汇总** — `done` 的 `data` 是开放 dict(`LoopEvent.data: dict`),
往里加键是纯增量、不动 `EventType` 闭集、不破坏前端契约(不认的键自动忽略)。两处发 done
(`loop.py:174` 自然停 / `loop.py:299` 强制收尾)统一走一个 `_turn_summary(state)` 助手:
```python
def _turn_summary(state) -> dict:
    p = state.prompt_tokens_total
    return {
        "cost_cny": round(state.budget_spent_cny, 4),
        "llm_calls": state.step,
        "tool_calls": len(state.ledger.entries),
        "prompt_tokens": p,
        "completion_tokens": state.completion_tokens_total,
        "cached_tokens": state.cached_tokens_total,
        "cache_hit_rate": round(state.cached_tokens_total / p, 3) if p else 0.0,
    }
# 发 done 时:data = {"stop_reason": reason, **_turn_summary(state)}
```
escalate 链路里 runner 补发的那个唯一 done(`chat_runner`,修法 A)也带上同款汇总:loop
`run()` 把 final state 返回给 runner,runner 在补发 done 处对该 state 调同一个 `_turn_summary`
(助手提到 `state.py` 或 loop 模块级,两边共用,实现时定位置)。

**(3) cost_update 单圈 delta** — `loop.py:159-165` 现状只发累计 `cny/tokens/cached_tokens`。
追加单圈字段(数据现成,来自本圈 `step_result`):
```python
await self._emit("cost_update", state.step,
    cny=state.budget_spent_cny, tokens=state.budget_spent_tokens,
    cached_tokens=step_result.cached_tokens,                      # 现有
    step_cost_cny=step_result.cost_cny,                           # 新增
    step_prompt_tokens=step_result.prompt_tokens,                # 新增
    step_completion_tokens=step_result.completion_tokens)        # 新增
```
用途:某圈落了超大工具结果把 prompt 撑爆时,`step_prompt_tokens` 一眼定位是哪圈。

**(4) CI 回归测试** — 断言 `assemble_context` 的区一(system 消息)在连续两圈逐字节相同:
```python
def test_stable_prefix_byte_identical_across_steps():
    m1 = assemble_context(state, deps)
    state = apply_step(state, step_result_round1)
    m2 = assemble_context(state, deps)
    assert m1[0] == m2[0]   # 区一 system 消息逐字节相同 → KV-cache 前缀稳定
```
有人哪天往 system_prompt/persona 塞了会变的东西(时间戳/计数器),这条 CI 立刻红,赶在它
线上悄悄毁掉两折缓存之前。

### 边界 / 测试

- 跑完多圈 turn → done.data 含 cost/llm_calls/tool_calls/prompt/completion/cached/hit_rate,
  且 `cache_hit_rate ∈ [0,1]`、`prompt_tokens=0` 时 hit_rate=0(不除零)。
- 自然停 done 与强制收尾 done 都带汇总(两条路径一致)。
- cost_update 单圈字段 = 该圈 step_result 对应值;累计字段单调不减。
- CI 前缀测试:正常恒定 → 绿;人为往 system_prompt 注入 `state.step` → 红(测试有效性自证)。

---

## 5. 测试计划汇总

| 件 | 新增/改动测试 | 层级 |
|---|---|---|
| ③ | 数据工具超时→[超时]错误;同圈隔离;in-process 豁免;超时叠加烧签名 | 单测(hub) |
| ② | 大结果+有ref→截断;read_cached_result 取回;无ref→不截+警告;figures不计体积;load_skill豁免 | 单测(loop 整形) |
| ⑦ | done 汇总字段齐全+hit_rate边界;两条done路径一致;cost_update单圈delta;**稳定前缀CI** | 单测(state/loop)+CI |

全部走现有 chatloop 单测惯例(L0/L1,真 PG 由 `db_session` fixture,见测试 DB 策略卡)。

## 6. 显式不做(本轮)

- 完整 compaction(整段历史压缩重开)——子系统级,等 dogfood 数据。
- 子 agent 上下文隔离——子系统级,等"撞步数上限 turn 占比"数据。
- 终止闸精度(打转漂移检测 / 预算圈中预检)、插话粒度——中等项,下一批。
- token 估算回校 loop(用真实 usage 反推系数)——周期性离线 job,独立。
- 缓存命中率看板 / 告警接线——持久化/UI scope,本轮只发数据,消费留后续。

## 7. 风险与取舍

- **③ in-process 豁免留了一个理论 hang 口**(记忆写若涉重活)——接受:Celery 任务级超时 +
  用户可取消 兜底;真慢是"转异步"问题,不归超时管。
- **② 无 ref 不截 → 理论上某次窗口可能偏大**——接受:生产 MCP 数据工具全有缓存,现实膨胀源
  都能截;无 ref 的大输出是边角,且 log 警告会暴露它。安全优先于"不惜代价压窗口"。
- **② 阈值 4000 是拍的起点**——可配,上线后按 trace 体积分布调;偏大顶多少截几次,偏小会多
  几次取回往返,都不致命。
- **⑦ 复用 done 而非新事件**——选了非破坏性的加字段;代价是语义不如专门事件显式,但前端零改动,
  符合本项目最小化调性。

### ②③ 的阈值"等体验再调",数据出处就是 ⑦

② 的 4000 字、③ 的 30s 都是保命起点,刻意做成配置项(`ContextDeps` 字段 / `ToolHub` 构造参数),
调它们是改一个默认值、不动逻辑。而"真实体验"的数据来源正是本 spec 的 ⑦:
- **② 阈值**看 ⑦ 账单的**单圈 prompt 用量**(`cost_update.step_prompt_tokens`)——哪一圈被超大
  工具结果撑爆一眼可见,据此判断 4000 该调大还是调小、截得太频还是漏得太多。
- **③ 超时**看 trace 里工具延迟分布——30s 是否经常误杀正常的慢查询。
故三件一起上线后,⑦ 自身就把 ②③ 的调参依据喂出来了,形成"度量→调参"闭环,不靠拍脑袋。
