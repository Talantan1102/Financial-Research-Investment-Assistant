# risk-assessment 工具详细参考

风险评分 0-100,数值越大越危险。三大维度:估值 / 财务 / 波动。

## 1. assess_stock_risk — 综合风险打分

**参数**:`symbol` (Yes)

**返回**
```json
{"symbol":"600519", "risk_score":45.2, "risk_level":"中风险",
 "risk_factors":["PE 超过 30,估值略高", "..."],
 "components": {"valuation":{...}, "financial":{...}, "volatility":{...}}}
```

**评级表**
| 分数 | 等级 | 适合投资者 |
|---|---|---|
| 0-30 | 低风险 | 保守型 |
| 30-50 | 中低风险 | 平衡型 |
| 50-70 | 中风险 | 大多数 |
| 70-85 | 中高风险 | 风险偏好型 |
| 85-100 | 高风险 | 激进型 |

## 2. assess_valuation_risk — 估值风险

**参数**
| Name | Type | Req | Default |
|---|---|---|---|
| symbol | string | Yes | - |
| industry_pe_avg | number | No | null (用于横向对标) |

**返回字段**:`pe, pe_ttm, pb, risk_score, risk_factors, assessment`

**阈值**
| PE | 评估 |
|---|---|
| <15 | 低风险,可能低估 |
| 15-30 | 估值合理 |
| 30-50 | 估值偏高 |
| >50 | 估值极高 |

## 3. assess_financial_risk — 财务风险

**参数**:`symbol` (Yes)

**返回字段**:`debt_to_assets, current_ratio, quick_ratio, risk_score, risk_factors, assessment`

**阈值**
| 资产负债率 | 评估 |
|---|---|
| <40% | 低风险 |
| 40-60% | 中等 |
| 60-80% | 高风险 |
| >80% | 极高 |

## 4. assess_volatility_risk — 波动风险

**参数**:`symbol` (Yes), `period` (No, default `60d`: `20d/60d/120d`)

**返回字段**:`annual_volatility, max_drawdown, risk_score, risk_factors, assessment`

**阈值(年化波动率)**
| 波动率 | 评估 |
|---|---|
| <20% | 低波动 |
| 20-30% | 中等 |
| 30-50% | 高波动 |
| >50% | 极高 |

## 5. check_risk_warnings — 风险预警清单

**参数**:`symbol` (Yes)

**返回**
```json
{"symbol":"600519", "warning_count":2,
 "warnings":[
   {"level":"medium", "type":"估值风险", "message":"PE(28.74)偏高"},
   {"level":"medium", "type":"财务风险", "message":"资产负债率(25.34%)需关注"}
 ],
 "has_critical_warning": false}
```

**level**:`low / medium / high / critical`

---

## 典型工作流

### 快速风险诊断
```
User: "茅台风险大吗?"
→ assess_stock_risk(symbol="600519")
```

### 全面风险报告
```
User: "全面评估比亚迪风险"
→ assess_stock_risk(symbol="002594")
→ assess_valuation_risk(symbol="002594")
→ assess_volatility_risk(symbol="002594")
→ check_risk_warnings(symbol="002594")
```

### 跨股对比
```
User: "茅台和宁德时代谁风险大?"
→ assess_stock_risk(symbol="600519")    # 45.2
→ assess_stock_risk(symbol="300750")    # 62.5
```

### 叠加行业对标(跨 skill)
```
→ sector-analysis.compare_industry_valuation(industries=["白酒"])
  拿到白酒行业 PE 均值 35.8
→ assess_valuation_risk(symbol="600519", industry_pe_avg=35.8)
```

---

## 约定

- 所有风险分 0-100,越大越危险(与 ROE 等"越大越好"的指标方向相反,注意别搞反)
- 响应:`{success, data}` / `{success, error: "未找到估值数据"}` 等
