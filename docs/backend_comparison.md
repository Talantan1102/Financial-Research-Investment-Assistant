# AgentFlow Backend 对比：基础版 vs MCP 增强版

> 详细对比两种实现方案，帮助你选择合适的版本

---

## 📊 快速对比

| 特性 | 基础版 (finance_research) | MCP 增强版 (mcp_enhanced_finance) |
|------|---------------------------|-----------------------------------|
| **工具数量** | 8个 | 16个 (+8个 MCP 工具) |
| **行情数据源** | 聚合数据 API | Tushare (更专业) |
| **财务分析** | ❌ 无 | ✅ 完整财报分析 |
| **风险评估** | ❌ 无 | ✅ 风险评估工具 |
| **数据精度** | 基础 | 专业级 |
| **复杂度** | 低 | 中等 |
| **适用场景** | 快速原型/通用场景 | 专业金融分析 |

---

## 🔧 工具详细对比

### 基础版工具（8个）

| 工具名 | 数据源 | 功能描述 |
|--------|--------|---------|
| `web_search` | Bocha AI | 网络搜索 |
| `knowledge_search` | Milvus | 本地知识库搜索 |
| `stock_query` | 聚合数据 API | 基础股票查询 |
| `bidding_search` | 招投标 API | 招投标信息 |
| `text2sql` | PostgreSQL | SQL 查询 |
| `data_analyzer` | 本地算法 | 数据分析 |
| `chart_generator` | 本地算法 | 图表生成 |
| `finish` | - | 完成任务 |

### MCP 增强版工具（16个）

#### ToolExecutor 工具（8个，同基础版）
- `web_search`, `knowledge_search`, `stock_query`, `bidding_search`
- `text2sql`, `data_analyzer`, `chart_generator`, `finish`

#### MCP Server Skills 工具（8个，新增）

| 工具名 | Skill | 数据源 | 功能描述 |
|--------|-------|--------|---------|
| `market_data:get_quote` | MarketData | Tushare | 实时行情（精确） |
| `market_data:search_stock` | MarketData | Tushare | 股票搜索 |
| `market_data:get_history` | MarketData | Tushare | 历史K线 |
| `market_data:get_financial_data` | MarketData | Tushare | 每日指标 |
| `financial_analysis:get_financial_report` | FinancialAnalysis | Tushare | 详细财报 |
| `financial_analysis:calculate_financial_ratios` | FinancialAnalysis | Tushare | 财务比率 |
| `financial_analysis:compare_financials` | FinancialAnalysis | Tushare | 公司对比 |
| `risk_assessment:assess_risk` | RiskAssessment | Tushare | 风险评估 |

---

## 🎯 使用场景对比

### 基础版适用场景

- ✅ 快速原型验证
- ✅ 通用金融问答
- ✅ 不需要深度财务分析
- ✅ 对数据精度要求不高
- ✅ 希望简单部署

**示例场景**：
```
"最近保险行业有什么新闻？" → web_search
"查询平安银行的基本信息" → stock_query
"分析收集的数据" → data_analyzer
```

### MCP 增强版适用场景

- ✅ 专业投资研究
- ✅ 深度财务分析
- ✅ 需要精确历史数据
- ✅ 风险评估需求
- ✅ 公司间对比分析

**示例场景**：
```
"分析茅台的ROE趋势和同行业对比" → 
  market_data:get_history + 
  financial_analysis:calculate_financial_ratios +
  financial_analysis:compare_financials

"评估比亚迪的投资风险" →
  market_data:get_quote +
  financial_analysis:get_financial_report +
  risk_assessment:assess_risk
```

---

## 📁 文件位置

### 基础版
```
sandbox/server/backends/resources/finance_research.py
configs/sandbox-server/finance_research_config.json
configs/synthesis/finance_research_config.json
```

### MCP 增强版
```
sandbox/server/backends/resources/mcp_enhanced_finance.py
configs/sandbox-server/mcp_enhanced_finance_config.json
configs/synthesis/mcp_enhanced_finance_config.json
```

---

## 🚀 快速启动

### 基础版启动

```bash
cd ~/.openclaw/workspace-dev/external/AgentFlow

# 1. 启动 Sandbox
/opt/miniconda3/envs/deepresearch/bin/python -m sandbox.server \
  configs/sandbox-server/finance_research_config.json

# 2. 运行合成（另开终端）
/opt/miniconda3/envs/deepresearch/bin/python -m synthesis.run \
  configs/synthesis/finance_research_config.json
```

### MCP 增强版启动

```bash
cd ~/.openclaw/workspace-dev/external/AgentFlow

# 1. 确保 Tushare Token 已设置
export TUSHARE_API_TOKEN="your_token"

# 2. 启动 Sandbox
/opt/miniconda3/envs/deepresearch/bin/python -m sandbox.server \
  configs/sandbox-server/mcp_enhanced_finance_config.json

# 3. 运行合成（另开终端）
/opt/miniconda3/envs/deepresearch/bin/python -m synthesis.run \
  configs/synthesis/mcp_enhanced_finance_config.json
```

---

## ⚠️ 注意事项

### MCP 增强版额外依赖

需要确保金融研投助手的依赖已安装：

```bash
# 在金融研投助手目录
pip install tushare pandas numpy
```

### 数据精度差异

| 数据项 | 基础版 (聚合数据) | MCP 增强版 (Tushare) |
|--------|------------------|---------------------|
| 实时行情 | 有延迟 (15分钟) | 可能更快 |
| 历史数据 | 基础K线 | 完整复权数据 |
| 财务数据 | 有限字段 | 完整三大报表 |
| 数据更新 | 不定期 | 每日更新 |

---

## 💡 推荐方案

### 阶段1：快速验证（使用基础版）

先用基础版跑通流程，验证：
- AgentFlow 集成是否正常
- 数据合成流程是否顺畅
- 生成的数据格式是否正确

### 阶段2：专业训练（使用 MCP 增强版）

确认基础版正常后，切换到 MCP 增强版：
- 获得更专业的金融数据
- 支持深度财务分析
- 生成的数据更适合专业投资模型训练

### 阶段3：混合使用

也可以根据场景选择：
- 通用问题 → 基础版
- 深度分析 → MCP 增强版

---

## 🔧 迁移指南

从基础版迁移到 MCP 增强版：

```python
# 修改前（基础版）
result = await backend.action_stock_query(stock_code="600519.SH")

# 修改后（MCP 增强版）
result = await backend.action_market_data_get_quote(symbol="600519")
# 或继续使用基础版工具
result = await backend.action_stock_query(stock_code="600519.SH")
```

**注意**：MCP 增强版向后兼容，基础版工具仍然可用。

---

## 📊 性能对比

| 指标 | 基础版 | MCP 增强版 |
|------|--------|-----------|
| 启动时间 | ~2s | ~3s (需要初始化 Tushare) |
| 单次调用延迟 | ~500ms | ~500-800ms |
| 内存占用 | 低 | 中 (缓存更多数据) |
| 并发能力 | 高 | 高 (Tushare 有限流) |

---

## ✅ 最终建议

| 场景 | 推荐版本 |
|------|---------|
| 快速原型/POC | 基础版 |
| 生产级金融分析 | MCP 增强版 |
| 需要完整财报数据 | MCP 增强版 |
| 风险评估场景 | MCP 增强版 |
| 数据精度要求高 | MCP 增强版 |

**一般建议**：
- 先从 **基础版** 开始，跑通流程
- 需要深度分析时，切换到 **MCP 增强版**
- 两者可以共存，根据任务选择

---

*最后更新: 2026-03-15*
