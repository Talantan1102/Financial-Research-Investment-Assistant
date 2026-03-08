---
name: deep_research
description: 深度研究服务，基于多智能体协作生成高质量研究报告
allowed_tools: [Bash, Read, Write]
---

# DeepResearch Skill

## 📊 概述

提供基于多智能体协作的深度研究能力，通过5个专业Agent协同工作，生成高质量的研究报告。适用于复杂主题的深度分析、市场研究、投资分析等场景。

**架构**: 5-Agent协作系统
**数据源**: 网络搜索 + 本地知识库（可选）
**输出**: 结构化研究报告

---

## 🤖 多智能体系统

### Agent协作流程

```
用户提问
    ↓
【Architect】规划研究大纲
    ↓
【Scout】搜索收集信息
    ↓
【Wizard】数据分析和可视化
    ↓
【Writer】撰写研究报告
    ↓
【Critic】质量评审和改进
    ↓
最终报告
```

### Agent角色说明

#### 1. Architect（架构师）
- **职责**: 分析研究问题，规划研究大纲
- **输出**: 结构化的研究大纲和子问题
- **示例**:
  - 问题: "中国AI芯片市场分析"
  - 大纲:
    1. 市场规模和增长趋势
    2. 主要玩家和竞争格局
    3. 技术路线和发展方向
    4. 机遇与挑战

#### 2. Scout（侦探）
- **职责**: 根据大纲搜索信息，收集事实和数据
- **数据源**:
  - 网络搜索（博查API）
  - 本地知识库（可选）
- **输出**: 相关文章、数据点、引用来源

#### 3. Wizard（极客）
- **职责**: 数据分析、趋势识别、可视化建议
- **输出**: 数据洞察、图表建议、关键指标

#### 4. Writer（笔杆）
- **职责**: 基于收集的信息撰写研究报告
- **输出**: 结构化的markdown报告
- **特点**:
  - 清晰的逻辑结构
  - 数据支撑的论述
  - 专业的语言风格

#### 5. Critic（评论家）
- **职责**: 评审报告质量，提出改进建议
- **评估维度**:
  - 完整性: 是否覆盖所有关键点
  - 准确性: 数据和事实是否可靠
  - 逻辑性: 论述是否严谨
  - 可读性: 表达是否清晰
- **输出**: 质量评分（0-100）和改进建议

---

## 🛠️ 可用工具

### 1. research_stream - 执行深度研究（流式）

**功能**: 执行深度研究任务，返回流式事件。适用于需要实时反馈的场景。

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
import asyncio
from app.service.deep_research_v2 import DeepResearchV2Service

async def main():
    service = DeepResearchV2Service()

    async for event_str in service.research(
        query='中国AI芯片市场分析',
        search_web=True,
        search_local=False
    ):
        # 解析SSE事件
        if event_str.startswith('data: '):
            data = event_str[6:].strip()
            if data and data != '[DONE]':
                print(data)

asyncio.run(main())
"
```

**参数**:
- `query` (必需): 研究问题或主题
  - 示例: `'中国AI芯片市场分析'`, `'茅台近期投资价值分析'`
- `session_id` (可选): 会话ID，用于标识和恢复研究任务
- `search_web` (可选): 是否启用网络搜索，默认 `True`
- `search_local` (可选): 是否启用本地知识库，默认 `False`
- `resume` (可选): 是否从检查点恢复，默认 `False`

**流式事件类型**:
```json
{
  "type": "phase",
  "content": "Architect: 规划研究大纲...",
  "timestamp": "2026-03-08T14:30:00"
}

{
  "type": "outline",
  "content": ["市场规模", "竞争格局", "发展趋势"],
  "timestamp": "2026-03-08T14:31:00"
}

{
  "type": "fact",
  "content": "2023年中国AI芯片市场规模达到XXX亿元",
  "source": "https://...",
  "timestamp": "2026-03-08T14:32:00"
}

