import json
import random

# 读取我们生成的评分数据
with open("data/seeds_10000_production/seeds_10000_scored.jsonl", "r") as f:
    seeds = [json.loads(line) for line in f]

# 筛选高质量数据 (excellent + high)
high_quality = [
    s for s in seeds 
    if s["scores"]["quality_level"] in ["excellent", "high"]
]

# 随机打乱，取前 100 个用于测试
random.shuffle(high_quality)
test_seeds = high_quality[:100]

# 转换为 Agent Flow 格式
agentflow_seeds = []
for s in test_seeds:
    agentflow_seeds.append({
        "content": s["content"],
        "kwargs": {
            "tags": s.get("slots", {}),
            "entities": s.get("entities", {}),
            "quality_score": s["scores"]["overall"]
        }
    })

# 保存
with open("seeds/finance_research/our_seeds.jsonl", "w") as f:
    for s in agentflow_seeds:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

print(f"✅ 已准备 {len(agentflow_seeds)} 个 Seed")
