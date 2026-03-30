import json
import random

# 数据
STOCKS = [
    {"name": "贵州茅台", "code": "600519.SH"},
    {"name": "五粮液", "code": "000858.SZ"},
    {"name": "宁德时代", "code": "300750.SZ"},
    {"name": "比亚迪", "code": "002594.SZ"},
    {"name": "招商银行", "code": "600036.SH"},
    {"name": "平安银行", "code": "000001.SZ"},
    {"name": "中芯国际", "code": "688981.SH"},
    {"name": "海康威视", "code": "002415.SZ"},
    {"name": "隆基绿能", "code": "601012.SH"},
    {"name": "泸州老窖", "code": "000568.SZ"},
]

INDUSTRIES = ["白酒", "新能源", "银行", "科技", "医药", "消费"]
CONCEPTS = ["ROE", "PE", "PB", "MACD", "KDJ", "毛利率", "净利率", "股息率", "成交量", "换手率"]

random.seed(42)

seeds = []
used = set()
max_attempts = 5000
attempts = 0

while len(seeds) < 1000 and attempts < max_attempts:
    attempts += 1
    
    # 随机选择实体数量和类型
    r = random.random()
    
    if r < 0.05:  # 0个实体
        content = random.choice([
            "选股有什么方法？", "怎么分析一只股票值不值得买？", "新手怎么开始投资？",
            "帮我看看持仓组合", "我的股票组合需要调整吗？", "当前市场环境下如何构建组合？",
            "价值投资的核心方法论", "如何识别具有护城河的公司？"
        ])
        entity_count = 0
        entities = {"stocks": [], "industries": [], "concepts": []}
        
    elif r < 0.30:  # 1只股票
        s = random.choice(STOCKS)
        templates = [
            f"{s['name']}现在多少钱？", f"{s['name']}今天股价多少？",
            f"{s['name']}现在能买吗？", f"{s['name']}可以入手吗？",
            f"{s['name']}赚钱吗？", f"{s['name']}业绩怎么样？",
            f"{s['name']}现在贵不贵？", f"分析{s['name']}",
            f"{s['name']}怎么样？", f"{s['name']}亏了15%，要不要割肉？",
            f"{s['name']}风险大吗？我怕再跌", f"{s['name']}还能涨吗？"
        ]
        content = random.choice(templates)
        entity_count = 1
        entities = {"stocks": [s], "industries": [], "concepts": []}
        
    elif r < 0.65:  # 2只股票
        s1, s2 = random.sample(STOCKS, 2)
        templates = [
            f"{s1['name']}和{s2['name']}哪个好？",
            f"买{s1['name']}还是{s2['name']}？",
            f"{s1['name']} vs {s2['name']}，选哪个？",
            f"{s1['name']}和{s2['name']}哪个更稳？",
        ]
        content = random.choice(templates)
        entity_count = 2
        entities = {"stocks": [s1, s2], "industries": [], "concepts": []}
        
    elif r < 0.80:  # 3只股票
        s1, s2, s3 = random.sample(STOCKS, 3)
        templates = [
            f"帮我看看持仓：{s1['name']}、{s2['name']}、{s3['name']}",
            f"{s1['name']}、{s2['name']}、{s3['name']}这个组合怎么样？",
        ]
        content = random.choice(templates)
        entity_count = 3
        entities = {"stocks": [s1, s2, s3], "industries": [], "concepts": []}
        
    elif r < 0.90:  # 1个行业
        i = random.choice(INDUSTRIES)
        templates = [
            f"{i}板块今天怎么样？", f"{i}行业最近走势如何？",
            f"{i}龙头是哪只？", f"分析{i}行业",
        ]
        content = random.choice(templates)
        entity_count = 1
        entities = {"stocks": [], "industries": [i], "concepts": []}
        
    elif r < 0.95:  # 2个行业
        i1, i2 = random.sample(INDUSTRIES, 2)
        content = f"{i1}和{i2}哪个板块更有前景？"
        entity_count = 2
        entities = {"stocks": [], "industries": [i1, i2], "concepts": []}
        
    else:  # 1个概念
        c = random.choice(CONCEPTS)
        templates = [
            f"{c}是什么意思？", f"能解释下{c}吗？",
            f"{c}怎么看？", f"{c}怎么算？"
        ]
        content = random.choice(templates)
        entity_count = 1
        entities = {"stocks": [], "industries": [], "concepts": [c]}
    
    if content not in used:
        used.add(content)
        seeds.append({
            "content": content,
            "kwargs": {"tags": {"entity_count": entity_count, "has_entity": entity_count > 0}},
            "entities": entities
        })

# 统计
from collections import Counter
dist = Counter(s["kwargs"]["tags"]["entity_count"] for s in seeds)

print("📊 实体数量分布:")
for k, v in sorted(dist.items()):
    print(f"  {k}个实体: {v} ({v/len(seeds)*100:.1f}%)")

# 保存
with open("seeds_1000_final.jsonl", "w", encoding="utf-8") as f:
    for s in seeds:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")

print(f"\n💾 已保存 seeds_1000_final.jsonl")
print(f"✅ 共生成 {len(seeds)} 个 Seed")
print(f"📝 尝试次数: {attempts}")
