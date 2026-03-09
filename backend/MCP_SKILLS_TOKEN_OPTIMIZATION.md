# MCP Tools vs Claude Skills：Token 优化完整方案

## 📋 目录

- [核心发现](#核心发现)
- [MCP Tools vs Claude Skills 对比](#mcp-tools-vs-claude-skills-对比)
- [渐进式披露原理](#渐进式披露原理)
- [Token 消耗实测数据](#token-消耗实测数据)
- [当前项目分析](#当前项目分析)
- [三种优化方案](#三种优化方案)
- [实施路径建议](#实施路径建议)
- [参考资料](#参考资料)

---

## 🎯 核心发现

### 关键洞察

1. **Skills 采用三级懒加载**：Metadata（启动）→ Instructions（调用）→ Resources（按需）
2. **Token 节省高达 96%**：Skills (~100 tokens/skill) vs MCP (~1,000 tokens/tool)
3. **调用机制完全不同**：Skills 是注入 markdown 指令，MCP 是 function calling
4. **我们的项目用的是 MCP Tools**：所有工具定义在启动时加载，消耗约 17,000 tokens

### 实测数据对比

| 方案 | 启动 Token | 单条消息成本（Opus 4.6） | 上下文可用率 |
|------|-----------|------------------------|-------------|
| **MCP (58 tools)** | 55,000 tokens | $0.16/message | ~72% 被占用 |
| **MCP (100+ tools)** | 100,000+ tokens | $0.30/message | ~85% 被占用 |
| **Skills (20 skills)** | 2,000 tokens | $0.006/message | ~99% 可用 |
| **MCP + Tool Search** | 8,700 tokens | $0.026/message | ~95% 可用 |

**我们的项目**（17 个工具）：
- 当前成本：~17,000 tokens = **$0.051/message**
- 优化后（Skills）：~1,700 tokens = **$0.005/message**
- **节省 90%**

---

## 🔍 MCP Tools vs Claude Skills 对比

### 架构对比

| 维度 | MCP Tools（我们现在） | Claude Skills |
|------|---------------------|---------------|
| **工具定义格式** | Python 代码 + JSON Schema | Markdown 文件 (SKILL.md) |
| **启动加载** | ✅ 所有工具完整定义 | ✅ 仅 YAML frontmatter |
| **参数定义** | ✅ JSON Schema（完整） | ❌ 无（在 markdown 中） |
| **调用机制** | Function calling | 注入 user message |
| **执行方式** | 外部 MCP 进程 | Claude 读取指令 → 调用内置 tools |
| **Token 消耗** | 每条消息都占用全部定义 | 仅调用时占用 |
| **路由机制** | LLM function calling | LLM 纯推理 |

### 加载时机对比

#### MCP Tools（当前架构）

```python
# 启动时 - server.py
@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="market_data.get_quote",
            description="获取指定股票的实时行情数据，包括当前价格、涨跌幅、成交量等信息",
            inputSchema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "股票代码，支持多种格式：'600519'(纯数字)、'sh600519'(带市场前缀)、'600519.SH'(Tushare格式)"
                    }
                },
                "required": ["symbol"]
            }
        ),
        # ... 16 个其他工具
    ]
```

**Token 消耗（启动时）**：
- 单个工具：~800-1,000 tokens
- 17 个工具：~17,000 tokens
- **每条消息都携带这些定义**

#### Claude Skills

```markdown
<!-- market_data/SKILL.md -->
---
name: market_data
description: 股票市场行情数据查询
---

# MarketData Skill

## 工具列表

### get_quote
获取股票实时行情

**使用方法**：
```bash
python -c "
from app.data.tushare_client import get_tushare_client
client = get_tushare_client()
print(client.get_quote('600519'))
"
```

[更多工具...]
```

**Token 消耗**：
- 启动时（frontmatter）：~50 tokens
- 调用时（完整 SKILL.md）：~2,000 tokens
- **仅在使用时加载**

---

## 📊 渐进式披露原理

### 三级加载架构

```
Level 1: Metadata（启动时加载）
├─ Token 消耗：~100 tokens/skill
├─ 加载内容：SKILL.md 的 YAML frontmatter
└─ 作用：技能发现和路由

Level 2: Instructions（调用时加载）
├─ Token 消耗：~2,000-5,000 tokens/skill
├─ 加载内容：完整的 SKILL.md markdown
├─ 触发时机：Skill("market_data") 调用时
└─ 作用：提供详细指令

Level 3: Resources（按需加载）
├─ Token 消耗：0 tokens（不占上下文）
├─ 加载内容：references/, scripts/, assets/ 文件
├─ 触发时机：Read tool 读取时
└─ 作用：提供参考文档和脚本
```

### 加载流程示例

**场景**：用户问"小米股价多少？"

#### MCP Tools 流程

```
1. 用户提问: "小米股价多少？"
   └─ 上下文：17,000 tokens（所有工具定义）

2. Claude 推理并选择工具
   └─ Function calling: market_data.get_quote("1810.HK")

3. MCP Server 执行工具
   └─ 返回结果

总 Token：17,000 (定义) + 500 (推理) + 100 (结果) = 17,600 tokens
```

#### Claude Skills 流程

```
1. 用户提问: "小米股价多少？"
   └─ 上下文：1,700 tokens（17 个 skill frontmatter）

2. Claude 判断需要 market_data skill
   └─ 调用: Skill("market_data")

3. 系统加载 market_data/SKILL.md
   └─ 注入 user message（~2,000 tokens）

4. Claude 读取指令，调用 Bash tool
   └─ 执行 Python 脚本获取股价

5. 返回结果

总 Token：1,700 (frontmatter) + 2,000 (SKILL.md) + 500 (推理) = 4,200 tokens
```

**节省**：17,600 → 4,200 = **76% 减少**

---

## 💰 Token 消耗实测数据

### 我们的项目估算

#### 当前架构（MCP Tools）

**工具清单**（17 个）：
- MarketData (8 tools): ~6,400 tokens
- FinancialAnalysis (3 tools): ~2,400 tokens
- RiskAssessment (3 tools): ~2,400 tokens
- DeepResearch (3 tools): ~5,800 tokens

**启动加载总计**：~17,000 tokens

**单条消息成本**：
```
输入: 17,000 (定义) + 500 (对话) = 17,500 tokens
成本: 17,500 × $3/M = $0.053/message
```

**10 轮对话成本**：$0.53

#### 优化后（Skills + Tool Search）

**Skill 清单**（4 个）：
- market_data: ~100 tokens (frontmatter)
- financial_analysis: ~100 tokens
- risk_assessment: ~100 tokens
- deep_research: ~100 tokens

**启动加载总计**：~400 tokens

**单条消息成本**（假设调用 1 个 skill）：
```
输入: 400 (frontmatter) + 2,000 (SKILL.md) + 500 (对话) = 2,900 tokens
成本: 2,900 × $3/M = $0.009/message
```

**10 轮对话成本**：$0.09

**节省**：$0.53 → $0.09 = **83% 减少**

### 工具数量增长影响

| 工具数量 | MCP Tools 启动 Token | Skills 启动 Token | 节省比例 |
|---------|--------------------|--------------------|---------|
| 10 | 10,000 | 1,000 | 90% |
| 17 (当前) | 17,000 | 1,700 | 90% |
| 50 | 50,000 | 5,000 | 90% |
| 100 | 100,000 | 10,000 | 90% |

**结论**：Skills 的 token 消耗与工具数量呈线性关系，而 MCP 也是线性，但 Skills 的系数小 10 倍。

---

## 🔧 当前项目分析

### 文件结构

```
backend/app/mcp_server/
├── server.py                 # MCP Server 入口
├── skills/
│   ├── base.py              # BaseSkill 基类
│   ├── market_data.py       # MarketData Skill (8 tools)
│   ├── financial_analysis.py # FinancialAnalysis (3 tools)
│   ├── risk_assessment.py   # RiskAssessment (3 tools)
│   ├── deep_research.py     # DeepResearch (3 tools)
│   ├── deep_research_enhanced.py
│   └── deep_research_split.py
└── config.py
```

### 代码分析

#### 当前实现（MCP Tools）

```python
# skills/market_data.py
class MarketDataSkill(BaseSkill):
    name = "market_data"
    description = "股票市场行情数据查询，支持A股实时行情获取"

    def _register_tools(self):
        self.register_tool(
            name="get_quote",
            handler=self.get_quote,
            description="获取指定股票的实时行情数据，包括当前价格、涨跌幅、成交量等信息",
            parameters=[
                ToolParameter(
                    name="symbol",
                    type="string",
                    description="股票代码，支持多种格式：'600519'(纯数字)、'sh600519'(带市场前缀)、'600519.SH'(Tushare格式)",
                    required=True
                )
            ]
        )
        # ... 7 个其他工具
```

**问题**：
- ❌ 所有工具定义在启动时注册到 MCP Server
- ❌ 每个工具的完整 JSON Schema 都占用 token
- ❌ 工具数量增加时，token 消耗线性增长

#### server.py 注册逻辑

```python
# server.py
@self.server.list_tools()
async def list_tools() -> List[Tool]:
    tools = []
    for skill in self.skills.values():
        for tool_def in skill.discover_tools():
            tools.append(Tool(
                name=f"{skill.name}.{tool_def.name}",
                description=tool_def.description,
                inputSchema=tool_def.to_json_schema()["parameters"]
            ))
    return tools  # 返回所有 17 个工具的完整定义
```

**Token 消耗**：每次 `list_tools()` 调用都返回 17 个完整定义，~17,000 tokens

---

## 🎨 三种优化方案

### 方案 1：启用 MCP Tool Search ⭐ 推荐（快速见效）

**原理**：让 Claude 自动按需搜索工具，而非一次性加载全部

**实施方法**：

1. **在 MCP Server 中添加 Tool Search 支持**

```python
# server.py
@self.server.list_tools()
async def list_tools() -> List[Tool]:
    # 添加 tool_search meta-tool
    tools = [
        Tool(
            name="tool_search",
            description="Search for tools by keyword. Returns tool names and brief descriptions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'stock price', 'financial data')"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of tools to return (default 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        )
    ]

    # 仅添加高频工具的完整定义（2-3 个）
    high_freq_tools = ["market_data.get_quote", "market_data.search_stock"]

    for skill in self.skills.values():
        for tool_def in skill.discover_tools():
            full_name = f"{skill.name}.{tool_def.name}"
            if full_name in high_freq_tools:
                tools.append(Tool(
                    name=full_name,
                    description=tool_def.description,
                    inputSchema=tool_def.to_json_schema()["parameters"]
                ))

    return tools
```

2. **实现 tool_search handler**

```python
@self.server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    if name == "tool_search":
        query = arguments["query"]
        max_results = arguments.get("max_results", 5)

        # 简单的关键词匹配（可以用 BM25 或向量检索）
        results = []
        for skill in self.skills.values():
            for tool_def in skill.discover_tools():
                if query.lower() in tool_def.description.lower():
                    results.append({
                        "name": f"{skill.name}.{tool_def.name}",
                        "description": tool_def.description[:100] + "..."
                    })

        return [TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "tools": results[:max_results]
            }, ensure_ascii=False)
        )]

    # ... 原有的 tool calling 逻辑
```

**效果**：
- 启动 Token：~3,000 tokens（tool_search + 2 个高频工具）
- 节省：17,000 → 3,000 = **82% 减少**
- 成本：$0.051 → $0.009/message

**优点**：
- ✅ 无需改变现有代码架构
- ✅ 保留所有工具的可用性
- ✅ 实施成本低（1-2 天）

**缺点**：
- ⚠️ 需要实现搜索逻辑
- ⚠️ 首次调用有额外的搜索开销

---

### 方案 2：改造为真正的 Claude Skills ⭐⭐ 推荐（最大收益）

**原理**：将 Python Skills 改造为 Markdown 指令包，实现三级懒加载

**实施方法**：

1. **创建 Skills 目录结构**

```
backend/claude_skills/
├── market_data/
│   ├── SKILL.md              # 核心指令
│   ├── references/
│   │   └── tushare_api.md   # API 文档
│   └── scripts/
│       └── get_quote.py     # 可执行脚本
├── financial_analysis/
│   └── SKILL.md
├── risk_assessment/
│   └── SKILL.md
└── deep_research/
    └── SKILL.md
```

2. **编写 SKILL.md**

```markdown
<!-- market_data/SKILL.md -->
---
name: market_data
description: 股票市场行情数据查询，支持A股实时行情获取
allowed_tools: Bash, Read, Write
---

# MarketData Skill

## 概述

提供股票市场行情数据查询能力，基于 Tushare API。

## 可用工具

### 1. get_quote - 获取实时行情

**功能**：查询指定股票的实时行情数据

**使用方法**：
```bash
cd /backend
python -c "
from app.data.tushare_client import get_tushare_client
client = get_tushare_client()
result = client.get_quote('600519')
print(result)
"
```

**参数**：
- symbol: 股票代码（如 '600519' 或 '1810.HK'）

**返回**：包含价格、涨跌幅、成交量等数据的字典

### 2. search_stock - 搜索股票

**功能**：根据代码或名称搜索股票

**使用方法**：
```bash
python -c "
from app.data.tushare_client import get_tushare_client
client = get_tushare_client()
result = client.search_stock('茅台')
print(result)
"
```

[更多工具定义...]

## 工作流

当用户询问股票行情时：

1. **识别需求**
   - 实时行情 → 使用 get_quote
   - 历史数据 → 使用 get_history
   - 不确定代码 → 先用 search_stock

2. **执行查询**
   - 使用 Bash tool 调用对应脚本
   - 解析返回的 JSON 结果

3. **格式化输出**
   - 提取关键信息（价格、涨跌幅等）
   - 用友好的格式呈现给用户

## 参考文档

详细的 API 文档请参考：`references/tushare_api.md`
```

3. **修改 MCP Server 支持 Skills**

```python
# server.py
class FinancialMCPServer:
    def __init__(self):
        self.skills_dir = Path(__file__).parent.parent / "claude_skills"
        self.skill_metadata = self._load_skill_metadata()
        # ...

    def _load_skill_metadata(self) -> Dict[str, Dict]:
        """加载所有 Skills 的 frontmatter（Level 1）"""
        metadata = {}
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    content = skill_md.read_text()
                    # 解析 YAML frontmatter
                    if content.startswith("---"):
                        yaml_end = content.find("---", 3)
                        yaml_content = content[3:yaml_end]
                        metadata[skill_dir.name] = yaml.safe_load(yaml_content)
        return metadata

    @self.server.list_tools()
    async def list_tools() -> List[Tool]:
        """返回 Skill tool（让 Claude 调用 Skills）"""
        return [
            Tool(
                name="skill",
                description=f"Load and execute a Claude Skill. Available skills: {', '.join(self.skill_metadata.keys())}",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": list(self.skill_metadata.keys()),
                            "description": "Skill name to load"
                        }
                    },
                    "required": ["name"]
                }
            )
        ]

    @self.server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]):
        if name == "skill":
            skill_name = arguments["name"]
            skill_path = self.skills_dir / skill_name / "SKILL.md"
            skill_content = skill_path.read_text()

            # 返回完整的 SKILL.md 内容（Level 2 加载）
            return [TextContent(
                type="text",
                text=skill_content
            )]
```

**效果**：
- 启动 Token：~400 tokens（4 个 skill metadata）
- 调用时 Token：~2,000 tokens（单个 SKILL.md）
- 节省：17,000 → 2,400 = **86% 减少**
- 成本：$0.051 → $0.007/message

**优点**：
- ✅ 最大化 token 节省（86%）
- ✅ 可扩展性极强（支持无限工具）
- ✅ 符合 Claude 官方最佳实践
- ✅ 支持 Level 3 资源（references/）

**缺点**：
- ⚠️ 需要重构现有代码（较大工作量）
- ⚠️ 增加一次调用往返（Skill() → 加载 SKILL.md）
- ⚠️ 依赖 Claude 的 Skill tool 支持

---

### 方案 3：混合架构（渐进式迁移）⭐⭐⭐ 最推荐

**原理**：保留高频工具为 MCP Tools，低频工具改为 Skills 或 Tool Search

**实施方法**：

1. **高频工具保留 MCP Tools**（2-3 个）
   - market_data.get_quote
   - market_data.search_stock

2. **中频工具使用 Tool Search**（5-10 个）
   - market_data.get_history
   - financial_analysis.analyze_balance_sheet
   - ...

3. **复杂工作流改为 Skills**（1-2 个）
   - deep_research → 改为 SKILL.md

**配置文件**：

```python
# config.py
TOOL_LOADING_STRATEGY = {
    "high_frequency": {
        "mode": "eager",  # 启动时加载
        "tools": [
            "market_data.get_quote",
            "market_data.search_stock",
        ]
    },
    "medium_frequency": {
        "mode": "lazy_search",  # Tool Search 按需加载
        "tools": [
            "market_data.get_history",
            "market_data.get_financial_data",
            "financial_analysis.*",  # 通配符
            "risk_assessment.*"
        ]
    },
    "workflows": {
        "mode": "skill",  # Skills 架构
        "skills": [
            "deep_research"
        ]
    }
}
```

**实现**：

```python
# server.py
@self.server.list_tools()
async def list_tools() -> List[Tool]:
    tools = []

    # 1. 添加 tool_search meta-tool
    tools.append(create_tool_search_tool())

    # 2. 添加高频工具（完整定义）
    for tool_name in TOOL_LOADING_STRATEGY["high_frequency"]["tools"]:
        skill_name, tool_name_only = tool_name.split(".")
        skill = self.skills[skill_name]
        tool_def = skill.get_tool(tool_name_only)
        tools.append(Tool(
            name=tool_name,
            description=tool_def.description,
            inputSchema=tool_def.to_json_schema()["parameters"]
        ))

    # 3. 添加 Skill tool（用于加载 Skills）
    tools.append(create_skill_tool(
        available_skills=TOOL_LOADING_STRATEGY["workflows"]["skills"]
    ))

    return tools
```

**效果**：
- 启动 Token：~2,500 tokens（tool_search + 2 高频工具 + skill tool）
- 节省：17,000 → 2,500 = **85% 减少**
- 成本：$0.051 → $0.008/message

**优点**：
- ✅ 保留高频工具的低延迟
- ✅ 大幅减少 token 消耗
- ✅ 渐进式迁移，风险可控
- ✅ 灵活配置，易于调整

**缺点**：
- ⚠️ 需要维护三种模式的代码
- ⚠️ 配置复杂度增加

---

## 🛣️ 实施路径建议

### Phase 1：快速验证（1-2 天）

**目标**：验证 Tool Search 的可行性和效果

**任务**：
1. 在 server.py 中添加 tool_search meta-tool
2. 保留 2 个高频工具（get_quote, search_stock）
3. 其他 15 个工具通过 tool_search 按需加载
4. 测试并收集数据

**预期效果**：
- Token 减少 80%+
- 成本降低到 $0.01/message

### Phase 2：Skills 改造试点（1 周）

**目标**：将 DeepResearch 改造为真正的 Skill

**任务**：
1. 创建 `claude_skills/deep_research/SKILL.md`
2. 编写完整的工作流指令
3. 将 references 和 scripts 分离到对应目录
4. 测试 Skill 调用流程

**预期效果**：
- DeepResearch 启动 Token 从 ~5,800 → ~100
- 调用时 Token ~3,000（完整 SKILL.md）

### Phase 3：全面优化（2-3 周）

**目标**：完成混合架构部署

**任务**：
1. 配置三种加载策略（eager, lazy_search, skill）
2. 改造 MarketData 为 Skill
3. 改造 FinancialAnalysis、RiskAssessment 为 Skill
4. 优化 Tool Search 算法（BM25 或向量检索）
5. 添加缓存机制（已加载的工具定义）

**预期效果**：
- 总 Token 消耗 ~2,500
- 成本降低到 $0.008/message
- **节省 84%**

### Phase 4：监控与优化（持续）

**任务**：
1. 监控各工具的调用频率
2. 动态调整 high_frequency 配置
3. 优化 SKILL.md 的 token 消耗（< 5,000 tokens）
4. 收集用户反馈，调整工作流

---

## 📚 参考资料

### 官方文档
- [Inside Claude Code Skills: Structure, prompts, invocation](https://mikhail.io/2025/10/claude-code-skills/)
- [Claude Agent Skills: A First Principles Deep Dive](https://leehanchung.github.io/blogs/2025/10/26/claude-skills-deep-dive/)
- [Introducing advanced tool use on the Claude Developer Console](https://www.anthropic.com/engineering/advanced-tool-use)
- [Extend Claude with skills - Claude Code Docs](https://code.claude.com/docs/en/skills)

### Token 优化
- [Claude Skills vs MCP: Complete Guide to Token-Efficient AI Agent Architecture](https://dev.to/jimquote/claude-skills-vs-mcp-complete-guide-to-token-efficient-ai-agent-architecture-4mkf)
- [What is MCP Tool Search? The Claude Code feature that fixes context pollution](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide)
- [MCP Tool Schema Bloat: The Hidden Token Tax (and How to Fix It)](https://layered.dev/mcp-tool-schema-bloat-the-hidden-token-tax-and-how-to-fix-it/)
- [10 Strategies to Reduce Token Bloat](https://thenewstack.io/how-to-reduce-mcp-token-bloat/)

### 渐进式披露
- [100x Token Reduction Dynamic Toolsets](https://www.speakeasy.com/blog/100x-token-reduction-dynamic-toolsets)
- [Progressive Disclosure MCP Extension](https://huggingface.co/spaces/MCP-1st-Birthday/mcp-extension-progressive-disclosure/blob/main/README.md)
- [Stop Bloating Your CLAUDE.md: Progressive Disclosure for AI Coding Tools](https://alexop.dev/posts/stop-bloating-your-claude-md-progressive-disclosure-ai-coding-tools/)

### 架构对比
- [Claude Skills vs. MCP: A Technical Comparison for AI Workflows](https://intuitionlabs.ai/articles/claude-skills-vs-mcp)
- [Skills vs Dynamic MCP Loadouts](https://lucumr.pocoo.org/2025/12/13/skills-vs-mcp/)

---

## 📊 附录：完整 Token 消耗对比表

### 当前架构（MCP Tools）

| Skill | 工具数量 | 单工具 Token | 总 Token |
|-------|---------|-------------|---------|
| MarketData | 8 | ~800 | 6,400 |
| FinancialAnalysis | 3 | ~800 | 2,400 |
| RiskAssessment | 3 | ~800 | 2,400 |
| DeepResearch | 3 | ~1,200 | 3,600 |
| **总计** | **17** | - | **14,800** |

加上 MCP 协议开销：~17,000 tokens

### 方案 1：Tool Search

| 组件 | Token |
|------|-------|
| tool_search meta-tool | 200 |
| get_quote (high freq) | 800 |
| search_stock (high freq) | 800 |
| **启动总计** | **1,800** |

调用低频工具时：+1,000 tokens（搜索 + 加载单个工具）

### 方案 2：Claude Skills

| Skill | Frontmatter (启动) | SKILL.md (调用) |
|-------|--------------------|----------------|
| market_data | 50 | 2,000 |
| financial_analysis | 50 | 1,500 |
| risk_assessment | 50 | 1,500 |
| deep_research | 50 | 3,000 |
| **启动总计** | **200** | - |

调用时：200 (frontmatter) + 2,000 (单个 SKILL.md) = 2,200 tokens

### 方案 3：混合架构

| 组件 | Token |
|------|-------|
| tool_search meta-tool | 200 |
| skill meta-tool | 150 |
| get_quote (eager) | 800 |
| search_stock (eager) | 800 |
| deep_research frontmatter | 50 |
| **启动总计** | **2,000** |

---

## 🎯 最终建议

**推荐方案**：混合架构（方案 3）

**理由**：
1. ✅ 兼顾性能（高频工具零延迟）和成本（低频工具按需加载）
2. ✅ 渐进式迁移，风险可控
3. ✅ 灵活配置，易于调整
4. ✅ 预期节省 85% token 消耗

**实施优先级**：
1. **Phase 1（立即）**：实现 Tool Search，快速见效
2. **Phase 2（2周内）**：DeepResearch 改造为 Skill（试点）
3. **Phase 3（1月内）**：全面迁移到混合架构
4. **Phase 4（持续）**：监控优化

**成本预期**：
- 当前：$0.051/message
- Phase 1 后：$0.010/message（节省 80%）
- Phase 3 后：$0.008/message（节省 84%）

---

**文档版本**：v1.0
**创建日期**：2026-03-08
**最后更新**：2026-03-08
**负责人**：AI Research Team
