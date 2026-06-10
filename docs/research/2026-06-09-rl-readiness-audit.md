---
title: RL 就绪度审计 — verl + sglang 给金融数值 agent 做 RL,本仓现有资产缺口
date: 2026-06-09
type: audit
branch: feat/chatloop-eval-blueprint
source: 本审计 workflow(6 路代码审计合成)
related:
  - docs/research/2026-06-09-verl-multistep-tool-rl-recipe.md  # verl 契约与 recipe 对照源
snapshot_warning: >-
  dd_report eval 模块正被另一会话重构(numerical_metric.py = clean / 工作区干净,
  prediction_metric.py = deleted, golden/ground_truth_loader.py = deleted,
  metrics/base.py = modified 已删 ground_truth 字段)。凡标注"快照于2026-06-09,该模块在动"
  的结论,接 RL 试点 spec 前必须以重构落定后的版本复核。
evidence_rule: 每条结论带 file:line;读不到/不确定标【未核实】;绝不臆测。
---

# RL 就绪度审计:verl + sglang × 金融数值 agent

> 工作区快照核验(本审计起始):`git status --short` 确认 `backend/eval/dd_report/golden/ground_truth_loader.py` = **D(deleted)**、`backend/eval/dd_report/metrics/prediction_metric.py` = **D**、`backend/eval/dd_report/metrics/base.py` = **M(modified,已删 `ground_truth` 字段,现存 `tushare_adapter` / `evaluator_clients`,`CaseMeta.cut_off_date: date` @ base.py:32)**;`numerical_metric.py` 本体 **不在 status 中(工作区干净)**。全仓 `grep compute_score` 在源码侧 **零命中**(只命中 verl recipe 文档与 mypy 缓存二进制)。这些事实是下文判断的地基。

## 一句话总览

**本仓的"纯算法估值器层"(`valuation_helpers/` + `calculate_valuations`)是近乎理想的确定性 oracle,可直接进独立 verl 训练 venv 当 verifiable reward;但工具循环、cassette、题集真值、numerical_metric 这四块都需要 ~10–100 行/项的胶水,且最大命门是"确定性 oracle 边界很窄"——只有工具选择/记忆抽取/估值算式/数值取数四类有真值,所有"答案质量/grounding/citation"层是 LLM-judge,不能当 RL 奖励。** 整体就绪度:**没有任何一块能零胶水直接接,但估值数学层离得最近;六缺口中两块(numerical_metric 依赖、题集数值真值)还撞在正在重构的 dd_report 上,须等其 settle。**

## 就绪度对照表

| # | 缺口 | 现状 | 能否直接接 verl | 精确缺口 | 补法 | 工作量 |
|---|------|------|:---:|----------|------|:---:|
| 1 | numerical_metric 当 reward fn | 吃结构化 report dict,返回 `MetricResult` 对象,无模块级 `compute_score`;tushare 真值同步取数内核可复用 | **否** | 形状错配(verl 给 flat `solution_str`,它要 `report["financial_analysis"]["key_metrics"]` 嵌套 dict)+ 无 `compute_score` + 依赖 `base.py`/`MetricInputs` 正被重构字段在动 | 新写 `verl_oracle_reward.py`:文本→结构化抽取 + `MetricInputs` 装配 + cassette 回放 inner + 返回适配 | **中**(~50–100 行,且部分形态依赖未定 spec 决策) |
| 2 | chatloop 工具复用为 verl BaseTool | `Tool.run` 已 async、入参 dict、schema 已是 OpenAI function 格式、数据层 mock/cache/cassette 解耦且经 e2e 守护 | **部分**(偏能) | `Tool.run` 返回 dict ≠ `tuple[ToolResponse, float, dict]`;无 `instance_id`/`create`/`release` 生命周期;无 per-trajectory 注入钩子;ToolHub 层的"指导性错误"文案会丢 | 写薄 `BaseTool` adapter(补生命周期 + dict→ToolResponse + 经 `create_kwargs` 注入 oracle/cassette 名)+ `tool_to_verl_yaml` | **小**(~30 行/工具 + ~15 行注入 + ~10 行 yaml) |
| 3 | cassette 格式被 verl execute() 读 | tushare cassette = VCR YAML(原始 HTTP JSON);**已有 `TushareCache` = `(api_name, sha256(sorted params)) → pickled DataFrame`** 几乎即插即用 | **部分** | cassette 那侧只有 pytest 参数化文件名 + VCR 线性匹配,**没有"入参 hash → 单条快照"独立索引**;VCR 回放引擎绑 pytest+httpx 拦截不可脱;覆盖面窄(5 ts_code × ~8 endpoint) | 首选直接复用 `TushareCache`;次选写 ~30 行 YAML 索引器(范式见 `cassette_validation.py:48-70`) | **小**(复用 TushareCache 近零;自写索引器 ~30 行) |
| 4 | 金融题集→真值进 `reward_model.ground_truth` | 4 类异构 golden(dd_report / tool_selection / chatloop / memory),工具选择+抽取边是确定性 JSON,可零转换序列化 | **部分** | 金融数值真值**不落盘**(live tushare,且 loader 代码此刻被删);确定性可 oracle 样本仅 ~150–170 条(未达几百);"数值计算"类无 golden;答案质量层全 judge | 写"真值快照固化器"+ 从 HEAD 恢复 loader 蓝本 + 模板化扩量 + 新建数值计算 golden | **中**(快照器 + 扩量 + 恢复 loader) |
| 5 | compute_dcf / A5a cross-check 纯度与确定性 | 7 个估值 helper + `calculate_valuations` **全纯 CPU、同步、确定性、零随机/网络/DB**;实测浮点逐位可复现 | **是**(估值数学层) | "取数→ValuationInputs"映射耦合在 `Analyst._build_valuation_inputs_from_state` 私有方法(import 它会拉 LLM 栈);取数侧网络确定性未验;OutlierDiagnosis/Analyst/debate 调 LLM 须排除 | 把映射逻辑抽成 `valuation_helpers` 自由函数 + 取数 cassette 化;oracle 只吃 `ValuationInputs` 调 `calculate_valuations(router_override=None)` | **小**(抽函数 + cassette 注入) |
| 6 | verl 训练 venv vs 后端 import 链 | A 层(估值数学)零第三方;A+ 层(orchestrator)仅 +pydantic;包 `__init__` 空无副作用;均 smoke 实测通过 | **是**(A/A+ 层) | A/A+ **无重耦合**;B 层 `numerical_metric` 经 `base.py:14` eager 拖起 `openai`+`httpx`(算数值用不到);verl/sglang 必须独立 venv(torch/cuda 宇宙不兼容) | 训练 venv 装 ~5 个 oracle 源文件 + pydantic(+ B 层加 openai/httpx 或把 `EvaluatorClient` 改 `TYPE_CHECKING`-only);PYTHONPATH 指 backend/ | **小**(独立 venv + 复制 5 文件) |

