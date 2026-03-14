# 金融研投助手 GRPO 训练方案

> **目标**：训练模型在多轮对话中正确使用工具（function calling）的能力
>
> **训练方式**：GRPO (Group Relative Policy Optimization)
>
> **场景**：用户与金融研投助手的对话场景

---

## 一、现有工具体系分析

### 1.1 四个核心 Skill

#### 1. **market_data** - 市场行情数据
提供股票市场行情查询功能，基于 Tushare 数据源。

**工具列表（8个）**：
- `get_quote` - 获取实时行情（价格、涨跌幅、成交量）
- `search_stock` - 搜索股票（根据代码或名称）
- `get_history` - 历史K线数据（日线、周线、月线）
- `get_stock_basic_info` - 股票基础信息（行业、地区、上市日期）
- `get_top_list` - 龙虎榜数据（机构买卖）
- `get_money_flow` - 资金流向（主力、散户净流入）
- `get_limit_list` - 涨跌停统计
- `get_company_info` - 公司详细信息（简介、联系方式）

#### 2. **financial_analysis** - 财务分析
提供 A 股上市公司财务报表查询和分析功能。

**工具列表（3个）**：
- `get_financial_report` - 获取财报（利润表/资产负债表/现金流量表）
- `calculate_financial_ratios` - 计算财务指标（ROE、ROA、毛利率、净利率、资产负债率等）
- `compare_financial_data` - 对比财务数据（同比/环比变化）

#### 3. **risk_assessment** - 风险评估
提供投资组合风险分析功能，基于历史数据计算风险指标。

**工具列表（3个）**：
- `assess_portfolio_risk` - 评估投资组合风险（预期收益、波动率、夏普比率）
- `calculate_risk_metrics` - 计算单项资产风险指标（波动率、Beta、最大回撤、VaR、CVaR）
- `generate_risk_report` - 生成风险报告（风险等级、投资建议、风险提示）

#### 4. **deep_research** - 深度研究
基于多智能体协作的深度研究能力（Architect、Scout、Wizard、Critic、Writer）。

**工具列表（3个）**：
- `research_stream` - 执行深度研究（流式，实时反馈）
- `research_sync` - 执行深度研究（同步，批处理）
- `quick_research` - 快速研究（简化版）

### 1.2 工具统计

**总计**：17个工具，分布在4个Skill中

**复杂度分布**：
- 简单工具（单一查询）：10个
- 中等工具（需要计算/分析）：5个
- 复杂工具（多步骤/协作）：2个

---

## 二、GRPO 训练数据量规划

### 2.1 数据量级参考

根据 GRPO 训练经验和文献：

| 数据量级 | 效果预期 | 适用场景 |
|---------|---------|---------|
| 1,000-2,000条 | 能看到效果 | 快速验证、原型测试 |
| 3,000-5,000条 | 较好效果 | 正式训练、生产部署 |
| 8,000-10,000条 | 充分训练 | 高质量要求、复杂场景 |

### 2.2 推荐方案

**初期目标**：**3,000-5,000条**

**理由**：
1. 17个工具需要足够的覆盖度
2. 多轮对话需要更多样化的数据
3. GRPO需要组内采样（每个问题生成多个回答）
4. 平衡质量和成本

**数据质量分级**：
- **GOLD（30%）**：人工验证100%准确，推理完整
- **SILVER（50%）**：通过自动化验证，大概率准确
- **BRONZE（20%）**：LLM生成，未充分验证

---

## 三、数据构造策略

### 3.1 策略概览

采用**混合策略**：

```
模板生成 (60%) + 真实对话记录 (30%) + 对抗样本 (10%)
```

### 3.2 方案 A：模板生成 + 人工校验

**适用场景**：数值计算类、查询类任务

**流程**：
```
1. 设计场景模板（20-50个基础模板）
   ↓
2. 参数化生成变体（每个模板 × 50-100个变体）
   ↓
3. 自动化验证（规则检查、数值验证）
   ↓
4. 人工抽检（10-20%抽检率）
   ↓
5. 质量分级（GOLD/SILVER/BRONZE）
```

