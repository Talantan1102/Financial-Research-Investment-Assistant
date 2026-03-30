#!/usr/bin/env python3
"""
10万 Seed 生成方案 v3.1 - 阿里云Batch API版

使用阿里云批量任务API生成10万条Seed，优势：
1. 成本更低（批量任务有折扣）
2. 无需保持长连接
3. 自动处理并发和重试
4. 适合大规模生成
"""

import json
import random
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass
from openai import OpenAI
import time

# 设置随机种子
random.seed(42)

# ============ 配置 ============

DASHSCOPE_API_KEY = "sk-f5ad885285a44c339968325bdebc5658"
BATCH_SIZE = 100000  # 总任务数
TASKS_PER_FILE = 10000  # 每个文件的任务数（阿里云限制）

# ============ 槽位定义 ============

@dataclass
class SlotConfig:
    name: str
    weight: float
    description: str

SLOT_VALUES_V3 = {
    "user_type": {
        "小白": SlotConfig("小白", 0.12, "完全不懂投资"),
        "新手散户": SlotConfig("新手散户", 0.08, "刚入市"),
        "稳健散户": SlotConfig("稳健散户", 0.12, "追求稳健"),
        "激进散户": SlotConfig("激进散户", 0.08, "喜欢追涨"),
        "散户": SlotConfig("散户", 0.10, "普通散户"),
        "价值投资者": SlotConfig("价值投资者", 0.10, "看基本面"),
        "技术派": SlotConfig("技术派", 0.08, "看K线"),
        "基本面派": SlotConfig("基本面派", 0.05, "深度研究"),
        "专业": SlotConfig("专业", 0.08, "系统性投资"),
        "机构": SlotConfig("机构", 0.06, "研报风格"),
        "基金经理": SlotConfig("基金经理", 0.03, "组合视角"),
    },
    "intent": {
        "问买卖": SlotConfig("问买卖", 0.20, "买入/卖出决策"),
        "问估值": SlotConfig("问估值", 0.15, "贵不贵"),
        "查价格": SlotConfig("查价格", 0.12, "当前股价"),
        "比股票": SlotConfig("比股票", 0.12, "多股对比"),
        "问风险": SlotConfig("问风险", 0.12, "风险评估"),
        "深度分析": SlotConfig("深度分析", 0.13, "全面分析"),
        "学知识": SlotConfig("学知识", 0.10, "概念学习"),
        "问配置": SlotConfig("问配置", 0.06, "组合配置"),
    },
    "context": {
        "空仓观望": SlotConfig("空仓观望", 0.10, "没持仓，在看"),
        "准备建仓": SlotConfig("准备建仓", 0.08, "想买"),
        "等待回调": SlotConfig("等待回调", 0.05, "等跌下来买"),
        "刚买入": SlotConfig("刚买入", 0.05, "刚建仓"),
        "小赚": SlotConfig("小赚", 0.08, "盈利不多"),
        "已盈利": SlotConfig("已盈利", 0.10, "赚钱中"),
        "大赚": SlotConfig("大赚", 0.04, "赚很多"),
        "刚被套": SlotConfig("刚被套", 0.06, "开始亏损"),
        "已亏损": SlotConfig("已亏损", 0.12, "亏钱中"),
        "深套中": SlotConfig("深套中", 0.10, "亏很多"),
        "套牢很久": SlotConfig("套牢很久", 0.04, "长期被套"),
        "开盘前": SlotConfig("开盘前", 0.03, "早盘前"),
        "盘中": SlotConfig("盘中", 0.03, "交易时间"),
        "收盘后": SlotConfig("收盘后", 0.02, "盘后"),
    },
    "expression_style": {
        "啰嗦型": SlotConfig("啰嗦型", 0.15, "话多，反复说"),
        "简洁型": SlotConfig("简洁型", 0.25, "言简意赅"),
        "模糊型": SlotConfig("模糊型", 0.20, "表达不清"),
        "精确型": SlotConfig("精确型", 0.25, "数据准确"),
        "口语化": SlotConfig("口语化", 0.15, "随意自然"),
    },
    "query_length": {
        "超短": SlotConfig("超短", 0.08, "1-10字"),
        "短句": SlotConfig("短句", 0.20, "10-30字"),
        "中等": SlotConfig("中等", 0.35, "30-60字"),
        "较长": SlotConfig("较长", 0.25, "60-100字"),
        "很长": SlotConfig("很长", 0.12, "100-150字"),
    },
}

