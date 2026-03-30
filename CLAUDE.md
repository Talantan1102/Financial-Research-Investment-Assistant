# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AgentFlow is a unified agent data synthesis framework for generating high-quality training and evaluation data across heterogeneous agent environments (RAG, MM-Doc, Deep Research, GUI, Text2SQL, Data Analysis, Embodied Agents).

The framework follows a three-stage pipeline: **Trajectory Sampling → Trajectory Selection → QA Synthesis**.

## Project Structure

```
AgentFlow/
├── synthesis/           # Data synthesis pipeline (Trajectory Sampling → Selection → QA Synthesis)
│   ├── core/           # Core components: config, models, worker, sampler, selector, synthesizer
│   ├── api.py          # High-level API: load_config, load_seeds, synthesize
│   └── pipeline.py     # Main SynthesisPipeline class
├── rollout/            # Agent execution pipeline for benchmarks
│   ├── core/           # Core components: config, models, runner, evaluator
│   ├── api.py          # High-level API: rollout, quick_rollout
│   └── pipeline.py     # Main RolloutPipeline class
├── sandbox/            # HTTP sandbox service for tool execution
│   ├── server/         # HTTP server with modular backend design
│   │   ├── backends/   # Backend implementations (MCP Native, Resource-based, API Tools)
│   │   ├── core/       # ToolExecutor, ResourceRouter
│   │   └── app.py      # FastAPI application
│   ├── client.py       # HTTP client for sandbox interaction
│   ├── sandbox.py      # Sandbox facade
│   └── tool_schemas/   # Tool schema definitions for LLM prompts
└── configs/            # Configuration files
    ├── sandbox-server/ # Sandbox server configs (one per environment)
    └── synthesis/      # Synthesis configs (one per task type)
```

## Common Commands

### Installation

```bash
# Install core dependencies
bash install.sh

# With optional ML/DL dependencies (torch, transformers)
bash install.sh --ml

# Install everything including cloud dependencies
bash install.sh --all
```

### Running Tests

```bash
# Run all tests
pytest tests/

# Run a specific test file
pytest tests/test_finance_integration.py

# Run with verbose output
pytest tests/ -v
```

### Running the Sandbox Server

```bash
# Start sandbox server with a config
./start_sandbox_server.sh --config configs/sandbox-server/finance_research_config.json

# The server reads host/port from the config file's server.url and server.port
```

### Data Synthesis

```bash
# Run synthesis pipeline via Python API
python -c "
from synthesis import synthesize
synthesize(config_path='configs/synthesis/grpo_100k_config.json')
"

# Or run the pipeline directly
python synthesis/pipeline.py --config configs/synthesis/grpo_100k_config.json
```

### Benchmark Rollout

```bash
# Run rollout pipeline
python rollout/pipeline.py --config configs/rollout/example_config.json --data benchmark.jsonl

# Run specific tasks
python rollout/pipeline.py --config config.json --task-ids task1 task2 task3

# Run with limited tasks for testing
python rollout/pipeline.py --config config.json --max-tasks 10
```

## Architecture Overview

### Synthesis Pipeline (`synthesis/`)

The synthesis pipeline generates training data through three stages:

1. **TrajectorySampler** (`core/sampler.py`): An LLM-driven agent explores a sandbox environment starting from seed inputs, building a branching trajectory tree with concurrent expansion and action de-duplication.

2. **TrajectorySelector** (`core/selector.py`): All root-to-leaf paths are scored by depth, information richness, and tool diversity, then selected with configurable strategies.

3. **QASynthesizer** (`core/synthesizer.py`): For each selected path, the LLM generates multi-hop, factoid QA pairs grounded in collected observations.

Key classes:
- `SynthesisConfig` (`core/config.py`): Configuration dataclass with validation
- `SandboxWorker` (`core/worker.py`): Manages sandbox connection and tool execution
- `TrajectoryNode`, `Trajectory` (`core/models.py`): Data models for trajectories

### Rollout Pipeline (`rollout/`)

The rollout pipeline runs trained agents on benchmark tasks:

- `RolloutPipeline` (`pipeline.py`): Main orchestration class
- `AgentRunner` (`core/runner.py`): Executes agent on individual tasks
- `Evaluator` (`core/evaluator.py`): Evaluates results using various metrics (exact_match, f1_score, contains_answer, numeric_match, llm_judgement)

### Sandbox (`sandbox/`)

The sandbox provides isolated execution environments for tools:

**Server Architecture**:
- `HTTPServiceServer` (`server/`): FastAPI-based HTTP server
- `ToolExecutor` (`server/core/tool_executor.py`): Executes tool calls
- `ResourceRouter` (`server/core/resource_router.py`): Routes requests to backends

**Backend Types** (`server/backends/`):
1. **MCP Native Backend** (`mcp_native_base.py`): Native MCP Server implementation (e.g., FinanceResearch)
2. **Resource Backend** (`base.py`): Stateful backends requiring initialization (VM, RAG)
3. **API Tools** (`tools/`): Stateless lightweight tools (WebSearch)

**Client**:
- `HTTPServiceClient` (`client.py`): Async HTTP client for sandbox interaction
- `Sandbox` (`sandbox.py`): High-level facade with auto-start capability

## Configuration

### Synthesis Config (`SynthesisConfig`)

Key fields:
- `model_name`, `api_key`, `base_url`: LLM configuration
- `max_depth`, `branching_factor`: Trajectory sampling parameters
- `min_depth`, `max_selected_traj`: Trajectory selection parameters
- `available_tools`: List of allowed tools (e.g., `["unified_finance:*"]`)
- `resource_types`: Backend resource types to initialize
- `sandbox_server_url`, `sandbox_config_path`: Sandbox connection
- `sampling_tips`, `synthesis_tips`: Guidance prompts for LLM

### Rollout Config (`RolloutConfig`)

Key fields:
- `data_path`: Benchmark data file (jsonl format)
- `max_turns`: Maximum conversation turns per task
- `evaluation_metric`: Metric for evaluation
- `parallel`, `max_workers`: Parallel execution settings

### Sandbox Config

Sandbox server configs define available backends and their initialization parameters. Each backend type has different configuration requirements:

- MCP Native backends: Define `mcp_servers` with server configurations
- Resource backends: Define resource initialization configs
- API Tools: No initialization required

## Key Design Patterns

### Progressive Disclosure

The framework uses progressive disclosure for tool discovery (especially in MCP Native backends like Finance Research):

1. **Round 1**: `skill(name="market_data")` - Select a skill
2. **Round 2**: `get_skill_tools(name="market_data")` - Get available tools for the skill
3. **Round 3**: `execute_skill_tool(skill_name, tool_name, arguments)` - Execute specific tool

This reduces cognitive load on the LLM compared to exposing all tools at once.

### Seed Format

Seeds for synthesis are stored in JSONL format:
```jsonl
{"content": "贵州茅台股票投资分析", "kwargs": {"tags": {"topic": "stock_analysis", "symbol": "600519"}}}
```

### Tool Naming Convention

Tools follow the pattern `resource_type:tool_name` or for MCP native: `skill_name.tool_name`.

Examples:
- `unified_finance:skill`
- `web:search`
- `vm:screenshot`
- `market_data.get_quote` (MCP native)

## Important Notes

- The sandbox server must be running before starting synthesis or rollout (unless `sandbox_auto_start: true`)
- API keys can use environment variable syntax: `"${ENV_VAR:default_value}"`
- Trajectory results are saved incrementally during synthesis
- The framework uses async/await patterns throughout; use `asyncio.run()` for synchronous contexts
