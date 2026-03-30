# GRPO 训练数据标签体系设计文档

**版本**: v1.0  
**日期**: 2026-03-23  
**作者**: 卤蛋 🐤  
**状态**: 草案  

---

## 1. 背景与目标

### 1.1 问题背景

AgentFlow 项目需要为金融研投助手训练 GRPO（Group Relative Policy Optimization）模型。与简单的数学问答场景不同，我们的场景具有以下特点：

- **多轮对话**：需要多轮工具调用才能完成任务
- **答案不唯一**：同一问题可以有多种解决路径
- **验证困难**：不像数学题有确定答案
- **过程更重要**：选错工具、冗余调用都需要惩罚

### 1.2 设计目标

1. **自动化评估**：单人维护，无需人工标注
2. **双轨制评估**：可验证任务用规则，开放式任务用 LLM 评判
3. **防止过度调用**：通过标签约束工具使用次数
4. **覆盖所有工具**：确保 43 个工具都能被训练到

### 1.3 核心设计原则

借鉴 Kimi K2 技术报告的 **"可验证奖励 + 自我批评"** 双轨制：

| 任务类型 | 评估方式 | 适用场景 |
|---------|---------|---------|
| **可验证奖励 (RLVR)** | 规则/代码自动验证 | 查询股价、财务指标等确定性任务 |
| **自我批评奖励** | 模型自评 + 成对比较 | 投资分析、行业对比等开放式任务 |

---

## 2. 标签体系设计

### 2.1 基础标签（所有任务必需）

```json
{
  "content": "分析贵州茅台(600519.SH)的投资价值",
  "kwargs": {
    "tags": {
      "category": "stock_analysis",        // 数据类别
      "difficulty": "hard",                 // easy/medium/hard
      "expected_turns": 3,                  // 期望解决轮次
      
      // 解决路径约束
      "valid_skills": ["market_data", "financial_analysis"],
      "min_tools": 3,
      "max_tools": 6,
      
      // 评估配置
      "verifiable": true,                   // 是否可规则验证
      "reward_weights": {                   // 奖励权重
        "accuracy": 0.6,
        "efficiency": 0.3,
        "format": 0.1
      }
    },
    "timeout": 120
  }
}
```

### 2.2 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `category` | string | ✅ | 任务类别：stock_basic/stock_analysis/sector_analysis/financial_deep等 |
| `difficulty` | string | ✅ | 难度：easy(单工具)/medium(单技能多工具)/hard(多技能协作) |
| `expected_turns` | int | ✅ | 期望解决轮次，用于效率评估 |
| `valid_skills` | array | ✅ | 有效技能列表，限制模型选择范围 |
| `min_tools` | int | ✅ | 最少工具调用数，防止敷衍回答 |
| `max_tools` | int | ✅ | 最多工具调用数，防止过度调用 |
| `verifiable` | bool | ✅ | 是否可规则验证 |
| `reward_weights` | object | ❌ | 奖励权重，不填使用默认值 |

---

## 3. 任务分类与标签模板

### 3.1 任务分类总览

| 任务类别 | 占比 | 验证方式 | 示例 |
|---------|------|---------|------|
| **可验证查询** | 40% | API对比 | 查股价、查PE、查ROE |
| **可验证计算** | 20% | 规则计算 | 计算涨跌幅、对比估值 |
| **半开放式** | 25% | 规则+LLM混合 | 财务健康度评估 |
| **全开放式** | 15% | LLM评判 | 投资建议、行业分析 |

### 3.2 类别 A：可验证查询（Verifiable Query）

**定义**：有确定答案，可通过 API 或缓存验证

**标签模板**：