**示例场景模板**：

```python
# 场景模板1：单股分析（2-3步工具调用）
{
    "template_id": "single_stock_analysis",
    "user_query_template": "分析一下{stock_name}值不值得买",
    "variables": {
        "stock_name": ["茅台", "平安银行", "比亚迪", "宁德时代", ...],
        "stock_code": ["600519", "000001", "002594", "300750", ...]
    },
    "expected_trajectory": [
        {
            "step": 1,
            "thought": "先查询{stock_name}的当前股价和行情",
            "tool": "market_data.get_quote",
            "args": {"symbol": "{stock_code}"}
        },
        {
            "step": 2,
            "thought": "再看看财务指标，特别是ROE和毛利率",
            "tool": "financial_analysis.calculate_financial_ratios",
            "args": {"symbol": "{stock_code}"}
        },
        {
            "step": 3,
            "thought": "最后评估一下投资风险",
            "tool": "risk_assessment.calculate_risk_metrics",
            "args": {"symbol": "{stock_code}", "days": 252}
        }
    ],
    "answer_template": "根据数据分析，{stock_name}当前股价{price}元，{conclusion}",
    "difficulty": "MEDIUM",
    "task_type": "SINGLE_STOCK_ANALYSIS"
}
```

**优点**：
- ✅ 可控性强，质量有保证
- ✅ 可以覆盖所有工具组合
- ✅ 易于设计对抗样本（错误的工具调用）
- ✅ 易于批量生成

**缺点**：
- ❌ 需要人工设计场景模板
- ❌ 初期工作量较大
- ❌ 可能缺乏真实性

### 3.3 方案 B：真实对话记录

**适用场景**：复杂多轮、开放式问题

**流程**：
```
1. 修改 MCPChatService 添加轨迹记录
   ↓
2. 收集真实用户对话（或内部测试对话）
   ↓
3. 过滤低质量对话（失败的、错误的）
   ↓
4. 人工标注质量分数
   ↓
5. 转换为训练格式
```

**实现方案**：

```python
# 在 MCPChatService 中添加轨迹记录
class MCPChatServiceWithLogging(MCPChatService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trajectory = []

    async def call_mcp_tool(self, tool_name, arguments):
        result = await super().call_mcp_tool(tool_name, arguments)

        # 记录工具调用
        self.trajectory.append({
            "tool": tool_name,
            "arguments": arguments,
            "result": result,
            "timestamp": datetime.now().isoformat()
        })

        return result

    async def chat(self, user_question, *args, **kwargs):
        self.trajectory = []
        answer = await super().chat(user_question, *args, **kwargs)

        # 保存完整轨迹
        self.save_trajectory(user_question, answer)

        return answer

    def save_trajectory(self, question, answer):
        data = {
            "question": question,
            "trajectory": self.trajectory,
            "answer": answer,
            "timestamp": datetime.now().isoformat()
        }

        with open("trajectories.jsonl", "a") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
```

**优点**：
- ✅ 数据真实性高
- ✅ 能捕获真实用户意图
- ✅ 发现未预期的使用模式

**缺点**：
- ❌ 需要足够的用户量
- ❌ 质量参差不齐，需要筛选
- ❌ 可能工具覆盖不均匀

### 3.4 方案 C：对抗样本生成

**目的**：训练模型识别错误的工具调用

**类型**：
1. **错误的工具选择**：问股价却调用财报工具
2. **错误的参数**：股票代码格式错误
3. **缺少必要步骤**：直接评估风险但没先查数据
4. **冗余的工具调用**：重复调用相同工具
5. **逻辑错误**：先分析后查询（顺序错误）

**示例**：

