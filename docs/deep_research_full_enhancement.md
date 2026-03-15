# Deep Research 全方位增强架构设计

## 核心架构思想

```
固定流程骨架 + 动态工具编排 = 灵活且可控的研究流程

┌─────────────────────────────────────────────────────────────┐
│                    Deep Research Pipeline                    │
├─────────────────────────────────────────────────────────────┤
│  Phase 1: PLAN (Architect)                                  │
│  ├── 输入: 用户查询                                          │
│  ├── 处理: 意图识别 → 任务分解 → 工具规划                     │
│  └── 输出: 研究大纲 + 工具执行计划 (Tool Execution Plan)      │
├─────────────────────────────────────────────────────────────┤
│  Phase 2: SEARCH (Scout)                                    │
│  ├── 输入: 研究大纲 + 工具执行计划                            │
│  ├── 处理: 并行数据获取 (动态工具调度)                        │
│  │   ├── 工具路由: 根据查询智能选择工具                        │
│  │   ├── 并行执行: 同时调用多个工具                           │
│  │   └── 结果融合: 合并多源数据                               │
│  └── 输出: 原始数据集合 (Raw Data Collection)                 │
├─────────────────────────────────────────────────────────────┤
│  Phase 3: ANALYZE (Wizard)                                  │
│  ├── 输入: 原始数据 + 分析策略配置                             │
│  ├── 处理: 多维度分析 (可配置分析器)                          │
│  │   ├── 财务分析器 (可选)                                    │
│  │   ├── 估值分析器 (可选)                                    │
│  │   ├── 行业分析器 (可选)                                    │
│  │   ├── 趋势分析器 (可选)                                    │
│  │   └── 风险分析器 (可选)                                    │
│  └── 输出: 分析洞察 + 可视化配置                              │
├─────────────────────────────────────────────────────────────┤
│  Phase 4: WRITE (Writer)                                    │
│  ├── 输入: 分析结果 + 报告模板配置                             │
│  ├── 处理: 模板渲染 + 内容生成                                │
│  └── 输出: 结构化报告                                         │
├─────────────────────────────────────────────────────────────┤
│  Phase 5: REVIEW (Critic)                                   │
│  ├── 输入: 报告 + 评审规则配置                                 │
│  ├── 处理: 多维度质量评审                                      │
│  └── 输出: 评分 + 改进建议                                     │
├─────────────────────────────────────────────────────────────┤
│  Phase 6: REVISE (Writer)                                   │
│  ├── 输入: 报告 + 改进建议                                     │
│  ├── 处理: 针对性修订                                          │
│  └── 输出: 最终报告                                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 详细设计方案

### 1. 配置驱动的流程控制

#### 全局配置 (GlobalConfig)

```yaml
# config/deep_research.yaml

research_config:
  # 流程开关
  phases:
    plan: { enabled: true }
    search: { enabled: true }
    analyze: { enabled: true }
    write: { enabled: true }
    review: { enabled: true }
    revise: { enabled: true }
  
  # 工具注册表
  tools:
    # 市场数据
    - name: get_quote
      skill: market_data
      category: price
      triggers: ["股价", "行情", "价格", "涨跌"]
    
    - name: get_history
      skill: market_data
      category: price
      triggers: ["走势", "历史", "K线", "趋势"]
    
    - name: get_daily_basic
      skill: market_data
      category: valuation
      triggers: ["PE", "PB", "估值", "市值", "换手率"]
    
    # 财务分析
    - name: get_fina_indicator
      skill: financial_analysis
      category: financial
      triggers: ["财务", "ROE", "ROA", "毛利率", "净利率"]
    
    - name: get_income_statement
      skill: financial_analysis
      category: financial
      triggers: ["利润表", "营收", "净利润"]
    
    # 行业分析
    - name: compare_industry_metrics
      skill: sector_analysis
      category: industry
      triggers: ["行业对比", "行业排名", "行业ROE"]
    
    - name: compare_industry_valuation
      skill: sector_analysis
      category: industry
      triggers: ["行业估值", "行业PE"]
    
    - name: get_industry_leaders
      skill: sector_analysis
      category: industry
      triggers: ["龙头", "行业第一", "行业老大"]
    
    # 网络搜索
    - name: web_search
      skill: web_research
      category: news
      triggers: ["新闻", "资讯", "最新", "动态"]
  
  # 分析器配置
  analyzers:
    financial_analyzer:
      enabled: true
      metrics: [roe, roa, gross_margin, net_margin, debt_ratio]
      output_format: table
    
    valuation_analyzer:
      enabled: true
      methods: [pe_band, pb_band, pe_percentile, pb_percentile]
      history_years: 5
    
    industry_analyzer:
      enabled: true
      comparison_scope: ["个股vs行业"]
      output_format: comparison_table
    
    trend_analyzer:
      enabled: true
      periods: [1d, 5d, 20d, 60d]
      indicators: [price_trend, volume_trend]
    
    risk_analyzer:
      enabled: true
      metrics: [volatility, beta, max_drawdown]
  
  # 报告模板
  templates:
    investment_research:
      sections: [摘要, 公司概况, 财务分析, 估值分析, 行业地位, 风险提示, 投资建议]
    
    industry_research:
      sections: [摘要, 行业概况, 竞争格局, 龙头企业, 发展趋势, 投资机会]
    
    quick_scan:
      sections: [核心观点, 关键数据, 简要结论]