```json
{
  "content": "贵州茅台当前股价是多少？",
  "kwargs": {
    "tags": {
      "category": "stock_basic",
      "difficulty": "easy",
      "expected_turns": 1,
      "valid_skills": ["market_data"],
      "min_tools": 1,
      "max_tools": 2,
      
      // 可验证任务特有标签
      "verifiable": true,
      "verification_method": "api",
      "ground_truth_source": "tushare",
      "cache_key": "600519.SH_quote",
      
      // 可验证字段
      "verifiable_fields": [
        {
          "field": "current_price",
          "path": "data.nowPri",
          "tolerance": 0.01,
          "weight": 1.0
        }
      ],
      
      "reward_weights": {
        "accuracy": 0.7,
        "efficiency": 0.2,
        "format": 0.1
      }
    },
    "timeout": 30
  }
}
```

**verifiable_fields 说明**：

| 字段 | 说明 |
|------|------|
| `field` | 字段标识名 |
| `path` | 在 API 返回中的路径 |
| `tolerance` | 容差范围（股价0.01，PE/PB 0.1，ROE 0.5） |
| `weight` | 该字段在准确性奖励中的权重 |

### 3.3 类别 B：可验证计算（Verifiable Computation）

**定义**：需要计算，但结果可验证

**标签模板**：

```json
{
  "content": "计算贵州茅台的市盈率分位",
  "kwargs": {
    "tags": {
      "category": "stock_analysis",
      "difficulty": "medium",
      "expected_turns": 2,
      "valid_skills": ["market_data", "data_analysis"],
      "min_tools": 2,
      "max_tools": 4,
      
      "verifiable": true,
      "verification_method": "compute",
      "computation_rule": "percentile(current_pe, historical_pe_list)",
      
      "verifiable_fields": [
        {
          "field": "pe_percentile",
          "computation": "percentile",
          "tolerance": 5.0,
          "weight": 1.0
        }
      ],
      
      "reward_weights": {
        "accuracy": 0.5,
        "efficiency": 0.3,
        "reasoning": 0.2
      }
    },
    "timeout": 60
  }
}
```

### 3.4 类别 C：半开放式（Semi-Open）

**定义**：部分可验证，部分需要 LLM 评判

**标签模板**：

```json
{
  "content": "评估贵州茅台的财务健康度",
  "kwargs": {
    "tags": {
      "category": "financial_deep",
      "difficulty": "hard",
      "expected_turns": 3,
      "valid_skills": ["financial_analysis", "market_data"],
      "min_tools": 3,
      "max_tools": 5,
      
      "verifiable": true,
      "verification_method": "hybrid",
      
      // 可验证部分
      "verifiable_fields": [
        {"field": "roe", "tolerance": 0.5, "weight": 0.3},
        {"field": "debt_ratio", "tolerance": 2.0, "weight": 0.3}
      ],
      
      // 需 LLM 评判部分
      "evaluation_criteria": [
        "是否分析盈利能力(ROE/毛利率)",
        "是否分析偿债能力(负债率/流动比率)",
        "是否分析运营效率(周转率)",
        "结论是否综合多维度"
      ],
      
      "reward_weights": {
        "accuracy": 0.4,
        "quality": 0.3,
        "efficiency": 0.2,
        "format": 0.1
      }
    },
    "timeout": 90
  }
}
```

### 3.5 类别 D：全开放式（Open-Ended）

**定义**：无确定答案，完全依赖 LLM 评判

**标签模板**：

```json
{
  "content": "贵州茅台值得投资吗？给出你的分析",
  "kwargs": {
    "tags": {
      "category": "comprehensive",
      "difficulty": "hard",
      "expected_turns": 4,
      "valid_skills": ["market_data", "financial_analysis", "sector_analysis", "risk_assessment"],
      "min_tools": 4,
      "max_tools": 7,
      
      "verifiable": false,
      "verification_method": "llm_judge",
      
      // LLM 评判标准
      "evaluation_criteria": [
        {
          "dimension": "信息完整性",
          "description": "是否覆盖估值、财务、行业、风险等维度",
          "weight": 0.3
        },
        {
          "dimension": "数据支撑度",
          "description": "观点是否有具体数据支持",
          "weight": 0.3
        },
        {
          "dimension": "逻辑连贯性",
          "description": "推理过程是否合理",
          "weight": 0.2
        },
        {
          "dimension": "实用性",
          "description": "结论是否有投资价值",
          "weight": 0.2
        }
      ],
      
      // 自我批评配置
      "self_critique": {
        "enabled": true,
        "comparison_mode": "pairwise",
        "judge_prompt": "请从以下维度评估回答质量..."
      },
      
      "reward_weights": {
        "quality": 0.5,
        "efficiency": 0.3,
        "format": 0.2
      }
    },
    "timeout": 120
  }
}
```

