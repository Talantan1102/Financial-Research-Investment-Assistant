# 设计方案:缩工具链 + 备好 RL 底料

> 由设计 workflow(4 路并行勘察真实代码 + 汇总)产出,所有结论已对真实代码核验(file:line 见文末索引)。
> 范围:harness / 工具 / 评测侧。**不含**推理期拐杖(参考代码 skill)、**不含**训练侧(课程 / 奖励函数 / SFT-RL 循环)。

## 摘要

计算题的最短工具链是 `trade_cal(定窗) → get_daily(取数)×N → run_python(算)`,弱模型死在两处——
**"N 次串行取数的编排"和"手写 run_python 崩"**。我们能做、且不破坏 benchmark 的最高杠杆:

1. **缩链**:加一个批量取数工具 + 给 get_daily 内联相对窗口,把"`2+N` 步、随股票数线性膨胀"的链**结构性压成固定 2–3 步**,与股票数解耦 → 训练推理一致。
2. **底料**:runner 现在只落末次答案(且把 gold 写进每行=泄漏面)。**完整轨迹 + ledger 落盘** + **把 0/1 判分改连续距离**,几乎零额外数据就把"分级数据"扩成"分级 + 稠密中间奖励 + 干净 SFT 轨迹"。
3. **红线**:最猛的"取数+算合一"(`compute_indicator`)会**把计算从 agent 拿掉**,且复用 oracle 就是裁判与被测同源 → 评测失效。**缓做,不进第一批。**

## ① 缩工具链(按性价比排序)

| 序 | 提案 | 砍掉步数 | 改动量 | 口径风险 | 决定 |
|---|---|---|---|---|---|
| 1 | `get_daily_batch`(一次取多股 + 按 trade_date 对齐) | 排序/筛选 `2+N`→3;相关 4→3 | 低(照 compare_stocks) | 零(同源 tushare.get_daily) | **先做** |
| 2 | `get_daily` 加 `anchor+lookback`(窗口内联) | 每题 −1;消灭"漏 anchor"整类失败 | 低(复用 _handle_window) | 零(同源解析) | **同期做** |
| 3 | `compute_indicator`(取数+指标合一,整链→1) | 整链→1 | 中 | 高(计算从 agent 拿掉 + oracle 同源) | **缓做** |

做完 1+2,**5 种题形全部收敛到 2–3 步、步数与股票数无关** → RL 想要的低方差、可奖励轨迹形状。

### 提案 1:get_daily_batch
- **为什么**:get_daily 是单股的(`get_daily.py:25-33`)。排序/筛选 N=3–5,弱模型被迫连发 N 次结构相同的取数,每次都是出错机会(取错代码/漏参/窗口不齐),链长 `2+N` 随股票数膨胀——qwen3-8b 15.6% 的主战场。
- **塌掉**:排序/筛选 `2+N`→3;相关 4→3;N-1 次"拼 ts_code"出错面积→1。
- **接口**:`ts_codes:list[str](2–10), start/end(或 anchor+lookback)` → `{start,end, aligned_dates(各 code trade_date 交集), by_code:{code:{dates,close,pct_chg,summary}}}`。
- **关键点**:① 内部 `asyncio.gather(get_daily×N)`,每只复用 `_format_daily`(照 `compare_stocks.py:42-62`);② **把"按 date 对齐"做进工具**(相关题免在 run_python 写内连接,对齐口径同 oracle `indicator_oracle.py:53-55`,不动 gold);③ N×整年易超截断阈值 → 现成 `_cap_oversized_output` 换成**单个 ref+summary**,agent 从"管 N 个 ref"塌成 1 个;summary 给"每只首末收盘+count"小卡,短窗口排序题可免 run_python。
- **影响**:缓存自然独立(加 TTL);进 DEFERRED 不进 CORE;文档写"算多股排序/筛选/相关用本工具,别逐只 get_daily";唯一关注点=真 tushare 下 N×整年可能逼近 30s 超时(可单调)。~70 行。

### 提案 2:get_daily 加 anchor+lookback
- **为什么**:gold 生成本就是 `trade_cal(window)→get_daily` 两步(`generator.py:36-44`);**基线最大宗残留正是"trade_cal 漏 anchor→放弃"(~1/4)**。把窗口解析吸进 get_daily 直接消灭这类失败。
- **接口**:向后兼容加可选 `anchor:YYYYMMDD + lookback:1y/6m/3m/...`;给了就先调 `trade_cal._handle_window`(`trade_cal.py:114-151` 抽共享函数)解析真实 (start,end) 再取数。**窗口口径与 trade_cal 逐字一致,gold 不变。**
- **影响**:口径零漂移(同源);缓存在 handle 内归一化成 start/end 再算 key;trade_cal 保留给纯日历查询。~40 行,风险极低(老路径不动)。批量版同享此参数 → 排序/筛选 trade_cal 都不用调,链变 2 步。

