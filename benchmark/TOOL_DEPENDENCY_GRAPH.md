# 金融研投助手工具依赖图谱

**版本**: v1.0  
**日期**: 2026-03-21  
**说明**: 定义各工具之间的输入输出依赖关系，用于构建工具链测试

---

## 一、工具总览 (43个)

| Skill | 工具数 | 工具列表 |
|-------|--------|----------|
| market_data | 11 | get_quote, search_stock, get_history, get_stock_basic_info, get_top_list, get_money_flow, get_limit_list, get_company_info, get_daily_basic, get_north_money, get_margin |
| financial_analysis | 7 | calculate_financial_ratios, get_income_statement, get_balance_sheet, get_cash_flow, get_fina_indicator, analyze_profitability, analyze_solvency |
| sector_analysis | 7 | get_industry_list, get_industry_performance, get_industry_leaders, compare_industry_metrics, compare_industry_valuation, get_concept_list, get_concept_stocks |
| risk_assessment | 5 | assess_stock_risk, assess_valuation_risk, assess_financial_risk, assess_volatility_risk, check_risk_warnings |
| web_research | 4 | search_stock_news, search_company_announcements, search_industry_news, search_research_reports |
| data_analysis | 6 | calculate_statistics, analyze_price_trend, calculate_correlation, calculate_technical_indicators, normalize_data, generate_chart_data |
| deep_research | 3 | generate_stock_report, generate_industry_report, generate_comparison_report |

---

## 二、工具输入输出定义

### 2.1 Market Data Skill

| 工具 | 核心输入 | 核心输出 | 可作为后续工具的输入 |
|------|----------|----------|----------------------|
| **search_stock** | keyword | ts_code, name | get_quote, get_history, get_daily_basic 等所有需要股票代码的工具 |
| **get_quote** | ts_code | price, change, volume | - |
| **get_history** | ts_code, start_date, end_date | kline_data (open, high, low, close, volume) | calculate_statistics, analyze_price_trend, calculate_technical_indicators, calculate_correlation |
| **get_stock_basic_info** | ts_code | industry, area, list_date | - |
| **get_daily_basic** | ts_code | pe, pb, ps, total_mv, turnover_rate | assess_valuation_risk, normalize_data |
| **get_money_flow** | ts_code | buy_sm_amount, sell_sm_amount | - |
| **get_top_list** | trade_date | ts_code, name, close, amount | - |
| **get_limit_list** | trade_date, limit_type | ts_code, name, fl_ratio | - |
| **get_company_info** | ts_code | company_name, chairman, business | - |
| **get_north_money** | - | trade_date, buy_amount, sell_amount | - |
| **get_margin** | ts_code | rzye, rqye | - |

### 2.2 Financial Analysis Skill

| 工具 | 核心输入 | 核心输出 | 可作为后续工具的输入 |
|------|----------|----------|----------------------|
| **get_income_statement** | ts_code, period | revenue, profit, expenses | calculate_financial_ratios, analyze_profitability |
| **get_balance_sheet** | ts_code, period | assets, liabilities, equity | calculate_financial_ratios, analyze_solvency |
| **get_cash_flow** | ts_code, period | op_cashflow, inv_cashflow | calculate_financial_ratios |
| **get_fina_indicator** | ts_code, period | roe, grossprofit_margin, debt_to_assets | assess_financial_risk |
| **calculate_financial_ratios** | ts_code, period | roe, roa, gross_margin | - |
| **analyze_profitability** | ts_code | profit_trend, margin_analysis | - |
| **analyze_solvency** | ts_code | debt_ratio, liquidity_analysis | assess_financial_risk |

### 2.3 Sector Analysis Skill

| 工具 | 核心输入 | 核心输出 | 可作为后续工具的输入 |
|------|----------|----------|----------------------|
| **get_industry_list** | - | industry_code, industry_name | get_industry_performance, get_industry_leaders |
| **get_industry_performance** | industry_code | avg_price_change, avg_pe | compare_industry_metrics, compare_industry_valuation |
| **get_industry_leaders** | industry_code | ts_code, name, market_cap | get_daily_basic, get_quote |
| **compare_industry_metrics** | industries | comparison_table | - |
| **compare_industry_valuation** | industries | pe_comparison, pb_comparison | - |
| **get_concept_list** | - | concept_code, concept_name | get_concept_stocks |
| **get_concept_stocks** | concept_name | ts_code, name | get_quote, get_daily_basic |