---

## 逐缺口详情

### 缺口 1 — numerical_metric 当 verl reward fn（就绪度:否）

> **快照于 2026-06-09,该模块在动。** `numerical_metric.py` 本体工作区干净,但同目录依赖被另一会话重构:`base.py` 改(删 `GroundTruthLoader` import + `MetricInputs.ground_truth` 字段)、`prediction_metric.py` / `golden/ground_truth_loader.py` 删、`runner.py` / `backtest_runner.py` / `metric_scores.py` 已 modified。关键:`NumericalMetric` **不依赖被删的 `ground_truth` 字段**,所以重构不直接砸到它,但 `MetricInputs` 形状在变,胶水不能照抄旧字段。

- **签名是 dataclass + `.compute(inputs)`,不是模块级函数**:`@dataclass NumericalMetric(... tolerance=0.01)`,`def compute(self, inputs: MetricInputs) -> MetricResult`(`numerical_metric.py:63-69`)。
- **吃的是结构化 report dict 不是字符串**:从 `report["financial_analysis"]["key_metrics"]` 逐项取 `item["name"]`/`value`/`period`(`numerical_metric.py:79-95`);`report` 是 `InvestmentDueDiligenceReport.model_dump()`(`base.py:42`)。这是与 verl 契约最大形状错配——verl 给整条 response 解码后的 flat `solution_str`(recipe `:439-440`),这里要嵌套 dict。
- **tushare 真值同步取数,走 `TushareBacktestAdapter`,cassette 回放架构上可行但当前无现成 cassette**:`_lookup_real_value` 里 `method = getattr(adapter, spec["fetch"], None); rows = method(ts_code=ts_code)` 纯同步无 `await`(`numerical_metric.py:129-132`),契合 verl 逐样本同步调。adapter `inner` 是 Protocol(`tushare_backtest_adapter.py:16-23`),注入点干净,但仓里只有 test fake / live SDK / 空 stub 三种,**没有"录一遍 dump 再回放"的 cassette inner**(recipe `:727` 自列为待建)。
- **返回 `MetricResult` 对象不是 float/dict**:`MetricResult(value: float|None, details: dict)`(`base.py:18-25`);verl 要 float 或带 `score` 键 dict(recipe `:350`)。需 `{"score": result.value, **result.details}`。
- **容差/归一化半成品**:±1% 相对误差 `abs(claimed-real)/max(abs(real),1e-9) <= 0.01`(`numerical_metric.py:101`+`:66`);`parse_chinese_number` 处理 `亿/万/%`(`:41-47`);**但正则 `r"(-?\d+(?:\.\d+)?)"` 不去千分位逗号**(`:25`,`"1,500亿"` 只抓到 `1` 静默错算)、**无单位裸数字按"元"算**(docstring `:13-14` 自标已知坑)。RL 早期 policy 输出不规范会大量假"数值错",reward 噪声高。
- **无模块级 `compute_score`**:全仓 grep 源码侧零命中(本审计实测)。要新写 `verl_oracle_reward.py` 包一层。
- **覆盖面窄**:`_KNOWN_METRICS` 只 4 类,ROE/资产负债率 v0 硬走 `fetch_income`、`row_key` 占位(`:51-60`);非这 4 类一律 `skipped`(`:87-88`)。

**胶水量:~50–100 行**(前置文本→结构化抽取 + `MetricInputs` 装配 + cassette inner + 返回适配)。其中"前置抽取"是"逐指标抽取打分"还是"单一最终估值打分"是 **spec 决策点**,不是纯胶水——后者(范本 recipe `:458-468`)会绕过 metric 类的多指标遍历逻辑。**重构未落定**:`MetricInputs(...)` 构造调用须等重构 settle 后再对字段,现在写会撞 in-flight 改动。

