# 细粒度分层 Mock 策略设计

## 工具分类矩阵 (6 Skills × 30 Tools)

### 1. market_data (8 tools) - **建议: Mock**
| 工具 | 调用成本 | 数据稳定性 | 建议策略 | Mock 复杂度 |
|------|---------|-----------|---------|------------|
| `get_quote` | 低 | 实时变化 | **Mock** | 低 - 股票数据格式固定 |
| `search_stock` | 低 | 稳定 | **Mock** | 低 - 字典查询 |
| `get_history` | 中 | 历史固定 | **Mock** | 中 - 需要生成K线数据 |
| `get_stock_basic_info` | 低 | 稳定 | **Mock** | 低 - 静态数据 |
| `get_top_list` | 低 | 每日变化 | **Mock** | 中 - 龙虎榜结构固定 |
| `get_money_flow` | 中 | 实时变化 | **Mock** | 中 - 资金流向格式固定 |
| `get_limit_list` | 低 | 每日变化 | **Mock** | 低 - 涨跌停列表 |
| `get_company_info` | 低 | 稳定 | **Mock** | 低 - 公司资料静态 |

**Mock 理由**: Tushare API 需要 Token，且有调用频率限制。数据格式固定，Mock 质量高。

---

### 2. web_research (5 tools) - **建议: 分层**
| 工具 | 调用成本 | 数据稳定性 | 建议策略 | 说明 |
|------|---------|-----------|---------|------|
| `web_search` | 高(按次计费) | 实时变化 | **Mock** | 搜索费用高，结果难预测 |
| `knowledge_search` | 低 | 稳定 | **真实调用** | 内部知识库，无外部费用 |
| `deep_search` | 很高(递归) | 实时变化 | **Mock** | 消耗 API 次数多 |
| `extract_webpage` | 中 | 变化 | **可Mock/真实** | 视需求而定 |
| `batch_search` | 高 | 实时变化 | **Mock** | 批量搜索费用高 |

**Mock 理由**: 博查/Serper API 按次收费，Deep Search 会递归调用多次。

---

### 3. financial_analysis (3 tools) - **建议: 混合**
| 工具 | 调用成本 | 数据稳定性 | 建议策略 | 说明 |
|------|---------|-----------|---------|------|
| `get_financial_report` | 中 | 季度更新 | **Mock** | 财报数据季度发布，可缓存 |
| `calculate_financial_ratios` | 低 | 计算类 | **真实调用** | 纯计算，无外部依赖 |
| `compare_financial_data` | 低 | 计算类 | **真实调用** | 纯计算，无外部依赖 |

**策略**: 计算类工具真实调用（验证公式正确性），数据获取类 Mock。

---

### 4. risk_assessment (3 tools) - **建议: 真实调用**
| 工具 | 调用成本 | 数据稳定性 | 建议策略 | 说明 |
|------|---------|-----------|---------|------|
| `assess_portfolio_risk` | 低 | 计算类 | **真实调用** | 基于已有数据计算 |
| `calculate_risk_metrics` | 低 | 计算类 | **真实调用** | VaR、夏普比率等计算 |
| `generate_risk_report` | 低 | 生成类 | **真实调用** | 基于计算结果生成 |

**理由**: 纯计算类工具，无外部 API 费用，真实调用可验证算法正确性。

---

### 5. data_analysis (4 tools) - **建议: 真实调用**
| 工具 | 调用成本 | 数据稳定性 | 建议策略 | 说明 |
|------|---------|-----------|---------|------|
| `analyze_data` | 中 | 计算类 | **真实调用** | LLM 分析，需要验证 prompt |
| `generate_chart` | 低 | 生成类 | **真实调用** | 图表生成，验证可视化 |
| `text_to_sql` | 中 | 生成类 | **真实调用** | LLM 生成 SQL，需验证准确性 |
| `calculate_metrics` | 低 | 计算类 | **真实调用** | 纯计算 |

**理由**: 涉及 LLM 调用，需要验证 prompt 和输出质量。

---

### 6. deep_research (7 tools) - **建议: Mock**
| 工具 | 调用成本 | 数据稳定性 | 建议策略 | 说明 |
|------|---------|-----------|---------|------|
| `plan` | 中 | 生成类 | **Mock** | 研究规划 |
| `search` | 高 | 实时变化 | **Mock** | 内部会调用搜索 |
| `analyze` | 中 | 生成类 | **Mock** | 分析步骤 |
| `write` | 中 | 生成类 | **Mock** | 写作步骤 |
| `review` | 中 | 生成类 | **Mock** | 审核步骤 |
| `revise` | 中 | 生成类 | **Mock** | 修改步骤 |
| `get_state` | 低 | 状态类 | **Mock** | 获取状态 |

**理由**: Deep Research 是多步骤编排，会内部调用搜索，Mock 可加速测试。

---

## 细粒度配置方案