---

## 4. 自动化评估实现

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Reward Calculator                         │
├─────────────────────────────────────────────────────────────┤
│  Input: Trajectory + Seed Tags                               │
│                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │  Rule-Based     │  │  LLM Judge      │  │  Hybrid      │ │
│  │  (可验证任务)    │  │  (开放式任务)    │  │  (混合任务)   │ │
│  └────────┬────────┘  └────────┬────────┘  └──────┬───────┘ │
│           │                    │                   │        │
│           └────────────────────┼───────────────────┘        │
│                                ▼                            │
│                         ┌─────────────┐                     │
│                         │  Total Reward│                     │
│                         └─────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 规则评估实现（RuleBasedReward）

```python
# synthesis/reward/rule_reward.py

from typing import Dict, List, Any
from dataclasses import dataclass
import json

@dataclass
class Trajectory:
    """模型生成的轨迹"""
    turns: List[Dict]  # 每轮的工具调用
    final_answer: str
    tools_used: List[str]
    total_tokens: int

class RuleBasedReward:
    """基于规则的奖励计算（用于可验证任务）"""
    
    def __init__(self, tushare_client=None):
        self.tushare = tushare_client
        self._ground_truth_cache = {}
    
    def calculate(self, trajectory: Trajectory, seed_tags: Dict) -> float:
        """
        计算规则奖励
        
        Args:
            trajectory: 模型生成的轨迹
            seed_tags: 种子标签
            
        Returns:
            总奖励 (0-1)
        """
        weights = seed_tags.get("reward_weights", {
            "accuracy": 0.6,
            "efficiency": 0.3,
            "format": 0.1
        })
        
        reward = 0.0
        
        # 1. 准确性奖励
        if seed_tags.get("verifiable"):
            accuracy_reward = self._calculate_accuracy(trajectory, seed_tags)
            reward += weights.get("accuracy", 0.6) * accuracy_reward
        
        # 2. 效率奖励（防止过度调用）
        efficiency_reward = self._calculate_efficiency(trajectory, seed_tags)
        reward += weights.get("efficiency", 0.3) * efficiency_reward
        
        # 3. 格式奖励
        format_reward = self._calculate_format(trajectory)
        reward += weights.get("format", 0.1) * format_reward
        
        return reward
    
    def _calculate_accuracy(self, trajectory: Trajectory, seed_tags: Dict) -> float:
        """计算准确性奖励"""
        verifiable_fields = seed_tags.get("verifiable_fields", [])
        if not verifiable_fields:
            return 1.0
        
        total_weight = sum(f.get("weight", 1.0) for f in verifiable_fields)
        accuracy_score = 0.0
        
        for field_config in verifiable_fields:
            field_name = field_config["field"]
            weight = field_config.get("weight", 1.0)
            tolerance = field_config.get("tolerance", 0.01)
            
            # 从轨迹中提取预测值
            predicted = self._extract_field_value(trajectory, field_name)
            
            # 获取 ground truth
            ground_truth = self._get_ground_truth(seed_tags, field_name)
            
            # 对比
            if predicted is not None and ground_truth is not None:
                if abs(predicted - ground_truth) <= tolerance:
                    accuracy_score += weight / total_weight
        
        return accuracy_score
    
    def _calculate_efficiency(self, trajectory: Trajectory, seed_tags: Dict) -> float:
        """
        计算效率奖励
        
        逻辑：
        - 工具数在 [min, max] 范围内：满分
        - 工具数 < min：线性扣分
        - 工具数 > max：每多一个扣 0.05
        """
        tool_count = len(trajectory.tools_used)
        min_tools = seed_tags.get("min_tools", 1)
        max_tools = seed_tags.get("max_tools", 10)
        expected_turns = seed_tags.get("expected_turns", 3)
        actual_turns = len(trajectory.turns)
        
        # 工具数量评分
        if min_tools <= tool_count <= max_tools:
            tool_score = 1.0
        elif tool_count < min_tools:
            tool_score = 0.5 + 0.5 * (tool_count / min_tools)
        else:
            tool_score = max(0, 1.0 - (tool_count - max_tools) * 0.05)
        
        # 轮次评分
        if actual_turns <= expected_turns:
            turn_score = 1.0
        else:
            turn_score = max(0.5, 1.0 - (actual_turns - expected_turns) * 0.1)
        
        return (tool_score + turn_score) / 2
    
    def _calculate_format(self, trajectory: Trajectory) -> float:
        """计算格式奖励"""
        score = 0.0
        answer = trajectory.final_answer
        
        # 检查是否有结构化的推理过程
        if "<reasoning>" in answer or "分析" in answer:
            score += 0.5
        
        # 检查是否有明确结论
        if "<answer>" in answer or "结论" in answer or "总结" in answer:
            score += 0.5
        
        return score
    
    def _get_ground_truth(self, seed_tags: Dict, field_name: str) -> Any:
        """获取 ground truth（带缓存）"""
        cache_key = seed_tags.get("cache_key", f"{seed_tags.get('stock_code')}_{field_name}")
        
        if cache_key in self._ground_truth_cache:
            return self._ground_truth_cache[cache_key].get(field_name)
        
        # 从 API 获取
        if seed_tags.get("verification_method") == "api" and self.tushare:
            # 调用 Tushare API
            stock_code = seed_tags.get("stock_code")
            result = self.tushare.get_quote(stock_code)
            if result.get("success"):
                self._ground_truth_cache[cache_key] = result["data"]
                return result["data"].get(field_name)
        
        return None
    
    def _extract_field_value(self, trajectory: Trajectory, field_name: str) -> Any:
        """从轨迹中提取字段值（简化版）"""
        # 从最终回答中提取数值
        # 实际实现需要更复杂的解析逻辑
        answer = trajectory.final_answer
        # TODO: 实现字段提取逻辑
        return None
```

