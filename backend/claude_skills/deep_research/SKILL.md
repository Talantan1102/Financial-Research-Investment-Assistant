---
name: deep_research
description: 深度研究服务（分步执行版），提供6个独立工具对应5个Agent，支持LLM完全控制研究流程，并集成行业分析能力
version: "1.0"
tool_count: 7
---

# DeepResearch Skill

## 概述

提供基于多智能体协作的深度研究能力，通过5个专业Agent协同工作，生成高质量的研究报告。

**新特性**: 深度集成 `sector_analysis` 行业分析能力，支持行业对比、估值分析、龙头股识别等。

**架构**: 5-Agent协作系统（Architect → Scout → Wizard → Writer → Critic）
**数据源**: 网络搜索 + 本地知识库（可选）+ 金融数据API
**输出**: 结构化研究报告

---

## 多智能体系统

### Agent协作流程

```
用户提问 → Architect(规划大纲) → Scout(搜索收集) → Wizard(数据分析) → Writer(撰写报告) → Critic(质量评审) → 最终报告
```

### Agent角色说明

1. **Architect（架构师）**: 分析研究问题，规划研究大纲和子问题
2. **Scout（侦探）**: 根据大纲搜索信息，收集事实和数据
   - 网络搜索（博查API）
   - 本地知识库
   - **金融数据**: 股票行情、财务报表、行业数据
   - **行业分析**: 行业对比、估值分析、龙头股
3. **Wizard（极客）**: 数据分析、趋势识别、可视化建议
4. **Writer（笔杆）**: 基于收集的信息撰写结构化markdown报告
5. **Critic（评论家）**: 评审报告质量，输出评分和改进建议

---

## 可用工具

### 1. plan - 规划研究大纲

**功能**: 【步骤1】Architect Agent 分析问题，生成结构化研究计划

**调用方式**: `deep_research.plan(query, session_id)`

**返回**: session_id, sections[], hypotheses[]

---

### 2. search - 搜索信息

**功能**: 【步骤2】Scout Agent 搜索网络/知识库/金融数据

**调用方式**: `deep_research.search(session_id, section_id, search_web, search_local)`

**数据源**:
- 网络搜索（博查API）
- 本地知识库
- **股票数据**: market_data 工具
- **行业数据**: sector_analysis 工具

---

### 3. analyze - 分析数据

**功能**: 【步骤3】Wizard Agent 深度分析，生成洞察

**调用方式**: `deep_research.analyze(session_id, section_id)`

---

### 4. write - 撰写报告

**功能**: 【步骤4】Writer Agent 撰写完整报告

**调用方式**: `deep_research.write(session_id, section_id)`

---

### 5. review - 质量评审

**功能**: 【步骤5】Critic Agent 评审报告质量

**调用方式**: `deep_research.review(session_id)`

**返回**: score, approved, strengths[], weaknesses[], suggestions[]

---

### 6. revise - 修订改进

**功能**: 【步骤6】Writer Agent 根据反馈修订报告

**调用方式**: `deep_research.revise(session_id)`

---

### 7. get_state - 获取研究状态

**功能**: 查看当前进度、已完成步骤、中间结果

**调用方式**: `deep_research.get_state(session_id)`

---

## 行业分析集成 ⭐

### 在研究中使用行业分析

Deep Research 现已深度集成 `sector_analysis` 行业分析能力。

#### 研究步骤中的行业分析

**Step 1: 规划阶段 (plan)**
```
Architect 识别研究涉及的行业 → 自动规划行业分析章节
```

**Step 2: 搜索阶段 (search)**
```
Scout 根据章节需要调用 sector_analysis 工具:
- 行业财务对比: compare_industry_metrics
- 行业估值对比: compare_industry_valuation  
- 行业涨跌幅: get_industry_performance
- 行业龙头: get_industry_leaders
```

**Step 3: 分析阶段 (analyze)**
```
Wizard 基于行业数据进行交叉分析:
- 行业排名 vs 个股表现
- 估值水平 vs 财务质量
- 资金流向 vs 行业趋势
```

#### 典型行业研究场景

**场景1: 寻找被低估的优质行业**
```
研究流程:
1. plan: "寻找当前被低估的优质行业"
2. search: 调用 compare_industry_metrics(metric="roe")
   → 发现白酒、医药ROE最高
3. search: 调用 compare_industry_valuation
   → 发现银行PE最低(5倍)
4. analyze: 对比分析盈利能力 vs 估值水平
5. write: 输出"银行行业被低估"结论
```

