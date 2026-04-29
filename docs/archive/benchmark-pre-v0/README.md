> **⚠️ DEPRECATED — archived 2026-04-30**
>
> This benchmark suite (162 cases: phase1 single-tool 134 + phase2 complex 28)
> was the pre-v0 evaluation system, used to test the legacy `mcp_server/skills/`
> architecture. The v0 chat main path supersedes this.
>
> **Active eval system is at:** [`backend/tests/eval/`](../../../backend/tests/eval/)
> **Eval design spec:** [`docs/superpowers/specs/2026-04-29-dev-test-loop-design.md` § 8](../../superpowers/specs/2026-04-29-dev-test-loop-design.md)
>
> This archive is kept as historical reference and may inform new eval cases,
> but its `run_benchmark.py` and `evaluator.py` scripts are not maintained.

---

# Benchmark 测试用例集

金融研投助手 MCP Server 的端到端测试用例集，用于评估 LLM 的工具调用能力。

## 目录结构

```
benchmark/
├── README.md                      # 本文件
├── TOOL_DEPENDENCY_GRAPH.md       # 工具依赖图谱
├── phase1_single_tool_calls.jsonl # Phase 1: 单工具调用测试 (134个用例)
├── phase2_complex_scenarios.jsonl # Phase 2+: 复杂场景测试 (28个用例)
├── run_benchmark.py               # Benchmark 运行脚本
├── evaluator.py                   # 评估器
├── evaluation_rules.py            # 评估规则
├── functional_checker.py          # 功能检查器
├── validate_tools.py              # 工具验证脚本
├── test_control_flow.py           # 控制流测试
├── test_evaluator_quick.py        # 快速评估测试
├── test_llm_control_flow.py       # LLM 控制流测试
├── benchmark_qwen-max_*.json      # 测试结果示例
├── v2/                            # V2 版本测试框架
│   ├── conftest.py
│   ├── testdata/
│   └── unit/
└── archive/                       # 归档文件
    ├── BENCHMARK_IMPROVEMENT_PLAN.md
    ├── BENCHMARK_V2_PLAN.md
    ├── PHASE1_REPORT.md
    └── phase1_improve.py
```

## 核心文件说明

### 工具依赖图谱

| 文件 | 说明 |
|------|------|
| `TOOL_DEPENDENCY_GRAPH.md` | 定义 43 个工具的输入输出依赖关系，用于构建工具链测试 |

**包含内容**:
- 工具输入输出定义 (7个Skill, 43个工具)
- 高频工具链依赖图谱 (12个典型工具链)
- 输入依赖矩阵
- 测试工具链设计 (L1/L2/L3三级)
- 数据流转示例
- 测试股票推荐列表

### 测试用例文件

| 文件 | 用例数 | 说明 |
|------|--------|------|
| `phase1_single_tool_calls.jsonl` | 134 | Phase 1: 单工具调用测试（43工具 × 3场景 + 5 NO-SKILL） |
| `phase2_complex_scenarios.jsonl` | 28 | Phase 2+: 多工具协作、控制流、错误处理、边界情况 |

### 评估与运行脚本

| 文件 | 说明 |
|------|------|
| `run_benchmark.py` | 运行完整 benchmark (支持 Phase 1 和 Phase 2+) |
| `evaluator.py` | 评估器核心模块 |
| `evaluation_rules.py` | 评估规则定义 |
| `functional_checker.py` | 功能等价性检查 |

### 测试脚本

| 文件 | 说明 |
|------|------|
| `test_control_flow.py` | 控制流场景测试 |
| `test_evaluator_quick.py` | 快速评估测试 |
| `test_llm_control_flow.py` | LLM 控制流调用测试 |

### V2 测试框架

`v2/` 目录包含基于 pytest 的测试框架：
- `conftest.py`: 测试配置
- `testdata/`: 测试数据
- `unit/`: 单元测试（按 Skill 组织）

## Phase 1: 单工具调用测试

**文件**: `phase1_single_tool_calls.jsonl`

**目标**: 验证 LLM 能否正确选择单个 Skill 和工具，并传递正确参数

**设计理念**: 每种工具设计 **3 种不同场景**，增强 benchmark 的稳定性
- 基础场景：直接查询
- 参数场景：带特定参数（时间、条件等）
- 变体场景：不同表述方式

**覆盖范围**:
- ✅ **43 个工具** × **3 场景** = **129 个单工具调用用例**
- ✅ **5 个 NO-SKILL 场景**（问候、闲聊、无关问题等）
- ✅ **总计 134 个用例**

### 按 Skill 统计

| Skill | 工具数 | 用例数 |
|-------|--------|--------|
| market_data | 11 | 33 |
| financial_analysis | 7 | 21 |
| sector_analysis | 7 | 21 |
| risk_assessment | 5 | 15 |
| web_research | 4 | 12 |
| data_analysis | 6 | 18 |
| deep_research | 3 | 9 |
| **NO-SKILL** | - | 5 |
| **总计** | **43** | **134** |

### 用例编号规则

