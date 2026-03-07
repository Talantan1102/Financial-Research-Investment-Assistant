# GRPO训练数据构造方案 - 标签体系与执行计划

> 基于行业信息助手项目场景的深度调研报告
> 
> **文档状态**: 规划阶段 | **最后更新**: 2026-03-04

---

## 第一部分：调研分析

### 1.1 现有GRPO数据构造方法调研

#### 方法1：DeepSeek-R1路线（冷启动+RL）

**核心流程**：
```
少量高质量SFT数据（数千条）→ GRPO强化学习 → 自我进化
```

**数据来源**：
- 数学领域：GSM8K、MATH、NuminaMath（精选子集）
- 代码领域：HumanEval、CodeContest
- 通用推理：合成逻辑推理题

**优点**：
- 数据量需求小（几千条即可启动）
- 通过RL自我扩展，边际成本低
- 数学/代码领域验证成熟

**缺点**：
- 需要高质量种子数据
- 对reward函数设计敏感
- 金融领域缺乏现成数据集

**适合度评估**：⭐⭐⭐⭐☆（4/5）
- ✅ 数据量需求适合单人
- ❌ 需要领域适配

---

#### 方法2：OpenAI o1路线（大规模合成）

**核心流程**：
```
问题生成器 → 多模型投票生成答案 → 质量过滤 → 训练数据
```

**数据来源**：
- 使用GPT-4/Claude等强模型生成 reasoning traces
- 多模型交叉验证筛选高质量数据
- 数十万到百万级数据量

**优点**：
- 数据多样性高
- 覆盖广泛场景

**缺点**：
- 数据量需求大（10万+）
- API成本高（数千美元）
- 质量过滤工程量大

**适合度评估**：⭐⭐☆☆☆（2/5）
- ❌ 数据量过大
- ❌ 成本过高
- ❌ 单人难以完成

---

#### 方法3：学术数据集改造路线

**核心流程**：
```
公开学术数据集（GSM8K/MATH等）→ 领域适配改造 → 训练
```

**数据来源**：
- 数学推理：GSM8K（8.5K）、MATH（12K）
- 金融数学：FinQA、ConvFinQA（少量）
- 通用QA：Natural Questions等

**优点**：
- 数据质量有保障
- 免费获取
- 验证充分

**缺点**：
- 金融/行业分析数据稀缺
- 需要大量改造工作
- 场景匹配度不高

**适合度评估**：⭐⭐⭐☆☆（3/5）
- ✅ 数据质量高
- ❌ 需要大量改造

---

### 1.2 关键结论：适合单人的混合策略

基于调研，推荐采用 **"DeepSeek-R1路线 + 领域专家知识注入"** 的混合策略：

| 策略要素 | 说明 | 原因 |
|---------|------|------|
| **种子数据** | 3-5K条高质量领域数据 | 单人可完成标注/生成 |
| **数据合成** | 基于模板+LLM批量生成 | 降低成本，保证多样性 |
| **质量筛选** | 规则过滤+人工抽检 | 保证训练稳定性 |
| **渐进扩展** | 先训小模型验证再扩展 | 降低试错成本 |

---

## 第二部分：场景分析

### 2.1 行业信息助手的核心任务场景

基于项目实际功能，定义以下**一级任务类型**：

```
TASK_TYPE
├── INFORMATION_RETRIEVAL      # 信息检索类
├── NUMERIC_COMPUTATION        # 数值计算类
├── COMPARATIVE_ANALYSIS       # 对比分析类
├── TREND_PREDICTION           # 趋势预测类
├── REPORT_GENERATION          # 报告生成类
├── CONFLICT_RESOLUTION        # 冲突解决类
└── TOOL_ORCHESTRATION         # 工具调度类
```

---

### 2.2 二级场景细分

#### 2.2.1 INFORMATION_RETRIEVAL（信息检索）

**定义**：从多源信息中提取准确事实

**子场景**：
| 子类型 | 说明 | 示例 |
|-------|------|------|
| `FACT_EXTRACTION` | 事实提取 | "2024年宁德时代装机量是多少？" |
| `DATA_LOCATION` | 数据定位 | "某研报中提到的市场份额数据在哪里？" |
| `SOURCE_VERIFICATION` | 来源验证 | "验证这个数据是否来自官方统计" |
| `MULTI_SOURCE_SYNTHESIS` | 多源合成 | "综合三个来源给出市场规模的置信区间" |

