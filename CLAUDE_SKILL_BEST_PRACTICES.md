# Claude Skill & Tool 编写最佳实践学习文档

> 基于 Anthropic MCP 官方文档和 Claude Cookbook 的综合学习总结
> 学习日期: 2026-03-18

---

## 一、核心概念理解

### 1.1 什么是 MCP (Model Context Protocol)？

MCP 是 Anthropic 推出的**开源标准**，用于连接 AI 应用和外部系统。

**类比理解**: MCP 就像 AI 应用的 **USB-C 接口**
- USB-C: 标准化连接电子设备
- MCP: 标准化连接 AI 应用和外部数据源、工具、工作流

### 1.2 MCP 的核心组件

```
┌─────────────────────────────────────────────────────────────────┐
│                      MCP 架构概览                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌──────────────┐         MCP Protocol         ┌──────────────┐│
│   │   AI Client  │  ←────────────────────────→  │ MCP Server   ││
│   │  (Claude/    │                              │  (Skills &   ││
│   │   ChatGPT)   │                              │   Tools)     ││
│   └──────────────┘                              └──────────────┘│
│          │                                             │        │
│          │ 1. Discover (发现)                          │        │
│          │ 2. Invoke (调用)                            │        │
│          │ 3. Get Result (获取结果)                    │        │
│          │                                             │        │
│          ▼                                             ▼        │
│   ┌──────────────────────────────────────────────────────┐     │
│   │                   Data Sources                        │     │
│   │  • Files/Databases  • APIs  • Search Engines         │     │
│   └──────────────────────────────────────────────────────┘     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 三种核心交互模式

| 模式 | 控制方 | 用途 | 示例 |
|------|--------|------|------|
| **Tools** | Model-controlled (模型控制) | LLM 自动发现和调用 | 计算器、搜索、API 调用 |
| **Resources** | Application-driven (应用驱动) | 应用决定如何加载上下文 | 文件、数据库 schema |
| **Prompts** | User-controlled (用户控制) | 用户主动选择 | /命令、快捷指令 |

---

## 二、Tool 设计最佳实践

### 2.1 Tool 的核心原则

#### 原则 1: 单一职责 (Single Responsibility)

```python
# ❌ 不好的设计: 一个工具做太多事情
{
  "name": "process_data",
  "description": "Process any type of data",  # 太模糊
  "parameters": {
    "data": "...",  # 不知道应该传什么
    "type": "..."   # 类型太多
  }
}

# ✅ 好的设计: 每个工具只做一件事
{
  "name": "get_weather",
  "description": "Get current weather for a specific city",
  "parameters": {
    "city": {
      "type": "string",
      "description": "City name, e.g., 'Beijing' or 'New York'"
    }
  }
}
```

#### 原则 2: 自描述的命名

```python
# ❌ 不好的命名
{
  "name": "calc",           # 缩写不清晰
  "name": "get_data",       # 太泛化
  "name": "process"         # 不知道处理什么
}

