# 代码解释器工具(`run_python`)设计

- 日期:2026-06-11
- 状态:设计定稿,待实施
- 关联:[chat-loop 重设计](2026-06-05-chat-loop-redesign-design.md) · [chat-loop 重设计总卡](../../claude-context/chat-loop-redesign-done.md) · `docs/claude-context/optional-extras-for-heavy-deps.md` · `docs/claude-context/product-minimalism-default.md`

## 1. 背景与目标

chat agent 现有 14 个工具都是「查数据 / 检索 / 控制」类,没有「**自主写代码做计算 + 画图**」的能力。用户问「帮我把这家公司近五年营收画成趋势图」「这几只股票的估值指标对比一下,出张图」时,agent 只能把数字念出来,无法做二次计算、无法产出可视化。

本工具补这个缺口:给 chat agent(以及深度研报 pipeline)一个**代码解释器** `run_python`——LLM 当场写 Python,在沙箱里执行数值计算,并产出**交互式数据分析图**(plotly)回渲到前端。

**价值定位**(对齐 `user-portfolio-target`):作品的技术深度点在两处——(1) 「LLM 自主写分析代码 → 沙箱执行 → 精美交互图」这条端到端可讲的能力闭环;(2) 「LLM 生成代码的安全执行」这个面试高频考点上,有一套可溯源、分层、留口子的工程方案。不在「支持一切语言/一切库」。

## 2. 决策记录

下表是设计期 6 个关键决策,每条标注理由与被否方案,便于后续追溯。

| 决策维度 | 选定 | 否决方案 | 理由 |
|---|---|---|---|
| 使用场景 | chat + 深度研报共用同一执行后端 | 仅 chat / 通用执行服务 | 两处都要画图;通用服务过度设计,违背克制默认 |
| 沙箱底座 | **复用 `SkillExecutor`**(subprocess+rlimit+AST 扫描+workdir),executor 边界抽象成接口,Docker 留 v1.x 口 | 坚持 Docker 容器 / 进程内 exec | 仓库已有生产级 subprocess 沙箱且有 25+ 安全测试;Docker 重运维且与 `SkillExecutor` 重复,违背框架最小化;进程内 exec 隔离最弱、作品减分 |
| 图技术栈 | **plotly 交互图**,`fig.to_json()` 纯内存序列化 | matplotlib 静态图 / ECharts 手搓 option | plotly.express 是真正的「数据分析代码」,体现深度;`to_json()` 不碰文件系统,正好绕开沙箱已禁的 `open()`(matplotlib `savefig` 反而与 ban 冲突) |
| 执行状态语义 | **无状态单发**:每次调用=完整脚本+一次性 workdir | 会话内有状态 kernel | 与 SkillExecutor 一次性 subprocess 天然契合;无 kernel 生命周期/并发隔离/泄漏面;迭代时重发全量代码(多花 token 换架构简单) |
| 渲染协议 | 沙箱产出 plotly figure JSON → 前端新增 `PlotlySpecRenderer` + 专用 `chart` SSE 事件 | 复用现有 ECharts `chart_spec` 链路 | code interpreter 需画任意图(散点矩阵/箱线/热力/K线),ECharts option 手搓只能覆盖现有四类且非「分析代码」;plotly 渲染器照搬 ECharts 渲染器模式,成本可控 |
| 数据来源 | **只做解释器**:`data` 参数接收 LLM 从现有工具拿到的 JSON | 本 spec 顺带接持仓/时间序列工具 | spec 聚焦;沙箱保持纯净无网络;持仓/日线/行业映射工具拆独立 follow-up(见 §9) |

### 2.1 诚实标注的张力

chat-loop 重设计原话:「**计算进技能脚本(零名额)**」——本意是不给通用计算开工具名额,把计算固化成预写技能脚本。`run_python` 是**有意识地破这条**:「LLM 自主写代码」是用户明确要的新能力,语义与「跑预审脚本」根本不同(见 §3.1),值这个工具名额。这个偏离是清醒的,不是疏忽。