### 提案 3:compute_indicator(缓做)
整链→1 步,但**会把"算指标"从 agent 拿掉**,且复用 `eval/operators.py`+`indicator_oracle.py` = 裁判与被测同源。若做:**独立重写口径**(不 import eval/)+ 与 oracle 差分校验 + 评测按"用没用它"分桶标注。**第一批不做**——先靠 1+2 压平取数链,run_python 崩留给训练侧(SFT+RL)。

## ② 备好底料

### 2a. 部分奖励信号(确定性优先)
gold 端(冻结 oracle + 同源 `meta.window_dates`,已核验 `generator.py:87`)与过程端(`messages`+`ledger`)双双机读对照,所以**几乎全是纯确定性**;唯一离不开 LLM 的是 ranking/set 的"自由文本→结构"一跳。

| 信号 | 对照 | 等级 | 稠密度 |
|---|---|---|---|
| 数值接近 gold(连续距离) | oracle gold+tol | 纯确定 | 极高 |
| 工具纪律(失败/打转/撞闸) | ledger 纯函数 | 纯确定 | 高 |
| 窗口解析对 / 取数区间对 / 标的对 | meta.window_dates / case.stocks | 纯确定 | 高 |
| run_python 跑通(首通/重试/never) | 结果前缀 | 纯确定 | 中 |
| 口径(用 pct_chg/先对齐) | 代码正则探针 | 半确定(弱 shaping) | 中 |
| 终态命中 scalar / ranking·set | judge / judge_llm | 纯确定 / 需 LLM | 低 |

**关键约束**:ledger 只存 args_hash(不可逆),要拿实际 start/end/ts_code **必须从 `messages` 的 `tool_calls[].arguments` 解析**(`eval_agent.py:84-106` 已踩坑)。
**MVP**:① `score.py`(不动 judge.judge,并排加 `scalar_distance`/`ranking_partial(tau)`/`set_jaccard`);② `trace_signals.py`(从 messages/ledger 抽过程信号,各配真 cassette 单测)。**奖励函数本身(加权/系数)属训练侧,不做。**

### 2b. 干净 SFT 轨迹采集
- **轨迹本体** = `ChatLoopState.messages`(标准 OpenAI 多轮,结构天生合法)。**三个坑(已核验)**:
  - **坑一**:`assemble_context` 就地把老圈大 tool 输出降级成占位符,eval 默认阈值 **1320 字**(`context.py:76`),一年日线必被降级 → 直接落 messages 得残缺轨迹。**硬性缓解**:采集跑 `deps` 传 `downgrade_char_threshold=10**9`(关降级,一行,零侵入 loop)。
  - **坑二**:撞闸后注入的"(系统:已达上限…)"是 harness 拐杖(`loop.py:419-448`),绝不能进 SFT → **只收 `halt_reason=="natural"`** + 导出白名单 regex 兜底。
  - **坑三**:ledger 不是轨迹,抽 args 只信 messages。
- **两道闸**:① 判对(逐 run,收紧容差复判防蒙对);② 过程干净(`halt_reason==natural` ∧ 全 entry success ∧ 无尾部失败/熔断/打转 ∧ 步数≤桶理想)→ `cleanliness_score`,同 case 多干净 run 留最高分一条。
- **来源(用户决策:用最强模型标注)**:SFT 种子质量 = 热启动质量,**不在源头将就**。用**当前能跑通本 harness 的最强模型**生成轨迹——具体模型在采集步(落地第 3 步)前钉死,经**模型切换模块的 registry** 配(这正是该模块的第一个真用处;接前沿模型只需在 registry 加一条 + 其 API key)。约束:轨迹**必须经本 harness 的工具/循环产出**(格式要跟 qwen3-8b 推理时面对的一致);**不**用 qwen3-8b 自蒸馏;**不**凭空造(oracle 无工具序列、人工编 args 易漂移)。两道闸(判对+过程干净)筛选同样适用。**量化**:k=5,每题≤2 条 → ~200–280 条干净样本。
- **导出格式**:标准 OpenAI 多轮 `{messages, tools(快照), meta{case_id,difficulty,indicator,reference_date,source_model,n_steps,cleanliness_score}}`;**带 system 但剥掉尾部动态区**(步数/预算提示会教模型依赖)、**带 tools 快照**、`meta` **不含 gold/passed**。