```json
{
    "user": "茅台今天股价多少？",
    "negative_trajectories": [
        {
            "error_type": "wrong_tool",
            "trajectory": [
                {"tool": "financial_analysis.get_financial_report", "args": {"symbol": "600519"}}
            ],
            "reward": -0.5,
            "error_reason": "应该用 market_data.get_quote 查询实时股价，而不是查财报"
        },
        {
            "error_type": "wrong_parameter",
            "trajectory": [
                {"tool": "market_data.get_quote", "args": {"symbol": "茅台"}}
            ],
            "reward": -0.3,
            "error_reason": "股票代码应该是 '600519'，而不是中文名称"
        }
    ]
}
```

---

## 四、数据分类体系

### 4.1 按任务类型分类

| 任务类型 | 工具调用数 | 推理难度 | 数据量占比 | 示例问题 |
|---------|----------|---------|-----------|----------|
| **简单查询** | 1-2个 | 低 | 30% | "茅台今天股价多少？" |
| **中等分析** | 2-4个 | 中 | 50% | "分析茅台的财务健康度" |
| **复杂研究** | 4+个 | 高 | 20% | "对比茅台和五粮液，给投资建议" |

### 4.2 按场景类型分类

| 场景类型 | 说明 | 涉及工具 | 占比 |
|---------|------|---------|------|
| **行情查询** | 查股价、查K线、查龙虎榜 | market_data.* | 20% |
| **财务分析** | 查财报、算指标、对比数据 | financial_analysis.* | 25% |
| **风险评估** | 评估单股/组合风险 | risk_assessment.* | 15% |
| **综合分析** | 行情+财务+风险组合 | 跨skill | 30% |
| **深度研究** | 使用deep_research | deep_research.* | 10% |

### 4.3 按工具组合模式分类

| 模式 | 说明 | 示例 |
|------|------|------|
| **单工具** | 只调用1个工具 | "查茅台股价" |
| **顺序调用** | 依次调用2-4个工具 | "查股价→查财报→评估风险" |
| **并行查询** | 同时查询多个标的 | "同时查茅台和五粮液的财务数据" |
| **条件分支** | 根据结果决定下一步 | "如果ROE>15%，则进一步分析" |
| **迭代深化** | 逐步深入分析 | deep_research流程 |

---

## 五、奖励函数设计

### 5.1 复合奖励函数

```python
def compute_financial_reward(response, ground_truth):
    """
    金融场景复合奖励函数
    """
    rewards = {}

    # 1. 工具调用正确性（40%）
    rewards["tool_correctness"] = check_tool_sequence(response, ground_truth)
    # - 工具选择是否正确
    # - 工具调用顺序是否合理
    # - 是否有冗余调用

    # 2. 工具参数正确性（30%）
    rewards["parameter_correctness"] = check_tool_parameters(response, ground_truth)
    # - 股票代码格式是否正确
    # - 日期格式是否正确
    # - 参数值是否在合理范围内

    # 3. 答案准确性（20%）
    rewards["answer_accuracy"] = compare_with_ground_truth(response, ground_truth)
    # - 数值结果是否准确（可验证的计算）
    # - 结论是否与数据一致
    # - 是否有幻觉（虚构数据）

    # 4. 推理完整性（10%）
    rewards["reasoning_completeness"] = check_reasoning_steps(response)
    # - 是否展示了推理过程
    # - 逻辑链条是否完整
    # - 是否有明确的结论

    # 加权求和
    total_reward = (
        0.40 * rewards["tool_correctness"] +
        0.30 * rewards["parameter_correctness"] +
        0.20 * rewards["answer_accuracy"] +
        0.10 * rewards["reasoning_completeness"]
    )

    return total_reward
```

### 5.2 任务类型特异性奖励

| 任务类型 | 核心评估维度 | 权重调整 |
|---------|-------------|---------|
| 简单查询 | 工具选择 + 参数正确性 | tool: 50%, param: 40% |
| 中等分析 | 工具序列 + 答案准确性 | tool: 40%, answer: 30% |
| 复杂研究 | 推理完整性 + 答案质量 | reasoning: 30%, answer: 40% |

### 5.3 可验证奖励示例

**数值计算类（可自动验证）**：