- `MD-xxx`: market_data (MD-001 ~ MD-011, MD-001-A/B ~ MD-011-A/B)
- `FA-xxx`: financial_analysis (FA-001 ~ FA-007, FA-001-A/B ~ FA-007-A/B)
- `SA-xxx`: sector_analysis (SA-001 ~ SA-007, SA-001-A/B ~ SA-007-A/B)
- `RA-xxx`: risk_assessment (RA-001 ~ RA-005, RA-001-A/B ~ RA-005-A/B)
- `WR-xxx`: web_research (WR-001 ~ WR-004, WR-001-A/B ~ WR-004-A/B)
- `DA-xxx`: data_analysis (DA-001 ~ DA-006, DA-001-A/B ~ DA-006-A/B)
- `DR-xxx`: deep_research (DR-001 ~ DR-003, DR-001-A/B ~ DR-003-A/B)
- `NO-SKILL-xxx`: 不调用工具场景 (NO-SKILL-001 ~ NO-SKILL-005)

### 示例：一个工具的 3 种场景

以 `get_quote` 为例：

| 用例ID | 查询 | 场景类型 |
|--------|------|----------|
| MD-001 | "茅台现在股价多少？" | 基础场景 |
| MD-001-A | "000858今天多少钱一股？" | 代码查询 |
| MD-001-B | "贵州茅台的实时行情" | 名称变体 |

## Phase 2+: 复杂场景测试

**文件**: `phase2_complex_scenarios.jsonl`

**目标**: 验证 LLM 在多工具协作、控制流、错误处理等复杂场景下的表现

**覆盖范围** (28个):

| 类别 | 用例数 | 说明 |
|------|--------|------|
| 多 Skill 协作 | 5个 | MULTI-001 ~ MULTI-005 |
| 控制流测试 | 11个 | FOREACH, WHILE, IFELSE, SWITCH, FILTER, COMPLEX |
| 错误处理 | 4个 | ERROR-001 ~ ERROR-003, ERROR-005 |
| 边界情况 | 5个 | EDGE-001 ~ EDGE-005 |

### 控制流测试详情

- **FOREACH**: 3个 (批量查询股票、行业估值对比、批量财务分析)
- **WHILE**: 2个 (循环查找低估值股票、查找热门板块)
- **IFELSE**: 2个 (PE判断条件分支、风险等级判断)
- **SWITCH**: 1个 (行业类型分支处理)
- **FILTER**: 2个 (筛选涨幅行业、复合条件筛选)
- **COMPLEX**: 3个 (嵌套控制流组合)

## 用例字段说明

```json
{
  "id": "MD-001",                    // 用例唯一标识
  "query": "茅台现在股价多少？",      // 用户查询
  "expected_skill": "market_data",   // 预期调用的 Skill
  "expected_tools": ["get_quote"],   // 预期调用的工具列表
  "complexity": "simple",            // 复杂度: simple/medium/high
  "evaluation_criteria": "..."       // 评估标准
}
```

## 使用方式

### 运行 Phase 1 测试 (单工具调用)
```bash
# 评估所有 Phase 1 测试用例 (134个)
python benchmark/run_benchmark.py --test-file phase1_single_tool_calls.jsonl

# 指定模型
python benchmark/run_benchmark.py --test-file phase1_single_tool_calls.jsonl --model qwen-max

# 限制测试数量 (快速验证)
python benchmark/run_benchmark.py --test-file phase1_single_tool_calls.jsonl --max-tests 50
```

### 运行 Phase 2+ 测试 (复杂场景)
```bash
# 评估复杂场景测试用例 (28个)
python benchmark/run_benchmark.py

# 指定模型和提供商
python benchmark/run_benchmark.py --model qwen-max --provider dashscope
```

### 评估指标
- **Skill 选择准确率**: 是否正确选择 expected_skill
- **工具选择准确率**: 是否正确选择 expected_tools
- **参数准确率**: 是否正确提取参数
- **NO-SKILL 识别率**: 是否正确识别不调用工具的场景
- **场景覆盖率**: 每个工具的 3 个场景是否都能正确处理

### 工具反馈信息
`run_benchmark.py` 现在会在报告中展示每个测试用例的**工具调用详细信息**，包括：
- 工具名称和参数（输入）
- 工具返回结果（输出）
- 失败测试的详细分析（在报告末尾）

这有助于分析模型响应的原因，例如：
- 工具是否被正确调用
- 工具返回的数据是否正确
- 模型基于什么数据生成了回答

## 测试用例生成规则

为确保 benchmark 的稳定性，每种工具设计 3 种场景：

1. **基础场景**: 最直接的查询方式
   - 例: "茅台现在股价多少？"

2. **参数场景**: 带特定参数（股票代码、时间、条件等）
   - 例: "000858今天多少钱一股？"

3. **变体场景**: 不同表述方式或关注点
   - 例: "贵州茅台的实时行情"

## 统计汇总

| 类别 | 用例数 |
|------|--------|
| Phase 1 单工具调用 | 129 |
| Phase 1 NO-SKILL | 5 |
| Phase 2+ 复杂场景 | 28 |
| **总计** | **162** |
