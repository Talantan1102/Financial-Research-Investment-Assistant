# 评估体系 · 研发看板模块设计 (v1)

> 2026-05-31 · 状态:已对齐设计，待实现 + dogfood

## 背景与目标

整个项目（金融研究助手）横跨知识库检索、对话 Agent、深度研报、跨会话记忆、持仓监控、估值交叉验证、多空辩论等子系统，各自有零散评估，但**缺统一视图**。论文（Agent Harness Engineering: A Survey, §8 Verification & Evaluation）强调"没有评估就没有优化"。

本模块是 **评估体系架构的设计画布**：先在研发看板上把"整个项目该怎么评估"画出来、通过对话不断完善，再据此补齐真实评估基建。它不是评估基建本身。

## 关键决策（已与用户对齐）

1. **形态 = 独立页 `/eval`**（非扩展已有 verification 维度，非新增第 8 维）。理由：评估体系横切全项目，比单个 ETCLOVG 维度大；看板已有 §6 verification 维度承载 eval 基建能力（EvalRunner / Judge / GoldenCase），本页是其上层的"全局覆盖视图"。
2. **组织 = 子系统 × 评估层级 矩阵**。空格子直接暴露缺口，最契合"看哪里没评估"。
3. **首版 = 扫码库预填真实现状 + 缺口**（非空脚手架）。用 workflow 7 个 agent 并行扫真实代码。

## 评估平台选型：LangSmith（分层接入，2026-05-31 决策）

**决策**：接入 LangSmith（托管云，LangGraph 原生），分层 build-vs-buy，**不替换**现有自建栈。

**现状**：项目 LangGraph 1.0 原生编排，但零 LangChain/LangSmith tracing；已有完整自建栈（`trace_service.py` + `eval_runner.py` + `judge.py` + `eval_recorder.py` + `eval_models.py`）。项目刻意框架轻量（只用 `langchain-text-splitters` 一个工具）。

**分层分工**：
- **组件级**（recall@k / nDCG 等离线 IR 指标）：保留自建（算法深度自证 + LangSmith 弱项）；可注册成 LangSmith custom evaluator 统一看板。
- **智能体级 + 系统级**：LangSmith（datasets + evaluators + 实验版本对比 + 回归）。
- **回归监控**：LangSmith CI 实验门禁 + 可选 online evaluator。

**接入 roadmap**：
- **P0 追踪 [✅ 已落地 + 验证 · 2026-06-01]**：`openai_client.py` 的 `build_llm_service_from_env()` 在 `LANGSMITH_TRACING=true` 时用 `wrap_openai` 包装 OpenAI client（关时零开销、锁在 DI 缝，不破坏 router 不 import openai）；LangGraph 图执行由 langchain-core 同一 env 自动上报。已验：真打 LLM → trace 落 LangSmith（project `frA-p0-smoke`，run 已 ingested）；守门单测 9 例 + ruff/mypy 绿；`.env.example` 记了 3 个变量。`langsmith 0.8.4` 随 langchain-core 传递依赖已在，**零新依赖**。
- **P1 数据集**：现有 golden（记忆 ~50 / 监控 ~12 / 研报 backtest / chat）→ LangSmith datasets。SSOT：golden 真相留代码（可 git review），脚本单向 sync 到 LangSmith。
- **P2 evaluator**：`judge.py` 包成 LangSmith evaluator；离线指标注册 custom evaluator；`evaluate()` 跑 V0-V3 ablation 版本对比。
- **P3 回归 + 在线**：CI 跑 LangSmith 实验做分数门禁；可选 online evaluator 抓生产反馈。

**TraceService 关系（SSOT，别莽拆）**：短期并存 —— LangSmith = 调试/实验 UI，TraceService = 自有结构化审计（成本/quota/自定义指标）；中期再评估瘦身，把通用 trace 交给 LangSmith。