### 4.3 LLM 评判实现（LLMJudgeReward）

```python
# synthesis/reward/llm_judge_reward.py

import json
from typing import Dict, List
from openai import AsyncOpenAI

class LLMJudgeReward:
    """大模型评判奖励（用于开放式任务）"""
    
    def __init__(self, model: str = "kimi-coding/k2p5", api_key: str = None):
        self.model = model
        self.client = AsyncOpenAI(api_key=api_key)
    
    async def calculate(self, trajectory: Trajectory, seed_tags: Dict) -> float:
        """
        计算 LLM 评判奖励
        
        Args:
            trajectory: 模型生成的轨迹
            seed_tags: 种子标签
            
        Returns:
            总奖励 (0-1)
        """
        criteria = seed_tags.get("evaluation_criteria", [])
        if not criteria:
            return 1.0
        
        # 构建评判 prompt
        prompt = self._build_judge_prompt(trajectory, seed_tags)
        
        # 调用评判模型
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是一个严格的评判专家，请客观评估回答质量。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        # 解析评判结果
        result = json.loads(response.choices[0].message.content)
        
        # 计算加权分数
        total_score = 0.0
        total_weight = 0.0
        
        for criterion in criteria:
            dim_name = criterion["dimension"] if isinstance(criterion, dict) else criterion
            weight = criterion.get("weight", 1.0 / len(criteria)) if isinstance(criterion, dict) else 1.0 / len(criteria)
            
            score = result.get("scores", {}).get(dim_name, 5)  # 默认5分（满分10分）
            total_score += (score / 10.0) * weight
            total_weight += weight
        
        return total_score / total_weight if total_weight > 0 else 0.5
    
    def _build_judge_prompt(self, trajectory: Trajectory, seed_tags: Dict) -> str:
        """构建评判 prompt"""
        criteria = seed_tags.get("evaluation_criteria", [])
        criteria_text = "\n".join([
            f"{i+1}. {c['dimension'] if isinstance(c, dict) else c}"
            for i, c in enumerate(criteria)
        ])
        
        return f"""请评估以下金融分析回答的质量。

【用户问题】
{seed_tags.get('content', '')}

【模型回答】
{trajectory.final_answer}

【评估维度】
{criteria_text}

请对每个维度给出 0-10 的评分，并返回 JSON 格式：
{{
  "scores": {{
    "维度1": 8,
    "维度2": 7,
    ...
  }},
  "reasoning": "简要说明评分理由"
}}
"""
    
    async def pairwise_compare(
        self, 
        trajectory_a: Trajectory, 
        trajectory_b: Trajectory, 
        seed_tags: Dict
    ) -> int:
        """
        成对比较两个轨迹
        
        Returns:
            1: A 更好
            0: 平局
            -1: B 更好
        """
        prompt = f"""请比较以下两个回答的质量。

【用户问题】
{seed_tags.get('content', '')}

【回答 A】
{trajectory_a.final_answer}

【回答 B】
{trajectory_b.final_answer}

【评估维度】
{json.dumps(seed_tags.get('evaluation_criteria', []), ensure_ascii=False)}

请判断哪个回答更好，返回 JSON：
{{
  "winner": "A" | "B" | "tie",
  "reasoning": "简要说明理由"
}}
"""
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是一个严格的评判专家。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        winner = result.get("winner", "tie")
        
        if winner == "A":
            return 1
        elif winner == "B":
            return -1
        else:
            return 0
```