```

---

### 2. 动态工具路由系统

#### 意图识别 → 工具选择

```python
class ToolRouter:
    """
    智能工具路由器
    根据用户查询自动选择需要调用的工具
    """
    
    def __init__(self, config: ResearchConfig):
        self.config = config
        self.llm = OpenAIClient()
    
    async def route(self, query: str, context: Dict = None) -> ToolExecutionPlan:
        """
        分析查询意图，生成工具执行计划
        """
        # Step 1: 意图识别
        intent = await self._analyze_intent(query)
        # {
        #   "research_type": "个股研究" | "行业研究" | "市场分析",
        #   "entities": ["600519", "白酒", "茅台"],
        #   "data_needs": ["行情", "财务", "行业"],
        #   "time_range": "最近一年",
        #   "depth": "深度" | "快速"
        # }
        
        # Step 2: 工具选择
        tools = self._select_tools(intent)
        
        # Step 3: 依赖分析
        dependencies = self._analyze_dependencies(tools)
        
        # Step 4: 执行顺序规划
        execution_order = self._plan_execution_order(tools, dependencies)
        
        return ToolExecutionPlan(
            intent=intent,
            tools=tools,
            execution_order=execution_order,
            parallel_groups=self._group_parallelizable(tools)
        )
    
    async def _analyze_intent(self, query: str) -> ResearchIntent:
        """
        使用LLM分析研究意图
        """
        prompt = f"""
分析以下查询的研究意图：
查询: {query}

请提取以下信息：
1. 研究类型: 个股研究 / 行业研究 / 市场分析 / 概念追踪
2. 涉及标的: 股票代码、行业名称、概念名称
3. 数据需求: 行情 / 财务 / 行业 / 新闻 / 资金
4. 时间范围: 实时 / 近期 / 历史
5. 研究深度: 深度分析 / 快速了解

返回JSON格式。
"""
        response = await self.llm.chat(prompt)
        return ResearchIntent.parse(response)
    
    def _select_tools(self, intent: ResearchIntent) -> List[ToolConfig]:
        """
        根据意图选择工具
        """
        selected = []
        
        # 根据研究类型选择基础工具
        if intent.research_type == "个股研究":
            selected.extend([
                self.config.get_tool("get_quote"),
                self.config.get_tool("get_daily_basic"),
                self.config.get_tool("get_fina_indicator"),
            ])
        
        elif intent.research_type == "行业研究":
            selected.extend([
                self.config.get_tool("compare_industry_metrics"),
                self.config.get_tool("compare_industry_valuation"),
                self.config.get_tool("get_industry_leaders"),
            ])
        
        # 根据数据需求补充工具
        if "历史走势" in intent.data_needs:
            selected.append(self.config.get_tool("get_history"))
        
        if "资金流向" in intent.data_needs:
            selected.append(self.config.get_tool("get_money_flow"))
            selected.append(self.config.get_tool("get_north_money"))
        
        if "新闻资讯" in intent.data_needs:
            selected.append(self.config.get_tool("web_search"))
        
        return selected
```

---

### 3. 并行执行引擎

```python
class ParallelExecutionEngine:
    """
    并行工具执行引擎
    最大化数据获取效率
    """
    
    async def execute(self, plan: ToolExecutionPlan) -> DataCollection:
        """
        执行工具计划，自动并行化
        """
        results = DataCollection()
        
        # 按并行组执行
        for group in plan.parallel_groups:
            # 组内并行执行
            group_results = await asyncio.gather(
                *[self._execute_tool(tool, plan.intent) for tool in group],
                return_exceptions=True
            )
            
            # 收集结果
            for tool, result in zip(group, group_results):
                if isinstance(result, Exception):
                    results.add_error(tool.name, result)
                else:
                    results.add_data(tool.category, result)
        
        return results
    
    async def _execute_tool(self, tool: ToolConfig, intent: ResearchIntent) -> ToolResult:
        """
        执行单个工具
        """
        # 获取工具处理器
        handler = self.tool_registry.get_handler(tool.skill, tool.name)
        
        # 构建参数
        params = self._build_params(tool, intent)
        
        # 执行
        return await handler(**params)