**所需工具**：
- `web_search` - 网络搜索
- `document_retrieval` - 文档检索
- `knowledge_base_query` - 知识库查询

**难度分布**：
- Easy: 40%（直接可检索的事实）
- Medium: 40%（需要多源交叉）
- Hard: 20%（需要深度推理）

---

#### 2.2.2 NUMERIC_COMPUTATION（数值计算）

**定义**：基于财务/市场数据进行计算分析

**子场景**：
| 子类型 | 说明 | 示例 |
|-------|------|------|
| `FINANCIAL_RATIO` | 财务比率计算 | "计算ROE、毛利率、净利率" |
| `GROWTH_ANALYSIS` | 增长分析 | "计算CAGR、同比增长率" |
| `VALUATION_METRICS` | 估值指标 | "计算PE、PB、EV/EBITDA" |
| `MARKET_SIZE_CALC` | 市场规模计算 | "基于渗透率推算市场容量" |
| `UNIT_CONVERSION` | 单位换算 | "Wh到kWh，亿元到美元" |

**常见计算陷阱**（重点训练）：
1. **基期陷阱**："增长50%后再下降50%，回到原点？"
2. **单位陷阱**："0.8元/Wh vs 800元/kWh"
3. **年化陷阱**："季度增长10%，年化增长不是40%"
4. **同比/环比混淆**：不同基期的比较

**所需工具**：
- `calculator` - 计算器
- `data_retrieval` - 数据获取
- `formula_lookup` - 公式查询

**难度分布**：
- Easy: 30%（单一计算）
- Medium: 50%（多步计算）
- Hard: 20%（复杂建模）

---

#### 2.2.3 COMPARATIVE_ANALYSIS（对比分析）

**定义**：多主体、多指标的对比评估

**子场景**：
| 子类型 | 说明 | 示例 |
|-------|------|------|
| `COMPANY_COMPARISON` | 公司对比 | "比亚迪vs特斯拉财务对比" |
| `INDUSTRY_BENCHMARK` | 行业对标 | "某公司毛利率vs行业平均" |
| `TIME_SERIES_COMPARISON` | 时序对比 | "今年vs去年同期表现" |
| `SCENARIO_ANALYSIS` | 情景分析 | "乐观/中性/悲观情景下的预测" |

**输出格式**：
- 结构化表格
- 优劣分析
- 关键差异解读

**所需工具**：
- `multi_query_search` - 多查询搜索
- `chart_generator` - 图表生成
- `data_analyzer` - 数据分析

---

#### 2.2.4 TREND_PREDICTION（趋势预测）

**定义**：基于历史数据和当前信息预判趋势

**子场景**：
| 子类型 | 说明 | 示例 |
|-------|------|------|
| `MARKET_FORECAST` | 市场预测 | "预测2025年新能源车销量" |
| `PRICE_TREND` | 价格走势 | "分析锂价未来6个月走势" |
| `TECHNOLOGY_DIFFUSION` | 技术扩散 | "固态电池商业化时间预测" |
| `POLICY_IMPACT` | 政策影响 | "双积分政策调整的影响" |

**预测要素**（训练中需体现）：
1. 历史数据回顾
2. 驱动因素分析
3. 风险因素评估
4. 置信区间表达
5. 情景假设说明

---

#### 2.2.5 REPORT_GENERATION（报告生成）

**定义**：生成结构化研究报告

**子场景**：
| 子类型 | 说明 | 示例 |
|-------|------|------|
| `INDUSTRY_DEEP_DIVE` | 行业深度 | "生成锂电池行业深度报告" |
| `COMPANY_PROFILE` | 公司画像 | "生成某公司投资分析报告" |
| `MARKET_BRIEF` | 市场简报 | "生成本周市场动态简报" |
| `DATA_VISUALIZATION` | 数据可视化 | "为数据生成分析图表" |

**报告结构模板**：
```
1. 执行摘要
2. 行业/公司概况
3. 市场数据分析
4. 竞争格局
5. 风险提示
6. 结论与建议
```

---

#### 2.2.6 CONFLICT_RESOLUTION（冲突解决）

**定义**：处理信息矛盾和数据不一致

