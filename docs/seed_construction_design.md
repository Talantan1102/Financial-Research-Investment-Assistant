# Seed 构造设计方案

## 1. 金融研投助手技能体系

### 1.1 7大 Skill 概览

| Skill | 工具数 | 核心能力 | 典型场景 |
|-------|-------|---------|---------|
| **market_data** | 11 | 实时行情、K线、资金流向 | 查股价、看走势 |
| **financial_analysis** | 7 | 财务报表、ROE/ROA计算 | 分析盈利能力 |
| **sector_analysis** | 7 | 行业对比、龙头识别 | 行业研究 |
| **risk_assessment** | 5 | 波动率、夏普比率、回撤 | 风险评估 |
| **deep_research** | 3 | 综合研报生成 | 深度分析 |
| **web_research** | 4 | 新闻、公告搜索 | 资讯获取 |
| **data_analysis** | 6 | 统计分析、图表 | 数据可视化 |

**总计：43个工具**

### 1.2 核心工具清单

**market_data 工具:**
- `get_quote` - 实时行情
- `search_stock` - 股票搜索
- `get_history` - 历史K线
- `get_stock_basic_info` - 基础信息
- `get_top_list` - 龙虎榜
- `get_money_flow` - 资金流向
- `get_daily_basic` - 每日指标（PE/PB）
- `get_adj_factor` - 复权因子
- `get_limit_list` - 涨跌停
- `get_concept_detail` - 概念股详情

**financial_analysis 工具:**
- `calculate_financial_ratios` - 财务比率计算
- `get_income_statement` - 利润表
- `get_balance_sheet` - 资产负债表
- `get_cash_flow` - 现金流量表
- `get_fina_indicator` - 财务指标
- `analyze_profitability` - 盈利能力分析
- `analyze_solvency` - 偿债能力分析

---

## 2. Seed 标签体系

### 2.1 核心标签（必含）

```json
{
  "tags": {
    "category": "stock_analysis",     // 数据类别
    "primary_skill": "market_data",   // 主要使用的 Skill
    "complexity": "single",           // 复杂度: single/multi/chain
    "difficulty": "medium",           // 难度: easy/medium/hard
    "stock_code": "600519.SH",        // 股票代码（如有）
    "industry": "liquor"              // 行业（如有）
  }
}
```

### 2.2 Category（数据类别）定义

| Category | 说明 | 典型 Skill 组合 |
|----------|------|----------------|
| `stock_basic` | 基础信息查询 | market_data |
| `stock_analysis` | 个股综合分析 | market_data + financial_analysis |
| `stock_risk` | 个股风险评估 | market_data + risk_assessment |
| `sector_analysis` | 行业分析 | sector_analysis + market_data |
| `sector_comparison` | 行业对比 | sector_analysis |
| `financial_deep` | 财务深度分析 | financial_analysis + data_analysis |
| `research_report` | 研报生成 | deep_research + web_research |
| `news_sentiment` | 舆情分析 | web_research + data_analysis |
| `technical_analysis` | 技术分析 | market_data + data_analysis |
| `comprehensive` | 综合分析 | 3+ Skills |

### 2.3 Complexity（复杂度）定义

| Complexity | 说明 | 示例 |
|------------|------|------|
| `single` | 单一 Skill，1-2个工具 | 查贵州茅台当前股价 |
| `multi` | 单一 Skill，3+个工具 | 查茅台股价+PE+历史走势 |
| `chain` | 多 Skill 协作 | 股价+财务+风险综合评估 |
| `control_flow` | 带控制流 | 条件判断、循环等 |

---

## 3. Seed 模板系统

### 3.1 模板变量