## 3. 工具契约

### 3.1 为什么是新工具,不是 `run_skill_script` 的增强

`run_skill_script` 与 `run_python` 语义正交,不能合并:

| | `run_skill_script`(已存在) | `run_python`(本工具) |
|---|---|---|
| 代码来源 | 仓库 `claude_skills/*/scripts/` 的**预写、已审**脚本 | LLM **当场写的任意源码** |
| LLM 角色 | 选脚本名 + 传参 | 写代码 |
| 安全画像 | 可信(人工审过) | 不可信(生成代码)→ AST 扫描更要紧 |
| 入参 | `script_ref` + `payload` | `code`(源码字符串) + `data`(可选 JSON) |

### 3.2 工具入参 / 出参

入参(pydantic `CodeInterpreterArgs`):

```python
class CodeInterpreterArgs(BaseModel):
    code: str                          # LLM 写的完整 Python 脚本
    data: dict[str, Any] | None = None # 喂给脚本 stdin 的 JSON(从现有工具结果来)
```

脚本契约(与 SkillExecutor 现有 stdin/stdout JSON 契约一致):
- 脚本从 `sys.stdin` 读 `data`(`json.load(sys.stdin)`)
- 脚本向 `sys.stdout` 打印一个 JSON,形如:
  ```json
  {"result": <任意可序列化的计算结果>, "figures": [<plotly fig.to_dict()>, ...]}
  ```
- `result` 是给 LLM 看的计算结论;`figures` 是给前端渲染的图(可空数组)

工具出参(`ToolResult.output`,给 loop 后处理):

```python
{"result": ..., "figures": [...], "stderr": "...", "elapsed_s": 1.2}
```

### 3.3 渐进披露挂接

进**延迟组**(`DEFERRED_TOOLS`),在 `tool_docs.py` 加第 15 条 `ToolDoc`:
- `group="deferred"`,`brief` 一句话触发描述(如「写 Python 做数值计算/画交互分析图。需二次计算或可视化时用。」)
- `thin_required={"code": "string"}`(实测空 properties 会被模型绕开,保留必填参数名)
- `doc` 完整文档(何时用/何时不用/脚本契约/plotly 示例/硬约束:无网络无文件无状态)走 `search_tools` 按需返回
- 注册:在 chatloop 工具装配处(in-process 工具注册入口)`register_inprocess([CodeInterpreterTool(...)])`

工具实现为 `InProcessTool`(`run_with_state`),因为需要 `state` 来访问 turn 级的预算/事件通道(见 §5)。

## 4. 架构与组件

```
CodeInterpreterTool (backend/app/chatloop/code_interpreter_tool.py)
   │  run_with_state(args, state)
   ▼
ExecutorBackend (接口, backend/app/skills/executor_backend.py)  ◄── 留口子的关键抽象
   ├─ SkillExecutorBackend   ← v1.0:适配 SkillExecutor.execute_source()
   └─ DockerExecutorBackend  ← v1.x 口子:接口已留,本期不实装
```

### 4.1 SkillExecutor 需新增内联源码入口

**已核实的约束**:`SkillExecutor.execute()` 接 `SkillScriptRef`(磁盘 `skills_root/skill_name/script_path`),AST 扫描走 `script_full.read_text()` 从磁盘读——它跑**磁盘脚本,不接内联源码**(`backend/app/skills/skill_executor.py:84-130`)。

因此 v1.0 工作含给 `SkillExecutor` 加 `execute_source(source: str, payload: dict, timeout_s) -> SkillExecutionResult`:
- 复用 `scan_script_safety(source)` 直接扫内联源码(无需先落盘再读)
- 把 source 写进一次性 workdir 的临时 `.py`,再走现有 `_run_subprocess`(rlimit/env 白名单/stdin payload/stdout JSON/超时 SIGKILL 全复用)
- `ExecutorBackend` 接口签名:`async def run_code(source: str, data: dict, timeout_s: int) -> ExecutionResult`

### 4.2 绘图依赖走 optional extra

