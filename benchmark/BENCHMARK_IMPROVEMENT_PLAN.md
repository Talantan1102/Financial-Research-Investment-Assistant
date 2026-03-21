# 金融研投助手 Benchmark 改进方案

**版本**: v1.0  
**日期**: 2026-03-21  
**作者**: AI Assistant  

---

## 一、核心问题诊断

```
┌─────────────────────────────────────────────────────────────────┐
│                        问题根因分析                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │ 测试用例结构   │───▶│ Prompt模糊   │───▶│ 评估逻辑缺陷  │      │
│  │ 设计缺陷      │    │ 主观/缺参数   │    │ 二值判断      │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │              │
│         ▼                   ▼                   ▼              │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 结果: Skill准确率34.7%, 大量误判, 测试价值降低            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 当前关键问题

| 问题 | 影响 | 严重程度 |
|------|------|----------|
| 65%测试用例 `expected_skill` 为空 | 必然判错，准确率失真 | 🔴 严重 |
| Prompt模糊（"全面分析"、"看看"） | LLM行为不可预测 | 🔴 严重 |
| 评估逻辑只允许精确匹配 | 否定功能等价的替代方案 | 🟡 中度 |
| 控制流测试评估不当 | For-Each重复工具被判错 | 🟡 中度 |
| 缺少参数（"今天"、"低估值"） | 工具调用失败 | 🟡 中度 |

---

## 二、改进方案架构

### 2.1 测试用例结构重设计

#### 当前结构（问题版）
```json
{
  "id": "MULTI-001",
  "query": "全面分析一下茅台这只股票",      // ❌ 模糊
  "expected_skill": "",                      // ❌ 65%为空
  "expected_tools": ["a", "b", "c", "d"],   // ❌ 过于具体
  "complexity": "medium"
}
```

#### 新结构（改进版）
```json
{
  "id": "MULTI-001",
  "query": "生成一份茅台的深度研究报告",     // ✅ 明确动作+对象
  "query_variants": [                        // ✅ 同义表达
    "生成一份茅台的深度研究报告",
    "帮我写一份茅台的投资分析报告"
  ],
  
  "intent": {                                // ✅ 显式定义意图
    "primary_skill": "deep_research",
    "acceptable_skills": ["deep_research"],
    "min_tools": 1,
    "max_tools": 3
  },
  
  "expected_capabilities": [                 // ✅ 能力导向
    "stock_quote",
    "financial_metrics",
    "risk_assessment"
  ],
  
  "evaluation": {                            // ✅ 灵活评估
    "mode": "functional",
    "required_data_fields": ["price", "pe", "pb", "roe"],
    "forbidden_patterns": ["无法获取", "数据错误"],
    "min_response_length": 100
  },
  
  "metadata": {
    "category": "single_skill_deep",
    "control_flow": null,
    "data_sources": ["market_data", "financial_analysis", "risk_assessment"]
  }
}
```

---

### 2.2 Prompt 规范化标准

#### A. 动作动词规范

| 意图 | 推荐动词 | 示例 | 避免 |
|------|---------|------|------|
| 获取原始数据 | **获取/查询/读取** | "获取茅台的实时股价" | "看看"、"查一下" |
| 计算指标 | **计算/统计/分析** | "计算茅台的ROE" | "分析一下" |
| 生成报告 | **生成/创建/撰写** | "生成一份深度研报" | "全面分析" |
| 对比分析 | **对比/比较** | "对比茅台和五粮液的估值" | "看看...怎么样" |
| 筛选过滤 | **筛选出/找出/列出** | "筛选出PE低于20的股票" | "找几只" |

#### B. 参数明确化模板

```javascript
// 时间参数
"最近一个交易日"  // ✅ 明确相对时间
"2026年3月21日"  // ✅ 或绝对时间
// 避免: "今天"、"最近"

// 数量参数
"查询3只股票"     // ✅ 明确数量
"批量查询(不超过10只)" // ✅ 或范围
// 避免: "几只"、"一些"

// 阈值参数
"PE低于20"        // ✅ 明确阈值
"市值大于1000亿且PE低于30" // ✅ 复合条件明确
// 避免: "低估值"、"大盘股"

// 条件参数
"如果PE低于20则深度分析，否则简单分析" // ✅ 明确条件分支
// 避免: "针对性分析"、"根据情况"
```

#### C. 控制流显式标记

```javascript
// For-Each 循环
"批量查询以下股票的行情: 600519, 000858, 600809"
"并行获取这3只股票的财务数据"

// If-Else 条件
"判断茅台的PE值: 如果低于20则生成深度研报，否则只显示基本信息"
"根据风险等级给出建议: 高风险提醒，低风险推荐"

