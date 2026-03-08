---
name: financial_analysis
description: A股上市公司财务分析，支持财报查询、财务指标计算、财报对比分析
allowed_tools: [Bash, Read]
---

# FinancialAnalysis Skill

## 📊 概述

提供A股上市公司全面的财务分析能力，基于Tushare API。支持三张财务报表查询、关键财务指标计算、多期财务数据对比分析。

**数据源**: Tushare Pro API
**支持市场**: A股（上海、深圳）
**报表类型**: 利润表、资产负债表、现金流量表

---

## 🛠️ 可用工具

### 1. get_financial_report - 获取财务报表

**功能**: 获取指定公司的财务报表数据（利润表、资产负债表、现金流量表）

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
from app.data.tushare_client import get_tushare_client
client = get_tushare_client()

# 获取利润表
ts_code = client._normalize_stock_code('600519')
df = client.get_api().income(
    ts_code=ts_code,
    period='20231231',
    fields='ts_code,ann_date,end_date,report_type,total_revenue,revenue,operate_profit,total_profit,n_income,n_income_attr_p,basic_eps,diluted_eps'
)
import json
result = df.head(1).to_dict('records')
print(json.dumps(result, ensure_ascii=False, indent=2))
"
```

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

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
from app.data.tushare_client import get_tushare_client
client = get_tushare_client()

ts_code = client._normalize_stock_code('600519')
df = client.get_api().fina_indicator(
    ts_code=ts_code,
    period='20231231',
    fields='ts_code,ann_date,end_date,eps,roe,roe_waa,roe_dt,roa,grossprofit_margin,netprofit_margin,debt_to_assets,current_ratio,quick_ratio,ocf_to_or,or_last_year,op_yoy,ebt_yoy,netprofit_yoy,dt_netprofit_yoy'
)
import json
result = df.head(1).to_dict('records')
print(json.dumps(result, ensure_ascii=False, indent=2))
"
```

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
      "ann_date": "20240328",

      "eps": "6.4700",
      "roe": "32.58%",
      "roe_weighted": "32.85%",
      "roe_diluted": "32.58%",
      "roa": "22.45%",
      "gross_profit_margin": "91.23%",
      "net_profit_margin": "53.56%",

      "debt_to_assets": "25.34%",
      "current_ratio": "4.52",
      "quick_ratio": "4.21",

      "revenue_yoy": "18.20%",
      "operating_profit_yoy": "16.87%",
      "profit_before_tax_yoy": "17.12%",
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
   - `operating_profit_yoy`: 营业利润同比增长率
   - `net_profit_yoy`: 净利润同比增长率

4. **现金流指标**:
   - `ocf_to_revenue`: 经营现金流/营收比率

---

### 3. compare_financial_data - 对比财务数据

**功能**: 对比分析财务数据的同比/环比变化（营收、净利润、ROE、ROA）

**使用方法**:
```bash
cd /Users/talantan/.openclaw/workspace-dev/external/financial-research-assistant/backend
python -c "
from app.data.tushare_client import get_tushare_client
client = get_tushare_client()

ts_code = client._normalize_stock_code('600519')

# 获取利润表数据（用于对比营收和净利润）
df = client.get_api().income(
    ts_code=ts_code,
    fields='ts_code,end_date,total_revenue,n_income_attr_p'
)
import json
result = df.head(4).to_dict('records')
print(json.dumps(result, ensure_ascii=False, indent=2))
"
```

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
      {
        "end_date": "20231231",
        "value": 15173000.0,
        "formatted_value": "15173000.00"
      },
      {
        "end_date": "20230930",
        "value": 11245000.0,
        "formatted_value": "11245000.00"
      },
      {
        "end_date": "20230630",
        "value": 7568000.0,
        "formatted_value": "7568000.00"
      },
      {
        "end_date": "20230331",
        "value": 3856000.0,
        "formatted_value": "3856000.00"
      }
    ],
    "qoq_comparisons": [
      {
        "current_period": "20231231",
        "previous_period": "20230930",
        "current_value": "15173000.00",
        "previous_value": "11245000.00",
        "change": "3928000.00",
        "change_rate": "34.93%",
        "trend": "上升"
      }
    ],
    "yoy_comparisons": [
      {
        "current_period": "20231231",
        "year_ago_period": "20221231",
        "current_value": "15173000.00",
        "year_ago_value": "12835000.00",
        "change": "2338000.00",
        "change_rate": "18.21%",
        "trend": "上升"
      }
    ],
    "summary": "营业总收入最新值为 15173000.00，环比上升 34.93%。近3期平均增长率为 28.54%"
  }
}
```

**对比类型**:
- **环比 (QoQ)**: 与上一个报告期对比
- **同比 (YoY)**: 与去年同期对比（需至少5期数据）

---

## 📋 工作流指导

### 典型分析流程

#### 1. 查看公司最新财务状况
```
用户: "茅台最新的财报怎么样？"

步骤:
1. 使用 calculate_financial_ratios('600519') 获取最新财务指标
2. 提取关键指标: ROE, 毛利率, 净利率, 资产负债率
3. 格式化输出:
   "贵州茅台 (600519) 2023年报财务指标：
   - ROE: 32.58% (优秀)
   - 毛利率: 91.23%
   - 净利率: 53.56%
   - 资产负债率: 25.34% (低风险)"