`pyproject.toml` 新增 `[project.optional-dependencies]` 组(对齐 `optional-extras-for-heavy-deps`):

```toml
code-interpreter = ["plotly>=5.17"]   # pandas/numpy 已在 base
```

**已核实**:SkillExecutor 子进程用 `sys.executable` 启动(`skill_executor.py:143`),即与后端同一解释器。故 plotly 必须装在后端运行 venv(WSL fria-venv)。沙箱白名单放行 `pandas`/`numpy`/`plotly` import。

## 5. 数据流(核心)

```
LLM 写 code(+可选 data)
   → CodeInterpreterTool.run_with_state
   → ExecutorBackend.run_code(source, data, timeout)
   → subprocess: stdin=data(JSON) → stdout={result, figures:[plotly_json,...]}
   → loop 后处理(集中处理 cache/事件/摘要三件事,工具只返回数据):
       ├─ figures 完整 JSON → ToolResultCache(大输出不进上下文,守 KV-cache 铁律)
       ├─ 发 SSE `chart` 事件(带 chart_id + figure JSON)→ 前端渲染
       └─ 回 LLM 的 tool 消息只含紧凑摘要:
          "result={...}; 生成 N 张图[chart_id=...](已渲染给用户)"
   → 前端 PlotlySpecRenderer 就近渲染交互图
```

**铁律遵守**:figure JSON 可达数 KB,**绝不进 LLM 上下文**——图只走旁路渲染,LLM 只看到摘要+chart_id。这同时满足 KB-cache 窗口铁律(大输出降级为缓存键)和「图能渲染」两个目标。工具保持纯粹(只返回 `{result, figures}`);缓存、发 `chart` 事件、生成摘要这三件事在 loop 后处理集中做。

> 落点说明:loop 检测 `ToolResult.output` 里是否含 `figures` 键。这把「工具产数据」与「传输/缓存副作用」解耦,符合 chatloop「loop.py 是唯一有副作用的编排壳」的分工。具体落在 loop 的工具结果应用环节(实施期定准确插入点)。

## 6. 沙箱与安全

复用 SkillExecutor 全套(已核实 `skill_safety.py` + `skill_executor.py`):

| 维度 | 复用现状 |
|---|---|
| 危险 API | AST 黑名单:`os.system`/`subprocess.*`/`socket`/`requests`/`httpx`/`eval`/`exec`/`__import__`/`compile`/**`open`**/`ctypes.CDLL`(`skill_safety.py:8-38`) |
| 内存/CPU | `RLIMIT_AS` 256MB + `RLIMIT_CPU`(`skill_executor.py:28-46`) |
| 超时 | 默认 30s / 上限 300s,超时 `SIGKILL` 进程组(`skill_executor.py:174-195`) |
| env | 白名单仅 `PATH/LANG/LC_ALL/LC_CTYPE`(`skill_executor.py:57`) |
| 网络 | 完全禁用(`requests`/`httpx`/`socket` 在黑名单) |
| workdir | 一次性临时目录,跑完 `rmtree` |

**plotly 与 `open()` ban 的契合**:脚本无法写文件,图必须 `fig.to_dict()`/`to_json()` 纯内存序列化经 stdout 出来——这与 D3 选 plotly 的理由相互印证。

**新增硬化项**(实施期落):
- stdout 大小护栏:SkillExecutor 现仅截 stderr(2048B),stdout 无上限。子进程受 256MB RLIMIT 间接约束,但应加显式 stdout 上限,超限→缓存键 + 如实上报(不静默截断,守终止闸诚实原则)
- 成本:每次执行计入 turn 预算闸(token + ¥);执行耗时计入步数

## 7. 前端渲染

**已核实**现有 ECharts 链路:`ChartSpecRenderer.tsx` = `ReactECharts option={spec.option} height=280`,判 `spec.type==='echarts'`。新增物照搬此模式:

