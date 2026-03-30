# Seed 数据在 Agent Flow 中的使用方案

## 1. 概述

我们生成的 9,689 个高质量 Seed，可以在 Agent Flow 中用于：

1. **训练数据** - 用于 Fine-tuning 或 GRPO 训练
2. **测试用例** - 验证 Agent 的响应质量
3. **评估基准** - 评估模型性能
4. **Prompt 优化** - 分析高质量 Seed 优化 Prompt

---

## 2. 数据准备

### 2.1 筛选高质量数据

根据评分结果，筛选出高质量数据：

```bash
# excellent + high 等级 (97.8%)
python3 << 'EOF'
import json

# 读取评分数据
with open("data/seeds_10000_production/seeds_10000_scored.jsonl", "r") as f:
    seeds = [json.loads(line) for line in f]

# 筛选高质量数据
high_quality = [
    s for s in seeds 
    if s["scores"]["quality_level"] in ["excellent", "high"]
]

print(f"高质量数据: {len(high_quality)} / {len(seeds)}")

# 保存
with open("agent_flow_training_data.jsonl", "w") as f:
    for s in high_quality:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

print("✅ 已保存到 agent_flow_training_data.jsonl")
EOF
```

### 2.2 数据格式转换

转换为 Agent Flow 可用的格式：

```python
# convert_to_agentflow_format.py
import json

def convert_seed(seed):
    """将 Seed 转换为 Agent Flow 训练格式"""
    
    # 提取关键信息
    content = seed["content"]
    slots = seed["slots"]
    entities = seed["entities"]
    scores = seed["scores"]
    
    # Agent Flow 训练格式
    return {
        # 用户输入
        "input": content,
        
        # 预期的工具调用（根据 intent 推断）
        "expected_tools": infer_tools(slots["intent"]),
        
        # 标签信息
        "metadata": {
            "user_type": slots["user_type"],
            "intent": slots["intent"],
            "context": slots["context"],
            "style": slots["style"],
            "entities": entities,
            "quality_score": scores["overall"],
            "quality_level": scores["quality_level"],
        },
        
        # 用于训练的系统提示
        "system_prompt": generate_system_prompt(slots),
    }

def infer_tools(intent):
    """根据意图推断需要的工具"""
    tool_map = {
        "查价格": ["market_data.get_quote"],
        "问估值": ["financial_analysis.calculate_ratios"],
        "问买卖": ["deep_research.analyze", "risk_assessment.evaluate"],
        "比股票": ["financial_analysis.compare", "market_data.get_quote"],
        "问风险": ["risk_assessment.evaluate"],
        "深度分析": ["deep_research.generate_report"],
        "学知识": ["financial_analysis.explain_concept"],
    }
    return tool_map.get(intent, ["market_data.get_quote"])

def generate_system_prompt(slots):
    """根据槽位生成系统提示"""
    return f"""你是一个专业的金融投资助手。
用户类型: {slots['user_type']}
用户意图: {slots['intent']}
当前场景: {slots['context']}
请根据用户的问题，调用合适的工具提供帮助。"""

# 执行转换
with open("data/seeds_10000_production/seeds_10000_scored.jsonl", "r") as f:
    seeds = [json.loads(line) for line in f]

# 只转换高质量数据
high_quality = [s for s in seeds if s["scores"]["quality_level"] in ["excellent", "high"]]
converted = [convert_seed(s) for s in high_quality]

# 保存
with open("agent_flow_dataset.jsonl", "w") as f:
    for item in converted:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"✅ 转换完成: {len(converted)} 条数据")
```

---

## 3. 在 Agent Flow 中的使用场景

### 3.1 场景1: GRPO 训练数据

```python
# 加载训练数据
import json

def load_training_data(filepath):
    """加载训练数据"""
    data = []
    with open(filepath, "r") as f:
        for line in f:
            item = json.loads(line)
            data.append({
                "input": item["input"],
                "expected_tools": item["expected_tools"],
                "metadata": item["metadata"],
            })
    return data

# 使用数据
training_data = load_training_data("agent_flow_dataset.jsonl")
print(f"加载训练数据: {len(training_data)} 条")

# 划分训练集和验证集
train_size = int(len(training_data) * 0.9)
train_data = training_data[:train_size]
val_data = training_data[train_size:]

print(f"训练集: {len(train_data)} 条")
print(f"验证集: {len(val_data)} 条")
```

