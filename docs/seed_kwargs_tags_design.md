# Seed Kwargs 标签扩展技术方案

## 1. 目标

扩展 Seed 的 `kwargs` 字段，支持**自定义标签**，用于：
- 标记数据类别/主题
- 追踪数据来源和属性
- 支持多维度数据筛选和分析

## 2. 标签格式规范

### 2.1 标准标签字段

```json
{
  "content": "分析贵州茅台的投资价值",
  "kwargs": {
    "tags": {
      "category": "stock_analysis",      // 数据类别
      "industry": "liquor",              // 行业
      "stock_code": "600519.SH",         // 股票代码
      "difficulty": "medium",            // 难度: easy/medium/hard
      "data_source": "market_data",      // 数据来源技能
      "language": "zh"                   // 语言
    },
    "timeout": 60                        // 保留原有功能
  }
}
```

### 2.2 保留字段

| 字段 | 用途 | 类型 |
|------|------|------|
| `timeout` | 执行超时时间 | int |
| `tags` | 自定义标签字典 | dict |

### 2.3 标签规范

- `tags` 下的所有键值对都是**可选的**
- 支持任意字符串键值对
- 建议采用**扁平结构**（不要嵌套太深）

## 3. 数据流修改

### 3.1 数据模型扩展

```python
# synthesis/core/models.py

@dataclass
class Trajectory:
    trajectory_id: str
    nodes: List[TrajectoryNode]
    seed_data: str
    total_depth: int
    source_id: str = ""
    tags: Dict[str, Any] = field(default_factory=dict)  # 新增

@dataclass
class SynthesizedQA:
    question: str
    answer: str
    trajectory_id: str
    reasoning_steps: List[Dict[str, str]]
    source_id: str = ""
    qa_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: Dict[str, Any] = field(default_factory=dict)  # 新增
```

### 3.2 Pipeline 传递标签

```python
# synthesis/pipeline.py

trajectory = Trajectory(
    trajectory_id=traj_id,
    nodes=nodes,
    seed_data=seed_content,
    total_depth=leaf_node.depth,
    source_id=source_id,
    tags=seed_kwargs.get("tags", {})  # 传递标签
)

qa = synthesizer.synthesize_qa(
    trajectory, 
    qa_index,
    tags=trajectory.tags  # 传递标签到 QA
)
```

### 3.3 最终输出格式

```json
{
  "question": "贵州茅台当前股价是多少？",
  "answer": "1850.50元",
  "trajectory_id": "src_0001_xxx_traj_0",
  "reasoning_steps": [...],
  "source_id": "src_0001_xxx",
  "qa_id": "src_0001_xxx_traj_0_qa_0",
  "metadata": {...},
  "tags": {
    "category": "stock_analysis",
    "industry": "liquor",
    "stock_code": "600519.SH",
    "difficulty": "medium"
  }
}
```

## 4. 使用场景

### 4.1 数据筛选

```python
# 筛选特定行业的数据
qa_data = load_qa_data("synthesized_qa.jsonl")
liquor_data = [qa for qa in qa_data if qa.get("tags", {}).get("industry") == "liquor"]
```

### 4.2 数据分析

```python
# 统计各难度级别的数据量
from collections import Counter
difficulty_counts = Counter(qa.get("tags", {}).get("difficulty", "unknown") for qa in qa_data)
```

### 4.3 模型训练

```python
# 按标签分组训练
for category, group in group_by_tag(qa_data, "category"):
    train_model(group, tag=category)
```

## 5. 实现计划

### 5.1 修改文件列表

1. `synthesis/core/models.py` - 添加 tags 字段
2. `synthesis/core/selector.py` - 传递 tags
3. `synthesis/core/synthesizer.py` - 接收 tags 并写入 QA
4. `synthesis/pipeline.py` - 从 kwargs 提取 tags 并传递

### 5.2 向后兼容

- 旧数据没有 `tags` 字段时，默认为空字典 `{}`
- 新代码可以正常处理旧格式数据

## 6. 示例 Seeds

```jsonl
{"content": "分析贵州茅台(600519)的投资价值", "kwargs": {"tags": {"category": "stock_analysis", "industry": "liquor", "stock_code": "600519.SH", "difficulty": "medium"}, "timeout": 60}}
{"content": "查询新能源行业的龙头企业", "kwargs": {"tags": {"category": "sector_analysis", "industry": "new_energy", "difficulty": "easy"}}}
{"content": "计算贵州茅台的夏普比率和最大回撤", "kwargs": {"tags": {"category": "risk_analysis", "stock_code": "600519.SH", "difficulty": "hard"}}}
```

---

**文档版本**: v1.0  
**编写日期**: 2026-03-21  
**编写人**: 卤蛋 🐤
