# Dev-Test-Loop Design Spec

| Meta | |
|---|---|
| **Spec ID** | `2026-04-29-dev-test-loop` |
| **作者** | Talantan (with Claude brainstorming) |
| **日期** | 2026-04-29 |
| **依赖** | 无(基础设施 spec) |
| **后续依赖此 spec 的** | `2026-04-29-v0-skeleton-design`(暂停中,等本 spec 落地后恢复)/ 后续所有 v1+ sub-spec |
| **状态** | Draft — 等用户 review |

---

## 0. 文档定位

本 spec **不是业务功能 spec**,而是**为整个 Financial-Research-Investment-Assistant 重构项目立工程基础设施**:测试分层、依赖管理、LLM 测试模式、CI、评测、可观测、闭环反馈机制。

### 为什么独立成 spec(而非内嵌 v0 skeleton spec)

1. **复用经济性** — v0 / v1 工具迁移 / Memory / 上下文压缩 / 评测深化 等所有后续 sub-spec 都依赖这套基础设施;立独立 spec = 立一次用 N 次。
2. **关注点分离** — 工程基础设施 vs 业务实现是两个维度,挤一起会互相干扰。
3. **闭环不混淆** — dev-test-loop 讨论的是"反馈如何回流",v0 讨论的是"业务怎么写",两者节奏不同。
4. **Portfolio 叙事顺序** — "我先立测试基础设施,再做业务" 是工业项目的真实节奏,叙事更自然。

### 在 roadmap 中的位置

```
[本 spec: dev-test-loop] ─→ [v0 skeleton] ─→ [v1 工具迁移] ─→ [v1+ Memory] ─→ ...
        ↑
   所有后续 spec 都受益于此
```

### Scope

**In-scope(13 项)**:依赖管理 / 测试分层 / LLM 测试三模式 / Mock 边界 / CI / Eval 节奏 / Trace 联动接口 / 闭环反馈 / 本地 DX / Lint+Format+Type / Benchmark 改造路径 / 测试目录组织 / Cassette 版本化。

**Out-of-scope**:CD / 部署、可观测的具体实现(在 v0 spec)、性能 benchmarking 工具(由 trace + eval 体系承担)。

---

## 1. 现状摸底

### 既有资产盘点

| 类别 | 现状 | 评价 |
|---|---|---|
| 测试框架 | pytest + `pytest.ini`,markers `unit/integration`,`asyncio_mode=auto` | ✅ 基线在 |
| 测试目录 | `backend/tests/integration/` + `e2e/`,**无 `unit/`**;`backend/test_mock_*.py` 散在根目录 | ⚠️ 待重组 |
| 现有测试 | e2e 1 个(调旧 `MCPChatService`),integration 2 个(MCP 协议) | ⚠️ v0 重构后大半失效,删 |
| Eval / Benchmark | `benchmark/` 已有 134 + 28 = 162 个用例 + `run_benchmark.py` + `evaluator.py` | 🌟 形态不匹配 v0 chat 主路径,**归档** |
| Mock 层 | `mock_tushare_service.py`(110KB) + `mock_bocha_service.py`(11KB),用 LLM 生成模拟数据 | 🌟 portfolio 叙事点,**保留** |
| LLM 接入 | OpenAI compatible 协议接百炼,默认 qwen3-max | ✅ 改为 deepseek-v4-flash |
| CI / CD | 无 `.github/workflows/` | ❌ 从零建 |
| 依赖管理 | pip + `requirements.txt`,无 lockfile,conda + venv 双轨 | ⚠️ 切 uv |
| Lint / Format / Type | 无任何配置 | ❌ 从零建 |
| Task runner | 仅 `start-services.sh` | ⚠️ 加 poethepoet |
| Trace | 无 | ❌ 等 v0 spec 实现,本 spec 定接口 |

---

## 2. 决策一:测试分层形态

### ① 问题陈述
LLM 项目里 unit 测试断言 `assert response == X` 永远不稳(LLM 非确定);真正的 bug 在 prompt 设计、agent 决策、工具选择、schema 解析这些"软"层;但全靠 e2e 又慢又贵。"对不对" 由 eval 说了算,可 eval 慢且贵。**经典金字塔不适用**,需重新设计。

### ② 业界 alternatives

| 编号 | 形态 | 比例(unit/int/e2e/eval) | 代表 |
|---|---|---|---|
| P1. 经典金字塔 | 70/20/10/0 | Google 测试金字塔、传统后端 |
| P2. 钻石形(中部重) | 20/50/20/10 | LangChain 项目主流、LangGraph 推荐 |
| P3. 沙漏形 | 40/10/40/10 | Mozilla 风格 |
| P4. Eval-driven | 10/10/30/50 | DeepEval / Confident-AI / Promptfoo |
| P5. Behavioral testing | 灵活混合 + 行为断言 | DeepEval、Ragas、自建框架 |

### ③ 选择:**P2 钻石形 + P5 行为断言注入(微调比例)**

我们选 P2 钻石形,但比例从经典 `20/50/20/10` 微调为 `20/50/15/15` —— **削 e2e 升 eval**,理由:LLM 项目里 e2e 跟 eval 在覆盖能力上有重叠(都是端到端跑),而 eval 的"对不对"判别能力远强于 e2e 的 cassette 断言,所以匀 5pp 给 eval 更划算。

| Layer | 比例 | 跑什么 | LLM 状态 | 时长目标 | 触发 |
|---|---|---|---|---|---|
| **L0 单元** | ~20% | Pydantic schema、纯函数、tier 路由、span builder、cost 计算公式、cassette parser | 不调 LLM(`LLM_MODE=none`) | <5s 全跑 | 每次保存 / 每 PR |
| **L1 集成** | ~50% | 单 agent + 横切服务联动;**行为断言**(如 `assert plan.tool_calls[0].name == "get_stock_quote"`);tool dispatch 链路 | LLM 走 mock client (`LLM_MODE=mock`) | <30s 全跑 | 每 PR |
| **L2 E2E 子集** | ~15% | HTTP → graph → Responder 流式;golden 输入 ~20 条 | LLM 走 cassette (`LLM_MODE=cassette`) | <2min 子集 / <5min 全 | 每 PR 子集 / nightly 全 |
| **L3 Eval** | ~15% | 50-70 条 golden 用例 + LLM-as-judge 多维度打分 | LLM 走真实百炼 deepseek-v4-flash (`LLM_MODE=live`) | ~5-15min | 手动 / nightly / pre-release |