```python
SEED_TEMPLATES = {
    "stock_basic": [
        "查询{stock_name}({stock_code})的实时股价和基本资料",
        "{stock_name}今天股价多少？PE和PB估值如何？",
    ],
    "stock_analysis": [
        "分析{stock_name}({stock_code})的投资价值，包括估值、财务状况",
        "{stock_name}的基本面怎么样？值得投资吗？",
    ],
    "stock_risk": [
        "评估{stock_name}({stock_code})的投资风险，计算夏普比率和最大回撤",
        "{stock_name}的风险高吗？波动率如何？",
    ],
    "sector_analysis": [
        "分析{industry}行业的现状和龙头企业",
        "{industry}板块有哪些龙头股？",
    ],
    "sector_comparison": [
        "对比{industry1}和{industry2}两个行业的估值和投资价值",
        "白酒和新能源哪个行业更值得投资？",
    ],
    # ... 更多模板
}
```

### 3.2 股票池设计

**A股核心股票池（50只）:**

```python
STOCK_POOL = {
    # 白酒（5只）
    "liquor": [
        {"name": "贵州茅台", "code": "600519.SH", "tags": ["龙头", "高端"]},
        {"name": "五粮液", "code": "000858.SZ", "tags": ["龙头", "高端"]},
        {"name": "泸州老窖", "code": "000568.SZ", "tags": ["次高端"]},
        {"name": "山西汾酒", "code": "600809.SH", "tags": ["清香型"]},
        {"name": "洋河股份", "code": "002304.SZ", "tags": ["浓香型"]},
    ],
    # 新能源（5只）
    "new_energy": [
        {"name": "宁德时代", "code": "300750.SZ", "tags": ["龙头", "电池"]},
        {"name": "比亚迪", "code": "002594.SZ", "tags": ["整车", "龙头"]},
        {"name": "隆基绿能", "code": "601012.SH", "tags": ["光伏", "硅片"]},
        {"name": "阳光电源", "code": "300274.SZ", "tags": ["逆变器"]},
        {"name": "通威股份", "code": "600438.SH", "tags": ["硅料", "电池"]},
    ],
    # 银行（5只）
    "bank": [
        {"name": "招商银行", "code": "600036.SH", "tags": ["股份制", "零售"]},
        {"name": "工商银行", "code": "601398.SH", "tags": ["国有大行"]},
        {"name": "平安银行", "code": "000001.SZ", "tags": ["股份制"]},
        {"name": "宁波银行", "code": "002142.SZ", "tags": ["城商行"]},
        {"name": "常熟银行", "code": "601128.SH", "tags": ["农商行"]},
    ],
    # 科技（5只）
    "technology": [
        {"name": "中芯国际", "code": "688981.SH", "tags": ["芯片", "制造"]},
        {"name": "海康威视", "code": "002415.SZ", "tags": ["安防", "龙头"]},
        {"name": "立讯精密", "code": "002475.SZ", "tags": ["消费电子"]},
        {"name": "北方华创", "code": "002371.SZ", "tags": ["半导体设备"]},
        {"name": "韦尔股份", "code": "603501.SH", "tags": ["芯片设计"]},
    ],
    # 医药（5只）
    "pharmaceutical": [
        {"name": "恒瑞医药", "code": "600276.SH", "tags": ["创新药", "龙头"]},
        {"name": "迈瑞医疗", "code": "300760.SZ", "tags": ["医疗器械"]},
        {"name": "药明康德", "code": "603259.SH", "tags": ["CXO"]},
        {"name": "爱尔眼科", "code": "300015.SZ", "tags": ["医疗服务"]},
        {"name": "片仔癀", "code": "600436.SH", "tags": ["中药", "绝密配方"]},
    ],
    # ... 更多行业
}
```

---

## 4. Seed 生成策略

### 4.1 生成维度

**维度1: 按 Skill 覆盖**
- 每个 Skill 生成 N 个 Seed
- 确保所有 43 个工具都被覆盖

**维度2: 按复杂度覆盖**
- `single`: 40%
- `multi`: 35%
- `chain`: 20%
- `control_flow`: 5%

**维度3: 按行业覆盖**
- 每个行业生成 M 个 Seed
- 确保行业分布均衡

**维度4: 按难度覆盖**
- `easy`: 30%
- `medium`: 50%
- `hard`: 20%

### 4.2 生成算法