### 2.4 Risk Assessment Skill

| 工具 | 核心输入 | 核心输出 | 可作为后续工具的输入 |
|------|----------|----------|----------------------|
| **assess_stock_risk** | ts_code | risk_level, risk_factors | - |
| **assess_valuation_risk** | ts_code | valuation_risk_level | - |
| **assess_financial_risk** | ts_code | financial_risk_level | - |
| **assess_volatility_risk** | ts_code | volatility_risk_level | - |
| **check_risk_warnings** | ts_code | warnings | - |

### 2.5 Web Research Skill

| 工具 | 核心输入 | 核心输出 | 可作为后续工具的输入 |
|------|----------|----------|----------------------|
| **search_stock_news** | ts_code, start_date | news_list | generate_stock_report |
| **search_company_announcements** | ts_code | announcements | generate_stock_report |
| **search_industry_news** | industry, start_date | news_list | generate_industry_report |
| **search_research_reports** | keyword | reports | generate_stock_report |

### 2.6 Data Analysis Skill

| 工具 | 核心输入 | 核心输出 | 可作为后续工具的输入 |
|------|----------|----------|----------------------|
| **calculate_statistics** | data (from get_history) | mean, std, min, max | - |
| **analyze_price_trend** | price_data (from get_history) | trend, support, resistance | - |
| **calculate_correlation** | data1, data2 | correlation_coefficient | - |
| **calculate_technical_indicators** | kline_data | macd, rsi, kdj | - |
| **normalize_data** | data | normalized_data | - |
| **generate_chart_data** | data | chart_data | - |

### 2.7 Deep Research Skill

| 工具 | 核心输入 | 核心输出 | 可作为后续工具的输入 |
|------|----------|----------|----------------------|
| **generate_stock_report** | ts_code | comprehensive_report | - |
| **generate_industry_report** | industry_code | industry_report | - |
| **generate_comparison_report** | ts_codes | comparison_report | - |

---

## 三、工具链依赖图谱

### 3.1 高频工具链

```
工具链 1: 个股完整分析流程
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  search_stock    │────▶│   get_quote      │────▶│ assess_stock_risk│
│  (获取ts_code)   │     │  (获取实时价格)   │     │  (综合风险评估)  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────────┐
│get_daily_basic   │────▶│assess_valuation_ │
│ (获取估值指标)    │     │    risk          │
└──────────────────┘     └──────────────────┘

工具链 2: 技术分析流程
┌──────────────────┐     ┌──────────────────────────┐     ┌──────────────────┐
│   get_history    │────▶│ calculate_technical_     │────▶│ analyze_price_   │
│  (获取K线数据)    │     │     indicators           │     │     trend        │
└──────────────────┘     └──────────────────────────┘     └──────────────────┘
         │
         ▼
┌──────────────────┐
│calculate_        │
│statistics        │
└──────────────────┘

工具链 3: 行业龙头筛选
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ get_industry_    │────▶│ get_industry_    │────▶│  get_daily_basic │
│    list          │     │    leaders       │     │ (获取龙头估值)   │
└──────────────────┘     └──────────────────┘     └──────────────────┘

工具链 4: 深度研报生成
┌──────────────────┐     ┌──────────────────┐
│  search_stock_   │────▶│                  │
│     news         │     │                  │
└──────────────────┘     │                  │
                         │  generate_stock_ │
┌──────────────────┐     │     report       │
│ search_company_  │────▶│                  │
│  announcements   │     │                  │
└──────────────────┘     └──────────────────┘

工具链 5: 多股对比分析
┌──────────────────┐     ┌──────────────────┐
│  search_stock    │────▶│   get_history    │
│  (获取多股代码)   │     │  (获取多股数据)  │
└──────────────────┘     └──────────────────┘
         │                        │
         │                        ▼
         │               ┌──────────────────┐
         │               │calculate_        │
         │               │correlation       │
         │               └──────────────────┘
         │                        │
         ▼                        ▼
┌──────────────────┐     ┌──────────────────┐
│generate_         │◀────│   normalize_     │
│comparison_report │     │     data         │
└──────────────────┘     └──────────────────┘

工具链 6: 财务健康度评估
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ get_income_      │────▶│ calculate_       │────▶│analyze_          │
│  statement       │     │financial_ratios  │     │profitability     │
└──────────────────┘     └──────────────────┘     └──────────────────┘
         │
         ▼
┌──────────────────┐     ┌──────────────────┐
│  get_balance_    │────▶│  analyze_        │────▶│assess_financial_ │
│    sheet         │     │   solvency       │     │     risk         │
└──────────────────┘     └──────────────────┘     └──────────────────┘
```