**场景2: 行业龙头股研究**
```
研究流程:
1. plan: "白酒行业龙头投资价值分析"
2. search: 调用 get_industry_leaders(industry="白酒", by="market_cap")
   → 茅台、五粮液、泸州老窖
3. search: 调用 market_data.get_daily_basic(symbol="600519")
   → 茅台PE/PB数据
4. search: 调用 financial_analysis.get_fina_indicator(symbol="600519")
   → 茅台财务指标
5. analyze: 综合评估龙头地位、估值、财务质量
6. write: 输出茅台龙头投资价值报告
```

**场景3: 热点行业追踪**
```
研究流程:
1. plan: "当前市场热点行业分析"
2. search: 调用 get_industry_performance(period="5d")
   → 发现半导体、AI涨幅最大
3. search: 调用 get_concept_stocks(concept_name="人工智能")
   → 获取AI概念股列表
4. search: 调用 compare_industry_valuation
   → 评估AI行业当前估值
5. analyze: 判断是趋势还是泡沫
6. write: 输出热点行业投资提示
```

---

## 完整研究示例

### 示例: 银行行业投资价值深度研究

```python
# Step 1: 规划
plan_result = deep_research.plan(query="银行行业投资价值深度分析")
session_id = plan_result["data"]["session_id"]
# 返回大纲: ["行业概况", "财务对比", "估值分析", "龙头股", "投资建议"]

# Step 2: 搜索 - 行业财务对比
search_result = deep_research.search(session_id=session_id, section_id="财务对比")
# Scout 自动调用: sector_analysis.compare_industry_metrics(industries=["银行", "白酒", "保险"], metric="roe")

# Step 2: 搜索 - 估值对比  
search_result = deep_research.search(session_id=session_id, section_id="估值分析")
# Scout 自动调用: sector_analysis.compare_industry_valuation(industries=["银行", "保险"])

# Step 2: 搜索 - 龙头股
search_result = deep_research.search(session_id=session_id, section_id="龙头股")
# Scout 自动调用: sector_analysis.get_industry_leaders(industry="银行", by="market_cap")

# Step 3: 分析
analyze_result = deep_research.analyze(session_id=session_id)
# Wizard 交叉分析: ROE vs PE → 发现银行被低估

# Step 4: 撰写
write_result = deep_research.write(session_id=session_id)
# Writer 生成完整报告

# Step 5: 评审
review_result = deep_research.review(session_id=session_id)
# Critic 评分和建议

# Step 6: 修订 (如有需要)
revise_result = deep_research.revise(session_id=session_id)
```

---

## 工具调用指南

### Scout Agent 自动调用的工具

Scout 在搜索阶段会根据研究内容自动选择工具:

| 研究内容 | 自动调用的工具 |
|---------|--------------|
| 个股数据 | market_data.get_quote, market_data.get_history |
| 财务分析 | financial_analysis.get_financial_report |
| 行业对比 | sector_analysis.compare_industry_metrics |
| 行业估值 | sector_analysis.compare_industry_valuation |
| 行业龙头 | sector_analysis.get_industry_leaders |
| 概念板块 | sector_analysis.get_concept_stocks |
| 市场热点 | sector_analysis.get_industry_performance |
| 网络信息 | web_research.web_search |

---

## 注意事项

### 1. 查询质量建议
**好的查询**:
- "中国AI芯片市场规模、竞争格局和发展趋势分析"
- "银行 vs 保险，哪个行业现在更值得投资？"
- "白酒行业龙头股估值对比分析"

### 2. 质量评分解读
```
90-100: 优秀 - 完整、准确、逻辑清晰
80-90:  良好 - 基本完整，逻辑通顺
70-80:  合格 - 覆盖主要内容
60-70:  一般 - 内容不够完整
<60:    需改进
```

### 3. 行业分析数据依赖
行业分析工具需要:
- Tushare API Token（已配置）
- 足够的API积分（财务指标需要800+积分）

### 4. 友好的输出格式
```
【深度研究报告】银行行业投资价值分析

研究摘要: 银行行业当前PE仅5倍，处于历史低位...

一、行业财务对比
┌─────────┬────────┬──────────┐
│ 行业    │ ROE(%) │ 股票数   │
├─────────┼────────┼──────────┤
│ 白酒    │ 25.5   │ 18       │
│ 医药    │ 18.2   │ 156      │
│ 银行    │ 12.1   │ 42       │
└─────────┴────────┴──────────┘

二、估值对比
银行PE(5.2x) < 保险(12.5x) < 医药(28.5x) < 白酒(35.8x)

三、龙头股
1. 招商银行 - 市值第一(8500亿)
2. 平安银行 - 增速最快(15%)
...

质量评分: 88.5 | 数据点: 45 | 参考来源: 12
```

---

**Skill 版本**: v1.0
**最后更新**: 2026-03-15 (集成行业分析)