### 4.4 混合评估实现（HybridReward）

```python
# synthesis/reward/hybrid_reward.py

from typing import Dict
import asyncio

class HybridReward:
    """
    混合评估：可验证部分用规则，质量部分用 LLM
    
    适用于半开放式任务
    """
    
    def __init__(self, tushare_client=None, llm_api_key=None):
        self.rule_reward = RuleBasedReward(tushare_client)
        self.llm_reward = LLMJudgeReward(api_key=llm_api_key)
    
    async def calculate(self, trajectory: Trajectory, seed_tags: Dict) -> float:
        """
        计算混合奖励
        
        权重分配：
        - 可验证部分：40-60%
        - 质量评估：40-60%
        """
        weights = seed_tags.get("reward_weights", {
            "accuracy": 0.4,
            "quality": 0.3,
            "efficiency": 0.2,
            "format": 0.1
        })
        
        reward = 0.0
        
        # 1. 准确性奖励（规则）
        if seed_tags.get("verifiable"):
            accuracy_reward = self.rule_reward._calculate_accuracy(trajectory, seed_tags)
            reward += weights.get("accuracy", 0.4) * accuracy_reward
        
        # 2. 质量奖励（LLM）
        if "evaluation_criteria" in seed_tags:
            quality_reward = await self.llm_reward.calculate(trajectory, seed_tags)
            reward += weights.get("quality", 0.3) * quality_reward
        
        # 3. 效率奖励（规则）
        efficiency_reward = self.rule_reward._calculate_efficiency(trajectory, seed_tags)
        reward += weights.get("efficiency", 0.2) * efficiency_reward
        
        # 4. 格式奖励（规则）
        format_reward = self.rule_reward._calculate_format(trajectory)
        reward += weights.get("format", 0.1) * format_reward
        
        return reward
```

### 4.5 奖励计算入口