**子场景**：
| 子类型 | 说明 | 示例 |
|-------|------|------|
| `DATA_RECONCILIATION` | 数据调和 | "三个来源数据不一致如何处理" |
| `FACT_CHECKING` | 事实核查 | "验证某个市场传言的真实性" |
| `SOURCE_EVALUATION` | 来源评估 | "评估不同数据源的可靠性" |
| `UNCERTAINTY_QUANTIFICATION` | 不确定性量化 | "给出置信区间而非点估计" |

**关键能力**：
- 识别矛盾来源（统计口径、时间点、定义差异）
- 评估来源可信度
- 给出置信评估
- 说明不确定性

---

#### 2.2.7 TOOL_ORCHESTRATION（工具调度）

**定义**：智能选择和组合多个工具完成任务

**子场景**：
| 子类型 | 说明 | 示例 |
|-------|------|------|
| `SEQUENTIAL_TOOL_USE` | 顺序工具调用 | "先搜索数据，再计算比率" |
| `PARALLEL_SEARCH` | 并行搜索 | "同时搜索多个公司数据" |
| `CONDITIONAL_EXECUTION` | 条件执行 | "根据初步结果决定深入方向" |
| `ERROR_RECOVERY` | 错误恢复 | "搜索失败时切换数据源" |

---

## 第三部分：标签体系设计

### 3.1 标签体系总览

```yaml
# 核心标签体系
data_sample:
  # === 基础标识 ===
  id: str                    # 唯一标识符
  version: str               # 数据版本（用于迭代管理）
  source: str                # 数据来源
  
  # === 任务标签（2层）===
  task_type:                 # 一级：任务类型
    type: enum               # INFORMATION_RETRIEVAL | NUMERIC_COMPUTATION | ...
  task_subtype:              # 二级：子类型
    type: enum               # FACT_EXTRACTION | FINANCIAL_RATIO | ...
  
  # === 领域标签 ===
  domain:                    # 行业领域
    type: enum               # NEW_ENERGY | SEMICONDUCTOR | HEALTHCARE | ...
  sub_domain:                # 细分领域
    type: str                # 如：动力电池、光伏组件
  
  # === 难度标签 ===
  difficulty:                # 难度等级
    type: enum               # EASY | MEDIUM | HARD
  difficulty_reason:         # 难度原因说明
    type: str
  
  # === 能力标签 ===
  required_capabilities:     # 所需能力
    type: list[enum]         # REASONING | CALCULATION | KNOWLEDGE | ...
  
  # === 工具标签 ===
  tools_required:            # 需要调用的工具
    type: list[enum]         # WEB_SEARCH | CALCULATOR | CHART_GEN | ...
  tool_orchestration_type:   # 工具调度类型
    type: enum               # SINGLE | SEQUENTIAL | PARALLEL | CONDITIONAL
  
  # === 质量标签 ===
  quality_tier:              # 质量等级
    type: enum               # GOLD | SILVER | BRONZE
  verification_status:       # 验证状态
    type: enum               # VERIFIED | UNVERIFIED | DISPUTED
  
  # === 数据内容 ===
  prompt: str                # 输入提示
  reference_answer: str      # 参考答案
  reasoning_process: str     # 期望推理过程
  
  # === 评估标签 ===
  evaluation_criteria:       # 评估标准
    type: dict               # 各维度权重
  common_mistakes:           # 常见错误
    type: list[str]          # 用于负样本生成
```

---

### 3.2 详细标签定义

#### 3.2.1 任务类型（task_type）

| 值 | 说明 | 占比目标 |
|----|------|---------|
| `INFORMATION_RETRIEVAL` | 信息检索类 | 25% |
| `NUMERIC_COMPUTATION` | 数值计算类 | 30% |
| `COMPARATIVE_ANALYSIS` | 对比分析类 | 15% |
| `TREND_PREDICTION` | 趋势预测类 | 10% |
| `REPORT_GENERATION` | 报告生成类 | 10% |
| `CONFLICT_RESOLUTION` | 冲突解决类 | 5% |
| `TOOL_ORCHESTRATION` | 工具调度类 | 5% |

#### 3.2.2 难度等级（difficulty）

| 等级 | 定义 | 特征 | 占比目标 |
|------|------|------|---------|
| `EASY` | 基础任务 | 单步推理、直接检索、标准计算 | 30% |
| `MEDIUM` | 进阶任务 | 多步推理、简单综合、多源对比 | 50% |
| `HARD` | 复杂任务 | 深度推理、复杂建模、矛盾处理 | 20% |

