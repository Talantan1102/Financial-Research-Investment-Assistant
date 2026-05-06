# deep-research 工具详细参考

L4 综合产出层。三个工具均为**编排器**,内部调用 L1-L3 多 skill 合成研报。

## 1. generate_stock_report — 个股研报

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| symbol | string | Yes | - | 股票代码 |
| report_type | string | No | comprehensive | comprehensive / valuation / financial |

**返回结构**
```json
{
  "symbol":"600519", "report_type":"comprehensive", "generated_at":"2026-03-20",
  "sections": {
    "company_overview": {name, fullname, industry, area, list_date, introduction},
    "valuation":        {pe, pe_ttm, pb, ps, total_mv, assessment},
    "financial":        {roe, roa, gross_margin, debt_to_assets, trend_roe[]},
    "market":           {current_price, change_percent, volume}
  }
}
```

**report_type 差异**
| 类型 | 聚焦 section |
|---|---|
| comprehensive | 全部四个 section |
| valuation | company_overview + valuation(深挖 PE/PB/PS) |
| financial | company_overview + financial(深挖 ROE/margin/trend) |

## 2. generate_industry_report — 行业研报

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| industry | string | Yes | - | 行业名 |
| focus | string | No | overview | overview / leaders / valuation / trend |

**返回结构**
```json
{
  "industry":"白酒", "focus":"overview",
  "sections": {
    "leaders":     {top_companies[], leader_count},
    "valuation":   {industry, pe_ttm, pb, ps, stock_count},
    "performance": {industry, avg_change, rank}
  }
}
```

**focus 差异**
| focus | 聚焦 |
|---|---|
| overview | 全景(三 section) |
| leaders | 龙头股细节 |
| valuation | 行业估值多维 |
| trend | 涨跌幅趋势 |

## 3. generate_comparison_report — 对比研报

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| symbols | array | Yes | - | 股票代码列表,≥2 |
| dimensions | array | No | 全部 | valuation / profitability / growth / risk |

**返回结构**
```json
{
  "symbols":["600519","000858"],
  "dimensions":["valuation","profitability","risk"],
  "data": {
    "600519": {name, industry, valuation:{pe,pb,total_mv}, profitability:{roe,gross_margin,net_margin}},
    "000858": {...}
  },
  "summary": {"lowest_pe":["000858",22.5], "highest_roe":["600519",32.58]}
}
```

**维度定义**
| 维度 | 涵盖指标 |
|---|---|
| valuation | PE, PB, PS, 市值 |
| profitability | ROE, 毛利率, 净利率 |
| growth | 营收增速, 利润增速 |
| risk | 波动率, 负债率 |

---

## 典型工作流

### 个股深度分析
```
User: "深度分析贵州茅台"
→ generate_stock_report(symbol="600519", report_type="comprehensive")
```

### 行业研究
```
User: "分析银行行业投资机会"
→ generate_industry_report(industry="银行", focus="overview")
```

### 个股对比
```
User: "对比茅台和五粮液"
→ generate_comparison_report(symbols=["600519","000858"], dimensions=["valuation","profitability"])
```

### 赛道研究(多步)
```
User: "我想投新能源赛道"
→ generate_industry_report(industry="新能源", focus="overview")     # 赛道全景
→ generate_comparison_report(symbols=["300750","002594","601012"])  # 龙头对比
→ generate_stock_report(symbol="300750")                            # 聚焦候选
```

---

## 编排细节(与底层 skill 的关系)

`generate_stock_report` 本质等价于以下调用序列:
```
market-data.get_stock_basic_info(symbol)
market-data.get_company_info(symbol)
market-data.get_daily_basic(symbol)
market-data.get_quote(symbol)
financial-analysis.calculate_financial_ratios(symbol)
financial-analysis.analyze_profitability(symbol, periods=4)
sector-analysis.compare_industry_valuation([industry])   # 可选对标
```

**模型决策规则**:用户要"深度/综合/研报/投资建议" → 调 `deep-research`;用户只要单一事实或单一指标 → 直接调对应底层 skill,**不要越级调 deep-research**。

## 约定

- `dimensions` 传空数组时返回全部 4 维;传列表时只返回指定维度
- `symbols` 至少 2 只,否则 `{success:false, error:"请提供至少2只股票进行对比"}`
- 数据缺失时对应 section 值可能为 null,消费前检查
- 响应:`{success, data}` / `{success, error}`