### 3.2 输入依赖矩阵

| 下游工具 | 依赖上游工具 | 依赖字段 |
|----------|--------------|----------|
| get_quote | search_stock | ts_code |
| get_history | search_stock | ts_code |
| get_daily_basic | search_stock | ts_code |
| get_stock_basic_info | search_stock | ts_code |
| get_company_info | search_stock | ts_code |
| get_money_flow | search_stock | ts_code |
| get_margin | search_stock | ts_code |
| calculate_statistics | get_history | close, volume |
| analyze_price_trend | get_history | close, high, low |
| calculate_correlation | get_history | close (多股) |
| calculate_technical_indicators | get_history | open, high, low, close, volume |
| generate_chart_data | get_history | kline_data |
| calculate_financial_ratios | get_income_statement, get_balance_sheet | revenue, profit, assets |
| analyze_profitability | get_income_statement | revenue, profit |
| analyze_solvency | get_balance_sheet | assets, liabilities |
| assess_financial_risk | get_fina_indicator, analyze_solvency | roe, debt_ratio |
| assess_valuation_risk | get_daily_basic | pe, pb |
| assess_volatility_risk | get_history | close (计算波动率) |
| get_industry_performance | get_industry_list | industry_code |
| get_industry_leaders | get_industry_list | industry_code |
| get_concept_stocks | get_concept_list | concept_name |
| compare_industry_metrics | get_industry_performance | industry metrics |
| compare_industry_valuation | get_industry_performance | pe, pb |
| generate_stock_report | search_stock_news, search_company_announcements, search_research_reports | news, announcements, reports |
| generate_industry_report | search_industry_news | industry news |
| generate_comparison_report | search_stock, get_history | ts_codes, price_data |

---

## 四、测试工具链设计

基于依赖图谱，设计以下测试工具链：

### 4.1 基础工具链 (L1)

| 工具链ID | 工具组合 | 测试目的 | 预期步骤 |
|----------|----------|----------|----------|
| CHAIN-001 | search_stock → get_quote | 名称查询到价格 | 2步 |
| CHAIN-002 | search_stock → get_history | 名称查询到K线 | 2步 |
| CHAIN-003 | get_industry_list → get_industry_leaders | 行业到龙头 | 2步 |
| CHAIN-004 | get_concept_list → get_concept_stocks | 概念到成分股 | 2步 |

### 4.2 分析工具链 (L2)

| 工具链ID | 工具组合 | 测试目的 | 预期步骤 |
|----------|----------|----------|----------|
| CHAIN-005 | search_stock → get_history → calculate_statistics | 统计分析流程 | 3步 |
| CHAIN-006 | search_stock → get_history → calculate_technical_indicators | 技术分析流程 | 3步 |
| CHAIN-007 | search_stock → get_income_statement → calculate_financial_ratios | 财务比率计算 | 3步 |
| CHAIN-008 | search_stock → get_daily_basic → assess_valuation_risk | 估值风险评估 | 3步 |

### 4.3 完整工作流 (L3)

