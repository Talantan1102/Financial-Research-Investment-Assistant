# sector-analysis 工具详细参考

A 股行业分类 + 概念板块。每日收盘后更新。

## 1. get_industry_list — 行业列表

**参数**:无

**返回**:`[{code, name}]`,共 ~109 个行业

## 2. get_industry_performance — 行业表现

**参数**:`period` (No, default `1d`: `1d / 5d / 20d`)

**返回**:`[{industry, avg_change, stock_count, rank}]`

## 3. get_industry_leaders — 行业龙头

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| industry | string | Yes | - | 行业名(如"白酒") |
| by | string | No | market_cap | market_cap / revenue / profit |
| limit | integer | No | 10 | 返回数 |

**返回**:`[{ts_code, name, total_mv, rank}]`

## 4. compare_industry_metrics — 财务指标对比

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| industries | array | No | null(全部) | 行业名列表 |
| metric | string | No | roe | roe / gross_margin / net_margin / debt_ratio |

**返回**:`[{industry, avg_value, stock_count, rank}]`

## 5. compare_industry_valuation — 估值对比

**参数**:`industries` (No, null 为全部)

**返回字段**:每个行业的 `pe_ttm, pb, ps, stock_count`

**估值解读**
| PE | 判断 |
|---|---|
| <10 | 通常低估(如银行) |
| 10-25 | 估值合理 |
| 25-40 | 溢价估值 |
| >40 | 昂贵 |

## 6. get_concept_list — 概念列表

**参数**:无

**返回**:`[{code, name}]`,共 ~385 个概念

## 7. get_concept_stocks — 概念成分股

**参数**
| Name | Type | Req | 说明 |
|---|---|---|---|
| concept_code | string | No | 概念代码 |
| concept_name | string | No | 概念名(如"人工智能") |

**注意**:`concept_code` 和 `concept_name` 二选一,不要同时传。

**返回**:`[{ts_code, name}]`

---

## 典型工作流

### 找低估行业
```
User: "哪些行业估值低?"
→ compare_industry_metrics(metric="roe")           # 先找高 ROE
→ compare_industry_valuation(industries=[...])     # 再看 PE
```

### 追踪热点
```
User: "最近热点是什么?"
→ get_industry_performance(period="5d")   # 半导体 +8.5%, AI +6.2%
→ get_concept_stocks(concept_name="半导体")
```

### 行业对比
```
User: "银行 vs 保险"
→ compare_industry_metrics(industries=["银行","保险"], metric="roe")
→ compare_industry_valuation(industries=["银行","保险"])
→ get_industry_leaders(industry="银行")
→ get_industry_leaders(industry="保险")
```

### 概念板块探索
```
User: "AI 板块有哪些股?"
→ get_concept_list()                                # 如果需要代码
→ get_concept_stocks(concept_name="人工智能")
```

---

## 为其他 skill 提供基线

`compare_industry_valuation` 的行业 PE 均值,可作为 `risk-assessment.assess_valuation_risk` 的 `industry_pe_avg` 参数,实现跨层校准(见 ARCHITECTURE 的"侧向依赖")。

## 约定

- 排序字段枚举:`market_cap / revenue / profit`
- 对比指标枚举:`roe / gross_margin / net_margin / debt_ratio`
- 响应:`{success, data}` / `{success, error: "行业名称不能为空"}` 等