**难度判定标准**：
```yaml
EASY:
  - 推理步骤: 1-2步
  - 工具调用: 单一工具
  - 知识需求: 常识性或可直接检索
  - 计算复杂度: 单一公式直接计算

MEDIUM:
  - 推理步骤: 3-5步
  - 工具调用: 2-3个工具顺序调用
  - 知识需求: 需要领域知识整合
  - 计算复杂度: 多步计算或简单建模

HARD:
  - 推理步骤: 5步以上
  - 工具调用: 多工具复杂调度
  - 知识需求: 深度专业知识+推理
  - 计算复杂度: 复杂建模或多情景分析
```

#### 3.2.3 领域标签（domain）

| 一级领域 | 二级领域示例 | 占比目标 |
|---------|-------------|---------|
| `NEW_ENERGY` | 动力电池、光伏、储能、新能源车 | 30% |
| `SEMICONDUCTOR` | 芯片设计、制造、设备、材料 | 15% |
| `HEALTHCARE` | 医药、医疗器械、生物科技 | 10% |
| `CONSUMER` | 食品饮料、家电、零售 | 10% |
| `TMT` | 互联网、软件、通信 | 10% |
| `FINANCIAL` | 银行、保险、证券 | 10% |
| `MANUFACTURING` | 机械、化工、材料 | 10% |
| `GENERAL` | 跨领域通用 | 5% |

#### 3.2.4 能力标签（required_capabilities）

| 能力 | 说明 | 关联任务类型 |
|------|------|-------------|
| `ARITHMETIC` | 基础运算能力 | NUMERIC_COMPUTATION |
| `ALGEBRAIC` | 代数建模能力 | NUMERIC_COMPUTATION |
| `LOGICAL` | 逻辑推理能力 | ALL |
| `TEMPORAL` | 时序推理能力 | TREND_PREDICTION |
| `SPATIAL` | 空间/结构理解 | REPORT_GENERATION |
| `CAUSAL` | 因果推断能力 | TREND_PREDICTION |
| `KNOWLEDGE` | 领域知识调用 | INFORMATION_RETRIEVAL |
| `METACOGNITIVE` | 元认知（知道不知道） | CONFLICT_RESOLUTION |

#### 3.2.5 工具标签（tools_required）

| 工具 | 说明 | 使用场景 |
|------|------|---------|
| `WEB_SEARCH` | 网络搜索 | 获取实时信息 |
| `DOCUMENT_RETRIEVAL` | 文档检索 | 检索内部知识库 |
| `CALCULATOR` | 计算器 | 精确数值计算 |
| `CHART_GENERATOR` | 图表生成 | 数据可视化 |
| `FORMULA_LOOKUP` | 公式查询 | 查找计算公式 |
| `DATA_TABLE` | 数据表查询 | 查询结构化数据 |
| `COMPARISON_ENGINE` | 对比引擎 | 多维度对比分析 |

---

### 3.3 质量等级体系

#### 3.3.1 质量等级定义

| 等级 | 标准 | 使用策略 |
|------|------|---------|
| `GOLD` | 人工验证100%准确，推理完整 | 核心训练集，必须高质量 |
| `SILVER` | 经过规则验证，大概率准确 | 扩展训练集，用于增加多样性 |
| `BRONZE` | LLM生成，未经充分验证 | 预训练/实验使用，谨慎使用 |

#### 3.3.2 升级/降级规则

```yaml
升级条件:
  BRONZE→SILVER:
    - 通过自动化规则验证
    - 与已知正确答案匹配
    - 格式完全合规
  
  SILVER→GOLD:
    - 人工验证准确
    - 推理过程合理
    - 有明确来源支持

降级条件:
  - 发现事实错误
  - 推理过程有漏洞
  - 来源不可靠
```

---

## 第四部分：数据构造执行计划

### 4.1 总体策略

**数据规模规划**：
| 阶段 | 数据量 | 质量等级 | 用途 |
|------|-------|---------|------|
| 种子数据 | 500条 | GOLD | 冷启动SFT |
| 核心训练集 | 3,000条 | GOLD+SILVER | 主要训练 |
| 扩展集 | 2,000条 | SILVER | 多样性增强 |
| **总计** | **5,500条** | - | - |

**时间规划**：2周完成数据构造

---

### 4.2 详细执行步骤

#### Week 1: 基础设施 + 种子数据

**Day 1-2: 标签体系落地**

