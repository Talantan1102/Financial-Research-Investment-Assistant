# MCP Server 完整工具清单与 Mock 策略

## 📊 工具总览 (6 Skills × 30 Tools)

| Skill | 工具数 | 主要数据源 | Mock 建议 |
|-------|-------|-----------|-----------|
| **market_data** | 8 | Tushare API | **全部 Mock** |
| **web_research** | 5 | 博查/内部KB | **4 Mock + 1 Real** |
| **financial_analysis** | 3 | Tushare + 计算 | **1 Mock + 2 Real** |
| **risk_assessment** | 3 | 计算类 | **全部 Real** |
| **data_analysis** | 4 | 计算/LLM | **全部 Real** |
| **deep_research** | 7 | 编排类 | **全部 Mock** |

---

## 1️⃣ market_data (8 tools) - 全部 Mock

### 数据来源：Tushare Pro API

Tushare 是一个金融数据接口平台，提供免费和付费的 API：
- **免费版**: 有限频次，基础数据
- **付费版**: 高频次，专业数据

**Mock 理由**:
1. 需要 Tushare Token，且有限流
2. 实时行情数据变化快，Mock 可保证一致性
3. 历史数据格式固定，LLM 生成质量高

| 工具 | 功能 | Tushare API 对应 | Mock 复杂度 | 说明 |
|------|------|-----------------|------------|------|
| `get_quote` | 实时行情 | `quotation` / `realtime` | ⭐ | 当前价格、涨跌幅 |
| `search_stock` | 股票搜索 | `stock_basic` | ⭐ | 根据代码/名称搜索 |
| `get_history` | 历史K线 | `daily` / `weekly` / `monthly` | ⭐⭐ | 日/周/月线数据 |
| `get_stock_basic_info` | 基础信息 | `stock_basic` / `stock_company` | ⭐ | 行业、地区、上市日期 |
| `get_top_list` | 龙虎榜 | `top_list` / `top_inst` | ⭐⭐ | 机构买卖数据 |
| `get_money_flow` | 资金流向 | `moneyflow` | ⭐⭐ | 主力/散户净流入 |
| `get_limit_list` | 涨跌停 | `limit_list` | ⭐ | 每日涨跌停统计 |
| `get_company_info` | 公司详情 | `stock_company` | ⭐ | 公司简介、联系方式 |

### Tushare API 补充说明

Tushare 实际 API 还有更多功能，目前只用了基础部分：

```
可选扩展（当前未实现）:
├── 财务数据
│   ├── income  (利润表)
│   ├── balance_sheet  (资产负债表)
│   ├── cashflow  (现金流量表)
│   └── forecast  (业绩预告)
├── 市场数据
│   ├── daily_basic  (每日指标)
│   ├── stk_limit  (涨跌停价格)
│   ├── margin  (融资融券)
│   └── pledge  (股权质押)
├── 基金数据
│   ├── fund_basic  (基金列表)
│   ├── fund_nav  (基金净值)
│   └── fund_portfolio  (基金持仓)
└── 宏观经济
    ├── cpi  (CPI)
    ├── gdp  (GDP)
    └── interest_rate  (利率)
```

**建议**: 如果后续需要更丰富的金融数据，可以扩展 Tushare API 的调用。

---

## 2️⃣ web_research (5 tools) - 4 Mock + 1 Real

### 数据来源：博查搜索 API + 内部知识库

| 工具 | 功能 | 数据源 | Mock 建议 | 理由 |
|------|------|--------|-----------|------|
| `web_search` | 网络搜索 | 博查 API | **Mock** | 按次收费，成本高 |
| `knowledge_search` | 知识库搜索 | 内部 KB | **Real** | 无外部费用 |
| `deep_search` | 深度搜索 | 递归搜索 | **Mock** | 消耗多倍 API 调用 |
| `extract_webpage` | 网页提取 | 爬虫/服务 | **Mock** | 可缓存，变化大 |
| `batch_search` | 批量搜索 | 博查 API | **Mock** | 批量费用高 |

**搜索 API 成本对比**:
- 博查 API: ~¥0.01-0.05/次
- Serper API: ~$0.001-0.005/次
- 一次 deep_search 可能调用 5-10 次 web_search

---

## 3️⃣ financial_analysis (3 tools) - 1 Mock + 2 Real

### 数据来源：Tushare 财务数据 + 计算

| 工具 | 功能 | 类型 | Mock 建议 | 理由 |
|------|------|------|-----------|------|
| `get_financial_report` | 获取财务报表 | 数据获取 | **Mock** | 数据固定，季度更新 |
| `calculate_financial_ratios` | 计算财务比率 | 纯计算 | **Real** | 验证公式正确性 |
| `compare_financial_data` | 对比财务数据 | 纯计算 | **Real** | 验证计算逻辑 |

**财务比率计算项**:
- ROE (净资产收益率)
- ROA (总资产收益率)
- 毛利率
- 净利率
- 资产负债率
- 流动比率
- 速动比率

---

## 4️⃣ risk_assessment (3 tools) - 全部 Real

### 数据来源：计算类（无外部 API）

