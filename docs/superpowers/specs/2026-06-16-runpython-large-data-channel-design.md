# 设计:run_python 长序列数据通道(抬阈值 + data-by-ref)

- 日期:2026-06-16
- 分支:feat/portfolio-overview(并发栈,与 trade_cal 同源;spec 为新文档不冲突,实施前确认改动面)
- 体裁:bug 修复设计(systematic-debugging 根因已定),落地后进 plan

## 根因(已追踪定死)

时序计算任务(回撤/波动率/相关性/区间涨幅)实测大面积失败(M1/M2/C2),根因不是 AI 不会算,是**数据喂不进 run_python**:

1. get_daily 一年日线 ~12–15k 字(最多 260 行×7 列);
2. 超 `oversize_result_char_threshold`(默认 **4000 字**)→ `loop.py:_cap_oversized_output` 换成 600 字摘要 + 缓存 ref,**全序列被踢出上下文**;
3. **run_python 的数据只来自 LLM 手填的 `data` 参数(`code_interpreter_tool.py:55-56`),无按 ref 取数通道** → LLM 手里没有全序列;
4. 只能 read_cached_result 每页 2000 字翻回来(`control_tools.py:128`)再手抄 → 翻页螺旋 → 撞打转/预算闸。

**关键数字(100k 是硬顶,不是可调配置)**:100k tokens 是**模型输入的硬上限**(`CHATLOOP_MAX_CONTEXT_TOKENS=100000` 按此设,`chat_runner.py:263`)。这 100k 是**共享预算**:稳定前缀(系统提示 + persona + 23 工具 schema + 技能清单)+ 历史区 + 本 turn 逐圈**累积**的工具结果,全挤在 100k 里,且随对话变长还在缩。
- **单序列**:一年 ~15k 字 ≈ 3–4k tokens,塞进 100k 绰绰有余 → 被 4000 字上限**误截**,抬阈值(①)即解;
- **多序列**:C2 四只 ≈ 12–16k tokens 且逐圈累积 + 前缀历史占去一截 → **物理上挤不进 100k**,抬阈值无用,数据**必须**走 ref 不进上下文(②)。

**所以 ② 不是优化、是必需**:100k 硬顶决定大数据不可能长驻上下文,② 是唯一能扩展的路;① 只是单序列的有界权宜,扛不到多标的(复杂档=筛选/排名,正是 agentic RL 尖货,**没 ② 跑不起来**)。

**本修同时解锁产品与验证集**:不修它,中等/复杂档 pass@k 量的是这个 bug 不是 AI 战力。

## 两个修法(分阶段,一份 spec)

### ① 抬截断阈值(快赢,config 级)

- `ContextDeps.oversize_result_char_threshold` 默认 **4000 → 24000**(一年单序列 ~15k 字 + 余量;~4k tokens,远在 100k 窗口内)。chat_runner 可经 env `CHATLOOP_OVERSIZE_RESULT_CHARS` 覆盖,默认 24000。
- 不动压力阀:`context_pressure_ratio=0.85`×`max_context_tokens` 仍是**多结果累积**的兜底——单序列放行、四只票堆到逼近窗口时仍逐级收紧降级(②之前的安全网)。
- **诚实边界**:① 只去掉**翻页螺旋**(全序列在上下文里,run_python 的 `data` 一次填得上),**但仍靠 LLM 手抄 242 个浮点进 `data`**——慢、可能抄错/丢精度。单标的(S2/M2)预计能通,多标的(C2)仍会因累积+手抄成本爆。手抄问题留 ②。
- **测试影响**:`test_loop_oversize_cap.py`(会话起始已 M)断言按新阈值更新;补一条"一年级序列不再被截断"的断言。

### ② data-by-ref 通道(根治,架构级)

补全现有"大数据绕开上下文"设计哲学的缺口(图→chart 事件 ✅ / 大结果→缓存摘要 ✅ / **大结果→run_python 计算 ❌ 缺**):**让 run_python 按 ref 直接吃缓存里的完整结构化数据,数字全程不经 LLM。**

**接口**:`CodeInterpreterArgs` 加可选字段
```
data_refs: dict[str, str] | None = None
# 变量名 → 缓存 ref(来自截断工具结果的 ref 字段)。
# 执行器把每个 ref 还原成完整结构化工具输出,注入脚本的 data[变量名]。
# 例:data_refs={"maotai": "u1::get_daily:abc"} → 脚本里 data["maotai"]["close"] 即全序列。
```
- **inline `data` 仍保留**,`data_refs` 为加项;两者合并后传给 backend(向后兼容)。

**数据流**(`CodeInterpreterTool.run_with_state`,服务端解析,数字不经 LLM):
1. 对每个 `(varname, ref)`:校验 `ref.startswith(f"{state.user_id}::")`(沿用 `read_cached_result` 防越权,不泄露他人键存在性),不符 → `[无权访问]` 指导错误;
2. `raw = await cache.get_raw(ref)`;None → `[缓存不存在/已过期] 请重调原工具`;
3. `structured = json.loads(raw)`(缓存存的是工具输出 JSON);解析失败 → 指导错误;
4. `merged = {**(args.data or {}), **{varname: structured ...}}`;
5. `run_code(source=args.code, data=merged, timeout_s=...)`(沙箱内 `data[varname]` 即完整数据)。

**接线**:
- `worker_wiring.py:237` 注入 cache 到 `CodeInterpreterTool(backend=..., cache=singletons.cache)`(现仅注 backend);
- `tool_docs.py` run_python 文档加 `data_refs` 用法 + 一句纪律:"数据量大的工具结果(日线序列等)别手抄进 data,用 data_refs 传 ref,执行器自动灌全量";
- `code_interpreter_tool.py`:加字段 + 解析逻辑 + ToolError 分支;
- 复用 `ToolResultCache.get_raw`(无需新缓存方法;若结构化更顺可加薄 `get_json`)。

**run_python 自纠**:ref 失效/越权回指导性错误,chatloop while 循环天然让模型改 data_refs 重试。

## 确定性 / 验证集衔接

修完**重测 pass@k**:②让"取数→run_python 算指标"成为干净的多步可验证形态——agent 只指挥(传 ref),数字由后端精确灌入、独立 oracle 精确对账,**手抄精度损失这条噪声被消除**(对 ±容差判分尤其关键)。这是把"能覆盖计算类场景"变"真覆盖"的最后一块管线。

## 不做(YAGNI)

- 不让 run_python 自己调工具/触网(沙箱铁律不变);
- 不做 ref 的跨 turn 持久化(turn 内缓存够用);
- 不改 read_cached_result 语义(它仍是"人看的取回";data_refs 是"机器算的取数",两条路);
- 不把所有工具结果都不截断(压力阀+阈值仍是上下文成本的闸)。

## 验收

- ① 后:S2/M2(单标的时序计算)实测能自然停、答案对独立 oracle ±容差通过,不再撞打转/预算闸;`test_loop_oversize_cap` 绿。
- ② 后:C2(四只筛选)能用 data_refs 一次把四只全序列灌进 run_python、自然停、筛选集合对 oracle;无手抄、无翻页螺旋;新增 run_python data_refs 单测(命中/越权/失效三路)+ 加 MCP chat 工具测试点同步(若计数受影响)。
- 重测 6 题 pass@k,中等/复杂档真实战力可读。

## 阶段

1. **① 抬阈值**(小改、先做、立即重测 S2/M2 单标的;**不指望它扛复杂档**);
2. **② data-by-ref 通道**(架构改动,**本修主菜**,重测 C2 + 多标的);
3. 重测 6 题 pass@k → 再定 RL 打哪档。