{
  "type": "progress",
  "content": "已完成3/5个Agent",
  "percentage": 60,
  "timestamp": "2026-03-08T14:33:00"
}

{
  "type": "final_report",
  "content": "# 研究报告\n\n...",
  "quality_score": 85.5,
  "timestamp": "2026-03-08T14:35:00"
}
```

**返回示例**:
```json
{
  "success": true,
  "data": {
    "session_id": "research_20260308_143000",
    "query": "中国AI芯片市场分析",
    "final_report": "# 中国AI芯片市场分析\n\n## 摘要\n...",
    "quality_score": 85.5,
    "phase": "completed",
    "total_events": 156,
    "events": [...]
  }
}
```

---

### 2. research_sync - 执行深度研究（同步）

**功能**: 执行深度研究任务，返回完整结果（非流式）。适用于批处理场景。

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
import asyncio
from app.service.deep_research_v2 import DeepResearchV2Service

async def main():
    service = DeepResearchV2Service()
    result = await service.research_sync(
        query='茅台近期投资价值分析',
        session_id='research_maotai_001'
    )

    print(f'研究完成！')
    print(f'质量评分: {result[\"quality_score\"]}')
    print(f'\\n报告摘要:\\n{result[\"final_report\"][:500]}...')

asyncio.run(main())
"
```

**参数**:
- `query` (必需): 研究问题
- `session_id` (可选): 会话ID
- `search_web` (可选): 是否启用网络搜索，默认 `True`
- `search_local` (可选): 是否启用本地知识库，默认 `False`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "session_id": "research_maotai_001",
    "query": "茅台近期投资价值分析",
    "final_report": "# 贵州茅台投资价值分析\n\n## 一、基本面分析\n...",
    "quality_score": 88.5,
    "outline": [
      "基本面分析",
      "估值水平评估",
      "风险因素",
      "投资建议"
    ],
    "facts": [
      "2023年营收1517.3亿元，同比增长18.2%",
      "ROE达到32.58%，行业领先",
      "当前PE为35倍，处于历史中位"
    ],
    "data_points": [
      {"date": "2023Q1", "revenue": 385.6, "growth": 21.3},
      {"date": "2023Q2", "revenue": 756.8, "growth": 19.8}
    ],
    "charts": [
      {
        "type": "line",
        "title": "营收增长趋势",
        "data": [...]
      }
    ],
    "references": [
      "https://example.com/maotai-analysis",
      "https://example.com/baijiu-industry"
    ],
    "insights": [
      "茅台品牌价值持续增强",
      "直销渠道占比提升",
      "国际化进展顺利"
    ],
    "iterations": 2,
    "phase": "completed"
  }
}
```

---

### 3. quick_research - 快速研究（简化版）

**功能**: 执行快速研究，返回核心发现和简要报告。适用于快速了解某个主题的场景。

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
import asyncio
from app.service.deep_research_v2 import DeepResearchV2Service

async def main():
    # 快速模式：限制迭代次数
    service = DeepResearchV2Service(max_iterations=3)
    result = await service.research_sync(query='小米汽车市场前景')

    print(f'快速研究完成！')
    print(f'质量评分: {result[\"quality_score\"]}')
    print(f'迭代次数: {result.get(\"iterations\", 0)}')

asyncio.run(main())
"
```

**参数**:
- `query` (必需): 研究问题
- `max_iterations` (可选): 最大迭代次数，默认 `3`（快速模式）

**返回示例**:
```json
{
  "success": true,
  "data": {
    "query": "小米汽车市场前景",
    "summary": "小米汽车作为新能源汽车市场的新进入者，凭借强大的品牌效应和生态整合能力...",
    "key_facts": [
      "小米汽车预计2024年Q1交付",
      "定价区间21-30万元",
      "首款车型为中型SUV",
      "目标年销量10万辆",
      "已获得生产资质"
    ],
    "key_insights": [
      "小米生态优势明显，智能座舱体验领先",
      "面临激烈竞争，需快速建立品牌认知",
      "供应链整合能力是关键挑战"
    ],
    "quality_score": 72.3,
    "iterations": 3
  }
}
```

