---
name: market-data-skill
description: A股市场行情数据查询，支持股票实时行情、历史K线、资金流向、龙虎榜等数据获取
author: 深圳市深维智见教育科技有限公司
version: 1.0.0
license: Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
---

# Market Data Skill

## 简介

市场行情数据 Skill，提供A股市场行情查询功能，基于 Tushare 数据源。支持实时行情、历史K线、资金流向等多种市场数据获取。

## 功能特性

- **实时行情**：获取指定股票的实时行情数据
- **股票搜索**：根据代码或名称关键词搜索股票
- **历史K线**：获取日线、周线、月线历史数据
- **基础信息**：获取股票行业、地区、上市日期等信息
- **龙虎榜数据**：获取每日龙虎榜明细
- **资金流向**：获取个股主力资金、散户资金流向
- **涨跌停统计**：获取每日涨跌停股票统计
- **公司信息**：获取上市公司详细信息

## 注册的工具

### get_quote

获取指定股票的实时行情数据，包括当前价格、涨跌幅、成交量等信息。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码，支持多种格式：纯数字、带市场前缀、Tushare格式 |

**返回示例：**
```json
{
  "gid": "sh600519",
  "ts_code": "600519.SH",
  "name": "贵州茅台",
  "nowPri": "1850.50",
  "increase": "25.30",
  "increPer": "1.39"
}
```

### search_stock

根据股票代码或名称关键词搜索股票信息。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| keyword | string | 是 | 搜索关键词，可以是股票代码或名称 |

### get_history

获取股票历史K线数据，支持日线、周线、月线。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码 |
| period | string | 否 | 周期类型：daily/weekly/monthly，默认daily |
| start_date | string | 否 | 开始日期，格式YYYYMMDD |
| end_date | string | 否 | 结束日期，格式YYYYMMDD |
| limit | integer | 否 | 返回数据条数限制，默认100 |

### get_stock_basic_info

获取股票基础信息（行业、地区、上市日期等）。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码 |

### get_top_list

获取龙虎榜每日明细，包含机构买卖数据。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| trade_date | string | 否 | 交易日期，格式YYYYMMDD，默认最近交易日 |
| limit | integer | 否 | 返回条数限制，默认50 |

### get_money_flow

获取个股资金流向数据（主力、散户净流入等）。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码 |
| trade_date | string | 否 | 交易日期，格式YYYYMMDD |
| start_date | string | 否 | 开始日期，格式YYYYMMDD |
| end_date | string | 否 | 结束日期，格式YYYYMMDD |

### get_limit_list

获取每日涨跌停统计。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| trade_date | string | 否 | 交易日期，格式YYYYMMDD，默认最近交易日 |
| limit_type | string | 否 | 涨跌停类型：U(涨停)、D(跌停)，默认全部 |

### get_company_info

获取上市公司详细信息（公司简介、联系方式、办公地址等）。

**参数：**
| 名称 | 类型 | 必填 | 描述 |
|------|------|------|------|
| symbol | string | 是 | 股票代码 |

## 使用示例

```python
from app.mcp_server.skills.market_data import MarketDataSkill

skill = MarketDataSkill()

# 获取实时行情
result = await skill.get_quote("600519")

# 获取历史数据
result = await skill.get_history(
    symbol="600519",
    period="daily",
    limit=30
)
```

## 依赖

- Tushare API
- `TUSHARE_API_TOKEN` 环境变量

## 目录结构

```
market-data-skill/
├── SKILL.md              # 本文件
├── scripts/              # 可选：脚本文件
├── references/           # 可选：参考文档
└── assets/              # 可选：静态资源
```

## 源码位置

实际代码位于：`../market_data.py`
