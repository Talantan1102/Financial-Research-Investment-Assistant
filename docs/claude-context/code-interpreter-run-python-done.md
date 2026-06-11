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

## 已知留口(follow-up)

- 图不跨 reload 持久化(reload 从 PG 拉消息无 chart);持仓/日线/行业数据工具未接
  (部分示例端到端不通,见 spec § 9);DockerExecutorBackend;会话内有状态 kernel。

相关:[[chat-loop-redesign-done]] [[v0.9-skill-loader-l1-l2-l3a-landed]] [[optional-extras-for-heavy-deps]]