```python
# synthesis/reward/__init__.py

from typing import Dict
from .rule_reward import RuleBasedReward
from .llm_judge_reward import LLMJudgeReward
from .hybrid_reward import HybridReward

class RewardCalculator:
    """奖励计算统一入口"""
    
    def __init__(self, tushare_client=None, llm_api_key=None):
        self.rule_reward = RuleBasedReward(tushare_client)
        self.llm_reward = LLMJudgeReward(api_key=llm_api_key)
        self.hybrid_reward = HybridReward(tushare_client, llm_api_key)
    
    async def calculate(self, trajectory: Trajectory, seed_tags: Dict) -> float:
        """
        根据任务类型选择合适的评估方式
        """
        verifiable = seed_tags.get("verifiable", False)
        verification_method = seed_tags.get("verification_method", "api")
        
        # 可验证任务 → 规则评估
        if verifiable and verification_method in ["api", "compute"]:
            return self.rule_reward.calculate(trajectory, seed_tags)
        
        # 混合任务 → 混合评估
        elif verifiable and verification_method == "hybrid":
            return await self.hybrid_reward.calculate(trajectory, seed_tags)
        
        # 开放式任务 → LLM 评判
        else:
            return await self.llm_reward.calculate(trajectory, seed_tags)
```

---

## 5. Ground Truth 缓存机制

### 5.1 为什么需要缓存

- API 调用有成本（Tushare 积分）
- API 调用有延迟（影响训练速度）
- 股价数据有有效时间（同一交易日内的查询结果相同）

### 5.2 缓存实现

```python
# synthesis/reward/ground_truth_cache.py

import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

class GroundTruthCache:
    """Ground Truth 缓存管理"""
    
    def __init__(self, cache_dir: str = ".cache/ground_truth"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache = {}
        
        # 不同字段的缓存有效期（分钟）
        self.ttl_config = {
            "current_price": 60,        # 股价缓存1小时
            "pe_ratio": 1440,           # PE缓存1天
            "pb_ratio": 1440,           # PB缓存1天
            "roe": 10080,               # ROE缓存1周
            "default": 60
        }
    
    def _get_cache_key(self, stock_code: str, field: str) -> str:
        """生成缓存 key"""
        content = f"{stock_code}_{field}_{datetime.now().strftime('%Y%m%d')}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _get_cache_file(self, cache_key: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{cache_key}.json"
    
    def get(self, stock_code: str, field: str) -> Optional[Any]:
        """获取缓存值"""
        cache_key = self._get_cache_key(stock_code, field)
        
        # 先查内存
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            if not self._is_expired(entry, field):
                return entry["value"]
        
        # 再查磁盘
        cache_file = self._get_cache_file(cache_key)
        if cache_file.exists():
            entry = json.loads(cache_file.read_text())
            if not self._is_expired(entry, field):
                self._memory_cache[cache_key] = entry
                return entry["value"]
        
        return None
    
    def set(self, stock_code: str, field: str, value: Any):
        """设置缓存值"""
        cache_key = self._get_cache_key(stock_code, field)
        
        entry = {
            "stock_code": stock_code,
            "field": field,
            "value": value,
            "cached_at": datetime.now().isoformat()
        }
        
        # 写入内存
        self._memory_cache[cache_key] = entry
        
        # 写入磁盘
        cache_file = self._get_cache_file(cache_key)
        cache_file.write_text(json.dumps(entry, ensure_ascii=False))
    
    def _is_expired(self, entry: Dict, field: str) -> bool:
        """检查是否过期"""
        cached_at = datetime.fromisoformat(entry["cached_at"])
        ttl_minutes = self.ttl_config.get(field, self.ttl_config["default"])
        expired_at = cached_at + timedelta(minutes=ttl_minutes)
        return datetime.now() > expired_at
    
    def batch_cache(self, stock_codes: list, fields: list, fetch_func):
        """
        批量缓存
        
        Args:
            stock_codes: 股票代码列表
            fields: 字段列表
            fetch_func: 获取数据的函数
        """
        missing = []
        
        # 检查哪些需要获取
        for code in stock_codes:
            for field in fields:
                if self.get(code, field) is None:
                    missing.append((code, field))
        
        # 批量获取
        if missing:
            results = fetch_func(missing)
            for (code, field), value in zip(missing, results):
                self.set(code, field, value)
```

