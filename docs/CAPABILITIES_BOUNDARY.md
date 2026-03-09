# 金融研投助手 - 工具能力边界文档

**版本**: v2.1
**更新日期**: 2026-03-09
**适用范围**: financial-research-assistant 项目
**适用分支**: feature/mcp-migration

---

## 文档统计

| 类别 | 数量 | 说明 |
|------|------|------|
| MCP Skills | 4 Skills | MarketData / FinancialAnalysis / RiskAssessment / DeepResearch |
| MCP 工具 | 21 个 | LLM 直接通过 function calling 调用 |
| MCP 元工具 | 3 个 | skill / get_skill_tools / execute_skill_tool |
| Service 服务 | 15+ 个 | 底层业务逻辑封装 |
| API 路由 | 11 Routers | RESTful HTTP 接口 |
| DeepResearch Agents | 5 个 | Architect / Scout / Wizard / Writer / Critic |

---

---

## 目录

1. [概述](#1-概述)
2. [MCP Skills 工具详述（LLM 直接调用）](#2-mcp-skills-工具详述)
   - 2.1 [MarketData - 市场行情数据（8 工具）](#21-marketdata---市场行情数据8-工具)
   - 2.2 [FinancialAnalysis - 财务分析（3 工具）](#22-financialanalysis---财务分析3-工具)
   - 2.3 [RiskAssessment - 风险评估（3 工具）](#23-riskassessment---风险评估3-工具)
   - 2.4 [DeepResearch - 深度研究（7 工具）](#24-deepresearch---深度研究7-工具)
3. [MCP Server 元工具](#3-mcp-server-元工具)
4. [Service 层服务](#4-service-层服务)
5. [Router 层 API](#5-router-层-api)
6. [工具组合使用指南](#6-工具组合使用指南)
7. [限制与注意事项](#7-限制与注意事项)
8. [附录](#8-附录)

---

## 1. 概述

### 1.1 项目架构

金融研投助手采用 **MCP (Model Context Protocol) + 三轮编排** 架构：

```
用户提问
  ↓
MCPChatService（三轮编排）
  ├─ Round 1：LLM 选择 Skill（元工具调度）
  ├─ Round 2：LLM 调用具体工具（function calling，最多 5 轮）
  └─ Round 3：LLM 基于工具结果生成最终回答
  ↓
返回答案
```

### 1.2 工具分类总览

| 分类 | Skill 名称 | 工具数 | 数据源 | 说明 |
|------|-----------|--------|--------|------|
| **MCP Skill** | MarketData | 8 | Tushare API | 股票行情、历史数据、资金流向等 |
| **MCP Skill** | FinancialAnalysis | 3 | Tushare API | 财报查询、财务指标、财务对比 |
| **MCP Skill** | RiskAssessment | 3 | Tushare API + 历史价格 | 风险指标、组合风险、风险报告 |
| **MCP Skill** | DeepResearch | 7 | 博查搜索 API + 本地知识库 | 6 步分步研究 + 状态查询 |
| **元工具** | MCP Server | 3 | - | skill / get_skill_tools / execute_skill_tool |
| **Service** | 各类服务 | 26 | 多种 | 底层业务逻辑 |
| **Router API** | HTTP 端点 | 50+ | - | 对外 REST API |

### 1.3 核心数据流

```
LLM (qwen-max)
  ↕ function calling
MCP Server（三元工具）
  ↕ execute_skill_tool
4 个 Skills（21 个工具）
  ↕
底层 Service（TushareClient / 博查 API / LangGraph）
  ↕
外部数据源（Tushare / 博查 / Redis / PostgreSQL / Milvus）
```

---

## 2. MCP Skills 工具详述

> **重要**：以下 21 个工具是 LLM 通过 function calling 直接调用的，是评估的核心对象。

---

### 2.1 MarketData - 市场行情数据（8 工具）

**Skill 元信息**
- **名称**: `market_data`
- **位置**: `backend/app/mcp_server/skills/market_data.py`
- **SKILL.md**: `backend/claude_skills/market_data/SKILL.md`
- **描述**: 股票市场行情数据查询，支持 A 股实时行情获取
- **底层依赖**: `TushareClient`（`backend/app/data/tushare_client.py`）

---

#### 工具 1：`get_quote`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/market_data.py`
- **功能描述**：获取指定股票的实时行情数据（当前价格、涨跌幅、成交量等）
- **输入参数**：
  - `symbol` (string, 必填): 股票代码，支持格式：`'600519'` / `'sh600519'` / `'600519.SH'`
- **返回结果**：
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
- **怎么用（正确用法）**：
  - 场景 1：查询单只股票当前价格 → `get_quote(symbol='600519')`
  - 场景 2：查询涨跌幅 → 从返回的 `increPer` 字段获取
  - 场景 3：查询成交量/成交额 → 从 `traAmount` / `traNumber` 获取
- **不能怎么用（能力边界/限制）**：
  - ❌ 不能获取历史数据（只有当前行情，需用 `get_history`）
  - ❌ 不能批量查询多只股票（一次只能查一只）
  - ❌ 不能获取盘前/盘后数据
  - ❌ 不能获取分钟级实时行情（最小粒度为日线快照）
  - ❌ Tushare 积分 < 200 时，价格字段标记为 "N/A"
- **依赖**：Tushare API（`TUSHARE_API_TOKEN`、`TUSHARE_API_URL`）
- **错误处理**：空代码返回错误；API 异常返回 `success: false`；缓存 5 分钟 TTL

---

#### 工具 2：`search_stock`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/market_data.py`
- **功能描述**：根据股票代码或名称关键词搜索股票信息
- **输入参数**：
  - `keyword` (string, 必填): 搜索关键词，可以是代码（`'600519'`）或名称（`'贵州茅台'`）
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "results": [{"gid": "...", "name": "...", "nowPri": "..."}],
      "count": 1
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：用户只知道名称不知道代码 → `search_stock(keyword='贵州茅台')`
  - 场景 2：代码模糊搜索 → `search_stock(keyword='6005')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 不支持行业、板块等维度搜索
  - ❌ 名称搜索仅按代码精准匹配（先尝试 sh/sz 前缀），实际不支持模糊名称匹配
  - ❌ 不能按条件筛选（如"市值大于 1000 亿的白酒股"）
- **依赖**：Tushare API
- **错误处理**：关键词为空返回错误；未找到返回 `success: false`

---

#### 工具 3：`get_history`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/market_data.py`
- **功能描述**：获取股票历史 K 线数据，支持日线、周线、月线
- **输入参数**：
  - `symbol` (string, 必填): 股票代码
  - `period` (string, 可选): 周期类型 `daily` / `weekly` / `monthly`，默认 `daily`
  - `start_date` (string, 可选): 开始日期，格式 `YYYYMMDD`
  - `end_date` (string, 可选): 结束日期，格式 `YYYYMMDD`
  - `limit` (integer, 可选): 返回条数限制，默认 100
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "records": [
        {"trade_date": "20260308", "open": 1840.0, "high": 1865.0, "low": 1835.0, "close": 1850.5, "vol": 125000}
      ],
      "meta": {"symbol": "600519.SH", "period": "daily", "count": 100}
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看近 30 天走势 → `get_history(symbol='600519', limit=30)`
  - 场景 2：查看特定日期范围 → `get_history(symbol='600519', start_date='20260101', end_date='20260308')`
  - 场景 3：查看周线/月线 → `get_history(symbol='600519', period='weekly')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 不支持分钟级 K 线数据
  - ❌ 默认只返回 100 条，大量历史需显式设置 `limit`
  - ❌ 日期格式必须为 `YYYYMMDD`，不支持其他格式
  - ❌ 不支持指数的 K 线数据（仅个股）
- **依赖**：Tushare API
- **错误处理**：参数验证、API 异常捕获

---

#### 工具 4：`get_stock_basic_info`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/market_data.py`
- **功能描述**：获取股票基础信息（行业、地区、上市日期等）
- **输入参数**：
  - `symbol` (string, 必填): 股票代码
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "ts_code": "600519.SH",
      "name": "贵州茅台",
      "industry": "白酒",
      "area": "贵州",
      "market": "主板",
      "list_date": "20010827"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看行业分类 → `get_stock_basic_info(symbol='600519')`
  - 场景 2：查看上市日期和所属市场 → 从返回字段提取
- **不能怎么用（能力边界/限制）**：
  - ❌ 不包含动态行情数据（股价、成交量等）
  - ❌ 不包含财务数据（需用 FinancialAnalysis Skill）
  - ❌ 返回的是静态注册信息，可能有延迟
- **依赖**：Tushare API
- **错误处理**：代码为空、API 错误

---

#### 工具 5：`get_top_list`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/market_data.py`
- **功能描述**：获取龙虎榜每日明细，包含机构买卖数据
- **输入参数**：
  - `trade_date` (string, 可选): 交易日期 `YYYYMMDD`，默认最近交易日
  - `limit` (integer, 可选): 返回条数限制，默认 50
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "records": [
        {"ts_code": "...", "name": "...", "close": 15.5, "pct_change": 10.03, "turnover_rate": 25.6}
      ],
      "meta": {"trade_date": "20260308", "count": 50}
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看今日龙虎榜 → `get_top_list()`
  - 场景 2：查看指定日期龙虎榜 → `get_top_list(trade_date='20260307')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 仅返回榜单数据，不包含机构买卖金额明细
  - ❌ 不能查询个股是否曾上龙虎榜（需多次查询）
  - ❌ 非交易日查询会返回空数据
- **依赖**：Tushare API
- **错误处理**：API 异常捕获

---

#### 工具 6：`get_money_flow`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/market_data.py`
- **功能描述**：获取个股资金流向数据（主力、散户净流入等）
- **输入参数**：
  - `symbol` (string, 必填): 股票代码
  - `trade_date` (string, 可选): 交易日期 `YYYYMMDD`
  - `start_date` (string, 可选): 开始日期 `YYYYMMDD`
  - `end_date` (string, 可选): 结束日期 `YYYYMMDD`
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "records": [
        {"trade_date": "20260308", "net_mf_amount": 5000.0, "buy_lg_vol": 10000, "sell_lg_vol": 5000}
      ],
      "meta": {"symbol": "600519.SH"}
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看单日资金流向 → `get_money_flow(symbol='600519', trade_date='20260308')`
  - 场景 2：查看一段时间资金流向 → `get_money_flow(symbol='600519', start_date='20260301', end_date='20260308')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 不支持行业/板块级别的资金流向汇总
  - ❌ 不支持实时资金流向（日级数据）
  - ❌ 不自动做聚合分析（返回原始数据，分析需 LLM 自行完成）
- **依赖**：Tushare API
- **错误处理**：代码为空、日期格式检查、API 异常

---

#### 工具 7：`get_limit_list`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/market_data.py`
- **功能描述**：获取每日涨跌停统计
- **输入参数**：
  - `trade_date` (string, 可选): 交易日期 `YYYYMMDD`，默认最近交易日
  - `limit_type` (string, 可选): 涨跌停类型 `U`(涨停) / `D`(跌停)，默认全部
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "records": [{"ts_code": "...", "name": "...", "limit": "U", "pct_chg": 10.01}],
      "meta": {"trade_date": "20260308"}
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看今日涨停股 → `get_limit_list(limit_type='U')`
  - 场景 2：查看今日跌停股 → `get_limit_list(limit_type='D')`
  - 场景 3：查看全部涨跌停 → `get_limit_list()`
- **不能怎么用（能力边界/限制）**：
  - ❌ 仅统计数据，不包含涨跌停原因分析
  - ❌ 不支持连板统计（不知道是第几板）
  - ❌ 非交易日查询返回空数据
- **依赖**：Tushare API
- **错误处理**：API 异常捕获

---

#### 工具 8：`get_company_info`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/market_data.py`
- **功能描述**：获取上市公司详细信息（公司简介、联系方式、办公地址等）
- **输入参数**：
  - `symbol` (string, 必填): 股票代码
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "ts_code": "600519.SH",
      "chairman": "丁雄军",
      "province": "贵州",
      "city": "遵义",
      "introduction": "贵州茅台酒股份有限公司...",
      "website": "http://www.moutai.com.cn"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看公司简介 → `get_company_info(symbol='600519')`
  - 场景 2：查看公司管理层和联系方式 → 从返回字段提取
- **不能怎么用（能力边界/限制）**：
  - ❌ 不包含财务数据（需用 FinancialAnalysis Skill）
  - ❌ 不包含股价数据（需用 `get_quote`）
  - ❌ 信息可能有延迟（以公司公告为准）
- **依赖**：Tushare API
- **错误处理**：代码为空、API 错误

---

### 2.2 FinancialAnalysis - 财务分析（3 工具）

**Skill 元信息**
- **名称**: `financial_analysis`
- **位置**: `backend/app/mcp_server/skills/financial_analysis.py`
- **SKILL.md**: `backend/claude_skills/financial_analysis/SKILL.md`
- **描述**: A 股上市公司财务分析，支持财报查询、财务指标计算、财报对比分析
- **底层依赖**: `TushareClient`

---

#### 工具 9：`get_financial_report`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/financial_analysis.py`
- **功能描述**：获取指定公司的财务报表数据，包括利润表、资产负债表、现金流量表
- **输入参数**：
  - `symbol` (string, 必填): 股票代码，支持 `'600519'` / `'sh600519'` / `'600519.SH'`
  - `report_type` (string, 必填): 报表类型 `income`(利润表) / `balance`(资产负债表) / `cashflow`(现金流量表)
  - `period` (string, 可选): 报告期 `YYYYMMDD`（如 `20231231`），不填返回最新
  - `report_count` (integer, 可选): 报告期数量，默认 1，最多 10
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "symbol": "600519.SH",
      "report_type": "利润表",
      "report_count": 1,
      "reports": [
        {
          "end_date": "20231231",
          "total_revenue": "1234567.89",
          "revenue": "1200000.00",
          "net_income": "450000.00",
          "basic_eps": "1.50"
        }
      ]
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看最新利润表 → `get_financial_report(symbol='600519', report_type='income')`
  - 场景 2：查看最近 4 期资产负债表 → `get_financial_report(symbol='600519', report_type='balance', report_count=4)`
  - 场景 3：查看特定报告期 → `get_financial_report(symbol='600519', report_type='income', period='20231231')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 最多返回 10 期报告（`report_count` 范围 1-10）
  - ❌ 必须指定具体报表类型（不能一次获取全部三张报表）
  - ❌ 不能对比两家公司的财报（需分别调用再由 LLM 对比）
  - ❌ 不包含报表附注和审计意见
  - ❌ 数据为万元单位，金额字段为字符串格式
- **依赖**：Tushare API（`income` / `balancesheet` / `cashflow` 接口）
- **错误处理**：代码为空、report_type 不支持、report_count 范围检查、API 未初始化、数据为空

---

#### 工具 10：`calculate_financial_ratios`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/financial_analysis.py`
- **功能描述**：计算关键财务指标和比率（ROE、ROA、毛利率、净利率、资产负债率等）
- **输入参数**：
  - `symbol` (string, 必填): 股票代码
  - `period` (string, 可选): 报告期 `YYYYMMDD`，不填返回最新
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "symbol": "600519.SH",
      "ratios": {
        "eps": "1.5000",
        "roe": "25.50%",
        "roa": "15.30%",
        "gross_profit_margin": "85.20%",
        "net_profit_margin": "35.50%",
        "debt_to_assets": "25.30%",
        "current_ratio": "2.50",
        "quick_ratio": "2.20",
        "revenue_yoy": "10.50%",
        "net_profit_yoy": "10.80%",
        "ocf_to_revenue": "65.30%"
      },
      "summary": "ROE 25.50%（优秀）；毛利率 85.20%；净利率 35.50%；资产负债率 25.30%（低风险）"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：全面评估公司盈利能力 → `calculate_financial_ratios(symbol='600519')`
  - 场景 2：评估指定报告期指标 → `calculate_financial_ratios(symbol='600519', period='20231231')`
  - 场景 3：对比两家公司 → 分别调用后对比 `ratios` 字段
- **不能怎么用（能力边界/限制）**：
  - ❌ 一次只返回一个报告期的指标（不能批量返回多期）
  - ❌ 不能自定义计算公式（指标集固定）
  - ❌ 不包含估值指标（PE、PB、PS 等，需其他数据源）
  - ❌ 指标分类固定为四大类：盈利能力、偿债能力、增长能力、现金流
- **依赖**：Tushare API（`fina_indicator` 接口）
- **错误处理**：代码为空、API 未初始化、数据不存在

---

#### 工具 11：`compare_financial_data`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/financial_analysis.py`
- **功能描述**：对比分析财务数据的同比/环比变化
- **输入参数**：
  - `symbol` (string, 必填): 股票代码
  - `indicator` (string, 必填): 对比指标 `revenue`(营收) / `net_profit`(净利润) / `roe`(ROE) / `roa`(ROA)
  - `periods` (integer, 可选): 对比期数，默认 4，范围 2-20
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "symbol": "600519.SH",
      "indicator": "营业总收入",
      "unit": "万元",
      "data_points": [
        {"end_date": "20231231", "value": 1234567.89}
      ],
      "qoq_comparisons": [
        {"current_period": "20231231", "previous_period": "20230930", "change_rate": "12.23%", "trend": "上升"}
      ],
      "yoy_comparisons": [
        {"current_period": "20231231", "year_ago_period": "20221231", "change_rate": "10.23%", "trend": "上升"}
      ],
      "summary": "营业总收入最新值为 1234567.89，环比上升 12.23%。近4期平均增长率为 10.50%"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看营收趋势 → `compare_financial_data(symbol='600519', indicator='revenue', periods=8)`
  - 场景 2：查看 ROE 变化 → `compare_financial_data(symbol='600519', indicator='roe')`
  - 场景 3：查看净利润同比 → `compare_financial_data(symbol='600519', indicator='net_profit')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 环比计算需要至少 2 期数据
  - ❌ 同比计算需要至少 5 期数据（4 个季度 +1）
  - ❌ 最多支持 20 期对比
  - ❌ 仅支持 4 个预定义指标（revenue / net_profit / roe / roa）
  - ❌ 不能跨公司对比（需分别调用）
  - ❌ 指标来源固定：revenue/net_profit 从利润表获取，roe/roa 从财务指标表获取
- **依赖**：Tushare API
- **错误处理**：代码为空、indicator 不支持、periods 范围检查、数据不足

---

### 2.3 RiskAssessment - 风险评估（3 工具）

**Skill 元信息**
- **名称**: `risk_assessment`
- **位置**: `backend/app/mcp_server/skills/risk_assessment.py`
- **SKILL.md**: `backend/claude_skills/risk_assessment/SKILL.md`
- **描述**: 投资组合风险评估，支持风险指标计算、投资组合分析、风险报告生成
- **底层依赖**: `TushareClient` + 历史价格数据计算

---

#### 工具 12：`calculate_risk_metrics`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/risk_assessment.py`
- **功能描述**：计算单项资产的风险指标（波动率、Beta、最大回撤、VaR、CVaR 等）
- **输入参数**：
  - `symbol` (string, 必填): 股票代码
  - `days` (integer, 可选): 历史数据天数，默认 252（一个交易年）
  - `benchmark` (string, 可选): 基准指数代码（如 `'000001'` 上证指数）
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "symbol": "600519",
      "name": "贵州茅台",
      "data_period": "252天",
      "data_points": 250,
      "metrics": {
        "expected_return": 0.18,
        "volatility": 0.25,
        "sharpe_ratio": 0.60,
        "max_drawdown": -0.40,
        "var_95": -0.050,
        "cvar_95": -0.075,
        "downside_deviation": 0.20,
        "beta": 1.15,
        "correlation": 0.85,
        "alpha": 0.03
      },
      "risk_assessment": {
        "level": "中高风险",
        "score": 72.30,
        "description": "资产波动较大,需谨慎投资"
      }
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：评估单只股票风险 → `calculate_risk_metrics(symbol='600519')`
  - 场景 2：计算相对基准的 Beta → `calculate_risk_metrics(symbol='600519', benchmark='000001')`
  - 场景 3：短期风险评估 → `calculate_risk_metrics(symbol='600519', days=60)`
- **不能怎么用（能力边界/限制）**：
  - ❌ 最少需要 30 个交易日数据（不足时返回错误）
  - ❌ 无风险收益率固定为 3%（中国国债），不可自定义
  - ❌ 年化因子固定 252 个交易日
  - ❌ 不支持期权/期货等衍生品的风险计算
  - ❌ 不支持情景分析和压力测试
  - ❌ Beta 计算需要提供基准指数，否则不返回 Beta/Alpha
- **依赖**：Tushare API（历史日线数据）
- **错误处理**：代码为空、历史数据不足、API 未初始化、基准数据不足

---

#### 工具 13：`assess_portfolio_risk`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/risk_assessment.py`
- **功能描述**：评估投资组合的整体风险，计算加权组合指标
- **输入参数**：
  - `portfolio` (string, 必填): 投资组合描述，格式 `'代码1:权重1,代码2:权重2,...'`，如 `'600519:0.4,000001:0.3,600036:0.3'`
  - `days` (integer, 可选): 历史天数，默认 252
  - `benchmark` (string, 可选): 基准指数代码
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "portfolio": {
        "holdings": [{"symbol": "600519", "name": "贵州茅台", "weight": "40.00%"}],
        "data_period": "252天",
        "data_points": 250
      },
      "metrics": {
        "expected_return": 0.15,
        "volatility": 0.22,
        "sharpe_ratio": 0.54,
        "max_drawdown": -0.35,
        "var_95": -0.045,
        "cvar_95": -0.065,
        "asset_contributions": {"600519": {"weight": "40.00%", "return": "15.00%", "contribution": "6.00%"}}
      },
      "risk_assessment": {"level": "中等风险", "score": 55.50}
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：评估组合风险 → `assess_portfolio_risk(portfolio='600519:0.4,000001:0.3,600036:0.3')`
  - 场景 2：评估组合相对基准 → 加上 `benchmark='000001'`
- **不能怎么用（能力边界/限制）**：
  - ❌ 权重总和必须为 1（允许 ±0.01 误差），否则报错
  - ❌ 最少需要 30 个交易日数据
  - ❌ 不支持空头头寸（权重不能为负）
  - ❌ 不支持杠杆（权重不能大于 1）
  - ❌ 不能自动优化组合权重（仅评估给定权重）
  - ❌ 不考虑交易成本和税费
  - ❌ `days` 参数自动乘以 1.5 来覆盖非交易日
- **依赖**：Tushare API
- **错误处理**：组合为空、权重不为 1、历史数据不足、API 错误

---

#### 工具 14：`generate_risk_report`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/risk_assessment.py`
- **功能描述**：生成详细的风险评估报告（风险等级、投资建议、风险提示）
- **输入参数**：
  - `symbol` (string, 必填): 股票代码或投资组合描述字符串
  - `days` (integer, 可选): 历史天数，默认 252
  - `is_portfolio` (boolean, 可选): 是否为投资组合，默认 False
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "title": "资产风险评估报告",
      "generated_at": "2026-03-09 10:30:00",
      "risk_rating": {"level": "中等风险", "score": 55.50},
      "key_metrics": {
        "预期年化收益率": "18.00%",
        "波动率(年化)": "25.00%",
        "夏普比率": "0.60",
        "最大回撤": "-40.00%",
        "95% VaR": "-5.00%"
      },
      "recommendations": ["建议根据个人风险偏好合理配置"],
      "risk_warnings": ["历史最大回撤达40.0%,存在大幅亏损风险"]
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：生成单股风险报告 → `generate_risk_report(symbol='600519')`
  - 场景 2：生成组合风险报告 → `generate_risk_report(symbol='600519:0.4,000001:0.6', is_portfolio=True)`
- **不能怎么用（能力边界/限制）**：
  - ❌ 报告基于历史数据，不保证未来表现
  - ❌ 风险评级权重固定：波动率 40% + 最大回撤 40% + 夏普比率 20%
  - ❌ 建议仅供参考，不构成正式投资建议
  - ❌ 不支持自定义报告模板
- **依赖**：内部调用 `calculate_risk_metrics` 或 `assess_portfolio_risk`
- **错误处理**：参数为空、数据获取失败

---

### 2.4 DeepResearch - 深度研究（7 工具）

**Skill 元信息**
- **名称**: `deep_research`
- **位置**: `backend/app/mcp_server/skills/deep_research.py`
- **SKILL.md**: `backend/claude_skills/deep_research/SKILL.md`
- **描述**: 深度研究服务（分步执行版），6 个步骤 Agent + 1 个状态查询
- **底层依赖**: `DeepResearchV2Service`（`backend/app/service/deep_research_v2/`）

**5 Agent 协作架构**：
```
plan(Architect) → search(Scout) → analyze(Wizard) → write(Writer) → review(Critic) → revise(Writer)
```

---

#### 工具 15：`plan`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/deep_research.py`
- **功能描述**：规划研究大纲。Architect Agent 分析问题，生成结构化研究计划（章节 + 假设）
- **输入参数**：
  - `query` (string, 必填): 研究问题，如 `'小米汽车2024年市场竞争力分析'`
  - `session_id` (string, 可选): 会话 ID，不提供则自动生成
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "session_id": "abc-123-def",
      "query": "茅台近期投资价值分析",
      "outline": {
        "sections": [
          {"id": "section_1", "title": "公司基本面分析", "key_points": ["营收趋势", "利润率"]}
        ],
        "hypotheses": ["茅台作为头部白酒企业，具有品牌优势"]
      },
      "next_step": "调用 search 搜索信息",
      "usage": "deep_research.search(session_id='abc-123-def', search_web=True)"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：开始新研究 → `plan(query='中国新能源汽车市场深度分析')`
  - 场景 2：指定会话继续 → `plan(query='...', session_id='existing-id')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 仅生成大纲，不进行任何搜索或分析
  - ❌ 大纲质量取决于 LLM 理解能力
  - ❌ 不支持修改已生成的大纲（需重新调用）
- **依赖**：`DeepResearchV2Service`、`CheckpointService`
- **错误处理**：异常捕获和日志记录

---

#### 工具 16：`search`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/deep_research.py`
- **功能描述**：搜索信息。Scout Agent 根据大纲搜索网络/知识库，收集资料
- **输入参数**：
  - `session_id` (string, 必填): 会话 ID（由 `plan` 返回）
  - `section_id` (string, 可选): 章节 ID（如 `'section_1'`），不提供则搜索所有章节
  - `search_web` (boolean, 可选): 是否启用网络搜索，默认 True
  - `search_local` (boolean, 可选): 是否启用本地知识库搜索，默认 False
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "section_id": "section_1",
      "facts_count": 15,
      "sources_count": 8,
      "facts": ["茅台2023年营收同比增长10.5%"],
      "sources": [{"title": "...", "url": "...", "snippet": "..."}],
      "next_step": "调用 analyze 分析数据"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：搜索所有章节 → `search(session_id='abc', search_web=True)`
  - 场景 2：搜索单个章节 → `search(session_id='abc', section_id='section_1')`
  - 场景 3：仅搜索本地知识库 → `search(session_id='abc', search_web=False, search_local=True)`
- **不能怎么用（能力边界/限制）**：
  - ❌ 必须先调用 `plan` 生成大纲（依赖 session 状态）
  - ❌ 网络搜索依赖博查 API（API 不可用时搜索失败）
  - ❌ 返回最多 20 条事实和来源（超出截断）
  - ❌ 搜索结果质量取决于博查 API 和关键词匹配
  - ❌ 本地知识库需预先配置（默认 False）
- **依赖**：博查 API（`SEARCH_API_KEY`）、`CheckpointService`
- **错误处理**：会话不存在、章节 ID 不存在、搜索 API 错误

---

#### 工具 17：`analyze`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/deep_research.py`
- **功能描述**：分析数据。Wizard Agent 对搜索结果进行深度分析，生成洞察
- **输入参数**：
  - `session_id` (string, 必填): 会话 ID
  - `section_id` (string, 可选): 章节 ID，不提供则分析所有章节
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "section_id": "all",
      "insights_count": 8,
      "insights": ["茅台在高端白酒市场的市场份额持续增长"],
      "analysis": {"trend": "上升", "confidence": 0.85, "key_factors": ["品牌强度"]}
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：分析全部搜索结果 → `analyze(session_id='abc')`
  - 场景 2：分析单个章节 → `analyze(session_id='abc', section_id='section_1')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 必须先调用 `search` 获取数据
  - ❌ 分析基于已搜集的数据，不会生成新数据
  - ❌ 洞察质量受搜索结果质量影响
- **依赖**：`DeepResearchV2Service`、`CheckpointService`
- **错误处理**：会话不存在、数据不足

---

#### 工具 18：`write`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/deep_research.py`
- **功能描述**：撰写报告。Writer Agent 基于分析数据撰写完整报告（摘要、正文、结论、参考文献）
- **输入参数**：
  - `session_id` (string, 必填): 会话 ID
  - `section_id` (string, 可选): 章节 ID，不提供则撰写完整报告
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "section_id": "full_report",
      "content": "【摘要】\n...\n【正文】\n...\n【结论】\n...\n【参考文献】\n...",
      "word_count": 3500,
      "next_step": "调用 review 评审质量"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：生成完整报告 → `write(session_id='abc')`
  - 场景 2：生成单章节 → `write(session_id='abc', section_id='section_1')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 必须先调用 `analyze` 完成分析
  - ❌ 报告内容完全基于已有分析数据
  - ❌ 报告字数限制 5000-20000 字
  - ❌ 不支持自定义报告模板或格式
- **依赖**：`DeepResearchV2Service`、`CheckpointService`
- **错误处理**：会话不存在、数据不足

---

#### 工具 19：`review`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/deep_research.py`
- **功能描述**：质量评审。Critic Agent 评审报告质量，给出评分和改进建议
- **输入参数**：
  - `session_id` (string, 必填): 会话 ID
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "score": 8.5,
      "approved": true,
      "strengths": ["逻辑清晰，层次分明"],
      "weaknesses": ["某些观点缺乏最新数据支持"],
      "suggestions": ["补充2026年Q1的最新财报数据"],
      "next_step": "如需修订，调用 revise；否则研究完成"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：评审完整报告 → `review(session_id='abc')`
- **不能怎么用（能力边界/限制）**：
  - ❌ 必须先调用 `write` 生成报告
  - ❌ 评分标准固定（内容质量、逻辑、数据支撑）
  - ❌ 不支持自定义评审标准
- **依赖**：`DeepResearchV2Service`、`CheckpointService`
- **错误处理**：会话不存在、报告不存在

---

#### 工具 20：`revise`

- **类型**：MCP Skill Tool
- **位置**：`backend/app/mcp_server/skills/deep_research.py`
- **功能描述**：修订改进。Writer Agent 根据 Critic 的反馈修订报告
- **输入参数**：
  - `session_id` (string, 必填): 会话 ID
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "revised_report": "【摘要】\n修订后内容...",
      "word_count": 3800,
      "improvements": ["添加了2026年Q1财报数据", "补充了竞争对手对标分析"],
      "next_step": "可再次调用 review 确认质量"
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：根据评审反馈修订 → `revise(session_id='abc')`
  - 场景 2：多轮修订 → `revise` → `review` → `revise`（最多 3 轮）
- **不能怎么用（能力边界/限制）**：
  - ❌ 必须先调用 `review` 完成评审
  - ❌ 最多支持 3 轮修订循环
  - ❌ 修订基于 Critic 的建议，不接受外部自定义修改指令
- **依赖**：`DeepResearchV2Service`、`CheckpointService`
- **错误处理**：会话不存在、未经过评审

---

#### 工具 21：`get_state`

- **类型**：MCP Skill Tool（辅助）
- **位置**：`backend/app/mcp_server/skills/deep_research.py`
- **功能描述**：获取当前研究进度和状态
- **输入参数**：
  - `session_id` (string, 必填): 会话 ID
- **返回结果**：
  ```json
  {
    "success": true,
    "data": {
      "session_id": "abc-123-def",
      "query": "茅台近期投资价值分析",
      "current_phase": "writing",
      "completed_steps": ["plan", "search", "analyze"],
      "progress": "3/5",
      "has_report": true,
      "has_review": false
    }
  }
  ```
- **怎么用（正确用法）**：
  - 场景 1：查看研究进度 → `get_state(session_id='abc')`
  - 场景 2：判断下一步操作 → 根据 `current_phase` 和 `completed_steps` 决定
- **不能怎么用（能力边界/限制）**：
  - ❌ 仅查询状态，不修改任何数据
  - ❌ 不返回具体的报告内容或搜索结果
- **依赖**：`CheckpointService`
- **错误处理**：会话不存在

---

## 3. MCP Server 元工具

MCP Server 采用**三元工具架构**（渐进式披露），LLM 通过 3 个元工具间接调用 21 个具体工具。

**位置**: `backend/app/mcp_server/server.py`

### 元工具 1：`skill`

- **功能描述**：加载指定 Skill 的 SKILL.md 文档，了解 Skill 的能力和使用方式
- **输入参数**：
  - `name` (string, 必填): Skill 名称（`market_data` / `financial_analysis` / `risk_assessment` / `deep_research`）
- **返回结果**：SKILL.md 文件的完整内容（markdown 文本）
- **用途**：Round 1 中 LLM 选择感兴趣的 Skill 后，先调用此工具了解 Skill 详情

### 元工具 2：`get_skill_tools`

- **功能描述**：获取指定 Skill 下所有工具的 JSON Schema 定义
- **输入参数**：
  - `name` (string, 必填): Skill 名称
- **返回结果**：
  ```json
  {
    "success": true,
    "skill_name": "market_data",
    "tool_count": 8,
    "tools": [{"name": "get_quote", "description": "...", "inputSchema": {...}}]
  }
  ```
- **用途**：Round 1 中获取工具定义，注入 LLM 的 function calling 上下文

### 元工具 3：`execute_skill_tool`

- **功能描述**：执行指定 Skill 下的具体工具
- **输入参数**：
  - `skill_name` (string, 必填): Skill 名称
  - `tool_name` (string, 必填): 工具名称
  - `arguments` (object, 可选): 工具参数
- **返回结果**：工具执行结果（JSON）
- **用途**：Round 2 中 LLM 通过 function calling 调用具体工具

---

## 4. Service 层服务

> Service 层是底层业务逻辑，不直接暴露给 LLM，但支撑 MCP Skills 和 Router API 运行。

### 4.1 核心服务

| 服务 | 位置 | 功能 | 关键方法 |
|------|------|------|---------|
| **MCPChatService** | `service/mcp_chat_service.py` | 三轮编排对话 | `chat()`, `chat_stream()` |
| **DeepResearchV2Service** | `service/deep_research_v2/service.py` | 多 Agent 研究 | `research()`, `research_sync()` |
| **TushareClient** | `data/tushare_client.py` | 金融数据获取 | `get_quote()`, `get_history()`, ... |

### 4.2 数据服务

| 服务 | 位置 | 功能 | 数据源 |
|------|------|------|--------|
| **TushareClient** | `data/tushare_client.py` | A 股行情/财务/资金流 | Tushare API |
| **StockService** | `service/stock_service.py` | 股票资讯 | 聚合数据 API |
| **WebSearchService** | `service/web_search_service.py` | 网络搜索 | Serper API |

### 4.3 存储服务

| 服务 | 位置 | 功能 | 存储 |
|------|------|------|------|
| **SessionService** | `service/session_service.py` | 会话历史 | Redis |
| **CheckpointService** | `service/checkpoint_service.py` | 研究检查点 | PostgreSQL |
| **MemoryService** | `service/memory_service.py` | 长期记忆 | Milvus |
| **EmbeddingService** | `service/embedding_service.py` | 文本向量化 | DashScope |

### 4.4 TushareClient 关键特性

- **缓存**：5 分钟 TTL 自动过期
- **积分判断**：积分 >= 200 使用 `daily` 接口获取完整行情；积分 < 200 价格字段为 N/A
- **股票代码标准化**：`'600519'` → `'600519.SH'`，`'000001'` → `'000001.SZ'`
- **单例模式**：全局唯一实例 `get_tushare_client()`
- **自定义异常**：`TushareInvalidCodeError` / `TushareRateLimitError` / `TushareNetworkError`

---

## 5. Router 层 API

> Router 层提供 HTTP REST API，主要面向前端应用。

| Router | 路径前缀 | 主要端点 | 功能 |
|--------|---------|---------|------|
| **chat_router** | `/chat` | `POST /chat/mcp` | MCP 聊天（核心） |
| **research_router** | `/research` | `POST /research/stream` | 深度研究（流式） |
| **search_router** | `/search` | `POST /search/web` | 网络搜索 |
| **news_router** | `/news` | `GET /news/list` | 行业资讯 |
| **document_router** | `/documents` | `POST /documents/upload` | 文档管理 |
| **attachment_router** | `/attachments` | `POST /attachments` | 聊天附件 |
| **session_router** | `/sessions` | `GET/POST /sessions` | 会话管理 |
| **auth_router** | `/auth` | `POST /auth/login` | 用户认证 |
| **knowledge_router** | `/knowledge-bases` | `POST /knowledge-bases` | 知识库管理 |
| **memory_router** | `/memories` | `GET /memories` | 长期记忆 |
| **database_router** | `/database` | `POST /database/text2sql` | 自然语言转 SQL |

---

## 6. 工具组合使用指南

### 6.1 常见工作流

#### 工作流 1：股票投资分析

```
1. market_data.get_quote(symbol='600519')           → 获取当前价格
2. market_data.get_history(symbol='600519', limit=30) → 获取近期走势
3. financial_analysis.calculate_financial_ratios(symbol='600519') → 评估财务状况
4. risk_assessment.calculate_risk_metrics(symbol='600519')  → 评估风险水平
```

**适用问题**：*"茅台值得投资吗？"*、*"分析一下茅台的投资价值"*

#### 工作流 2：行业对比分析

```
1. financial_analysis.calculate_financial_ratios(symbol='600519') → 茅台财务指标
2. financial_analysis.calculate_financial_ratios(symbol='000858') → 五粮液财务指标
3. risk_assessment.calculate_risk_metrics(symbol='600519')   → 茅台风险
4. risk_assessment.calculate_risk_metrics(symbol='000858')   → 五粮液风险
   → LLM 综合对比分析
```

**适用问题**：*"茅台和五粮液哪个更值得投资？"*

#### 工作流 3：深度研究报告

```
1. deep_research.plan(query='中国新能源汽车市场深度分析')
2. deep_research.search(session_id='xxx', search_web=True)
3. deep_research.analyze(session_id='xxx')
4. deep_research.write(session_id='xxx')
5. deep_research.review(session_id='xxx')
6. deep_research.revise(session_id='xxx')  // 如果评审不通过
```

**适用问题**：*"请帮我写一份关于 AI 芯片行业的深度研究报告"*

#### 工作流 4：投资组合评估

```
1. risk_assessment.assess_portfolio_risk(portfolio='600519:0.4,000001:0.3,600036:0.3')
2. risk_assessment.generate_risk_report(symbol='600519:0.4,000001:0.3,600036:0.3', is_portfolio=True)
```

**适用问题**：*"评估一下这个投资组合的风险"*

#### 工作流 5：市场热点追踪

```
1. market_data.get_limit_list(limit_type='U')     → 今日涨停股
2. market_data.get_top_list()                       → 今日龙虎榜
3. market_data.get_money_flow(symbol='xxx')         → 热点个股资金流向
```

**适用问题**：*"今天哪些股票涨停了？资金流向如何？"*

### 6.2 工具间依赖关系

```
DeepResearch 工具链（严格顺序）：
plan → search → analyze → write → review → revise(可选) → review(可选)

其他 Skills 工具无严格依赖，可自由组合使用。
```

### 6.3 跨 Skill 组合

| 组合 | 工具 | 适用场景 |
|------|------|---------|
| 行情 + 财务 | `get_quote` + `calculate_financial_ratios` | 快速评估个股 |
| 行情 + 风险 | `get_quote` + `calculate_risk_metrics` | 风险预警 |
| 财务 + 风险 | `get_financial_report` + `generate_risk_report` | 全面评估 |
| 行情 + 深度研究 | `get_quote` + `plan/search/...` | 深入调研 |

---

## 7. 限制与注意事项

### 7.1 全局限制

| 限制项 | 说明 |
|--------|------|
| **LLM 模型** | 仅支持 qwen-max，不可切换 |
| **数据市场** | 仅支持 A 股（沪深），不支持港股（除部分基础信息）、美股 |
| **数据延迟** | 行情数据约 15 分钟延迟，非实时盘口数据 |
| **工具调用轮数** | MCPChatService 单次对话最多 5 轮工具调用 |
| **并发限制** | Tushare API 有频率限制（缓存 5 分钟缓解） |
| **会话上下文** | 最多 5000 tokens 历史 / 20 条消息 |

### 7.2 各 Skill 特殊限制

#### MarketData
- 积分 < 200 时行情数据受限（价格字段为 N/A）
- 不支持分钟级/秒级数据
- 不支持指数数据的完整行情
- 搜索功能仅支持代码精确匹配

#### FinancialAnalysis
- 财报数据单次最多 10 期
- 对比数据最多 20 期
- 仅支持 4 个预定义对比指标
- 不包含估值指标（PE/PB/PS）

#### RiskAssessment
- 最少 30 个交易日数据
- 无风险收益率固定 3%
- 不支持衍生品风险计算
- 组合权重必须严格为 1

#### DeepResearch
- 6 步必须严格按顺序执行
- 最多 3 轮修订循环
- 搜索最多 20 条事实
- 报告字数 5000-20000 字
- 依赖博查 API 稳定性

### 7.3 常见陷阱

1. **日期格式**：所有日期必须为 `YYYYMMDD` 格式，不是 `YYYY-MM-DD`
2. **股票代码**：推荐使用纯数字格式 `'600519'`，系统自动标准化
3. **组合权重**：`assess_portfolio_risk` 的权重必须严格加总为 1
4. **DeepResearch 状态**：每步必须等待前一步完成，使用 `get_state` 检查进度
5. **数据缓存**：TushareClient 缓存 5 分钟，频繁查询会返回缓存数据

---

## 8. 附录

### 8.1 环境变量清单

| 变量名 | 用途 | 必需 | 默认值 |
|--------|------|------|--------|
| `DASHSCOPE_API_KEY` | qwen-max LLM API | 是 | - |
| `TUSHARE_API_TOKEN` | 金融数据 API | 是 | - |
| `TUSHARE_API_URL` | Tushare 自定义 URL | 否 | `https://api.tushare.pro` |
| `SEARCH_API_KEY` / `BOCHA_API_KEY` | 博查搜索 API | 是（DeepResearch 需要） | - |
| `DASHSCOPE_BASE_URL` | LLM API 基础 URL | 否 | 官方地址 |
| `REDIS_HOST` | Redis 主机 | 是（会话管理需要） | `redis` |
| `REDIS_PORT` | Redis 端口 | 否 | `6379` |
| `REDIS_PASSWORD` | Redis 密码 | 否 | - |
| `DATABASE_URL` | PostgreSQL 连接串 | 是（检查点需要） | - |

### 8.2 外部服务依赖

| 服务 | 用途 | 使用者 | 状态 |
|------|------|--------|------|
| **Tushare API** | A 股数据 | MarketData / FinancialAnalysis / RiskAssessment | 活跃 |
| **博查 API** | 网络搜索 | DeepResearch Scout Agent | 活跃 |
| **DashScope** | LLM + Embedding | MCPChatService / DeepResearch / EmbeddingService | 活跃 |
| **Redis** | 会话存储 | SessionService | 活跃 |
| **PostgreSQL** | 检查点/用户 | CheckpointService / AuthService | 活跃 |
| **Milvus** | 向量存储 | MemoryService / KnowledgeService | 活跃 |

### 8.3 工具速查表

| # | 工具全名 | Skill | 一句话说明 |
|---|---------|-------|-----------|
| 1 | `market_data.get_quote` | MarketData | 获取实时行情 |
| 2 | `market_data.search_stock` | MarketData | 搜索股票 |
| 3 | `market_data.get_history` | MarketData | 历史 K 线 |
| 4 | `market_data.get_stock_basic_info` | MarketData | 股票基础信息 |
| 5 | `market_data.get_top_list` | MarketData | 龙虎榜 |
| 6 | `market_data.get_money_flow` | MarketData | 资金流向 |
| 7 | `market_data.get_limit_list` | MarketData | 涨跌停统计 |
| 8 | `market_data.get_company_info` | MarketData | 公司信息 |
| 9 | `financial_analysis.get_financial_report` | FinancialAnalysis | 财务报表 |
| 10 | `financial_analysis.calculate_financial_ratios` | FinancialAnalysis | 财务比率 |
| 11 | `financial_analysis.compare_financial_data` | FinancialAnalysis | 财务对比 |
| 12 | `risk_assessment.calculate_risk_metrics` | RiskAssessment | 单资产风险 |
| 13 | `risk_assessment.assess_portfolio_risk` | RiskAssessment | 组合风险 |
| 14 | `risk_assessment.generate_risk_report` | RiskAssessment | 风险报告 |
| 15 | `deep_research.plan` | DeepResearch | 规划大纲 |
| 16 | `deep_research.search` | DeepResearch | 搜索资料 |
| 17 | `deep_research.analyze` | DeepResearch | 分析数据 |
| 18 | `deep_research.write` | DeepResearch | 撰写报告 |
| 19 | `deep_research.review` | DeepResearch | 质量评审 |
| 20 | `deep_research.revise` | DeepResearch | 修订报告 |
| 21 | `deep_research.get_state` | DeepResearch | 查询进度 |

---

> **免责声明**：本系统提供的所有数据和分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。历史数据不代表未来表现。
