# web-research 工具详细参考

当前为 **mock/simulated** 数据,演示用。生产接入需替换 `backend/app/service/mock_bocha_service.py`。

## 1. search_stock_news — 个股新闻

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| symbol | string | Yes | - | 股票代码 |
| days | integer | No | 7 | 回溯天数 |
| limit | integer | No | 10 | 返回条数 |

**返回字段**:`news[].{title, source, date, url, summary}`, `count`, `search_period`

**示例**
- 默认:`search_stock_news(symbol="600519")`
- 月度:`search_stock_news(symbol="600519", days=30, limit=20)`

## 2. search_company_announcements — 公司公告

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| symbol | string | Yes | - | 股票代码 |
| category | string | No | all | all / report(定期报告) / major(重大事项) / disclosure(信披) |
| limit | integer | No | 10 | 返回数 |

**示例**
- 全部:`search_company_announcements(symbol="600519")`
- 年报季报:`search_company_announcements(symbol="600519", category="report")`

## 3. search_industry_news — 行业新闻

**参数**
| Name | Type | Req | Default |
|---|---|---|---|
| industry | string | Yes | - |
| days | integer | No | 7 |
| limit | integer | No | 10 |

**示例**:`search_industry_news(industry="白酒", days=14)`

## 4. search_research_reports — 研报搜索

**参数**
| Name | Type | Req | Default | 说明 |
|---|---|---|---|---|
| keyword | string | Yes | - | 股票名或行业名 |
| report_type | string | No | all | all / rating(评级) / earnings(盈利预测) / industry(行业) |
| limit | integer | No | 5 | 返回数 |

**返回字段**:`reports[].{title, institution, author, date, rating, target_price, summary}`

**示例**
- 个股:`search_research_reports(keyword="贵州茅台")`
- 评级:`search_research_reports(keyword="宁德时代", report_type="rating")`
- 行业:`search_research_reports(keyword="银行行业", report_type="industry")`

---

## 典型工作流

### 新闻速览
```
User: "茅台最近有什么新闻?"
→ search_stock_news(symbol="600519", days=7)
```

### 财报查询
```
User: "茅台年报发布了吗?"
→ search_company_announcements(symbol="600519", category="report")
```

### 综合另类信号
```
User: "了解一下比亚迪的最新情况"
→ search_stock_news(symbol="002594", days=30)
→ search_company_announcements(symbol="002594")
→ search_research_reports(keyword="比亚迪")
```

---

## 约定

- **分类枚举**:category: `all / report / major / disclosure`;report_type: `all / rating / earnings / industry`
- **时间范围**:days 默认 7,月度 30,季度 90
- **响应**:`{success, data}` / `{success, error}`
- **Mock 数据**:当前返回固定模板,仅供演示流程