### 缺口 2 — chatloop 工具复用为 verl BaseTool/rollout（就绪度:部分）

> 快照声明:chatloop / tools / tushare 路径**不在 dd_report 重构范围内**,证据稳定。路径事实:`hub.py` 不存在,实际是 `tool_hub.py`;工具执行入口有两层——L1 in-process `Tool` ABC(`base.py:21`)、L2 MCP `TOOL_DEF + handle()`(`financial_statements.py:25-97`,经 `_MCPToolProxy` 注册进 `ToolHub`,`registry.py:57`/`tool_hub.py:91-95`)。

- **① execute 入口(部分/偏能)**:L1 `async def run(self, args: BaseModel) -> dict`(`base.py:26-28`;`get_financials.py:42`),async + 入参 Pydantic 实例 + 返回纯 dict,阻抗低。缺口:返回 dict ≠ verl `tuple[ToolResponse, float, dict]`(recipe `:675`);无 `instance_id` 形参;ToolHub 层"指导性错误"文案(`tool_hub.py:407-427` 映射 `[执行失败]/[参数校验失败]`)不在 `Tool.run` 里,直接复用会丢。补:adapter ~20–30 行/工具,`return ToolResponse(text=json.dumps(out, ensure_ascii=False)), 0.0, {}`。**verl 版本敏感**(recipe `:679`):v0.5 `execute` 首返回值是 `str`,main 是 `ToolResponse`。
- **② create/release 状态(是,财务工具最简单)**:`GetFinancialsTool` 无状态(`__init__` 只持 `self._tushare`,`get_financials.py:39`),`create/release` 退化成空操作。但本仓有有状态 `InProcessTool.run_with_state(args, state: ChatLoopState)`(`inprocess.py:24,33`),`ToolHub` 用 `isinstance` 注入 turn 级 state(`tool_hub.py:296-298`)——这些是记忆/技能类(`worker_wiring.py:208-217`),**依赖整个 `ChatLoopState` 不能映射到 verl `instance_id` 轻状态,是硬墙**。缺口:`Tool` 无 `create_kwargs` 注入钩子(`__init__` 收进程级依赖不是 per-trajectory)。补:adapter 的 `create` 把 `create_kwargs`(cassette 名/容差/真值)存 `self._instances[instance_id]`(~15 行新写,本仓无等价物)。**建议 RL 试点只取无状态数值工具**(13 个 `ToolName`,`schemas.py:48-60`)。
- **③ schema→verl YAML(是)**:`Tool.schema_for_llm()` 产标准 OpenAI function 格式 `{type:function, function:{name,description,parameters: model_json_schema()}}`(`base.py:30-38`),与 verl `OpenAIFunctionToolSchema`(recipe `:307-310,:323`)逐字段同构。财务工具 args 扁平(`FinancialsArgs` 只 `ts_code:str`+`period:Literal`,`get_financials.py:15-17`)无 `$ref`。缺口小:Pydantic v2 嵌套模型带 `$defs/title/$ref` 需 flatten;`function.name` 须 == tool-call 名 == `tools_kwargs` key(recipe `:310`,本仓稳定)。补:`tool_to_verl_yaml` ~10 行。
- **④ live vs cache/cassette(是)— 最利好**:`GetFinancialsTool.run` 不碰网络,调注入的 `self._tushare`(`get_financials.py:46-47`);`TushareService` 是 Protocol(`tushare_service.py:21`),`build_tushare_service()` 看 `TUSHARE_MODE` 默认 `mock`(`tushare_factory.py:19-41`);`RealTushareService._call_cached` 已有 sqlite cache 层(`tushare_service.py:69-82`,`data/tushare_cache.sqlite`);仓内已有 tushare 真实回放 cassette(`test_tushare_real_cassette.py` + fixtures)。**推荐**:`TUSHARE_MODE=real` + 预热 cache → 零网络确定性真值。缺口:`build_tushare_service()` 进程级 env 读取(`tushare_factory.py:24`),无 per-样本切换,靠 ② 的 `create_kwargs` 注入 ts_code/cassette;MCP 路径每 `handle` 新建 service(`financial_statements.py:65-70`),走 L1 更干净。

**关键墙**:要复用的是**单个无状态数值工具的 `Tool.run` + schema**,**不是** `ToolLoop`(`loop.py:45` 整个状态机不进 verl,verl 用自己的 `ToolAgentLoop`)。

### 缺口 3 — cassette 格式被 verl execute() 读（就绪度:部分）

> 快照于 2026-06-09;cassette/tushare 基建**不属于 dd_report 重构范围**,结论不受其影响。

