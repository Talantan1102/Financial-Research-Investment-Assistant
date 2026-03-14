# DeepResearch Skill - 快速开始指南

## 🚀 5分钟快速开始

### 1. 安装依赖（必需）

```bash
cd backend
pip install openai langchain langgraph
```

### 2. 配置环境变量

```bash
export DASHSCOPE_API_KEY="sk-946dc6cdc78b40829f826a0ca3fb7382"
export TUSHARE_API_TOKEN="your_token"
```

### 3. 测试 Skill 是否正常

```bash
python tests/test_deep_research_skill.py
```

期望输出: `🎉 所有测试通过！`

---

## 💡 使用方式

### 方式 1: 直接调用 Skill（适合测试）

```python
from app.mcp_server.skills.deep_research import DeepResearchSkill

skill = DeepResearchSkill()

# 快速研究
result = await skill.quick_research(
    query="贵州茅台2024年投资价值分析",
    max_iterations=3
)

print(result["summary"])
```

### 方式 2: 通过 MCP Client（推荐）

```python
from app.mcp_client.client import MCPClient

client = MCPClient()
await client.connect()

result = await client.call_tool(
    "deep_research.quick_research",
    {
        "query": "比亚迪 vs 特斯拉竞争分析",
        "max_iterations": 3
    }
)

print(result["data"]["summary"])
await client.disconnect()
```

### 方式 3: 通过 qwen function calling（最智能）

```python
from app.service.mcp_chat_service import mcp_chat

# qwen 会自动判断是否需要深度研究
answer = await mcp_chat(
    "帮我深入研究一下宁德时代的投资价值，包括技术优势、市场地位、财务状况"
)

print(answer)
```

---

## 🛠️ 3个工具说明

### 1. quick_research（快速研究）

**适用场景**: 快速了解某个主题

```python
result = await client.call_tool(
    "deep_research.quick_research",
    {
        "query": "平安银行2024年财务状况",
        "max_iterations": 3  # 默认3次，足够快
    }
)
```

**返回内容**:
- `summary` - 简要总结
- `key_facts` - 关键事实（前5条）
- `key_insights` - 关键洞察（前3条）
- `quality_score` - 质量评分
- `iterations` - 实际迭代次数

### 2. research_sync（深度研究）

**适用场景**: 完整的行业或公司分析

```python
result = await client.call_tool(
    "deep_research.research_sync",
    {
        "query": "中国新能源汽车行业2024年发展现状与趋势",
        "search_web": True,
        "search_local": False
    }
)
```

**返回内容**:
- `final_report` - 完整报告
- `outline` - 大纲
- `facts` - 所有事实
- `data_points` - 数据点
- `charts` - 图表
- `references` - 参考来源
- `insights` - 洞察

### 3. research_stream（流式研究）

**适用场景**: 前端实时展示研究进度

```python
result = await client.call_tool(
    "deep_research.research_stream",
    {
        "query": "茅台 vs 五粮液对比分析",
        "session_id": "optional_session_id",
        "resume": False
    }
)
```

**返回内容**:
- `events` - 流式事件列表
- `final_report` - 最终报告
- `quality_score` - 质量评分
- `total_events` - 总事件数

---

## 🧪 验证 Skill 是否工作

### 快速验证

```bash
python -c "
from app.mcp_server.skills import DeepResearchSkill
skill = DeepResearchSkill()
print(f'✅ DeepResearch Skill 已就绪')
print(f'   工具数量: {skill.tool_count}')
for t in skill.discover_tools():
    print(f'   - {t.name}')
"
```

期望输出:
```
✅ DeepResearch Skill 已就绪
   工具数量: 3
   - research_stream
   - research_sync
   - quick_research
```

### 完整测试

```bash
# 1. 基础功能测试（不需要 API key）
python tests/test_deep_research_skill.py

# 2. 真实功能测试（需要 API key）
python tests/test_deep_research_real.py
```

---

## 🔧 故障排查

### 问题 1: ModuleNotFoundError: No module named 'openai'

**解决**:
```bash
pip install openai langchain langgraph
```

### 问题 2: DASHSCOPE_API_KEY not set

**解决**:
```bash
export DASHSCOPE_API_KEY="sk-946dc6cdc78b40829f826a0ca3fb7382"
```

### 问题 3: MCP Client 连接失败

**解决**:
```python
# 确保 MCP Server 路径正确
server_path = "app/mcp_server/server.py"
client = MCPClient(server_script_path=server_path)
```

### 问题 4: 研究超时

**解决**:
```python
# 减少迭代次数
result = await skill.quick_research(
    query="你的问题",
    max_iterations=2  # 从默认3减少到2
)
```

---

## 📊 性能参考

| 工具 | 迭代次数 | 预计时间 | 质量评分 |
|------|---------|---------|----------|
| quick_research | 2-3 | 20-40秒 | 0.80-0.85 |
| research_sync | 5-8 | 50-90秒 | 0.85-0.92 |
| research_stream | 5-8 | 50-90秒 | 0.85-0.92 |

---

## 📝 示例问题

### 股票分析
```
"贵州茅台2024年投资价值分析，包括股价表现、财务指标、市场地位"
"平安银行近期财务状况和风险评估"
"比亚迪 vs 特斯拉竞争分析，各自优劣势"
```

### 行业研究
```
"中国新能源汽车行业2024年发展现状与趋势"
"人工智能芯片市场竞争格局分析"
"光伏产业链上下游分析"
```

### 公司研究
```
"宁德时代技术优势、市场地位、财务状况综合分析"
"腾讯控股业务布局和增长动力分析"
"阿里巴巴电商业务转型分析"
```

---

## 🎯 最佳实践

### 1. 选择合适的工具

- **快速了解** → `quick_research` (max_iterations=2-3)
- **深度分析** → `research_sync` (默认配置)
- **实时反馈** → `research_stream` (前端展示)

### 2. 优化查询问题

✅ **好的问题**:
- "贵州茅台2024年投资价值分析，包括股价表现、财务指标、行业地位"
- "比亚迪电动车技术优势、市场份额、盈利能力分析"

❌ **不好的问题**:
- "茅台" (太简单，缺少上下文)
- "分析所有白酒公司" (范围太大)

### 3. 控制成本

```python
# 使用快速模式减少 API 调用
result = await skill.quick_research(
    query="你的问题",
    max_iterations=2  # 限制迭代次数
)
```

### 4. 处理结果

```python
if result.get("success"):
    # 成功
    summary = result.get("summary", "")
    quality = result.get("quality_score", 0)

    if quality > 0.85:
        print("高质量报告")
    else:
        print("建议增加迭代次数")
else:
    # 失败
    error = result.get("error", "")
    print(f"研究失败: {error}")
```

---

## 📚 相关文档

- [使用示例](../../../backend/examples/deep_research_example.py)

---

**快速开始完成！** 🎉

现在你可以开始使用 DeepResearch Skill 进行深度研究了！