**`LLM_MODE` 取值**: `none | mock | cassette | live` — 按 layer 强制,各 layer `conftest.py` 设置 fixture 覆盖。

### ④ 量化评估方案
- **PR 反馈速度**: 一次 `poe test`(L0+L1+L2 子集)P95 ≤ 90s
- **Bug 发现层级分布**: 每个修过的 bug 标记最先 surface 的 layer;**目标 ≥ 60% 的 bug 在 L0+L1 被发现**
- **Flake 率**: L1 + L2 ≤ 1%
- **Coverage**: L0+L1 行覆盖 ≥ 70%(sanity check);**eval 通过率作为更核心覆盖**(golden 通过率 ≥ 90% 才能 release v0)
- **Cost guardrail**: nightly L3 单次 ≤ ¥20

---

## 3. 决策二:依赖管理选型

### ① 问题陈述
项目当前 `pip + requirements.txt + conda + venv` 双轨,**无 lockfile**:跨机器装出依赖版本可能差异;CI 与本地不可重现;portfolio 角度看 `requirements.txt` 没 lock 是 2024+ 工程基线缺失。

### ② 业界 alternatives

| 编号 | 工具 | Lock | Speed | 现代化 |
|---|---|---|---|---|
| D1. pip + requirements.txt(现状) | 无 | baseline | 旧 |
| D2. pip-tools | 有 | baseline | 旧 |
| D3. Poetry | 有 | baseline | 中 |
| D4. PDM | 有 | baseline | 中 |
| **D5. uv**(选) | 有 | **10-100×** | 最新 |
| D6. Hatch | 弱 | baseline | 中 |
| D7. Conda only | 有 | 慢 | ML 专用 |

### ③ 选择:**D5 uv**

**Conda 与 uv 分工**:
- conda `deepresearch` —— 提供 Python 解释器 + native ML deps(Milvus 客户端等如有 native binding)
- uv —— 在 conda env 内管理 PyPI 包,产 lockfile

**配置形态**:
- `backend/pyproject.toml` 维护 `[project] dependencies` + `[project.optional-dependencies] dev`
- `backend/uv.lock` 进 git
- 本地 / CI 同一命令:`uv sync --all-extras`
- CI 用 `astral-sh/setup-uv@v3`

### ④ 量化评估方案
- 本地 install 速度: `uv sync` vs `pip install -r requirements.txt` 同一冷状态对比,**目标 ≥ 5× 加速**
- CI install 时间:**目标 < 15s**(GH Actions Linux runner + uv cache)
- Lockfile reproducibility: 跨 macOS / Linux 双平台 install 后 `uv pip freeze` 输出一致
- 依赖解析时间(锁定一个新包):**目标 < 2s**

---

## 4. 决策三:LLM Mock 客户端形态

### ① 问题陈述
P2+P5 的 L1(占 ~50% 测试)走 mock LLM 客户端。**怎么写 mock**直接决定 L1 flake 率、写测试速度、prompt 改动维护成本、行为 fidelity。

注意区分两层:
- **LLM mock**(给 `LLMService` 用) — 本节讨论
- **数据层 mock**(`mock_tushare_service.py` 等,LLM-driven) — 不动,作为既有资产保留

### ② 业界 alternatives

| 编号 | 形态 | 代表 |
|---|---|---|
| MC1. 静态 dict 映射 | LangChain `FakeListLLM`、Anthropic SDK `FakeAnthropic` |
| MC2. Pattern-based router | 自建 if-else / regex |
| MC3. LLM-as-mock | 项目里 `mock_tushare/mock_bocha` 的形态 |
| MC4. Recorded fixture | pytest-recording、自建 |
| **MC5. Hybrid 三层组合**(选) | 自建组合 |

### ③ 选择:**MC5 Hybrid 三层组合**

| 层 | 形态 | 适用场景 |
|---|---|---|
| 数据层 mock(已有) | MC3 LLM-as-mock | Tushare / Bocha 等外部数据 API mock,**保留不动** |
| LLM mock 主力 | MC1 静态映射 + MC2 pattern fallback | L1 中 ~80% 的 agent 决策测试,fixture 在 `tests/fixtures/llm_mocks/agent_decisions.yaml` |
| LLM mock 复杂 case | MC4 recorded fixture | L1 中 ~20% 的复杂场景(critic 多维度打分、多轮对话),`tests/fixtures/llm_mocks/recorded/*.json` |

**接口统一**:
```python
class MockLLMClient:
    def chat(prompt, schema) -> Response  # 跟 LLMService 接口对齐
    # 内部 pipeline: static_dict → pattern_router → recorded_fixture → fail
```

### ④ 量化评估方案
- **Mock fidelity**: 同一 input 在 mock vs live 下,L1 测试断言通过率差异 ≤ 5%(**按需手动触发** `poe test-fidelity`,不进 nightly 默认链路 — 因为这件事只在 mock 客户端大改时需要校对)
- **Mock 维护成本**: 一次 prompt 改动平均改 mock 行数 ≤ 8(每次 prompt 改动 PR 时人工估算,记录在 PR description)
- **L1 flake 率**: 同 mock 配置连跑 100 次失败 ≤ 1(`poe test-flake-check` 触发,judge release 前跑一次)
- **写新 L1 测试时间**: 新 agent 决策测试从写到跑通 ≤ 10min(感性指标,不强制量化)

---

