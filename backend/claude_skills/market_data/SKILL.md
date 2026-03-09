---
name: market_data
description: 股票市场行情数据查询，支持A股实时行情、历史数据、龙虎榜等
version: "1.0"
tool_count: 8
---

# MarketData Skill

## 概述

提供全面的股票市场行情数据查询能力，基于 Tushare API。支持实时行情、历史K线、龙虎榜、资金流向、涨跌停统计等数据。

**数据源**: Tushare Pro API
**支持市场**: A股（上海、深圳）、港股
**实时性**: 准实时数据（延迟约15分钟）

---

## 可用工具

### 1. get_quote - 获取实时行情

**功能**: 查询指定股票的实时行情数据（当前价格、涨跌幅、成交量等）

**调用方式**: `market_data.get_quote(symbol)`

**参数**:
- `symbol` (必需): 股票代码
  - 支持格式: `'600519'` (纯数字), `'sh600519'` (带市场前缀), `'600519.SH'` (Tushare格式)
  - 示例: `'600519'` (贵州茅台), `'000001'` (平安银行), `'1810.HK'` (小米集团)

**返回示例**:
```json
{
  "success": true,
  "data": {
    "gid": "sh600519",
    "ts_code": "600519.SH",
    "name": "贵州茅台",
    "nowPri": "1850.50",
    "increase": "25.30",
    "increPer": "1.39",
    "todayStartPri": "1840.00",
    "yestodEndPri": "1825.20",
    "todayMax": "1865.00",
    "todayMin": "1835.00",
    "traAmount": "125000",
    "traNumber": "231250000",
    "update_time": "20260308"
  }
}
```

**关键字段**:
- `nowPri`: 当前价格
- `increPer`: 涨跌幅（%）
- `traAmount`: 成交量（手）
- `traNumber`: 成交额（元）

---

### 2. search_stock - 搜索股票

**功能**: 根据股票代码或名称关键词搜索股票信息

**调用方式**: `market_data.search_stock(keyword)`

**参数**:
- `keyword` (必需): 搜索关键词
  - 股票代码: `'600519'`, `'sh600519'`
  - 股票名称: `'茅台'`, `'平安银行'`

**返回**: 与 `get_quote` 相同格式，包含匹配的股票信息

**注意**: 当前实现仅支持精确代码匹配，名称模糊搜索需要遍历股票列表

---

### 3. get_history - 获取历史K线数据

**功能**: 获取股票历史K线数据，支持日线、周线、月线

**调用方式**: `market_data.get_history(symbol, period, start_date, end_date, limit)`

**参数**:
- `symbol` (必需): 股票代码
- `period` (可选): 周期类型，默认 `'daily'`
  - `'daily'`: 日线
  - `'weekly'`: 周线
  - `'monthly'`: 月线
- `start_date` (可选): 开始日期，格式 `YYYYMMDD`
- `end_date` (可选): 结束日期，格式 `YYYYMMDD`
- `limit` (可选): 返回条数限制，默认 `100`

**返回示例**:
```json
{
  "success": true,
  "data": [
    {
      "trade_date": "20260308",
      "open": "1840.00",
      "high": "1865.00",
      "low": "1835.00",
      "close": "1850.50",
      "volume": "125000",
      "amount": "231250000"
    }
  ],
  "meta": {
    "count": 1,
    "period": "daily"
  }
}
```

---

### 4. get_stock_basic_info - 获取股票基础信息

**功能**: 获取股票基础信息（行业、地区、上市日期等）

**调用方式**: `market_data.get_stock_basic_info(symbol)`

**参数**:
- `symbol` (必需): 股票代码

**返回示例**:
```json
{
  "success": true,
  "data": {
    "ts_code": "600519.SH",
    "name": "贵州茅台",
    "industry": "白酒",
    "area": "贵州",
    "list_date": "20010827",
    "market": "主板",
    "exchange": "SSE"
  }
}
```

---

### 5. get_top_list - 获取龙虎榜数据

**功能**: 获取龙虎榜每日明细，包含机构买卖数据

**调用方式**: `market_data.get_top_list(trade_date, limit)`

**参数**:
- `trade_date` (可选): 交易日期，格式 `YYYYMMDD`，默认最近交易日
- `limit` (可选): 返回条数限制，默认 `50`

**返回示例**:
```json
{
  "success": true,
  "data": [
    {
      "trade_date": "20260308",
      "ts_code": "600519.SH",
      "name": "贵州茅台",
      "close": "1850.50",
      "pct_change": "1.39",
      "turnover_rate": "0.52",
      "amount": "2312500000",
      "reason": "日涨幅偏离值达7%"
    }
  ],
  "meta": {
    "count": 1
  }
}
```

---

### 6. get_money_flow - 获取资金流向

**功能**: 获取个股资金流向数据（主力、散户净流入等）

**调用方式**: `market_data.get_money_flow(symbol, trade_date, start_date, end_date)`

