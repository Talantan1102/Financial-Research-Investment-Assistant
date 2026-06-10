---
title: "verl 多步工具 RL · 施工向实现配方(金融数值 agent)"
date: 2026-06-09
source_pipeline: "research synthesis workflow (e2e-config / oracle-reward / loss-masking / credit-assignment / task-env / tool-rl-precedents / mismatch-pitfalls 七路并行调研) + 独立核验区"
verification: "核验区独立核过当前 verl(verl-project/verl @main,实测 2026-06-09);凡【核验区】给出的确切配置键/接口/行为以核验区为准,它优先于其它调研路的二手摘要"
target_task: "单对话轮(一个金融问题)+ 多工具步(agent 循环调财务工具取数→计算→交叉核对)+ 最终答案可验证(纯 Python 估值器 / tushare 真值当 oracle,数值容差比对);reward = 确定性 oracle outcome reward,非神经 RM/judge;工具返回冻进 cassette 回放;框架 = verl + sglang rollout,单机多卡 + LoRA 7B/8B"
verl_repo: "github.com/volcengine/verl 已 301 迁到 github.com/verl-project/verl(API full_name 即 verl-project/verl);main 最新 commit 5a38699 @2026-06-09;最新 release tag = v0.8.0"
caveat: "verl 版本敏感。工具系统在 v0.6→v0.8 间重构过一次;经典 BaseTool 范例文件已从 main 删除(完整存在于 v0.5.0 tag)。每条配置键标了取数版本。LoRA 确切键名等【未核实】项已明示,不编造。"
---

# verl 多步工具 RL · 施工向实现配方(金融数值 agent)

> 读者 = 要照着写 config 和 code 的工程师。本文超过 survey 层,挖到能照抄的颗粒度。
>
> **核验优先级**:文中凡标【核验区】的 = 独立核过当前 verl 的确切事实,优先采信;其它为七路并行调研沉淀(多数也核到源码,但若与核验区冲突以核验区为准)。
>
> **版本断层警告(读其它任何节之前先读这条)**:`volcengine/verl` 已整体迁到 `verl-project/verl`。当前 `main` 分支**已删除** `examples/sglang_multiturn/` 整个目录(经典 run script + `config/tool_config/*.yaml` BaseTool 配置 + `verl/tools/gsm8k_tool.py` 全不在 main 了)。这些经典 BaseTool 范例完整存在于 **`v0.5.0` tag**。本文「BaseTool 完整范例」取自 v0.5.0,「config schema 真值 / `@function_tool` 新路径」取自 main/v0.8.0,每条都标了取数版本。**别混 v0.5 文档示例和 main 源码——你"配置键随版本迁移"踩坑全部来自这种混用。强烈建议 pin 一个明确 tag(v0.8.0 工具系统已新架构且 release 稳定),所有键以那个 tag 的 `rollout.yaml`/`base_tool.py` 为唯一真相。**

---

## 0. TL;DR — 给赶时间的人,先把整条链路定形

你的任务在 verl 里映射成:

| 你的概念 | verl 里的载体 | 走哪条路 |
|---|---|---|
| 一个金融问题 | parquet 一行的 `prompt`(chat messages) | — |
| agent 循环调财务工具取数→算→核对 | `ToolAgentLoop` 状态机(`@register("tool_agent")`),AgentLoop/async 路径 | rollout |
| 财务取数工具(读 cassette) | `BaseTool` 子类 + `multi_turn.tool_config_path` YAML | rollout/tool |
| oracle(tushare 真值 ±1% 比对) | 自定义 reward function `compute_score(...)`,写在 reward manager 层 | reward |
| oracle 真值冻进每条样本 | `extra_info.tools_kwargs.<tool>.create_kwargs` + `reward_model.ground_truth` | data |
| cassette 回放 | **你自己在 tool 的 `execute()` 里读快照**(verl 无原生 cassette 层) | env |

**四个必备开关(AgentLoop 工具路径)**:`actor_rollout_ref.rollout.name=sglang` + `actor_rollout_ref.rollout.mode=async` + `data.return_raw_chat=True` + dataset 每行带 `agent_name=tool_agent`(或 `actor_rollout_ref.rollout.agent.default_agent_loop=tool_agent`)。【核验区证实键 (1)(2)(5)(6) + task-env 路】

**三件最该记住的事**:
1. **oracle 走 reward manager(`compute_score`),不走 tool**;终局 outcome reward 落在轨迹最后一个有效 token(`reward_tensor[i, valid_response_length-1]`)。
2. **工具返回 token 自动 loss-mask**(assistant 生成=loss_mask 1,tool/user 返回=0),delta-based tokenization 默认行为,无单独开关。
3. **多步长轨迹的 rollout↔training 精度 mismatch 会沿 token 累乘**→ 必开 Truncated Importance Sampling(TIS),否则"loss 正常、reward 玄学崩"。

---

## 1. 任务形态:"单对话轮 + 多工具步 + oracle 奖励"在 verl 里到底长什么样

### 1.1 三层映射(prompt / rollout / reward)

**prompt = 任务**。一条训练样本 = parquet 一行,`prompt` 是 chat messages 列表(system 说明可用的财务工具 + user 给金融问题)。`data.return_raw_chat=True` 时原始 messages 原样进 rollout。【task-env 路 §1.1;核验区证实 `data.return_raw_chat` 默认 True,示例脚本仍显式传】

**rollout = 工具循环**。当前(main/v0.8.0)由 `ToolAgentLoop.run()` 驱动一个 4 态状态机:

```
PENDING → GENERATING → PROCESSING_TOOLS →(回到 GENERATING)→ TERMINATED
```

- `PENDING`:`apply_chat_template(messages, tools=schemas, ...)` 拼成 prompt_ids。
- `GENERATING`:调 `server_manager.generate(...)` 出一段 assistant token;**注入 tool_parser 的 stop_token_ids**,使生成在一次 tool call 后停住;`assistant_turns += 1`;`response_mask += [1]*len`(assistant token 参与训练)。
- `PROCESSING_TOOLS`:`tool_parser.extract_tool_calls` 解析 tool_calls,`asyncio.gather` 并发执行(上限 `max_parallel_calls`),每个返回拼成 `{"role":"tool","content":...}` 追加进 messages 再 tokenize;**tool 返回 token `response_mask += [0]*len`(不参与 loss)**;`user_turns += 1`。
- (来源:`verl/experimental/agent_loop/tool_agent_loop.py` @main,task-env 路;`response_mask` 1/0 语义见 §4 与 `docs/advance/agent_loop.rst`)

**终止条件(精确列表,源码)** —— "agent 结束"= 以下任一(`_handle_generating_state`,@main):
1. `len(response_mask) >= response_length`(超长);
2. `max_assistant_turns and assistant_turns >= max_assistant_turns`;
3. `max_user_turns and user_turns >= max_user_turns`;
4. **解析后没有 tool_calls → TERMINATED**(模型不再调工具 = 给最终答案了);
5. `PROCESSING_TOOLS` 末尾拼完工具返回后若 `len(response_mask)+len(response_ids) >= response_length` 也 TERMINATED。

(来源:`tool_agent_loop.py` @main,task-env 路)

**reward = oracle 验最终答案**。轨迹结束后,**reward manager**(不是工具)逐样本解码整条 response 成 `solution_str`,把它连同 `ground_truth`/`data_source`/`extra_info` 交给你的 `compute_score`,返回标量写到末 token。详见 §3。

### 1.2 两条多轮工具路径必须先分清(版本演进核心)

verl 有**两套**多轮工具 rollout 路径,配置键不同,别混:

| 路径 | 触发方式 | 状态 | 取数 |
|---|---|---|---|
| **sglang 原生多轮**(老) | `rollout.name=sglang` + `rollout.multi_turn.enable=True`,**不强制** `mode=async`,不走 dataset `agent_name` | v0.4–v0.5 主力 | v0.5.0 run script `run_qwen2.5-3b_gsm8k_multiturn.sh` |
| **AgentLoop / ToolAgentLoop**(新,推荐) | `rollout.mode=async` + `data.return_raw_chat=True` + dataset 带 `agent_name`(或 `agent.default_agent_loop`) | v0.4.2 起 alpha,现为主线 | `docs/advance/agent_loop.rst`(标 `.. versionadded:: 0.4.2`) |

`docs/advance/agent_loop.rst` 顶部:`.. versionadded:: 0.4.2 [status: alpha]` + `.. warning:: Agent Loop is ready for use, but the API may change in future releases`(Last updated 07/17/2025,main,取数 2026-06-09)。

> **你的场景(单轮金融问题 + 多工具步 + oracle outcome reward)走 AgentLoop 路径的 `tool_agent` loop**——它就是为"agent 循环调工具取数→算→交叉核对"设计的。

---

## 2. 端到端配置(带版本 caveat)

### 2.1 canonical config schema 真值(main 分支 `rollout.yaml`)

以下键路径与默认值取自 `verl/trainer/config/rollout/rollout.yaml`(main = v0.8.0 逐字一致,取数 2026-06-09)。`_target_: verl.workers.config.RolloutConfig`。**这些键/默认值全部经【核验区】逐字证实**:

