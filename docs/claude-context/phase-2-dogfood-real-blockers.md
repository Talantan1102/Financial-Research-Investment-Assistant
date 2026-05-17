---
name: Phase 2 dogfood 撞实的 4 大真工业问题
description: v1.x DD report eval Phase 2 真 dogfood 尝试撞实 — OpenRouter 模型 ID format / 账户充值 / region block / free model 全部 reasoning,实操层面真跑 LLM 比 spec 预想难
type: project
---

## Phase 2 dogfood 真跑撞实 (2026-05-17)

### 上下文

Phase 2 全部 12 task ship 完(commit `b7eac2e`),95 PASS test + framework
scaffold 全 work。尝试真跑 `backend/scripts/run_phase2_ablation_dogfood.py`
看 4×5 ablation 矩阵真数字 — 撞实 4 个 spec § 4.1 / § 4.3 / T2.6 实施都
没预料到的真工业问题,**实操层面真跑 LLM 比预想难**。

### 撞实的 4 大问题

#### 问题 1 — Spec-prescribed model ID 跟 OpenRouter 实际命名不一致

我们 ship 的 `eval/dd_report/llm_swapper.py::EVALUATOR_MODELS` 白名单 用 short
ID(`gpt-4o-2024-05-13`, `qwen2.5-72b-instruct`, `deepseek-v3` 等)。

OpenRouter 实际命名格式是 `<vendor>/<model-name>`:
- `openai/gpt-4o-2024-05-13`
- `qwen/qwen-2.5-72b-instruct`
- `deepseek/deepseek-v3.2`(注:DeepSeek 已经 migrate 到 v3.1/v3.2/v4 系列, `v3` 不再存在)
- `anthropic/claude-sonnet-4.6`(latest = 4.6,plan 写的 `claude-sonnet-4` 不存在)

实测命中错误:
```
deepseek-v3: FAIL - Error code: 400 - {'error': {'message': 'deepseek-v3 is not a valid model ID', 'code': 400}}
qwen2.5-72b-instruct: FAIL - Error code: 400 - {'message': 'qwen2.5-72b-instruct is not a valid model ID'}
```

**Why spec 错**:写 spec 时(2026-05-17)我 reference 的 model ID 是从 spec 论文 +
HuggingFace name 抄,没 verify OpenRouter 实际 API。**这是 spec § 4.1 决策 1
"选 cutoff < 2024 的 3 LLM" 的 implementation gap — spec 选对了 model,但
不知道 OpenRouter route 名字带 vendor prefix**。

**How to apply 修复**:
- 改 `BACKTEST_EVALUATOR_MODELS` 用 OpenRouter 实际 ID:`("openai/gpt-4o-2024-05-13", "qwen/qwen-2.5-72b-instruct", "deepseek/deepseek-v3.2")` 或类似
- 但注意 `deepseek-v3` 已不存在,只能用 `deepseek-v3.2` 或 `deepseek-chat`(后者 cutoff 也是 2024+)— 真正"cutoff < 2024 的 DeepSeek"在 OpenRouter 已 deprecate
- Phase 2.x 真接 OpenRouter 时,先 `httpx.get('https://openrouter.ai/api/v1/models')` 拉实际 list,再选 cutoff 合适的 — 不要从 spec 假设 model ID

#### 问题 2 — OpenRouter 账户充值为 0,任何付费模型 402

```
deepseek/deepseek-chat: FAIL - 402 - {'error': {'message': 'Insufficient credits.
This account never purchased credits.'}}
qwen/qwen3.6-flash: 402 same
```

`Insufficient credits. This account never purchased credits` 说明 user 创建
OpenRouter 账户但**从未充值**。所有付费模型(包括最便宜 `qwen-2.5-72b-instruct
$0.36/M token`)都 402 拒绝。

**Why 没预料到**:Phase 1 ship 时只验 OpenAI key auth(`unset proxy + chat call`
go through),没验 account credit balance。OpenRouter 跟 OpenAI 不同 — 它是
聚合网关,需要单独充值。

**How to apply 修复**:
- User 充 ~$5 OpenRouter credits(`openrouter.ai/credits`),Phase 2 dogfood
  4×8 case 预算 ~$5(per spec § 5.3 估算)
- 或者用国内 DashScope provider 改造 LLMSwapper(已有 API key)— 但 cutoff
  问题:deepseek-v4-flash 是 2026-04,跑 2024-2025 backtest case 会 leak,
  违反 spec § 4.1 决策 1。只能跑 sanity 副线(8 case cutoff=2026-04-30)。

#### 问题 3 — OpenAI / Anthropic 模型 region-blocked(403)

```
openai/gpt-4o-2024-05-13: 403 - This model is not available in your region.
anthropic/claude-sonnet-4: 403 same
```

OpenRouter 对 OpenAI/Anthropic 模型有 region restriction(大陆 IP 直接 403)。
即使账户有 credit 也访问不到。

**Why 没预料到**:Spec § 4.1 决策 1 选 GPT-4o + Qwen + DeepSeek 3 LLM cross-check
的考虑是 "cutoff 时间 + 跨厂商多样性",没考虑 region availability。OpenRouter
的 vendor routing 对地区敏感。