## 5. 决策四:Cassette 录制重放 + 三模式切换

### ① 问题陈述
L2 测试要在不打真 LLM 前提下跑出"真实行为",做法是**录制一次真实调用 → 后续跑回放(cassette)**。围绕这个 cassette 有四个子问题:**工具选什么 / 进 git 吗 / 如何检测失效 / 三模式怎么切**。

### ② 业界 alternatives

**Cassette 工具**:
- C-a. pytest-vcr (vcrpy 系) — 经典,vcrpy 维护放缓
- C-b. pytest-recording — 2024-2025 主流,vcrpy 现代分支(选)
- C-c. SDK-level 自建 — 灵活但重复造轮子

**进 git 策略**:
- 不进 git — 仓库瘦但 CI 跑不了
- **进 git + sanitize**(选)
- Git LFS — 适合大 cassette

**失效检测**:
- 手动 — 反馈慢
- **半自动 nightly validation**(选)— 跑 cassette 真打 LLM 跟旧 output 做 LLM-as-judge 对比
- 全自动 model version 元数据 — provider 不一定暴露

**三模式切换**:
- env var only — 不灵活
- pytest marker only — 命令行场景没用
- **env var + fixture + marker 组合**(选)

### ③ 选择(汇总)

| 维度 | 选择 |
|---|---|
| 工具 | **pytest-recording**(`pip install pytest-recording`) |
| 存储 | **进 git + sanitize**;单 cassette ≤ 50KB,总目录 ≤ 5MB |
| 失效检测 | **nightly validation job**:抽 10 个 cassette 真打 LLM,LLM-as-judge 跟旧 output 比,差异超阈值开 issue |
| 切换 | **env var `LLM_MODE` + fixture + marker** 组合 |

**配置草稿**:
```python
# tests/conftest.py
@pytest.fixture
def vcr_config():
    return {
        "filter_headers": ["authorization", "x-dashscope-api-key", "x-api-key"],
        "filter_post_data_parameters": [],
        "decode_compressed_response": True,
        "record_mode": os.getenv("VCR_RECORD_MODE", "none"),
        "match_on": ["method", "scheme", "host", "port", "path", "body"],
    }
```

**Cassette 目录**:`backend/tests/fixtures/cassettes/test_*.yaml`,进 git。

### ④ 量化评估方案
- **Cassette 总大小**: ≤ 5MB(超出说明该用 mock)
- **Cassette 失效率(drift 率定义)**: 一次 nightly validation 抽 10 个 cassette,若 LLM-as-judge 给"cassette output vs new live output"的语义相似度 < 0.8 则记为 1 个 drift;月累计 drift 数 / (10 × 30 = 300) ≤ **10%**(即每月 ≤ 30 次单条 drift)
- **L2 回放速度**: 单 cassette 测试 ≤ 200ms(vs live 5-15s)
- **模式切换正确率**: `LLM_MODE=mock pytest -m "not live_only"` 跑完后,trace 表中 live 调用记录 = 0
- **Sanitize 覆盖率**: cassette 里 grep `dashscope-` / `sk-` / `bearer ` 关键字,目标 0 命中(pre-commit hook 校验 cassette 文件)

---

## 6. 决策五:CI 形态

### ① 问题陈述
PR 谁触发测试?哪些 blocking 哪些 nightly?Personal portfolio 项目要"工程感"但不能 over-engineering 烧光 GH Actions free quota。

### ② 业界 alternatives

| 编号 | 形态 | 适用 |
|---|---|---|
| CI-1. GH Actions only | 主流个人项目 |
| CI-2. pre-commit only | 不依赖云 |
| CI-3. 商用 SaaS | 企业项目 |
| CI-4. 不做 CI | toy demo |
| **CI-5. GH Actions + pre-commit 组合**(选) | 主流 portfolio |

### ③ 选择:**CI-5**

**三层 job 分布**:

| 层 | 触发 | 跑什么 | 时长目标 | 失败行为 |
|---|---|---|---|---|
| **本地 pre-commit** | `git commit` | ruff format check + ruff check | ≤ 3s | 阻断 commit |
| **PR blocking** | PR open / push | ruff + mypy + L0 + L1 + L2 子集(20 个核心 cassette) | ≤ 5min | PR 红、阻断合入 |
| **Nightly @ 北京 03:00** | cron `0 19 * * *` UTC | L2 全集 + L3 eval(deepseek-v4-flash) + cassette validation + dependency security audit | ≤ 30min | 自动开 GitHub issue |

**Cost guardrail**:
- Nightly job 单次 budget hard limit: **¥20**(env `EVAL_COST_LIMIT_CNY=20`,LLMService 累计成本超阈值即 abort)
- GH Actions 月用量 > 80%(1600min)时,workflow 加 step 发 issue
- PR job **不跑 L3 eval**

**Secrets 管理**:
- `DASHSCOPE_API_KEY` → GH Actions repo secrets,**只 nightly job 用**
- PR job 不需要 LLM key(全靠 mock + cassette 回放)— fork PR 安全保证

**Dependency security audit**:
- `uv pip audit`(或 `pip-audit`),nightly 跑,免费,portfolio 信号

### ④ 量化评估方案
- **PR blocking 时长**: P50 ≤ 3min, P95 ≤ 5min(超时直接 fail PR)
- **Nightly cost / 次**: hard limit ¥20;实际 ≤ ¥5(全用 deepseek-v4-flash)
- **Nightly cost / 月**: hard limit ¥150
- **GH Actions 月用量**: ≤ 50%(1000min);超 80% 自动 issue
- **PR flake 率**: 同 commit 重跑 10 次失败 ≤ 1
- **Drift 检测时效**: nightly 发现 cassette drift 后开 issue,平均关闭 ≤ 3 天
- **Portfolio 信号**: repo 主页 CI badge passing;最近 30 天 CI 运行 > 50 次

---

## 7. 决策六:全局 LLM Model + Tier Router 占位

