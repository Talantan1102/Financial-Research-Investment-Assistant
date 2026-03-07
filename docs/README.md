# 金融研投助手

一个基于 AI 的深度研究助手，支持智能搜索、知识图谱、数据可视化等功能。

## 📁 文档索引

| 文档 | 说明 |
|------|------|
| [架构设计](./architecture/README.md) | 系统架构与核心设计 |
| [MCP 集成方案](./architecture/mcp-integration.md) | MCP 协议集成详细方案 |
| [MCP Server API](./api/mcp-server.md) | MCP Server 接口文档 |
| [MCP Client API](./api/mcp-client.md) | MCP Client 接口文档 |
| [测试指南](./testing/test-guide.md) | 测试规范与指南 |

## 🚀 快速开始

### 环境要求

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Docker | 20.0+ | 运行所有基础服务 |
| Python | 3.10+ | 后端服务 |
| Node.js | 18+ | 前端构建 |

### 启动服务

```bash
# 启动所有基础服务
chmod +x start-services.sh
./start-services.sh start

# 查看状态
./start-services.sh status
```

### 配置环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

**必填 API Key：**
- `DASHSCOPE_API_KEY` - 阿里云百炼
- `BOCHA_API_KEY` - 博查搜索

### 启动后端

```bash
cd backend
conda create -n deepresearch python=3.10
conda activate deepresearch
pip install -r requirements.txt
python app/app_main.py
```

### 启动前端

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

## 📂 项目结构

```
financial-research-assistant/
├── backend/
│   ├── app/
│   │   ├── mcp_server/     # MCP Server
│   │   ├── mcp_client/     # MCP Client
│   │   ├── service/        # 业务逻辑
│   │   └── router/         # API 路由
│   └── tests/              # 测试目录
├── frontend/               # React 前端
├── docs/                   # 文档目录
└── docker-compose.yml
```

## 🔧 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| LLM | 阿里云百炼 (Qwen) | 国内合规、成本可控 |
| 框架 | LangGraph + ReAct | 多智能体协作 |
| 向量库 | Milvus | 高性能向量检索 |
| 数据库 | PostgreSQL | 关系数据存储 |
| 后端 | FastAPI | 异步 API 框架 |
| 前端 | React + Vite | 现代化前端 |

## 📚 更多文档

- [API 文档](http://localhost:8000/docs) - 启动后端后访问
- [项目原 README](../READMED.md) - 完整项目文档

## 📄 许可证

MIT License