### 3.2 场景2: 测试用例

```python
# test_cases.py
import json
import random

def generate_test_cases(seed_file, num_cases=100):
    """生成测试用例"""
    with open(seed_file, "r") as f:
        seeds = [json.loads(line) for line in f]
    
    # 随机选择测试用例
    test_cases = random.sample(seeds, min(num_cases, len(seeds)))
    
    # 格式化为测试用例
    cases = []
    for seed in test_cases:
        cases.append({
            "name": f"test_{seed['slots']['intent']}_{seed['slots']['user_type']}",
            "input": seed["content"],
            "expected_intent": seed["slots"]["intent"],
            "expected_entities": seed["entities"],
            "quality_threshold": 8.0 if seed["scores"]["quality_level"] == "high" else 9.0,
        })
    
    return cases

# 生成测试用例
test_cases = generate_test_cases("data/seeds_10000_production/seeds_10000_scored.jsonl", 100)

# 保存测试用例
with open("agent_flow_test_cases.json", "w") as f:
    json.dump(test_cases, f, ensure_ascii=False, indent=2)

print(f"✅ 生成 {len(test_cases)} 个测试用例")
```

### 3.3 场景3: 评估基准 (Benchmark)

```python
# benchmark.py
import json
from collections import defaultdict

def create_benchmark(seed_file):
    """创建评估基准"""
    with open(seed_file, "r") as f:
        seeds = [json.loads(line) for line in f]
    
    # 按意图分类
    benchmark = defaultdict(list)
    for seed in seeds:
        intent = seed["slots"]["intent"]
        benchmark[intent].append({
            "input": seed["content"],
            "expected_tools": infer_tools(intent),
            "quality_score": seed["scores"]["overall"],
        })
    
    # 每个意图选择高质量样本
    final_benchmark = {}
    for intent, cases in benchmark.items():
        # 按质量分数排序，选择前10个
        cases.sort(key=lambda x: x["quality_score"], reverse=True)
        final_benchmark[intent] = cases[:10]
    
    return final_benchmark

# 创建评估基准
benchmark = create_benchmark("data/seeds_10000_production/seeds_10000_scored.jsonl")

# 保存
with open("agent_flow_benchmark.json", "w") as f:
    json.dump(benchmark, f, ensure_ascii=False, indent=2)

total_cases = sum(len(cases) for cases in benchmark.values())
print(f"✅ 创建评估基准: {len(benchmark)} 个意图, {total_cases} 个测试用例")
```

### 3.4 场景4: Prompt 优化分析

```python
# prompt_analysis.py
import json
from collections import Counter

def analyze_high_quality_seeds(seed_file):
    """分析高质量 Seed，提取 Prompt 优化建议"""
    with open(seed_file, "r") as f:
        seeds = [json.loads(line) for line in f]
    
    # 筛选 excellent 级别的 Seed
    excellent = [s for s in seeds if s["scores"]["quality_level"] == "excellent"]
    
    print(f"分析 {len(excellent)} 个 excellent 级别 Seed\n")
    
    # 1. 用户类型分布
    user_dist = Counter(s["slots"]["user_type"] for s in excellent)
    print("【高质量 Seed 用户类型分布】")
    for user, count in user_dist.most_common():
        print(f"  {user}: {count}")
    
    # 2. 意图分布
    intent_dist = Counter(s["slots"]["intent"] for s in excellent)
    print("\n【高质量 Seed 意图分布】")
    for intent, count in intent_dist.most_common():
        print(f"  {intent}: {count}")
    
    # 3. 高分维度分析
    avg_scores = {}
    for dim in ["naturalness", "relevance", "completeness", "compliance", "utility"]:
        scores = [s["scores"][dim] for s in excellent]
        avg_scores[dim] = sum(scores) / len(scores)
    
    print("\n【高分维度平均分】")
    for dim, score in sorted(avg_scores.items(), key=lambda x: x[1], reverse=True):
        print(f"  {dim}: {score:.2f}")
    
    # 4. 优秀案例展示
    print("\n【优秀案例 (各意图一个)】")
    shown_intents = set()
    for seed in excellent:
        intent = seed["slots"]["intent"]
        if intent not in shown_intents and len(shown_intents) < 5:
            shown_intents.add(intent)
            print(f"\n  [{intent}]")
            print(f"  内容: {seed['content'][:60]}...")
            print(f"  综合分: {seed['scores']['overall']}")
    
    return excellent

# 执行分析
excellent_seeds = analyze_high_quality_seeds("data/seeds_10000_production/seeds_10000_scored.jsonl")
```