---

## 📋 工作流指导

### 典型使用场景

#### 1. 市场研究
```
用户: "帮我深度分析一下中国新能源汽车市场"

步骤:
1. 使用 research_sync(query='中国新能源汽车市场深度分析', search_web=True)
2. 等待5个Agent协作完成（约2-5分钟）
3. 获取完整报告:
   - 市场规模和增长趋势
   - 竞争格局和主要玩家
   - 政策环境和驱动因素
   - 未来发展预测
4. 格式化输出报告
```

#### 2. 投资分析
```
用户: "给我一份茅台的深度投资分析报告"

步骤:
1. 使用 research_sync(query='贵州茅台投资价值深度分析')
2. Architect规划大纲:
   - 基本面分析（财务指标）
   - 估值水平
   - 行业地位和竞争优势
   - 风险因素
   - 投资建议
3. Scout收集数据:
   - 财报数据
   - 行业报告
   - 分析师观点
4. 生成完整报告
```

#### 3. 技术趋势研究
```
用户: "AI大模型的最新发展趋势是什么？"

步骤:
1. 使用 quick_research(query='AI大模型最新发展趋势', max_iterations=3)
2. 快速获取核心信息:
   - 5个关键事实
   - 3个核心洞察
   - 简要总结
3. 如需更深入，再用 research_sync
```

#### 4. 竞品分析
```
用户: "对比分析茅台和五粮液"

步骤:
1. 使用 research_sync(query='茅台vs五粮液对比分析：财务表现、品牌价值、市场地位')
2. Architect规划对比维度
3. Scout分别收集两家公司数据
4. Wizard进行数据对比分析
5. Writer撰写对比报告
```

#### 5. 行业深度报告
```
用户: "给我一份白酒行业的深度报告"

步骤:
1. 使用 research_stream(query='中国白酒行业深度报告')
2. 实时监控流式事件:
   - Phase: 当前处于哪个Agent
   - Progress: 完成百分比
   - Fact: 收集到的关键事实
3. 获取最终报告和质量评分
```

---

## ⚠️ 注意事项

### 1. 研究时长
- **快速研究**: 1-2分钟（3次迭代）
- **标准研究**: 3-5分钟（5-8次迭代）
- **深度研究**: 5-10分钟（10+次迭代）

### 2. 查询质量建议
**好的查询**:
- ✅ "中国AI芯片市场规模、竞争格局和发展趋势分析"
- ✅ "贵州茅台2023年财务分析和投资价值评估"
- ✅ "新能源汽车vs传统燃油车：市场份额变化和未来预测"

**不好的查询**:
- ❌ "AI" (太宽泛)
- ❌ "茅台怎么样？" (不明确)
- ❌ "给我一份报告" (无主题)

### 3. 数据来源
- **网络搜索**: 博查API（已配置）
- **本地知识库**: 需手动配置知识库路径
- **实时性**: 网络搜索可获取最新信息

### 4. 质量评分解读
```
90-100: 优秀 - 完整、准确、逻辑清晰
80-90:  良好 - 基本完整，逻辑通顺
70-80:  合格 - 覆盖主要内容，存在小问题
60-70:  一般 - 内容不够完整或逻辑欠佳
<60:    需改进 - 质量不达标
```

如果质量评分 < 70，Critic会建议重新研究（自动触发迭代）

### 5. 会话管理
- `session_id`: 用于标识研究任务
- 支持断点恢复（`resume=True`）
- 研究结果会保存在 `backend/.deep_research_cache/`

### 6. 环境变量
确保以下环境变量已配置：
```bash
export SEARCH_API_KEY="sk-0ae51a2ca27f4a76bfa2bc77b7102a9d"  # 博查API
export DASHSCOPE_API_KEY="sk-..."  # qwen LLM
```

---

## 📚 参考资源

