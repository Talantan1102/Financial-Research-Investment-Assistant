# Deep Research 搜索与分析阶段增强方案

## 当前状态分析

### 搜索阶段 (Scout Agent) - 当前能力
- ✅ 网络搜索（博查API）
- ✅ 本地知识库搜索
- ❌ **金融数据自动获取**（需要显式调用）
- ❌ **搜索结果智能排序**（按相关性/时效性）
- ❌ **多源数据融合**（搜索+行情+财务）

### 分析阶段 (Wizard Agent) - 当前能力
- ✅ 基础数据分析
- ✅ 趋势识别
- ❌ **财务指标计算**（ROE、PE等）
- ❌ **估值模型**（DCF、PE/PB分位）
- ❌ **可视化生成**（图表）
- ❌ **交叉分析**（行业 vs 个股）

---

## 🔍 搜索阶段增强方案

### 1. 智能数据源路由

**问题**: 当前需要显式指定调用哪个工具

**增强方案**:
```python
# Scout Agent 自动识别需要的数据类型
search(query="茅台投资价值"):
    # 智能识别需要的数据
    needs = analyze_query_needs(query)
    # {
    #   "stock_data": True,      # 需要股票行情
    #   "financial_data": True,  # 需要财务数据
    #   "industry_data": True,   # 需要行业对比
    #   "web_search": True       # 需要网络资讯
    # }
    
    # 并行获取数据
    results = await asyncio.gather(
        market_data.get_quote("600519"),        # 自动提取股票代码
        financial_analysis.get_fina_indicator("600519"),
        sector_analysis.compare_industry_valuation(["白酒"]),
        web_search("茅台 2024 业绩")
    )
```

**实现效果**:
- 用户只需说"分析茅台"
- 系统自动获取行情、财务、行业、新闻

---

### 2. 搜索结果增强

**问题**: 网络搜索结果质量参差不齐

**增强方案**:
```python
class EnhancedSearchEngine:
    def search(self, query, context=None):
        # 1. 多源并行搜索
        web_results = web_search(query)
        news_results = news_search(query)  # 新增新闻搜索
        report_results = report_search(query)  # 新增研报搜索
        
        # 2. 去重和排序
        all_results = merge_and_dedup([web_results, news_results, report_results])
        
        # 3. 相关性评分
        ranked_results = rank_by_relevance(all_results, query, context)
        
        # 4. 时效性加权
        final_results = apply_time_decay(ranked_results)
        
        return final_results
```

**实现效果**:
- 搜索结果更全面（网页+新闻+研报）
- 自动去重，避免信息冗余
- 优先返回高相关性、高时效性内容

---

### 3. 深度信息挖掘

**问题**: 当前只获取表层信息

**增强方案**:
```python
# 递归搜索，挖掘深度信息
def deep_search(topic, depth=2):
    """
    递归搜索，挖掘关联信息
    
    depth=1: 直接搜索主题
    depth=2: 搜索主题 + 子主题
    """
    results = []
    
    # 第一层：直接搜索
    level1 = web_search(topic)
    results.extend(level1)
    
    # 第二层：提取子主题，继续搜索
    if depth >= 2:
        sub_topics = extract_sub_topics(level1)
        for sub in sub_topics:
            level2 = web_search(sub)
            results.extend(level2)
    
    return results

# 示例：搜索"新能源汽车"
# L1: 新能源汽车市场概况
# L2: 比亚迪销量、宁德时代电池、特斯拉降价...
```

---

## 📊 分析阶段增强方案

### 1. 财务分析增强

**问题**: 当前缺乏专业的财务分析能力

**增强方案**:
```python
class FinancialAnalyzer:
    def analyze(self, symbol):
        # 获取数据
        income = get_income_statement(symbol)
        balance = get_balance_sheet(symbol)
        cashflow = get_cash_flow(symbol)
        indicators = get_fina_indicator(symbol)
        
        # 计算关键指标
        analysis = {
            "profitability": {
                "roe": indicators["roe"],
                "roa": indicators["roa"],
                "gross_margin": indicators["grossprofit_margin"],
                "net_margin": indicators["netprofit_margin"],
                "assessment": self._assess_profitability(indicators)
            },
            "growth": {
                "revenue_growth": income["total_revenue_yoy"],
                "profit_growth": income["n_income_yoy"],
                "assessment": self._assess_growth(income)
            },
            "valuation": {
                "pe_ttm": get_daily_basic(symbol)["pe_ttm"],
                "pb": get_daily_basic(symbol)["pb"],
                "assessment": self._assess_valuation(symbol)
            },
            "risk": {
                "debt_ratio": indicators["debt_to_assets"],
                "current_ratio": indicators["current_ratio"],
                "assessment": self._assess_risk(indicators)
            }
        }
        
        return analysis
```