```

---

### 4. 可配置分析器系统

```python
class ConfigurableAnalyzer:
    """
    可配置的多维度分析器
    根据配置动态选择分析维度
    """
    
    def __init__(self, config: AnalyzerConfig):
        self.analyzers = {
            "financial": FinancialAnalyzer(config.financial),
            "valuation": ValuationAnalyzer(config.valuation),
            "industry": IndustryAnalyzer(config.industry),
            "trend": TrendAnalyzer(config.trend),
            "risk": RiskAnalyzer(config.risk),
        }
    
    async def analyze(self, data: DataCollection, plan: AnalysisPlan) -> AnalysisResult:
        """
        根据分析计划执行多维度分析
        """
        results = {}
        
        # 并行执行所有启用的分析器
        analysis_tasks = []
        for analyzer_name, enabled in plan.enabled_analyzers.items():
            if enabled and analyzer_name in self.analyzers:
                analyzer = self.analyzers[analyzer_name]
                task = analyzer.analyze(data)
                analysis_tasks.append((analyzer_name, task))
        
        # 收集结果
        for name, task in analysis_tasks:
            try:
                results[name] = await task
            except Exception as e:
                results[name] = {"error": str(e)}
        
        # 生成综合分析
        synthesis = await self._synthesize(results, data)
        
        return AnalysisResult(
            dimensions=results,
            synthesis=synthesis,
            visualizations=self._generate_visualization_config(results)
        )
```

---

### 5. 具体使用示例

#### 示例 1: 个股深度研究

```python
# 用户查询
query = "贵州茅台投资价值深度分析"

# Phase 1: Plan
plan = await deep_research.plan(query)
# 输出:
# {
#   "intent": {
#     "research_type": "个股研究",
#     "entities": ["600519", "茅台", "贵州茅台"],
#     "data_needs": ["行情", "财务", "行业", "估值"],
#     "depth": "深度"
#   },
#   "tool_plan": {
#     "parallel_groups": [
#       ["get_quote", "get_daily_basic"],           # 组1: 行情数据
#       ["get_fina_indicator", "get_income_statement"], # 组2: 财务数据
#       ["compare_industry_valuation"],              # 组3: 行业数据
#     ]
#   },
#   "analysis_plan": {
#     "enabled_analyzers": {
#       "financial": true,
#       "valuation": true,
#       "industry": true,
#       "trend": true,
#       "risk": true
#     }
#   }
# }

# Phase 2: Search (自动并行执行)
data = await deep_research.search(plan)
# 并行获取:
# - get_quote("600519")
# - get_daily_basic("600519")
# - get_fina_indicator("600519")
# - get_income_statement("600519")
# - compare_industry_valuation(["白酒"])

# Phase 3: Analyze (可配置分析器)
analysis = await deep_research.analyze(data, plan)
# 输出:
# {
#   "financial": { "roe": 25.5, "roa": 18.2, ... },
#   "valuation": { "pe_band": [...], "pe_percentile": 85 },
#   "industry": { "vs_avg": { "roe_premium": 5.3, "pe_premium": 15 } },
#   "trend": { "price_20d": +5.2%, "volume_trend": "up" },
#   "risk": { "volatility": 25, "beta": 1.2 }
# }

# Phase 4-6: Write → Review → Revise
report = await deep_research.write(analysis)
review = await deep_research.review(report)
final_report = await deep_research.revise(report, review)
```

#### 示例 2: 行业对比研究

```python
query = "银行、保险、证券哪个行业更值得投资？"

plan = await deep_research.plan(query)
# 自动识别需要对比分析
# tool_plan: [compare_industry_metrics, compare_industry_valuation, get_industry_leaders]
# analysis_plan: { financial: true, valuation: true, industry: true }

data = await deep_research.search(plan)
# 获取三个行业的数据

analysis = await deep_research.analyze(data, plan)
# 输出对比分析:
# - 银行: ROE 12%, PE 5x (低估)
# - 保险: ROE 15%, PE 12x (合理)
# - 证券: ROE 8%, PE 25x (高估)
```

---

## 架构优势

| 特性 | 传统方式 | 增强架构 |
|------|---------|---------|
| **流程控制** | 硬编码 | 配置驱动 |
| **工具选择** | 显式指定 | 智能路由 |
| **执行效率** | 串行 | 并行化 |
| **分析维度** | 固定 | 可配置 |
| **扩展性** | 差 | 插件化 |
| **适应场景** | 单一 | 多样化 |

---

## 实施路线图

### Phase 1: 基础框架（1周）
- [ ] 配置系统实现
- [ ] 工具注册表
- [ ] 基础路由逻辑

### Phase 2: 智能路由（1周）
- [ ] 意图识别模块
- [ ] 动态工具选择
- [ ] 依赖分析

### Phase 3: 并行执行（1周）
- [ ] 并行执行引擎
- [ ] 结果融合
- [ ] 错误处理

### Phase 4: 可配置分析器（2周）
- [ ] 财务分析器
- [ ] 估值分析器
- [ ] 行业分析器
- [ ] 可视化生成

### Phase 5: 模板系统（1周）
- [ ] 报告模板引擎
- [ ] 多种模板支持
- [ ] 自定义模板

需要我优先实现哪个 Phase？
