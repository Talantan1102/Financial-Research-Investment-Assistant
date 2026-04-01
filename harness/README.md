# Claude Harness 初始化指南

## 概述

Claude Harness 是 AgentFlow 的测试和评估框架，用于自动化测试、基准评估和性能分析。

## 快速开始

### 0. 环境准备

**使用 Conda 环境：**

```bash
# 激活 deepresearch 环境
conda activate deepresearch

# 验证环境
python --version
```

> **注意：** harness 运行时需要使用 `deepresearch` conda 环境，请确保已激活该环境。

### 1. 初始化 Harness 环境

```bash
# 创建 harness 工作目录
mkdir -p harness/{configs,results,reports}

# 初始化测试配置
cat > harness/configs/test_config.json << 'EOF'
{
  "test_suite": "default",
  "sandbox_config": "configs/sandbox-server/finance_research_config.json",
  "synthesis_config": "configs/synthesis/grpo_100k_config.json",
  "max_workers": 4,
  "timeout": 300,
  "save_trajectories": true
}
EOF
```

### 2. 运行 Harness 测试

```bash
# 运行全部测试
python harness/runner.py --suite all

# 运行特定模块测试
python harness/runner.py --module synthesis
python harness/runner.py --module sandbox
python harness/runner.py --module rollout

# 运行特定测试用例
python harness/runner.py --test test_finance_integration
```

## Harness 模块说明

### Test Runner (`harness/runner.py`)

测试执行引擎，支持并行测试和结果收集。

**功能：**
- 自动发现测试用例
- 并行执行测试
- 生成测试报告
- 对比历史结果

### Benchmark Harness (`harness/benchmark.py`)

基准测试框架，用于评估合成数据质量和模型性能。

**功能：**
- 加载基准数据集
- 执行批量评估
- 计算指标（准确率、F1、EM等）
- 生成对比报告

### Sandbox Harness (`harness/sandbox_harness.py`)

沙盒环境测试工具。

**功能：**
- 测试后端可用性
- 验证工具调用
- 检查会话管理
- 性能压力测试

## 配置文件说明

### 测试套件配置 (`harness/configs/suite_*.json`)

```json
{
  "name": "金融研投测试套件",
  "description": "测试金融研投助手的功能完整性",
  "tests": [
    {
      "name": "skill_discovery",
      "type": "mcp_native",
      "backend": "unified_finance",
      "steps": [
        {"action": "list_resources", "expected": "skills >= 7"},
        {"action": "read_resource", "params": {"uri": "skill://market_data"}},
        {"action": "list_tools"},
        {"action": "call_tool", "params": {"name": "market_data.get_quote", "arguments": {"ts_code": "600519"}}}
      ]
    }
  ]
}
```

### 基准配置 (`harness/configs/benchmark_*.json`)

```json
{
  "benchmark_name": "finance_qa",
  "data_path": "benchmarks/finance/test.jsonl",
  "metrics": ["exact_match", "f1_score", "contains_answer"],
  "evaluator": {
    "model": "qwen-max",
    "temperature": 0.0
  },
  "thresholds": {
    "exact_match": 0.6,
    "f1_score": 0.7
  }
}
```

## 常用命令

### 执行测试

```bash
# 单元测试
python -m pytest tests/ -v --tb=short

# 集成测试
python harness/runner.py --type integration

# 端到端测试
python harness/runner.py --type e2e --config harness/configs/e2e_config.json
```

### 性能测试

```bash
# 压力测试
python harness/stress_test.py --workers 10 --requests 100

# 并发测试
python harness/concurrent_test.py --max-concurrent 5
```

### 生成报告

```bash
# HTML 报告
python harness/report.py --format html --output reports/test_report.html

# JSON 报告
python harness/report.py --format json --output reports/test_report.json

# Markdown 报告
python harness/report.py --format markdown --output reports/test_report.md
```

## 目录结构

```
harness/
├── __init__.py
├── runner.py              # 测试执行器
├── benchmark.py           # 基准测试
├── sandbox_harness.py     # 沙盒测试
├── report.py              # 报告生成
├── stress_test.py         # 压力测试
├── configs/               # 测试配置
│   ├── suite_default.json
│   ├── suite_finance.json
│   ├── benchmark_qa.json
│   └── benchmark_rag.json
├── fixtures/              # 测试数据
│   ├── seeds/
│   ├── benchmarks/
│   └── expected/
├── results/               # 测试结果
│   ├── 2026-03-29/
│   └── latest/
└── reports/               # 测试报告
    ├── html/
    └── markdown/
```

## 扩展 Harness

### 添加自定义测试

```python
# harness/plugins/my_test.py
from harness.core import TestCase, TestResult

class MyCustomTest(TestCase):
    name = "my_custom_test"

    async def run(self, context) -> TestResult:
        # 执行测试逻辑
        result = await self.check_something()

        return TestResult(
            passed=result.success,
            message=result.message,
            data=result.data
        )
```

### 添加自定义指标

```python
# harness/metrics/custom_metric.py
from harness.metrics import Metric

class CustomMetric(Metric):
    name = "custom_score"

    def calculate(self, prediction, reference) -> float:
        # 计算自定义指标
        return similarity_score(prediction, reference)
```

## 最佳实践

1. **测试隔离**：每个测试用例应该独立运行，不依赖其他测试
2. **数据清理**：测试完成后清理临时数据
3. **超时设置**：为每个测试设置合理的超时时间
4. **重试机制**：对不稳定的外部调用添加重试
5. **结果对比**：定期对比历史测试结果，发现性能退化

## 故障排查

### 测试失败常见原因

| 问题 | 原因 | 解决方案 |
|-----|------|---------|
| Sandbox 连接失败 | 服务器未启动 | 检查 `./start_sandbox_server.sh` |
| 工具调用超时 | 网络延迟 | 增加 `timeout` 配置 |
| 结果不匹配 | 模型更新 | 更新预期结果或阈值 |
| 内存不足 | 并发过高 | 减少 `max_workers` |

## 集成 CI/CD

```yaml
# .github/workflows/harness.yml
name: Harness Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: bash install.sh
      - name: Run Harness
        run: python harness/runner.py --suite all --format junit
      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: test-results
          path: harness/results/
```