STOCK_POOL_V3 = {
    "白酒": ["贵州茅台", "五粮液", "泸州老窖", "山西汾酒", "洋河股份", "古井贡酒"],
    "新能源": ["宁德时代", "比亚迪", "隆基绿能", "阳光电源", "通威股份", "TCL中环"],
    "银行": ["招商银行", "平安银行", "宁波银行", "兴业银行", "工商银行", "建设银行"],
    "科技": ["中芯国际", "海康威视", "北方华创", "韦尔股份", "兆易创新", "紫光国微"],
    "医药": ["恒瑞医药", "迈瑞医疗", "药明康德", "片仔癀", "爱尔眼科", "智飞生物"],
    "消费": ["美的集团", "海天味业", "伊利股份", "中国中免", "格力电器", "顺丰控股"],
    "新能源车上游": ["天齐锂业", "赣锋锂业", "华友钴业", "天赐材料", "恩捷股份"],
    "互联网/软件": ["科大讯飞", "金山办公", "恒生电子", "用友网络"],
}

INDUSTRIES_V3 = list(STOCK_POOL_V3.keys())

BUILD_SEED_PROMPT = """你是一个投资用户，正在向AI助手咨询股票相关问题。

【你的画像】
- 用户类型：{user_type}
- 意图：{intent}
- 当前状态：{context}
- 表达风格：{expression_style}
- Query长度：{query_length}

【实体信息】
{entity_info}

【生成要求】
1. 严格遵循"表达风格"的要求：
   - 啰嗦型：说话啰嗦，反复强调，夹杂无关信息，句子很长（80-150字）
   - 简洁型：言简意赅，直接说重点，短句（10-30字）
   - 模糊型：表达不清，用词不准，意思含糊（如"那个什么...", "大概...", "好像..."）
   - 精确型：有具体数字，逻辑清晰，用词准确（如"我50块买的，现在亏了15%"）
   - 口语化：像聊天一样自然，有口头禅（如"那个...", "说实话...", "我觉得吧..."）

2. 严格遵循"Query长度"的要求控制字数

3. 根据"意图"和"当前状态"决定query内容

4. 如果有实体（股票/行业），query中应该提及；如果是无实体场景，query不应该提及具体股票

5. 根据"用户类型"调整用词

请生成一个符合以上所有要求的query，只输出query内容，不要有任何解释。"""

# ============ 任务生成器 ============