```python
def generate_seeds(
    total_count: int = 1000,
    stock_pool: Dict = STOCK_POOL,
    templates: Dict = SEED_TEMPLATES
) -> List[Dict]:
    """
    生成 Seed 数据
    
    Args:
        total_count: 目标 Seed 数量
        stock_pool: 股票池
        templates: 模板库
    
    Returns:
        Seed 列表
    """
    seeds = []
    
    # 1. 按 Skill 覆盖生成
    for skill_name in SKILLS.keys():
        skill_seeds = generate_skill_seeds(skill_name, count=total_count//7)
        seeds.extend(skill_seeds)
    
    # 2. 按复杂度平衡
    seeds = balance_complexity(seeds)
    
    # 3. 去重
    seeds = deduplicate(seeds)
    
    # 4. 添加 kwargs
    seeds = add_kwargs(seeds)
    
    return seeds[:total_count]
```

---

## 5. Seed 示例

### 5.1 Single 复杂度示例

```json
{
  "content": "查询贵州茅台(600519.SH)的实时股价",
  "kwargs": {
    "tags": {
      "category": "stock_basic",
      "primary_skill": "market_data",
      "complexity": "single",
      "difficulty": "easy",
      "stock_code": "600519.SH",
      "industry": "liquor"
    },
    "timeout": 30
  }
}
```

### 5.2 Multi 复杂度示例

```json
{
  "content": "分析贵州茅台(600519.SH)的估值情况，包括当前PE、PB和历史估值分位",
  "kwargs": {
    "tags": {
      "category": "stock_analysis",
      "primary_skill": "market_data",
      "complexity": "multi",
      "difficulty": "medium",
      "stock_code": "600519.SH",
      "industry": "liquor"
    },
    "timeout": 60
  }
}
```

### 5.3 Chain 复杂度示例

```json
{
  "content": "评估宁德时代(300750.SZ)的投资价值，包括财务健康度、估值水平和行业地位",
  "kwargs": {
    "tags": {
      "category": "comprehensive",
      "primary_skill": "financial_analysis",
      "secondary_skills": ["market_data", "sector_analysis"],
      "complexity": "chain",
      "difficulty": "hard",
      "stock_code": "300750.SZ",
      "industry": "new_energy"
    },
    "timeout": 120
  }
}
```

---

## 6. 数据规模建议

| 阶段 | Seed 数量 | 生成 QA 数量 | 用途 |
|------|----------|-------------|------|
| **实验阶段** | 50-100 | 100-200 | 验证流程 |
| **小规模** | 200-500 | 500-1000 | 模型微调 |
| **中规模** | 1000-3000 | 3000-8000 | 模型训练 |
| **大规模** | 5000+ | 15000+ | 生产级 |

### 6.1 第一阶段目标（实验阶段）

**100 个 Seed，预计生成 200-300 个 QA**

| Skill | Seed 数 | 占比 |
|-------|--------|------|
| market_data | 20 | 20% |
| financial_analysis | 15 | 15% |
| sector_analysis | 15 | 15% |
| risk_assessment | 10 | 10% |
| deep_research | 10 | 10% |
| web_research | 15 | 15% |
| data_analysis | 15 | 15% |

---

## 7. 实施计划

### 7.1 立即执行（今天）

1. **编写 Seed 生成脚本**
   - 读取股票池
   - 应用模板生成 Seed
   - 自动添加 kwargs 标签

2. **生成实验阶段 100 个 Seed**
   - 手动验证质量
   - 运行 Pipeline 生成 QA

### 7.2 后续优化

1. **扩展股票池** - 从 50 只扩展到 200 只
2. **丰富模板** - 每个 category 至少 10 个模板
3. **自动化验证** - 确保工具覆盖率 100%

---

## 8. 决策点

**请磊总确认**:

1. **第一阶段规模**: 100 个 Seed 是否合适？
2. **股票池**: 50 只核心股票是否足够？需要补充哪些行业？
3. **复杂度分布**: single:multi:chain = 40:35:20 是否合理？
4. **标签体系**: 是否有需要添加或调整的标签？

---

**文档版本**: v1.0  
**编写日期**: 2026-03-21  
**编写人**: 卤蛋 🐤