## ③ Benchmark 完整性(红线)

| 改动 | 测的内容变吗 | 判定 |
|---|---|---|
| 提案 1 batch | 仍测取对哪些股/哪个窗口/算对;省的是纯 harness 制造的 N 次取数编排 | ✅ 安全 |
| 提案 2 anchor+lookback | 仍测选对窗口/取对/算对;省的是跨工具传参 | ✅ 安全 |
| 提案 3 compute_indicator | **把"算指标"从 agent 拿掉**,run_python 能力不再被测 | ⚠️ 改变测的内容 |

**三条红线**:① compute_indicator 绝不复用 eval/oracle(裁判同源 → 接了的模型该桶必 100%);② **gold 绝不进 SFT**(现 `runner.py:209` 把 gold 写进每行=泄漏 → 产物物理分离:`trajectories_raw.jsonl` 无 gold + `judgements.jsonl` gold 只在此);③ 任何工具改动后**跑全量 pass@k 回归**(单测拦不住桶级回归);新工具文档要从"何时**不**用"反向掰弯弱模型逐只串行本能;`reference_date` 随轨迹冻结。

## ④ 落地顺序(全用现成 141 题验证)

1. **(并行 A)提案 1 + 提案 2** → 全量 pass@k 重跑,看 deepseek 步数分布下降 + qwen3-8b 筛选/排序桶因编排变短而回升(对比基线 模型×桶 表)。
2. **(并行 B)score.py + 轨迹落盘改造** → `run_one` 返回带 final state;采集模式关降级;`trajectories_raw.jsonl`+`judgements.jsonl`(gold 隔离);抽样人工看 5 条轨迹确认 tool 结果完整、无系统注入。
3. **trace_signals.py + 筛选器 + SFT 导出器** → deepseek k=5 产出 ~200–280 条干净轨迹,白名单校验 0 命中,抽样确认 system 剥动态区/tools 快照在/无 gold。
4. **(缓做,单独立项)compute_indicator** —— 仅当 1 效果不足且接受分桶标注成本时。

## ⑤ 边界

| 归我们 | 归训练侧 |
|---|---|
| 缩工具链(提案 1/2/3) | 课程难度怎么排课 |
| 轨迹+ledger 落盘、gold 隔离 | 奖励**函数**(加权/系数/折扣) |
| 0/1 判分改连续距离、抽过程信号(**备齐信号**) | SFT-RL 循环本身、热启动后 RL |
| 筛干净轨迹、导出标准 SFT 格式 | 用轨迹做监督热启动 |

**一句话**:我们交付"**变薄的工具链 + 一组现成稠密中间标签 + 一批干净 SFT 种子轨迹**",训练侧拿去排课、定奖励、跑 SFT-RL。全部改动在 eval/工具侧,**零侵入 loop/state/tool_hub**。

## 关键文件行号索引(均已核验)
- 单股取数/列式·summary/刻意不给 high·low:`app/mcp_server/tools/get_daily.py:25-33,46-63,66-85`
- 多股并行聚合先例(提案 1 照抄):`app/mcp_server/tools/compare_stocks.py:42-62`
- trade_cal window 解析(提案 2 复用):`app/mcp_server/tools/trade_cal.py:57-76,114-151`
- 渐进披露分档:`app/chatloop/tool_docs.py:502-528,536-557`
- 降级就地改 messages(坑一)+ eval 默认阈值 1320:`app/chatloop/context.py:76-77,131-187`
- 超大结果→ref+summary:`app/chatloop/loop.py:298-338`;撞闸注入文案(坑二):`loop.py:419-448`
- gold 生成链 + meta.window_dates:`eval/question_gen/generator.py:36-44,86-90`
- 判分器(改连续距离的源):`eval/question_gen/judge.py:31-48,68-86`;LLM 判:`judge_llm.py:61-76`
- runner(gold 泄漏 `:209`,轨迹被丢在 run_one 返回值):`eval/question_gen/runner.py:82-114,191-214`
- 冻结口径 oracle(**勿在生产工具 import**):`eval/indicator_oracle.py:49-62`
- tool_calls 抽取范式(只信 messages):`app/chatloop/eval_agent.py:84-106`
- 基线诊断(残留=工具可靠性):`docs/research/2026-06-17-pre-rl-tooling-baseline.md:62-82`
