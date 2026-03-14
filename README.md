# 金融研投助手

基于 AI 的智能金融研究分析系统，提供深度研究、市场数据分析、财务分析和风险评估等功能。

## 核心功能

| 功能模块 | 说明 |
|---------|------|
| **深度研究 (DeepResearch)** | 多 Agent 协作的自动化研究报告生成 |
| **市场数据 (MarketData)** | 股票行情、历史数据、资金流向等实时数据 |
| **财务分析 (FinancialAnalysis)** | 财报查询、财务指标计算、财务对比分析 |
| **风险评估 (RiskAssessment)** | 单资产风险指标、投资组合风险评估 |
| **智能对话 (MCP Chat)** | 基于 MCP 协议的自然语言交互 |

## 系统架构

```
用户提问
  ↓
MCPChatService（三轮编排）
  ├─ Round 1：LLM 选择 Skill
  ├─ Round 2：LLM 调用具体工具
  └─ Round 3：LLM 生成最终回答
  ↓
返回答案
```

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| LLM | 阿里云百炼 (Qwen) | 国内合规、成本可控 |
| 框架 | LangGraph + MCP | 多智能体协作、工具调用协议 |
| 数据 | Tushare API | A 股金融数据 |
| 向量库 | Milvus | 高性能向量检索 |
| 数据库 | PostgreSQL + Redis | 关系数据 + 缓存 |
| 后端 | FastAPI | 异步 API 框架 |
| 前端 | React + Vite | 现代化前端 |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- Docker 20.0+（可选，用于运行基础服务）

### 1. 克隆仓库

```bash
git clone <repository-url>
cd financial-research-assistant
```

### 2. 配置环境变量

```bash
cd backend
cp .env.example .env
```

编辑 `.env` 文件，填入以下必需的 API Key：

```bash
# 阿里云百炼（必需）
DASHSCOPE_API_KEY=your_dashscope_api_key

# Tushare（必需）
TUSHARE_API_TOKEN=your_tushare_token
TUSHARE_API_URL=https://api.tushare.pro  # 可选，自定义代理地址
```

### 3. 安装后端依赖

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. 启动后端服务

```bash
python app/app_main.py
```

后端服务默认运行在 http://localhost:8000

### 5. 安装前端依赖（可选）

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 http://localhost:5173

## 使用示例

### 方式 1：通过 API 调用

```bash
curl -X POST http://localhost:8000/chat/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "question": "分析一下贵州茅台的投资价值",
    "model": "qwen-max"
  }'
```

### 方式 2：Python 代码调用

```python
from app.service.mcp_chat_service import MCPChatService

async def example():
    async with MCPChatService(model="qwen-max") as service:
        answer = await service.chat("查一下茅台近期的股市表现")
        print(answer)
```

### 方式 3：深度研究报告

```bash
curl -X POST http://localhost:8000/research/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "中国新能源汽车行业深度分析"
  }'
```

## 项目结构

```
financial-research-assistant/
├── backend/                    # 后端代码
│   ├── app/
│   │   ├── mcp_server/        # MCP Server（技能市场）
│   │   │   ├── skills/        # Skill 实现
│   │   │   │   ├── market_data.py       # 市场数据技能
│   │   │   │   ├── financial_analysis.py # 财务分析技能
│   │   │   │   ├── risk_assessment.py    # 风险评估技能
│   │   │   │   └── deep_research.py      # 深度研究技能
│   │   │   └── server.py      # MCP Server 入口
│   │   ├── mcp_client/        # MCP Client 实现
│   │   ├── service/           # 业务逻辑服务
│   │   ├── router/            # API 路由
│   │   └── data/              # 数据访问层
│   └── tests/                 # 测试目录
│       ├── integration/       # 集成测试
│       └── e2e/              # 端到端测试
├── frontend/                  # React 前端
├── docs/                      # 项目文档
│   ├── 00-项目指南/           # 快速开始、文档索引
│   ├── 01-架构设计/           # 系统架构、MCP 集成方案
│   ├── 02-开发指南/           # 能力边界、工具调用评估
│   ├── 03-API文档/            # 接口文档
│   ├── 04-功能模块/           # 各功能模块详细说明
│   ├── 05-测试文档/           # 测试规范与指南
│   ├── 06-训练计划/           # 模型训练文档
│   └── 07-后端模块/           # 后端代码架构
└── README.md
```

## 文档导航

| 文档 | 说明 |
|------|------|
| [文档首页](docs/00-项目指南/文档首页.md) | 项目介绍与快速开始 |
| [架构概述](docs/01-架构设计/架构概述.md) | 系统架构总览 |
| [MCP 集成方案](docs/01-架构设计/mcp集成方案.md) | MCP 协议集成详细方案 |
| [测试指南](docs/05-测试文档/测试指南.md) | 测试规范与指南 |

完整文档索引请查看 [文档索引](docs/00-项目指南/文档索引.md)。

## MCP Skills 工具列表

| Skill | 工具数量 | 功能概述 |
|-------|---------|---------|
| market_data | 8 | 实时行情、历史数据、资金流向、涨跌停等 |
| financial_analysis | 3 | 财报查询、财务指标、财务对比 |
| risk_assessment | 3 | 风险指标计算、投资组合风险评估 |
| deep_research | 7 | 研究规划、搜索、分析、撰写、评审 |

## 运行测试

```bash
# 集成测试
python -m pytest backend/tests/integration/ -v

# 端到端测试
python -m pytest backend/tests/e2e/ -v
```

## 环境变量说明

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `DASHSCOPE_API_KEY` | ✅ | 阿里云百炼 API Key |
| `TUSHARE_API_TOKEN` | ✅ | Tushare 数据接口 Token |
| `TUSHARE_API_URL` | ❌ | Tushare 自定义代理地址 |
| `REDIS_HOST` | ❌ | Redis 主机（默认 localhost） |
| `DATABASE_URL` | ❌ | PostgreSQL 连接串 |

## 许可证

MIT License

## 免责声明

本系统提供的所有数据和分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。
