---
name: web-research
description: 股票新闻、公司公告、行业新闻、研报等另类数据的 L1 数据采集层。当用户问"最近有什么新闻""有没有公告""机构怎么看"等外部信息查询时使用。当前为 Mock 数据,演示用。
---

# web-research Skill

## 层级位置

**L1 数据采集层** — 回答"外部世界在说什么"。与 `market-data` 并列,覆盖结构化数据之外的另类信号。

- **被上游调用**:`deep-research`(综合研报的"催化剂/情绪"段落)
- **不调用**:本层是最底层。

## 何时使用

- 用户询问某只股票的最新新闻、市场情绪
- 用户询问公司公告(年报/季报/重大事项/信息披露)
- 用户询问行业动态、政策影响
- 用户询问机构研报、评级、目标价

不适用于:行情/估值(用 `market-data`)、财务分析(用 `financial-analysis`)。

## 工具清单(4)

| 工具 | 一句话 |
|---|---|
| `search_stock_news` | 个股近 N 日新闻 |
| `search_company_announcements` | 公司公告(支持分类:报告/重大事项/信披) |
| `search_industry_news` | 行业新闻 |
| `search_research_reports` | 研报(支持类型:评级/盈利预测/行业) |

完整参数和示例:见 `references/tools.md`。

## 关键约定

- 当前版本返回 **mock 模拟数据**,接入生产需替换 `backend/app/service/mock_bocha_service.py` 为真实博查/新闻 API
- `days` 默认 7 天;月度复盘用 30,季度用 90
- 响应统一 `{success, data}`,使用前检查 `success`