| 工具 | 功能 | 类型 | Mock 建议 |
|------|------|------|-----------|
| `assess_portfolio_risk` | 组合风险评估 | 计算类 | **Real** |
| `calculate_risk_metrics` | 计算风险指标 | 计算类 | **Real** |
| `generate_risk_report` | 生成风险报告 | 生成类 | **Real** |

**风险指标**:
- VaR (风险价值)
- 夏普比率
- 最大回撤
- 波动率
- Beta

---

## 5️⃣ data_analysis (4 tools) - 全部 Real

### 数据来源：计算 + LLM

| 工具 | 功能 | 类型 | Mock 建议 | 理由 |
|------|------|------|-----------|------|
| `analyze_data` | 智能数据分析 | LLM | **Real** | 验证 Prompt 效果 |
| `generate_chart` | 图表生成 | 生成 | **Real** | 验证可视化 |
| `text_to_sql` | 自然语言转 SQL | LLM | **Real** | 验证 SQL 准确性 |
| `calculate_metrics` | 计算指标 | 计算 | **Real** | 验证公式 |

---

## 6️⃣ deep_research (7 tools) - 全部 Mock

### 数据来源：多 Agent 编排（内部调用其他工具）

| 工具 | 功能 | 类型 | Mock 建议 | 理由 |
|------|------|------|-----------|------|
| `plan` | 规划研究大纲 | 编排 | **Mock** | 加速多步骤流程 |
| `search` | 搜索信息 | 编排 | **Mock** | 内部调用搜索 |
| `analyze` | 分析数据 | 编排 | **Mock** | 内部调用分析 |
| `write` | 撰写报告 | 编排 | **Mock** | 纯生成任务 |
| `review` | 质量评审 | 编排 | **Mock** | 纯评审任务 |
| `revise` | 修订改进 | 编排 | **Mock** | 纯修订任务 |
| `get_state` | 获取状态 | 状态 | **Mock** | 状态查询 |

**Deep Research 流程**:
```
plan → search → analyze → write → review → revise
(步骤1) (步骤2) (步骤3) (步骤4) (步骤5) (步骤6)
```

每个步骤内部可能调用 web_search / analyze_data 等工具，Mock 可大幅加速。

---

## 📋 Mock 策略总表

### 按工具统计

| Mock 策略 | 工具数 | 占比 | 工具列表 |
|-----------|-------|------|---------|
| **LLM Mock** | 20 | 66.7% | market_data(8) + web_research(4) + financial_analysis(1) + deep_research(7) |
| **Real** | 10 | 33.3% | web_research(1) + financial_analysis(2) + risk_assessment(3) + data_analysis(4) |

### 按 Skill 统计

| Skill | 工具数 | Mock | Real | 说明 |
|-------|-------|------|------|------|
| market_data | 8 | 8 | 0 | 全部 Mock |
| web_research | 5 | 4 | 1 | knowledge_search Real |
| financial_analysis | 3 | 1 | 2 | 计算类 Real |
| risk_assessment | 3 | 0 | 3 | 全部 Real |
| data_analysis | 4 | 0 | 4 | 全部 Real |
| deep_research | 7 | 7 | 0 | 全部 Mock |

---

## 💰 成本效益分析

### 真实调用成本估算（1000 次合成）

| 费用项 | 单价 | 次数 | 小计 |
|--------|------|------|------|
| Tushare API | ¥0.001-0.01/次 | 8000 | ¥8-80 |
| 博查搜索 | ¥0.01-0.05/次 | 3000 | ¥30-150 |
| LLM (Qwen) | ¥0.005/次 | 1000 | ¥5 |
| **总计** | - | - | **¥43-235** |

### LLM Mock 成本（1000 次合成）

| 费用项 | 单价 | 次数 | 小计 |
|--------|------|------|------|
| LLM Mock 生成 | ¥0.005-0.02/次 | 20000 | ¥100-400 |
| Real 调用 | - | - | ¥10-50 |
| **总计** | - | - | **¥110-450** |

> **注意**: 看起来 LLM Mock 成本不低，但优势在于：
> 1. 不受外部 API 限流影响
> 2. 数据一致性更好（可复现）
> 3. 无需配置多个 API Key

---

## 🎯 推荐实施优先级

### Phase 1: 核心高频工具 (8 tools)
1. `market_data.get_quote`
2. `market_data.get_history`
3. `market_data.get_stock_basic_info`
4. `web_research.web_search`
5. `web_research.deep_search`
6. `deep_research.plan`
7. `deep_research.search`
8. `deep_research.analyze`

### Phase 2: 补充工具 (12 tools)
- 剩余 market_data 工具
- 剩余 web_research 工具
- 剩余 deep_research 工具

### Phase 3: 优化验证 (可选)
- 增加 Mock 结果缓存
- 增加 Mock/Real 对比验证
- 增加数值合理性校验

---

## 📝 下一步行动

1. **确认 Mock 范围**: 是否按上述 20/10 分配？
2. **设计 Prompt**: 为 20 个 Mock 工具设计 LLM Prompt
3. **实现 Engine**: 开发 LLMMockEngine 核心代码
4. **集成测试**: 与 AgentFlow 集成验证

需要我直接开始实现 Phase 1 的代码吗？