```yaml
# actor_rollout_ref.rollout.*
name: ???            # ??? = omegaconf 强制项,必填;valid: hf/vllm/sglang/trtllm
                     # 注释 'The default value will be removed in the future';多轮工具填 sglang
mode: async          # 注释 '# sync: LLM, async: AsyncLLM';AgentLoop/function-tool 路径填/保持 async

multi_turn:
  _target_: verl.workers.config.MultiTurnConfig
  enable: False                       # 默认 False;多轮工具任务置 True;注释要求 rollout.name 也设 sglang
  max_assistant_turns: null           # null = 不限(default max_length // 3)
  tool_config_path: null              # BaseTool(有状态)YAML 路径 —— 【核验区:这是 live schema key,23 处源码命中】
  function_tool_path: null            # @function_tool(无状态)Python 文件路径;与 tool_config_path 可共存,重名报错
  max_user_turns: null
  max_parallel_calls: 1               # 单轮内最大并行工具调用数
  max_tool_response_length: 256       # ⚠️ 工具响应最大长度,默认仅 256,财务返回易超,务必调大
  tool_response_truncate_side: middle # left / middle / right
  use_inference_chat_template: False
  tokenization_sanity_check_mode: strict   # strict / ignore_strippable / disable
  format: hermes                      # hermes, llama3_json, ...(决定 ToolParser)
  num_repeat_rollouts: null

agent:                                # [Experimental] agent loop based rollout configs
  _target_: verl.workers.config.AgentLoopConfig
  num_workers: 8
  default_agent_loop: single_turn_agent   # ⚠️ 默认是 single_turn_agent,不是 tool_agent!
                                          # 要工具循环必须显式置 tool_agent(或 dataset 写 agent_name=tool_agent)
  agent_loop_config_path: null            # 自定义 AgentLoop 列表配置(hydra instantiate)
  custom_async_server:
    _target_: verl.workers.config.CustomAsyncServerConfig
    path: null
    name: null
```

(来源:`rollout.yaml` @main,task-env/e2e-config 路;键与默认值经【核验区】证实)

> **容易记错的真值**(核验区/调研一致强调):
> - 默认 agent loop 是 `single_turn_agent`,**不是** `tool_agent`。要工具循环必须显式 `agent.default_agent_loop=tool_agent` 或 dataset 写 `agent_name=tool_agent`。
> - `multi_turn` 是**嵌套块**,真正生效的是 `multi_turn.enable`。docs 里的 `multi_turn: True` / `rollout.multi_turn: True` 是**旧式简写**(两者都能 resolve,但 `enable` 才是 dataclass field)。**别照抄裸 `multi_turn: True`**。
> - `name: ???` 的 `???` 是 omegaconf "mandatory missing" 标记,必须在 run script 里赋值。

### 2.2 键名打架的真实坑(核验区裁决)

【核验区】明确:doc 的 "Custom Tool Configuration" 段写工具配置键为 `actor_rollout_ref.rollout.tool_kwargs.tools_config_file`,但**该键在当前 `rollout.yaml` schema 中不存在**(0 occurrences;`tools_config_file` 仅出现在 `tool_registry.py` + 那一行 doc,共 2 hits)。而 `multi_turn.tool_config_path` 才是 live schema key(23 处源码命中,默认 null)。

→ **照抄请用 `actor_rollout_ref.rollout.multi_turn.tool_config_path`,把 `tool_kwargs.tools_config_file` 当作 stale doc 忽略。**(已交叉验证:核验区 + v0.5.0 run script + main schema 三方一致)

### 2.3 AgentLoop 路径的两个必填项(agentic_rl docs 原文)

> There are two options required to use agent loop:
> - `data.return_raw_chat=True`
> - `actor_rollout_ref.rollout.mode=async`

(来源:`docs/start/agentic_rl.rst`,Last updated 07/15/2025,main;`data.return_raw_chat` 默认 True 经【核验区】证实,但示例脚本仍显式传)

### 2.4 `@function_tool` 路径的官方 YAML 片段(docs 原文,逐字)

`docs/sglang_multiturn/multiturn.rst`(Last updated 05/09/2026)给的 "Function Tool Configuration":

```yaml
actor_rollout_ref:
    rollout:
        mode: async
        multi_turn:
            enable: True
            format: hermes  # or any other format your model's chat template supports
            function_tool_path: path/to/your_tools.py
        agent:
            default_agent_loop: tool_agent
```

(来源:`multiturn.rst` @main,05/09/2026;`default_agent_loop: tool_agent` 已交叉验证 `tool_agent_loop.py` 顶部确有 `@register("tool_agent")`)

> ⚠️ **但 function_tool 是 stateless 的,不接 `tools_kwargs` 注入,没有 `create`/`release` 生命周期。你要从 dataset 注 tushare oracle 真值/cassette 名,必须用 BaseTool。** docs 明确:"For per-trajectory state ... or that needs tools_kwargs injected from the dataset, keep using BaseTool via tool_config_path"。(task-env 路 §0/§3)

### 2.5 完整 bash run script(照抄底稿,v0.5.0 AgentLoop 实证)

下面是 v0.5.0 `run_qwen2.5-3b_gsm8k_tool_agent_mlflow.sh` 逐字(AgentLoop 路径范例,含 `mode=async`):

```bash
set -x
ulimit -n 65535
PROJECT_DIR="$(pwd)"
CONFIG_PATH="$PROJECT_DIR/examples/sglang_multiturn/config"

python3 -m verl.trainer.main_ppo \
    --config-path="$CONFIG_PATH" \
    --config-name='gsm8k_multiturn_grpo' \
    algorithm.adv_estimator=grpo \
    data.train_batch_size=256 \
    data.max_prompt_length=1024 \
    data.max_response_length=1024 \
    data.filter_overlong_prompts=True \
    data.truncation='error' \
    data.return_raw_chat=True \
    actor_rollout_ref.model.path=Qwen/Qwen2.5-3B-Instruct \
    actor_rollout_ref.actor.optim.lr=1e-6 \
    actor_rollout_ref.model.use_remove_padding=True \
    actor_rollout_ref.actor.ppo_mini_batch_size=256 \
    actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=32 \
    actor_rollout_ref.actor.use_kl_loss=True \
    actor_rollout_ref.actor.kl_loss_coef=0.001 \
    actor_rollout_ref.actor.kl_loss_type=low_var_kl \
    actor_rollout_ref.actor.entropy_coeff=0 \
    actor_rollout_ref.model.enable_gradient_checkpointing=True \
    actor_rollout_ref.actor.fsdp_config.param_offload=False \
    actor_rollout_ref.actor.fsdp_config.optimizer_offload=False \
    actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=32 \
    actor_rollout_ref.rollout.tensor_model_parallel_size=2 \
    actor_rollout_ref.rollout.name=sglang \
    actor_rollout_ref.rollout.mode=async \
    actor_rollout_ref.rollout.gpu_memory_utilization=0.5 \
    actor_rollout_ref.rollout.n=16 \
    actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=32 \
    actor_rollout_ref.ref.fsdp_config.param_offload=True \
    actor_rollout_ref.rollout.trace.backend=mlflow \
    actor_rollout_ref.rollout.trace.token2text=True \
    algorithm.use_kl_in_reward=False \
    trainer.critic_warmup=0 \
    trainer.logger='["console","mlflow"]' \
    trainer.project_name='gsm8k_tool-agent' \
    trainer.experiment_name='qwen2.5-3b_function_rm-gsm8k-sgl-tool-agent-verify-n16' \
    trainer.n_gpus_per_node=8 \
    trainer.nnodes=1 \
    trainer.save_freq=-1 \
    trainer.test_freq=20 \
    trainer.total_training_steps=2 \
    data.train_files=$HOME/data/gsm8k/train.parquet \
    data.val_files=$HOME/data/gsm8k/test.parquet \
    actor_rollout_ref.rollout.multi_turn.tool_config_path="$PROJECT_DIR/examples/sglang_multiturn/config/tool_config/gsm8k_tool_config.yaml" \
    trainer.total_epochs=15 $@
```

(来源:`examples/sglang_multiturn/run_qwen2.5-3b_gsm8k_tool_agent_mlflow.sh` @v0.5.0,取数 2026-06-09)

> 这份脚本**没有显式写** `agent.default_agent_loop=tool_agent`——因为它的 dataset 由 `gsm8k_tool_agent_loop.py` 预处理时已往每行注入 `agent_name="tool_agent"`(见 §2.7),`agent_name` 字段优先于 `default_agent_loop`。

**LoRA 增量**:你需要额外加 LoRA 配置键。**【未核实】LoRA 确切键名**(`lora_rank`/`lora_alpha` 等)未在本次取数文件内逐字核到,需查 `verl/trainer/config/model` 的 lora 段。不要照猜的键名写。tool-rl-precedents 路给的方向:`actor_rollout_ref.model.lora_rank=<r>` + `lora_alpha=<a>` 是常见形态但**待核**。

### 2.6 配套 hydra config(`--config-name='gsm8k_multiturn_grpo'`)

```yaml
hydra:
  searchpath:
    - file://verl/trainer/config
defaults:
  - ppo_trainer
  - _self_
data:
  max_prompt_length: 1024
  max_response_length: 1024
  train_batch_size: 256
  return_raw_chat: True
actor_rollout_ref:
  hybrid_engine: True
  rollout:
    name: sglang
    multi_turn:
      enable: True
      max_assistant_turns: 5
```

(来源:`examples/sglang_multiturn/config/gsm8k_multiturn_grpo.yaml` @v0.5.0)——`return_raw_chat: True` 与 `multi_turn.enable: True` 在 yaml 层定死,run script 再 CLI override。

### 2.7 数据样本结构(parquet 一行,逐字)

AgentLoop/ToolAgentLoop 路径预处理产物(`gsm8k_tool_agent_loop.py` @main):

```python
data = {
    "data_source": "openai/gsm8k",
    "agent_name": "tool_agent",          # ★ 路由到 ToolAgentLoop 的关键字段
    "prompt": [
        {"role": "system", "content": "You are a math expert. ... You should use the `calc_gsm8k_reward` tool ..."},
        {"role": "user", "content": question},
    ],
    "ability": "math",
    "reward_model": {"style": "rule", "ground_truth": solution},   # ★ 轨迹级 outcome 真值,你的 oracle 比对锚
    "extra_info": {
        "split": split,
        "index": idx,
        "answer": answer_raw,
        "question": question_raw,
        "need_tools_kwargs": True,
        "tools_kwargs": {
            "calc_gsm8k_reward": {                       # key = 工具名(对齐 tool_schema.function.name)
                "create_kwargs": {"ground_truth": solution},   # ★ 把 oracle 真值/cassette 名注进工具的官方通道
                # "execute_kwargs": {},
                # "calc_reward_kwargs": {},
                # "release_kwargs": {},
            },
        },
    },
}
```

