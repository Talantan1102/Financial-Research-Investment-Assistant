# data-analysis 工具详细参考

通用数值计算 + 股票量价分析。

## 1. calculate_statistics — 统计指标

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| data | array | Yes | - | 数值数组 |
| metrics | array | No | 全部 | mean / std / min / max / median |

**返回**:`{mean, std, min, max, median, count}`

## 2. analyze_price_trend — 价格趋势

**参数**:`symbol` (Yes), `period` (No, default `60d`: `20d/60d/120d`)

**返回字段**:`current_price, period_high, period_low, price_change, price_change_percent, trend_direction (up/down/sideways), trend_strength, volatility, avg_volume`

## 3. calculate_correlation — 相关性

**参数**:`symbol1` (Yes), `symbol2` (Yes), `period` (No, default `60d`)

**返回**:`{correlation (-1~+1), interpretation}`

**解读表**
| 相关系数 | 描述 |
|---|---|
| ≥0.8 | 强相关 |
| 0.5-0.8 | 中等相关 |
| 0.3-0.5 | 弱相关 |
| <0.3 | 几乎无关 |
| <0 | 负相关(反向) |

## 4. calculate_technical_indicators — 技术指标

**参数**:`symbol` (Yes), `indicators` (No, default 全部:`ma/rsi/macd/boll`)

**返回结构**
```json
{
  "ma": {"ma5":..., "ma10":..., "ma20":..., "ma60":...},
  "rsi": {"rsi": ...},
  "macd": {"macd":..., "signal":..., "histogram":...},
  "boll": {"upper":..., "middle":..., "lower":...}
}
```

**指标信号**
| 指标 | 买入信号 | 卖出信号 |
|---|---|---|
| MA | 价 > MA20 | 价 < MA20 |
| RSI | <30 超卖 | >70 超买 |
| MACD | 金叉(MACD>Signal) | 死叉 |
| Bollinger | 价 < Lower | 价 > Upper |

**最小数据量**:MA60 需 60 日,MACD 需 26 日,RSI 需 14 日,Bollinger 需 20 日

## 5. normalize_data — 标准化

**参数**:`data` (Yes), `method` (No, default `minmax`: `minmax / zscore`)

| Method | 输出范围 | 适用 |
|---|---|---|
| minmax | [0, 1] | 需有界值 |
| zscore | mean=0, std=1 | 有异常值 |

## 6. generate_chart_data — 图表数据

**参数**:`symbol` (Yes), `chart_type` (No, default `line`: `candlestick/line/bar/area`), `period` (No, default `60d`)

**图表格式**
| type | 字段 |
|---|---|
| candlestick | date, open, high, low, close, volume |
| line / bar | date, value |
| area | date, value, volume |

---

## 典型工作流

### 技术面分析
```
User: "茅台技术面如何?"
→ calculate_technical_indicators(symbol="600519", indicators=["ma","rsi","macd"])
→ analyze_price_trend(symbol="600519", period="60d")
```

### 组合相关性
```
User: "茅台和五粮液相关吗?"
→ calculate_correlation(symbol1="600519", symbol2="000858", period="120d")
```

### 图表数据
```
User: "给我茅台 K 线"
→ generate_chart_data(symbol="600519", chart_type="candlestick", period="120d")
```

---

## 约定

- **相关 ≠ 因果**:高相关只说明同向波动,不意味着因果关系
- **周期枚举**:`20d / 60d / 120d`
- **响应**:`{success, data}` / `{success, error: "历史数据不足"}` 等
