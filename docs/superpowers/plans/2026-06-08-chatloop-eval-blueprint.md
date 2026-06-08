# Chat-Loop Agent 评估体系 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`. 设计稿:`docs/superpowers/specs/2026-06-08-chatloop-eval-blueprint-design.md`。

**Goal:** 给 `backend/app/chatloop/` 的裸 while agent 搭一套自有评估体系,产出"行为 × 难度"成绩单(真 LLM live),并守住可信(裁判校准 / pass^k)。

**Architecture:** 新包 `backend/eval/chatloop/`,复用 `eval/tool_selection` 的确定性 scorer(行为①②③)+ `eval/memory/faithful_answer_metric`(行为④ grounding);自写正确生命周期的 SUT-runner(修掉现有 live 路径的 MCP cancel-scope bug)+ pass^k wrapper + 报告。

**Tech Stack:** Python 3.12,WSL `fria-venv`,真 PG + MCP subprocess(chat_tools)+ DashScope(`deepseek-v4-flash`),pytest。

**运行环境(所有 live 命令的前缀):**
```
wsl bash -lc 'source ~/fria-venv/bin/activate && cd /mnt/d/mys/Financial-Research-Investment-Assistant/backend && set -a && source ../.env && set +a && PYTHONPATH=. <CMD>'
```

**已验证的事实(实施前已 smoke 确认):**
- LLM 可达,单次 1.3s(`deepseek-v4-flash` via DashScope compatible-mode)。
- 重依赖(PG + MCP subprocess + heavy singletons + 真 ChatLoopAgent)全部能起。
- **现有 `eval/tool_selection` 的 `--live` 路径有 latent bug**:`_live_deps.build_eval_singletons()` 手动 `__aenter__` MCP 上下文并跨任务泄漏 → anyio `RuntimeError: Attempted to exit cancel scope in a different task`,连第一次 LLM 调用都被 cancel。修法 = `async with MCP` 包住整个 case 循环(同一任务)。这是本评估体系的第一个真实发现。
- DB:`app.core.database.SessionLocal`;异步 url:`app.app_main._sqlalchemy_async_pg_url`;singletons:`app.chatloop.worker_wiring.build_heavy_singletons`;agent:`app.chatloop.eval_agent.ChatLoopAgent`;tool_selection scorer:`eval.tool_selection._core`;grounding:`eval.memory.faithful_answer_metric`。
- **免责声明确认缺失**:`CHAT_SYSTEM_PROMPT` 不含「投资建议/仅供参考/不构成」(只含「买卖决策」)。

---

## 文件结构

- `backend/app/chatloop/system_prompt.py` — 改:补全局政策(免责每次带 + 不给方向性指令)。
- `backend/eval/chatloop/__init__.py` — 新建空包。
- `backend/eval/chatloop/scenario.py` — 场景规格 schema + loader(扩 tool_selection GoldenCase:加 persona/difficulty/policy/expected_answer 字段)。
- `backend/eval/chatloop/sut_runner.py` — 正确生命周期 SUT-runner(`async with` MCP);产出完整 SUTOutput(tool_calls + final_text + retrieved + side_effects)。
- `backend/eval/chatloop/scorers.py` — 行为 scorer 派发:①②③ 委托 tool_selection;④ grounding 委托 faithful_answer;免责存在性确定性检查。
- `backend/eval/chatloop/passk.py` — pass^k wrapper(同一 case 行为 scorer live 跑 k 次)。
- `backend/eval/chatloop/report.py` — 行为 × 难度 成绩单 markdown。
- `backend/eval/chatloop/run_eval.py` — CLI(`--golden` / `--ci` / `--offline` / `--k`)。
- `backend/eval/chatloop/golden/scenarios.jsonl` — 金标准场景集(≥18 条,跨难度+行为)。
- `backend/eval/chatloop/calibration/grounding_label_template.jsonl` — 待标校准集模板 + 标注协议头。
- `backend/tests/unit/eval/chatloop/test_*.py` — scorer/schema/passk 纯函数 L0 测试。

---

## Task 0:前置债 — 补全局政策进 chat 系统提示词

**Files:** Modify `backend/app/chatloop/system_prompt.py`

- [ ] **Step 1:** 读 `CHAT_SYSTEM_PROMPT`,在"诚实/不编造"附近加两条全局政策(保持逐字节稳定铁律——不含日期/会话动态):
  - `- 每条回复结尾附一句免责:"以上为信息与分析,仅供参考,不构成投资建议。"`
  - `- 不给方向性指令(买入/卖出/加仓/清仓/目标价/应该买),不给确定性承诺(一定涨/稳赚)。`
