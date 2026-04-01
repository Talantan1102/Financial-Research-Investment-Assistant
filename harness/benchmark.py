#!/usr/bin/env python3
"""
Claude Harness - 基准测试模块

用法:
    python harness/benchmark.py --config harness/configs/benchmark_finance.json
"""

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import statistics


class BenchmarkResult:
    """基准测试结果"""

    def __init__(self, metric_name: str, score: float,
                 details: Dict = None, passed: bool = True):
        self.metric_name = metric_name
        self.score = score
        self.details = details or {}
        self.passed = passed
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "score": self.score,
            "passed": self.passed,
            "timestamp": self.timestamp,
            "details": self.details
        }


class Benchmark:
    """基准测试基类"""

    name = "base_benchmark"
    description = "基础基准测试"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.results: List[BenchmarkResult] = []

    async def load_data(self) -> List[Dict]:
        """加载测试数据"""
        data_path = self.config.get("data_path")
        if not data_path or not os.path.exists(data_path):
            raise FileNotFoundError(f"数据文件不存在: {data_path}")

        data = []
        with open(data_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    data.append(json.loads(line))
        return data

    async def evaluate(self, prediction: str, reference: str) -> Dict[str, float]:
        """评估单个预测结果"""
        metrics = {}

        # Exact Match
        metrics["exact_match"] = 1.0 if prediction.strip() == reference.strip() else 0.0

        # Contains Answer
        metrics["contains_answer"] = 1.0 if reference.lower() in prediction.lower() else 0.0

        # F1 Score (简单的词级别)
        pred_words = set(prediction.lower().split())
        ref_words = set(reference.lower().split())
        if pred_words or ref_words:
            common = pred_words & ref_words
            precision = len(common) / len(pred_words) if pred_words else 0
            recall = len(common) / len(ref_words) if ref_words else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
            metrics["f1_score"] = f1
        else:
            metrics["f1_score"] = 0.0

        return metrics

    async def run(self) -> List[BenchmarkResult]:
        """运行基准测试"""
        raise NotImplementedError


class QABenchmark(Benchmark):
    """问答基准测试"""

    name = "qa_benchmark"
    description = "问答质量基准测试"

    async def run(self) -> List[BenchmarkResult]:
        """运行 QA 基准测试"""
        print(f"\n📊 运行 QA 基准测试: {self.config.get('benchmark_name', 'unknown')}")

        # 加载数据
        data = await self.load_data()
        print(f"   加载了 {len(data)} 条测试数据")

        if not data:
            return [BenchmarkResult("load_data", 0.0, {}, passed=False)]

        # 收集所有指标的分数
        all_scores: Dict[str, List[float]] = {
            "exact_match": [],
            "f1_score": [],
            "contains_answer": []
        }

        # 评估每个样本
        for item in data[:self.config.get("max_samples", 100)]:
            prediction = item.get("prediction", "")
            reference = item.get("answer", item.get("reference", ""))

            scores = await self.evaluate(prediction, reference)
            for metric, score in scores.items():
                if metric in all_scores:
                    all_scores[metric].append(score)

        # 计算平均分数
        results = []
        thresholds = self.config.get("thresholds", {})

        for metric_name, scores in all_scores.items():
            if scores:
                avg_score = statistics.mean(scores)
                threshold = thresholds.get(metric_name, 0.5)

                results.append(BenchmarkResult(
                    metric_name=metric_name,
                    score=avg_score,
                    details={"samples": len(scores), "threshold": threshold},
                    passed=avg_score >= threshold
                ))

        return results


class BenchmarkRunner:
    """基准测试运行器"""

    BENCHMARKS = {
        "qa": QABenchmark,
    }

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.results_dir = Path("harness/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件"""
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    async def run(self) -> List[BenchmarkResult]:
        """运行基准测试"""
        benchmark_type = self.config.get("type", "qa")

        if benchmark_type not in self.BENCHMARKS:
            raise ValueError(f"未知基准类型: {benchmark_type}")

        benchmark_class = self.BENCHMARKS[benchmark_type]
        benchmark = benchmark_class(self.config)

        return await benchmark.run()

    def save_results(self, results: List[BenchmarkResult]):
        """保存测试结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        benchmark_name = self.config.get("benchmark_name", "unknown")
        result_file = self.results_dir / f"benchmark_{benchmark_name}_{timestamp}.json"

        output = {
            "timestamp": datetime.now().isoformat(),
            "benchmark_name": benchmark_name,
            "config": self.config,
            "results": [r.to_dict() for r in results]
        }

        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n💾 基准测试结果已保存: {result_file}")

    def print_summary(self, results: List[BenchmarkResult]):
        """打印测试摘要"""
        print(f"\n{'='*60}")
        print("📊 基准测试摘要")
        print(f"{'='*60}")

        for result in results:
            icon = "✅" if result.passed else "❌"
            threshold = result.details.get("threshold", 0.5)
            print(f"{icon} {result.metric_name}: {result.score:.3f} "
                  f"(阈值: {threshold:.3f})")

        passed = sum(1 for r in results if r.passed)
        print(f"\n总计: {passed}/{len(results)} 指标通过")


async def main():
    parser = argparse.ArgumentParser(description="Claude Harness - 基准测试")
    parser.add_argument("--config", type=str, required=True,
                       help="基准测试配置文件路径")

    args = parser.parse_args()

    runner = BenchmarkRunner(args.config)
    results = await runner.run()
    runner.print_summary(results)
    runner.save_results(results)

    # 如果有失败的指标，返回非零退出码
    for result in results:
        if not result.passed:
            return 1
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
