# AlphaScout · 通用金融 Agent 平台

> 把「多智能体编排 + 上下文工程 + 结构化输出 + 评估可观测」在一个真实的 A 股研投场景里完整跑通的 LLM 应用作品。
>
> 你用大白话提问 —— agent 自己规划、调真实行情/财务数据、现写 Python 画图、交叉验证、给出可追溯到每一个数字的判断。

<p>
<img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white">
<img alt="React 19" src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black">
<img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white">
<img alt="LangGraph" src="https://img.shields.io/badge/LangGraph-1.x-1C3C3C">
<img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white">
<img alt="Milvus" src="https://img.shields.io/badge/Milvus-向量库-00A1EA">
<img alt="License MIT" src="https://img.shields.io/badge/License-MIT-green">
</p>

**导航**　·　[这是什么](#这是什么)　·　[界面预览](#界面预览)　·　[快速开始](#快速开始)　·　[技术要点](#技术要点粗粒度)　·　[更大的愿景](#更大的愿景)　·　[项目结构](#项目结构)　·　[测试与质量](#测试与质量)

---

## 这是什么

**AlphaScout** 是一个面向中国 A 股研究场景的 AI 研投助手。它的目标不是再做一个「自然语言查数据库」的接口，而是把一个**资深研究员的完整工作流**——从查行情、读三表、算估值、追资金、对比行业，到写出有数据支撑、可逐条追溯的研究判断——交给一个能自主规划、自主调工具、自我纠错的 agent 来完成。

它同时是一个 **LLM 应用的工程深度作品**：在一个场景里把当下最关键的几件工程问题都认真撞了一遍——多步工具调用如何不失控、金融幻觉如何防住、长期记忆如何跨会话、质量如何可评估可观测。

| 你能用它做什么 | 入口 |
|---|---|
| **对话研投** — 用大白话问，agent 自己取数、画图、给判断 | 对话页 |
| **深度尽调** — 一键生成一份多智能体协作的投资标的尽调报告 | 研报页 |
| **持仓总览** — 今天涨跌「怎么来的」，用大白话归因到每只股票 | 持仓页 |
| **持仓预警** — 盘中自动扫描异常信号，红色告警触发深度调查 + 邮件 | 监控页 |
| **跨会话记忆** — 跨对话记住你是谁、偏好什么、聊过什么 | 记忆页 |
| **知识库问答** — 研报 / 财报 / 政策切块入库，对话里随取随用 | 知识库页 |
| **Harness Board** — 把这个项目本身按 7 个工程维度逐条拆给你看的研发看板 | 独立看板 |

---

## 界面预览

**对话研投 —— 一句话提问，agent 自己规划 → 调真实数据 → 现写 Python 画图 → 给判断**

![对话研投 + 代码解释器画图](docs/screenshots/02-chat-chart.png)

**结构化分析 —— 每一个数字都来自工具调用，可追溯、可复核**

![结构化估值分析报告](docs/screenshots/01-chat-analysis.png)

**持仓总览 —— 今天这账「怎么来的」，用大白话归因 + 资产分布一图看清**

![持仓总览与归因](docs/screenshots/06-portfolio.png)

**Harness Board —— 把这个项目按 7 个工程维度逐条拆解、追踪、评估的研发看板**

| 工程维度全景图 | 评估体系看板 |
|---|---|
| ![Harness Board 关系图](docs/screenshots/08-board-topology.png) | ![评估体系](docs/screenshots/11-board-eval.png) |

---

## 快速开始

> 下面命令默认终端在**项目根目录**。默认全部走 mock，**不烧钱**；想接真数据时改一个环境变量即可。

### 环境要求

- Python 3.11+
- Node.js 20+（前端）
- [uv](https://docs.astral.sh/uv/) 包管理器：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- （可选）Docker Desktop —— 只有用到 PostgreSQL / Redis / Milvus 时才需要

### 安装

```bash
# 后端依赖（含开发工具 + 知识库 feature）
uv sync --extra dev --extra kb

# 配置环境变量：填入 LLM key、（可选）真数据 token
cp backend/.env.example backend/.env   # 然后编辑

# 前端依赖
cd frontend && npm install && cd ..
```

> 磁盘紧张、不需要知识库检索时，可用精简安装 `uv sync --extra dev`（知识库的向量检索/入库会缺重型 ML 依赖，其余功能照常）。

### 启动

```bash
# 终端 1 —— 后端（端口 8000，API 文档在 /docs）
uv run poe serve

# 终端 2 —— 前端（端口 5173）
cd frontend && npm run dev
```

打开 <http://localhost:5173> 就能进对话页。试着问一句：

> **「贵州茅台现在估值贵不贵？看下最新股价、PE、PB，结合白酒行业给个判断。」**

agent 会自己去查交易日历、拉行情和估值指标、写一段 Python 算 PE 历史分位并画图，最后给出一份可追溯的判断——就是上面预览图里的样子。

### 接真实数据（可选）

默认 `*_MODE=mock`。把对应开关改成 `real` 并填 key，即可接入真实数据源：

| 环境变量 | 作用 |
|---|---|
| `DASHSCOPE_API_KEY` | LLM key（阿里百炼 / 任意 OpenAI 兼容端点）—— **对话与研报必需** |
| `TUSHARE_MODE=real` + `TUSHARE_TOKEN` | 真实 A 股行情 / 财务数据 |
| `KB_MODE=real` | 知识库向量检索（需启动 Milvus） |
| `BOCHA_MODE=real` + `BOCHA_API_KEY` | 真实 Web 搜索 |
| `EMAIL_MODE=real` + SMTP 配置 | 持仓预警邮件通知 |

完整列表见 `backend/.env.example`。

### 进阶组件（按需启动）

```bash
docker compose up -d postgres redis     # 会话持久化 / 跨会话记忆 / 监控调度
./start-services.sh start                # Milvus / Redis（知识库、记忆向量检索）
make worker && make beat                 # 持仓监控的异步任务 + 定时调度（Celery）
make board                               # 启动 Harness Board 研发看板（端口 8910）
```

---

## 技术要点（粗粒度）

### 架构总览

```
            React 前端（对话优先 · 流式 SSE · 行情卡 / 工具卡 / 交互图表）
                                  │
                          FastAPI（async）
                                  │
   ┌──────────────┬───────────────┼───────────────┬──────────────┐
   │  对话引擎     │   深度尽调     │   持仓监控     │  跨会话记忆   │ 知识库
   │ (裸 while     │ (多智能体      │ (信号规则 +    │ (分层记忆 +   │ (按类型
   │  循环 + 原生   │  + 审查回炉)   │  深度调查      │  双时间线      │  切块 +
   │  function     │               │  + 邮件)       │  知识图谱)     │  向量检索)
   │  calling)     │               │               │               │
   └──────────────┴───────────────┴───────────────┴──────────────┘
                                  │
       横切服务（统一「接口 + 真实现 / Mock 实现 + 工厂」，靠环境变量切换）
       LLM · Tushare 行情财务 · Web 搜索 · 向量库 · Trace 追踪 · 评估 · 成本预算
                                  │
       PostgreSQL（业务 + 会话 + 图谱）   Redis（缓存 / 取消信号 / Celery）   Milvus（向量）
```

### 几个值得一说的设计

| 技术点 | 一句话说清 |
|---|---|
| **裸循环对话引擎** | 不堆重框架：一个 Python `while` 循环 + 模型原生 function calling 跑多步工具调用。**四道终止闸**防止 agent 失控空转；上下文按区域切分以贴合 KV-cache；工具**渐进披露**（先给类别再展开具体工具）省掉大量 token。 |
| **代码解释器** | agent 可以现写 Python 丢进沙箱执行，用 Plotly 画交互图。图表走独立通道渲染、不进上下文（省 token）。预览里那张茅台 PE 区间图就是这么来的。 |
| **多智能体深度尽调** | 规划 → 取数 → 分析 → 写作 → 审查 五个角色分工；审查官按 7 个维度打分，不合格**自动打回重做**（最多 2 轮硬上限）。规划阶段用「约束式路由」——模型只能在几个预置方案里四选一，保证结果可控、可写测试。 |
| **金融幻觉防御** | 财务数据必须来自工具调用，禁止模型自行编造；写作强制标注 `[来源: 工具名]`；估值、建仓比例等数字由**确定性 Python 函数**算，模型只负责叙述。错一个 PE 在金融里是会出事的，所以这条是底线。 |
| **跨会话长期记忆** | 借鉴 MemGPT 的分层记忆 + Zep 的双时间线知识图谱：跨对话记住你是谁、风险偏好、聊过什么；读取用「图谱 + 向量 + 时间感知排序」三路混合召回。 |
| **持仓监控** | 5 条信号规则盘中并发扫描（财务恶化 / 现金流 / 股东户数骤降 / 负面公告 / 异动），红色告警触发多智能体深度调查并发邮件；外加成本、并发、去重、事后核账四道闸。 |
| **真假可切换** | 所有外部依赖都是「接口 + 真实现 / Mock 实现 + 工厂」模式，一个环境变量切换。CI 全程 mock 离线、零成本；本地按需接真。 |
| **评估可观测** | 分层测试（单元 / 集成 / 录像回放 / 真模型）+ LLM 当裁判 + trace 查看器；外加一个 **Harness Board** 把整个项目按 ETCLOVG 七个工程维度（执行 / 工具 / 上下文 / 生命周期 / 可观测 / 验证 / 治理）逐条拆解、追踪完成度、做离线评估。 |
| **工程纪律** | 核心模块 `mypy --strict` 全过、`ruff` 清洁；外部调用录成「录像带」回放、录制时自动脱敏；fix 类提交强制标注「问题出在哪一层」便于溯源。 |

### 技术栈

| 层 | 选型 |
|---|---|
| LLM | OpenAI 兼容协议（默认阿里云百炼 Qwen / DeepSeek，可切任意兼容端点） |
| 编排 | 裸 Python 对话循环（chatloop）+ LangGraph 1.x（深度尽调子图、检查点） |
| 数据 | Tushare Pro（行情 / 三表 / 估值 / 资金信号）+ Bocha Web 搜索 + Milvus 向量库 |
| 异步 | Celery + Redis（持仓监控检测 / 详情卡生成 / 定时调度） |
| 持久化 | PostgreSQL（业务 / 会话 / 知识图谱）+ Redis + Milvus |
| 后端 | FastAPI + httpx async |
| 前端 | React 19 + Vite + Ant Design 5 + TypeScript strict + valtio |
| 质量 | pytest + pytest-recording(VCR) + mypy strict + ruff + uv |

---

## 更大的愿景

AlphaScout 这个仓库是整个构想里的**应用层**。它本身已经能独立跑通，但它背后还有一个更大的「数据飞轮」设想：

> **用应用本身生产训练数据，再用训练出的模型反哺应用。**
>
> 应用既是产品，也是 Sandbox 环境：把多步工具调用的白盒轨迹沉淀成训练数据 → 三阶段合成放大 → 用 GRPO 训练金融场景特化的工具调用模型 → 部署回应用提升能力。其中「合成 + 训练」部分在独立仓库，本仓库不含。

完整叙事（业务背景、三大模块、面试向 STAR 复盘）见 [`docs/project-story.md`](docs/project-story.md)。

---

## 项目结构

```
.
├── backend/
│   ├── app/
│   │   ├── chatloop/        # 裸循环对话引擎（工具调用 / 终止闸 / 上下文分区）
│   │   ├── agents/          # 多智能体深度尽调 + 估值交叉验证 + 多空辩论
│   │   ├── orchestration/   # LangGraph 装配（尽调子图 / 检查点）
│   │   ├── services/        # 横切服务（接口 + 真/Mock + 工厂）：LLM / Tushare / KB / 记忆 / 监控 / 评估
│   │   ├── router/          # FastAPI 路由（对话 / 研报 / 监控 / 记忆 / 持仓 / 知识库 / 认证）
│   │   └── app_main.py      # 入口 + lifespan
│   └── tests/               # 分层：unit / integration / e2e(录像) / eval(真模型)
├── frontend/                # React 前端（对话 / 研报 / 持仓 / 监控 / 记忆 / 知识库）
├── dashboard/               # Harness Board 研发看板（独立服务）
├── docs/                    # 设计文档 / 项目故事 / 截图
│   ├── superpowers/         # 每个版本的设计评审(spec) + 实施计划(plan)
│   └── claude-context/      # 长期工程上下文卡片
├── docker-compose.yml       # PostgreSQL / Redis / Milvus
└── Makefile                 # board / worker / beat 等
```

---

## 测试与质量

```bash
uv run poe test       # 单元 + 集成 + 录像回放（不含真模型，秒级，PR 必跑）
uv run poe lint       # ruff format check + ruff check + mypy strict
uv run poe eval       # golden case 评估
make board-test       # 研发看板测试套
```

| 层 | LLM | 速度 | 何时跑 |
|---|---|---|---|
| 单元 | 无 | <5s | 每次保存 |
| 集成 | mock（确定性） | <30s | 每个 PR |
| 录像回放 | cassette 回放 | <2min | 每个 PR |
| 真模型评估 | 真 API（烧钱） | 分钟级 | 手动 / nightly |

---

## 许可证

MIT License

## 免责声明

本系统提供的所有数据与分析**仅供学习研究参考，不构成任何投资建议**。本项目为个人技术作品，非持牌投资顾问。投资有风险，入市需谨慎。
