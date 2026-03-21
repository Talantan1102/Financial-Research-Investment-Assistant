---
name: web_research
description: |
  网络信息搜索，获取新闻、公告、研报等外部信息。
  
  Use this skill when:
  - User asks about latest news on a specific stock
  - User wants company announcements
  - User needs industry news
  - User wants research reports on stocks or industries
  
  Data Source: Simulated/Mock data (for demonstration)
version: "1.0"
tool_count: 4
---

# WebResearch Skill

## Overview

提供网络信息搜索能力，获取股票相关新闻、公司公告、行业新闻、研究报告等外部信息。

**Data Source**: Simulated/Mock data (for demonstration)  
**Coverage**: A-shares news, announcements, research reports  
**Total Tools**: 4

---

## Available Tools

### 1. search_stock_news - 搜索股票新闻

**Purpose**: 搜索指定股票的最新新闻。

**When to use**:
- User asks "茅台最近有什么新闻？"
- User wants latest updates on a stock
- Checking market sentiment through news

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| days | integer | No | 7 | 搜索最近几天的新闻 |
| limit | integer | No | 10 | 返回新闻数量 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "news": [
      {
        "title": "贵州茅台发布最新财报，业绩稳健增长",
        "source": "证券时报",
        "date": "2026-03-18",
        "url": "https://example.com/news/600519/1",
        "summary": "公司发布2025年年报，营收同比增长15%，净利润增长12%..."
      }
    ],
    "count": 3,
    "search_period": "最近7天"
  }
}
```

**Examples**:
- Default: `search_stock_news(symbol="600519")`
- More results: `search_stock_news(symbol="600519", days=30, limit=20)`
- Recent only: `search_stock_news(symbol="000858", days=3, limit=5)`

---

### 2. search_company_announcements - 搜索公司公告

**Purpose**: 搜索指定公司的公告。

**When to use**:
- User asks "茅台最近有什么公告？"
- User wants official company disclosures
- Checking earnings reports or major events

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| symbol | string | Yes | - | 股票代码 |
| category | string | No | all | 公告类型：all(全部), report(定期报告), major(重大事项), disclosure(信息披露) |
| limit | integer | No | 10 | 返回公告数量 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "symbol": "600519",
    "category": "all",
    "announcements": [
      {
        "title": "2025年年度报告",
        "category": "report",
        "date": "2026-03-20",
        "url": "https://example.com/announcement/600519/1"
      },
      {
        "title": "关于召开2025年度股东大会的通知",
        "category": "disclosure",
        "date": "2026-03-18",
        "url": "https://example.com/announcement/600519/2"
      }
    ],
    "count": 4
  }
}
```

**Examples**:
- All announcements: `search_company_announcements(symbol="600519")`
- Earnings reports only: `search_company_announcements(symbol="600519", category="report")`
- Major events: `search_company_announcements(symbol="600519", category="major")`

---

### 3. search_industry_news - 搜索行业新闻

**Purpose**: 搜索指定行业的最新新闻。

**When to use**:
- User asks "白酒行业最近有什么动态？"
- User wants industry trends and developments
- Checking sector-wide news

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| industry | string | Yes | - | 行业名称，如'白酒'、'新能源' |
| days | integer | No | 7 | 搜索最近几天的新闻 |
| limit | integer | No | 10 | 返回新闻数量 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "industry": "白酒",
    "news": [
      {
        "title": "白酒行业迎来政策利好",
        "source": "经济日报",
        "date": "2026-03-19",
        "url": "https://example.com/industry/白酒/1",
        "summary": "国家发改委发布白酒行业支持政策..."
      }
    ],
    "count": 3,
    "search_period": "最近7天"
  }
}
```

**Examples**:
- Default: `search_industry_news(industry="白酒")`
- More results: `search_industry_news(industry="新能源", days=30, limit=20)`
- Banking sector: `search_industry_news(industry="银行", days=14)`

---

### 4. search_research_reports - 搜索研报

**Purpose**: 搜索指定股票或行业的研究报告。

**When to use**:
- User asks "有没有茅台的研报？"
- User wants analyst ratings and target prices
- Checking professional research opinions

**Parameters**:
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| keyword | string | Yes | - | 搜索关键词，可以是股票名称或行业名称 |
| report_type | string | No | all | 研报类型：all(全部), rating(评级), earnings(盈利预测), industry(行业) |
| limit | integer | No | 5 | 返回研报数量 |

**Returns**:
```json
{
  "success": true,
  "data": {
    "keyword": "贵州茅台",
    "report_type": "all",
    "reports": [
      {
        "title": "贵州茅台深度研究：业绩稳健，估值合理",
        "institution": "中信证券",
        "author": "张三",
        "date": "2026-03-18",
        "rating": "买入",
        "target_price": "185.00",
        "summary": "公司基本面稳健，盈利能力持续提升..."
      },
      {
        "title": "白酒行业分析报告",
        "institution": "国泰君安",
        "author": "李四",
        "date": "2026-03-15",
        "rating": "增持",
        "target_price": "178.00",
        "summary": "行业景气度回升，龙头将充分受益..."
      }
    ],
    "count": 2
  }
}
```

**Examples**:
- Stock research: `search_research_reports(keyword="贵州茅台")`
- Industry report: `search_research_reports(keyword="银行行业", report_type="industry")`
- Ratings focus: `search_research_reports(keyword="宁德时代", report_type="rating")`

---

## Common Workflows

### Workflow 1: Stock News Check
```
User: "茅台最近有什么新闻？"

