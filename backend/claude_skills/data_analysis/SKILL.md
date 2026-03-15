---
name: data_analysis
description: 数据分析与可视化，支持智能分析、图表生成和 Text2SQL
version: "1.0"
tool_count: 4
---

# DataAnalysis Skill

## 概述

提供数据分析和可视化能力，包括智能数据分析、图表生成、自然语言转 SQL 等功能。

**功能**: 数据分析、图表生成、Text2SQL、金融指标计算
**适用数据**: JSON、CSV、表格数据
**输出**: 分析报告、可视化图表、SQL 查询

---

## 可用工具

### 1. analyze_data - 智能数据分析

**功能**: 智能数据分析，识别模式、趋势、异常，自动推荐可视化方式

**调用方式**: `data_analysis.analyze_data(data, analysis_type, context)`

**参数**:
- `data` (必需): 待分析的数据列表，每个元素是一个字典
  - 示例: `[{"month": "1月", "sales": 100}, {"month": "2月", "sales": 150}]`
- `analysis_type` (可选): 分析类型，默认 "auto"
  - 可选值: `"auto"` (自动), `"trend"` (趋势), `"distribution"` (分布), `"comparison"` (对比), `"correlation"` (相关性)
- `context` (可选): 分析上下文/问题，帮助理解数据背景

**返回示例**:
```json
{
  "success": true,
  "data": {
    "summary": "数据分析摘要...",
    "insights": [
      "发现 1: 销售额呈上升趋势",
      "发现 2: 2月份增长最为显著"
    ],
    "recommendations": ["建议关注..."],
    "visualization_type": "line_chart",
    "statistics": {
      "count": 12,
      "mean": 125.5,
      "max": 200,
      "min": 80
    }
  }
}
```

---

### 2. generate_chart - 图表生成

**功能**: 根据数据生成可视化图表

**调用方式**: `data_analysis.generate_chart(data, chart_type, title, x_key, y_key)`

**参数**:
- `data` (必需): 图表数据
- `chart_type` (必需): 图表类型
  - 可选值: `"line"` (折线), `"bar"` (柱状), `"pie"` (饼图), `"scatter"` (散点)
- `title` (可选): 图表标题
- `x_key` (可选): X轴数据字段名
- `y_key` (可选): Y轴数据字段名

**返回示例**:
```json
{
  "success": true,
  "data": {
    "chart_url": "/charts/chart_abc123.png",
    "chart_type": "bar",
    "title": "月度销售数据"
  }
}
```

---

### 3. text_to_sql - 自然语言转 SQL

**功能**: 将自然语言问题转换为 SQL 查询语句

**调用方式**: `data_analysis.text_to_sql(question, table_schema, dialect)`

**参数**:
- `question` (必需): 自然语言问题
  - 示例: `"查询2024年每个季度的总销售额"`
- `table_schema` (必需): 表结构信息
  - 示例: `"sales(id, product_name, amount, sale_date, region)"`
- `dialect` (可选): SQL 方言，默认 "postgresql"
  - 可选值: `"postgresql"`, `"mysql"`, `"sqlite"`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "sql": "SELECT EXTRACT(QUARTER FROM sale_date) as quarter, SUM(amount) as total FROM sales WHERE EXTRACT(YEAR FROM sale_date) = 2024 GROUP BY quarter ORDER BY quarter",
    "explanation": "按季度分组计算2024年销售总额"
  }
}
```

---

### 4. calculate_metrics - 计算金融指标

**功能**: 计算常用金融分析指标

**调用方式**: `data_analysis.calculate_metrics(data, metrics)`

**参数**:
- `data` (必需): 财务数据
  - 示例: `{"revenue": 1000, "cost": 600, "assets": 5000, "liabilities": 2000}`
- `metrics` (必需): 要计算的指标列表
  - 可选值: `["roe", "roa", "gross_margin", "net_margin", "current_ratio", "debt_ratio"]`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "roe": 0.133,
    "roa": 0.08,
    "gross_margin": 0.4,
    "net_margin": 0.25,
    "current_ratio": 1.5,
    "debt_ratio": 0.4,
    "interpretation": "ROE 为 13.3%，处于行业平均水平..."
  }
}
```

---

## 指标说明

| 指标 | 全称 | 计算公式 | 含义 |
|------|------|---------|------|
| ROE | 净资产收益率 | 净利润 / 净资产 | 衡量股东投资回报率 |
| ROA | 总资产收益率 | 净利润 / 总资产 | 衡量资产利用效率 |
| Gross Margin | 毛利率 | (收入-成本) / 收入 | 衡量产品盈利能力 |
| Net Margin | 净利率 | 净利润 / 收入 | 衡量整体盈利能力 |
| Current Ratio | 流动比率 | 流动资产 / 流动负债 | 衡量短期偿债能力 |
| Debt Ratio | 资产负债率 | 总负债 / 总资产 | 衡量财务杠杆水平 |

---

## 使用场景

| 场景 | 推荐工具 | 示例 |
|------|---------|------|
| 数据探索 | analyze_data | `analysis_type: "auto"` |
| 制作报表 | generate_chart | `chart_type: "bar"` |
| 数据库查询 | text_to_sql | `question: "查询Top10产品"` |
| 财务分析 | calculate_metrics | `metrics: ["roe", "roa"]` |

---

## 注意事项

1. **数据格式**: 数据应为列表格式，每个元素是字典
2. **字段命名**: 建议使用英文或拼音字段名，避免特殊字符
3. **数据量**: 大数据集建议先采样再分析
4. **Text2SQL**: 表结构描述越详细，生成的 SQL 越准确

---

## 错误处理

常见错误及解决方法:

| 错误 | 原因 | 解决方法 |
|------|------|---------|
| 数据格式错误 | data 不是列表 | 检查数据格式 |
| 缺少必要字段 | 未提供 x_key/y_key | 提供字段映射 |
| SQL 生成失败 | 表结构描述不清 | 补充字段类型信息 |