### ① 问题陈述
Q3(LLM provider 策略,session a4ce0864)原方案是 fast/balanced/deep 三 tier 各对应不同 model(deepseek-v3.2 / deepseek-v4 / qwen-max)。**重新审视后,v0 简化为单 model**。

### ② Tradeoff(诚实记录)

**失去**:
- 多模型路由叙事(qwen-max deep tier 故事不再用作 portfolio 重点)
- 复杂推理无 deep tier 兜底 — 统一交给 deepseek-v4-flash,Critic 质量可能下来

**得到**:
- Cost 极简(v4-flash 是项目最便宜的 model)
- API 路径单一(凭证管理简化)
- Eval 真实性 100%(SUT = prod)
- 新叙事:**"我设计了 tier 路由 infrastructure,v0 出于 cost simplicity 把三 tier 都映射到同一 model;架构支持后续仅靠 config 切到多 model"** — YAGNI 派的好故事,工程成熟度更强

### ③ 选择:**全局 deepseek-v4-flash + tier router 接口保留**

```python
class LLMService:
    def chat(self, prompt, tier: Literal["fast", "balanced", "deep"], schema=None):
        model = self.tier_router.resolve(tier)  # 接口存在
        # v0 默认配置(全 v4-flash):
        # tier_router.config = {fast: "deepseek-v4-flash",
        #                       balanced: "deepseek-v4-flash",
        #                       deep: "deepseek-v4-flash"}
```

v1 想接 qwen-max 时,**改 yaml/env 配置一行,不动 caller 代码**。

### ④ 量化评估方案
- **Tier router 接口稳定性**: v0~v3 内不破坏性变更
- **Model 切换成本**: 切到多 model 时,需修改的代码文件数 = 1(config.yaml)
- **Eval 实际 cost**: 70 用例 × 3K tokens / 用例 × v4-flash 价位 ≈ **¥1-2 / 次**
- **¥20 hard limit 触发率**: 目标 0(留 10× buffer 仅作 fail-fast 兜底)

---

## 8. 决策七:Eval 系统内容设计

### ① 问题陈述
CI 节奏已定(nightly 跑),**eval 跑什么内容、怎么打分、什么算通过**还没定。涉及:
- 现有 162 用例怎么改造?
- LLM-as-judge rubric 怎么写?
- 评测哪些维度?
- 什么算 pass?
- 怎么验证 judge 自身可信?

### ② 业界 alternatives

**Benchmark 改造路径**:
- E1. 整体复用 — 形态错位
- E2. 提取核心子集 + 新写
- **E3. 全新写 + 162 用例归档**(选)
- E4. 全用 + 新增

**LLM-as-judge rubric**:
- R1. 单一总分 0-100
- R2. 多维度(N 维各 0-10)
- R3. Pass/Fail binary
- **R4 = R2 + JSON 结构化输出 + 每维 evidence**(选,简化版)

**评测维度**:
- v0 chat 模式选: `factuality + tool_correctness + coverage + structure`
- v1 研报模式加: `citation + risk_disclosure`

**通过阈值**:
- T1. Hard threshold per case
- T2. Weighted score
- **T3. 通过率 + 维度 regression**(选)

**Judge 验证**:
- 经典:人工标 30 条 + Pearson ≥ 0.75
- **e-alt(选)**:Cross-judge Spearman + Sanity check

### ③ 选择(汇总)

| 子决策 | 选择 |
|---|---|
| 改造路径 | **E3 全新写 + 162 用例归档**(`benchmark/` → `docs/archive/benchmark-pre-v0/`) |
| Rubric | **R4 简化** — 4 维度各 0-10 + JSON + 每维 1 句 evidence |
| 维度 | `factuality + tool_correctness + coverage + structure`(v1 加 citation + risk_disclosure) |
| 阈值 | **T3** — 整体通过率 ≥ 90% + 任何维度 regression ≤ 5pp |
| Judge 验证 | **e-alt** — Cross-judge ≥ 0.70 + Sanity check 100%,手动触发,无日常人工 |

**Golden set 形态**(每条 JSON):
```json
{
  "case_id": "v0-chat-001",
  "category": "single_tool_call",
  "user_input": "茅台股价多少?",
  "expected_behavior": {
    "tool_calls": [{"name": "get_stock_quote", "args": {"ts_code": "600519.SH"}}],
    "response_must_contain": ["600519", "数字+元/股"]
  },
  "metadata": {
    "added_by": "init",
    "added_at": "2026-04-29",
    "tags": ["chat", "market_data"]
  }
}
```

**Judge prompt 结构**(伪代码):
```
你是金融研究助手的输出评审员。给定:
- 用户输入: {user_input}
- 期望行为: {expected_behavior}
- 实际 trace: {trace_summary}
- 实际响应: {final_response}

按以下 4 维度各打 0-10 分,输出 JSON:
{
  "factuality": {"score": 0-10, "evidence": "1 句话"},
  "tool_correctness": {"score": 0-10, "evidence": "1 句话"},
  "coverage": {"score": 0-10, "evidence": "1 句话"},
  "structure": {"score": 0-10, "evidence": "1 句话"}
}
```

**Sanity check 用例(e-alt)**:
- 5 条明显对(query "茅台股价" → SUT 输出 plan_with_quote)
- 5 条明显错(query "茅台股价" → SUT 输出 "你好我是助手")
- judge 必须给"明显对"≥ 8、"明显错"≤ 3 — 否则 judge 不可信

### ④ 量化评估方案

- **Golden set 大小 v0**: 50-70 条(全新写)
  - ~30 单工具调用(quote / financial / risk 各 ~10)
  - ~20-30 chat 多轮场景
  - ~10 边界 case(模糊输入、需要追问、错误输入)
