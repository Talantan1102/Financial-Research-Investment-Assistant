# MCP Server 模块

Financial Research Assistant 的 MCP (Model Context Protocol) Server 实现。

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              FinancialMCPServer                       │  │
│  │                 (server.py)                           │  │
│  └───────────────────────────────────────────────────────┘  │
│                         │                                   │
│         ┌───────────────┼───────────────┐                   │
│         ▼               ▼               ▼                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │
│  │ MarketData  │ │ DeepResearch│ │  Other      │            │
│  │   Skill     │ │   Skill     │ │  Skills     │            │
│  └─────────────┘ └─────────────┘ └─────────────┘            │
│         │               │                                   │
│         └───────────────┼───────────────┐                   │
│                         ▼               ▼                   │
│               ┌─────────────────┐ ┌─────────────┐           │
│               │  Tushare Client │ │  Other      │           │
│               │  (Data Source)  │ │  Sources    │           │
│               └─────────────────┘ └─────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
backend/app/mcp_server/
├── __init__.py              # 模块入口
├── server.py                # MCP Server主入口
├── config.py                # 配置管理
├── test_server.py           # 测试脚本
└── skills/
    ├── __init__.py          # Skills包入口
    ├── base.py              # Skill基类
    └── market_data.py       # MarketData Skill

backend/app/data/
├── __init__.py              # 数据源包入口
└── tushare_client.py        # Tushare API客户端
```

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# Tushare API Token（用于股票数据）
export TUSHARE_API_TOKEN="your_tushare_api_token"

# 可选配置
export MCP_LOG_LEVEL="INFO"
export TUSHARE_CACHE_TTL="300"  # 缓存时间（秒）
```

### 3. 测试MCP Server

```bash
# 测试Server初始化
cd backend/app
python -m mcp_server.test_server

# 仅测试Tushare客户端
python -m mcp_server.test_server --tushare-only
```

### 4. 启动MCP Server

```bash
cd backend/app
python -m mcp_server.server
```

## 开发指南

### 创建新的Skill

继承 `Skill` 基类并实现必要的方法：

```python
from app.mcp_server.skills.base import Skill, tool

class MySkill(Skill):
    def __init__(self):
        super().__init__(
            name="my_skill",
            description="我的自定义Skill"
        )
    
    async def initialize(self) -> bool:
        # 初始化资源
        return True
    
    async def cleanup(self) -> None:
        # 清理资源
        pass
    
    @tool(name="my_tool", description="工具描述")
    async def my_tool(self, param: str) -> dict:
        # 实现工具逻辑
        return {"result": "success"}
```

### 注册Skill

在 `server.py` 的 `_register_skills` 方法中注册：

```python
async def _register_skills(self) -> None:
    self.register_skill(MySkill())
```

## 可用工具

### MarketData Skill

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `get_quote` | 获取股票实时行情 | `symbol`: 股票代码, `include_details`: 是否包含详情 |
| `search_stock` | 搜索股票 | `keyword`: 关键词, `limit`: 结果数量 |
| `get_market_overview` | 获取市场概况 | `market`: 市场类型(sh/sz/all) |
| `batch_get_quotes` | 批量获取行情 | `symbols`: 股票代码列表 |

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `TUSHARE_API_TOKEN` | Tushare API Token | - |
| `TUSHARE_CACHE_TTL` | 缓存时间（秒） | 300 |
| `TUSHARE_MAX_RETRIES` | 最大重试次数 | 3 |
| `MCP_LOG_LEVEL` | 日志级别 | INFO |
| `MCP_TRANSPORT` | 传输模式 | stdio |

## 测试

```bash
# 运行所有测试
cd backend/app
python -m mcp_server.test_server

# 测试特定功能
python -c "
from app.data.tushare_client import get_tushare_client
client = get_tushare_client()
result = client.get_quote('600519')
print(result)
"
```

## 与现有代码的关系

- **保留现有代码**：原有的 `stock_service.py` 等文件保持不变
- **新增MCP层**：MCP Server作为新的接入层，复用现有业务逻辑
- **渐进式迁移**：可以逐步将现有服务改造为MCP Skills

## 后续开发计划

- [ ] DeepResearch Skill（复用 deep_research_v2/）
- [ ] WebSearch Skill
- [ ] Text2SQL Skill
- [ ] KnowledgeBase Skill
- [ ] SSE传输支持
