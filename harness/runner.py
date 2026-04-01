#!/usr/bin/env python3
"""
Claude Harness - AgentFlow 测试和评估框架

用法:
    python harness/runner.py --suite all
    python harness/runner.py --module synthesis --test test_sampler

环境要求:
    必须在 conda deepresearch 环境中运行
"""

import argparse
import asyncio
import json
import os
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# Conda 环境配置
CONDA_ENV_NAME = "deepresearch"


def check_conda_env():
    """检查是否在正确的 conda 环境中运行"""
    # 检查 CONDA_DEFAULT_ENV 环境变量
    current_env = os.environ.get("CONDA_DEFAULT_ENV", "")
    if current_env == CONDA_ENV_NAME:
        return True, current_env

    # 检查 Python 路径
    python_path = sys.executable
    if CONDA_ENV_NAME in python_path:
        return True, current_env

    return False, current_env


def ensure_conda_env():
    """确保在正确的 conda 环境中运行，如果不是则尝试切换"""
    is_correct_env, current_env = check_conda_env()

    if is_correct_env:
        print(f"✅ 当前已在 conda '{CONDA_ENV_NAME}' 环境中")
        return True

    print(f"⚠️  当前环境: '{current_env or 'base/system'}'")
    print(f"🔄 需要切换到 conda '{CONDA_ENV_NAME}' 环境")

    # 尝试使用 conda run 重新执行
    try:
        result = subprocess.run(
            ["conda", "run", "-n", CONDA_ENV_NAME, "python", __file__] + sys.argv[1:],
            check=True,
            capture_output=False
        )
        sys.exit(result.returncode)
    except FileNotFoundError:
        print(f"❌ 未找到 conda 命令，请确保 conda 已安装并可用")
        print(f"   请手动激活环境: conda activate {CONDA_ENV_NAME}")
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ 在 conda 环境中运行失败: {e}")
        return False


