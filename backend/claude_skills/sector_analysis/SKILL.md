---
name: sector_analysis
description: A股行业与概念板块分析，支持行业分类、概念板块、成分股查询、行业深度分析
version: "1.0"
tool_count: 7
---

# SectorAnalysis Skill

## 概述

提供 A 股市场行业分类和概念板块的深度分析能力，包括：
- 基础查询：行业列表、概念板块、成分股
- 深度分析：行业财务对比、估值对比、涨跌幅排名、龙头股识别

**适用场景**:
- 热点概念追踪（如AI、新能源、芯片等）
- 行业轮动分析
- 行业估值比较（找低估行业）
- 龙头股筛选

---

## 基础工具

### 1. get_industry_list - 获取行业列表

**功能**: 获取A股行业分类列表

**调用方式**: `sector_analysis.get_industry_list()`

---

### 2. get_concept_list - 获取概念列表

**功能**: 获取A股概念板块列表

**调用方式**: `sector_analysis.get_concept_list()`

---

### 3. get_concept_stocks - 获取概念成分股

**功能**: 获取指定概念板块的成分股列表

**调用方式**: 
- `sector_analysis.get_concept_stocks(concept_code="TS0")`
- `sector_analysis.get_concept_stocks(concept_name="国产芯片")`

---

## 深度分析工具 ⭐

### 4. compare_industry_metrics - 行业财务指标对比

**功能**: 对比不同行业的财务指标（ROE、毛利率、净利率等），识别盈利能力强的行业

**调用方式**: 
```python
sector_analysis.compare_industry_metrics(
    industries=["白酒", "银行", "医药", "新能源"],
    metric="roe"  # 可选: roe, gross_margin, net_margin, debt_ratio
)
```

**返回示例**:
```json
{
  "data": [
    {"industry": "白酒", "avg_value": 25.5, "stock_count": 18},
    {"industry": "医药", "avg_value": 18.2, "stock_count": 156},
    {"industry": "新能源", "avg_value": 15.3, "stock_count": 89},
    {"industry": "银行", "avg_value": 12.1, "stock_count": 42}
  ],
  "meta": {"metric": "roe", "metric_name": "净资产收益率"}
}
```

**应用场景**:
- "银行 vs 白酒，哪个行业ROE更高？"
- "哪些行业的盈利能力最强？"

---

### 5. compare_industry_valuation - 行业估值对比

**功能**: 对比不同行业的估值水平（PE、PB、PS），识别高估/低估行业

**调用方式**: 
```python
sector_analysis.compare_industry_valuation(
    industries=["白酒", "银行", "医药", "半导体"]
)
```

**返回示例**:
```json
{
  "data": [
    {"industry": "银行", "pe_ttm": 5.2, "pb": 0.8, "stock_count": 42},
    {"industry": "医药", "pe_ttm": 28.5, "pb": 3.2, "stock_count": 156},
    {"industry": "白酒", "pe_ttm": 35.8, "pb": 8.5, "stock_count": 18},
    {"industry": "半导体", "pe_ttm": 68.2, "pb": 5.8, "stock_count": 67}
  ]
}
```

**应用场景**:
- "当前哪些行业估值处于低位？"
- "半导体行业现在贵不贵？"

---

### 6. get_industry_performance - 行业涨跌幅排名

**功能**: 获取行业涨跌幅排名，追踪市场热点和冷门行业

**调用方式**: 
```python
sector_analysis.get_industry_performance(period="1d")  # 可选: 1d, 5d, 20d
```

**返回示例**:
```json
{
  "data": [
    {"industry": "半导体", "avg_change": 5.2, "stock_count": 67},
    {"industry": "人工智能", "avg_change": 3.8, "stock_count": 45},
    {"industry": "白酒", "avg_change": -1.2, "stock_count": 18},
    {"industry": "银行", "avg_change": -0.5, "stock_count": 42}
  ]
}
```

**应用场景**:
- "今天哪个行业涨得最好？"
- "最近一周资金在追捧哪些行业？"

---

### 7. get_industry_leaders - 行业龙头股

**功能**: 获取指定行业的龙头股（按市值、营收、利润排序）

**调用方式**: 
```python
sector_analysis.get_industry_leaders(
    industry="白酒",
    by="market_cap"  # 可选: market_cap, revenue, profit
)
```

**返回示例**:
```json
{
  "data": [
    {"ts_code": "600519.SH", "name": "贵州茅台", "total_mv": 2325000000000},
    {"ts_code": "000858.SZ", "name": "五粮液", "total_mv": 850000000000},
    {"ts_code": "000568.SZ", "name": "泸州老窖", "total_mv": 420000000000}
  ],
  "meta": {"industry": "白酒", "sort_by": "market_cap"}
}
```

**应用场景**:
- "白酒行业的龙头是谁？"
- "半导体行业里谁增长最快？"

---

## 深度研究集成建议

### 在 Deep Research 中使用行业分析

**研究步骤建议**:
1. **选题阶段**: 使用 `get_concept_list` 发现热点概念
2. **行业筛选**: 使用 `compare_industry_metrics` 筛选优质行业
3. **估值判断**: 使用 `compare_industry_valuation` 判断估值水平
4. **趋势确认**: 使用 `get_industry_performance` 确认资金趋势
5. **个股选择**: 使用 `get_industry_leaders` 选择行业龙头

**示例研究流程**:
```
研究主题: 寻找当前被低估的优质行业

Step 1: compare_industry_metrics(metric="roe") 
        → 发现白酒、医药ROE最高

Step 2: compare_industry_valuation(industries=["白酒", "医药", "银行"])
        → 发现银行PE最低(5倍)，白酒PE最高(35倍)

Step 3: get_industry_performance(period="20d")
        → 发现银行最近涨幅落后，可能被低估

Step 4: get_industry_leaders(industry="银行", by="market_cap")
        → 选择招商银行、平安银行等龙头

结论: 银行行业当前估值低(PE 5倍)，股息率高，适合价值投资
```

---

## 使用场景

| 场景 | 推荐工具 | 示例 |
|------|---------|------|
| 发现热点概念 | get_concept_list | 无参数 |
| 查询概念股 | get_concept_stocks | concept_name: "人工智能" |
| 对比行业盈利 | compare_industry_metrics | metric: "roe" |
| 找低估行业 | compare_industry_valuation | industries: ["银行", "保险"] |
| 追踪市场热点 | get_industry_performance | period: "5d" |
| 选行业龙头 | get_industry_leaders | industry: "白酒", by: "profit" |

---

## 注意事项

1. **数据更新**: 财务指标数据基于最新财报，估值数据基于最近交易日
2. **行业分类**: 行业分类基于Tushare标准，可能与实际业务有差异
3. **龙头股识别**: 默认按市值排序，也可按营收、利润排序
4. **对比范围**: 不指定industries时对比所有行业，数据量较大可能较慢