```python
# 示例：ROE计算
ground_truth = {
    "net_profit": 100,  # 净利润
    "equity": 500,      # 净资产
    "expected_roe": 0.20  # 期望ROE = 100/500
}

# 检查模型输出
if abs(response["roe"] - 0.20) < 0.001:
    reward = 1.0  # 计算正确
else:
    reward = 0.0  # 计算错误
```

**逻辑推理类（需人工验证）**：

```python
# 示例：投资建议
# 需要人工评分（或使用奖励模型）
criteria = {
    "data_support": 0.4,      # 建议是否有数据支持
    "logic_coherence": 0.3,   # 逻辑是否自洽
    "risk_awareness": 0.3     # 是否提及风险
}
```

---

## 六、训练数据格式

### 6.1 标准格式（适配 GRPO）

```json
{
  "id": "sample_001",
  "task_type": "SINGLE_STOCK_ANALYSIS",
  "difficulty": "MEDIUM",
  "quality_tier": "GOLD",

  "messages": [
    {
      "role": "user",
      "content": "分析一下茅台值不值得买"
    },
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_1",
          "type": "function",
          "function": {
            "name": "market_data.get_quote",
            "arguments": "{\"symbol\": \"600519\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_1",
      "content": "{\"nowPri\": \"1850.50\", \"increPer\": \"1.39\", ...}"
    },
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_2",
          "type": "function",
          "function": {
            "name": "financial_analysis.calculate_financial_ratios",
            "arguments": "{\"symbol\": \"600519\"}"
          }
        }
      ]
    },
    {
      "role": "tool",
      "tool_call_id": "call_2",
      "content": "{\"roe\": \"20.5%\", \"gross_profit_margin\": \"91.3%\", ...}"
    },
    {
      "role": "assistant",
      "content": "根据数据分析，贵州茅台当前股价1850.50元...",
      "tool_calls": null
    }
  ],

  "metadata": {
    "tools_used": ["market_data.get_quote", "financial_analysis.calculate_financial_ratios"],
    "tool_count": 2,
    "verifiable": true,
    "expected_answer": {
      "key_points": ["股价", "ROE", "毛利率", "投资建议"],
      "numerical_facts": {"price": 1850.50, "roe": 0.205}
    }
  },

  "reward_components": {
    "tool_correctness": 1.0,
    "parameter_correctness": 1.0,
    "answer_accuracy": 0.95,
    "reasoning_completeness": 0.9
  }
}
```

### 6.2 简化格式（便于生成）

```json
{
  "question": "茅台今天股价多少？",
  "trajectory": [
    {"tool": "market_data.get_quote", "args": {"symbol": "600519"}}
  ],
  "answer": "茅台当前股价1850.50元，上涨1.39%",
  "difficulty": "EASY",
  "quality": "GOLD"
}
```

---

## 七、实施路线图

### Phase 1: 小规模验证（Week 1-2）

**目标**：验证方案可行性，生成 500 条数据

**任务**：
- [ ] 设计 10-20 个场景模板（覆盖简单/中等难度）
- [ ] 实现模板生成脚本
- [ ] 人工验证 100 条数据质量
- [ ] 实现奖励函数（基础版）
- [ ] 小规模 GRPO 训练测试

**产出**：
- `data/seed/templates.yaml` - 场景模板库
- `data/seed/samples_500.jsonl` - 种子数据集
- `scripts/generate_from_template.py` - 生成脚本
- `scripts/reward_function.py` - 奖励函数

### Phase 2: 规模化生成（Week 3-4）

**目标**：扩展到 3,000 条数据

**任务**：
- [ ] 扩展场景模板到 50+ 个
- [ ] 引入 LLM 辅助生成（SILVER级数据）
- [ ] 实现真实对话记录系统
- [ ] 批量生成数据
- [ ] 自动化质量验证
- [ ] 人工抽检（10%）

