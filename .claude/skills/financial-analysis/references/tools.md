# financial-analysis 工具详细参考

A 股上市公司财务分析。数据源 Tushare Pro,季度更新(Q1/H1/Q3/Annual)。

## 1. calculate_financial_ratios — 核心比率一次算

**参数**:`symbol` (Yes), `period` (No, `YYYYMMDD`,空则最新)

**返回关键字段**:`roe, roe_dt, roa, gross_margin, net_profit_margin, debt_to_assets, current_ratio, quick_ratio, inventory_turnover, receivables_turnover, assets_turnover`

## 2. get_income_statement — 利润表

**参数**:`symbol` (Yes), `start_date` / `end_date` (No)

**返回字段**:`total_revenue, revenue, operate_profit, total_profit, n_income, n_income_attr_p, basic_eps, diluted_eps`

## 3. get_balance_sheet — 资产负债表

**参数**:同上

**返回字段**:`total_assets, total_cur_assets, total_nca, total_liab, total_cur_liab, total_ncl, total_hldr_eqy_exc_min_int`

## 4. get_cash_flow — 现金流量表

**参数**:同上

**关键字段**
| 字段 | 含义 | 单位 |
|---|---|---|
| n_cashflow_act | 经营活动现金流净额 | 万元 |
| n_cashflow_inv_act | 投资活动现金流净额 | 万元 |
| n_cashflow_fnc_act | 筹资活动现金流净额 | 万元 |
| c_cash_equ_end_period | 期末现金余额 | 万元 |

## 5. get_fina_indicator — 100+ 财务指标

一站式指标接口,支持时间序列。

**参数**:`symbol` (Yes), `start_date` / `end_date` (No)

**示例**:`get_fina_indicator(symbol="600519", start_date="20200101", end_date="20231231")`

## 6. analyze_profitability — 盈利能力趋势

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| symbol | string | Yes | - | - |
| periods | integer | No | 8 | 分析季度数 |

**返回**:`avg_roe, avg_gross_margin, roe_trend (up/down/sideways), trends[], assessment`

**评级表**
| ROE | 级别 |
|---|---|
| >20% | 优秀 |
| 15-20% | 良好 |
| 10-15% | 一般 |
| <10% | 较弱 |

## 7. analyze_solvency — 偿债能力

**参数**:`symbol` (Yes), `period` (No, `YYYYMMDD`)

**返回字段**:`current_ratio, quick_ratio, cash_ratio, debt_to_assets, debt_to_equity, equity_to_debt, interest_coverage, assessment`

**评级标准**
| 级别 | 条件 |
|---|---|
| 优秀 | 流动比 >2 且 负债率 <50% |
| 良好 | 流动比 >1.5 且 负债率 <60% |
| 一般 | 流动比 >1 且 负债率 <70% |
| 较弱 | 流动比 <1 或 负债率 >70% |

---

## 典型工作流

### 快速财务体检
```
User: "茅台财务状况怎么样?"
→ calculate_financial_ratios(symbol="600519")
→ analyze_profitability(symbol="600519", periods=4)
→ analyze_solvency(symbol="600519")
```

### 三表查询
```
User: "看看茅台最新的三张报表"
→ get_income_statement(symbol="600519")
→ get_balance_sheet(symbol="600519")
→ get_cash_flow(symbol="600519")
```

### ROE 趋势
```
User: "茅台近两年 ROE 趋势"
→ get_fina_indicator(symbol="600519", start_date="20220101")
→ analyze_profitability(symbol="600519", periods=8)
```

---

## 基准值表(重要)

| 指标 | 优秀 | 良好 | 一般 | 较弱 |
|---|---|---|---|---|
| ROE | >20% | 15-20% | 10-15% | <10% |
| 毛利率 | >50% | 30-50% | 15-30% | <15% |
| 净利率 | >20% | 10-20% | 5-10% | <5% |
| 资产负债率 | <40% | 40-60% | 60-80% | >80% |
| 流动比率 | >2 | 1.5-2 | 1-1.5 | <1 |

## 约定

- **报告期**:`YYYYMMDD`。季度:Q1=`0331`, 中报=`0630`, Q3=`0930`, 年报=`1231`
- **报表单位**:万元
- **响应**:`{success, data}` / `{success, error: "未找到财务指标数据"}`