---

## 6. 种子数据生成规范

### 6.1 文件结构

```
seeds/
├── finance_research/
│   ├── verifiable_query/          # 可验证查询（40%）
│   │   ├── stock_basic.jsonl      # 基础查询
│   │   └── financial_metrics.jsonl # 财务指标查询
│   ├── verifiable_compute/        # 可验证计算（20%）
│   │   └── calculations.jsonl
│   ├── semi_open/                 # 半开放式（25%）
│   │   ├── financial_health.jsonl
│   │   └── valuation_analysis.jsonl
│   └── open_ended/                # 全开放式（15%）
│       ├── investment_advice.jsonl
│       └── industry_analysis.jsonl
└── generate_seeds.py              # 生成脚本
```

### 6.2 种子生成脚本框架

```python
# seeds/generate_seeds.py

import json
from pathlib import Path
from typing import List, Dict

# 股票池
STOCK_POOL = {
    "liquor": [
        {"name": "贵州茅台", "code": "600519.SH"},
        {"name": "五粮液", "code": "000858.SZ"},
        {"name": "泸州老窖", "code": "000568.SZ"},
    ],
    "new_energy": [
        {"name": "宁德时代", "code": "300750.SZ"},
        {"name": "比亚迪", "code": "002594.SZ"},
    ],
    # ... 更多行业
}

# 模板库
TEMPLATES = {
    "verifiable_query": [
        {
            "template": "查询{stock_name}({stock_code})的实时股价",
            "tags": {
                "category": "stock_basic",
                "difficulty": "easy",
                "expected_turns": 1,
                "valid_skills": ["market_data"],
                "min_tools": 1,
                "max_tools": 2,
                "verifiable": True,
                "verification_method": "api",
                "verifiable_fields": [
                    {"field": "current_price", "tolerance": 0.01}
                ]
            }
        },
        {
            "template": "{stock_name}的最新ROE是多少？",
            "tags": {
                "category": "financial_deep",
                "difficulty": "medium",
                "expected_turns": 2,
                "valid_skills": ["financial_analysis"],
                "min_tools": 1,
                "max_tools": 2,
                "verifiable": True,
                "verification_method": "api",
                "verifiable_fields": [
                    {"field": "roe", "tolerance": 0.5}
                ]
            }
        }
    ],
    "open_ended": [
        {
            "template": "分析{stock_name}的投资价值",
            "tags": {
                "category": "comprehensive",
                "difficulty": "hard",
                "expected_turns": 4,
                "valid_skills": ["market_data", "financial_analysis", "sector_analysis"],
                "min_tools": 4,
                "max_tools": 7,
                "verifiable": False,
                "verification_method": "llm_judge",
                "evaluation_criteria": [
                    {"dimension": "信息完整性", "weight": 0.3},
                    {"dimension": "数据支撑度", "weight": 0.3},
                    {"dimension": "逻辑连贯性", "weight": 0.2},
                    {"dimension": "实用性", "weight": 0.2}
                ]
            }
        }
    ]
}

def generate_seeds(category: str, count: int) -> List[Dict]:
    """生成指定类别的种子数据"""
    seeds = []
    templates = TEMPLATES.get(category, [])
    
    for i in range(count):
        # 随机选择模板和股票
        template = templates[i % len(templates)]
        industry = list(STOCK_POOL.keys())[i % len(STOCK_POOL)]
        stock = STOCK_POOL[industry][i % len(STOCK_POOL[industry])]
        
        # 生成种子
        seed = {
            "content": template["template"].format(
                stock_name=stock["name"],
                stock_code=stock["code"]
            ),
            "kwargs": {
                "tags": {
                    **template["tags"],
                    "stock_code": stock["code"],
                    "industry": industry
                },
                "timeout": template["tags"].get("expected_turns", 3) * 30
            }
        }
        
        seeds.append(seed)
    
    return seeds

def main():
    """主函数"""
    output_dir = Path("seeds/finance_research")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成各类别种子
    categories = {
        "verifiable_query": 40,
        "verifiable_compute": 20,
        "semi_open": 25,
        "open_ended": 15
    }
    
    for category, count in categories.items():
        seeds = generate_seeds(category, count)
        
        # 按子类别分组写入
        output_file = output_dir / f"{category}.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            for seed in seeds:
                f.write(json.dumps(seed, ensure_ascii=False) + "\n")
        
        print(f"✅ 生成 {category}: {count} 个种子 → {output_file}")

if __name__ == "__main__":
    main()
```

