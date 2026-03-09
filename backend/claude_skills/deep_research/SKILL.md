---
name: deep_research
description: 深度研究服务，基于多智能体协作生成高质量研究报告
version: "1.0"
tool_count: 3
---

# DeepResearch Skill

## 概述

提供基于多智能体协作的深度研究能力，通过5个专业Agent协同工作，生成高质量的研究报告。适用于复杂主题的深度分析、市场研究、投资分析等场景。

**架构**: 5-Agent协作系统（Architect → Scout → Wizard → Writer → Critic）
**数据源**: 网络搜索 + 本地知识库（可选）
**输出**: 结构化研究报告

---

## 多智能体系统

### Agent协作流程

```
用户提问 → Architect(规划大纲) → Scout(搜索收集) → Wizard(数据分析) → Writer(撰写报告) → Critic(质量评审) → 最终报告
```

### Agent角色说明

1. **Architect（架构师）**: 分析研究问题，规划研究大纲和子问题
2. **Scout（侦探）**: 根据大纲搜索信息，收集事实和数据（博查API + 本地知识库）
3. **Wizard（极客）**: 数据分析、趋势识别、可视化建议
4. **Writer（笔杆）**: 基于收集的信息撰写结构化markdown报告
5. **Critic（评论家）**: 评审报告质量（完整性、准确性、逻辑性、可读性），输出评分和改进建议

---

## 可用工具

### 1. research_stream - 执行深度研究（流式）

**功能**: 执行深度研究任务，返回流式事件。适用于需要实时反馈的场景。

**调用方式**: `deep_research.research_stream(query, session_id, search_web, search_local, resume)`

**参数**:
- `query` (必需): 研究问题或主题
  - 示例: `'中国AI芯片市场分析'`, `'茅台近期投资价值分析'`
- `session_id` (可选): 会话ID，用于标识和恢复研究任务
- `search_web` (可选): 是否启用网络搜索，默认 `True`
- `search_local` (可选): 是否启用本地知识库，默认 `False`
- `resume` (可选): 是否从检查点恢复，默认 `False`

**流式事件类型**:
```json
{"type": "phase", "content": "Architect: 规划研究大纲..."}
{"type": "outline", "content": ["市场规模", "竞争格局", "发展趋势"]}
{"type": "fact", "content": "2023年中国AI芯片市场规模达到XXX亿元", "source": "..."}
{"type": "progress", "content": "已完成3/5个Agent", "percentage": 60}
{"type": "final_report", "content": "# 研究报告\n\n...", "quality_score": 85.5}
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
    "phase": "completed"
  }
}
```

---

### 2. research_sync - 执行深度研究（同步）

**功能**: 执行深度研究任务，返回完整结果（非流式）。适用于批处理场景。

**调用方式**: `deep_research.research_sync(query, session_id, search_web, search_local)`

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
    "outline": ["基本面分析", "估值水平评估", "风险因素", "投资建议"],
    "facts": ["2023年营收1517.3亿元", "ROE达到32.58%"],
    "insights": ["茅台品牌价值持续增强", "直销渠道占比提升"],
    "references": ["https://..."],
    "iterations": 2,
    "phase": "completed"
  }
}
```

---

### 3. quick_research - 快速研究（简化版）

**功能**: 执行快速研究，返回核心发现和简要报告。适用于快速了解某个主题。

**调用方式**: `deep_research.quick_research(query, max_iterations)`

**参数**:
- `query` (必需): 研究问题
- `max_iterations` (可选): 最大迭代次数，默认 `3`（快速模式）

**返回示例**:
```json
{
  "success": true,
  "data": {
    "query": "小米汽车市场前景",
    "summary": "小米汽车作为新能源汽车市场的新进入者...",
    "key_facts": ["小米汽车预计2024年Q1交付", "定价区间21-30万元"],
    "key_insights": ["小米生态优势明显", "面临激烈竞争"],
    "quality_score": 72.3,
    "iterations": 3
  }
}
```

---

## 工作流指导

### 典型使用场景

#### 1. 市场研究
```
用户: "帮我深度分析一下中国新能源汽车市场"

步骤:
1. 调用 deep_research.research_sync(query='中国新能源汽车市场深度分析', search_web=True)
2. 等待Agent协作完成
3. 获取完整报告并格式化输出
```

#### 2. 投资分析
```
用户: "给我一份茅台的深度投资分析报告"

步骤:
1. 调用 deep_research.research_sync(query='贵州茅台投资价值深度分析')
2. 获取报告: 基本面分析、估值水平、风险因素、投资建议
```

#### 3. 快速了解
```
用户: "AI大模型的最新发展趋势是什么？"

步骤:
1. 调用 deep_research.quick_research(query='AI大模型最新发展趋势')
2. 获取核心事实和洞察
```

---

## 注意事项

### 1. 查询质量建议
**好的查询**:
- "中国AI芯片市场规模、竞争格局和发展趋势分析"
- "贵州茅台2023年财务分析和投资价值评估"

**不好的查询**:
- "AI"（太宽泛）
- "茅台怎么样？"（不明确）

### 2. 模式选择
- **快速了解**: `quick_research` (3次迭代)
- **标准分析**: `research_sync` (默认配置)
- **实时反馈**: `research_stream` (需要进度监控)

### 3. 质量评分解读
```
90-100: 优秀 - 完整、准确、逻辑清晰
80-90:  良好 - 基本完整，逻辑通顺
70-80:  合格 - 覆盖主要内容
60-70:  一般 - 内容不够完整
<60:    需改进
```

### 4. 数据来源
- **网络搜索**: 博查API（已配置）
- **本地知识库**: 需手动配置知识库路径
- 仅在有相关内部资料时启用 `search_local=True`

### 5. 友好的输出格式
将markdown报告转换为结构化输出:
```
【深度研究报告】中国AI芯片市场分析

研究摘要: ...
市场规模: 2023年 XXX亿元，增长率 XX%
竞争格局: 1.华为海思 2.寒武纪 ...
核心洞察: ...
参考文献: [1] https://...

质量评分: 85.5 | 数据点: 23 | 参考来源: 15
```

---

**Skill 版本**: v1.0
**最后更新**: 2026-03-08
