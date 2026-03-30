import json
import random

# 读取评分数据
with open("data/seeds_10000_production/seeds_10000_scored.jsonl", "r") as f:
    seeds = [json.loads(line) for line in f]

# 筛选 excellent 等级
excellent_seeds = [
    s for s in seeds 
    if s["scores"]["quality_level"] == "excellent"
]

print(f"excellent 等级 Seed: {len(excellent_seeds)} 个")

# 转换为 Agent Flow 格式
agentflow_seeds = []
for s in excellent_seeds:
    agentflow_seeds.append({
        "content": s["content"],
        "kwargs": {
            "tags": s.get("slots", {}),
            "entities": s.get("entities", {}),
            "quality_score": s["scores"]["overall"]
        }
    })

# 保存
with open("seeds/finance_research/excellent_seeds.jsonl", "w") as f:
    for s in agentflow_seeds:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

print(f"✅ 已保存 {len(agentflow_seeds)} 个 excellent Seed 到 seeds/finance_research/excellent_seeds.jsonl")
