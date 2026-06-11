# Chat Loop 终止闸精度修补 设计(决策点④)

> 来源:`dashboard/data/reports/chatloop-runtime-optimization-survey.yaml` 决策点④。
> 本 spec 只覆盖④的三件小改,不碰打转闸本体(连续两圈全同)与预算闸圈首逻辑——它们保持现状。

## 背景与缺口

四道终止闸(步数 / 金额·token 双预算 / 打转 / 自然停)覆盖面业界领先,但代码审读发现两处**精度**缺陷:

1. **打转漏检(乱试)** — 打转闸(`gates.py:29-35`)只比"连续两圈签名集合完全相同";烧签名(`burn_threshold=3`)只管**同一签名**失败 3 次。模型给查不到的标的换参数硬试(`query_kb(09988.HK)`❌→`query_kb(9988)`❌→`query_kb(BABA)`❌……)每圈签名都不同,**两道闸都不响**,直到烧满 `max_steps=12`。
2. **单圈预算超支** — 预算闸只在圈首检查(`loop.py:132`),而本圈 LLM 成本要等工具执行后的 `apply_step`(`state.py:189-190`)才入账。某圈 LLM 调用(大上下文)把累计成本顶过上限后,本圈仍照常分发工具、并触发又一轮 LLM,钱已花出。

研报里的第三件(c)"强制收尾文案带终止原因"经核对**已落地**(`loop.py:329` 系统消息含 `{reason}`,`loop.py:134` `loop_halt` 事件透传 `reason`),只剩"raw 代码对模型不够人话"这点尾巴。

## 不做(显式划界)

- 不改打转闸本体(连续两圈全同)——它抓"原地踏步",与新增的"连续失败"互补,各管一类。
- 不改预算闸圈首检查——保留,新增的是分发前的第二道。
- 不做按工具成本模型选择性跳过("只跳重型工具")——我们没有可靠的每工具成本模型,YAGNI。预算不足时**整轮工具都不分发**(用户已确认)。
- 不改 `done`/`loop_halt`/`cost_update` 事件里 `reason`/`stop_reason` 的 **raw 机器码**(前端/看板按 raw 码归因)——人话映射只用于喂给模型的系统消息。

## 三件改动

### (a) 跨签名连续失败闸

**判据**:`ledger.entries` **尾部连续 `success=False`** 的条数 ≥ 阈值即 halt,reason = `"repeated_failures"`。不看签名(这正是与烧签名/打转闸的区别),只看"是否一直在失败"。

**为什么不误杀正常多查**:查 5 家公司财报全成功 → 尾部连续失败计数为 0;中间任意一次成功即清零。抓的是"一直失败的乱试",不是"调用频率"。

**阈值**:`max_consecutive_failures: int = 5`(比烧签名的 3 宽一档,给正常重试留空间;按"实际体验再调")。

**口径与时序**:与 spinning 同——在圈首 `check_gates` 内判定,此时台账已含此前各圈的 dispatch 结果。被烧签名拒绝的调用不进台账(`loop.py:195` 在 dispatch 前过滤,`apply_results` 不记台账),故不污染该计数;模型换参数→新签名→真分发→真失败,才会被计入,正是要抓的乱试。

**落点**:
- `state.py` `ToolLedger` 加纯方法 `trailing_failure_count() -> int`(从 `entries` 末尾数连续 `not success`)。
- `gates.py` `check_gates` 末尾追加:`if state.ledger.trailing_failure_count() >= cfg.max_consecutive_failures: return "repeated_failures"`(置于 spinning 之后)。
- `GateConfig` 加 `max_consecutive_failures: int = 5`。
- `state.py` `ChatLoopState.halt_reason` 注释补 `repeated_failures`。

### (b) 分发前预算预检

**判据**(纯谓词,放 `gates.py`):`budget_margin_exhausted(state, cfg) -> bool`——剩余 cny < `max_cny * margin_ratio` **或** 剩余 token < `max_tokens * margin_ratio` 即 True。`margin_ratio` 预留收尾那次 LLM 调用的余量。

**编排**(`loop.py` `run`,在 `filter_burned` 之后、`dispatch` 之前):若 `budget_margin_exhausted` 为真且本圈确有工具要分发——
1. `await self._emit("loop_halt", state.step, reason="budget")`;
2. 为 `step_result.tool_calls` **每个** call 产出预算指导错误占位结果(`success=False, error="[预算不足] 请基于已有信息作答,不要再调用工具"`),`apply_results` 折叠进 messages——满足协议红线(assistant(tool_calls) 后每个 tool_call_id 必须有 tool 消息);
3. `return await self._force_conclude(state, "budget")`(收尾那次 LLM 调用 `tool_choice=none`,被预留余量覆盖)。

**为什么是"分发前 + 整轮跳过"**:此时 `apply_step` 已把本圈 LLM 成本入账,用最新预算判断;跳过整轮工具就省掉"工具执行 + 又一轮 LLM 处理结果"两笔开销,只留一次收尾调用。

**阈值**:`budget_dispatch_margin_ratio: float = 0.2`(剩余低于上限 20% 即收尾;按"实际体验再调")。

**落点**:
- `gates.py` 加 `budget_margin_exhausted(state, cfg)` 纯谓词。
- `GateConfig` 加 `budget_dispatch_margin_ratio: float = 0.2`。
- `loop.py` `run` 插入上述编排;加静态方法 `_budget_skipped_result(call)`(仿 `_burned_result`)。

### (c) 收尾原因人话化

**改动**:`loop.py` 加模块级 `_HALT_REASON_TEXT: dict[str, str]`,把 raw 码映射成中文短语(`max_steps→"已达步数上限"`、`budget→"已达预算上限"`、`spinning→"检测到原地重复调用"`、`repeated_failures→"检测到连续多次工具失败"`)。`_force_conclude` 的系统消息用 `_HALT_REASON_TEXT.get(reason, reason)` 替换裸 `{reason}`。

**不动**:`loop_halt`/`done` 事件的 `reason`/`stop_reason` 仍是 raw 码(机器归因)。

## 测试策略

全部 L0 纯函数 / 编排单测,无 I/O,沿用 `backend/tests/unit/chatloop/` 既有 Fake 模式(`FakeLLM` / `_Hub` / 真 `ContextDeps`)。

- `test_gates.py`(扩充):`trailing_failure_count` 计数;连续失败 ≥ 阈值返回 `repeated_failures`;中间一次成功清零不误杀;成功多查不触发;`budget_margin_exhausted` 真/假边界(cny 触发 / token 触发 / 都够)。
- `test_state.py`(扩充):`trailing_failure_count` 在混合成功/失败台账上的尾部语义。
- `test_loop.py` 或新 `test_loop_budget_skip.py`:预算余量不足时,分发被跳过(`_Hub.dispatch` 未被调用)、发 `loop_halt(budget)`、每个 tool_call 有 tool 消息、最终走 force_conclude 出 done;余量充足时正常 dispatch。
- `test_loop.py`:`_force_conclude` 系统消息含人话短语(不含裸 `repeated_failures`)。

## 验收

- WSL fria-venv 下 `pytest backend/tests/unit/chatloop/ -q` 全绿。
- `ruff format --check .` + `ruff check .` + `mypy`(全仓口径,含测试文件)无新增错误。
- 不改任何事件的 raw `reason`/`stop_reason` 字段值(前端/看板兼容)。