- [ ] **Step 2:** 验证:`PYTHONPATH=. python -c "from app.chatloop.system_prompt import CHAT_SYSTEM_PROMPT as p; assert '不构成投资建议' in p; print('OK', len(p))"`(env 前缀)。Expected: `OK <len>`。
- [ ] **Step 3:** Commit `feat(chatloop): 系统提示词补全局政策——免责每次带 + 不给方向性指令`。

---

## Task 1:新包 + 场景 schema(扩 tool_selection golden)

**Files:** Create `backend/eval/chatloop/__init__.py`, `scenario.py`, `tests/unit/eval/chatloop/test_scenario.py`

- [ ] **Step 1(test first):** 写 `test_scenario.py`:`load_scenarios` 读一条含 `{case_id, user_input, expected, bucket, difficulty, persona?, policy_refs?, expected_answer?}` 的 jsonl → `Scenario`;难度越界/缺 case_id fail-loud;`difficulty ∈ {直球,自然难,对抗}`。
- [ ] **Step 2:** 运行验证 FAIL(模块不存在)。
- [ ] **Step 3:** 实现 `scenario.py`:`@dataclass(frozen=True) Scenario` 复用 tool_selection 字段语义 + 加 `difficulty: str`、`persona: str|None`、`policy_refs: list[str]`、`expected_answer: dict|None`(grounding 用:`{must_ground_on: [...], expect_abstain: bool}`);`load_scenarios(path)` 仿 `tool_selection._core.load_golden` fail-loud。复用 `tool_selection._core.GoldenCase` 投影(`to_ts_case()`)给 ①②③ scorer。
- [ ] **Step 4:** 运行测试 PASS:`pytest tests/unit/eval/chatloop/test_scenario.py -v`(env 前缀)。
- [ ] **Step 5:** Commit `feat(eval): chatloop 评估 — 场景规格 schema`。

---

## Task 2:SUT-runner(修 MCP 生命周期 bug,产出完整 SUTOutput)

**Files:** Create `backend/eval/chatloop/sut_runner.py`

- [ ] **Step 1:** 实现 `run_scenarios_live(scenarios, *, dispatch_mode, k=1) -> list[SutResult]`:
  - **关键**:`async with MCPClient.from_subprocess(profile="chat_tools") as mcp:` 包住 `build_heavy_singletons(...)` + 整个 case 循环(同一任务,修掉 cancel-scope bug)。engine 用 `_sqlalchemy_async_pg_url()`。
  - `dispatch_mode="noop"`:复用 `tool_selection._live.FakeNoopHub`(首轮工具选择,①②③ 用)。
  - `dispatch_mode="real"`:用真 `build_real_hub`(grounding ④ 用,agent 真检索真答);`max_steps` 放到 6。
  - `SutResult = {case_id, tool_calls: [{tool_name,args}], final_text: str, retrieved: list, request_id}`(从 `ChatLoopAgent.run` 的 `out` 投影;final_text/retrieved 从 SUTOutput 取,字段名以 `eval_agent.py` 实际为准——实施时读该文件确认)。
- [ ] **Step 2(smoke,非单测):** 用 `golden/scenarios.jsonl` 的 2 条 noop 跑:确认无 cancel-scope error、返回 tool_calls。命令见下。
- [ ] **Step 3:** Commit `feat(eval): chatloop SUT-runner — 修 MCP 跨任务 cancel-scope bug + 完整 SUTOutput`。

Smoke:`PYTHONPATH=. python -m eval.chatloop.run_eval --golden eval/chatloop/golden/scenarios.jsonl --offline --behaviors routing,tool,abstain`(env 前缀)。

---

## Task 3:scorers(①②③ 复用 + 免责确定性检查)

**Files:** Create `backend/eval/chatloop/scorers.py`, `tests/unit/eval/chatloop/test_scorers.py`

- [ ] **Step 1(test):** `test_scorers.py`:`score_routing/score_tool/score_abstain` 委托 `tool_selection._core.score_case`(用 `Scenario.to_ts_case()`);`score_disclaimer(final_text)` = 确定性子串检查("不构成投资建议" in text)→ pass/fail;`score_advice(final_text)` = 方向性词命中("建议买入/目标价/应该买")→ violation。给 fixture 文本断言。
- [ ] **Step 2:** 运行 FAIL。
- [ ] **Step 3:** 实现 `scorers.py`。①②③ 纯委托;免责/方向性 = 纯函数关键词。
- [ ] **Step 4:** 运行 PASS。
- [ ] **Step 5:** Commit `feat(eval): chatloop scorers — ①②③ 复用 + 免责/方向性确定性检查`。

---

## Task 4:grounding scorer(④,复用 faithful_answer)

**Files:** Create `backend/eval/chatloop/grounding_scorer.py`, `tests/unit/eval/chatloop/test_grounding.py`