- **Eval cost / 次**: 实际 ¥1-2(deepseek-v4-flash);hard limit ¥20
- **Eval runtime**: 串行 ≤ 15min;并行可压到 ~5min
- **Pass 阈值**: 整体通过率 ≥ 90% AND 4 维度均分 regression ≤ 5pp
- **Judge 自验证**(e-alt 触发频率):judge model 升级 / rubric 调整时手动触发,平时不跑
  - **Cross-judge Spearman ≥ 0.70**
  - **Sanity check pass rate = 100%**
- **Hard cost limit**: ¥20 / 次;¥150 / 月

---

## 9. 决策八:Trace + Eval 联动接口

### ① 问题陈述
Eval runner 跑完一条用例后,要拿到 SUT 这次执行的中间结果(planner 输出的 plan、调了什么工具、token 消耗、latency)然后让 judge 打分。这些数据在 trace 里。**Eval 怎么读 trace?读到什么 schema?eval 结果写到哪里?**

### ② 业界 alternatives
- TI-1. 直读 SQLite spans 表 — 紧耦合
- **TI-2. TraceService 提供 query API**(选)
- TI-3. Trace export 为 JSON 文件 — 慢

### ③ 选择:**TI-2 + 独立 eval_results 表 + request_id 关联**

**契约 1:Eval 读 trace**
```python
class TraceService:
    def get_trace(self, request_id: str) -> TraceTree:
        """返回一个 request 的整棵 span tree"""

    def query_spans(self, filters: dict) -> list[Span]:
        """灵活查询 spans"""

class TraceTree:  # Pydantic
    request_id: str
    root_span: Span
    total_cost_cny: float
    total_latency_ms: int
    cache_hit_rate: float

class Span:
    span_id: str
    parent_id: str | None
    name: str  # "ChatPlanner.plan" / "LLMService.call" / "tool:get_stock_quote"
    inputs: dict
    outputs: dict
    metadata: dict  # model_name, tier, tokens, cache_hit, cost
    started_at: datetime
    ended_at: datetime
    error: str | None
```

**契约 2:Eval 写结果 — 独立表**

```python
class EvalResult:  # Pydantic
    eval_id: str
    request_id: str  # FK to trace
    case_id: str  # golden set 用例 id
    factuality_score: int  # 0-10
    factuality_evidence: str
    tool_correctness_score: int
    tool_correctness_evidence: str
    coverage_score: int
    coverage_evidence: str
    structure_score: int
    structure_evidence: str
    judge_model: str
    judge_cost_cny: float
    judge_latency_ms: int
    timestamp: datetime
```

**通过 `request_id` 关联**:debug 时一条 SQL `JOIN spans ON request_id` 就能看 "这个用例分数低,trace 里 planner 当时输出了什么"。

### ④ 量化评估方案
- **接口稳定性**: TraceService API v0~v3 内不破坏性变更
- **JOIN 查询性能**: trace + eval_results 联合查 "过去一周通过率最低 5 条用例" + 它们 trace 详情,目标 ≤ 200ms(SQLite 单进程)
- **存储增长**: 每次 nightly 70 用例 ≈ 1MB,1 个月 ~30MB,可接受
- **Replay 兼容性(预埋)**: 给定 trace request_id,eval runner 可重跑同 input 拿新 trace,跟旧 trace 比维度分变化(v1 用)

---

## 10. 决策九:Lint / Format / Type 选型

### ① 问题陈述
没有 lint/format/type check = portfolio 看 PR 一眼 reject;LLM 项目里 Pydantic schema 错位是大量 bug 源,type check 必须有。

### ② 业界 alternatives

**Lint + Format**:
- L-a. **ruff**(选)— Rust 写,2024+ 主流,替代 pylint+flake8+isort+black
- L-b. pylint + flake8 + isort + black 经典组合
- L-c. yapf

**Type check**:
- **T-a. mypy**(选,现阶段)— 主流,Pydantic / LangChain 兼容性最好
- T-b. pyright
- T-c. ty(Astral 出品,等 GA)
- T-d. basedpyright

### ③ 选择:**ruff(lint+format)+ mypy(type)+ 渐进 strictness**

**配置**:
```toml
# pyproject.toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "C4", "SIM"]

[tool.mypy]
python_version = "3.11"
strict_optional = true
disallow_untyped_defs = false  # 渐进:允许部分旧代码无 type
warn_unused_ignores = true
files = ["backend/app", "backend/tests"]
```

**Strictness 渐进**:
- 必须 typed:接口 / Pydantic schema / agent base / tool registry / 横切服务
- 可不 typed:测试代码 / 一次性脚本
- 整体目标:type coverage ≥ 70%

**三道关**:
1. 编辑器内置:LSP 实时红线
2. Pre-commit hook:`ruff format --check + ruff check`
3. PR CI:`ruff format --check + ruff check + mypy`

### ④ 量化评估方案
- **Lint runtime**: ruff 全仓 ≤ 1s 冷启 / ≤ 100ms 增量
- **Format check**: ruff format check ≤ 0.5s
- **mypy 全仓**: ≤ 30s 首次 / ≤ 5s 增量(带 cache)
- **Type 覆盖**(可执行版本): 在 CI 加一个 `mypy --strict backend/app/{services,agents,tools,orchestration}` step,这些目录强制 100% typed;其余目录 mypy 默认非 strict 跑过即可。Type coverage 整体 70% 是引导值,不强制量化(避免引入 mypyc/mypy-html-report 重工具)
- **PR blocker**: ruff format check + ruff check + mypy(整体 + strict 子集)任一 fail 即 block

---

## 11. 决策十:测试目录组织

### ① 问题陈述
现状测试散落:`integration/` `e2e/` 无 `unit/`;`backend/test_mock_*.py` 散在根目录;`mcp_server/tests/` 分散。重构后必须有一致入口,且 conftest.py 作用域跟 layer 对齐。

### ② 业界 alternatives
- **O-1. 平铺按 layer**(选)— 跟 P2+P5 钻石形匹配
- O-2. 镜像按业务模块
- O-3. 混合

### ③ 选择:**O-1 平铺按 layer**