→ search_stock_news(symbol="600519", days=7, limit=10)
   → Get latest news articles

→ Response: "贵州茅台近期新闻：
   1. 发布2025年年报，业绩稳健增长(3月18日)
   2. 获多家机构增持，看好长期发展(3月15日)"
```

### Workflow 2: Earnings Announcement
```
User: "茅台年报发布了吗？"

→ search_company_announcements(symbol="600519", category="report", limit=5)
   → Get official earnings reports

→ Response: "贵州茅台最新公告：
   2025年年度报告已发布(3月20日)
   关于召开股东大会的通知(3月18日)"
```

### Workflow 3: Industry Research
```
User: "新能源行业最近有什么动态？"

→ search_industry_news(industry="新能源", days=14, limit=10)
   → Get industry-wide news

→ Response: "新能源行业动态：
   1. 行业迎来政策利好(3月19日)
   2. 景气度持续提升(3月16日)"
```

### Workflow 4: Analyst Research
```
User: "看看机构对茅台的评价"

→ search_research_reports(keyword="贵州茅台", report_type="rating", limit=5)
   → Get analyst reports

→ Response: "机构研报：
   中信证券：买入，目标价185元
   国泰君安：增持，目标价178元"
```

### Workflow 5: Comprehensive News Research
```
User: "我想了解一下比亚迪的最新情况"

→ Step 1: search_stock_news(symbol="002594", days=30)
   → Latest news

→ Step 2: search_company_announcements(symbol="002594", limit=10)
   → Official announcements

→ Step 3: search_research_reports(keyword="比亚迪", limit=5)
   → Analyst opinions

→ Response: Comprehensive news summary
```

---

## Important Notes

### 1. Category Types
| Category | Description |
|----------|-------------|
| all | 全部公告 |
| report | 定期报告（年报、季报） |
| major | 重大事项 |
| disclosure | 信息披露 |

### 2. Report Types
| Report Type | Description |
|-------------|-------------|
| all | 全部研报 |
| rating | 评级报告 |
| earnings | 盈利预测 |
| industry | 行业报告 |

### 3. Data Source Note
Currently returns mock/simulated data for demonstration purposes. In production, this would connect to real news APIs and research report databases.

### 4. Date Ranges
- `days` parameter determines the lookback period
- Default is 7 days for recent updates
- Use 30 days for monthly review
- Use 90 days for quarterly review

### 5. Error Handling
All tools return standardized response:
```json
{"success": true, "data": {...}}    // Success
{"success": false, "error": "股票代码不能为空"}   // Missing symbol
{"success": false, "error": "行业名称不能为空"}   // Missing industry
{"success": false, "error": "搜索关键词不能为空"}   // Missing keyword
```

### 6. Best Practices
- Use `search_stock_news` for market sentiment
- Use `search_company_announcements` for official information
- Use `search_industry_news` for sector trends
- Use `search_research_reports` for professional opinions
- Combine with other skills for comprehensive analysis
- Always check `success` field before using data

---

**Skill Version**: v1.0  
**Last Updated**: 2026-03-20  
**Compatible with**: AgentFlow v1.0, MCP Protocol