**How to apply 修复**:
- 替换 backtest 主线 evaluator:`gpt-4o-2024-05-13` → 国产 cutoff < 2024 模型(`qwen-2.5-72b-instruct` 或 `deepseek-v3.2`),牺牲跨厂商多样性
- 或者 user 用 VPN(违 OpenRouter ToS)
- 或者切到 DashScope(国产 native,不受 region 限制)
- 推荐:Phase 2.x dogfood 主线 = `qwen-2.5-72b-instruct` + `deepseek-v3.2` + `meta-llama/llama-3.3-70b`(全国产/开源,不 region block)

#### 问题 4 — OpenRouter free models 几乎全是 reasoning model + 严格 rate limit

OpenRouter 上 24 个 `:free` 模型:
- 多数是 reasoning models(content=None,推理过程在 `reasoning_content` 字段)
- 非 reasoning 的 free model 大部分 OpenAI/Anthropic free preview(region blocked)
- 唯一 chat completion 形态 + 不 region block 的 `deepseek/deepseek-v4-flash:free`
  实测返回 `content=None, reasoning_content='_02 b1: pie album\n# frozen in'`(乱码)

非 reasoning 的国产 free model 全部 429:
```
qwen/qwen3-next-80b-a3b-instruct:free: 429 - Provider returned error
meta-llama/llama-3.3-70b-instruct:free: 429 same
qwen/qwen3-coder:free: 429 same
```

**Why 没预料到**:OpenRouter free tier 实际不能稳定跑 32 case × 6 LLM call 的
dogfood(rate limit 太严)。Plan 当初讨论"成本 ~$28 / 跑"假设的是付费模型,
没考虑 user 可能用 free tier。

**How to apply 修复**:
- Free tier 不可作 dogfood evaluator 用 — 必须付费 model
- 如果想免费验框架:用 mock LLM(class 内部 return fake JSON),不真调 LLM。
  我们 ship 的 L0 unit test 已经是这套 — 95 PASS 就是这种验证。

#### 问题 5(顺带撞实)— git workflow:detached HEAD 期间 commit 是 orphan

T2.7 spec reviewer 跑 `git checkout e52e750`(parent commit)验 pre-existing
broken test。**没切回 branch**,HEAD 留 detached。后续 9 个 subagent 在 detached HEAD
上 commit(T2.7 fix → T2.11 cleanup),branch ref `feat/external-agent-survey` 留在
`2fc2d95`(T2.7 feat)。

到 verification 阶段 user 看到的 `HEAD` 实际是 `b7eac2e`,看起来正常 — 但其实
**branch ref 跟 HEAD 严重分叉**。一旦 `git checkout feat/external-agent-survey`
就会 silent reset 到 `2fc2d95`,丢失 9 commits 的 working tree state(commit
object 还在,只是 branch 不指向)。

**根因**:subagent 跑 `git stash && git checkout <SHA> && pytest && git checkout
<BRANCH> && git stash pop` 模式时,如果 `git checkout <SHA>` 让 HEAD detached,
后续在 detached HEAD 上做的 commit 都成 orphan。

**修复**(2026-05-17 实操):`git merge --ff-only b7eac2e` 把 branch ref 推进到
final commit,所有 9 个 orphan commit 重新 reachable。Working tree 同步,数据 0 丢失。

**预防** (Phase 3 + 后续):
- Subagent 跑 git checkout <SHA> 验证后,必须 `git switch -` 或 `git switch <branch>` 回 branch,**不要单纯 `git checkout <branch>` — 后者在 detached HEAD 已有 commit 时不会更新 branch ref**
- 或者用 `git worktree add` 单独 worktree 跑验证,完成 `git worktree remove`,主 worktree 不动 HEAD
- 平台层:Bash tool 跑 `git checkout` 后探测 detached state,提示"现在在 detached HEAD,后续 commit 会 orphan"

### 行动决策

1. **真 dogfood 推迟** 直到 user OpenRouter 账户充值 + LLMSwapper model ID 修正
2. **Phase 2 framework ship 完毕状态不变** — 95 PASS + 12 task 都正确,只是 真 LLM
   call 在 user 当前 OpenRouter account state 下不可行
3. **下一步建议**:
   - (a) user 充值 $5 OpenRouter + 我修 `BACKTEST_EVALUATOR_MODELS` whitelist 用国产
     non-region-blocked ID + 重跑 dogfood
   - (b) Phase 3 改造 LLMSwapper 多 provider 支持(OpenRouter + DashScope + ...
     ),不依赖单一聚合网关
   - (c) Drop OpenAI 模型,backtest 主线只用国产(qwen + deepseek + llama)
     — 牺牲跨厂商多样性换实际可执行

### 沉淀的 plan/spec 修正项

写 Phase 3 spec 时必须做:
1. **每个外部 LLM provider 必须 pre-flight check**:account credit balance + region
   reachability + model id format,跑实际 1 个 API call 验通
2. **不要假设 OpenRouter 是"所有模型一站通"** — region/credit/rate-limit 每个 model
   独立。Plan 假设的 cross-LLM matrix 必须按 user 实际可用模型回头改
3. **subagent git workflow** — `git checkout` 改用 `git switch`(更明确切 branch
   语义,detached 时报错),写进 finishing-a-development-branch skill 守护