```
backend/
├── app/
└── tests/
    ├── conftest.py                 # 全局 fixture (LLM_MODE 切换、mock client)
    ├── fixtures/
    │   ├── llm_mocks/
    │   │   ├── agent_decisions.yaml    # MC1 静态 dict
    │   │   └── recorded/*.json         # MC4 复杂 case fixture
    │   └── cassettes/              # pytest-recording (进 git)
    │       └── test_*.yaml
    ├── unit/                       # L0
    │   ├── conftest.py             # force LLM_MODE=none
    │   ├── test_pydantic_schemas.py
    │   ├── test_tier_router.py
    │   └── test_span_builder.py
    ├── integration/                # L1
    │   ├── conftest.py             # force LLM_MODE=mock
    │   ├── test_chat_planner_decisions.py
    │   └── test_responder_streaming.py
    ├── e2e/                        # L2
    │   ├── conftest.py             # force LLM_MODE=cassette
    │   └── test_e2e_chat_quote.py
    └── eval/                       # L3
        ├── golden/
        │   └── v0_chat_golden.jsonl
        ├── runner.py
        ├── judge.py
        ├── sanity_check/
        │   └── obvious_cases.jsonl
        └── results/                # gitignored 大文件
```

**现有文件去向**(配合 v0 spec "ground-up backend" 决议):

| 现有 | 处置 |
|---|---|
| `backend/test_mock_*.py`(3 文件) | 删除(测的是旧 mock_tushare 内部行为;mock 客户端测试在 `tests/integration/test_mock_data_layer.py` 重写) |
| `backend/app/mcp_server/tests/test_mcp_server.py` | 删除 |
| `backend/tests/integration/test_mcp_*.py`(2 文件) | 删除 |
| `backend/tests/e2e/test_e2e_chat.py` | 删除(调旧 `MCPChatService`) |
| `benchmark/`(整目录) | **迁到** `docs/archive/benchmark-pre-v0/`,README 加 deprecated 标记 + 指向 `tests/eval/` |

### ④ 量化评估方案
- 测试 layer 总计 4 个目录
- conftest.py 数量:1 全局 + 4 layer = 5 个
- pytest 自动发现率:100%
- 单测试文件 LOC ≤ 200(超出应拆)
- benchmark archive 大小 ≤ 5MB

---

## 12. 决策十一:本地 DX / Task runner

> **Note(I-1 修订, 2026-04-30)**: `backend/` 不是 Python package(无 `__init__.py`),uvicorn / mypy / pytest 都把 `backend/` 当作 source root,模块名实际是 `app.*`(不是 `backend.app.*`)。下面所有 `backend.app.*` 引用应解读为 `app.*` + `--app-dir backend`(为 uvicorn)或 `files = ["backend/app"]`(为 mypy)。最终采用的是后者形态:不引入 `backend/__init__.py`(避免重命名 100+ 文件),保持 `backend/` 作为非-package source root,并在所有工具的配置里显式声明 source root。

### ① 问题陈述
开发常用命令(启服务 / 跑测试 / 看 trace / 跑 eval / lint)散在 README 和各种脚本里。需要 one-stop task runner。

### ② 业界 alternatives
- M-a. Make / Makefile
- M-b. just (Rust)
- M-c. nox / tox(单 Python 环境过度)
- **M-d. poethepoet**(选)— pyproject.toml 集成

### ③ 选择:**poethepoet**

理由:配置集中(`pyproject.toml` 单一来源)+ 跟 uv/ruff 同源 + 0 额外安装(在 dev deps 里)。

**核心 8 个任务**:

```toml
# pyproject.toml
[tool.poe.tasks]
dev          = "uvicorn backend.app.app_main:app --reload --port 8000"
trace-view   = "uvicorn backend.app.services.trace_viewer:app --port 8001"
test         = "pytest backend/tests/unit backend/tests/integration backend/tests/e2e -m 'not slow and not live_only'"
test-all     = "pytest backend/tests"
eval         = "python -m backend.tests.eval.runner --golden v0_chat_golden.jsonl"
eval-validate = "python -m backend.tests.eval.runner --mode cross-judge"
lint         = ["ruff format --check .", "ruff check .", "mypy backend"]
format       = "ruff format ."
ci           = ["lint", "test"]  # 模拟 PR job 本地跑一遍
```

### ④ 量化评估方案
- 命令总数:8 核心(扩展 ≤ 12)
- 新人上手:`poe --help` 一屏看完
- 单命令执行 P50:dev 启动 ≤ 5s / test ≤ 90s / lint ≤ 10s / format ≤ 2s
- README 测试章节:**只列 `poe X` 命令**(命令本身就是文档)

---

## 13. 决策十二:闭环反馈机制(Working Agreement)

### ① 问题陈述
开发链路写了 spec/plan、实现完跑测试 — **测试 fail / eval regression 后下一步是什么**?反馈数据怎么真的回流到 spec/plan,而不是"跑过就完事"?个人项目尤其容易松散。

### ② 业界 alternatives
- **L-1. 极简流程**(选)— GitHub Issues + PR + spec retrospective
- L-2. 带看板流程(GitHub Projects)— 1 人 over-kill
- L-3. 完整 Agile — 0 意义

### ③ 选择:**L-1 + 4 条具体规则**

**规则 1(反馈触发)**:
- PR job fail → block PR(无需开 issue)
- Nightly job fail → 自动 issue,标 `nightly-failure`
- Cassette drift → 自动 issue,标 `cassette-drift`
- Eval regression > 5pp → 自动 issue,标 `eval-regression`

**规则 2(反馈 24h SLA — 软约束)**:
- Nightly issue 出现后 24h 内响应(确认 / 修复 / 标延期理由)
- Eval regression > 5pp:必须修到不退步才 release v0/v1

**规则 3(修复回流分类)**:
- bug 是实现问题 → 直接修代码 + 加 regression test
- bug 是 plan 漏了 → 改 plan,然后修代码
- bug 是 spec 设计错 → 改 spec(走完整 spec 修订),然后改 plan,然后改代码
- 三种情况都要在 commit message 写 `原因 layer:[impl|plan|spec]`(pre-commit hook regex 校验)