```

#### 2. 深度财报分析
```
用户: "帮我分析一下茅台的利润表"

步骤:
1. 使用 get_financial_report(symbol='600519', report_type='income', report_count=1)
2. 提取关键数据:
   - 营业总收入
   - 营业利润
   - 归母净利润
   - 基本每股收益
3. 结合 calculate_financial_ratios 分析盈利能力
4. 输出综合分析
```

#### 3. 财务趋势分析
```
用户: "茅台近一年营收增长趋势如何？"

步骤:
1. 使用 compare_financial_data(symbol='600519', indicator='revenue', periods=4)
2. 分析环比和同比变化:
   - Q4 vs Q3: 环比增长 34.93%
   - 2023 vs 2022: 同比增长 18.21%
3. 计算平均增长率
4. 评估增长趋势（加速/减速/稳定）
```

#### 4. 多维度财务健康检查
```
用户: "评估茅台的财务健康状况"

步骤:
1. 获取最新财务指标 (calculate_financial_ratios)
2. 分析各维度:
   - 盈利能力: ROE, ROA, 毛利率
   - 偿债能力: 资产负债率, 流动比率
   - 增长能力: 营收同比, 利润同比
   - 现金流: 经营现金流/营收比率
3. 综合评分和建议
```

#### 5. 对比两家公司财务
```
用户: "对比茅台和五粮液的盈利能力"

步骤:
1. 分别获取两家公司的财务指标:
   - calculate_financial_ratios('600519')
   - calculate_financial_ratios('000858')
2. 对比关键指标:
   - ROE: 32.58% vs XX%
   - 毛利率: 91.23% vs XX%
   - 净利率: 53.56% vs XX%
3. 分析优劣势
```

---

## ⚠️ 注意事项

### 1. 报告期格式
- **格式**: `YYYYMMDD`（如 `'20231231'`）
- **季报时间**: Q1=0331, Q2=0630, Q3=0930, Q4=1231
- 不指定 `period` 时自动返回最新报告期

### 2. 报表类型选择
- **利润表 (income)**: 分析收入、利润、每股收益
- **资产负债表 (balance)**: 分析资产结构、负债水平
- **现金流量表 (cashflow)**: 分析现金流健康状况

### 3. 数据时效性
- 财报数据在正式公告后更新（年报约4月底，季报约1个月后）
- `ann_date` 为公告日期
- `end_date` 为报告期截止日

### 4. 指标解读
- **ROE > 15%**: 优秀
- **ROE 10-15%**: 良好
- **ROE < 10%**: 一般
- **资产负债率 < 40%**: 低风险
- **资产负债率 40-60%**: 中等风险
- **资产负债率 > 60%**: 高风险

### 5. 同比/环比计算
- **环比**: 需至少2期数据
- **同比**: 需至少5期数据（4个季度+1）
- 数据不足时仅返回环比

### 6. API字段映射

Tushare API 字段对照：
```
total_revenue → 营业总收入
n_income_attr_p → 归母净利润
total_assets → 总资产
total_liab → 总负债
n_cashflow_act → 经营活动现金流
roe → 净资产收益率
grossprofit_margin → 毛利率
netprofit_margin → 净利率
debt_to_assets → 资产负债率
```

---

## 📚 参考资源

### Tushare API 文档
- **财务报表**: https://tushare.pro/document/2?doc_id=33
- **财务指标**: https://tushare.pro/document/2?doc_id=79

### 相关代码
- **MCP Skill**: `backend/app/mcp_server/skills/financial_analysis.py`
- **数据客户端**: `backend/app/data/tushare_client.py`

---

## 🎯 最佳实践

### 1. 先看指标再看报表
- 使用 `calculate_financial_ratios` 快速了解财务健康状况
- 发现异常指标后，再用 `get_financial_report` 深入分析

### 2. 关注趋势而非单点
- 使用 `compare_financial_data` 分析多期数据
- 判断趋势：加速增长/稳定增长/增长放缓/下滑

### 3. 多维度综合评估
- 盈利能力 + 偿债能力 + 增长能力 + 现金流
- 四个维度缺一不可

### 4. 行业对比
- 不同行业的合理指标范围不同
- 白酒行业: 高毛利率（>80%）正常
- 制造业: 资产负债率可能较高

### 5. 友好的输出格式
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

【综合评价】
财务状况优异，盈利能力强，负债率低，现金流充沛。
```

---

## 🔧 故障排查

### 常见问题

**1. "未找到财务数据"**
- 检查股票代码是否正确
- 确认公司是否已发布对应期间财报
- 新上市公司可能缺少历史数据

**2. "报表类型错误"**
- 仅支持: `income`, `balance`, `cashflow`
- 检查拼写

**3. "报告期数量超限"**
- `report_count` 必须在 1-10 之间
- 需要更多历史数据请分批查询

**4. "对比期数不足"**
- 环比至少需要2期数据
- 同比至少需要5期数据（一年+1）

**5. "指标数据为N/A"**
- 部分公司可能缺少某些字段
- 检查原始数据是否存在

---

**Skill 版本**: v1.0
**最后更新**: 2026-03-08
**维护者**: Financial Research Team