- 新增 `react-plotly.js` + `plotly.js` 依赖
- 新增 `PlotlySpecRenderer.tsx`(`<Plot data layout />`,判 `spec.type==='plotly'`,失败兜底同 ECharts 的 dashed-border 提示)
- 新增 SSE `chart` 事件类型(`types/chat.ts` 事件枚举 + `useChatSSE` 消费),携带 `chart_id` + figure JSON
- chat 消息流就近渲染;研报详情页(`ReportDetailModal`)同一渲染器复用
- 主题:沙箱里预置项目主题(配色/中文字体默认),保证「精美」下限不靠 LLM 每次手调

## 8. 错误处理与测试

### 8.1 错误处理(复用现有模式)
- 工具内异常 → ToolHub `_guidance_error` 指导性格式(参数校验/超时/执行失败已有映射)
- 执行失败回喂结构化:`{stderr, exit_code, error_kind}`(SkillExecutor 已产 `SkillExecutionError` 枚举:`safety_scan_rejected`/`timeout`/`non_zero_exit`/`stdout_invalid_json`)
- 自纠回路:chatloop while 循环天然承载,LLM 看到 stderr 可改代码重试;烧签名机制兜底防打转

### 8.2 测试策略(分层,沿用项目 L0/L1/L2 约定)
- **L0 executor**:`execute_source` 新入口单测——内联源码安全扫描通过/拒绝、超时、OOM、stdout 非 JSON、plotly 图序列化往返(SkillExecutor 已有 25+ 测试做底)
- **L0 工具**:`CodeInterpreterTool` 参数校验、出参结构、`figures` 透传
- **L0 loop 后处理**:figures→cache+chart 事件+摘要的纯函数验证(不灌上下文)
- **沙箱逃逸**:扩 `test_skill_sandbox_escape_attempts`——内联源码版的 `open`/`socket`/`import` 绕过企图
- **前端**:`PlotlySpecRenderer` 渲染 + 非法 spec 兜底
- **eval 金标准**:≥3 条该调 `run_python` 的 query(画趋势图/算指标对比)+ 近似负例(纯数据查询不该调),进工具选择专项 eval

## 9. 范围外 / follow-up

本 spec **只做解释器**。以下是已识别但刻意不在本期做的(对齐克制默认 + 留口子):

| 项 | 状态 | 说明 |
|---|---|---|
| `get_portfolio_positions` 工具 | follow-up | chat agent 现无持仓查询工具;接了「画我持仓行业分布」才端到端跑通 |
| `get_daily_series` 时间序列工具 | follow-up | 接了「算两只股票相关性」才有时序输入 |
| `get_stock_industry` 行业映射 | follow-up | 行业分布饼图需要 ts_code→行业 |
| `DockerExecutorBackend` | v1.x 口子 | 接口已留,真要更强隔离再实装 |
| 会话内有状态 kernel | 不做 | 无状态单发已满足;有状态是另一个量级的工程 |
| `/python ...` slash 强制调用 | 可选 | 现有 forced_tool_router 分支可承载,按需开 |

**本期能端到端跑通的示例**(数据来自现有工具):财报近五年营收/利润趋势图(`get_financial_statements` → pandas → 折线)、多股估值指标对比图(`compare_stocks`/`get_market_indicators` → 柱状/雷达)。需要持仓或日线时序的示例,待对应数据工具 follow-up 后才通。

## 10. 风险与留口子小结

- **风险:AST 黑名单可被理论绕过**——诚实标注的已知边界(不是正向白名单)。缓解:rlimit+断网+workdir+env 白名单多层兜底;DockerBackend 口子留给「真要更强隔离」。这恰是面试可讲的「分层防御 + 清醒的残余风险」叙事。
- **风险:plotly 装错 venv 则脚本 import 失败**——`import-chain-with-smoke-test` 约定:实施期先 `python -c "import plotly"` 在 fria-venv 实测。
- **留口子:ExecutorBackend 接口**——v1.0 SkillExecutorBackend,v1.x DockerExecutorBackend 直接换实现不动工具层。
- **留口子:figures 是数组**——天然支持一次执行出多张图;ToolResultCache 承载多轮中间结果取回。