// While 循环
"循环查询股票，直到找到3只满足条件的"
"持续获取数据直到覆盖过去30天"
```

---

### 2.3 评估逻辑分层

#### 三层评估体系

```
┌─────────────────────────────────────────────────────────────────┐
│                      三层评估体系                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  L1: 功能性评估 (Functional)                             │  │
│  │  ─────────────────────────────────────────                │  │
│  │  • 是否获取了必需的数据字段？                              │  │
│  │  • 回答是否完整回答了用户问题？                            │  │
│  │  • 是否包含明显的幻觉或错误信息？                          │  │
│  │                                                           │  │
│  │  适用: 多Skill协作、控制流测试、复杂场景                    │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  L2: 等价性评估 (Equivalent)                             │  │
│  │  ─────────────────────────────────────────                │  │
│  │  • 实际调用的工具是否与期望工具功能等价？                   │  │
│  │  • generate_stock_report ≈ get_quote + get_daily_basic   │  │
│  │  • 数量是否符合预期？(如For-Each调用3次get_quote)          │  │
│  │                                                           │  │
│  │  适用: 工具选择测试、替代方案场景                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  L3: 精确性评估 (Exact)                                  │  │
│  │  ─────────────────────────────────────────                │  │
│  │  • Skill是否完全匹配？                                    │  │
│  │  • 工具名称是否完全一致？                                  │  │
│  │  • 参数是否正确？                                         │  │
│  │                                                           │  │
│  │  适用: 基础功能测试、单一Skill测试                         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 评估规则配置

```json
{
  "id": "DA-001",
  "evaluation_rule": {
    "level": "functional",
    "accept_alternative_tools": true,
    "required_outputs": ["mean", "std"],
    "source": "any"
  }
}
```

---

### 2.4 测试用例分类体系

#### 新分类体系（7大类）

| 类别 | 代码 | 说明 | 评估重点 |
|------|------|------|----------|
| **基础工具** | BT | 单一Skill单一工具 | 精确匹配 (L3) |
| **Skill边界** | SB | 测试Skill选择边界 | 等价性评估 (L2) |
| **多Skill协作** | MC | 顺序/并行多Skill | 数据完整性 (L1) |
| **控制流-循环** | CF-L | For/While循环 | 迭代次数+数据正确性 |
| **控制流-分支** | CF-B | If/Switch分支 | 条件判断正确性 |
| **复杂场景** | CS | 组合控制流 | 端到端功能 (L1) |
| **异常处理** | EH | 错误/边界情况 | 容错能力 |

#### 控制流测试专用标记

```json
{
  "id": "CF-L-001",
  "category": "control_flow_loop",
  "control_flow": {
    "type": "for_each",
    "items": ["600519.SH", "000858.SZ", "600809.SH"],
    "parallel": true,
    "expected_iterations": 3,
    "expected_tool_pattern": "get_quote(×3)"
  }
}
```

---

## 三、具体改进任务清单

### Phase 1: 修复已有用例（优先级：高）

#### Task 1.1: 填充空的 expected_skill
- **范围**: 32个用例
- **动作**: 根据 query 内容推断并填充
- **示例**:
  ```json
  // MULTI-001
  "expected_skill": "deep_research"
  
  // FOREACH-001  
  "expected_skill": "market_data"
  
  // COMPLEX-001
  "expected_skill": "sector_analysis"
  ```

#### Task 1.2: 重写模糊 Prompt
- **范围**: 18个高模糊度用例
- **重点词汇替换**:
  | 原词 | 替换为 |
  |------|--------|
  | "全面分析" | "生成深度研究报告" |
  | "看看" | "获取" |
  | "针对性的方法" | "根据行业类型选择不同分析工具" |
  | "选几只" | "筛选出3只" |
  | "刚上市" | "2024年1月后上市" |

#### Task 1.3: 修复控制流测试
- **修改评估逻辑**: 允许工具重复调用
- **修改期望工具格式**:
  ```json
  // 修改前
  "expected_tools": ["get_quote"]
  
  // 修改后
  "expected_tools": ["get_quote"],
  "tool_invocation_pattern": {
    "type": "repeated",
    "min_count": 3,
    "max_count": 3
  }
  ```

---

### Phase 2: 增强评估逻辑（优先级：高）

#### Task 2.1: 实现等价工具映射
```python
EQUIVALENT_TOOLS = {
    "generate_stock_report": [
        "get_quote", "get_daily_basic", 
        "calculate_financial_ratios", "assess_stock_risk"
    ],
    "generate_industry_report": [
        "get_industry_performance", "get_industry_leaders"
    ]
}
```

#### Task 2.2: 实现功能检查器
```python
def check_functional_completeness(response, required_fields):
    """检查回答是否包含必需的数据字段"""
    return all(field in response for field in required_fields)
```

#### Task 2.3: 修改评分算法
```python
def calculate_accuracy(result, evaluation_rule):
    if evaluation_rule["level"] == "functional":
        return score_by_data_completeness(result)
    elif evaluation_rule["level"] == "equivalent":
        return score_by_tool_equivalence(result)
    else:  # exact
        return score_by_exact_match(result)
```

---

### Phase 3: 新增测试用例（优先级：中）