- **① 存储格式**:VCR.py(pytest-recording/vcrpy 8.x)YAML,顶层 `interactions: [{request, response}]`,`version:1`,冻**原始 HTTP 请求/响应对**。落盘 `backend/tests/fixtures/cassettes/<module-stem>/<test-name>.yaml`(`conftest.py:71-81`);tushare 专用子目录 36 个 `.yaml`(`test_tushare_real_cassette/test_get_daily_real[600519.SH].yaml` 等)。一条 interaction:`request.body` = JSON `{"api_name":"daily","token":"REDACTED","params":{...}}`(`:3-4`),`response.body.string` = tushare 原始 `{"code":0,"data":{"fields":[...],"items":[...]}}`(`:24`)。
- **② key/索引**:VCR 不算 hash,按 `match_on` 字段线性匹配。tushare 专用 `["method","path","token_stripped_body"]` + 自定义 matcher 剔 token(`e2e/conftest.py:13-41`)→ 等价类 = `api_name + params`(工具入参)。**关键发现:已有现成"入参 hash → 快照"层 `TushareCache`** —— sqlite 表主键 `(api_name, params_hash)`,`params_hash = sha256(json.dumps(params, sort_keys=True, ensure_ascii=True))`(`tushare_cache.py:60-84`),`fields` 投影并入 hash(`tushare_service.py:75`)。**这就是 verl 想要的形态。** 注意 LLM cassette(b1/chatloop)故意丢 body 纯顺序回放(`test_chatloop_cassette.py:213`),不可按入参寻址——但 RL 的 LLM 是被训练的 policy,本就不该读 cassette,对数值工具层无影响。
- **③ 冻原始响应**:cassette `response.body.string` = tushare 原始 JSON 信封,DataFrame 化在回放命中之后(`tushare_client.py:65-75`)。例外:`TushareCache` 冻 `pickle.dumps(df)`(`tushare_cache.py:105,134`)。
- **④ 脱 pytest**:VCR 回放绑 pytest+httpx 拦截**不可脱**;但 YAML 数据可脱——`cassette_validation.py:55-69` 已示范 `yaml.safe_load(path.read_text())` 裸读,零 pytest 依赖。这正是 verl execute() 该走的路径。

**精确缺口**:cassette 那侧没有"入参 hash → 单条快照"独立索引(只有 pytest 参数化文件名 + VCR 线性匹配),独立索引**只在 `TushareCache` 现成存在**;覆盖面窄(5 ts_code × ~8 endpoint,`test_tushare_real_cassette.py:39-45`)。**补法**:首选直接复用 `TushareCache`(execute() 里 `await cache.get(api_name, params)`,miss 落真 API);次选写 ~30 行 YAML 索引器(范式 `cassette_validation.py:48-70`)。**风险**:`TushareCache` 存 pickle DataFrame,跨 pandas/python 版本可能反序列化失败(已有 corrupt-blob 容错降级为 miss,`:106-113`),verl 进程 pandas 版本须对齐;自建索引若忘剔 token 会全 miss;tushare 快照漂移无自动告警(`cassette_validation.py:66-69` 只认 LLM-shaped cassette)。

### 缺口 4 — 金融题集→真值进 `reward_model.ground_truth`（就绪度:部分）

> **快照于 2026-06-09,该模块在动。** `ground_truth_loader.py` + `prediction_metric.py` 已删,`MetricInputs.ground_truth` 已从 base.py 移除。

**本仓没有单一统一"问题→答案"题集**,分散在 4 类异构 golden:

- **A. dd_report backtest**(`golden/backtest_cases.jsonl`,40 行=32 backtest+8 sanity):一行 = `{case_id, ts_code, target_name, cut_off_date, case_type, company_type}`,**行内无标准答案字段**;真值运行时 live 拉 tushare——数值真值 `_lookup_real_value` 调 `adapter.fetch_income(...)` 取 `revenue`/`n_income` ±1%(`numerical_metric.py:52-53,101,125-150`);预测方向真值靠 HEAD 的 `prediction_metric._direction_correct` 比对 cut_off 后 90 天 K 线/公告(**此刻已删**)。
- **B. tool_selection**(`golden.jsonl`,28 行):`{case_id, category, user_input, expected:{first_tool, args_contains:{ts_code}}, bucket}` — **结构化确定性**。
- **C. chatloop scenarios**(`golden/scenarios.jsonl`,30 case):tool_selection 同构 + `difficulty/persona/policy_refs`,部分带 `expected_answer:{expect_abstain, must_ground_on}`(`scenarios.jsonl:27,35`)。`must_ground_on` 是指向句(「应基于 get_financial_statements 的净利润数值」`:36`)**不是数值本身** → judge 评。
- **D. memory**(`cross_turn_extraction_golden.jsonl` 20 行等):`expected_edges:[{rel_type:"HOLDS", target_label:"Stock:600519.SH", properties:{qty:500, avg_cost:1500}}]`(`:1`)— **结构化图谱边 + 确定性数值属性**。

**确定性可 oracle 真值**:tool_selection/chatloop `first_tool`+`args_contains`(`scorers.py:5-8` 「确定性层零裁判」委托 `score_case`)、`expect_abstain`(`scorers.py:91`)、cross_turn `expected_edges` qty/avg_cost、numerical 数值(live 拉 + ±1%,需快照固化)、prediction direction(已删需恢复)。**不可 oracle**:`must_ground_on`(`scorers.py:8` 「grounding 裁判」`grounding_scorer.py`)、citation/risk-pairing(LLM-judge cassette)、b1 关键词软断言(`test_b1_diff_balanced.py:99-108` 弱,不算严格 oracle)。

