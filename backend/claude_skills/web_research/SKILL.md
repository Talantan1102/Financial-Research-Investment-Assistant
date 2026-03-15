---
name: web_research
description: 网络搜索与信息收集，支持网络搜索、知识库搜索和深度研究
version: "1.0"
tool_count: 5
---

# WebResearch Skill

## 概述

提供网络信息搜索和收集能力，支持多种搜索策略和网页内容提取。适用于查找实时新闻、市场信息、行业报告等。

**数据源**: 博查搜索 API / Serper API
**搜索类型**: 网页搜索、知识库搜索、深度搜索
**功能**: 搜索结果缓存、网页内容提取、交叉验证

---

## 可用工具

### 1. web_search - 网络搜索

**功能**: 搜索互联网获取最新信息，适用于查找实时数据、新闻、市场信息等

**调用方式**: `web_research.web_search(query, num_results, source)`

**参数**:
- `query` (必需): 搜索关键词
  - 示例: `'贵州茅台 2025年财报'`, `'新能源汽车销量'`
- `num_results` (可选): 返回结果数量，默认 10
  - 范围: 1-20
- `source` (可选): 搜索来源，默认 "web"
  - 可选值: `"web"` (全网), `"news"` (新闻)

**返回示例**:
```json
{
  "success": true,
  "data": {
    "results": [
      {
        "url": "https://example.com/article",
        "name": "文章标题",
        "summary": "内容摘要",
        "snippet": "摘要片段",
        "site_name": "网站名称",
        "source": "web"
      }
    ],
    "total": 10,
    "query": "搜索关键词"
  }
}
```

---

### 2. knowledge_search - 知识库搜索

**功能**: 搜索内部知识库获取结构化信息

**调用方式**: `web_research.knowledge_search(query, num_results)`

**参数**:
- `query` (必需): 搜索关键词
- `num_results` (可选): 返回结果数量，默认 5

**返回示例**:
```json
{
  "success": true,
  "data": {
    "results": [...],
    "total": 5,
    "source": "knowledge_base"
  }
}
```

---

### 3. deep_search - 深度搜索

**功能**: 深度研究模式，递归搜索并进行交叉验证

**调用方式**: `web_research.deep_search(query, max_depth, verify_results)`

**参数**:
- `query` (必需): 研究主题/问题
- `max_depth` (可选): 搜索深度，默认 2
  - 说明: 控制递归搜索的层级
- `verify_results` (可选): 是否交叉验证，默认 true

**返回示例**:
```json
{
  "success": true,
  "data": {
    "results": [...],
    "verified_facts": [...],
    "confidence_score": 0.85,
    "sources_count": 12
  }
}
```

---

### 4. extract_webpage - 网页内容提取

**功能**: 提取指定网页的主要内容

**调用方式**: `web_research.extract_webpage(url)`

**参数**:
- `url` (必需): 网页 URL
  - 示例: `'https://www.example.com/news/123'`

**返回示例**:
```json
{
  "success": true,
  "data": {
    "title": "文章标题",
    "content": "提取的正文内容...",
    "publish_time": "2025-03-01",
    "author": "作者名"
  }
}
```

---

## 使用场景

| 场景 | 推荐工具 | 示例 |
|------|---------|------|
| 查最新新闻 | web_search | `query: "茅台 股价 最新消息"` |
| 查行业报告 | deep_search | `query: "新能源汽车行业分析", max_depth: 2` |
| 验证信息 | extract_webpage | `url: "报道链接"` |
| 内部资料 | knowledge_search | `query: "公司产品线"` |

---

## 注意事项

1. **API Key**: 需要配置 `BOCHA_API_KEY` 或 `SEARCH_API_KEY` 环境变量
2. **搜索限制**: 免费 API 有调用频率限制，请合理使用
3. **结果缓存**: 相同查询会缓存 1 小时以提高性能
4. **深度搜索**: 深度搜索会消耗更多 API 调用次数

---

## 错误处理

常见错误及解决方法:

| 错误 | 原因 | 解决方法 |
|------|------|---------|
| API Key 无效 | 未配置或配置错误 | 检查环境变量 |
| 搜索结果为空 | 关键词太冷门 | 更换关键词或扩大范围 |
| 网页提取失败 | 网站反爬或失效 | 尝试其他来源 |
