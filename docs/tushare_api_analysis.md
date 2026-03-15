# Tushare API 深度分析

## Tushare 架构特点

Tushare 是一个**统一的金融数据 SDK**，核心特点：

```
单一 SDK (tushare) → 多个数据接口 (api.xxx()) → 不同数据类型
```

### 一个 SDK，多种接口

```python
import tushare as ts

# 初始化一次
api = ts.pro_api()

# 然后通过不同的方法名获取不同数据
api.stock_basic()      # 股票基础信息
api.daily()            # 日线行情
api.income()           # 利润表
api.balance_sheet()    # 资产负债表
api.top_list()         # 龙虎榜
api.moneyflow()        # 资金流向
...
```

---

## 当前 MCP Tools 与 Tushare API 映射

| MCP Tool | Tushare API | 数据类型 |
|----------|-------------|---------|
| `get_quote` | `stock_basic` + `daily` | 实时行情（积分<200时降级） |
| `search_stock` | `stock_basic` | 股票基础信息 |
| `get_history` | `daily`/`weekly`/`monthly` | K线历史数据 |
| `get_stock_basic_info` | `stock_basic` | 股票基础信息 |
| `get_top_list` | `top_list` + `top_inst` | 龙虎榜数据 |
| `get_money_flow` | `moneyflow` | 资金流向 |
| `get_limit_list` | `limit_list` | 涨跌停统计 |
| `get_company_info` | `stock_company` | 公司详细信息 |

---

## 一个 Tool 可能调用多个 API

### 示例：get_quote 的实现逻辑

```python
def get_quote(self, symbol: str):
    # 1. 检查用户积分
    points = self.get_user_points()
    
    if points >= 200:
        # 高积分用户：调用 daily 接口获取完整行情
        df = api.daily(ts_code=ts_code)
        # 返回完整价格数据
    else:
        # 低积分用户：降级使用 stock_basic
        df = api.stock_basic(ts_code=ts_code)
        # 仅返回基本信息，价格标记为 N/A
```

**结论**: `get_quote` 这一个 tool，内部可能调用 **2 个不同的 Tushare API**！

---

## Tushare API 的多样性

### 同一类数据，多个维度

以股票行情为例，Tushare 提供：

```python
# 日线数据
api.daily(ts_code="600519.SH", start_date="20250101", end_date="20250315")

# 周线数据
api.weekly(ts_code="600519.SH")

# 月线数据
api.monthly(ts_code="600519.SH")

# 分钟线（需高积分）
api.minute(ts_code="600519.SH")

# 实时行情（需高积分）
api.quotation(ts_code="600519.SH")
```

### 财务数据，多种报表

```python
# 利润表
api.income(ts_code="600519.SH")

# 资产负债表
api.balance_sheet(ts_code="600519.SH")

# 现金流量表
api.cashflow(ts_code="600519.SH")

# 业绩预告
api.forecast(ts_code="600519.SH")

# 业绩快报
api.express(ts_code="600519.SH")
```

---

## 对 Mock 策略的影响

### 问题：一个 Tool 可能需要多个 Mock Prompt

| MCP Tool | 可能的场景 | 需要的 Mock 类型 |
|----------|-----------|-----------------|
| `get_quote` | 高积分用户 | 完整行情数据 |
| `get_quote` | 低积分用户 | 仅基本信息 |
| `get_history` | daily 周期 | 日K线数据 |
| `get_history` | weekly 周期 | 周K线数据 |
| `get_history` | monthly 周期 | 月K线数据 |

### 解决方案：参数感知的 Mock

```python
class TushareMockEngine:
    def generate(self, tool: str, params: dict):
        if tool == "get_quote":
            # 根据积分（或参数）选择 Mock 类型
            user_tier = params.get("user_tier", "high")
            
            if user_tier == "high":
                return self._generate_full_quote(params["symbol"])
            else:
                return self._generate_basic_info(params["symbol"])
        
        elif tool == "get_history":
            period = params.get("period", "daily")
            
            if period == "daily":
                return self._generate_daily_kline(params)
            elif period == "weekly":
                return self._generate_weekly_kline(params)
            elif period == "monthly":
                return self._generate_monthly_kline(params)
```

---

## 未使用的 Tushare API（可扩展）

当前只用了 Tushare 约 **10%** 的接口，还有大量可用：

### 财务数据（未使用）
- `income` - 利润表
- `balance_sheet` - 资产负债表
- `cashflow` - 现金流量表
- `forecast` - 业绩预告
- `express` - 业绩快报
- `fina_indicator` - 财务指标

### 市场数据（未使用）
- `daily_basic` - 每日指标（PE、PB、换手率等）
- `stk_limit` - 涨跌停价格
- `moneyflow_hsgt` - 沪深港通资金流向
- `margin` - 融资融券
- `pledge` - 股权质押
- `repurchase` - 股票回购

### 基金数据（未使用）
- `fund_basic` - 基金列表
- `fund_nav` - 基金净值
- `fund_portfolio` - 基金持仓
- `fund_daily` - 基金日线

### 宏观经济（未使用）
- `cpi` - CPI数据
- `ppi` - PPI数据
- `gdp` - GDP数据
- `interest_rate` - 利率
- `money_supply` - 货币供应量

---

## 总结

### Tushare 特点
1. **统一 SDK**: 一个 `pro_api()` 实例
2. **多接口**: 100+ 个数据接口
3. **参数驱动**: 不同参数获取不同数据
4. **积分体系**: 不同接口需要不同积分

### 对 Mock 的影响
1. **一个 Tool 可能对应多个 API**
2. **需要根据参数选择 Mock 策略**
3. **Mock Prompt 需要覆盖多种场景**

### 建议
- **Phase 1**: Mock 当前已实现的 8 个 market_data tools
- **Phase 2**: 根据需要扩展更多 Tushare API
- **Phase 3**: 优化 Mock 的多样性和真实性
