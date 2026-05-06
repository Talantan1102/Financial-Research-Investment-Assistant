# market-data 工具详细参考

基于 Tushare Pro API,覆盖 A 股沪深两市。数据近实时(~15 分钟延迟)。

## 1. get_quote — 股票实时行情

获取当前价格、涨跌、成交量/额。

**参数**
| Name | Type | Req | 说明 |
|---|---|---|---|
| symbol | string | Yes | 股票代码(`600519` / `sh600519` / `600519.SH` 均可) |

**返回示例**
```json
{"success": true, "data": {
  "ts_code": "600519.SH", "name": "贵州茅台",
  "nowPri": "1850.50", "increase": "25.30", "increPer": "1.39",
  "todayStartPri": "1840.00", "yestodEndPri": "1825.20",
  "todayMax": "1865.00", "todayMin": "1835.00",
  "traAmount": "125000", "traNumber": "231250000",
  "update_time": "20260308"
}}
```

## 2. search_stock — 股票搜索

**参数**:`keyword` (string, Yes) — 代码或名称。

**示例**:`search_stock(keyword="茅台")` / `search_stock(keyword="600519")`

## 3. get_history — 历史 K 线

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| symbol | string | Yes | - | 股票代码 |
| period | string | No | daily | daily / weekly / monthly |
| start_date | string | No | null | YYYYMMDD |
| end_date | string | No | null | YYYYMMDD |
| limit | integer | No | 100 | 条数上限 |

**返回字段**:`trade_date, open, high, low, close, volume, amount`

**示例**
- 近 30 日:`get_history(symbol="600519", limit=30)`
- 周线:`get_history(symbol="600519", period="weekly", limit=52)`
- 区间:`get_history(symbol="600519", start_date="20240101", end_date="20240301")`

## 4. get_stock_basic_info — 基础信息

**参数**:`symbol` (Yes) → 返回 `ts_code, name, industry, area, list_date, market, exchange`

## 5. get_company_info — 公司详细信息

**参数**:`symbol` (Yes) → 返回 `fullname, introduction, website, email, address` 等

## 6. get_daily_basic — 每日估值指标

**参数**
| Name | Type | Req | Default |
|---|---|---|---|
| symbol | string | No | null(空则返回全市场) |
| trade_date | string | No | null(默认最近交易日) |

**返回字段**:`pe, pe_ttm, pb, ps, total_mv, circ_mv, turnover_rate`

## 7. get_money_flow — 资金流向

**参数**:`symbol` (Yes), `trade_date` / `start_date` / `end_date` (可选)

**返回关键字段**:`net_mf_amount`(主力净流入)、`buy_lg_vol`、`sell_lg_vol`

## 8. get_top_list — 龙虎榜

**参数**:`trade_date` (No, 默认最近), `limit` (No, 50)

## 9. get_limit_list — 涨跌停统计

**参数**:`trade_date` (No), `limit_type` (No, "U" / "D" / null 全部)

## 10. get_north_money — 北向资金

**参数**:`start_date` / `end_date` (可选) → 返回 `north_money, south_money`

## 11. get_margin — 融资融券

**参数**:`symbol` (No, 空则全市场), `start_date` / `end_date` (可选)

**返回字段**:`rzye`(融资余额)、`rqye`(融券余额)、`rzmre`(融资买入额)

---

## 典型工作流

### Quick quote
```
User: "茅台股价多少?"
→ get_quote(symbol="600519")
```

### Search then quote
```
User: "茅台今天的股价"
→ search_stock(keyword="茅台")    # 得到 600519
→ get_quote(symbol="600519")
```

### Trend analysis
```
User: "茅台最近一个月走势"
→ get_history(symbol="600519", limit=30)
```

### Full market snapshot
```
User: "给我茅台的全貌"
→ get_quote + get_stock_basic_info + get_daily_basic
  + get_money_flow + get_company_info
```

---

## 约定

- **代码格式**:推荐纯 6 位;也接受 `sh600519` / `600519.SH`
- **日期格式**:`YYYYMMDD`,无分隔符
- **响应**:成功 `{success: true, data}` / 失败 `{success: false, error}`
- **时效**:实时 ~15 分钟延迟;每日指标收盘后更新
