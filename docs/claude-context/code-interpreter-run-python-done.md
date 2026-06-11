---
title: run_python 代码解释器工具 ship
type: project
date: 2026-06-11
---

# 代码解释器工具 run_python(2026-06-11 ship)

**结论**:chat agent 加 `run_python`(延迟组工具)—— LLM 当场写 Python,经复用的
SkillExecutor 沙箱(新增 `execute_source` 内联源码入口)执行,产 plotly 交互图。图经
`chart` SSE 事件旁路渲染(前端 PlotlySpecRenderer + chart 消息),figures 在 loop 的
dispatch→apply_results 之间被剥离,绝不进 LLM 上下文。沙箱底座抽成 `ExecutorBackend`
接口,DockerExecutorBackend 留 v1.x 口。14 任务 TDD ship,后端 + 前端测试全绿。

## Why

- 破「计算进技能脚本(零名额)」旧决策:LLM 自主写代码 ≠ 跑预审脚本,语义不同,值
  一个延迟组工具名额(常驻 ~30 token)。代价是执行不可信代码 → AST 扫描吃重。
- 渲染没复用现成 ECharts chart_spec 链路:手搓 ECharts option 只能覆盖四类且非「分析
  代码」;plotly.express 才是真分析代码,且 `to_dict()` 纯内存绕开沙箱 open() ban。
- figures 走 chart 事件不走 message markdown:figure JSON 数 KB,进 message 会污染
  下一 turn 的 LLM 上下文(KV-cache 铁律),旁路事件最干净。

## How to apply

- 改执行后端找 `backend/app/skills/executor_backend.py`(接口)+ `skill_executor.py`
  的 `execute_source`;Docker 版只需新增 backend 实现,不动 `CodeInterpreterTool`。
- 加新「产图」工具:工具 output 放 `figures: [plotly_fig_dict]`,ToolLoop
  `_extract_and_emit_charts` 自动抽出发 chart 事件(约定即接线,无需改 loop)。

## 实施期两个非显然的坑(都被测试/冒烟抓出)

1. **前端不能用全量 `plotly.js`**:它拉 `mapbox-gl` 的 git 型 exotic subdep,pnpm v11
   `blockExoticSubdeps` 拒绝且该子依赖要连 GitHub(本网络不通);`auto-install-peers`
   默认开会自动拉这个 peer。解法:`plotly.js-dist-min` 预构建单包 + `react-plotly.js/factory`
   建 `Plot`(bundler 推荐做法),装包加 `--config.auto-install-peers=false`。
2. **沙箱里 numpy/plotly OOM**:OpenBLAS 默认按 CPU 核数起线程,每线程预留内存 arena,
   在 256MB `RLIMIT_AS` 下直接 "OpenBLAS error: Memory allocation still failed"。修法不是
   抬内存,而是 `_minimal_env` 注入 `OPENBLAS/OMP/MKL/NUMEXPR_NUM_THREADS=1`(单线程既
   守内存又确定性,对纯计算技能脚本无副作用)。e2e 真子进程测试抓出,mock 测试不可能复现。

## 端到端 verify(真浏览器跑全栈)抓出的两个坑——只有真跑才暴露

3. **deferred 组 = 工具不可用**:run_python 起初放 deferred 组,模型只看到 thin 条目
   (`thin_schema` 剥了参数 description),裸调时根本不知道"脚本须 print 一个含
   result/figures 的 JSON"→ 写出不符契约的代码(`stdout_invalid_json` + 幻觉一个
   `plotly.com` 图片链接 + "运行环境限制"道歉)。**教训:输出契约是用对工具的前提的工具
   不能放 deferred**。修法:升 core(契约随 code 参数 description 常驻可见),brief 保持
   ≤80 不塞契约。单测过了但 agent 实跑全错——LLM-judge 端到端跑不出这个。
4. **valtio 只读对象喂 plotly 会空图**:figure 经 chart 事件进 valtio store 变
   reactive/只读;plotly 绘制时就地 mutate(归一化 `line.color` 等)→ 抛
   `Cannot assign to read only property 'color'`,且被 react-plotly **静默吞掉**
   (无 console error)→ `.js-plotly-plot` 容器在但 0 子节点、不画。修法:
   `PlotlySpecRenderer` 用 `JSON.parse(JSON.stringify(figure))` 深拷成可变对象再交 plotly
   (`structuredClone` 拷不了 valtio proxy)。**单测 mock 了 plotly 永远抓不到——必须真浏览器跑**。

## 已知留口(follow-up)

- 图不跨 reload 持久化(reload 从 PG 拉消息无 chart);持仓/日线/行业数据工具未接
  (部分示例端到端不通,见 spec § 9);DockerExecutorBackend;会话内有状态 kernel。
- 沙箱 AST 黑名单残余口子(spec § 10 已标注可被绕过):review 已补 `os.popen`/`os.fdopen`
  封堵任意 shell 执行;`pathlib.Path(...).read_text()` 这类文件读仍可绕过(现有 AST
  resolver 不解析"Call 结果上的方法调用")—— 单用户作品 + 断网兜底下风险低,留作硬化
  follow-up(要么扩 resolver,要么 ban `pathlib` import)。

相关:[[chat-loop-redesign-done]] [[v0.9-skill-loader-l1-l2-l3a-landed]] [[optional-extras-for-heavy-deps]]