- [ ] **Step 1:** 读 `eval/memory/faithful_answer_metric.py` 确认 `JudgeProtocol`/`decompose_to_claims`/`is_grounded` 接口。
- [ ] **Step 2(test):** mock judge:给 `(answer, evidence)` → 拆 claim → grounding 比;`expect_abstain=True` 且答案含弃答标记 → PASS。
- [ ] **Step 3:** 实现 `grounding_scorer.py`:复用 faithful_answer 的拆 claim + provenance 子串;judge 用 `build_llm_service_from_env`(裁判模型独立:用与被评不同 model,如 `qwen-max`,实施时确认可用)。
- [ ] **Step 4:** 运行 PASS。
- [ ] **Step 5:** Commit `feat(eval): chatloop grounding scorer — 复用 RAGAS 式 faithful_answer`。

---

## Task 5:pass^k wrapper(⑥)

**Files:** Create `backend/eval/chatloop/passk.py`, `tests/unit/eval/chatloop/test_passk.py`

- [ ] **Step 1(test):** `pass_power_k(results_per_run: list[list[bool]]) -> dict` 纯函数:输入 k 次每 case 的 pass bool → 输出 `{case_id: {pass1, passk}}`,`passk = 全 k 次都 True`。给确定性 fixture(k=3,某 case [T,T,F] → passk=False,pass1=1/3)。
- [ ] **Step 2:** 运行 FAIL → 实现纯函数 → PASS。
- [ ] **Step 3:** SUT-runner 加 `k` 支持(同 case 跑 k 次,**隔离 request_id**)。
- [ ] **Step 4:** Commit `feat(eval): chatloop pass^k — 连胜率纯函数 + runner k 次`。

---

## Task 6:报告 + CLI

**Files:** Create `backend/eval/chatloop/report.py`, `run_eval.py`

- [ ] **Step 1:** `report.py`:`format_scorecard(results) -> str` 行为 × 难度 表(通过率,无聚合总分);分两段(确定性闸红绿 / 离线 pass^k + grounding + κ 占位)。
- [ ] **Step 2:** `run_eval.py` CLI:`--golden`/`--ci`(noop,确定性行为)/`--offline`(real,全行为+pass^k)/`--k`/`--behaviors`;仿 `tool_selection/eval_runner.py`。
- [ ] **Step 3:** Commit `feat(eval): chatloop 报告 + CLI`。

---

## Task 7:金标准场景集(≥18 条,跨难度+行为)

**Files:** Create `backend/eval/chatloop/golden/scenarios.jsonl`

- [ ] **Step 1:** 写 ≥18 条,覆盖:路由(个人→memory / 公开→kb·数据)、工具选择(首选+参数)、克制弃答(无关工具 / 假前提)、grounding(给证据该 ground / 无证据该弃答)。难度三档各 ≥4。台词用 `retail-investor-voice` 口语(散户腔,非书面语——书面语关键词门会静默跳过)。
- [ ] **Step 2:** 验证 schema:`python -m eval.chatloop.run_eval --golden ...`(dry,零 LLM)校验通过。
- [ ] **Step 3:** Commit `feat(eval): chatloop 金标准场景集 v1`。

---

## Task 8:裁判校准集模板 + 协议

**Files:** Create `backend/eval/chatloop/calibration/grounding_label_template.jsonl`, `README.md`

- [ ] **Step 1:** 生成 30-40 条待标行 `{case_id, 问题, 证据, 回答, 标:"", 理由:""}`(从 Task 7 场景 live 跑的真实输出 + 手搓对抗,PASS/FAIL ~50/50);`README.md` 写 §8.1.1 标注协议(二元 / 忠于证据 / 弃答=PASS / 一句理由)。
- [ ] **Step 2:** Commit `feat(eval): chatloop grounding 裁判校准集模板 + 标注协议`。
- [ ] **Step 3:** `calibrate.py`:读已标 jsonl + 跑裁判 → 算一致率/κ;κ<0.6 报警不上岗。(用户标完后跑。)

---

## Task 9:整跑 + 分析(交付物)

- [ ] **Step 1:** `--ci` 全跑(确定性闸,noop):路由/工具/弃答/免责 成绩单。
- [ ] **Step 2:** `--offline --k 5` 跑(real):grounding + pass^k。
- [ ] **Step 3:** 写分析:每个红灯指出"SUT 坏 / scorer 坏 / 系统真退步";对照 spec 的"诚实账"。
- [ ] **Step 4:** Commit 报告产物。

---

## 优先级(deadline:明天给结果)

**必达**:Task 0 → 1 → 2 → 3 → 7 → 6 → 9(--ci):**真·路由/工具/弃答/免责 成绩单**(确定性闸,reuse 为主,风险最低)。
**力争**:Task 4 + 5 + 9(--offline):grounding + pass^k。
**交用户**:Task 8 校准集模板(用户明天手标)。