**规则 4(spec 完成必须 retrospective)**:

每个 spec 实现到合并完成时,在 spec 文档末尾追加:

```markdown
## Retrospective

**实现完成日**: YYYY-MM-DD

**对的设计**(1-3 条):
- ...

**错的设计 / plan 漏了什么**(1-3 条):
- ...

**下个 spec 要避免**(1-3 条):
- ...

**沉淀到 memory**:
- [memory file](path) — one-line hook
```

**没写 retrospective → spec 不算 done,不能 invoke writing-plans 进入下一个**。

### ④ 量化评估方案
- **Spec 完成周期**: 目标 ≤ 14 天 / spec(超过说明 plan 拆得太大)
- **Retrospective 覆盖率**: **100%**
- **Nightly issue 24h 响应率**: 目标 ≥ 80%
- **修复 commit "原因 layer" 标注覆盖率**: 100%(pre-commit hook regex 校验)
- **Memory 沉淀频率**: 每个 spec 完成后,至少 1 条 retrospective lesson 进 memory

### 闭环可视化

```
        ┌─────────────────────────────────────────┐
        │                                         │
        v                                         │
┌──────────┐  ┌──────┐  ┌────┐  ┌─────────────┐   │
│ Spec     │→ │ Plan │→ │实现│→ │PR + nightly │   │
│(brainstm)│  │      │  │+测试│  │CI/eval/trace│   │
└──────────┘  └──────┘  └────┘  └─────────────┘   │
   ^             ^         ^          │           │
   │             │         │          v           │
   │             │         │     ┌─────────┐      │
   │             │         │     │反馈分类 │      │
   │             │         │     └─────────┘      │
   │             │         │          │           │
   │             │         │     ┌────┴────┐      │
   │             │         └─────┤impl bug │      │
   │             └───────────────┤plan 漏  │      │
   └─────────────────────────────┤spec 错  │      │
                                 └─────────┘      │
                                                  │
       ┌──────────────────────────────────────────┘
       │
       v
  Memory 沉淀(/reinforce-skill)
       │
       v
  下一个 spec 自动避免重蹈
```

---

## 14. 验收标准(本 spec 落地完成的判断标准)

| 类别 | 指标 | 阈值 |
|---|---|---|
| **依赖管理** | `uv sync` 跨平台 reproducible | 100% |
| **Lint** | `poe lint` 零错误 | 100% |
| **测试 layer** | unit/integration/e2e/eval 4 个目录都存在,各 ≥ 1 个测试 | ✓ |
| **PR CI** | PR 提交后 ≤ 5min 出绿 / 红勾 | P95 ≤ 5min |
| **Nightly CI** | 第一次 nightly 跑通,自动开 / 关 issue 链路验证 | ✓ |
| **Eval scaffold** | golden set ≥ 50 条 + judge 跑通 + cross-judge sanity | ✓ |
| **Trace 接口** | TraceService 接口定义完成,有 stub 实现可被 eval runner mock | ✓ |
| **Mock 客户端** | MC5 三层 mock 可用,L1 测试可跑 | ✓ |
| **Cassette** | 至少 1 个 cassette 录制重放成功 | ✓ |
| **DX** | `poe --help` 列出 8 个命令,各可跑 | ✓ |
| **闭环反馈** | 4 条规则在 `WORKING_AGREEMENT.md` 落地;commit hook 校验 commit msg 跑通 | ✓ |
| **Cost 控制** | nightly 单次跑实际 cost ≤ ¥5;hard limit ¥20 不被触发 | ✓ |

---

## 15. 风险与未解问题

| 风险 / 未解 | 应对 |
|---|---|
| pytest-recording 拦截 OpenAI Python SDK(走 httpx)是否 100% 兼容 | 实施时跑 spike test(录一次百炼调用 → 重放 → 验证 input/output 一致)验证;如失败回退 SDK-level recorder |
| Cassette drift 频率高(模型版本频繁静默升级) | 提高 nightly validation 频率到 2x/day;或加 cassette 元数据带 model version + 调用时间 |
| Sanity check 用例可能太弱,judge 给"明显错"打中分 | 实施时人工抽检前 5 次 nightly judge 输出;如果 sanity 不严,加更极端 case(空字符串、全错语言) |
| 一人项目无 reviewer,PR self-merge 流程 | 接受;依赖 commit hook + nightly job 机器把关;每月手动 spec retrospective |
| 百炼模型下线(deepseek-v4-flash 被替代) | tier_router config 一行改;同时检查 cassette 是否需重录 |

**v1 衔接点**:
- **多 model 路由**(qwen-max / Anthropic 接入):改 tier_router config + provider adapter
- **Memory 子系统真实实现**:本 spec 已定 trace + eval 接口,memory 接入直接走 TraceService API
- **Cassette → Langfuse adapter**:cassette format 跟 OTel span 同构,可加 exporter

---

## 附录 A:`pyproject.toml` 完整草稿