### 系统架构
- **服务实现**: `backend/app/service/deep_research_v2/`
- **Agent定义**: `backend/app/service/deep_research_v2/agents/`
- **配置文件**: `backend/app/service/deep_research_v2/config.py`

### 相关文档
- **架构设计**: `docs/DEEP_RESEARCH_V2_ARCHITECTURE.md`
- **双模式设计**: `docs/DEEP_RESEARCH_DUAL_MODE.md`

### 技术栈
- **框架**: LangGraph（状态机编排）
- **LLM**: qwen-max (DashScope)
- **搜索**: 博查API
- **存储**: 本地文件系统（检查点）

---

## 🎯 最佳实践

### 1. 选择合适的模式
- **快速了解**: `quick_research` (3次迭代)
- **标准分析**: `research_sync` (默认配置)
- **实时反馈**: `research_stream` (需要进度监控)

### 2. 撰写清晰的研究问题
- 包含主题、范围、目标
- 示例: "分析[主题]的[维度1]、[维度2]和[维度3]"

### 3. 合理使用本地知识库
- 仅在有相关内部资料时启用 `search_local=True`
- 否则会降低研究速度且无实际收益

### 4. 解读研究报告
重点关注：
- **摘要**: 核心结论
- **关键事实**: 数据支撑
- **洞察**: 深层次发现
- **参考文献**: 信息来源

### 5. 迭代优化
如果首次结果不满意：
- 重新表述研究问题（更具体）
- 增加迭代次数
- 检查数据源配置

### 6. 友好的输出格式
将markdown报告转换为结构化输出：
```
【深度研究报告】中国AI芯片市场分析
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 研究摘要
...

📈 市场规模
- 2023年: XXX亿元
- 增长率: XX%
...

🏢 竞争格局
1. 华为海思
2. 寒武纪
...

💡 核心洞察
✓ 洞察1: ...
✓ 洞察2: ...

📌 参考文献
[1] https://...
[2] https://...

━━━━━━━━━━━━━━━━━━━━━━━━━━━
质量评分: 85.5 | 数据点: 23 | 参考来源: 15
```

---

## 🔧 故障排查

### 常见问题

**1. "搜索API失败"**
- 检查 `SEARCH_API_KEY` 环境变量
- 验证API Key是否有效
- 尝试设置 `search_web=False` 使用缓存数据

**2. "LLM调用失败"**
- 检查 `DASHSCOPE_API_KEY` 环境变量
- 验证网络连接
- 查看API配额是否用尽

**3. "质量评分过低"**
- 优化研究问题（更具体、更聚焦）
- 增加迭代次数
- 检查搜索结果是否相关

**4. "会话恢复失败"**
- 确认 `session_id` 是否正确
- 检查 `.deep_research_cache/` 目录权限
- 检查点文件是否存在且未损坏

**5. "研究超时"**
- 减少迭代次数
- 简化研究问题
- 使用 `quick_research` 快速模式

**6. "本地知识库无数据"**
- 确认知识库路径配置正确
- 检查知识库文件格式（支持txt, md, pdf）
- 验证文件读取权限

---

## 🚀 进阶用法

### 1. 自定义迭代次数
```python
from app.service.deep_research_v2 import DeepResearchV2Service

# 深度研究模式（更多迭代）
service = DeepResearchV2Service(max_iterations=15)
result = await service.research_sync(query='...')
```

### 2. 断点恢复
```python
# 第一次研究
result = await service.research(
    query='长期研究主题',
    session_id='long_research_001'
)

# 稍后继续
result = await service.research(
    query='长期研究主题',
    session_id='long_research_001',
    resume=True  # 从检查点恢复
)
```

### 3. 组合多个Skill
```bash
# 先用 MarketData 获取实时数据
market_data = get_quote('600519')

# 再用 DeepResearch 深度分析
research_result = research_sync(
    query=f'贵州茅台投资分析（当前价格{market_data["nowPri"]}）'
)
```

---

**Skill 版本**: v1.0
**最后更新**: 2026-03-08
**维护者**: Financial Research Team
