# 模型选择与对比模块 设计 spec

> brainstorming 产物。目标:让 chat agent 的底层模型可切换(给用户选),并能在反向出题
> pass@k 上按模型对比(给训练/选模型出依据)。承 `2026-06-17-pre-rl-tooling-baseline.md`
> 的结论:残留是"工具调用可靠性"= RL 靶子;本模块量化"小模型(RL 候选)vs 大模型(天花板)"
> 在该靶子上的差距。

## 1. 目标与动机

两个用途,一套基础设施:
- **生产**:用户每会话选一个模型,整段对话固定用它,记录归因。
- **训练/评测**:pass@k 能指定模型跑,多模型自动汇成"模型 × 难度/指标"对比表——
  这是"选哪个 base model 来 RL、RL 要补多少"的直接依据。

**关键洞察**:清单里的 qwen2.5-7b / qwen3-8b 是**小模型(可本地微调的 RL 候选)**,
dsv4-flash / qwen-plus / qwen-max 是大 API 模型(能力天花板)。pre-RL 基线发现残留 =
工具调用可靠性,而小模型恰在此最弱 → **对比表直接量化 RL 要补的缺口**。

## 2. 现状(已勘的接线)

- `TierRouter`(`app/services/tier_router.py`)把逻辑 tier(fast/balanced/deep)解析成具体模型名;
  v0 三档全映射到 `deepseek-v4-flash`;docstring 明言"换多模型只需改 config"——本就为此留口。
- `LLMService.stream_step(tier=...)` / `.chat(tier=...)`:`model = self._tier_router.resolve(tier)`,
  调 client,**把 model 记进 StepResult 与 trace Span**(`app/services/llm_service.py`)。
- chatloop(生产 chat 裸循环)与评测 runner 都用 `build_llm_service_from_env()` 起的同一个 LLMService;
  `ToolLoop` 持 `self._tier`,在 `loop.py` 两处调 `self._llm.stream_step(..., tier=self._tier)`。
- 结论:**模型解析单点在 TierRouter / LLMService;"记录"这层(trace 带 model)基本现成。**

## 3. 设计

### 3.1 地基:模型覆盖口子(唯一核心改动)

`LLMService.stream_step` 与 `.chat` 各加一个可选参数 `model: str | None = None`:
- 给了 → 直接用该模型(校验在清单内,不在则 fail loud);
- 没给 → 照旧 `tier_router.resolve(tier)`。

即 `resolved = model or self._tier_router.resolve(tier)`。**保留 tier 抽象,指定模型只是 escape hatch**
(贴合"框架最小化 + 架构留口子")。trace/StepResult 记录的 model 自然变成实际用的那个。

`ToolLoop` 加 `model: str | None = None`(与 `tier` 并列),两处 `stream_step` 调用透传。

### 3.2 模型清单(allowlist)

新增一个小注册表(SSOT,放 tier_router 旁或单独模块),5 个:

| 清单名 | dashscope model ID(待 smoke 确认) | 角色 |
| --- | --- | --- |
| deepseek-v4-flash | deepseek-v4-flash | 现默认,大 |
| qwen-plus | qwen-plus | 大 |
| qwen-max | qwen-max | 大,天花板 |
| qwen2.5-7b | qwen2.5-7b-instruct | **小,RL 候选** |
| qwen3-8b | qwen3-8b | **小,RL 候选** |

- 请求/参数里的 model 必须在清单内,否则 fail loud。
- 清单项带元信息(显示名、dashscope id、大/小、是否已验证支持流式函数调用)。

### 3.3 生产侧:每会话选一次

- chat 会话(持久化的 ChatSession)加一个 `model` 字段;默认 = 系统默认(deepseek-v4-flash)。
- 聊天请求 schema 加可选 `model`;**仅在会话首轮(或显式设置)写入会话**,后续轮用会话存的 model;
  请求带的 model 若与会话已存的不一致 → 以会话为准(或 fail loud,spec 实施时定;倾向"以会话为准 + warn",
  保"每会话固定"语义)。
- chatloop 每轮把 `session.model` 透传进 §3.1 的覆盖口子。
- 记录:trace 已带 model;额外在会话/turn 落一份(已存 or 新增列),事后能按模型切生产数据。

### 3.4 评测侧:多模型对比(训练最想要的)

- `runner.run_passk(..., model: str | None = None)`:整轮用一个模型(透传到 ToolLoop 的 model)。
- `_dump_answers` 落盘记录里加 `model` 字段。
- **新增对比入口** `run_compare(cases, models: list[str], ...)`:对每个 model 跑一遍 run_passk,
  汇成"模型 × (难度/指标桶)"对比表(每格 pass 率),外加总分一列。CLI 出表,可落盘 markdown/yaml。
- 这张表 = "小模型 vs 大模型在各桶差多少"的依据。

## 4. 风险与验证(小模型是核心未知)

**第一步必须 smoke 测**(承"spec 假设要 smoke 验"纪律):对 5 个模型各发一次"带工具的流式请求",确认:
1. dashscope 准确 model ID(qwen2.5-7b / qwen3-8b 的 instruct 后缀等);
2. 是否支持**原生流式 function-calling**,且 tool_call 分片格式与现有 `openai_client` 解析兼容
   (大模型 qwen 的 "id/name 只在首片" 已趟过,小模型未必同);
3. 小模型若**不支持/不稳**函数调用 → **这是比较数据,不是 blocker**:清单项标"未验证/弱",
   pass@k 自然低,正是要量化的结论。spec 不为小模型的弱函数调用做兜底/降级(那会污染对比)。

## 5. 测试约定

- **单元**:覆盖口子(给 model 用 model、不给走 tier、model 不在清单 fail loud);
  ToolLoop 透传 model 到 stream_step;会话 model 字段默认与透传;runner `_dump_answers` 带 model;
  `run_compare` 聚合表形状正确(用 mock LLM,不打真模型)。
- **smoke(live,手动)**:§4 的 5 模型流式函数调用 + 一道 pass@k 题各模型能跑通。
- **回归**:不传 model 时,生产与评测行为与现状逐字不变(model 默认 None → 走 tier → deepseek-v4-flash)。

## 6. 范围 / 不做

- **不做**:chat 前端的模型下拉(下轮);不碰 tier 抽象(model 覆盖是 escape hatch,tier 仍是默认路径)。
- **不做**:为小模型的弱函数调用做兜底/prompt 特调(会污染"原生能力对比";RL 才是补这块的正解)。
- **不引新依赖**:全部走现有 dashscope OpenAI-compatible 客户端。