**序列化**:tool_selection/chatloop `expected`/cross_turn `expected_edges` 本身 JSON dict,**零转换进 parquet `non_tensor_batch`**;dd_report 数值真值**不能直接序列化**(运行时 live 拉,`numerical_metric.py:132`),须预先 dump 每个 `(ts_code, period, 指标)` 的 tushare 元值进 ground_truth;`CaseMeta.cut_off_date: date`(`base.py:32`)非 JSON-able 需 isoformat(`backtest_cases.jsonl` 里已是 `"2024-06-30"` 字符串,内存 CaseMeta 才是 date 对象)。

**量级**:单题集均几十条,合并去重 **~150–170 条**确定性可 oracle,**未达"几百条"门槛**;backtest 仅 8 独立标的 × 5 cut_off,多样性低。chatloop 已有 pass@k 基建(`passk.py`)但为 CI 闸非 RL 训练量。**补法**:写真值快照固化器 + 从 HEAD `git show` 恢复 loader 蓝本 + 模板化扩量(tool_selection/chatloop 是 `user_input`+`expected` 模板可低成本扩到几百)+ 新建数值计算 golden。

### 缺口 5 — compute_dcf / A5a cross-check 纯度与确定性（就绪度:部分,估值数学层=是）

> 快照于 2026-06-09;**目标文件全在 `valuation_helpers/` 与估值链路,不属于 dd_report 重构,结论稳定。**

- **① 7 个 helper 全纯 CPU、同步、确定性**:`compute_dcf_value`(`dcf.py:186-275`,只 `math.isfinite` + 四则/`**` 折现)、`compute_growth_trajectory`(`dcf.py:42-136`)、`compute_company_wacc`(`dcf.py:139-183` CAPM)、`compute_dcf_sensitivity`(`dcf.py:278-318` 5×5)、`compute_pe_value`/`compute_pb_value`/`compute_ev_ebitda_value`(`pe.py:18-55`/`pb.py:21-57`/`ev_ebitda.py:26-98`)、`analyze_consistency`(`consistency.py:29-50` 样本方差 CV)。全目录 grep `LLMService|llm\.|.chat(` **零命中**,无 `random`/`datetime.now`/`time.`/网络/DB。**实测**:同输入连调两次 `compute_dcf_value`,`v1==v2`,`31.4281518...` 浮点逐位一致。注意 `0.0`/`None` 是合法返回(`ev_ebitda.py:98` clamp、`dcf.py:313-314` Gordon 发散、`consistency.py:34`)非异常。
- **② A5a cross-check 纯/LLM 分界**:`calculate_valuations`(`valuation_calculator.py:84-184`)是数值主干,逐 model 调纯 helper + `analyze_consistency`,文件唯一 LLM 命中 `apply_llm_override` 是**纯函数**(`industry_model_router.py:84-93` 只换 list,override 对象上游传入,**不调 LLM**)。`IndustryModelRouter`/`industry_defaults.py` 查表 normalize 全纯。**必须排除**:`OutlierDiagnosisAgent.diagnose` **调 LLM**(`outlier_diagnosis_agent.py:73` `self._llm.chat(...)`,仅 `severe` 触发,`analyst.py:286-287`);`Analyst.step` 调 LLM(`analyst.py:224`)+ import debate(bull/bear/orchestrator 均 LLM)。`RouterOverride` 本期 A5a 默认 None(`analyst.py:283 router_override=None`)→ 实跑 router 纯查表无 LLM。
- **③ 确定性边界画法**:reward fn oracle 输入应是 **`ValuationInputs` dataclass**(`valuation_calculator.py:45-66`),直接 `calculate_valuations(inputs, router_override=None)`,拿 `ValuationResult` 的 `pe_value/pb_value/ev_ebitda_value/dcf_base/valuation_consistency` 当真值。把"取数"和"OutlierDiagnosis narrative"踢出边界。
- **④ 独立进程可 import**:7 helper AST 闭包只含 `__future__/math/typing/exceptions`,**实测** Windows py3.12(无 pydantic)独立进程 import + 跑通 DCF/PE/consistency = `PURE HELPERS IMPORT OK`;`calculate_valuations` 闭包多 `industry_model_router`(+pydantic)和 `investment_dd_schema`(只 `datetime/enum/typing/pydantic`,**无 LLM/DB**),**不 import** `llm_service`/`analyst`(AST 已证,不拖 LLM/langgraph/tushare 重型栈)。

**精确缺口**:(1) `calculate_valuations` 输入来自 `state.tool_results`(网络 tushare),取数侧确定性**【本审计未读 tushare client 实现,需另查】**,补:tool_results 快照成 JSON fixture 或 cassette client,oracle 只吃 `ValuationInputs`;(2) `tool_results → ValuationInputs` 反推逻辑(eps=price/pe、shares=total_mv/price×1e4)在 `Analyst._build_valuation_inputs_from_state`(`analyst.py:347-517`)私有方法,纯但 import 它拉 LLM 栈,补:抽成 `valuation_helpers` 自由函数;(3) `severe → 诊断`是 LLM 分叉,reward 只到 `valuation_consistency` 层。**风险**:CV 阈值边界(0.15/0.30,`consistency.py:25-26`)样本压线时 reward 对舍入敏感;oracle 应锚 `ValuationResult` dataclass 而非 `ValuationAnalysis` pydantic schema(减耦合)。

### 缺口 6 — verl 训练 venv vs 后端 import 链（就绪度:部分,A/A+ 层=是）

> **快照于 2026-06-09,该模块在动。** numerical_metric 结论基于工作区当前版本,接 oracle 前需复核。