**数据隐私**：LangSmith 云会收 trace（含 prompt 里的财务数据/key）；本项目演示数据可接受，已知悉。需自托管再评估企业版。

**在矩阵里怎么体现**：matrix 扫的是"现状"（全自建/缺口）。LangSmith 落地后，「智能体级/系统级/回归」三列里计划用平台填的格子标 `LangSmith` chip，与「自建」chip 区分；组件级恒为「自建」。

## 评估层级（矩阵的列，4）

| id | 名称 | 含义 |
|----|------|------|
| `component` | 组件级 | 单元级：切块/向量/检索/单工具正确性的离线指标（recall@k, nDCG, precision） |
| `agent` | 智能体级 | 单 agent 输出正确性：LLM 评判 / golden case |
| `system` | 系统级 | 端到端任务成功率：e2e golden / 回测 / 差分对照 |
| `regression` | 回归监控 | 回归套件 / 在线监控 / 鲁棒性（混沌·投毒·漂移） |

## 子系统（矩阵的行，7）

知识库检索 / 对话 Agent / 深度研报 / 跨会话记忆 / 持仓监控 / 估值交叉验证 / 多空辩论。

（后续可增行：工具层、记忆-KB 路由等；增列：成本/延迟评估。）

## 格子 schema

- `status`: `covered`（●有）| `partial`（◐部分）| `gap`（○缺口）
- `methods`: 方法 tag 列表（golden / LLM-judge / cassette / 离线指标 / 回测 / 差分 / 混沌 / 投毒 …）
- `evidence`: 真实代码/测试路径（调研阶段实际验证存在的）
- `gap`: 缺口说明（partial/gap 必填）

## 数据驱动 + 迭代闭环（核心）

矩阵唯一真相（SSOT）= `dashboard/config/eval_system.yaml`。迭代闭环：对话中调整方向 → 改 yaml → 刷新 `/eval` → 截图给用户 → 继续完善。页面纯渲染，不写回 yaml。这就是"在看板上把架构通过交流完善"的载体。

## 页面与交互

- `/eval` 独立页 + 顶栏「评估体系」入口（仿 `/story`）。
- 矩阵 grid：状态点 + 方法 chip；格子点击 → htmx `hx-get` 到 `/eval/cell/{sub}/{layer}`，展开详情到矩阵下方 `#eval-detail` 面板（沿用看板 cap chip 展开交互）。
- 顶部 summary（覆盖率 N% · X 有 / Y 部分 / Z 缺口）+ legend。
- 底部「评估底座」note 链到 `/m/verification`（§6）。

## 文件清单

- `dashboard/config/eval_system.yaml`（数据 / SSOT）
- `dashboard/derive/eval_matrix.py`（加载 + 校验 + summary 统计）
- `dashboard/templates/eval.html` + `_eval_cell_detail.html`
- `dashboard/server.py`（+2 route：`/eval`、`/eval/cell/{sub}/{layer}`）
- `dashboard/templates/_board_nav.html`（+nav item）
- `dashboard/static/style.css`（+`.eval-*` 样式，复用现有 token）
- `dashboard/tests/`（eval_matrix 单测 + TestClient 集成测试）

## 视觉

沿用 iOS Calm Minimal：复用现有 CSS 变量（`--accent` / `--lit` / `--wip` / `--todo` / `--dim-*`），**零新字体、零新依赖**。

## 非目标（YAGNI，v1 不做）

- 页面内编辑（靠改 yaml）
- 接 DB（纯 config 驱动）
- 跑真实 eval / 算真实指标（本页是架构视图；真实评估基建是后续按这张图补齐的工作）

## 实现方式

workflow 三段：① 7 agent 并行扫各子系统真实评估现状 + 缺口（结构化输出）→ ② 1 agent 汇总成 yaml + 建 route/template/css/nav/测试，自检 pytest+mypy+ruff → ③ 人工用 Playwright 鼠标键盘实测。