| 工具链ID | 工具组合 | 测试目的 | 预期步骤 |
|----------|----------|----------|----------|
| CHAIN-009 | search → get_history → calculate_indicators → analyze_trend → assess_risk | 单股完整分析 | 5步 |
| CHAIN-010 | get_industry_list → get_industry_leaders → get_daily_basic (多股) → compare | 行业龙头对比 | 4步 |
| CHAIN-011 | search (多股) → get_history → correlation → comparison_report | 多股对比报告 | 4步 |
| CHAIN-012 | search → get_financials → calculate_ratios → analyze_profitability → assess_financial_risk | 财务健康评估 | 5步 |

---

## 五、数据流转示例

### 示例 1: 个股技术分析完整流程

```python
# Step 1: 搜索股票
tool: search_stock
input: {"keyword": "茅台"}
output: {"ts_code": "600519.SH", "name": "贵州茅台"}

# Step 2: 获取历史数据
tool: get_history
input: {"ts_code": "600519.SH", "start_date": "2024-01-01", "end_date": "2024-03-21"}
output: {"kline_data": [{"trade_date": "20240320", "open": 1700, "high": 1720, "low": 1695, "close": 1715, "volume": 25000}, ...]}

# Step 3: 计算技术指标
tool: calculate_technical_indicators
input: {"kline_data": [...]}
output: {"macd": {"dif": 12.5, "dea": 11.8, "macd": 1.4}, "rsi": 58.2, "kdj": {"k": 65, "d": 60, "j": 75}}

# Step 4: 分析价格趋势
tool: analyze_price_trend
input: {"price_data": [1715, 1708, 1720, ...]}
output: {"trend": "upward", "support": 1680, "resistance": 1750}
```

### 示例 2: 行业分析完整流程

```python
# Step 1: 获取行业列表
tool: get_industry_list
input: {}
output: {"industries": [{"industry_code": "白酒", "name": "白酒"}, ...]}

# Step 2: 获取行业表现
tool: get_industry_performance
input: {"industry_code": "白酒"}
output: {"avg_change": 2.5, "avg_pe": 28.5, "stocks_count": 18}

# Step 3: 获取行业龙头
tool: get_industry_leaders
input: {"industry_code": "白酒", "top_n": 5}
output: {"leaders": [{"ts_code": "600519.SH", "name": "贵州茅台", "market_cap": 21000}, ...]}

# Step 4: 获取龙头估值
tool: get_daily_basic (并行调用)
input: [{"ts_code": "600519.SH"}, {"ts_code": "000858.SZ"}, ...]
output: [{"ts_code": "600519.SH", "pe": 32.5, "pb": 8.2}, ...]

# Step 5: 对比行业估值
tool: compare_industry_valuation
input: {"industries": ["白酒", "银行", "医药"]}
output: {"comparison": [{"industry": "白酒", "avg_pe": 28.5}, {"industry": "银行", "avg_pe": 6.2}, ...]}
```

---

## 六、测试股票列表

基于工具依赖图谱，推荐以下测试股票（覆盖不同场景）：

| 股票代码 | 名称 | 场景覆盖 |
|----------|------|----------|
| 600519.SH | 贵州茅台 | 大盘股、高PE、白酒龙头 |
| 000858.SZ | 五粮液 | 大盘股、白酒行业对比 |
| 000001.SZ | 平安银行 | 银行股、低PE |
| 300750.SZ | 宁德时代 | 创业板、新能源 |
| 688981.SH | 中芯国际 | 科创板、芯片概念 |
| 601318.SH | 中国平安 | 保险、金融 |
| 000002.SZ | 万科A | 房地产、周期性 |

---

## 七、工具链测试优先级

| 优先级 | 工具链ID | 说明 |
|--------|----------|------|
| P0 | CHAIN-001, CHAIN-002 | 基础查询链 |
| P0 | CHAIN-005, CHAIN-006 | 技术分析链 |
| P1 | CHAIN-009 | 单股完整分析 |
| P1 | CHAIN-010 | 行业龙头筛选 |
| P1 | CHAIN-012 | 财务健康评估 |
| P2 | CHAIN-011 | 多股对比报告 |
| P2 | CHAIN-003, CHAIN-004 | 行业/概念查询 |

---

*此文档用于指导 benchmark 工具链测试设计*