def get_conda_python():
    """获取 conda 环境的 Python 解释器路径"""
    try:
        result = subprocess.run(
            ["conda", "run", "-n", CONDA_ENV_NAME, "which", "python"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


class TestResult:
    """测试结果数据类"""

    def __init__(self, name: str, passed: bool, message: str = "",
                 duration: float = 0.0, data: Dict = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.duration = duration
        self.data = data or {}
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "duration": self.duration,
            "timestamp": self.timestamp,
            "data": self.data
        }


class TestSuite:
    """测试套件基类"""

    name = "base_suite"
    description = "基础测试套件"

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.results: List[TestResult] = []

    async def setup(self):
        """测试前准备"""
        pass

    async def teardown(self):
        """测试后清理"""
        pass

    async def run(self) -> List[TestResult]:
        """运行测试套件"""
        raise NotImplementedError


class SynthesisSuite(TestSuite):
    """合成模块测试套件"""

    name = "synthesis"
    description = "测试数据合成流水线"

    async def run(self) -> List[TestResult]:
        results = []

        # 测试配置加载
        start = time.time()
        try:
            from synthesis.core import SynthesisConfig
            config = SynthesisConfig.from_json(
                self.config.get("synthesis_config", "configs/synthesis/grpo_100k_config.json")
            )
            results.append(TestResult(
                name="config_load",
                passed=True,
                message="配置加载成功",
                duration=time.time() - start
            ))
        except Exception as e:
            results.append(TestResult(
                name="config_load",
                passed=False,
                message=f"配置加载失败: {e}",
                duration=time.time() - start
            ))

        return results


class SandboxSuite(TestSuite):
    """沙盒模块测试套件"""

    name = "sandbox"
    description = "测试沙盒环境和工具调用"

    async def run(self) -> List[TestResult]:
        results = []

        # 测试沙盒连接
        start = time.time()
        try:
            from sandbox import HTTPServiceClient
            async with HTTPServiceClient(
                base_url=self.config.get("sandbox_url", "http://127.0.0.1:8080")
            ) as client:
                sessions = await client.list_sessions()
                results.append(TestResult(
                    name="sandbox_connect",
                    passed=True,
                    message=f"沙盒连接成功，当前会话: {len(sessions)}",
                    duration=time.time() - start
                ))
        except Exception as e:
            results.append(TestResult(
                name="sandbox_connect",
                passed=False,
                message=f"沙盒连接失败: {e}",
                duration=time.time() - start
            ))

        return results


class RolloutSuite(TestSuite):
    """Rollout 模块测试套件"""

    name = "rollout"
    description = "测试基准评估流水线"

    async def run(self) -> List[TestResult]:
        results = []

        # 测试配置加载
        start = time.time()
        try:
            from rollout.core import RolloutConfig
            # 这里可以添加具体的 rollout 测试
            results.append(TestResult(
                name="rollout_config",
                passed=True,
                message="Rollout 配置测试通过",
                duration=time.time() - start
            ))
        except Exception as e:
            results.append(TestResult(
                name="rollout_config",
                passed=False,
                message=f"Rollout 测试失败: {e}",
                duration=time.time() - start
            ))

        return results


class HarnessRunner:
    """Harness 测试运行器"""

    SUITES = {
        "synthesis": SynthesisSuite,
        "sandbox": SandboxSuite,
        "rollout": RolloutSuite,
    }

    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.results_dir = Path("harness/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """加载配置文件"""
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    async def run_suite(self, suite_name: str) -> List[TestResult]:
        """运行单个测试套件"""
        if suite_name not in self.SUITES:
            print(f"❌ 未知测试套件: {suite_name}")
            return []

        suite_class = self.SUITES[suite_name]
        suite = suite_class(self.config)

        print(f"\n{'='*60}")
        print(f"🧪 运行测试套件: {suite.name}")
        print(f"   {suite.description}")
        print(f"{'='*60}")

        await suite.setup()
        try:
            results = await suite.run()
        finally:
            await suite.teardown()

        return results

    async def run_all(self) -> Dict[str, List[TestResult]]:
        """运行所有测试套件"""
        all_results = {}

        for suite_name in self.SUITES.keys():
            results = await self.run_suite(suite_name)
            all_results[suite_name] = results

        return all_results

    def save_results(self, results: Dict[str, List[TestResult]]):
        """保存测试结果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_file = self.results_dir / f"harness_results_{timestamp}.json"

        output = {
            "timestamp": datetime.now().isoformat(),
            "suites": {
                name: [r.to_dict() for r in suite_results]
                for name, suite_results in results.items()
            }
        }

        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n💾 测试结果已保存: {result_file}")

    def print_summary(self, results: Dict[str, List[TestResult]]):
        """打印测试摘要"""
        print(f"\n{'='*60}")
        print("📊 测试摘要")
        print(f"{'='*60}")

        total_tests = 0
        total_passed = 0

        for suite_name, suite_results in results.items():
            passed = sum(1 for r in suite_results if r.passed)
            failed = len(suite_results) - passed
            total_tests += len(suite_results)
            total_passed += passed

            status = "✅" if failed == 0 else "❌"
            print(f"{status} {suite_name}: {passed}/{len(suite_results)} 通过")

            for result in suite_results:
                icon = "✅" if result.passed else "❌"
                print(f"   {icon} {result.name}: {result.message}")

        print(f"\n总计: {total_passed}/{total_tests} 通过 "
              f"({100*total_passed/total_tests:.1f}%)")


async def main():
    # 首先检查 conda 环境
    if not ensure_conda_env():
        print(f"❌ 请在 conda '{CONDA_ENV_NAME}' 环境中运行此脚本")
        print(f"   手动激活命令: conda activate {CONDA_ENV_NAME}")
        return 1

    parser = argparse.ArgumentParser(description="Claude Harness - AgentFlow 测试框架")
    parser.add_argument("--suite", type=str, default="all",
                       choices=["all", "synthesis", "sandbox", "rollout"],
                       help="要运行的测试套件")
    parser.add_argument("--config", type=str, default=None,
                       help="配置文件路径")
    parser.add_argument("--format", type=str, default="console",
                       choices=["console", "json", "junit"],
                       help="输出格式")

    args = parser.parse_args()

    runner = HarnessRunner(args.config)

    if args.suite == "all":
        results = await runner.run_all()
    else:
        suite_results = await runner.run_suite(args.suite)
        results = {args.suite: suite_results}

    runner.print_summary(results)
    runner.save_results(results)

    # 如果有失败的测试，返回非零退出码
    for suite_results in results.values():
        for result in suite_results:
            if not result.passed:
                return 1
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