**实现效果**:
- 自动生成盈利能力、成长性、估值、风险四维分析
- 每个维度给出评级（优秀/良好/一般/较差）

---

### 2. 估值模型增强

**问题**: 当前缺乏估值分析

**增强方案**:
```python
class ValuationAnalyzer:
    def analyze(self, symbol):
        # PE Band 分析
        pe_history = get_pe_history(symbol, years=5)
        current_pe = get_daily_basic(symbol)["pe_ttm"]
        pe_percentile = calculate_percentile(pe_history, current_pe)
        
        # PB Band 分析
        pb_history = get_pb_history(symbol, years=5)
        current_pb = get_daily_basic(symbol)["pb"]
        pb_percentile = calculate_percentile(pb_history, current_pb)
        
        return {
            "pe_analysis": {
                "current": current_pe,
                "historical_avg": np.mean(pe_history),
                "percentile": pe_percentile,
                "assessment": "undervalued" if pe_percentile < 30 else "fair" if pe_percentile < 70 else "overvalued"
            },
            "pb_analysis": {
                "current": current_pb,
                "historical_avg": np.mean(pb_history),
                "percentile": pb_percentile,
                "assessment": "undervalued" if pb_percentile < 30 else "fair" if pb_percentile < 70 else "overvalued"
            }
        }
```

**实现效果**:
- PE/PB 历史分位分析
- 自动判断高估/合理/低估

---

### 3. 交叉分析增强

**问题**: 当前缺乏行业对比和交叉分析

**增强方案**:
```python
class CrossAnalyzer:
    def industry_vs_stock(self, symbol):
        """
        个股 vs 行业对比分析
        """
        # 获取个股数据
        stock_fina = get_fina_indicator(symbol)
        stock_valuation = get_daily_basic(symbol)
        
        # 获取行业平均数据
        industry = get_stock_industry(symbol)
        industry_avg = compare_industry_metrics([industry])
        industry_valuation = compare_industry_valuation([industry])
        
        # 对比分析
        comparison = {
            "profitability": {
                "stock_roe": stock_fina["roe"],
                "industry_avg_roe": industry_avg[0]["avg_value"],
                "advantage": stock_fina["roe"] > industry_avg[0]["avg_value"]
            },
            "valuation": {
                "stock_pe": stock_valuation["pe_ttm"],
                "industry_avg_pe": industry_valuation[0]["pe_ttm"],
                "premium": (stock_valuation["pe_ttm"] / industry_valuation[0]["pe_ttm"] - 1) * 100
            }
        }
        
        return comparison
```

**实现效果**:
- 个股 vs 行业平均对比
- 识别个股优势和劣势
- 判断估值溢价/折价

---

### 4. 可视化生成增强

**问题**: 当前缺乏图表生成

**增强方案**:
```python
class VisualizationGenerator:
    def generate_charts(self, data, chart_type):
        """
        生成ECharts图表配置
        """
        if chart_type == "pe_band":
            return self._generate_pe_band_chart(data)
        elif chart_type == "revenue_trend":
            return self._generate_revenue_chart(data)
        elif chart_type == "industry_comparison":
            return self._generate_comparison_chart(data)
        
    def _generate_pe_band_chart(self, pe_data):
        return {
            "type": "line",
            "title": "PE Band",
            "xAxis": pe_data["dates"],
            "series": [
                {"name": "PE", "data": pe_data["values"]},
                {"name": "PE+1σ", "data": pe_data["plus1sigma"]},
                {"name": "PE-1σ", "data": pe_data["minus1sigma"]}
            ]
        }
```

**实现效果**:
- 自动生成PE Band图
- 生成营收趋势图
- 生成行业对比图

---

## 🎯 推荐增强优先级

### Phase 1: 高优先级（立即实现）
1. **智能数据源路由** - Scout自动识别需要的数据类型
2. **财务分析增强** - 自动生成四维度财务分析
3. **个股vs行业对比** - 交叉分析能力

### Phase 2: 中优先级（1周内）
4. **估值模型** - PE/PB历史分位分析
5. **搜索结果增强** - 新闻+研报搜索
6. **可视化生成** - 自动生成图表

### Phase 3: 低优先级（按需）
7. **深度搜索** - 递归挖掘关联信息
8. **多源融合** - 网页+数据+研报综合排名

---

## 💡 一句话总结

> **搜索阶段**可以增强智能路由（自动识别数据需求）和多源搜索（新闻+研报）；**分析阶段**可以增强财务四维度分析、估值模型、个股vs行业对比、可视化生成。

最推荐优先实现的是 **智能数据源路由** 和 **财务四维度分析**，这两个能显著提升研究质量。需要我实现吗？