(来源:`examples/data_preprocess/gsm8k_tool_agent_loop.py` @main)

**字段语义(核实)**:
- **`agent_name`**:决定走哪个 AgentLoop。`agent_loop.py`:`if "agent_name" not in batch.non_tensor_batch: batch.non_tensor_batch["agent_name"]=[config.agent.default_agent_loop]*len`,即 dataset 没带就用 `default_agent_loop` 兜底;带了就以行内值为准,且 `assert agent_name in _agent_loop_registry`。
- **`extra_info.tools_kwargs.<tool>.create_kwargs`**:`tool.create(create_kwargs=...)` 时注入(BaseTool 路径)。**这是把 oracle 真值/cassette 名喂进工具的官方通道。**
- **`reward_model.ground_truth`**:轨迹级 outcome reward 真值,reward manager 消费(见 §3)。
- `prompt` 是 message 列表;`return_raw_chat=True` 时 `raw_prompt` 原样进 `AgentLoopBase.run(**kwargs)`。

**映射到你的金融场景**:`prompt` = 金融问题(system 里说明可用财务工具);`reward_model.ground_truth` = tushare oracle 标准答案(数值或可比对结构,如 `{"ts_code":"600519.SH","truth_value":...}`);`tools_kwargs.<tool>.create_kwargs` = 这条样本用哪个 cassette / 哪个股票代码 / 容差。

### 2.8 工具注册:两种 schema(你的 tushare-oracle 应走 BaseTool)

#### (A) BaseTool 工具 schema YAML(完整,逐字 @v0.5.0)

```yaml
tools:
  - class_name: "verl.tools.gsm8k_tool.Gsm8kTool"    # 你的工具类全路径
    config:
      type: native                                    # config 是自由透传 dict,进 BaseTool.__init__(config=...)
                                                       # ★ 放 cassette 快照目录/容差阈值/tushare token 的地方
    tool_schema:
      type: "function"
      function:
        name: "calc_gsm8k_reward"                     # 必须 == 模型 tool call 名 == tools_kwargs 的 key
        description: "A tool for calculating the reward of gsm8k. (1.0 if parsed answer is correct, ...)"
        parameters:
          type: "object"
          properties:
            answer:
              type: "string"
              description: "The model's answer to the GSM8K math problem, must be a digits"
          required: ["answer"]
```

(来源:`examples/sglang_multiturn/config/tool_config/gsm8k_tool_config.yaml` @v0.5.0)

`tool_schema` 映射到 pydantic `OpenAIFunctionToolSchema`(`verl/tools/schemas.py` @main):`type` + `function{name, description, parameters{type, properties, required}}`。

#### (B) `@function_tool`(无状态,纯计算工具适用,@main 新增)

```python
from verl.tools.function_tool import function_tool

@function_tool
def get_weather(city: str) -> dict:
    """Get the current weather for a city.

    Args:
        city: The city to look up, e.g. "Tokyo" or "San Francisco".
    """
    return {"temperature_c": 17.3, "condition": "drizzle"}
```

机制(`verl/tools/function_tool.py` @main):schema 由 `transformers.utils.get_json_schema(fn)` 从签名 + Google-style docstring 推断;缺 docstring/类型标注/`Args:` → 注册即报 `DocstringParsingException`/`TypeHintParsingException`;`*args`/`**kwargs` 注册时 `raise ValueError`;返回值 `normalize_function_tool_return` 归一(`str`→`ToolResponse(text=)`;`dict`→`json.dumps`;`(resp, reward[, metrics])` 元组,`None` reward→`0.0`)。**没有 `create`/`release`,不接 `tools_kwargs` 注入** → 你的 oracle 不能用它。

---

## 3. oracle 奖励怎么接(自定义 reward function 骨架)

> 口径:本节代码/键以 **v0.5.0** 锚定,并标 `main`/`latest` 差异。【核验区证实了 `custom_reward_function` 接口签名/返回/调用时序/manager 默认】。

### 3.1 一句话:你的纯 Python oracle 怎么包成 verl reward

把 `compute_dcf` / 比对 tushare 真值的函数包成一个**模块级函数**,签名固定为 `def compute_score(data_source, solution_str, ground_truth, extra_info=None)`,放进一个 `.py` 文件,配置里指 `custom_reward_function.path` + `.name`。verl 用 `importlib` 按**文件路径**动态加载它,由 `NaiveRewardManager` 在**每条样本 rollout 解码后逐条同步调用**,返回 `float`(或带 `score` 键的 dict),写到该样本最后一个有效 token。

### 3.2 配置键(核验区 + v0.5.0 双证)

【核验区】给的确切形式(per latest config.html / reward_function.rst):

```yaml
custom_reward_function:
  path: null              # 你的 oracle 文件绝对路径;null 时 fallback 到 verl 预置 reward
  name: compute_score     # 文件内函数名,DEFAULT 'compute_score';函数就叫 compute_score 时可不设

reward_model:
  enable: False           # 默认 False;False = reward 只来自 user-defined/rule 函数,RM 不是神经 RM —— 正是你要的
  reward_manager: naive   # 默认 naive;另有 prime/batch/dapo
  launch_reward_fn_async: False   # 默认 False(同步);见 §3.6

data:
  reward_fn_key: data_source   # 选 reward 函数用的列,默认 data_source
```

> **【核验区版本 nuance】**:稳定文档(examples/config.html、reward_function.rst)用**顶层** `custom_reward_function:` 和 `reward_model:` 块;但**最新 `verl/trainer/ppo/reward.py` 源码**在 `config.reward.*` 命名空间下读它们(`config.reward.custom_reward_function` / `config.reward.reward_manager`)——一次近期 config 重构。**以你 pin 版本的实际 `grep` 为准。** v0.5.0 仍是顶层(`get_custom_reward_fn(config)` 用 `config.get("custom_reward_function")` 直取,oracle-reward 路证实)。
>
> 另:【核验区】提到新版有 async "Reward Loop" 路径(`launch_reward_fn_async`/`RewardLoopManager`,~v0.5.x+),两 registry 都接会 double-compute;**普通 sync oracle/rule reward 不需要它**。

### 3.3 加载机制(`get_custom_reward_fn`,逐字 @v0.5.0)

```python
def get_custom_reward_fn(config):
    import importlib.util, sys
    reward_fn_config = config.get("custom_reward_function") or {}
    file_path = reward_fn_config.get("path")
    if not file_path:
        return None
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Reward function file '{file_path}' not found.")
    spec = importlib.util.spec_from_file_location("custom_module", file_path)
    module = importlib.util.module_from_spec(spec)
    try:
        sys.modules["custom_module"] = module
        spec.loader.exec_module(module)
    except Exception as e:
        raise RuntimeError(f"Error loading module from '{file_path}': {e}") from e
    function_name = reward_fn_config.get("name")
    if not hasattr(module, function_name):
        raise AttributeError(f"Reward function '{function_name}' not found in '{file_path}'.")
    raw_fn = getattr(module, function_name)
    reward_kwargs = dict(reward_fn_config.get("reward_kwargs", {}))
    return partial(_call_with_kwargs, raw_fn, reward_kwargs)
```

(来源:`verl/trainer/ppo/reward.py` @v0.5.0;核验区证实 loader 行为)

工程含义:
- **靠文件路径加载,不靠 import 路径**:oracle 文件可放仓库任意位置,`path` 指对即可;模块被注册成固定名 `"custom_module"`。
- **oracle 文件顶部的 import 必须在训练进程 Python 环境可解析**(`import tushare` / 你的 `compute_dcf`);`exec_module` 失败抛 `RuntimeError`。
- `_call_with_kwargs(raw_fn, extra_kwargs, *args, **kwargs)` → `merged = {**kwargs, **extra_kwargs}`,即 yaml 的 `reward_kwargs` **覆盖** call-time kwargs。
- **【未核实/版本陷阱】`reward_kwargs`**:代码支持 `reward_fn_config.get("reward_kwargs", {})`,但 v0.5.0 的 yaml 默认块**未预置** `reward_kwargs`(隐式约定键)。可加,但你具体版本是否仍如此【需自查】。

### 3.4 何时被调用 + 怎么从多步轨迹抽答案(`NaiveRewardManager.__call__`,逐字 @v0.5.0/main)

```python
for i in range(len(data)):
    data_item = data[i]
    prompt_ids = data_item.batch["prompts"]
    prompt_length = prompt_ids.shape[-1]
    response_ids = data_item.batch["responses"]
    valid_response_length = data_item.batch["attention_mask"][prompt_length:].sum()
    valid_response_ids = response_ids[:valid_response_length]
    response_str = self.tokenizer.decode(valid_response_ids, skip_special_tokens=True)   # ← 整条 response 解码
    ground_truth = data_item.non_tensor_batch["reward_model"]["ground_truth"]
    data_source = data_item.non_tensor_batch[self.reward_fn_key]
    extra_info = data_item.non_tensor_batch.get("extra_info", {})
    extra_info["num_turns"] = data_item.non_tensor_batch.get("__num_turns__", None)   # ★ 走了几轮给你
    score = self.compute_score(
        data_source=data_source, solution_str=response_str,
        ground_truth=ground_truth, extra_info=extra_info,
    )
    if isinstance(score, dict):
        reward = score["score"]                          # ★ dict 只取 score["score"] 当 reward
        for key, value in score.items():
            reward_extra_info[key].append(value)         # 其余键进 reward_extra_info 当 metric 上报
    else:
        reward = score
    reward_tensor[i, valid_response_length - 1] = reward  # ★ outcome reward 放在末有效 token
```

(来源:`verl/workers/reward_manager/naive.py` @v0.5.0/main;核验区证实)