class BatchTaskGenerator:
    """生成阿里云Batch API任务文件"""
    
    def __init__(self):
        self.stock_pool = STOCK_POOL_V3
        self.industries = INDUSTRIES_V3
        self.slot_values = SLOT_VALUES_V3
        self.task_id = 0
    
    def weighted_choice(self, options: Dict[str, SlotConfig]) -> str:
        keys = list(options.keys())
        weights = [options[k].weight for k in keys]
        total = sum(weights)
        r = random.uniform(0, total)
        for key, weight in zip(keys, weights):
            r -= weight
            if r <= 0:
                return key
        return keys[-1]
    
    def select_entities(self) -> Dict[str, Any]:
        r = random.random()
        if r < 0.10:
            return {"type": "none", "stocks": [], "industries": [], "concepts": []}
        elif r < 0.55:
            industry = random.choice(self.industries)
            stock = random.choice(self.stock_pool[industry])
            return {"type": "single_stock", "stocks": [stock], "industries": [industry], "concepts": []}
        elif r < 0.80:
            industries = random.sample(self.industries, 2)
            stocks = [random.choice(self.stock_pool[i]) for i in industries]
            return {"type": "multi_stock", "stocks": stocks, "industries": industries, "concepts": []}
        elif r < 0.95:
            industry = random.choice(self.industries)
            return {"type": "industry", "stocks": [], "industries": [industry], "concepts": []}
        else:
            return {"type": "concept", "stocks": [], "industries": [], "concepts": []}
    
    def build_prompt(self, slots: Dict[str, str], entities: Dict[str, Any]) -> str:
        if entities["type"] == "none":
            entity_info = "无具体实体，用户可能在学习概念或询问通用投资方法"
        elif entities["type"] == "single_stock":
            entity_info = f"关注股票：{entities['stocks'][0]}（{entities['industries'][0]}）"
        elif entities["type"] == "multi_stock":
            entity_info = f"对比股票：{' vs '.join(entities['stocks'])}"
        elif entities["type"] == "industry":
            entity_info = f"关注行业：{entities['industries'][0]}"
        else:
            entity_info = "学习投资概念或方法"
        
        return BUILD_SEED_PROMPT.format(
            user_type=slots["user_type"],
            intent=slots["intent"],
            context=slots["context"],
            expression_style=slots["expression_style"],
            query_length=slots["query_length"],
            entity_info=entity_info
        )
    
    def generate_task(self) -> Dict[str, Any]:
        """生成单个任务"""
        self.task_id += 1
        
        slots = {
            "user_type": self.weighted_choice(self.slot_values["user_type"]),
            "intent": self.weighted_choice(self.slot_values["intent"]),
            "context": self.weighted_choice(self.slot_values["context"]),
            "expression_style": self.weighted_choice(self.slot_values["expression_style"]),
            "query_length": self.weighted_choice(self.slot_values["query_length"]),
        }
        
        entities = self.select_entities()
        prompt = self.build_prompt(slots, entities)
        
        # 构建Batch API请求格式
        task = {
            "custom_id": f"task_{self.task_id:06d}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "deepseek-v3.2",
                "messages": [
                    {"role": "system", "content": "你是一个投资用户模拟器，生成真实的用户query。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.9,
                "max_tokens": 200
            },
            "metadata": {
                "slots": slots,
                "entities": entities
            }
        }
        
        return task
    
    def generate_batch_files(self, total: int = 100000, tasks_per_file: int = 10000):
        """生成分批任务文件"""
        num_files = (total + tasks_per_file - 1) // tasks_per_file
        
        print(f"🚀 生成 {total} 个 Batch 任务")
        print(f"   每文件任务数: {tasks_per_file}")
        print(f"   总文件数: {num_files}\n")
        
        file_paths = []
        
        for file_idx in range(1, num_files + 1):
            file_path = f"batch_tasks_{file_idx:02d}.jsonl"
            file_paths.append(file_path)
            
            current_batch_size = min(tasks_per_file, total - (file_idx - 1) * tasks_per_file)
            
            with open(file_path, "w", encoding="utf-8") as f:
                for _ in range(current_batch_size):
                    task = self.generate_task()
                    f.write(json.dumps(task, ensure_ascii=False) + "\n")
            
            print(f"  ✅ 文件 {file_idx}/{num_files}: {file_path} ({current_batch_size} 个任务)")
        
        print(f"\n✅ 全部任务文件生成完成！")
        return file_paths


# ============ Batch API 提交 ============

class BatchAPISubmitter:
    """提交Batch任务到阿里云"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.batch_jobs = []
    
    def submit_file(self, file_path: str) -> str:
        """上传任务文件"""
        print(f"  📤 上传文件: {file_path}")
        with open(file_path, "rb") as f:
            file = self.client.files.create(file=f, purpose="batch")
        print(f"     文件ID: {file.id}")
        return file.id
    
    def create_batch_job(self, file_id: str) -> str:
        """创建批量任务"""
        batch_job = self.client.batches.create(
            input_file_id=file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h"
        )
        print(f"     任务ID: {batch_job.id}, 状态: {batch_job.status}")
        return batch_job.id
    
    def submit_all(self, file_paths: List[str]):
        """提交所有文件"""
        print(f"\n🚀 提交 {len(file_paths)} 个 Batch 任务到阿里云\n")
        
        for i, file_path in enumerate(file_paths, 1):
            print(f"[{i}/{len(file_paths)}] 提交 {file_path}")
            file_id = self.submit_file(file_path)
            job_id = self.create_batch_job(file_id)
            self.batch_jobs.append({
                "file_path": file_path,
                "file_id": file_id,
                "job_id": job_id
            })
            print()
        
        # 保存任务信息
        with open("batch_jobs_info.json", "w", encoding="utf-8") as f:
            json.dump(self.batch_jobs, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 全部提交完成！任务信息已保存到 batch_jobs_info.json")
        print(f"\n接下来请运行:")
        print(f"  python3 scripts/seeds/generate_seeds_100k_v3_batch.py --monitor")


# ============ 任务监控与下载 ============

class BatchJobMonitor:
    """监控Batch任务状态并下载结果"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=DASHSCOPE_API_KEY,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        
        with open("batch_jobs_info.json", "r", encoding="utf-8") as f:
            self.batch_jobs = json.load(f)
    
    def monitor_all(self):
        """监控所有任务"""
        print("\n👀 开始监控 Batch 任务状态\n")
        
        completed = 0
        failed = 0
        
        while completed + failed < len(self.batch_jobs):
            for job_info in self.batch_jobs:
                if job_info.get("status") in ["completed", "failed", "cancelled"]:
                    continue
                
                job = self.client.batches.retrieve(job_info["job_id"])
                job_info["status"] = job.status
                
                if job.status == "completed":
                    completed += 1
                    self.download_result(job_info, job)
                    print(f"  ✅ {job_info['file_path']}: 完成")
                elif job.status == "failed":
                    failed += 1
                    print(f"  ❌ {job_info['file_path']}: 失败")
                else:
                    print(f"  ⏳ {job_info['file_path']}: {job.status}")
            
            if completed + failed < len(self.batch_jobs):
                print(f"\n进度: {completed}/{len(self.batch_jobs)} 完成, {failed} 失败")
                print("等待60秒后再次查询...\n")
                time.sleep(60)
        
        print(f"\n{'='*60}")
        print(f"✅ 全部任务完成！")
        print(f"   成功: {completed}")
        print(f"   失败: {failed}")
        print(f"{'='*60}")
        
        # 合并结果
        self.merge_results()
    
    def download_result(self, job_info: Dict, job):
        """下载任务结果"""
        if job.output_file_id:
            result_content = self.client.files.content(job.output_file_id).text
            output_path = job_info["file_path"].replace("batch_tasks_", "batch_results_")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(result_content)
            job_info["output_path"] = output_path
        
        if job.error_file_id:
            error_content = self.client.files.content(job.error_file_id).text
            error_path = job_info["file_path"].replace("batch_tasks_", "batch_errors_")
            with open(error_path, "w", encoding="utf-8") as f:
                f.write(error_content)
            job_info["error_path"] = error_path
    
    def merge_results(self):
        """合并所有结果"""
        print("\n🔄 合并所有结果...")
        
        all_seeds = []
        
        for job_info in self.batch_jobs:
            if "output_path" in job_info and os.path.exists(job_info["output_path"]):
                with open(job_info["output_path"], "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            result = json.loads(line)
                            custom_id = result.get("custom_id", "")
                            content = result.get("response", {}).get("body", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
                            
                            # 找到对应的metadata
                            metadata = self.find_metadata(custom_id)
                            
                            all_seeds.append({
                                "content": content,
                                "slots": metadata.get("slots", {}),
                                "entities": metadata.get("entities", {}),
                                "task_id": custom_id
                            })
                        except:
                            continue
        
        # 保存合并结果
        output_file = "seeds_100k_v3_batch_all.jsonl"
        with open(output_file, "w", encoding="utf-8") as f:
            for seed in all_seeds:
                f.write(json.dumps(seed, ensure_ascii=False) + "\n")
        
        print(f"✅ 合并完成！共 {len(all_seeds)} 个 Seeds")
        print(f"   文件: {output_file}")
    
    def find_metadata(self, custom_id: str) -> Dict:
        """从任务文件中找到对应的metadata"""
        # 从batch_tasks文件中查找
        for job_info in self.batch_jobs:
            file_path = job_info["file_path"]
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        task = json.loads(line)
                        if task.get("custom_id") == custom_id:
                            return task.get("metadata", {})
        return {}


# ============ 主函数 ============

def main_generate():
    """生成任务文件"""
    generator = BatchTaskGenerator()
    file_paths = generator.generate_batch_files(total=BATCH_SIZE, tasks_per_file=TASKS_PER_FILE)
    
    print(f"\n生成完成！请运行:")
    print(f"  python3 scripts/seeds/generate_seeds_100k_v3_batch.py --submit")

def main_submit():
    """提交任务"""
    # 查找所有任务文件
    file_paths = sorted([f for f in os.listdir(".") if f.startswith("batch_tasks_") and f.endswith(".jsonl")])
    
    if not file_paths:
        print("❌ 未找到任务文件，请先运行 --generate")
        return
    
    submitter = BatchAPISubmitter()
    submitter.submit_all(file_paths)

def main_monitor():
    """监控任务"""
    if not os.path.exists("batch_jobs_info.json"):
        print("❌ 未找到任务信息文件，请先运行 --submit")
        return
    
    monitor = BatchJobMonitor()
    monitor.monitor_all()

def main():
    import sys
    
    if len(sys.argv) < 2:
        print("="*60)
        print("🚀 10万 Seed 生成方案 v3.1 - 阿里云Batch API版")
        print("="*60)
        print("\n使用方法:")
        print("  1. 生成任务文件: python3 scripts/seeds/generate_seeds_100k_v3_batch.py --generate")
        print("  2. 提交任务:     python3 scripts/seeds/generate_seeds_100k_v3_batch.py --submit")
        print("  3. 监控任务:     python3 scripts/seeds/generate_seeds_100k_v3_batch.py --monitor")
        print("\n或一键执行全部:")
        print("  python3 scripts/seeds/generate_seeds_100k_v3_batch.py --all")
        return
    
    command = sys.argv[1]
    
    if command == "--generate":
        main_generate()
    elif command == "--submit":
        main_submit()
    elif command == "--monitor":
        main_monitor()
    elif command == "--all":
        main_generate()
        main_submit()
        main_monitor()
    else:
        print(f"❌ 未知命令: {command}")
        print("可用命令: --generate, --submit, --monitor, --all")

if __name__ == "__main__":
    main()
