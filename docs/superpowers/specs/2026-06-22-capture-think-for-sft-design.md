# 设计:harness 保留 think(采进轨迹)+ 剥离历史 think(不回灌上下文)

> 为 SFT 开 think 的前置改动。teacher = **qwen3.7-max**(开 think,`reasoning_content` 走单独字段,已探针验证 reasoning+工具调用均 OK;比 qwen3-max 更新一代)。基座 Qwen3-8B-Thinking。承 `2026-06-22-sft-warmstart-plan.md` 决策 A。

## 目标 / 一句话

**当前轮的 teacher 思考要"采下来进轨迹"(给 SFT 当监督目标),但绝不"回灌进下一步的上下文"**——因为 Qwen3 推理时历史轮的 `<think>` 是被丢弃的(只看当前轮思考)。漏了后半句 → 训练里有历史 think、推理里没有 → 又一次训练/推理错位 + 白烧 token。

## 现状(已核验,改动比预想小)

| 点 | 现状 | file:line |
|---|---|---|
| 流式已接 reasoning | `StreamAssembler` 累积 `reasoning_parts` + emit `StepDelta(kind="reasoning")` 给 SSE | `openai_client.py:107,134-137` |
| **但聚合丢了** | `result()` 没把 `reasoning_parts` 放进 `StepResult` | `openai_client.py:201-209` |
| 类型没字段 | `StepResult` 无 reasoning 字段 | `llm_step.py:43-53` |
| **故意不存** | `apply_step` 注释明写"绝不携带 reasoning",assistant 消息只拼 content+tool_calls | `state.py:176,183-203` |
| 原样发 LLM | `assemble_context` 把 `state.messages` 原样投影给 LLM(故塞 reasoning 须在此剥) | `context.py:194+`(docstring「本 turn 轨迹区:state.messages 原样」) |

→ teacher 思考现在被采下来又在聚合处丢掉。打通只需 5 处小改。

## 改动(5 处)

1. **`StepResult` 加字段**(`llm_step.py:43`):`reasoning: str = ""`(默认空,向后兼容 deepseek 等无 think 模型)。

2. **`StreamAssembler.result()` 回填**(`openai_client.py:201`):`reasoning="".join(self.reasoning_parts)`。
   - 非流式 `chat()` 路径(若用到)同理从 `message.reasoning_content` 取;chatloop 主走 stream_step,优先改流式。

3. **`apply_step` 存进 assistant 消息**(`state.py:183-203`):当 `step_result.reasoning` 非空,`assistant_msg["reasoning_content"] = step_result.reasoning`。改 docstring(删"绝不携带 reasoning")。
   - **存成自定义键 `reasoning_content`**,与 dashscope 回传字段同名,语义清晰;放在 assistant 消息里 → 轨迹天然带上、SFT 渲染时取得到。

4. **`assemble_context` 剥离**(`context.py:194+` 投影 state.messages → LLM messages 处):构造 LLM-facing 消息时**丢掉 `reasoning_content` 键**(投影白名单 role/content/tool_calls/tool_call_id/name,或显式 del 副本的该键)。
   - **这是硬要求**:reasoning 永不发给 LLM(历史 think 不回灌 + 当前 think 本就不需回传)。
   - 注意:必须操作副本/投影,**不能改 state.messages 本体**(本体要留 reasoning 给轨迹)。原 downgrade 是就地改 content(协议红线只改 content),此处剥 reasoning 也只动投影、不动本体。

5. **collect 不用改**(`runner.py` `_dump_trajectories`):state.messages 的 assistant 轮现在带 `reasoning_content`,落盘自动带上。

## 关键不变量

- **本体 vs 投影**:`state.messages`(轨迹真源)带 reasoning;发给 LLM 的投影**不带**。两者分离是整个设计的命门。
- **向后兼容**:无 think 模型(deepseek-v4-flash)→ `reasoning=""` → 第 3 步不加键 → 全链路零行为变。**production no-think 路径完全不受影响**(KV-cache 前缀稳定性不变,因投影不含 reasoning)。
- **无需 collect 模式开关**:reasoning 只在思考模型下非空,平时无害,可一直存。
- **与决策 B 正交但同源**:决策 B(采集对齐 data_refs 形态)是"工具结果"的形态对齐;本设计是"think"的形态对齐。两者都是"轨迹形态 = 推理上场形态"。**SFT 采集时两者一起满足**:降级开着(决策 B)+ reasoning 进本体不进投影(本设计)。

## 下游(本设计不含,标清楚边界)

- **SFT 渲染**:tokenize+labels 生成器(SFT 方案 ① 待写)从轨迹的 `reasoning_content` 渲染成 Qwen3 `<think>...</think>`(在 assistant 块、tool_call 之前的正确位置),且 think 段**算 loss**(它是模型推理时要自己生成的)。
- **奖励/GRPO**:与本设计无关。

## 测试

1. **StreamAssembler 单测**:喂含 `reasoning_content` delta 的假 chunk,断言 `result().reasoning` == 拼接值;无 reasoning 的 chunk → `reasoning==""`。
2. **apply_step 单测**:`StepResult(reasoning="思考…")` → assistant 消息含 `reasoning_content`;`reasoning=""` → 不含该键(向后兼容)。
3. **assemble_context 单测**:state.messages 的 assistant 带 `reasoning_content` → 投影出的 LLM messages **不含** `reasoning_content`,但 state.messages 本体**仍含**(没被就地删)。
4. **回归**:既有 chatloop/openai_client/context 全套单测绿(无 think 路径零变)。
5. **(tushare 恢复后)live 验**:qwen3-max 开 think 跑一道,collect 落盘的 trajectories_raw 里 assistant 轮带 `reasoning_content`、且内容是真思考;同一轨迹喂回 LLM 的投影不含 think。

## 落地顺序(TDD,4 task)
1. StepResult 加字段 + StreamAssembler.result 回填(+ 单测 1)。
2. apply_step 存 reasoning_content(+ 单测 2,改 docstring)。
3. assemble_context 投影剥离(+ 单测 3,强调操作副本不动本体)。
4. 全回归(测试 4)+ 把 qwen3.7-max 加进 model_registry(teacher,带价;注意它和旧 `qwen-max`/无 think 不同)。live 验(测试 5)留 tushare 恢复。