---

## 7. 实施计划

### 7.1 Phase 1：基础设施（Week 1）

- [ ] 实现 `GroundTruthCache` 缓存机制
- [ ] 实现 `RuleBasedReward` 规则评估
- [ ] 实现 `LLMJudgeReward` LLM 评判
- [ ] 编写单元测试

### 7.2 Phase 2：种子数据（Week 1-2）

- [ ] 完成 `generate_seeds.py` 脚本
- [ ] 生成 100 个种子数据（实验集）
- [ ] 验证标签正确性
- [ ] 运行 Pipeline 测试评估流程

### 7.3 Phase 3：集成测试（Week 2）

- [ ] 集成到 GRPO Trainer
- [ ] 小规模训练实验（10 个 seed）
- [ ] 分析奖励分布，调整权重
- [ ] 修复发现的问题

### 7.4 Phase 4：扩展（Week 3）

- [ ] 扩展到 500-1000 个种子
- [ ] 增加更多任务类型
- [ ] 优化 LLM 评判 prompt
- [ ] 生产级训练

---

## 8. 附录

### 8.1 完整种子示例

```json
{
  "content": "对比贵州茅台和五粮液的估值水平",
  "kwargs": {
    "tags": {
      "category": "stock_comparison",
      "difficulty": "medium",
      "expected_turns": 3,
      "valid_skills": ["market_data"],
      "min_tools": 2,
      "max_tools": 4,
      "verifiable": true,
      "verification_method": "api",
      "stock_codes": ["600519.SH", "000858.SZ"],
      "verifiable_fields": [
        {"field": "maotai_pe", "path": "600519.SH.pe", "tolerance": 0.1, "weight": 0.25},
        {"field": "wuliangye_pe", "path": "000858.SZ.pe", "tolerance": 0.1, "weight": 0.25},
        {"field": "maotai_pb", "path": "600519.SH.pb", "tolerance": 0.1, "weight": 0.25},
        {"field": "wuliangye_pb", "path": "000858.SZ.pb", "tolerance": 0.1, "weight": 0.25}
      ],
      "reward_weights": {
        "accuracy": 0.5,
        "efficiency": 0.3,
        "format": 0.2
      }
    },
    "timeout": 90
  }
}
```

### 8.2 配置参考

```yaml
# config/reward_config.yaml

reward:
  # 默认权重
  default_weights:
    accuracy: 0.6
    efficiency: 0.3
    format: 0.1
  
  # 缓存配置
  cache:
    dir: ".cache/ground_truth"
    ttl:
      current_price: 60      # 分钟
      pe_ratio: 1440
      pb_ratio: 1440
      roe: 10080
  
  # LLM 评判配置
  llm_judge:
    model: "kimi-coding/k2p5"
    temperature: 0.0
    max_tokens: 2000
  
  # 容差配置
  tolerance:
    price: 0.01
    ratio: 0.1
    percentage: 0.5
```

---

**文档结束**