```toml
[project]
name = "financial-research-assistant"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "pydantic>=2.7",
    "openai>=1.40",
    "langgraph>=0.2",
    "tushare>=1.4",
    "httpx>=0.27",
    # ... (从 requirements.txt 迁移精简)
]

[project.optional-dependencies]
dev = [
    "ruff>=0.6",
    "mypy>=1.11",
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-recording>=0.13",
    "pytest-cov>=5.0",
    "poethepoet>=0.27",
    "pip-audit>=2.7",
]

[tool.uv]
managed = true

[tool.ruff]
line-length = 100
target-version = "py311"
extend-exclude = ["docs/archive"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "C4", "SIM"]

[tool.mypy]
python_version = "3.11"
strict_optional = true
disallow_untyped_defs = false
warn_unused_ignores = true
files = ["backend/app", "backend/tests"]

[tool.pytest.ini_options]
minversion = "8.0"
addopts = "-ra -q --strict-markers"
testpaths = ["backend/tests"]
asyncio_mode = "auto"
markers = [
    "unit: marks tests as unit tests",
    "integration: marks tests as integration tests",
    "e2e: marks tests as end-to-end tests",
    "live_only: tests that require real LLM API",
    "slow: tests that take >5s",
]

[tool.poe.tasks]
dev          = "uvicorn backend.app.app_main:app --reload --port 8000"
trace-view   = "uvicorn backend.app.services.trace_viewer:app --port 8001"
test         = "pytest backend/tests/unit backend/tests/integration backend/tests/e2e -m 'not slow and not live_only'"
test-all     = "pytest backend/tests"
eval         = "python -m backend.tests.eval.runner --golden v0_chat_golden.jsonl"
eval-validate = "python -m backend.tests.eval.runner --mode cross-judge"
lint         = ["ruff format --check .", "ruff check .", "mypy backend"]
format       = "ruff format ."
ci           = ["lint", "test"]
```

---

## 附录 B:现有文件去向汇总(deletion list)

| 文件 / 目录 | 大小 | 处置 |
|---|---|---|
| `backend/test_mock_tushare.py` | - | 删除 |
| `backend/test_mock_integration.py` | - | 删除 |
| `backend/test_mock_extended.py` | - | 删除 |
| `backend/app/mcp_server/tests/test_mcp_server.py` | - | 删除 |
| `backend/tests/integration/test_mcp_meta_tools.py` | - | 删除 |
| `backend/tests/integration/test_mcp_resource_tool_arch.py` | - | 删除 |
| `backend/tests/e2e/test_e2e_chat.py` | - | 删除 |
| `backend/requirements.txt` | - | 删除(替代:`pyproject.toml` + `uv.lock`) |
| `pytest.ini` | - | 删除(替代:`pyproject.toml [tool.pytest.ini_options]`) |
| `benchmark/` 整目录 | ~600KB | 迁到 `docs/archive/benchmark-pre-v0/` |

新增:
- `backend/pyproject.toml`(从无到有)
- `backend/uv.lock`(由 `uv lock` 生成,进 git)
- `.github/workflows/pr.yml`
- `.github/workflows/nightly.yml`
- `.pre-commit-config.yaml`
- `WORKING_AGREEMENT.md`
- `backend/tests/{unit,integration,e2e,eval}/`(完整 layer 目录树)
- `backend/tests/fixtures/{llm_mocks,cassettes}/`

---

## 附录 C:GitHub Actions Workflow 完整草稿

### `.github/workflows/pr.yml`

```yaml
name: PR

on:
  pull_request:
  push:
    branches: [main]

jobs:
  lint-and-fast-tests:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - name: Install deps
        run: uv sync --all-extras
      - name: Format check
        run: uv run ruff format --check .
      - name: Lint
        run: uv run ruff check .
      - name: Type check
        run: uv run mypy backend
      - name: Run L0+L1+L2 子集 tests
        env:
          LLM_MODE: cassette
        run: uv run pytest backend/tests -m "not slow and not live_only"
```

### `.github/workflows/nightly.yml`

```yaml
name: Nightly

on:
  schedule:
    - cron: "0 19 * * *"  # UTC 19:00 = 北京 03:00
  workflow_dispatch:

jobs:
  full-tests-and-eval:
    runs-on: ubuntu-latest
    timeout-minutes: 35
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras

      # L2 全集
      - name: Run L2 full
        env:
          LLM_MODE: cassette
        run: uv run pytest backend/tests/e2e

      # L3 eval
      - name: Run L3 eval
        env:
          DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
          LLM_MODE: live
          EVAL_COST_LIMIT_CNY: "20"
        run: uv run poe eval

      # Cassette validation
      - name: Cassette drift check
        env:
          DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
        run: uv run python -m backend.tests.eval.cassette_validation

      # Dependency audit
      - name: Dependency audit
        run: uv run pip-audit

      # 任一 step fail → 自动开 issue
      - name: Open issue on failure
        if: failure()
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: `[nightly] ${new Date().toISOString().split('T')[0]} failure`,
              body: `Nightly job failed. See [run](${context.serverUrl}/${context.repo.owner}/${context.repo.repo}/actions/runs/${context.runId}).`,
              labels: ['nightly-failure']
            })
```

---

## 附录 D:`.pre-commit-config.yaml` 草稿

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff-format
      - id: ruff
        args: [--fix]
  - repo: local
    hooks:
      - id: commit-msg-layer
        name: Commit message must mark fix layer (impl/plan/spec)
        entry: scripts/check_commit_msg.sh
        language: script
        stages: [commit-msg]
```

---

## 附录 E:`WORKING_AGREEMENT.md` 模板

```markdown
# Working Agreement (Solo Project)

## 1. 反馈触发
- PR fail → block,无需开 issue
- Nightly fail → 自动 GitHub issue 标 `nightly-failure`
- Cassette drift → 自动 issue 标 `cassette-drift`
- Eval regression > 5pp → 自动 issue 标 `eval-regression`

## 2. 反馈 SLA
- Nightly issue 24h 内响应
- Eval regression > 5pp 必修才 release

## 3. 修复回流分类(commit message 必标)
每个修复 commit message 必须含一行:
```
原因 layer: [impl|plan|spec]
```
- impl:实现 bug,直接修
- plan:plan 漏了,改 plan 再修代码
- spec:spec 设计错,走完整 spec 修订流程

## 4. Spec retrospective
每个 spec 完成时(plan 全实现合并 main)在 spec 末尾追加:
- 对的设计 1-3 条
- 错的设计 / plan 漏的 1-3 条
- 下个 spec 避免 1-3 条
- 沉淀到 memory 的链接

没写 retrospective → spec 不算 done。
```

---

## Retrospective

(待 dev-test-loop spec 实现完成后填写)