**产出**：
- `data/train/train_3000.jsonl` - 训练集
- `data/train/val_300.jsonl` - 验证集
- `data/train/test_300.jsonl` - 测试集
- `data/train/dataset_report.md` - 数据报告

### Phase 3: GRPO 训练（Week 5-6）

**目标**：完成 GRPO 训练

**任务**：
- [ ] 配置 GRPO 训练参数
- [ ] 实现组采样逻辑
- [ ] 训练基线模型（SFT）
- [ ] GRPO 强化学习训练
- [ ] 模型评估

**产出**：
- 训练好的模型 checkpoint
- 训练日志和指标
- 评估报告

### Phase 4: 迭代优化（Week 7-8）

**目标**：根据反馈优化

**任务**：
- [ ] 收集 bad cases
- [ ] 针对性补充数据
- [ ] 调整奖励函数
- [ ] 重新训练
- [ ] A/B 测试

---

## 八、关键问题和风险

### 8.1 数据质量风险

**问题**：模板生成的数据可能缺乏真实性

**应对**：
- 混合真实对话数据（30%）
- 人工抽检机制（10-20%）
- 持续收集用户反馈

### 8.2 工具覆盖度风险

**问题**：17个工具覆盖不均匀

**应对**：
- 制定工具覆盖目标（每个工具至少50个样本）
- 重点补充低频工具的数据
- 设计组合场景强制使用多个工具

### 8.3 奖励函数设计风险

**问题**：奖励函数可能存在漏洞（reward hacking）

**应对**：
- 多维度奖励，避免单一指标
- 引入负样本惩罚
- 人工审核高奖励样本

### 8.4 训练成本风险

**问题**：GRPO 训练成本较高（需要组采样）

**应对**：
- 先用小模型验证（如 Qwen2.5-7B）
- 使用 LoRA 降低训练成本
- 云端训练资源规划

---

## 九、成功指标

### 9.1 数据质量指标

| 指标 | 目标值 |
|------|-------|
| 总数据量 | ≥ 3,000 条 |
| GOLD 级数据占比 | ≥ 30% |
| 工具覆盖率 | 100%（所有17个工具） |
| 每工具平均样本数 | ≥ 50 条 |
| 人工验证通过率 | ≥ 90% |

### 9.2 模型能力指标

| 指标 | 基线（训练前） | 目标（训练后） |
|------|-------------|-------------|
| 工具选择准确率 | ~60% | ≥ 85% |
| 参数格式正确率 | ~70% | ≥ 90% |
| 多步推理完整率 | ~40% | ≥ 70% |
| 幻觉率（虚构数据） | ~15% | ≤ 5% |
| 用户满意度 | - | ≥ 4.0/5.0 |

### 9.3 业务指标

| 指标 | 目标 |
|------|------|
| 对话完成率 | ≥ 80% |
| 平均对话轮次 | 3-5轮 |
| 工具调用成功率 | ≥ 90% |
| 响应时间 | ≤ 3秒 |

---

## 十、附录

### 10.1 场景模板示例库

见 `templates/` 目录：
- `templates/simple_query.yaml` - 简单查询类模板
- `templates/financial_analysis.yaml` - 财务分析类模板
- `templates/risk_assessment.yaml` - 风险评估类模板
- `templates/comparative_analysis.yaml` - 对比分析类模板

### 10.2 工具组合推荐

常见工具调用链：
```
1. 单股分析：get_quote → calculate_financial_ratios → calculate_risk_metrics
2. 财报深挖：get_financial_report → calculate_financial_ratios → compare_financial_data
3. 组合优化：(多次 get_quote) → assess_portfolio_risk → generate_risk_report
4. 深度研究：quick_research 或 research_sync
```

### 10.3 参考资源

- **GRPO 论文**：DeepSeekMath (https://arxiv.org/abs/2402.03300)
- **Function Calling**：OpenAI Function Calling Guide
- **Qwen 训练**：Qwen2.5 Technical Report

---

**文档版本**：v1.0
**创建时间**：2026-03-08
**作者**：AI Training Team
**状态**：待评审