---

## 4. 集成到 Agent Flow 项目

### 4.1 目录结构

当前项目已整理的数据和脚本目录结构如下：

```
AgentFlow/
├── data/
│   ├── seeds/                        # 生产及测试用种子
│   │   ├── seeds_100k_all.jsonl     # 主力生产种子 (10万条)
│   │   └── seeds_100k_v3_test.jsonl # 测试用种子
│   └── seeds_10000_production/       # 1万种子生产中间产物
│       ├── seeds_10000_all.jsonl
│       ├── seeds_10000_scored.jsonl
│       └── ...
├── scripts/
│   ├── pipeline/
│   │   ├── convert_to_grpo.py       # 转换为 GRPO 训练格式
│   │   └── run_our_synthesis.py     # 运行数据合成
│   ├── seeds/
│   │   ├── generate_seeds_100k_v3_batch.py  # 10万 Seed Batch 生成
│   │   ├── score_seeds_batch.py     # 批量质量评分
│   │   ├── prepare_seeds.py         # 种子预处理
│   │   └── prepare_excellent_seeds.py
│   └── utils/
│       ├── compare_architecture.py
│       ├── show_progressive_disclosure.py
│       └── skill_writing_guide.py
├── tests/
│   └── manual/
│       ├── test_fix.py
│       ├── test_full_pipeline.py
│       └── test_single_seed.py
└── configs/synthesis/
    └── grpo_100k_config.json        # 种子路径: data/seeds/seeds_100k_all.jsonl
```

### 4.2 数据配置文件

```yaml
# data_config.yaml
seed_data:
  source_file: "data/raw/seeds_10000_scored.jsonl"
  total_count: 9689
  
  quality_filters:
    min_overall_score: 8.0
    allowed_levels: ["excellent", "high"]
    
  splits:
    train: 0.9
    val: 0.1
    
  output_files:
    training: "data/processed/training_data.jsonl"
    test_cases: "data/processed/test_cases.json"
    benchmark: "data/processed/benchmark.json"
```

### 4.3 使用示例

```python
# 在 Agent Flow 训练脚本中使用
import yaml

# 加载配置
with open("configs/data_config.yaml") as f:
    config = yaml.safe_load(f)

# 加载训练数据
train_data = load_training_data(config["seed_data"]["output_files"]["training"])

# 用于 GRPO 训练
for epoch in range(num_epochs):
    for batch in train_data:
        input_text = batch["input"]
        expected_tools = batch["expected_tools"]
        
        # 训练逻辑
        response = agent.generate(input_text)
        reward = calculate_reward(response, expected_tools)
        
        # 更新模型
        update_policy(reward)
```

---

## 5. 下一步建议

### 5.1 立即执行

1. ✅ **数据筛选**: 提取 excellent + high (9,467个)
2. ✅ **格式转换**: 转换为 Agent Flow 训练格式
3. ✅ **生成测试集**: 创建 100-200 个测试用例

### 5.2 短期计划

1. **数据标注**: 为关键 Seed 标注预期输出（ golden response ）
2. **A/B 测试**: 使用 Seed 测试不同 Prompt 的效果
3. **持续迭代**: 根据测试结果，生成更多特定场景的 Seed

### 5.3 长期规划

1. **自动扩展**: 使用高分 Seed 作为示例，生成更多数据
2. **多轮对话**: 基于单轮 Seed，生成多轮对话数据
3. **跨语言**: 生成英文版 Seed，支持国际化

---

## 6. 总结

我们生成的 9,689 个高质量 Seed，经过评分筛选后：

- **9,467 个** (97.8%) 可直接用于训练
- **平均分 8.83 分**，质量优秀
- **覆盖 7 种意图、7 种用户类型**，场景全面

这些数据可以直接集成到 Agent Flow 的：
- ✅ GRPO 训练流程
- ✅ 自动化测试
- ✅ 模型评估基准
- ✅ Prompt 优化分析

**准备好集成了吗？需要我生成具体的转换脚本吗？**
