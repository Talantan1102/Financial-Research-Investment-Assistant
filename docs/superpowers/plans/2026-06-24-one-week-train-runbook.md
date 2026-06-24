# 一周 SFT+RL 训练 Runbook（命令清单）

> 配套 `2026-06-24-eval-data-distribution-*`。**命令可信度标记**:✅ 已验证接口 / 🔨 需先建 / ⚠️ 对 pin 的 verl tag 核 / ⚙️ 填你的值。
> 路径前缀(本机 worktree):`WT=/mnt/d/mys/Financial-Research-Investment-Assistant/.claude/worktrees/eval-intent-coverage`;后端 `cd $WT/backend`。
> Python = WSL fria-venv:`PY=/home/administrator/fria-venv/bin/python`(AutoDL 上换成实例里的 venv)。

---

## D0 · 前置(开工前备齐)

```bash
# ⚙️ 1. 真 tushare 凭证(生成数据 + 冻 cassette 用)。写进 backend/.env:
#    TUSHARE_MODE=real
#    TUSHARE_TOKEN=<你的token>
#    TUSHARE_BASE_URL=http://tu.brze.top/dataapi      # 见记忆"接真 tushare"
#    POSTGRES_PASSWORD=postgres123                     # 本机测试库
# ⚙️ 2. 强模型 API key(SFT 采轨迹用,如 deepseek):配进 chatloop 的 model registry + 环境变量
# ⚙️ 3. AutoDL 账号 + 余额;想好 D3 便宜卡(4090) / D4-7 A100-80G 两段租期
# ⚠️ 4. pin verl tag(强烈建议 v0.8.0):git clone + git checkout v0.8.0,所有键以该 tag 的 rollout.yaml 为准
```

---

## D1 · 生成数据(0 卡,CPU+tushare) + 写打标编排

### 1a. ✅ 生成候选池 + 评测池

```bash
cd $WT/backend
# 默认 train_sample=90 只股,配 11 个意图 ≈ ~3000 候选;val/test 各 10 只 ≈ 评测偏少
set -a; source .env; set +a            # 载入 tushare 真数据凭证
$PY -m eval.question_gen.build_datasets
# 产出: backend/eval/question_gen/data/{train,val,test}.jsonl
```