# ✅ 好的命名
{
  "name": "calculate_mortgage_payment",  # 动词 + 具体对象
  "name": "search_github_repositories",   # 动作 + 范围 + 对象
  "name": "send_email_message"            # 动作 + 媒介 + 对象
}
```

#### 原则 3: 清晰的参数设计

```python
# 参数设计模板
{
  "name": "search_stock",
  "description": "Search stock information by symbol or company name",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": """
          Search query for stock lookup.
          Can be:
          - Stock symbol: '600519' or 'AAPL'
          - Company name: '贵州茅台' or 'Apple'
          Example: '600519' for Kweichow Moutai
        """
      },
      "market": {
        "type": "string",
        "description": "Stock market to search in",
        "enum": ["A-share", "US", "HK"],
        "default": "A-share"  # 合理默认值
      }
    },
    "required": ["query"]  # 明确必需参数
  }
}
```

### 2.2 Description 编写规范

#### 黄金法则: 描述要让 LLM 知道**什么时候**和**如何**使用

```python
# ❌ 差的描述
{
  "description": "Get data"  # 太简短，没有上下文
}

# ✅ 好的描述
{
  "description": """
  Get real-time stock quote for a given stock symbol.
  
  Use this when:
  - User asks about current stock price
  - User wants to know today's trading information
  - User asks about price changes or percentage gains/losses
  
  Returns:
  - Current price, open price, high/low prices
  - Trading volume and turnover
  - Price change amount and percentage
  """
}
```

#### Description 结构模板

```markdown
## Tool Description Template

[一句话功能描述]

Use this tool when:
- [场景 1]: [具体描述]
- [场景 2]: [具体描述]
- [场景 3]: [具体描述]

Parameters:
- [param_name]: [详细说明 + 格式 + 示例]

Returns:
- [字段 1]: [说明]
- [字段 2]: [说明]

Example usage:
- "查询贵州茅台股价" → search_stock(query="600519")
- "分析美股苹果走势" → search_stock(query="AAPL", market="US")
```

### 2.3 Schema 设计最佳实践

#### 完整的 Tool Schema 示例

```json
{
  "name": "get_weather",
  "title": "Weather Information Provider",
  "description": """
  Get current weather and forecast for a location.
  
  Use this when:
  - User asks about weather conditions
  - User wants to know temperature, humidity, or precipitation
  - User is planning travel and needs weather information
  
  Note: Only supports cities worldwide. Does not support weather by coordinates.
  """,
  "inputSchema": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string",
        "description": """
          City name for weather lookup.
          
          Format examples:
          - 'Beijing' (city name in English)
          - 'Shanghai, China' (city with country for disambiguation)
          - '北京市' (city name in Chinese)
          
          Invalid formats:
          - '39.9, 116.4' (coordinates not supported)
          - '10001' (zip codes not supported)
        """
      },
      "units": {
        "type": "string",
        "description": "Temperature units",
        "enum": ["celsius", "fahrenheit"],
        "default": "celsius"
      },
      "days": {
        "type": "integer",
        "description": "Number of forecast days (1-7)",
        "minimum": 1,
        "maximum": 7,
        "default": 1
      }
    },
    "required": ["location"]
  }
}
```

### 2.4 工具返回格式规范

#### 标准返回结构

```json
{
  "content": [
    {
      "type": "text",
      "text": "Current weather in Beijing: 25°C, sunny"
    }
  ],
  "isError": false
}
```

#### 错误处理

```json
{
  "content": [
    {
      "type": "text",
      "text": "Error: City 'Xyz123' not found. Please check the spelling or try a major city name."
    }
  ],
  "isError": true
}
```

---

## 三、Skill (资源) 设计最佳实践

### 3.1 Resource vs Tool 的区别

| 特性 | Tools | Resources |
|------|-------|-----------|
| **控制方** | Model-controlled | Application-driven |
| **用途** | 执行操作 | 提供上下文 |
| **调用方式** | LLM 自动决定 | 应用决定何时加载 |
| **示例** | 计算器、发送邮件 | 文件内容、数据库 schema |

### 3.2 Resource 设计原则

#### 原则 1: URI 设计要规范

```python
# ✅ 好的 URI 设计
{
  "uri": "file:///project/src/main.py",
  "name": "main.py",
  "mimeType": "text/x-python"
}

{
  "uri": "db://users/schema",
  "name": "User Table Schema",
  "mimeType": "application/json"
}
```

#### 原则 2: 使用 Annotations 提供元数据

```json
{
  "uri": "file:///project/README.md",
  "name": "README.md",
  "title": "Project Documentation",
  "mimeType": "text/markdown",
  "annotations": {
    "audience": ["user", "assistant"],
    "priority": 0.8,
    "lastModified": "2025-01-12T15:00:58Z"
  }
}
```

Annotations 含义:
- `audience`: 谁应该看到这个资源 (`user`, `assistant`)
- `priority`: 重要性 (0-1, 1 表示最重要)
- `lastModified`: 最后修改时间

### 3.3 Resource Templates (资源模板)

用于暴露参数化的资源:

```json
{
  "uriTemplate": "file:///{path}",
  "name": "Project Files",
  "description": "Access any file in the project directory",
  "mimeType": "application/octet-stream"
}
```

---

## 四、渐进式披露架构 (Progressive Disclosure)

### 4.1 什么是渐进式披露？

**核心思想**: 不要让 LLM 一次性看到所有工具，而是按需逐步发现。

```
┌─────────────────────────────────────────────────────────────────┐
│                   渐进式披露流程                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   传统方式 (45个工具同时暴露)        渐进式披露 (3个元工具)       │
│   ───────────────────────────        ─────────────────          │
│                                                                  │
│   LLM 看到:                         LLM 看到:                    │
│   ┌─────────────────────────┐       ┌─────────────────────────┐ │
│   │ get_quote               │       │ skill(name)             │ │
│   │ get_history             │       │ get_skill_tools(name)   │ │
│   │ search_stock            │       │ execute_skill_tool(...) │ │
│   │ get_financial_report    │       └─────────────────────────┘ │
│   │ ... (42 more)           │                ↓                  │
│   └─────────────────────────┘       Step 1: 加载 Skill 文档     │
│            ↓                                ↓                  │
│   "我该用哪个工具？"                Step 2: 获取工具列表        │
│   "参数是什么？"                           ↓                  │
│                                   Step 3: 执行具体工具          │
│                                                                  │
│   ❌ 选择困难，容易出错              ✅ 按需发现，调用准确        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 渐进式披露的三轮流程

#### Round 1: Skill Discovery (技能发现)

```python
# LLM 调用
skill(name="market_data")

# 返回: SKILL.md 文档
"""
---
name: market_data
description: 股票市场行情数据查询
---

## 概述
提供股票实时行情、历史K线等数据...

## 可用工具
- get_quote: 获取实时行情
- get_history: 获取历史数据
...
"""
```

#### Round 2: Tool Discovery (工具发现)

```python
# LLM 调用
get_skill_tools(name="market_data")

# 返回: JSON Schema 列表
[
  {
    "name": "get_quote",
    "description": "获取实时行情",
    "parameters": {...}
  },
  ...
]
```

#### Round 3: Tool Execution (工具执行)

```python
# LLM 调用
execute_skill_tool(
    skill_name="market_data",
    tool_name="get_quote",
    arguments={"symbol": "600519"}
)

# 返回: 实时行情数据
{"price": "1850.50", "pe": 28.74}
```

### 4.3 渐进式披露的优势

| 优势 | 说明 |
|------|------|
| **减少认知负担** | LLM 不需要在 45 个工具中选择 |
| **提高准确率** | 按需发现，参数信息清晰 |
| **降低错误率** | 统一调用入口，减少误用 |
| **可扩展性** | 新增工具不需要修改 LLM 提示 |

---

## 五、Prompt 设计最佳实践

### 5.1 Prompt 的角色

Prompts 是 **User-controlled** (用户控制) 的交互模式:

```
用户界面示例:
┌─────────────────────────────────────┐
│  /code_review    ← Prompt 作为命令   │
│  /explain_code                       │
│  /generate_tests                     │
└─────────────────────────────────────┘
```

### 5.2 Prompt 结构

```json
{
  "name": "code_review",
  "title": "Request Code Review",
  "description": "Asks the LLM to analyze code quality",
  "arguments": [
    {
      "name": "code",
      "description": "The code to review",
      "required": true
    },
    {
      "name": "language",
      "description": "Programming language",
      "required": false
    }
  ]
}
```

### 5.3 Prompt 返回的消息格式

```json
{
  "description": "Code review prompt",
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Please review this Python code:\ndef hello():\n    print('world')"
      }
    }
  ]
}
```

---

## 六、常见陷阱与解决方案

### 陷阱 1: Description 太简短

```python
# ❌ 错误
"description": "Get data"

# ✅ 正确
"description": """
Get real-time stock quote including current price, 
trading volume, and price changes.

Use when user asks about:
- Current stock prices
- Today's trading activity
- Price movements or percentage changes
"""
```

### 陷阱 2: 参数描述不清晰

```python
# ❌ 错误
"symbol": {"type": "string", "description": "Stock symbol"}

# ✅ 正确
"symbol": {
  "type": "string",
  "description": """
    Stock symbol for lookup.
    Format examples:
    - '600519' (A-share, 6 digits)
    - 'AAPL' (US stocks)
    - '1810.HK' (Hong Kong stocks)
    
    Invalid: 'sh600519' (don't include market prefix)
  """
}
```

### 陷阱 3: 工具名不一致

```python
# SKILL.md 中写:
"工具名: get_financial_statement"

# 实际代码中:
def get_financial_report():  # 不一致！
    pass

# ✅ 解决方案: 使用自动化生成工具确保一致性
```

### 陷阱 4: 缺少使用场景示例

```python
# ❌ 错误: 没有示例

# ✅ 正确: 添加使用场景
"description": """
...

Example scenarios:
- "What's the weather in Beijing?" → get_weather(location="Beijing")
- "Will it rain tomorrow in Shanghai?" → get_weather(location="Shanghai", days=2)
- "Temperature in New York" → get_weather(location="New York", units="fahrenheit")
"""
```

### 陷阱 5: 返回结果没有文档

```python
# ❌ 错误: LLM 不知道返回什么

# ✅ 正确: 明确返回格式
"returns": {
  "description": "Stock quote information",
  "fields": [
    {"name": "price", "type": "string", "description": "Current price in CNY"},
    {"name": "change", "type": "string", "description": "Price change amount"},
    {"name": "change_percent", "type": "string", "description": "Percentage change"}
  ]
}
```

---

## 七、完整示例: 金融研究助手

### 7.1 Skill 设计

```yaml
# market_data Skill
name: market_data
description: |
  股票市场行情数据查询，支持A股实时行情、历史数据、龙虎榜等。
  
  Use this skill when:
  - User asks about stock prices or market data
  - User wants to analyze stock trends
  - User needs trading information (volume, turnover, etc.)
  
  Data source: Tushare Pro API
  Coverage: A-shares (Shanghai, Shenzhen), Hong Kong stocks
  Delay: ~15 minutes for real-time data

version: "1.0"
tool_count: 11
```

### 7.2 Tool 设计

```json
{
  "name": "get_quote",
  "description": """
  Get real-time stock quote for a specific stock symbol.
  
  Use this tool when:
  - User asks about current stock price
  - User wants to know today's open/high/low prices
  - User asks about trading volume or turnover
  - User wants to see price change or percentage
  
  Returns real-time data including:
  - Current price (最新价)
  - Price change amount and percentage (涨跌额、涨跌幅)
  - Open, high, low prices (开盘价、最高价、最低价)
  - Trading volume and turnover (成交量、成交额)
  
  Note: Data is delayed by ~15 minutes for real-time stocks.
  """,
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": {
        "type": "string",
        "description": """
          Stock symbol to query.
          
          Valid formats:
          - '600519' (6 digits for A-shares)
          - '000001' (Shenzhen stocks)
          - 'AAPL' (US stocks, if supported)
          - '1810.HK' (Hong Kong stocks)
          
          Invalid formats:
          - 'sh600519' (don't include 'sh' prefix)
          - '600519.SH' (don't include '.SH' suffix)
          
          Examples:
          - '600519' for Kweichow Moutai (贵州茅台)
          - '000001' for Ping An Bank (平安银行)
        """
      }
    },
    "required": ["symbol"]
  }
}
```

### 7.3 渐进式披露流程

```python
# Step 1: Skill Discovery
skill(name="market_data")
# → 返回 SKILL.md，LLM 了解这是股票数据 Skill

# Step 2: Tool Discovery  
get_skill_tools(name="market_data")
# → 返回 11 个工具的 schema

# Step 3: Tool Execution
execute_skill_tool(
    skill_name="market_data",
    tool_name="get_quote",
    arguments={"symbol": "600519"}
)
# → 返回 {"price": "1850.50", ...}
```

---

## 八、工具与资源推荐

### 8.1 开发工具

| 工具 | 用途 |
|------|------|
| **MCP Inspector** | 调试和测试 MCP servers |
| **MCP CLI** | 命令行工具管理 servers |
| **Pydantic** | Python schema 验证 |

### 8.2 验证检查清单

```markdown
## Pre-flight Checklist

### Tool 验证
- [ ] 工具名使用动词+名词格式
- [ ] Description 包含使用场景
- [ ] 每个参数都有 type、description、示例
- [ ] 必需参数标记为 required
- [ ] 可选参数有合理的 default
- [ ] 返回结果有文档说明
- [ ] 错误信息清晰可理解

### Skill 验证
- [ ] SKILL.md 与代码实现一致
- [ ] 工具名完全匹配
- [ ] 参数名完全匹配
- [ ] 枚举值完全匹配
- [ ] 有完整的返回示例

### 渐进式披露验证
- [ ] skill() 返回清晰的 Skill 文档
- [ ] get_skill_tools() 返回完整 Schema
- [ ] execute_skill_tool() 统一调用
- [ ] LLM 能正确理解三轮流程
```

### 8.3 学习资源

1. **官方文档**
   - MCP 官方文档: https://modelcontextprotocol.io
   - Anthropic Cookbook: https://github.com/anthropics/claude-cookbooks

2. **示例项目**
   - MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
   - MCP TypeScript SDK: https://github.com/modelcontextprotocol/typescript-sdk

3. **社区资源**
   - MCP Servers 仓库: https://github.com/modelcontextprotocol/servers
   - Awesome MCP: https://github.com/punkpeye/awesome-mcp-servers

---

## 九、总结

### 核心要点

1. **Design for LLM**: 设计时要考虑 LLM 如何理解和使用
2. **Progressive Disclosure**: 使用渐进式披露减少认知负担
3. **Clear Descriptions**: 描述要包含使用场景和示例
4. **Consistent Naming**: 命名要一致、清晰、自描述
5. **Complete Schema**: 参数和返回都要有完整文档

### 投入产出比

| 投入 | 产出 |
|------|------|
| 精心设计 Skill/Tool | 工具调用成功率 60% → 90%+ |
| 完整文档和示例 | LLM 更容易学习正确模式 |
| 渐进式披露架构 | 更好的可扩展性和维护性 |

**结论**: 花时间精心设计 Skill 和 Tool 是非常值得的投资！

---

## 十、下一步行动

1. **审查现有 Skills**: 使用检查清单审查你的 7 个 Skills
2. **修复不一致**: 统一 SKILL.md 和代码实现
3. **添加示例**: 为每个 Tool 添加使用场景示例
4. **自动化验证**: 创建脚本检查文档和代码一致性
5. **A/B 测试**: 测试不同描述对 LLM 调用准确率的影响

---

*文档编写时间: 2026-03-18*
*参考资料: Anthropic MCP 官方文档, Claude Cookbook*