### 配置文件: `mock_config.yaml`

```yaml
# 全局模式
mode: "hybrid"  # real | mock | hybrid

# 按 Skill 配置
skills:
  market_data:
    mode: "mock"
    reason: "Tushare API 频率限制"
  
  web_research:
    mode: "selective"
    tools:
      web_search: "mock"
      knowledge_search: "real"
      deep_search: "mock"
      extract_webpage: "real"  # 可选
      batch_search: "mock"
  
  financial_analysis:
    mode: "selective"
    tools:
      get_financial_report: "mock"
      calculate_financial_ratios: "real"
      compare_financial_data: "real"
  
  risk_assessment:
    mode: "real"  # 全部真实调用
  
  data_analysis:
    mode: "real"  # 全部真实调用
  
  deep_research:
    mode: "mock"
    reason: "加速多步骤编排测试"

# Mock 数据配置
mock_data:
  # 按工具指定 Mock 数据文件
  market_data.get_quote: "mocks/market_data/quote.json"
  market_data.get_history: "mocks/market_data/history.json"
  web_research.web_search: "mocks/web_search/results.json"
  financial_analysis.get_financial_report: "mocks/financial/report.json"
  
  # 动态生成配置
  dynamic:
    market_data.get_quote:
      strategy: "template"  # template | random | llm
      template:
        name: "{symbol_name}"
        nowPri: "{random_price:1800-1900}"
        increase: "{random:-50-50}"
        increPer: "{random_percent:-5-5}"
    
    web_research.web_search:
      strategy: "llm"
      prompt: "根据查询 '{query}' 生成 5 条搜索结果，格式为 JSON"

# 采样策略 (控制 Mock 比例)
sampling:
  # 即使配置为 mock，也有一定概率真实调用
  mock_sampling_rate: 1.0  # 1.0 = 全部 mock, 0.1 = 10% mock
  
  # 特定工具采样率
  per_tool_sampling:
    web_research.web_search: 0.5  # 50% mock, 50% 真实

# 质量验证
validation:
  # Mock 结果与真实结果对比
  compare_with_real: false
  
  # 定期抽样验证
  sampling_validation:
    enabled: true
    interval: 100  # 每 100 次调用抽 1 次真实调用
    
  # Mock 数据新鲜度检查
  freshness_check:
    enabled: true
    max_age_days: 7  # Mock 数据最多使用 7 天
```

---

## 实现架构

```
AgentFlow Synthesis Pipeline
    ↓
MockableWorker (继承 SandboxWorker)
    ↓
策略路由
    ├── 真实调用 → Sandbox.execute() → 真实工具
    └── Mock 调用 → MockEngine → 返回预设数据
                    ↓
            ┌──────┼──────┐
            ↓      ↓      ↓
        Static  Dynamic  LLM-Gen
        Data    Template  Mock
```

### MockEngine 实现

```python
class MockEngine:
    """细粒度 Mock 引擎"""
    
    def __init__(self, config: MockConfig):
        self.config = config
        self.static_data = {}  # 静态 mock 数据
        self.template_engine = TemplateEngine()
        self.llm_client = None  # 用于 LLM 生成 mock
    
    async def mock(self, skill: str, tool: str, params: dict) -> dict:
        """根据配置返回 mock 数据"""
        
        # 1. 检查采样策略
        if not self._should_mock(skill, tool):
            return None  # 返回 None 表示需要真实调用
        
        # 2. 获取 mock 策略
        strategy = self._get_strategy(skill, tool)
        
        # 3. 根据策略生成数据
        if strategy == "static":
            return self._get_static_data(skill, tool)
        
        elif strategy == "template":
            return self._render_template(skill, tool, params)
        
        elif strategy == "llm":
            return await self._llm_generate(skill, tool, params)
        
        elif strategy == "hybrid":
            # 先尝试 static，再 fallback 到 llm
            data = self._get_static_data(skill, tool)
            if data:
                return data
            return await self._llm_generate(skill, tool, params)
```

---

## 成本对比估算

| 策略 | 单次合成成本 | 1000 条数据成本 | 质量 |
|------|-------------|----------------|------|
| 全部真实 | ¥50-100 | ¥50,000-100,000 | ⭐⭐⭐⭐⭐ |
| 全部 Mock | ¥5-10 | ¥5,000-10,000 | ⭐⭐⭐ |
| **分层策略** | **¥15-25** | **¥15,000-25,000** | **⭐⭐⭐⭐** |

---

## 推荐实施步骤

1. **Phase 1**: 实现 Static Mock (market_data + web_research)
2. **Phase 2**: 增加 Template Mock (动态生成股价、搜索结果)
3. **Phase 3**: 增加 Hybrid 采样 (10% 真实调用验证)
4. **Phase 4**: 增加 LLM-Gen Mock (生成更真实的搜索内容)

需要我实现 Phase 1 的代码吗？
