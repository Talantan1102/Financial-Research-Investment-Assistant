#!/usr/bin/env python3
"""
Seed 批量评分脚本
使用 LLM (qwen-max) 对生产的 Seed 进行 5 维度质量评分
"""

import json
import os
import sys
import time
import concurrent.futures
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import Counter
import threading

try:
    from openai import OpenAI
except ImportError:
    print("❌ 请先安装 openai: pip install openai")
    sys.exit(1)

# ============ 配置 ============
DASHSCOPE_API_KEY = "sk-f5ad885285a44c339968325bdebc5658"
MAX_WORKERS = 10
RATE_LIMIT_PER_SECOND = 10
INPUT_FILE = "data/seeds_10000_production/seeds_10000_all.jsonl"
OUTPUT_FILE = "data/seeds_10000_production/seeds_10000_scored.jsonl"
REPORT_FILE = "data/seeds_10000_production/scoring_report.txt"
CHECKPOINT_FILE = "data/seeds_10000_production/scoring_checkpoint.txt"

# ============ LLM 客户端 ============
class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.lock = threading.Lock()
        self.request_count = 0
        
    def score(self, prompt: str) -> Optional[Dict]:
        """调用 LLM 评分"""
        try:
            response = self.client.chat.completions.create(
                model="qwen-max",
                messages=[
                    {"role": "system", "content": "你是一个专业的金融对话数据质量评估专家。请严格按照JSON格式输出评分结果。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500,
            )
            content = response.choices[0].message.content.strip()
            
            with self.lock:
                self.request_count += 1
                
            # 解析 JSON
            return self._parse_json(content)
            
        except Exception as e:
            print(f"⚠️ API调用失败: {e}")
            return None
    
    def _parse_json(self, content: str) -> Optional[Dict]:
        """解析 JSON 响应"""
        import re
        
        # 提取 JSON 代码块
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            # 尝试清理后解析
            try:
                content = content.strip().strip('`').strip()
                return json.loads(content)
            except:
                print(f"⚠️ JSON解析失败: {content[:100]}...")
                return None

llm_client = LLMClient()

# ============ 评分 Prompt ============
SCORING_PROMPT_TEMPLATE = """请对以下投资咨询问题进行质量评分。

【待评估问题】
{content}

【标签信息】
- 用户类型: {user_type}
- 意图: {intent}
- 场景: {context}
- 风格: {style}
- 实体: {entities}

【评分维度】（0-10分，10分为最佳）

1. **自然度** (30%权重): 是否像真实用户会问的？语言是否自然流畅？
   - 10分: 非常自然，完全像真人提问
   - 5分: 一般，有机器感
   - 0分: 明显机器生成

2. **相关性** (25%权重): 与槽位标签的匹配程度？
   - 10分: 完美匹配所有标签
   - 5分: 部分匹配
   - 0分: 完全不匹配

3. **完整性** (20%权重): 信息是否完整可回答？
   - 10分: 完整，无需追问
   - 5分: 部分缺失
   - 0分: 极度缺失

4. **合规性** (15%权重): 有无编造市场走势/敏感内容？
   - 10分: 完全合规
   - 5分: 轻微违规（如出现"一直跌"、"涨得好"等编造走势）
   - 0分: 严重违规

5. **实用性** (10%权重): 对训练金融对话模型的价值？
   - 10分: 极高价值
   - 5分: 一般价值
   - 0分: 无价值

【输出格式】
```json
{{
  "naturalness": 8,
  "naturalness_comment": "语言自然，符合用户类型",
  "relevance": 9,
  "relevance_comment": "与槽位标签高度匹配",
  "completeness": 7,
  "completeness_comment": "信息基本完整",
  "compliance": 10,
  "compliance_comment": "无违规内容",
  "utility": 8,
  "utility_comment": "对训练有价值",
  "overall": 8.15,
  "quality_level": "high"
}}
```

quality_level 根据 overall 分数评定：
- 9-10分: "excellent" 
- 8-8.9分: "high"
- 6-7.9分: "medium"
- 4-5.9分: "low"
- 0-3.9分: "discard"

overall 分数计算: naturalness*0.3 + relevance*0.25 + completeness*0.2 + compliance*0.15 + utility*0.1

请只输出JSON，不要其他内容。"""

# ============ 工具函数 ============
def format_entities(entities: Dict) -> str:
    """格式化实体描述"""
    parts = []
    if entities.get("stocks"):
        parts.append(f"股票:{','.join([s['name'] for s in entities['stocks']])}")
    if entities.get("industries"):
        parts.append(f"行业:{','.join(entities['industries'])}")
    if entities.get("concepts"):
        parts.append(f"概念:{','.join(entities['concepts'])}")
    return ";".join(parts) if parts else "无"

def calculate_overall(scores: Dict) -> float:
    """计算综合分"""
    return (
        scores.get("naturalness", 0) * 0.3 +
        scores.get("relevance", 0) * 0.25 +
        scores.get("completeness", 0) * 0.2 +
        scores.get("compliance", 0) * 0.15 +
        scores.get("utility", 0) * 0.1
    )

def get_quality_level(overall: float) -> str:
    """获取质量等级"""
    if overall >= 9.0:
        return "excellent"
    elif overall >= 8.0:
        return "high"
    elif overall >= 6.0:
        return "medium"
    elif overall >= 4.0:
        return "low"
    else:
        return "discard"

# ============ 评分核心 ============
def score_single_seed(seed: Dict, index: int) -> Optional[Dict]:
    """对单个 Seed 评分"""
    content = seed.get("content", "")
    slots = seed.get("slots", {})
    entities = seed.get("entities", {})
    
    # 构建 prompt
    prompt = SCORING_PROMPT_TEMPLATE.format(
        content=content,
        user_type=slots.get("user_type", "未知"),
        intent=slots.get("intent", "未知"),
        context=slots.get("context", "未知"),
        style=slots.get("style", "未知"),
        entities=format_entities(entities),
    )
    
    # 调用 LLM
    scores = llm_client.score(prompt)
    
    if not scores:
        return None
    
    # 计算综合分
    overall = calculate_overall(scores)
    scores["overall"] = round(overall, 2)
    scores["quality_level"] = get_quality_level(overall)
    
    # 合并结果
    result = {
        **seed,
        "scores": scores,
        "scored_at": datetime.now().isoformat(),
        "scored_index": index,
    }
    
    return result

# ============ 批量评分 ============
def load_seeds(filepath: str) -> List[Dict]:
    """加载 Seed 数据"""
    seeds = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                seeds.append(json.loads(line))
    return seeds

def save_checkpoint(processed: int):
    """保存检查点"""
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(str(processed))

def load_checkpoint() -> int:
    """加载检查点"""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return int(f.read().strip())
    return 0

def batch_score(seeds: List[Dict], start_idx: int = 0) -> List[Dict]:
    """批量评分"""
    results = []
    total = len(seeds)
    
    print(f"\n🚀 开始评分: {total} 个 Seed")
    print(f"   起始位置: {start_idx}")
    print(f"   并发数: {MAX_WORKERS}")
    print(f"   预计耗时: {total * 0.5 / MAX_WORKERS:.1f} 分钟\n")
    
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        
        # 提交任务
        for i, seed in enumerate(seeds[start_idx:], start=start_idx):
            future = executor.submit(score_single_seed, seed, i)
            futures[future] = i
            
            # 速率限制
            if (i + 1) % RATE_LIMIT_PER_SECOND == 0:
                time.sleep(1)
        
        # 收集结果
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                    
                    # 实时保存
                    if len(results) % 100 == 0:
                        append_results(results[-100:], OUTPUT_FILE)
                        save_checkpoint(idx + 1)
                        
                    completed += 1
                    if completed % 50 == 0:
                        progress = (idx + 1) / total * 100
                        elapsed = time.time() - start_time
                        speed = (idx + 1) / elapsed if elapsed > 0 else 0
                        eta = (total - idx - 1) / speed if speed > 0 else 0
                        print(f"  ✅ {idx+1}/{total} ({progress:.1f}%) | "
                              f"成功:{len(results)} | "
                              f"速度:{speed:.1f}个/秒 | "
                              f"ETA:{eta/60:.1f}分钟")
                        
            except Exception as e:
                print(f"⚠️ 处理 Seed {idx} 失败: {e}")
    
    return results

def append_results(results: List[Dict], filepath: str):
    """追加保存结果"""
    with open(filepath, "a", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def generate_report(scored_seeds: List[Dict]):
    """生成评分报告"""
    report = []
    report.append("="*70)
    report.append("📊 Seed 评分报告")
    report.append("="*70)
    report.append(f"\n总评分数: {len(scored_seeds)}")
    
    # 综合分统计
    overall_scores = [s["scores"]["overall"] for s in scored_seeds if "scores" in s]
    if overall_scores:
        report.append(f"平均综合分: {sum(overall_scores)/len(overall_scores):.2f}")
        report.append(f"最高综合分: {max(overall_scores):.2f}")
        report.append(f"最低综合分: {min(overall_scores):.2f}")
    
    # 质量分级分布
    report.append("\n【质量分级分布】")
    level_dist = Counter(s["scores"]["quality_level"] for s in scored_seeds if "scores" in s)
    for level in ["excellent", "high", "medium", "low", "discard"]:
        count = level_dist.get(level, 0)
        pct = count / len(scored_seeds) * 100 if scored_seeds else 0
        report.append(f"  {level}: {count} ({pct:.1f}%)")
    
    # 各维度平均分
    report.append("\n【各维度平均分】")
    dimensions = ["naturalness", "relevance", "completeness", "compliance", "utility"]
    for dim in dimensions:
        scores = [s["scores"][dim] for s in scored_seeds if "scores" in s and dim in s["scores"]]
        if scores:
            avg = sum(scores) / len(scores)
            report.append(f"  {dim}: {avg:.2f}")
    
    # 用户类型分布（按质量）
    report.append("\n【用户类型-质量交叉】")
    user_quality = {}
    for s in scored_seeds:
        if "scores" not in s:
            continue
        user = s.get("slots", {}).get("user_type", "unknown")
        level = s["scores"]["quality_level"]
        if user not in user_quality:
            user_quality[user] = Counter()
        user_quality[user][level] += 1
    
    for user, dist in user_quality.items():
        total = sum(dist.values())
        high_pct = (dist.get("excellent", 0) + dist.get("high", 0)) / total * 100 if total > 0 else 0
        report.append(f"  {user}: 高质量占比 {high_pct:.1f}%")
    
    report.append("\n" + "="*70)
    
    report_text = "\n".join(report)
    print("\n" + report_text)
    
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n📄 报告已保存: {REPORT_FILE}")

# ============ 主流程 ============
def main():
    print("="*70)
    print("🎯 Seed 批量评分系统")
    print("="*70)
    
    # 检查输入文件
    if not os.path.exists(INPUT_FILE):
        print(f"❌ 输入文件不存在: {INPUT_FILE}")
        return
    
    # 加载数据
    print(f"\n📂 加载 Seed 数据: {INPUT_FILE}")
    seeds = load_seeds(INPUT_FILE)
    print(f"   共 {len(seeds)} 个 Seed")
    
    # 检查检查点
    start_idx = load_checkpoint()
    if start_idx > 0:
        print(f"📍 从检查点恢复: 已评分 {start_idx} 个")
        
        # 加载已评分结果
        scored_seeds = []
        if os.path.exists(OUTPUT_FILE):
            scored_seeds = load_seeds(OUTPUT_FILE)
            print(f"   已加载 {len(scored_seeds)} 个评分结果")
    
    # 确认开始
    remaining = len(seeds) - start_idx
    print(f"\n📝 待评分: {remaining} 个 Seed")
    print(f"   输出文件: {OUTPUT_FILE}")
    
    confirm = input("\n确认开始评分? (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消")
        return
    
    # 批量评分
    new_results = batch_score(seeds, start_idx)
    
    # 合并所有结果
    all_results = scored_seeds + new_results if start_idx > 0 else new_results
    
    # 保存完整结果
    print(f"\n💾 保存完整结果: {OUTPUT_FILE}")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    
    # 生成报告
    generate_report(all_results)
    
    # 清理检查点
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
    
    print("\n" + "="*70)
    print("✅ 评分完成!")
    print(f"   总评分: {len(all_results)} 个")
    print(f"   输出文件: {OUTPUT_FILE}")
    print("="*70)

if __name__ == "__main__":
    main()