#### Task 3.1: 添加 Skill 边界测试
```json
{
  "id": "SB-001",
  "query": "茅台的PE估值是多少？",
  "intent": {
    "primary_skill": "market_data",
    "confusing_skills": ["financial_analysis"],
    "reason": "PE是市场估值指标，需要股价数据"
  }
}
```

#### Task 3.2: 添加替代方案测试
```json
{
  "id": "SB-002", 
  "query": "生成一份茅台研报",
  "acceptable_solutions": [
    ["generate_stock_report"],
    ["get_quote", "get_daily_basic", "calculate_financial_ratios"]
  ],
  "evaluation": "functional"
}
```

#### Task 3.3: 添加复杂条件测试
```json
{
  "id": "CF-B-003",
  "query": "分析茅台: 如果PE<20且ROE>15%则推荐，如果PE>30或ROE<10%则提醒风险，否则保持观望",
  "control_flow": {
    "type": "nested_if",
    "conditions": ["pe < 20 and roe > 15", "pe > 30 or roe < 10"]
  }
}
```

---

### Phase 4: 测试框架升级（优先级：中）

#### Task 4.1: 添加 Query 变体支持
```json
{
  "id": "BT-001",
  "query_templates": [
    "茅台现在股价多少？",
    "600519当前价格",
    "贵州茅台最新行情"
  ],
  "intent_equivalence": true
}
```

#### Task 4.2: 添加动态评估
- 使用 LLM 作为评判员，评估回答质量
- 检查是否完整回答了用户问题

#### Task 4.3: 添加回归测试标记
```json
{
  "id": "BT-001",
  "regression_test": true,
  "flaky": false
}
```

---

## 四、实施路线图

```
Week 1: Phase 1 (紧急修复)
  ├─ Day 1-2: Task 1.1 (填充空skill)
  ├─ Day 3-4: Task 1.2 (重写模糊prompt) 
  └─ Day 5:   Task 1.3 (修复控制流评估)

Week 2: Phase 2 (评估升级)
  ├─ Day 1-2: Task 2.1 (等价工具映射)
  ├─ Day 3-4: Task 2.2 (功能检查器)
  └─ Day 5:   Task 2.3 (新评分算法)

Week 3: Phase 3-4 (增强)
  ├─ Day 1-2: 新增边界测试用例
  ├─ Day 3-4: 新增复杂场景用例
  └─ Day 5:   框架升级+回归测试

Week 4: 验证+文档
  ├─ 全量测试运行
  ├─ 修复残留问题
  └─ 输出测试用例编写规范文档
```

---

## 五、预期效果

| 指标 | 当前 | 目标 | 提升 |
|------|------|------|------|
| Skill准确率 | 34.7% | 85%+ | +50% |
| 误判率（工具选择） | 30.6% | <10% | -20% |
| 测试用例可用率 | 65% | 95%+ | +30% |
| 运行稳定性 | 95.9% | 98%+ | +2% |

---

## 六、附录：模糊 Prompt 案例分析

### 案例 1: "全面分析一下茅台这只股票" (MULTI-001)

**问题**:
- "全面" 太主观，LLM 选择了 `generate_stock_report`（综合研报工具）
- 但测试期望是 4 个独立工具调用
- **结果**：被判为 tools_correct: false，但实际上功能是对的

**建议修改**:
```json
{
  "query": "分别获取茅台的行情、估值、财务和风险数据",
  "expected_tools": ["get_quote", "get_daily_basic", "calculate_financial_ratios", "assess_stock_risk"]
}
// 或
{
  "query": "生成一份茅台的深度研究报告",
  "expected_tools": ["generate_stock_report"]
}
```

---

### 案例 2: "分析一下金融行业股票，用针对性的方法" (SWITCH-001)

**问题**:
- "针对性的方法" 是什么？没人知道
- LLM 调用了 3 个工具，但测试期望是 Switch 控制流

**建议修改**:
```json
{
  "query": "金融行业股票分析：如果是银行关注坏账率，如果是保险关注赔付率，如果是证券关注交易量",
  "expected_control_flow": "switch"
}
```

---

### 案例 3: "帮我找3只PE低于20的低估值股票" (WHILE-001)

**问题**:
- LLM 尝试用 `get_daily_basic` 一次性获取，而不是循环查找
- Tushare API 不支持按 PE 筛选，只能全量获取后过滤
- **结果**：工具调用失败，参数错误

**建议修改**:
```json
{
  "query": "循环查询股票，直到找到3只PE低于20的股票",
  "expected_control_flow": "while"
}
```

---

## 七、参考文档

- 原始测试报告: `benchmark_qwen-max_20260321_113148.json`
- 测试脚本: `run_benchmark.py`, `test_control_flow.py`
- 相关代码: `backend/app/service/mcp_chat_service.py`

---

*本文档为金融研投助手 Benchmark 改进的完整方案，建议按 Phase 分阶段实施。*
