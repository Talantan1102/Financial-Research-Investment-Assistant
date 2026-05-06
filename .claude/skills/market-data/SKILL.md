---
name: market-data
description: A 股行情、K 线、估值指标、资金流向(龙虎榜/北向/两融)的 L1 数据采集层,基于 Tushare Pro API。当用户问"多少钱""走势如何""PE 是多少""资金流向"等事实性查询时使用。
---

# market-data Skill

## 层级位置

**L1 数据采集层** — 回答"是什么/有什么"。与 `web-research` 并列。

- **被上游调用**:`financial-analysis`(取原始字段)、`data-analysis`(取 K 线)、`risk-assessment`(取估值/波动)、`sector-analysis`(取行业估值)、`deep-research`(全部编排)
- **不调用**:本层是最底层,不调其它 skill。

## 何时使用

- 用户询问股价、实时行情、历史 K 线
- 用户询问 PE/PB/市值/换手率等每日估值指标
- 用户询问龙虎榜、资金流向、涨跌停、北向资金、融资融券
- 用户想根据股票名称反查代码

不适用于:新闻公告(用 `web-research`)、财务比率(用 `financial-analysis`)、风险打分(用 `risk-assessment`)。

## 工具清单(11)

| 工具 | 一句话 |
|---|---|
| `get_quote` | 股票实时行情(价、涨跌、量额) |
| `search_stock` | 代码/名称反查 |
| `get_history` | 日/周/月 K 线 |
| `get_stock_basic_info` | 股票基础信息(行业/地区/上市日) |
| `get_company_info` | 公司详细信息(简介/联系方式) |
| `get_daily_basic` | 每日估值(PE/PB/PS/市值/换手率) |
| `get_money_flow` | 个股资金流向(主力/散户) |
| `get_top_list` | 龙虎榜每日明细 |
| `get_limit_list` | 涨跌停统计 |
| `get_north_money` | 沪深港通北向资金 |
| `get_margin` | 融资融券数据 |

完整参数、返回结构、示例:见 `references/tools.md`。典型调用流程:见 `references/workflows.md`。

## 关键约定

- 股票代码格式:纯 6 位(`600519`)最推荐,也支持 `sh600519` 和 `600519.SH`
- 日期格式:`YYYYMMDD`(无分隔符)
- 实时数据 ~15 分钟延迟
- 响应统一 `{success, data}` 或 `{success, error}`,使用前检查 `success`