**逐条解答你的问题**:
1. **输入**:4 个具名参数(名字必须对):`data_source`(=数据集名字符串)、`solution_str`(=**整条 response 解码后的纯文本字符串**,不是 messages list)、`ground_truth`(=`reward_model.ground_truth`)、`extra_info`(=`extra_info` dict,verl 还塞 `num_turns`)。
2. **`solution_str` 在多步任务里是什么**:整条多步轨迹的 **response 段拍平成一个字符串**(含各 turn 的生成 token;tool 返回 token 被 mask 但仍在 decode 文本里),不是只有最后一句。`num_turns` 给你判断走了几轮。
3. **怎么抽最终答案**:**这是你 reward function 自己的职责**——verl 把整条 `solution_str` 给你,你正则/解析抽。GSM8K 范例 `extract_solution`:从尾部 300 字符里正则抓 `#### <数字>`、取最后一个。→ 对你:让 policy 把最终估值用**固定锚点格式**输出(`<answer>...</answer>` 或 `#### {估值}`),`compute_score` 在 `solution_str` 尾部抓锚点。**裁剪取尾部**避免多步中间步数字误命中。
4. **输出**:per-sample 标量 `float`,或 **dict 且必须含 `"score"` 键**(其余键进 metrics)。
5. **写到哪**:`reward_tensor[i, valid_response_length-1]`(token-level sparse reward,正好契合"整条轨迹一个 oracle 分")。
6. **同步/逐样本**:`for i in range(len(data))` **串行逐条同步**。纯 CPU `compute_dcf` + cassette 回放,串行无瓶颈。

### 3.5 真实代码骨架(把 `compute_dcf` / tushare 比对包成 verl reward)

```python
# my_oracle_reward.py(放仓库任意位置,路径写进 yaml)
import re
from typing import Optional
from my_valuation import compute_dcf          # 你的纯 Python oracle,返回估值数字
from my_data import get_tushare_truth         # 训练期走 cassette 回放,返回真值

_ANSWER_RE = re.compile(r"<answer>\s*([-+]?\d[\d,\.]*)\s*</answer>")
_CLIP = 600  # 多步轨迹尾部裁剪,避免中间步数字误命中

def _extract_final_answer(solution_str: str) -> Optional[float]:
    tail = solution_str[-_CLIP:] if len(solution_str) > _CLIP else solution_str
    hits = _ANSWER_RE.findall(tail)
    if not hits:
        return None
    try:
        return float(hits[-1].replace(",", ""))
    except ValueError:
        return None

def compute_score(data_source, solution_str, ground_truth, extra_info=None):
    """verl 认的 reward function。逐样本同步调用。
    solution_str: 整条多步轨迹 response 解码后纯文本;ground_truth: parquet 的 reward_model.ground_truth。
    返回: float 或 {"score": float, ...metric...}
    """
    extra_info = extra_info or {}
    pred = _extract_final_answer(solution_str)
    if pred is None:
        return {"score": 0.0, "answer_parsed": 0.0, "format_ok": 0.0}   # 没按格式给答案 → 0
    ts_code = ground_truth if isinstance(ground_truth, str) else ground_truth.get("ts_code")
    truth = get_tushare_truth(ts_code, extra_info=extra_info)           # 确定性 oracle(cassette 回放)
    if truth == 0:
        correct = abs(pred) < 1e-9
    else:
        rel_err = abs(pred - truth) / abs(truth)
        correct = rel_err <= 0.01                                       # ±1% 容差
    return {
        "score": 1.0 if correct else 0.0,                              # outcome reward
        "rel_err": float(abs(pred - truth) / abs(truth)) if truth else 0.0,
        "format_ok": 1.0,
        "num_turns": float(extra_info.get("num_turns") or 0),
    }
```

要点对应源码约定:函数名 `compute_score` 对齐默认 `name`;4 个具名参数顺序/名字必须对;返回 dict 必含 `"score"`,其余键自动进 `reward_extra_info`(区分"格式错"vs"数值错")。

**配置**:
```yaml
custom_reward_function:
  path: /abs/path/to/my_oracle_reward.py
  name: compute_score
reward_model:
  enable: False            # 关神经 RM,只用规则 oracle
  reward_manager: naive    # 串行逐样本
  launch_reward_fn_async: False
data:
  reward_fn_key: data_source
```
命令行等价(Hydra override):`custom_reward_function.path=/abs/.../my_oracle_reward.py custom_reward_function.name=compute_score reward_model.reward_manager=naive`。

### 3.6 同步/异步路 + 一个静默吞异常的坑

- **同步路(默认)**:rollout 出整 batch 后,主流程直接 `compute_reward(data, reward_fn)`。
- **异步路(`launch_reward_fn_async: True`)**:`compute_reward_async.remote(...)` 把**整个 reward manager** 丢到 `num_cpus=1` 的 Ray worker,与 `log_prob` 并行——**异步是"整 batch 的 reward manager 在独立进程跑",不是"你函数 async"**。你的同步 `compute_dcf` 写普通 `def` 即可,两个版本都吃(latest 才有 `iscoroutinefunction` 分支支持 `async def`)。
- **⚠️ 静默降级坑**:`compute_reward` 的 `try/except` 会**吞掉你 reward function 抛的异常**,fallback 成 `reward_fn(data)`(无 `return_dict`)并清空 extra_info。即**oracle 内部 bug 不会让训练崩,而是被静默降级 reward 全 0**。调试期务必看 stdout `Error in reward_fn:` 打印;自己 catch 并返回 0 更可控。

### 3.7 reward manager 选型(影响并发)

`reward_model.reward_manager` 解析类:`naive`(串行,**推荐起步**)、`prime`(多进程并行,要求验证函数 multiprocessing-safe / 可 pickle / 无全局可变状态)、`batch`(批级签名,**与逐样本签名不同**,用它你函数要改成接 list)、`dapo`。**【未核实】`prime`/`batch` 的 compute_score 签名是否与 naive 完全一致——切换前查对应文件**。你纯 Python + cassette 回放,串行无瓶颈,**naive 即可**。

---

## 4. loss masking(机制 + 默认/手配 + 验证 + 坑)

> 【核验区:loss-masking-default verdict=confirmed】——以下机制经核验区独立证实。

### 4.1 结论:默认行为,不是单独开关

多轮工具开启后(`multi_turn.enable=True` + `name=sglang`/`vllm`),**只有 assistant 生成 token 进 loss,tool/user 返回 token 自动 mask**。**没有** `mask_tool_response` 这类配置键——masking 内建在 per-token `loss_mask` 的构造里。**你不需要为 masking 单独开任何开关。**

### 4.2 机制:delta-based tokenization(逐字,核验区原文)

每当 LLM 生成一条新 message:对 `messages[:i]` 套 chat template(`add_generation_prompt=True`),再对 `messages[:i+1]`(`add_generation_prompt=False`),**只 tokenize 两次序列化字符串的 delta**,assistant-delta token 给 `loss_mask=1`,tool/user token 给 `0`:

```python
prev = tokenizer.apply_chat_template(messages[:i],   add_generation_prompt=True,  tokenize=False)
curr = tokenizer.apply_chat_template(messages[:i+1], add_generation_prompt=False, tokenize=False)
token_ids += tokenizer.encode(curr[len(prev):], add_special_tokens=False)
loss_mask += [1] * len(token_ids)  # Mask only the new assistant tokens
```

