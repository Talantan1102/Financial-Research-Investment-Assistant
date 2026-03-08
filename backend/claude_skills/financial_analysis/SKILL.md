---
name: financial_analysis
description: A股上市公司财务分析，支持财报查询、财务指标计算、财报对比分析
version: "1.0"
tool_count: 3
---

# FinancialAnalysis Skill

## 概述

提供A股上市公司全面的财务分析能力，基于Tushare API。支持三张财务报表查询、关键财务指标计算、多期财务数据对比分析。

**数据源**: Tushare Pro API
**支持市场**: A股（上海、深圳）
**报表类型**: 利润表、资产负债表、现金流量表

---

## 可用工具

### 1. get_financial_report - 获取财务报表

**功能**: 获取指定公司的财务报表数据（利润表、资产负债表、现金流量表）

**调用方式**: `financial_analysis.get_financial_report(symbol, report_type, period, report_count)`

**参数**:
- `symbol` (必需): 股票代码
- `report_type` (必需): 报表类型
  - `'income'`: 利润表
  - `'balance'`: 资产负债表
  - `'cashflow'`: 现金流量表
- `period` (可选): 报告期，格式 `YYYYMMDD`（如 `'20231231'`），不填返回最新
- `report_count` (可选): 返回报告期数量，默认 `1`，最多 `10`

**返回示例（利润表）**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519.SH",
    "report_type": "利润表",
    "report_count": 1,
    "reports": [
      {
        "ts_code": "600519.SH",
        "end_date": "20231231",
        "ann_date": "20240328",
        "report_type": "年报",
        "total_revenue": "15173000.00",
        "revenue": "15173000.00",
        "operate_profit": "9521000.00",
        "total_profit": "9628000.00",
        "net_income": "8127000.00",
        "net_income_parent": "8127000.00",
        "basic_eps": "6.4700",
        "diluted_eps": "6.4700"
      }
    ]
  }
}
```

**关键字段（利润表）**:
- `total_revenue`: 营业总收入（万元）
- `operate_profit`: 营业利润（万元）
- `net_income_parent`: 归母净利润（万元）
- `basic_eps`: 基本每股收益（元）

**关键字段（资产负债表）**:
- `total_assets`: 总资产（万元）
- `total_liabilities`: 总负债（万元）
- `total_equity`: 股东权益合计（万元）

**关键字段（现金流量表）**:
- `operating_cashflow`: 经营活动现金流（万元）
- `investing_cashflow`: 投资活动现金流（万元）
- `financing_cashflow`: 筹资活动现金流（万元）

---

### 2. calculate_financial_ratios - 计算财务指标

**功能**: 计算关键财务指标和比率（ROE、ROA、毛利率、净利率、资产负债率等）

**调用方式**: `financial_analysis.calculate_financial_ratios(symbol, period)`

**参数**:
- `symbol` (必需): 股票代码
- `period` (可选): 报告期，格式 `YYYYMMDD`，不填返回最新

**返回示例**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519.SH",
    "ratios": {
      "ts_code": "600519.SH",
      "end_date": "20231231",
      "eps": "6.4700",
      "roe": "32.58%",
      "roe_weighted": "32.85%",
      "roa": "22.45%",
      "gross_profit_margin": "91.23%",
      "net_profit_margin": "53.56%",
      "debt_to_assets": "25.34%",
      "current_ratio": "4.52",
      "quick_ratio": "4.21",
      "revenue_yoy": "18.20%",
      "net_profit_yoy": "15.89%",
      "ocf_to_revenue": "85.23%"
    },
    "summary": "ROE 32.58%（优秀）；毛利率 91.23%；净利率 53.56%；资产负债率 25.34%（低风险）"
  }
}
```

**指标分类**:

1. **盈利能力指标**:
   - `eps`: 每股收益
   - `roe`: 净资产收益率（>15%为优秀）
   - `roa`: 总资产收益率
   - `gross_profit_margin`: 毛利率
   - `net_profit_margin`: 净利率

2. **偿债能力指标**:
   - `debt_to_assets`: 资产负债率（<40%为低风险）
   - `current_ratio`: 流动比率（>2为良好）
   - `quick_ratio`: 速动比率