- **A 层(纯估值数学)**:`valuation_helpers/` 全部 import 头 = `math` + `typing` + 包内 `exceptions`(`dcf.py:18-23`/`pe.py:9-13`/`pb.py:12-16`/`ev_ebitda.py:17-21`/`consistency.py:15-18` 零包内依赖/`exceptions.py:3`/`industry_defaults.py:13` 只 `__future__`)。**除 stdlib 零第三方**,smoke 实测 `T1_OK`。
- **A+ 层(orchestrator)**:`valuation_calculator.py:19-40` import 包内 5 helper + `industry_model_router`(`:24`,→ `typing`+`pydantic`+`investment_dd_schema`)+ `investment_dd_schema`(`:6-12` → `datetime/enum/typing/pydantic`)。**全部第三方 = `pydantic` 一个**,无 LLMService/DB/Celery/tushare;公共入口函数 `calculate_valuations`(`__all__`)。smoke 实测 `T2b_OK`。
- **B 层(numerical_metric)**:`numerical_metric.py:23` import `eval.dd_report.metrics.base`;顺 `base.py:14-15` 追 → `EvaluatorClient` 来自 `llm_swapper.py:27-30` 顶层 **eager `import httpx` + `from openai import OpenAI`**(只因 `MetricInputs.evaluator_clients` 字段类型标注);`TushareBacktestAdapter` 是纯 Protocol 零第三方(`tushare_backtest_adapter.py:9-13`,真 client 靠 `inner` 注入)。smoke 实测 `T3_OK/T4_OK`(venv openai 2.33.0 在)。**`numerical_metric` 本身不碰 tushare/pandas**(走 Protocol 注入)。
- **依赖声明源**:根 `pyproject.toml` 权威——`tushare>=1.4`(`:55`)、`openai>=1.40,<2.37`(`:23`,**注意上限 <2.37**)、`pydantic[email]>=2.7`(`:19`);`backend/app/requirements.txt` 是过时 legacy 非真相源。`app/__init__.py`/`app/agents/__init__.py` 实测空,无 eager 侧链。
- **③ 能否共 venv:必须独立,oracle 代码可无痛跨过去**:verl+sglang 要 Linux+CUDA+多卡 + 特定 torch/vllm/flash-attn,与后端 WSL fria-venv(FastAPI/Celery/langgraph/tushare)两套不兼容宇宙,合并必出 torch/cuda 冲突。但 oracle 增量极小:A/A+ = stdlib + pydantic(verl 环境几乎必有),B = 再加 openai/httpx(轻量纯 HTTP 无 CUDA 冲突)。**结论:训练 venv 独立,塞 ~5 个 oracle 源文件 + pydantic(+ B 层 openai/httpx)即可。**

**落地 smoke test 命令**(符合本仓「import 链假设要 smoke test 验」约定,已在 fria-venv 实测通过):
```bash
export PYTHONPATH=/path/to/backend
python -c "from app.agents.valuation_helpers.dcf import compute_dcf_value; from app.agents.valuation_helpers.pe import compute_pe_value; from app.agents.valuation_helpers.consistency import analyze_consistency; print('A_OK')"
python -c "from app.agents.valuation_calculator import calculate_valuations, ValuationInputs, ValuationResult; print('A+_OK')"
python -c "from eval.dd_report.metrics.numerical_metric import NumericalMetric, parse_chinese_number; print('B_OK')"
```

**风险**:(1)**快照风险(最高)**:B 层接 spec 前须以 dd_report 重构落定后版本复核,`base.py` eager 链可能正是这次会动的地方;(2)**openai 版本墙**:`pyproject.toml:23` pin `<2.37`(2.37 构造期强制校验 credentials),fria-venv 实测 2.33.0 已贴上限,训练 venv 若被 sglath 拉到 ≥2.37 会撞 `EvaluatorClient` 构造行为变化(A/A+ 不碰 openai 无此风险);(3)**pydantic 大版本**:verl 若 pydantic v1,`industry_model_router.py:19` 的 `ConfigDict`(v2-only)会炸,须确认 ≥2.7。

---

## 确定性 oracle 边界（命门专节,综合缺口 5 + 缺口 4）

**这是能不能上 RL 的命门:RL 奖励必须确定性可复现。本仓的真值分两半,只有左半可当奖励。**

### ✅ 有确定性真值,可直接当 RL reward（verifiable）

| 子任务 | 真值来源 | 确定性证据 | 备注 |
|--------|----------|-----------|------|
| **估值算式**(DCF/PE/PB/EV-EBITDA/敏感性/一致性 CV) | 纯 Python 算术,输入 `ValuationInputs` | `valuation_calculator.py:84-184` 全纯,浮点逐位实测可复现 | **离 RL 最近的一块**;oracle 只吃 `ValuationInputs` 调 `calculate_valuations(router_override=None)` |
| **数值取数准确率**(营收/净利对 tushare ±1%) | tushare 元值(需快照固化) | `numerical_metric.py:101` 相对误差容差 | 仅 4 指标且 ROE/资产负债率 v0 简化;真值 live 须固化;模块在动 |
| **工具选择 / 路由**(first_tool + args_contains) | golden `expected` JSON | `scorers.py:5-8` 确定性层零裁判 | 零转换进 ground_truth;process reward |
| **弃权检测**(expect_abstain) | golden bool | `scorers.py:91 is_abstain_case` | 确定性 |
| **记忆抽取边**(qty/avg_cost 等结构化属性) | `expected_edges` JSON | `cross_turn_extraction_golden.jsonl:1` 精确匹配 | 结构化数值,确定性 |

