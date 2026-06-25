# verl 补丁(D3 训练依赖)

D3 的 verl GRPO + sglang 训练依赖对 **verl** 框架的若干改动。verl 是独立第三方仓
(`verl-project/verl`,本机 clone 在 `/root/autodl-tmp/verl`),**不属于本项目仓**,故其改动
不能进本项目 PR。这里以 patch 形式记录,保证可复现:换机器时还原即可。

## 基线
- verl tag **v0.8.0**(commit `7aed6b2`)
- 环境:torch 2.9.1+cu128 / sglang 0.5.8 / flashinfer 0.6.1 / python 3.10(AutoDL `envs/verl`)

## 应用
```bash
cd /path/to/verl            # clone 并 checkout v0.8.0
git apply /path/to/repo/backend/eval/question_gen/verl_bridge/verl_patches/d3_verl_v0.8.0.patch
```

## 4 处改动及原因
1. **`verl/utils/attention_utils.py`** —— flash_attn 缺失时回退 transformers 纯 torch 的
   unpad/pad/index_first_axis。本环境 torch2.9+py3.10 无 flash_attn 预编译 wheel;且 rollout 走
   sglang、FSDP forward 走 sdpa,flash_attn 编译 kernel 本不需要,bert_padding 仅纯 torch 工具。
2. **`verl/workers/engine/fsdp/transformer_impl.py`** —— 构造 `LoraConfig` 前剔除值为 None 的键
   (如 `target_parameters`)。peft 降到 0.14(为兼容 sglang 的 torchao 0.9)不识别这些新参数。
3. **`verl/workers/rollout/sglang_rollout/async_sglang_server.py`** —— generate 仅在非 merge 模式
   带 LoRA adapter;merge=True 时 adapter 已并入基座,带上会触发 "adapter never loaded"。
4. **`verl/workers/rollout/sglang_rollout/sglang_rollout.py`** —— sgl_kernel 版本检查的 except 放宽
   到 `Exception`(包名缺失抛的是裸 Exception 非 AssertionError),回退到 sglang 0.5.8 的 `sgl_kernel` 名。

## 另需(非源码改动,见 [[rl-training-uses-verl-sglang]] / 设计文档)
- `pip install peft==0.14.0`(配合 #2)
- flash_attn **不装**(#1 已绕开;torch2.9/py3.10 也无 wheel)
- 训练前起工具服务:`PYTHONPATH=backend python -m eval.question_gen.verl_bridge.tool_server`(fria env,真 tushare)