任务：
1. 将标签体系转化为代码配置
2. 设计数据验证规则
3. 创建数据存储结构

产出：
- `config/label_schema.yaml` - 标签体系配置
- `src/data_validator.py` - 数据验证器
- `data/raw/` - 原始数据目录结构

**Day 3-4: 公开数据收集**

任务：
1. 收集公开研报PDF（20-30份）
2. 提取结构化数据
3. 标注GOLD级样本（100条）

数据来源：
- 巨潮资讯网（上市公司年报/研报）
- 券商研报（摘要部分）
- 行业协会统计公报

产出：
- `data/processed/from_reports.jsonl` (100条GOLD)

**Day 5-7: 专家场景设计**

任务：
1. 设计200个典型金融分析场景
2. 手工编写问答对
3. 交叉验证准确性

场景模板：
- 财务比率计算（50个）
- 增长分析（50个）
- 估值计算（50个）
- 对比分析（50个）

产出：
- `data/processed/expert_designed.jsonl` (200条GOLD)

**Week 1 产出总结**：
- GOLD级数据：300条
- 验证工具：完成
- 数据 pipeline：搭建完成

---

#### Week 2: 扩展数据 + 质量验证

**Day 8-9: LLM辅助生成（模板化）**

任务：
1. 设计数据生成模板（20个模板）
2. 使用LLM批量生成数据
3. 规则过滤初筛

模板示例：
```python
# 财务比率计算模板
template = {
    "task_type": "NUMERIC_COMPUTATION",
    "task_subtype": "FINANCIAL_RATIO",
    "template": "某公司{year}年营收{revenue}亿元，净利润{profit}亿元，总资产{assets}亿元，股东权益{equity}亿元。请计算：1)净利率 2)ROE 3)ROA",
    "variables": {
        "year": [2023, 2024],
        "revenue": [100, 200, 500, 1000, 2000],
        "profit": [10, 20, 50, 100, 200],
        "assets": [200, 500, 1000, 2000, 5000],
        "equity": [100, 200, 500, 1000, 2000]
    }
}
```

产出：
- `data/processed/llm_generated.jsonl` (2,000条BRONZE)

**Day 10-11: 对抗性样本设计**

任务：
1. 识别常见错误类型（10类）
2. 针对每类设计陷阱题（20个/类）
3. 编写对抗性测试集

错误类型：
1. 单位混淆（Wh vs kWh）
2. 基期错误（同比vs环比）
3. 年化错误（简单相加）
4. 百分比计算错误（增长vs占比）
5. 时间区间错误（包含端点）
6. 口径差异（含/不含税）
7. 币种混淆（人民币vs美元）
8. 指标混淆（营收vs净利润）
9. 逻辑谬误（因果倒置）
10. 过度推断（趋势外推）

产出：
- `data/processed/adversarial_cases.jsonl` (200条GOLD)

**Day 12-13: 数据清洗与升级**

任务：
1. 应用验证规则筛选LLM生成数据
2. 将验证通过的BRONZE→SILVER
3. 人工抽检升级部分数据→GOLD

验证规则：
- 数值计算可验证（公式正确）
- 格式合规（包含think/answer标签）
- 答案非空且合理
- 难度标签准确

产出：
- `data/processed/upgraded_silver.jsonl` (1,000条SILVER)
- `data/processed/upgraded_gold.jsonl` (200条GOLD)

**Day 14: 数据集合并与验证**

任务：
1. 合并所有数据源
2. 统计标签分布
3. 平衡数据集
4. 划分train/val/test

产出：
- `data/final/train.jsonl` (4,500条)
- `data/final/val.jsonl` (500条)
- `data/final/test.jsonl` (500条)
- `data/final/dataset_report.md` - 数据报告

**Week 2 产出总结**：
- SILVER级数据：1,000条
- GOLD级数据：500条（累计800条）
- 完整数据集：5,500条

---

### 4.3 质量保障检查点

#### 检查点1：种子数据质量（Day 7）

**检查项**：
- [ ] GOLD数据≥300条
- [ ] 每类task_type≥30条
- [ ] 人工验证准确率≥95%
- [ ] 格式合规率100%

**不通过处理**：
- 补充人工标注
- 降低部分数据难度重新设计

#### 检查点2：扩展数据质量（Day 11）

**检查项**：
- [ ] 生成数据≥2,000条
- [ ] 规则通过率≥60%
- [ ] 对抗性样本覆盖10类错误