3. **增长能力指标**:
   - `revenue_yoy`: 营收同比增长率
   - `net_profit_yoy`: 净利润同比增长率

4. **现金流指标**:
   - `ocf_to_revenue`: 经营现金流/营收比率

---

### 3. compare_financial_data - 对比财务数据

**功能**: 对比分析财务数据的同比/环比变化（营收、净利润、ROE、ROA）

**调用方式**: `financial_analysis.compare_financial_data(symbol, indicator, periods)`

**参数**:
- `symbol` (必需): 股票代码
- `indicator` (必需): 对比指标
  - `'revenue'`: 营业总收入
  - `'net_profit'`: 归母净利润
  - `'roe'`: 净资产收益率
  - `'roa'`: 总资产收益率
- `periods` (可选): 对比期数，默认 `4`（最近4个报告期），范围 `2-20`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519.SH",
    "indicator": "营业总收入",
    "unit": "万元",
    "data_points": [
      {"end_date": "20231231", "value": 15173000.0},
      {"end_date": "20230930", "value": 11245000.0},
      {"end_date": "20230630", "value": 7568000.0},
      {"end_date": "20230331", "value": 3856000.0}
    ],
    "qoq_comparisons": [
      {
        "current_period": "20231231",
        "previous_period": "20230930",
        "change_rate": "34.93%",
        "trend": "上升"
      }
    ],
    "summary": "营业总收入最新值为 15173000.00，环比上升 34.93%。近3期平均增长率为 28.54%"
  }
}
```

---

## 工作流指导

### 典型分析流程

#### 1. 查看公司最新财务状况
```
用户: "茅台最新的财报怎么样？"

步骤:
1. 调用 financial_analysis.calculate_financial_ratios(symbol='600519')
2. 提取关键指标: ROE, 毛利率, 净利率, 资产负债率
3. 格式化输出
```

#### 2. 深度财报分析
```
用户: "帮我分析一下茅台的利润表"

步骤:
1. 调用 financial_analysis.get_financial_report(symbol='600519', report_type='income')
2. 提取关键数据
3. 结合 calculate_financial_ratios 分析盈利能力
4. 输出综合分析
```

#### 3. 财务趋势分析
```
用户: "茅台近一年营收增长趋势如何？"

步骤:
1. 调用 financial_analysis.compare_financial_data(symbol='600519', indicator='revenue', periods=4)
2. 分析环比和同比变化
3. 评估增长趋势
```

#### 4. 对比两家公司财务
```
用户: "对比茅台和五粮液的盈利能力"

步骤:
1. 分别调用 calculate_financial_ratios('600519') 和 calculate_financial_ratios('000858')
2. 对比关键指标: ROE, 毛利率, 净利率
3. 分析优劣势
```

---

## 注意事项

### 1. 报告期格式
- **格式**: `YYYYMMDD`（如 `'20231231'`）
- **季报时间**: Q1=0331, Q2=0630, Q3=0930, Q4=1231
- 不指定 `period` 时自动返回最新报告期

### 2. 指标解读
- **ROE > 15%**: 优秀
- **ROE 10-15%**: 良好
- **ROE < 10%**: 一般
- **资产负债率 < 40%**: 低风险
- **资产负债率 40-60%**: 中等风险
- **资产负债率 > 60%**: 高风险

### 3. 同比/环比计算
- **环比**: 需至少2期数据
- **同比**: 需至少5期数据（4个季度+1）
- 数据不足时仅返回环比

### 4. 友好的输出格式
示例:
```
贵州茅台 (600519) 2023年度财务分析

【盈利能力】优秀
- ROE: 32.58% (行业领先)
- 毛利率: 91.23% (极高)
- 净利率: 53.56% (优秀)

【财务稳健性】极佳
- 资产负债率: 25.34% (低)
- 流动比率: 4.52 (充足)

【成长性】良好
- 营收同比: +18.20%
- 净利润同比: +15.89%
```

---

**Skill 版本**: v1.0
**最后更新**: 2026-03-08