**参数**:
- `symbol` (必需): 股票代码
- `trade_date` (可选): 单日交易日期，格式 `YYYYMMDD`
- `start_date` (可选): 开始日期，格式 `YYYYMMDD`
- `end_date` (可选): 结束日期，格式 `YYYYMMDD`

**返回示例**:
```json
{
  "success": true,
  "data": [
    {
      "trade_date": "20260308",
      "ts_code": "600519.SH",
      "net_mf_vol": "12500.5",
      "net_mf_amount": "231250000.0",
      "buy_lg_vol": "8000.0",
      "sell_lg_vol": "5000.0"
    }
  ],
  "meta": {
    "count": 1
  }
}
```

**关键字段**:
- `net_mf_amount`: 主力净流入金额（元）
- `buy_lg_vol`: 大单买入量（手）
- `sell_lg_vol`: 大单卖出量（手）

---

### 7. get_limit_list - 获取涨跌停统计

**功能**: 获取每日涨跌停统计

**调用方式**: `market_data.get_limit_list(trade_date, limit_type)`

**参数**:
- `trade_date` (可选): 交易日期，格式 `YYYYMMDD`，默认最近交易日
- `limit_type` (可选): 涨跌停类型
  - `'U'`: 仅涨停
  - `'D'`: 仅跌停
  - `None`: 全部

**返回示例**:
```json
{
  "success": true,
  "data": [
    {
      "trade_date": "20260308",
      "ts_code": "600519.SH",
      "name": "贵州茅台",
      "close": "1850.50",
      "pct_change": "10.00",
      "up_limit": "1.0",
      "industry": "白酒"
    }
  ],
  "meta": {
    "count": 1
  }
}
```

---

### 8. get_company_info - 获取公司详细信息

**功能**: 获取上市公司详细信息（公司简介、联系方式、办公地址等）

**调用方式**: `market_data.get_company_info(symbol)`

**参数**:
- `symbol` (必需): 股票代码

**返回示例**:
```json
{
  "success": true,
  "data": {
    "ts_code": "600519.SH",
    "chairman": "丁雄军",
    "province": "贵州省",
    "city": "贵阳市",
    "introduction": "贵州茅台酒股份有限公司是中国最大的白酒生产企业...",
    "website": "www.moutaichina.com",
    "email": "dmb@moutai.com.cn",
    "office": "贵州省仁怀市茅台镇"
  }
}
```

---

## 工作流指导

### 典型查询流程

#### 1. 用户询问股票行情（已知代码）
```
用户: "小米股价多少？"

步骤:
1. 调用 market_data.get_quote(symbol='1810.HK')
2. 提取关键数据：nowPri, increPer
3. 格式化输出：
   "小米集团 (1810.HK) 当前价格 XX 港元，今日上涨 XX%"
```

#### 2. 用户询问股票行情（不确定代码）
```
用户: "贵州茅台今天涨了多少？"

步骤:
1. 如果记得代码是 600519，直接用 market_data.get_quote(symbol='600519')
2. 如果不确定，先用 market_data.search_stock(keyword='茅台')
3. 然后用 get_quote 获取行情
```

#### 3. 查询历史趋势
```
用户: "茅台最近一个月的走势如何？"

步骤:
1. 计算日期范围（当前日期往前推30天）
2. 调用 market_data.get_history(symbol='600519', period='daily', start_date='20260208', end_date='20260308')
3. 分析数据：
   - 计算涨跌幅
   - 识别趋势（上涨/下跌/震荡）
   - 提取关键点（最高价、最低价）
```

#### 4. 多工具组合查询
```
用户: "茅台今天上龙虎榜了吗？资金流向如何？"

步骤:
1. 调用 market_data.get_top_list(trade_date='20260308') 查看是否上榜
2. 调用 market_data.get_money_flow(symbol='600519', trade_date='20260308') 查看资金流向
3. 综合分析并输出
```

---

## 注意事项

### 1. 股票代码格式
- **推荐格式**: 纯数字（如 `'600519'`）
- 系统会自动识别市场（上证/深证）
- 港股需使用 `.HK` 后缀（如 `'1810.HK'`）

### 2. 日期格式
- **统一格式**: `YYYYMMDD`（如 `'20260308'`）
- 不要使用 `YYYY-MM-DD` 或其他分隔符

### 3. 数据时效性
- Tushare API 提供准实时数据，延迟约 15 分钟
- 历史数据每日收盘后更新
- 节假日和周末无数据

### 4. API 调用限制
- Tushare API 有频率限制（具体取决于账户级别）
- 已有缓存机制
- 避免短时间内重复查询相同数据

### 5. 错误处理
所有工具调用都应检查返回的 `success` 字段：
```json
{"success": true, "data": {...}}   // 成功
{"success": false, "error": "..."}  // 失败
```

### 6. 友好的输出格式
- 提取关键指标（价格、涨跌幅）
- 使用百分比、千分位等友好格式
- 示例: "贵州茅台 (600519) ¥1,850.50 (+1.39%)"

---

**Skill 版本**: v1.0
**最后更新**: 2026-03-08