**不通过处理**：
- 优化生成模板
- 调整LLM prompt
- 增加规则约束

#### 检查点3：最终数据质量（Day 14）

**检查项**：
- [ ] 总数据量≥5,000条
- [ ] 标签分布合理（见3.2节目标占比）
- [ ] GOLD:SILVER:BRONZE ≈ 15:35:50
- [ ] 难度分布 Easy:Medium:Hard ≈ 30:50:20
- [ ] 领域分布覆盖前5大领域

**不通过处理**：
- 针对性补充稀缺类别
- 调整采样策略

---

## 第五部分：Reward函数设计指南

### 5.1 多维度Reward设计

基于标签体系，设计组合式reward函数：

```python
# Reward权重配置
REWARD_WEIGHTS = {
    "format_compliance": 0.15,      # 格式合规
    "reasoning_quality": 0.25,      # 推理质量
    "answer_accuracy": 0.35,        # 答案准确性（核心）
    "tool_usage": 0.15,             # 工具使用正确性
    "confidence_expression": 0.10,  # 置信度表达
}
```

### 5.2 任务类型特异性Reward

| 任务类型 | 核心评估维度 | 特殊奖励项 |
|---------|-------------|-----------|
| NUMERIC_COMPUTATION | 数值准确性 | 计算过程可复现 |
| INFORMATION_RETRIEVAL | 事实准确性 | 来源可追溯 |
| COMPARATIVE_ANALYSIS | 对比完整性 | 结构化输出 |
| TREND_PREDICTION | 逻辑合理性 | 置信区间表达 |
| CONFLICT_RESOLUTION | 矛盾识别 | 不确定性量化 |

---

## 第六部分：面试呈现要点

### 6.1 项目亮点总结

**数据层面的创新**：
1. **领域特化**：首个面向金融/行业分析的GRPO训练数据集
2. **标签体系完整**：7大任务类型 + 4级难度 + 7大领域覆盖
3. **质量分层**：GOLD/SILVER/BRONZE三级质量管控
4. **对抗性设计**：10类常见错误陷阱，针对性提升鲁棒性

**方法论创新**：
1. **小数据+高质量**：5K条精品数据 > 50K条低质数据
2. **渐进式构建**：种子→扩展→对抗→验证，每一步可验证
3. **单人可执行**：所有步骤设计为1人2周可完成

### 6.2 可能的面试官问题

**Q1: 为什么只有5K条数据？**

> "我们采用了DeepSeek-R1验证过的策略：高质量种子数据+RL自我扩展。5K条GOLD+SILVER级数据足以启动训练，远胜于50K条未验证数据。事实上，GSM8K只有8K条数据，但训练效果远超百万级低质数据。"

**Q2: 如何保证数据质量？**

> "我们建立了三级质量体系：
> 1. **GOLD级**：人工100%验证，推理完整
> 2. **SILVER级**：通过自动化规则验证
> 3. **BRONZE级**：LLM生成，仅用于实验
> 
> 训练时主要使用GOLD+SILVER，占比50%以上。"

**Q3: 数据分布如何设计？**

> "基于行业分析的实际场景：
> - 30%数值计算（财务分析核心）
> - 25%信息检索（数据收集）
> - 15%对比分析（竞品对标）
> - 其他类型覆盖完整工作流
> 
> 难度分布遵循真实场景：Easy 30%、Medium 50%、Hard 20%"

---

## 附录：工具清单

### 必需工具

| 工具 | 用途 | 获取方式 |
|------|------|---------|
| Python 3.10+ | 数据处理 | 官方安装 |
| PyYAML | 配置文件解析 | pip install pyyaml |
| Pandas | 数据分析 | pip install pandas |
| OpenAI SDK | LLM调用 | pip install openai |

### 可选工具

| 工具 | 用途 | 备注 |
|------|------|------|
| Jupyter Notebook | 数据探索 | 推荐 |
| Label Studio | 数据标注 | 如需团队协作 |

---

## 文档版本记录

| 版本 | 日期 | 修改内容 |
|------|------|---------|
| v0.1 | 2026-03-04 | 初始版本，完成标签体系设计 |
| v0.2 | TBD | 根据执行反馈调整 |

---

**下一步行动**：
1. 确认标签体系设计
2. 开始Day 1-2的基础设施建设
3. 同步准备公开数据源清单