### ❌ 无确定性真值,必须排除出 RL reward（LLM-judge / 主观 / 副作用）

| 子任务 | 为何不能当 oracle | 证据 |
|--------|-------------------|------|
| **grounding / must_ground_on** | LLM judge,`must_ground_on` 是指向句非数值 | `scorers.py:8` 裁判;`scenarios.jsonl:36`;`grounding_scorer.py` |
| **报告质量 / citation / risk-pairing** | LLM-judge cassette | `tests/eval/dd_report/cassettes/*_judge.yaml` |
| **OutlierDiagnosis 叙事诊断** | 调 LLM,非确定 + 网络副作用 | `outlier_diagnosis_agent.py:73` |
| **Analyst insights / bull-bear debate** | 全调 LLM | `analyst.py:224`;A5b debate |
| **b1 差异化关键词软断言** | presence 软断言,不严格 | `test_b1_diff_balanced.py:99-108` |
| **预测方向 / target_hit** | 逻辑确定(事后 K 线)但 **loader 代码此刻已删** | HEAD `prediction_metric._direction_correct`(snapshot:已删) |

**边界一句话**:把 reward 画在「**结构化可程序校验的层**」(工具名/args/弃权/抽取边/估值算式输出/数值取数 ±容差),**绝不**把奖励算在「**自然语言质量/grounding/citation/叙事**」上——后者全是 judge,引入噪声 + 成本 + 不可复现,毒化 RL 信号。"取数"层本身(网络 tushare)不在确定性内,必须 cassette/快照固化后才进边界。

---

## 最小试点建议

### 第一个 RL 试点选什么任务形态（最可能直接跑通的窄切片）

**推荐:单工具数值取数 + 确定性 ±容差奖励的窄切片。**

- **任务形态**:给一条"查某股某期某财务指标"的 user prompt,policy 学会(a)选对工具 `get_financials`、(b)填对 `ts_code`/`period` args、(c)从工具返回里抽出正确数值。奖励 = 工具选对(process,缺口 4 的 `first_tool`/`args_contains` 真值)+ 数值对 tushare ±1%(缺口 1 的容差内核)。
- **为何是它**:四块阻抗全在这条线上最低——工具入口已 async/dict/OpenAI-schema(缺口 2);数据层已 mock/cache/cassette 解耦经 e2e 守护、且 `TushareCache` 就是"入参 hash → 快照"(缺口 3);工具选择真值零转换进 ground_truth(缺口 4);容差/单位归一内核现成(缺口 1)。
- **明确避开**:`ToolLoop` 状态机、`InProcessTool` 记忆/技能类(依赖整个 `ChatLoopState`,硬墙);`must_ground_on`/citation/报告质量等 judge 层;`OutlierDiagnosis`/`Analyst`/debate 的 LLM 分叉。
- **次选(若想要"算式"而非"取数")**:估值算式窄切片——policy 输出 `ValuationInputs` 各字段,oracle 调 `calculate_valuations` 当真值。它是确定性最干净的一块(缺口 5/6),但需要先把 `tool_results→ValuationInputs` 映射抽成自由函数,且任务设计偏"填表"不偏"agent 多步工具",离 verl multistep tool RL 的典型形态稍远。

### 需要先补的最小胶水清单（按工作量从小到大）

1. **`tool_to_verl_yaml(tool)`**（~10 行,缺口 2③):取 `tool.schema_for_llm()["function"]` 套 verl `tool_schema`。**风险最低,先做。**
2. **复用 `TushareCache` 当 cassette 后端**（近零,缺口 3):execute() 里 `await cache.get(api_name, params)`,miss 落真 API 预热。免写索引器。
3. **`BaseTool` adapter**（~30 行/工具 + ~15 行注入,缺口 2①②):补 `create/release` 生命周期 + dict→ToolResponse + 经 `create_kwargs` 注入 ts_code/cassette 名/容差。
4. **真值快照固化器**（中,缺口 4):遍历 tool_selection/chatloop golden,把 `first_tool`/`args_contains` + 固化后的期望数值打成 `{task_type, question, ground_truth:{...JSON...}}`,date 全 isoformat。
5. **`verl_oracle_reward.py`**（~50–100 行,缺口 1):模块级 `compute_score(data_source, solution_str, ground_truth, extra_info)`,内部抽数值 + ±容差比对;**先用裸数值容差版,不复用 `NumericalMetric` 的多指标遍历**(避开正在重构的 `MetricInputs`)。
6. **独立训练 venv + 复制 oracle 源文件**（小,缺口 6):venv 装 ~5 文件 + pydantic(+ openai/httpx 若用 B 层),PYTHONPATH 指 backend/。
7.（可选,缺口 5 次选路径才需）**抽 `tool_results→ValuationInputs` 自由函数**:从 `Analyst._build_valuation_inputs_from_state` 提到 `valuation_helpers`。

### 动手前必跑的 smoke test 清单