**✅ 校验产出(意图/难度/量)**:
```bash
$PY - <<'PYEOF'
import json
from collections import Counter
for s in ("train","val","test"):
    rows=[json.loads(l) for l in open(f"eval/question_gen/data/{s}.jsonl",encoding="utf-8") if l.strip()]
    print(s, len(rows), dict(Counter(r["intent"] for r in rows)))
PYEOF
```
- ⚙️ 若 train < ~3000 或 val+test < ~500:调 `build_datasets.py` 顶部 `_TRAIN_SAMPLE`/`_VAL_SAMPLE`/`_TEST_SAMPLE`(分别约 90 / 15 / 15)后重跑。
- 评测股侧应见 valuation_calc / portfolio_calc 非 0(承 #183 `_sample_balanced`);若为 0,加大 val/test_sample。

### 1b. 🔨 写 `run_tagging` 编排(现是 NotImplementedError 壳)

在 `backend/eval/question_gen/tag_cases.py` 把 `run_tagging` 实现成(骨架,⚙️ 模型名/路径填你的):
```python
async def run_tagging(candidate_path, out_manifest, base_model, strong_model,
                      collect_dir, *, n_base=8, k_strong=5, ideal_steps_by_diff=None):
    from eval.question_gen import case as case_mod, runner, cleanliness
    cases = case_mod.load_jsonl(candidate_path)
    # 1) 基座 N=8 测通过次数
    base = await runner.run_passk(cases, k=n_base, model=base_model)
    counts = base["per_case_counts"]                       # ✅ #185 已暴露
    # 2) 强模型 k=5 collect 轨迹(gold 隔离写盘)
    await runner.run_passk(cases, k=k_strong, model=strong_model, collect_dir=collect_dir)
    # 3) 数每题干净轨迹(第二道闸)
    trajs = [json.loads(l) for l in open(collect_dir/"trajectories_raw.jsonl",encoding="utf-8")]
    clean = {}
    by_id = {c.case_id: c for c in cases}
    for t in trajs:
        ideal = (ideal_steps_by_diff or {}).get(by_id[t["case_id"]].difficulty, 8)
        if cleanliness.is_clean(t, ideal_steps=ideal):
            clean[t["case_id"]] = clean.get(t["case_id"], 0) + 1
    # 4) 组装 manifest
    rows = tag_cases.build_manifest_rows(counts, n_base, clean, cases)   # ✅ #185 已建
    dump_manifest(rows, out_manifest)
```
单测加在 `test_tag_cases.py`(mock runner.run_passk),确认编排串得对。**这步不跑模型,纯写代码 + 单测**。

---

## D2 · 派生器验真数据(0 卡) + 装 verl 环境

```bash
# ✅ 派生器(已合)喂真数据跑一遍(用占位 manifest 验股票不相交 + 三套产出)
# 真 manifest 要 D4 打标后才有;D2 先用 D1 的 train/eval 跑 write_sets 的 IO 路径
cd $WT/backend && $PY - <<'PYEOF'
from pathlib import Path
from eval.question_gen import case as c, derive_sets
cand=c.load_jsonl("eval/question_gen/data/train.jsonl")
ev=c.load_jsonl("eval/question_gen/data/test.jsonl")
fake=[{"case_id":x.case_id,"intent":x.intent,"tags":{"in_rl":True},
       "reward_eligible":x.gold_shape in ("scalar","multi_scalar"),"sft_clean_count":1} for x in cand[:50]]
print(derive_sets.write_sets(cand, fake, ev, Path("/tmp/derive_smoke")))   # 应不报股票相交
PYEOF
```

```bash
# ⚠️ AutoDL/本地 装 verl(pin tag);键以该 tag 为准
git clone https://github.com/volcengine/verl && cd verl && git checkout v0.8.0
pip install -e .   # 按 verl 文档装 sglang 对应版本(recipe 提到 verl0.6-sglang0.5.2 类组合)
```

---

## D3 · 管线调通(便宜卡 1×4090,小模型,最大风险)

> 用 **Qwen3-0.6B/1.7B** 在 4090 上跑通 verl+sglang+cassette+oracle,**撞掉版本/tokenization/TIS/reward 坑**,别拿 A100 调 bug。

```bash
# ✅ 先把题集转 verl parquet(每行 prompt/agent_name=tool_agent/reward_model.ground_truth/tools_kwargs)
#    照 recipe §2.7 的 gsm8k_tool_agent_loop.py 改一个 fin_tool_agent_loop.py(🔨 你写,oracle 真值进 create_kwargs)
# ⚠️ verl GRPO 2-step 冒烟(改自 recipe §2.5 脚本;模型换小,total_training_steps=2)
python3 -m verl.trainer.main_ppo \
  --config-path=$VERL/examples/sglang_multiturn/config --config-name='fin_multiturn_grpo' \
  algorithm.adv_estimator=grpo \
  actor_rollout_ref.model.path=Qwen/Qwen3-1.7B \
  actor_rollout_ref.rollout.name=sglang \
  actor_rollout_ref.rollout.mode=async \
  data.return_raw_chat=True \
  actor_rollout_ref.rollout.multi_turn.enable=True \
  actor_rollout_ref.rollout.multi_turn.tool_config_path=<你的 tushare_tool.yaml> \
  actor_rollout_ref.rollout.agent.default_agent_loop=tool_agent \
  actor_rollout_ref.rollout.multi_turn.max_tool_response_length=4096 \
  custom_reward_function.path=<你的 oracle_reward.py> custom_reward_function.name=compute_score \
  reward_model.enable=False reward_model.reward_manager=naive \
  actor_rollout_ref.rollout.n=8 \
  trainer.n_gpus_per_node=1 trainer.nnodes=1 \
  trainer.total_training_steps=2
```
**过闸标志**:跑完不报错 + grep 日志无 `Inconsistent training and inference tokenization` + reward 非全 0(看 `Error in reward_fn:` 没刷屏)。
**必撞的坑(recipe §4.4 / §0)**:`max_tool_response_length` 默认才 256(财务返回必超,务必调大)、Qwen3 reasoning 被 chat template 剥导致 tokenization mismatch、多步精度漂移要开 **TIS**。

---

## D4 · 打标(A100-80G) + 1-epoch 校准

```bash
# 🔨 用 D1 写好的 run_tagging。⚙️ base_model=你的 qwen3-8b(本地 sglang 起,跟 RL 同权重!) strong=deepseek API
cd $WT/backend && set -a; source .env; set +a
$PY - <<'PYEOF'
import asyncio
from pathlib import Path
from eval.question_gen import tag_cases
asyncio.run(tag_cases.run_tagging(
    candidate_path="eval/question_gen/data/train.jsonl",
    out_manifest=Path("eval/question_gen/data/manifest.jsonl"),
    base_model="qwen3-8b",            # ⚙️ 本地 sglang 服务名/路径,与 RL 基座同一份权重
    strong_model="deepseek-chat",     # ⚙️ API
    collect_dir=Path("eval/question_gen/data/traj"),
))
PYEOF
# ✅ 派生三套
$PY - <<'PYEOF'
from pathlib import Path; import json
from eval.question_gen import case as c, derive_sets
cand=c.load_jsonl("eval/question_gen/data/train.jsonl")
ev=c.load_jsonl("eval/question_gen/data/test.jsonl")
man=[json.loads(l) for l in open("eval/question_gen/data/manifest.jsonl",encoding="utf-8")]
print(derive_sets.write_sets(cand, man, ev, Path("eval/question_gen/data/sets"),
                             per_case_cap=2, per_job_cap=80))   # ⚙️ per_job_cap 调到 SFT≈500
PYEOF
```
**🔨 1-epoch RL 校准**:拿派生出的 `sets/rl_train.jsonl` 切 ~100 道,跑 verl GRPO `total_epochs=1`,**记每 epoch 墙钟** → 推全量 GPU-小时,定 D6-7 预算。

---

## D5 · SFT(LoRA 8B,A100,几小时)

```bash
# ⚠️ 用 verl 官方 Qwen3-8B LoRA FSDP 脚本(research 证实存在),数据=SFT 种子轨迹(标准 OpenAI 多轮)
#    examples/tuning/lora/run_qwen3_8b_fsdp.sh —— 改 data 指向你的 sft_seeds、产 LoRA adapter
bash $VERL/examples/tuning/lora/run_qwen3_8b_fsdp.sh   # ⚙️ 改脚本内 model.path / data / save_path
# 产出: SFT LoRA adapter(D6 RL 的起点)
```

---

## D6 · RL GRPO 正式跑(A100-80G,从 SFT 起)

```bash
# ⚠️ 改自 D3 脚本:模型换 qwen3-8b、加载 D5 的 LoRA adapter、去掉 total_training_steps 限制、加 LoRA 键
python3 -m verl.trainer.main_ppo \
  --config-path=$VERL/examples/sglang_multiturn/config --config-name='fin_multiturn_grpo' \
  algorithm.adv_estimator=grpo \
  actor_rollout_ref.model.path=<qwen3-8b 路径> \
  actor_rollout_ref.model.lora_rank=32 actor_rollout_ref.model.lora_alpha=64 \   # ⚠️ 键名对 v0.8.0 核
  actor_rollout_ref.rollout.name=sglang actor_rollout_ref.rollout.mode=async \
  actor_rollout_ref.rollout.gpu_memory_utilization=0.5 \                          # ⚙️ 80G 上 8B+KV 调这个
  actor_rollout_ref.rollout.tensor_model_parallel_size=1 \                        # 单卡 TP=1;2 卡可 TP=2
  data.return_raw_chat=True data.train_files=eval/question_gen/data/sets/rl_train.jsonl \
  actor_rollout_ref.rollout.multi_turn.enable=True \
  actor_rollout_ref.rollout.multi_turn.tool_config_path=<tushare_tool.yaml> \
  actor_rollout_ref.rollout.agent.default_agent_loop=tool_agent \
  custom_reward_function.path=<oracle_reward.py> reward_model.reward_manager=naive \
  actor_rollout_ref.rollout.n=8 \
  trainer.n_gpus_per_node=1 trainer.nnodes=1 \                                     # 想快:加到 2 + TP/DP
  trainer.total_epochs=<据 D4 校准定> trainer.save_freq=<N> trainer.logger='["console","mlflow"]'
```
**盯**:reward 曲线上行、`num_turns` 合理、无 reward 玄学崩(崩→查 TIS / tokenization mismatch)。

---

## D7 · 评测重采 k=16 + 收尾

```bash
# ✅ held-out 评测,每题重采 16 次读稳 pass@1
cd $WT/backend && $PY -m eval.question_gen.runner eval/question_gen/data/sets/eval.jsonl 16 6
# 产出: 按 difficulty×indicator 分桶 pass@k;answers 落 eval/.../passk_answers.jsonl
# ⚙️ 用 RL 后的 qwen3-8b(加载 RL adapter)跑评测,对比 SFT 前/后/RL 后三条
```

---

## 关键提醒(重申)

1. **D3 是唯一可能爆周的环节**(verl 版本坑)。便宜卡 + 小模型先撞,留 D7 缓冲。
2. **打标的基座必须 = RL 基座同一份 qwen3-8b 权重**(别用随便的 API),否则"学得动带"白测。
3. **D4 校准是闸**:跑不完就砍规模(少 epoch / n=8 不上 16 / 减 rl_train 量),保"能跑通、reward 上行的闭环"作为作品,别追大规模。
4. ⚠️ 所有 verl 键以你 **pin 的 tag** 的 `rollout.yaml`/`base_tool.py` 为唯一真相;recipe 标【未核实】的(LoRA 键、reward_kwargs)逐个对一遍再上。