(来源:【核验区】verbatim,SGLang multiturn doc;由 PR #1668 "Efficient and model-agnostic multi-turn messages tokenization and masking" 引入,合并 2025-06-09)

> **关键不对称**:prior messages 用 `add_generation_prompt=True`——把 assistant 起手提示符(`<|im_start|>assistant\n`)算进 prev,落在 delta 之外、不进 loss;真正进 loss 的只有提示符之后模型自己吐的 content。

**生产代码层**(`verl/workers/rollout/schemas.py` @main):mask 按 role 逐 message 写入,不是事后正则抠:

| 入口方法 | loss_mask | 谁的 token |
|---|---|---|
| `add_user_message(...)` | `False` → 0 | user 输入 |
| `add_assistant_message(...)` | `True` → 1 | **assistant 生成** |
| `add_tool_response_messages(...)` | `False` → 0 | **工具返回** |

初始 prompt 段 `prompt_loss_mask = zeros`(全 0)。AgentLoop 路径(`tool_agent_loop.py`)同样:`response_mask` 对 LLM 生成 token 置 1、对工具响应置 0(`AgentLoopOutput.response_mask`,1=LLM-generated,0=tool-response)。

### 4.3 验证 masking 正确(内置 sanity check,默认开)

`tokenization_sanity_check_mode: strict`(默认)。机制:每次 rollout 在 `finalize()` 末尾把完整 message list **重新整段 tokenize 得 `full_prompt_ids`,与增量构造的 `self.input_ids` 做 diff**;有差异按 mode 告警。`_get_prompt_diffs` 用 `difflib.SequenceMatcher` 对解码回的文本做 opcode diff,非 equal 段连同前后 10 字符上下文返回。三态:
- `strict`(默认):任何差异都告警;
- `ignore_strippable`:仅忽略空白字符差异(`\n \t \r` 空格),实义文本不一致仍告警;
- `disable`:完全跳过(只在已彻底确认差异良性时用)。

**实操**:首次接新模型/新 chat template,保持默认 `strict` 跑几个 step,**grep 日志 `Inconsistent training and inference tokenization detected`**;有就用 `_get_prompt_diffs` 输出的 `full_prompt_chunk`/`current_prompt_chunk` 定位。确认是良性空白差异再降到 `ignore_strippable`,**不要一上来 disable**。

### 4.4 已知坑

**(a) tool_calls 被清空 → tokenization mismatch(Issue #3960)**。复现 `Qwen/Qwen3-4B-Thinking-2507` + `gsm8k_tool_config.yaml`。根因:rollout 中 assistant 最后一条 message 的 `tool_calls` 被清空(`sglang_rollout.py` ~L861),但 sanity check 重渲 `full_prompt` 时按完整 message(含 tool_calls)重渲——增量 `current_prompt` 缺 `<tool_call>...</tool_call>` 块。diff 形态:
```diff
-The final answer is 14.<|im_end|>
+The final answer is 14.
+<tool_call>
+{"name": "calc_gsm8k_reward", "arguments": {"answer": "14"}}
+</tool_call><|im_end|>
```
这是实义差异,**不会被 ignore_strippable 静默**。**【未核实】是否已有合入修复 PR**——打开 #3960 看最新 timeline。命中时别误判成自己 config 错。

**(b) reasoning content 被 chat template 剥掉导致 delta 不准**(Qwen/QwQ-32B、Qwen3 系)。这些模型渲染时移除内部 reasoning,同条 message content 跨轮渲染会变。系统兜底:改用 "fixed base conversation"(单 system + 单 user 固定底座)。衍生开关 `use_inference_chat_template=True`(默认 False)对齐推理态,代价:长 reasoning 多轮易超 context;rollout 与生产又生新 mismatch。

**(c) 自定义工具时务必走 `add_tool_response_messages` 写工具返回,别自己往 input_ids 拼字符串**——否则绕过 per-role mask,工具 token 漏进 loss。

**(d) 【版本敏感】** PR #1668 描述期的 `tokenization_mode: fast/full/sanity_check` 键在 main 已收敛为 `tokenization_sanity_check_mode` 三态枚举;旧版本可能残留旧键名,以本地 `rollout.py` dataclass 为准。

---

## 5. credit assignment 选型(trajectory-only 起步 vs turn-level 中间奖励)

> 关键基线约束:**verl 原生只把一个标量 outcome reward 放在轨迹最后一个有效 token 上**(§3.4)。中间奖励(调对工具/参数合法/中间取数正确)**配置开不出来,必须改 reward 侧或 advantage 侧自己实现**。

### 5.1 verl 原生支持矩阵(一眼判断能不能配出来)

| 能力 | verl 原生 | 怎么开 |
|---|---|---|
| 单标量 outcome reward(末 token) | ✅ | `custom_reward_function.path/name` 配置即可 |
| reward 返回 dict 带多分量 | ✅ 但只取 `score["score"]`,其余进日志 | 配置即可,**多分量不进梯度** |
| `response_mask` 屏蔽工具返回 token 的 loss | ✅ | 多轮 rollout 自带(§4) |
| tool `execute()` 的 `tool_reward` 进 `compute_score` | ❌ 当场丢弃(issue #3525,open) | 改 `ToolAgentLoop._call_tool` + compute_score 签名 |
| Interaction `calculate_score` per-turn 进梯度 | ❌ 算了不用(issue #2540) | 改源码 |
| turn-level / step-level advantage | ❌ 主仓 #1654 open 未实现 | 换 fork 或自写 adv_estimator |

> **两个迷惑性陷阱**:① `BaseTool.execute()` 能 return `(response, tool_reward, metrics)` 第二位的 `tool_reward`,但 `ToolAgentLoop._call_tool` 收到后**当场丢弃**,没传给 `compute_score`(issue #3525,open,需自己提 PR/改源码)。② Interaction 系统的 `calculate_score` 是 per-turn 的,但其返回的 `user_turn_rewards` **实际并未用于训练**(issue #2540),最终 reward 仍来自外部 RewardManager。**别被这两个 API 名字骗了。**

Agent-lightning 对 verl 的判断(直接引用):"verl does not expose fine-grained control over its reward propagation or credit assignment mechanisms. Users requiring customized reward shaping ... are advised to clone and modify the verl source implementation directly." verl 把每次 agent 执行拆成 Triplet(prompt–response 对),**末轮 Triplet 的标量 reward 被广播复制到前面所有 Triplet**——仍是 trajectory-level,不是按轮区分功劳。

### 5.2 三条落地路线(按改动量从小到大)

**路线 1(最省事,推荐先做):中间奖励揉进末 token 标量**
- 在 `compute_score` 里:`oracle_score`(tushare ±容差)为主项,叠加 `+0.2·调对工具 +0.5·中间取数命中 −惩罚·参数非法`,返回 dict `{"score": total, ...}`(后几项进日志)。
- 配置:`custom_reward_function.path/name`,**零改源码**。
- 局限:仍 trajectory-level,reward 落末 token,不是真 turn credit。但配合 §5.3 硬门控,通常足够防退化。

**路线 2(要真 turn credit,中等代价):打通 tool_reward + 自填 token-level reward**
- 改 `ToolAgentLoop._call_tool` 保留 `execute()` 的 `tool_reward`(修 #3525 丢弃点),随 metadata 传入 `compute_score`;自定义 RewardManager,把 turn reward 写到对应 turn 的 token 区间(参照 `reward_tensor[i, t]` 写入点,但不止写末 token)。
- 代价:改 verl 源码 + 自管 turn 边界。

**路线 3(要 step-level 算法,换 fork):上 GiGPO**
- 用 `langfengQ/verl-agent`(verl 官方 fork,GiGPO 官方代码),一个键切换:
  ```bash
  algorithm.adv_estimator=gigpo \
  algorithm.gigpo.step_advantage_w=1.0 \
  algorithm.gigpo.mode=mean_std_norm \
  algorithm.gamma=0.95 \
  algorithm.use_kl_in_reward=False
  ```
- GiGPO 两层 group:episode-level 像 GRPO 用整轨回报;step-level 用"锚状态分组"(把多条轨迹里重复出现的相同环境状态聚到一组,组内比较不同动作回报),无额外 rollout、纯 hashmap。合并 `scores = episode_advantages + step_advantage_w * step_advantages`。实验:ALFWorld 1.5B 86.1% vs GRPO 72.8%(+13.3pp);7B 90.2% vs 77.6%(论文自报,2505.10978)。
- **⚠️ 适配判断(本报告推理,非论文原文)**:GiGPO 的 step 信用来自"重复锚状态"。你的金融取数任务里,中间状态(已取财务字段集 / 工具调用历史)若在 group 内不重复,锚状态分组退化成空组、step advantage≈0。ALFWorld/WebShop 因 agent 绕圈、重访同一页面才有重复状态。**你的任务是否有重复状态需自评,否则 GiGPO step 信号很稀。**
- **⚠️ fork 键差异**:verl-agent 用 `env.env_name`/`env.rollout.n`(环境驱动 rollout),与主仓 `actor_rollout_ref.rollout.n` 键不同 —— 照抄前务必核对你用哪个仓。

### 5.3 防"停止调工具"退化(纯 outcome reward 多步退化)

**现象(论文实锤,MT-GRPO 2505.11821)**:outcome-only(GRPO-OR)在多步搜索任务上"逐渐停止调用搜索工具"(gradually stops calling search tools),中间奖励归零,只靠瞎猜末轮答案 → EM 卡 20–33%。直觉:工具调用是中间 token,outcome 标量铺满全轨迹时,"调工具"和"不调工具直接蒙对"拿到相同 advantage,而调工具有格式/token 成本,梯度上反被压。verl 的末轮广播(§5.1)加剧此问题。可观测签名:**loss 看着正常,gradient norm 突刺后 reward 崩**(Echo Trap)。

**缓解(按工程代价排序)**:
1. **加 process/中间奖励**(MT-GRPO 法):工具执行 +0.2、中间取数命中 +0.5,直接给"调对工具"正梯度。
2. **step-level advantage**(GiGPO 法,路线 3)。
3. **format/tool-call 硬门控**(成本最低):**未走工具直接判 0 分**——你的 oracle 里加:若 agent 没调 tushare 取数就给答案,即便蒙对也判低分。纯在 `compute_score` 里实现,**配置即可,不改 advantage**。
4. **`response_mask` 已帮你**屏蔽工具返回 token 的 loss(避免模型学复读工具输出),verl 多轮自带。

中间项设计模板(ToolRL 2504.13958,做交叉核对/多工具时借):`R_correct` 三级——工具名 Jaccard `|N_G∩N_P|/|N_G∪N_P|` + 参数名匹配 + 参数值匹配;**动态课程** `p=训练进度` 平滑切换 format↔correctness(比两阶段硬切稳)。但主线是:**你有确定数值 oracle,最终数值 ±1% 命中应是主导 reward,ToolRL 式分解只做弱权重塑形。**

---

## 6. 环境与可重放(工具执行 + cassette 录制接进训练)

### 6.1 工具怎么执行/喂回

**工具是 rollout worker 同进程内的 async Python 调用**:`_call_tool` 直接 `await tool.execute(...)`,在 `AgentLoopWorker` 进程里跑,`asyncio.gather` 并发。**没有独立的 tool server 进程。** 但"工具内部"可以再去打外部服务(例如 v0.5.0 `SearchTool.execute()` 内部读 `config.get("retrieval_service_url")` 发 HTTP 到外部检索服务)。→ 对你:tushare 工具的 `execute()` 是同进程函数;它内部去 live 调 tushare 还是读本地快照,**完全由你在 `execute()` 里决定**,verl 不强制工具走外部 server。

**工具返回怎么喂回模型**(sglang multi-turn,`_handle_processing_tools_state` @main):每个返回拼成 `{"role":"tool","content": tool_response.text}` 追加进 messages,`apply_chat_template(...)` tokenize,`response_mask += [0]*len`(不算 loss),`user_turns += 1`,回 `GENERATING`。`format`(hermes/llama3_json)决定 tool call 解析与回填格式。

**`tools_kwargs` 怎么流进工具**(`_call_tool` BaseTool 分支 @main):
```python
kwargs = tools_kwargs.get(tool_name, {})
instance_id, _ = await tool.create(create_kwargs=kwargs.get("create_kwargs", {}))
tool_execution_response, tool_reward, res = await tool.execute(instance_id, tool_args, agent_data=agent_data)
```

### 6.2 BaseTool 接口签名(v0.5 vs main 有变化,照抄必看)

**v0.5.0**(`execute` 返回 `tuple[str, float, dict]`):
```python
class BaseTool:
    def __init__(self, config: dict, tool_schema: OpenAIFunctionToolSchema): ...
    async def create(self, instance_id=None, **kwargs) -> str: ...
    @rollout_trace_op
    async def execute(self, instance_id, parameters, **kwargs) -> tuple[str, float, dict]:
        # returns (tool_response:str, tool_reward_score:float, tool_metrics:dict)
    async def calc_reward(self, instance_id, **kwargs) -> float: ...
    async def release(self, instance_id, **kwargs) -> None: ...
```

**main / v0.8.0**(返回类型变成 `ToolResponse`,`create` 多返回一个 `ToolResponse`):
```python
from .schemas import OpenAIFunctionToolSchema, ToolResponse
class BaseTool:
    async def create(self, instance_id=None, **kwargs) -> tuple[str, ToolResponse]:   # ← 返回值变了
        return str(uuid4()), ToolResponse()
    @rollout_trace_op
    async def execute(self, instance_id, parameters, **kwargs) -> tuple[ToolResponse, float, dict]:  # ← str→ToolResponse
        return ToolResponse(text="..."), 0.0, {}
```

**迁移坑**:① v0.5 `execute` 第一返回值是 `str`,main 是 `ToolResponse(text=...)`;② main 把 `create_kwargs` 整个 dict 作为**一个名为 `create_kwargs` 的参数**传给 `create()`,而 v0.5 `Gsm8kTool.create(self, instance_id=None, ground_truth=None, **kwargs)` 期望解包。所以在 main 上,你的 `create` 签名应写 `async def create(self, instance_id=None, create_kwargs=None, **kwargs)`,然后 `gt = (create_kwargs or {}).get("ground_truth")`。两套别混。

### 6.3 cassette 录制响应怎么接进训练(verl 无原生 cassette 层)

**结论:verl 没有原生的工具返回 replay/cassette 层**。main 全树搜 `replay|cassette|mock|cache` 只命中 `router_replay`(MoE 专家路由 replay,与工具无关)。`_call_tool` 直接 `await tool.execute(...)`,中间无任何拦截/录制/回放 hook。

→ **确定性可重放 = 你自己在 tool 的 `execute()` 里读快照**。verl 给你的全部"钩子"= §2.8 的 `config:` 透传 dict(全局参数)+ §2.7 的 `tools_kwargs.create_kwargs` per-trajectory 注入(随 parquet 行走)。

**推荐做法(BaseTool 子类,main 签名,骨架)**:
```python
# verl/tools/tushare_oracle_tool.py
import json, hashlib, uuid
from pathlib import Path
from typing import Any, Optional
from .base_tool import BaseTool
from .schemas import OpenAIFunctionToolSchema, ToolResponse

class TushareTool(BaseTool):
    def __init__(self, config: dict, tool_schema: OpenAIFunctionToolSchema):
        super().__init__(config, tool_schema)
        self.mode = config.get("mode", "replay")              # YAML config: 块(全局):"replay" | "live"
        self.cassette_dir = Path(config.get("cassette_dir", "./cassettes"))
        self._inst = {}

    async def create(self, instance_id: Optional[str] = None, create_kwargs: Optional[dict] = None, **kwargs):
        create_kwargs = create_kwargs or {}                   # ⚠️ main 把 create_kwargs 当一个 dict 参数传(见 §6.2)
        iid = instance_id or uuid.uuid4().hex
        self._inst[iid] = {"ts_code": create_kwargs.get("ts_code"),
                           "cassette": create_kwargs.get("cassette")}   # per-trajectory 快照名,随 parquet 行注入
        return iid, ToolResponse()

    async def execute(self, instance_id: str, parameters: dict[str, Any], **kwargs) -> tuple[ToolResponse, float, dict]:
        # parameters = 模型这次 tool call 的入参(来自 tool_args = json.loads(tool_call.arguments))
        key = hashlib.sha1(json.dumps(parameters, sort_keys=True).encode()).hexdigest()[:16]
        cassette = self._inst[instance_id].get("cassette") or "default"
        snap = self.cassette_dir / cassette / f"{key}.json"
        if self.mode == "replay":
            data = json.loads(snap.read_text(encoding="utf-8"))       # 读冻结快照,零网络,确定性
        else:
            data = self._live_call(parameters)                        # 录制阶段:打真 tushare 并 dump
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.write_text(json.dumps(data, ensure_ascii=False))
        return ToolResponse(text=json.dumps(data, ensure_ascii=False)), 0.0, {}   # step reward 给 0

    async def release(self, instance_id: str, **kwargs) -> None:
        self._inst.pop(instance_id, None)
```

要点:① **快照 key = 工具入参的稳定 hash** → 同一调用必命中同一快照,训练回放确定性;② **每条轨迹用哪个 cassette** 通过 `tools_kwargs.<tool>.create_kwargs.cassette` 注入(随 parquet 行走),`create()` 收到;③ 录制阶段 `mode=live` 跑一遍 dump 快照,训练阶段 `mode=replay` 只读、零网络;④ **step reward 设 0**,真正 outcome reward(tushare ±1% 比对)走 §3 的 `compute_score`,`ground_truth` 从 `reward_model.ground_truth` 来。

> 这套就是 VCR/cassette 模式,但 verl 不提供它——它只提供让你干净接进去的两个注入点。**你项目里已有的 tushare cassette 可直接复用为 `cassette_dir` 内容,工具 `execute()` 做的就是 key→文件查找。**

### 6.4 启用所需的整套开关(汇总)

- `actor_rollout_ref.rollout.name=sglang`(必须 sglang;vLLM 多轮工具路径不完整)
- `actor_rollout_ref.rollout.mode=async`(agent_loop 走 async server)
- `actor_rollout_ref.rollout.multi_turn.enable=True`
- `actor_rollout_ref.rollout.multi_turn.tool_config_path=/abs/your_tool.yaml`
- `data.return_raw_chat=True`
- dataset 每行 `agent_name="tool_agent"`(或 `actor_rollout_ref.rollout.agent.default_agent_loop=tool_agent`)
- `actor_rollout_ref.rollout.multi_turn.max_tool_response_length` 调大(默认 256 太小,财务返回易截断)

---

## 7. 实现坑清单(mismatch+TIS / sglang sync-async / OOM 共置 / 版本敏感键)

### 7.1 rollout↔training 精度 mismatch + TIS(多步长轨迹的命门)

**根因**:rollout 引擎(sglang,bf16/不同 attention kernel)≠ training 引擎(FSDP forward,可能不同 dtype/kernel)。即使权重逐 bit 相同,逐 token log-prob 就是对不齐。verl 数学文档(`algo/rollout_corr_math.html`,2025-11-04)把误差拆成 Drift 1(`π_rollout→π_old`)+ Drift 2(`π_old→π_θ`)。实测:同一 Qwen2.5-7B bf16 vs fp16,10/10 请求漂移,单 token 最大 log-prob 差 2.05,35% token 超 0.01 阈值(discussion #5984)。

**为什么多步放大(你的语境核心)**:序列级 IS 权重是逐 token 比值连乘 `w_seq = exp(∑_t log ρ_t)`,轨迹越长方差越爆。文档点名 "The Length Trap":标准乘法 IS 惩罚长序列,模型为不被拒而回避长推理("context collapse")。多步工具轨迹天然长,正中此坑。**注意:cassette 回放消除了环境侧不确定性,但不消除引擎数值 mismatch**(cassette 固定的是 tool 文本返回,不是 sglang 算的 token log-prob),TIS 依然需要(此推论与 §7.1 根因一致,verl 文档未对 cassette 单独表述)。

**规避动作 = 开 Truncated Importance Sampling(TIS)**。配置键**版本敏感**:
- **新版(v0.6.0 起,PR #3694)** 嵌套结构:
  ```yaml
  algorithm:
    rollout_correction:
      rollout_is: token            # null | "token" | "sequence";长轨迹首选 token(避 Length Trap)
      rollout_is_threshold: 2.0    # token TIS 推荐 1.5–5.0;seq TIS 推荐 2.0–10.0
      rollout_is_batch_normalize: false
  actor_rollout_ref:
    rollout:
      calculate_log_probs: true    # ★ 必须 true,否则没有 π_rollout 的 log_prob;代码有 assert
  ```
- **旧版(过渡)** 扁平键:`actor_rollout_ref.actor.tis_imp_ratio_cap`(默认 -1=关;设 >0 开启并作 clamp 上限,经验 ~2.0)+ 必开 `calculate_log_probs=True`。**【未核实】旧键精确所属路径**(`actor.tis_imp_ratio_cap` 层级),以你版本 grep 为准。
- **doc 没给旧→新键的迁移/弃用说明**。先 `pip show verl` 看版本,再 grep 源码确认键名存在,别跨版本照抄。

**IS 权重必须 detach**(理论强制,非实现细节):`loss = -(w_t.detach() * torch.min(r_t·A, clamp(r_t,1-ε,1+ε)·A))`,不 detach 会多出错误 bias 项 `log π_θ · ∇_θ w(θ)`。grep `core_algos.py` 里 IS 权重乘 loss 处确有 `.detach()`/`stopgrad`。

**诊断工具**:社区 `inferscope rollout-diff training.jsonl serving.jsonl`(非 verl 内置,discussion #5984,2026-04)——逐 token log-prob 漂移,0.01 abs delta 为漂移线,5x/20x 作 critical 分级,输出位置直方图。让 rollout/training 各落 per-token logprob jsonl 配对比对;若漂移集中在 tool 拼回后的步,说明多轮拼接是放大点。**监控**:盯 `rollout_corr/rollout_is_mean`(<0.5 或 >2.0 报警)、`rollout_is_eff_sample_size`(<0.3 报警)、`kl`(>0.1)、gradient-norm 突刺(崩前兆)。

### 7.2 sglang sync-async 现状("只有 sync 能触发 tool call"是误配)

issue #2986 报"sglang+sync 能调工具,sglang+async / vllm 全失败"(verl 5.0.0,2025-08)。**已 CLOSED(2025-08-12),根因不是 async 不能调工具,而是 async 模式走 `AgentLoopManager`,你必须在 parquet 里显式加 `agent_name="tool_agent"`**,否则 manager 默认走 `single_turn_agent_loop`,根本不进 tool 分支。最小修复 = §2.7 的 `agent_name` + §6.4 的 async 开关组合。现状研判:v0.6.0(PR #3456 vllm 也迁 native server mode、#3171 重构 agent loop multiturn)后 async tool 路径已是主推,"sync-only"在新版不应再成立,但前提仍是 `agent_name` 配对。**落地前先在你的 verl 版本上跑 1-step smoke 确认 tool call 真被调起。**

### 7.3 OOM 共置(colocate)

- 共置(train+infer 同组 GPU)在 rollout↔train 切换、**权重从 FSDP 拷进 sglang** 时内存压力最大、最易 OOM。缓解:把 resume 拆阶段(载训练权重→resume 推理权重→sync→offload 训练模型→再 resume KV cache)。
- `gpu_memory_utilization`:不 offload 时 **0.5–0.7**;开 param/grad/optimizer offload 可 **0.8–0.9**(sglang rollout 默认 0.8)。
- sglang TP init 用 all-device broadcast,`DeviceMesh` 初始化查各 GPU 显存一致性,差 >~10% 报错;绕过 `SGL_DISABLE_TP_MEMORY_INBALANCE_CHECK=True`。
- FP8 rollout OOM(issue #4641):sglang FP8 量化 full-model materialize + blockwise 低效。7B/LoRA 想省显存上 FP8 rollout 注意此坑。

### 7.4 LoRA + sglang weight sync bug(你正是这个规模,直接相关)

issue #4065:**LoRA 适配器在 sglang 后端的权重同步处理有 bug**。你正是 LoRA 7B 规模,**务必在你 pin 的版本上专门验证 LoRA→sglang 的 weight sync 正确性**。另:sglang `update_weights` 是逐 key(vllm 是整包),GRPO 里逐 key 拖速度(issue #3766),7B/LoRA 单机大概率不致命但常数开销真实。

### 7.5 sequence-parallel + 多轮 logprob 维度 bug(影响 sp>1)

issue #2639:`fsdp + sglang + multi-turn + sync + ulysses_sequence_parallel_size>1` 下 `logprobs_from_logits` 报 logits 与 labels 第 1 维 size mismatch。根因:0.4.1 多模态支持后 `_req_level_generate_sequences` 总返回带 `multi_modal_inputs` 的 `non_tensor_batch`。**规避:纯文本多轮设 `return_multi_modal_inputs: False`。**

### 7.6 版本敏感键速查(照抄前先核对)

| 键/事实 | 坑 | 规避动作 |
|---|---|---|
| `multi_turn.tool_config_path` vs `tool_kwargs.tools_config_file` | doc 写后者,schema 只有前者(0 命中) | 用 `multi_turn.tool_config_path`【核验区裁决】 |
| `multi_turn: True` vs `multi_turn.enable: True` | 旧式裸 bool 简写 | 用 `multi_turn.enable: True`(dataclass field) |
| `agent.default_agent_loop` 默认 `single_turn_agent` | 不改不调工具 | 显式 `tool_agent` 或 dataset `agent_name` |
| `custom_reward_function` 顶层 vs `config.reward.*` | 近期重构 | grep 你的版本确认命名空间 |
| `tis_imp_ratio_cap`(旧) vs `algorithm.rollout_correction.*`(新) | 无迁移说明 | `pip show verl` + grep 键名 |
| `tokenization_mode` vs `tokenization_sanity_check_mode` | PR 描述期旧键 | 以本地 dataclass 为准 |
| `max_tool_response_length` 默认 256 | 财务返回被 middle 截断 | 调大 |
| LoRA 键名 | 【未核实】 | 查 `verl/trainer/config/model` lora 段 |
| "ChatScheduler" 类 | 源码无此类 | 当前真名 `LLMServerClient`+`AgentLoopManager`,别照此写 |

**落地清单(可勾选)**:① 锁一个 tag(建议 v0.8.0),所有键以那个 tag 的 `rollout.yaml`/`base_tool.py` 为唯一真相;② 数据加 `agent_name="tool_agent"` + `data.return_raw_chat=true` + `rollout.mode=async`;③ 开 TIS(`rollout_correction.rollout_is=token`,`rollout_is_threshold=2.0`,`calculate_log_probs=true`);④ grep 确认 IS 权重 `.detach()`;⑤ 纯文本设 `return_multi_modal_inputs=False`;⑥ 专门验 LoRA→sglang weight sync;⑦ `gpu_memory_utilization=0.5–0.7`;⑧ 跑 1-step smoke 确认 tool 真被调起 + grep tokenization sanity warning。

---

## 8. 工具-RL 先例可直接借的做法

> 按"任务形态吻合度"排序,每条挑能搬到金融数值 agent 的 reward/数据/环境构造。数字均**论文/厂商自报**,口径已标。

### 8.1 Snorkel FinQA RL Environment(最近,几乎是你的任务本身)
> ⚠️ 来源 = Snorkel AI **厂商博客**(无显式日期,非 peer-reviewed,数字自报),但工程形态最贴。
- **奖励 = 二值 + 数值容差归一化(最值钱)**:`1.0 if 答案在容差内匹配 ground truth else 0.0`;**靠"归一化"而非神经判官**——把 LaTeX/百分比/分数/千分位逗号/括号负号等先归一化再比较,**省掉 LLM-judge**。
- **可直接搬**:① 容差归一化层是你 oracle 核心,别用 EM,先归一化(去千分位、统一百分比/小数、括号负号、单位)再 `abs(pred-truth)/abs(truth)≤0.01`;② HTTP(reward/state)与工具通道(MCP)分离 → 工具通道回放 cassette,reward 通道连确定性估值器;③ 禁 `SELECT *`/强制 filter 这类工具侧硬约束 → 给财务工具加"必须指定股票代码+报告期"参数校验,逼精确取数;④ 多轴评估(correctness + 工具效率 + 幻觉率)做诊断、防 reward 被工具调用次数 gaming。
- 缺口:它是单一确定 oracle、**无 cassette 录制语义**,你的回放需自建。

### 8.2 Search-R1(取数→答 outcome-only 母板,**建在 verl 上**)
- **奖励**:纯 outcome,`r=EM(a_pred,a_gold)`,**不加 format reward,不用神经 RM**。
- **检索 token loss masking** = 你的"工具返回 token masking"直接复用:tushare 返回填进 `<information>`/`<tool_response>` 标签,这些 token `I=0` 不进 loss。verl 已内建(§4)。
- config 参考(论文自报):PPO policy lr 1e-6/value 1e-5,GAE λ=γ=1,KL β=0.001,clip ε=0.2;GRPO group size=5。检索 server 独立解耦 → 你的 cassette server 可同样独立起本地 HTTP。
- 数字:相对 RAG baseline Qwen2.5-7B +41%、3B +20%(平均跨 7 集,论文自报,2503.09516)。

### 8.3 ZeroSearch(EM→F1 防 reward hacking 的警示)
- **换 EM 为 F1 的理由**:"用 EM 当 reward 常导致 reward hacking:policy 倾向生成超长答案"。→ **警示你:若 oracle 用裸字符串 EM,模型会钻格式空子,务必用归一化数值容差。**
- 课程式噪声调度可移植成"课程式难度":先喂干净 cassette,后期注入残缺/缺字段响应,逼 agent 学健壮取数与交叉核对。REINFORCE 在单 reward 任务上报最优(省 critic),小规模可先试。

### 8.4 ReTool / ToRL(代码工具 RL，你的"纯 Python 估值器"就是这条线)
- **奖励**:rule-based outcome-only(ReTool `+1/-1`;ToRL `+1/-1`,可选 `-0.5` 不可执行罚但**默认关**,论文警告过罚→诱导简化代码退化)。
- **`<interpreter>`/`<code>` 返回 token masking + KL=0** 是代码/工具 RL 稳定性基线,直接搬到你"估值器返回值"token。
- **执行报错回传给模型**(ToRL):你的工具/估值器出错(缺字段、超期)时把结构化报错回灌上下文,让 agent 学重试/换工具——正是"交叉核对"链路需要的自纠错。
- **cold-start SFT 先教"何时插工具→取数→交叉核对"再 RL**(ReTool 顺序),避免纯 RL 冷启探索不到工具调用;若 base 已会调工具可学 ToRL 跳过 SFT。
- 数字:ReTool AIME24 67%(400 步)vs 文本 RL 40%(1080 步);ToRL AIME24 43.3% vs TIR 26.7%(论文自报)。说明**工具 RL 相对纯文本 RL 的增益在精确计算任务上极大**——正中你靶心。GRPO 每题采 16 sample 是数值任务稳的配置参考。

### 8.5 反例对照:Fin-R1(为什么它不算"可验证工具 RL")
- 金融,但**单轮 CoT、无工具、content reward = LLM-judge(Qwen2.5-Max)**,正是你 spec 要避开的。它用 judge 是因为没把"答案归一化"做好(自承小数/单位不匹配)。**你的设计应站 Snorkel 这边,把工程力气投在"数值/单位归一化器",而非神经判官。**

### 8.6 "做法蒸馏"——最该搬的 6 条
1. **oracle = 数值归一化 + ±容差,坚决不用 EM、不用 LLM-judge**(归一化器是核心工程量)。
2. **工具返回 token 必须 loss masking**(三家一致;verl 已内建,接入时确认/手验)。
3. **outcome-only 起步,format/中间项后加且弱权重**(中间罚过重诱导退化;约束"调对工具传对参数"用 ToolRL 三级 Jaccard 弱塑形 + 动态课程)。
4. **cassette 回放走独立工具通道,reward 走独立 oracle 通道**(Snorkel HTTP/MCP 分离)。
5. **cold-start SFT 教会调工具再上 RL**(ReTool 顺序);base 已会则跳过。
6. **算法**:小规模先试 REINFORCE(省 critic),不行再 GRPO(每题 16 sample);KL 取 0 或 1e-3;lr 1e-6 是这批工作共识值。

---

## 9. 【外部查不到、必须落到本项目代码才能定的缺口】(接后续代码审计)

以下每条都是 verl 文档/外部先例无法回答、必须审计本仓代码才能定的,列成清单交后续 code review:

1. **`numerical_metric` 能否直接当 reward fn**?本仓 eval 体系里若已有 `numerical_metric`(拉 tushare 真值 ±1% 比对)的实现,需确认它的签名能否包成 `compute_score(data_source, solution_str, ground_truth, extra_info=None)`——具体:① 它当前接收的是结构化数值还是字符串?`solution_str` 是整条 response 文本,需要在 reward fn 里先 `_extract_final_answer` 再喂给它;② 它返回的是 bool/float/dict?要适配 verl 的"float 或带 `score` 键 dict";③ 它内部取 tushare 真值的路径是否能切到 cassette 回放(见缺口 3)。**审计点:本仓 `numerical_metric` 的定义文件 + 调用签名。**

2. **chatloop 现有工具循环能否复用为 verl rollout**?本仓 chatloop 的 ToolHub/工具循环(`feat(chatloop)` 系列 commit)与 verl `ToolAgentLoop` 状态机是两套控制流。需审计:① 本仓工具的执行入口签名能否包成 verl `BaseTool.execute(instance_id, parameters, **kwargs) -> tuple[ToolResponse, float, dict]`?② 本仓工具的有状态性(若有 session/instance 状态)能否映射到 BaseTool 的 `create`/`release` 生命周期?③ 工具的 OpenAI function schema 能否直接转成 verl `tool_schema` YAML?**审计点:本仓 ToolHub 工具注册/分发代码 + 工具的 async 签名。**

3. **本仓 cassette 格式能否被 verl tool 的 `execute()` 直接读**?verl 无原生 cassette 层,要在 `execute()` 里 `json.loads(snap.read_text())`。需审计:① 本仓 tushare cassette 的存储格式(JSON?pickle?DB 行?)与 key 结构(按什么 hash/索引?);② §6.3 骨架里"工具入参稳定 hash → 快照"的 key 映射能否对齐本仓 cassette 的现有索引,还是需要重建索引;③ cassette 里冻的是原始 tushare 响应还是已处理结果——若是后者,工具 `execute()` 返回给 agent 的文本是否一致。**审计点:本仓 tushare cassette 录制/读取代码 + 存储格式。**

4. **`reward_model.ground_truth` 里放什么结构**?你的 oracle 需要标的 id + 期望估值锚 + 容差 + cassette 名。需审计本仓现有的"金融问题 → 真值"数据结构能否序列化进 parquet 的 `reward_model.ground_truth`(必须可 JSON 序列化、可放 `non_tensor_batch`)。**审计点:本仓金融题集/真值数据结构。**

5. **本仓 `compute_dcf` / 多模型估值 cross-check 的纯度**?reward fn 逐样本串行同步调用,且 oracle 文件顶部 import 必须在训练进程环境可解析。需审计:① `compute_dcf` 是否纯 CPU 同步(无网络/无 DB 副作用,除非走 cassette)?② 它的依赖链(`from my_valuation import compute_dcf`)在 verl 训练进程的 venv 里能否 import(本仓后端跑 WSL fria-venv,verl 训练环境是否同一个)?③ A5a 多模型估值 cross-check 若要当 oracle 一部分,其确定性如何(是否调 LLM?调 LLM 就不是确定性 oracle 了)。**审计点:本仓 `compute_dcf`/A5a cross-check 的依赖与确定性。**

6. **训练环境 vs 后端运行环境**?MEMORY 记后端跑 WSL fria-venv、装包走代理 7897。需确认 verl + sglang + LoRA 的训练环境(单机多卡)是否独立于后端 venv,oracle 文件的 import 链在训练环境是否成立(符合本仓"import 链假设要 smoke test 验"约定,落地时 `python -c "from my_valuation import compute_dcf"` 实测)。**审计点:训练环境依赖 smoke test。**

---

## 10. 全局明确标注的不确定项(不编造)

- 【未核实】LoRA 确切配置键(`lora_rank`/`lora_alpha` 等)——未在本次取数文件内逐字核到,查 `verl/trainer/config/model` lora 段。
- 【未核实】Issue #3960(tool_calls 清空→tokenization mismatch)是否已有合入修复 PR——打开 issue timeline 看最新。
- 【未核实】Issue #2986 的 async tool call 在你具体版本是否稳定——落地前跑 1-step smoke。
- 【未核实】`prime`/`batch` reward manager 的 compute_score 签名是否与 `naive` 完全一致——切换前查对应文件,本文只确证 naive 逐样本签名。
- 【未核实】旧键 `tis_imp_ratio_cap` 精确所属路径(`actor.tis_imp_ratio_cap` vs `actor_rollout_ref.actor.tis_imp_ratio_cap`)——以你版本 grep 为准。
- 【未核实】`max_assistant_turns`/`max_user_turns` 键名拼写来自 issue #2986 用户配置,multiturn.html 正文未逐字核到——跑前 grep 确认。
- 【未核实】"ChatScheduler" 类——源码中未检索到,当前真名 `LLMServerClient` + `AgentLoopManager`,疑为旧命名,**请勿照此写代码**。
- 【版本敏感】`custom_reward_function` 顶层 vs `config.reward.*` 命名空间(近期重构);`reward_kwargs` 在你版本 yaml 是否预置(v0.5.0 代码支持、yaml 未预置)——grep 你的版本。
- 【厂商二手】Snorkel FinQA 全部数字来自厂商博客(非论文、无显式日期),"4B 超 235B"等未经同行评审,引用标注来源性质。

---

## 来源清单(主源,逐条已在正文内联)

**verl 源码/配置(verl-project/verl,GitHub API 实测 2026-06-09)**:
- `verl/trainer/config/rollout/rollout.yaml` @main(=v0.8.0) — config schema 真值【核验区】
- `verl/workers/config/rollout.py::MultiTurnConfig` @main — dataclass 默认值【核验区】
- `verl/trainer/config/ppo_trainer.yaml` / `reward_model/reward_model.yaml` / `data/legacy_data.yaml` @v0.5.0 — reward/data 键
- `verl/trainer/ppo/reward.py` @v0.5.0 — `get_custom_reward_fn`/`compute_reward(_async)`【核验区】
- `verl/workers/reward_manager/naive.py` @v0.5.0/main — `NaiveRewardManager.__call__`【核验区】
- `verl/utils/reward_score/gsm8k.py` @v0.5.0 — `extract_solution` 锚点抽取
- `verl/workers/rollout/schemas.py` @main — delta tokenization/loss_mask/sanity check【核验区 loss-masking】
- `verl/experimental/agent_loop/{agent_loop,tool_agent_loop,single_turn_agent_loop,tool_parser}.py` @main — 状态机/register/response_mask
- `verl/tools/{base_tool,function_tool,schemas,tool_registry}.py` @main + `gsm8k_tool.py`/`base_tool.py` @v0.5.0 — BaseTool/@function_tool/ToolResponse
- `examples/data_preprocess/gsm8k_tool_agent_loop.py` / `gsm8k.py` @main/v0.5.0 — parquet 行结构
- `examples/sglang_multiturn/config/tool_config/gsm8k_tool_config.yaml` @v0.5.0 — BaseTool schema YAML
- `examples/sglang_multiturn/run_qwen2.5-3b_gsm8k_tool_agent_mlflow.sh` + `gsm8k_multiturn_grpo.yaml` @v0.5.0 — run script + hydra config
- `verl/tools/search_tool.py` @v0.5.0 — 工具内部打外部服务佐证

**verl 文档(readthedocs / docs rst,日期口径已标)**:
- `docs/sglang_multiturn/multiturn.rst` / multiturn.html(Last updated 05/09/2026)— 多轮 + function_tool + tokenization
- `docs/start/agentic_rl.rst`(07/15/2025)— AgentLoop 两必填项 + agent_name
- `docs/advance/agent_loop.rst`(07/17/2025,versionadded 0.4.2 alpha)— AgentLoopBase/Output
- `docs/preparation/reward_function.rst` / examples/config.html — custom reward 接口【核验区】
- `algo/rollout_corr.html`(2025-10-30)/ `rollout_corr_math.html`(2025-11-04)— TIS/RS/detach/Length Trap/诊断
- `workers/sglang_worker.html`(2025-05-31)/ `perf/perf_tuning.html` — 显存键

**verl issues / PR / discussion**:
- #3960(tool_calls 清空→mismatch)/ #2986(sync-only 误配,closed)/ #2639(sp>1 logprob bug)/ #3766(weight sync 逐 key)/ #4065(LoRA+sglang sync bug)/ #4641(FP8 OOM)/ #3525(tool_reward 丢弃)/ #2540(per-turn score 不进梯度)/ #1654(turn-level adv 未实现)
- PR #1668(delta tokenization & masking,合并 2025-06-09)/ #2953(token-TIS)/ #3694(seq-TIS BREAKING)
- discussion #5984(inferscope rollout-diff,2026-04-13)/ v0.6.0 release notes

**工具-RL 先例(一手 arXiv / 厂商博客,日期已标)**:
- Search-R1 2503.09516 / ReTool 2504.11536 / ToRL 2503.23383 / ToolRL 2504.13958 / ZeroSearch 2505.04588 / Reasoning-Table 2506.01710 / Fin-R1 2503.16252(反例)
- MT-GRPO 2505.11821(turn-level reward + 退化实锤)/ GiGPO 2505.10978 + `langfengQ/verl-agent`
- Snorkel FinQA(厂商博客,无日期,非 peer-reviewed):snorkel.ai/blog/building-finqa-an-open-rl-environment-for-financial-reasoning-agents/
- Agent-lightning(verl Triplet 传播判断):microsoft.github.io/agent-lightning/latest/algorithm-zoo/verl/