```bash
# (a) 独立训练 venv 能 import oracle —— 缺口 6 三条(A/A+ 必过,B 视是否复用 numerical_metric)
export PYTHONPATH=/path/to/backend
python -c "from app.agents.valuation_helpers.dcf import compute_dcf_value; from app.agents.valuation_helpers.pe import compute_pe_value; from app.agents.valuation_helpers.consistency import analyze_consistency; print('A_OK')"
python -c "from app.agents.valuation_calculator import calculate_valuations, ValuationInputs, ValuationResult; print('A+_OK')"

# (b) 工具入口 + schema 形状 —— 缺口 2①③
python -c "from app.tools.get_financials import GetFinancialsTool, FinancialsArgs; t=GetFinancialsTool.__new__(GetFinancialsTool); s=GetFinancialsTool.schema_for_llm.__doc__ or 'check'; print('schema shape: must be type/function/parameters')"
# 实跑一次 Tool.run(确认返回 dict、确认 TUSHARE_MODE=mock 不触网)
TUSHARE_MODE=mock python -c "import asyncio; from app.tools.get_financials import GetFinancialsTool, FinancialsArgs; from app.services.tushare_factory import build_tushare_service; t=GetFinancialsTool(build_tushare_service()); print(type(asyncio.run(t.run(FinancialsArgs(ts_code='600519.SH', period='annual')))))"

# (c) cassette/TushareCache 可脱 pytest 裸读 —— 缺口 3
python -c "import yaml,json,glob; fs=glob.glob('backend/tests/fixtures/cassettes/test_tushare_real_cassette/*.yaml'); d=yaml.safe_load(open(fs[0])); body=d['interactions'][0]['request']['body']; print('req keys:', list(json.loads(body).keys()))"
python -c "from app.services.tushare_cache import TushareCache; print('TushareCache import OK — (api_name, sha256 params) -> df')"

# (d) 确定性复现 —— 缺口 5(同输入两调逐位一致)
python -c "from app.agents.valuation_helpers.dcf import compute_dcf_value as f; a=f.__call__ if False else None; print('run compute_dcf_value twice, assert v1==v2 bit-exact')"

# (e) ⚠️ dd_report 重构是否落定(缺口 1/4/6 的阻塞前置)
git status --short backend/eval/dd_report/   # 期望:这些路径全部干净(无 M/D)才可对 MetricInputs 字段写胶水
```

> 注:(b)(d) 的 `python -c` 是占位骨架,落地时按实际构造参数补全;关键是先用 mock 模式确认入口形状与不触网,再切 cache/cassette。

---

## 阻塞项

1. **【最强阻塞】dd_report eval 正被另一会话重构,字段在动**——缺口 1/4/6 全部受影响。当前工作区:`prediction_metric.py` + `golden/ground_truth_loader.py` **已删**、`metrics/base.py` **已删 `MetricInputs.ground_truth` 字段**(本审计 `git status` + `grep base.py` 实证)。**影响**:(a) 任何 `MetricInputs(...)` 构造胶水**不能现在写**,字段会与 in-flight 改动冲突;(b) 预测方向 oracle 的 loader 代码不在工作区,要么从 HEAD `git show` 恢复作蓝本、要么等重构定稿;(c) `base.py:14` 的 `EvaluatorClient` eager import 链可能正是这次会动的地方。**必须先做**:等 dd_report 重构在 `feat/chatloop-eval-blueprint` 上 settle(或明确其最终 `MetricInputs` 形状),才能对缺口 1/4 的数值真值胶水定型。**规避路径**:最小试点(单工具取数容差)的 `verl_oracle_reward.py` 用**裸数值 + ±容差**自包含实现,**不 import `numerical_metric`/`MetricInputs`**,即可绕开此阻塞先跑通工具选择 + 取数那条线。

2. **取数侧网络确定性未验**——缺口 5 明确标【本审计未读 tushare client 实现】。`calculate_valuations` 纯,但其输入 `ValuationInputs` 源自 `state.tool_results`(网络 tushare)。**先做**:读 `app/data/tushare_client.py` 确认取数可被 cache/cassette 完全拦截、无隐藏随机/时间依赖,才能保证估值次选路径的端到端确定性。

3. **样本量不足 pass@k 稳健起步**——缺口 4:确定性可 oracle 样本合并去重 ~150–170 条,未达"几百"门槛,且 backtest 仅 8 独立标的多样性低。**先做**:用 tool_selection/chatloop 的模板化结构(`user_input`+`expected`)低成本扩量到几百条 + backtest 加标的,否则 RL 训练信号覆盖面与统计稳定性不足。

4. **verl 版本未锁定**——缺口 2 标 verl 版本敏感(v0.5 `execute` 返回 `str` vs main 返回 `ToolResponse`)。**先做**:锁定 verl 版本(参 `docs/research/2026-06-09-verl-multistep-tool-rl-recipe.md` 的 v0.5.0/main 双标),才能定 `BaseTool.execute` 签名与 reward manager 选择(起步用 `naive` 串行可回避 pickle 约束)。

5. **"前置抽取"形态是 spec 决策不是纯胶水**——缺口 1:RL 任务是"逐指标抽取打分"还是"单一最终估值打分"决定 `verl_oracle_reward.py` 走 `NumericalMetric` 多指标遍历还是单数容差两行。**先做**:在 RL 试点 spec 里定死任务形态,再写胶水。
