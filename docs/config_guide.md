# Agent Flow 配置详解与推荐

## 1. 配置参数全览

### 1.1 模型配置 (Model)

| 参数 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `model_name` | string | ✅ | LLM 模型名称 | "qwen-max", "gpt-4o" |
| `api_key` | string | ✅ | API 密钥 | "sk-xxx" 或 "${ENV_VAR}" |
| `base_url` | string | ✅ | API 基础 URL | "https://dashscope..." |

### 1.2 输入输出配置 (I/O)

| 参数 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `seeds_file` | string | ✅ | Seed 文件路径 | "seeds/finance/test.jsonl" |
| `output_dir` | string | ✅ | 输出目录 | "results/finance" |
| `number_of_seed` | int | ❌ | 处理 Seed 数量上限 | 100（null=全部） |

### 1.3 轨迹采样配置 (Trajectory Sampling)

| 参数 | 类型 | 默认 | 说明 | 推荐值 |
|------|------|------|------|--------|
| `max_depth` | int | 5 | 最大探索深度 | **10-15**（金融）/ **50**（Web） |
| `branching_factor` | int | 2 | 每个节点分支数 | **2-3** |
| `depth_threshold` | int | 3 | 深度阈值（剪枝用） | **2** |
| `min_depth` | int | 2 | 最小有效深度 | **2-3** |
| `max_selected_traj` | int | 3 | 每 Seed 选多少条轨迹 | **2-3** |
| `path_similarity_threshold` | float | 0.7 | 路径相似度阈值 | **0.7** |

### 1.4 工具配置 (Tools)

| 参数 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `available_tools` | list | ✅ | 可用工具列表 | ["unified_finance:*"] |
| `resource_types` | list | ❌ | 资源类型 | ["unified_finance"] |
| `resource_init_configs` | dict | ❌ | 资源初始化配置 | {"unified_finance": {...}} |

### 1.5 沙盒配置 (Sandbox)

| 参数 | 类型 | 默认 | 说明 | 示例 |
|------|------|------|------|------|
| `sandbox_server_url` | string | "http://127.0.0.1:18890" | 沙盒服务地址 | 同上 |
| `sandbox_auto_start` | bool | true | 自动启动沙盒 | true/false |
| `sandbox_config_path` | string | ❌ | 沙盒配置文件 | "configs/sandbox/xxx.json" |
| `sandbox_timeout` | int | 120 | 沙盒超时（秒） | **120** |

### 1.6 提示配置 (Prompts)

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `sampling_tips` | string/list | Agent 探索指导 | "Round 1: 获取技能文档..." |
| `synthesis_tips` | string/list | QA 生成指导 | "生成与金融相关的问题..." |
| `seed_description` | string | Seed 描述 | "金融研究主题" |
| `qa_examples` | list | QA 示例 | [{"question": "...", "answer": "..."}] |

---

## 2. 场景推荐配置

### 场景 1：金融研究（我们的场景）

```json
{
  "model_name": "qwen-max",
  "api_key": "sk-946dc6cdc78b40829f826a0ca3fb7382",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",

  "max_depth": 10,
  "branching_factor": 2,
  "depth_threshold": 2,
  "min_depth": 2,
  "max_selected_traj": 2,
  "path_similarity_threshold": 0.7,

  "number_of_seed": 100,

  "resource_types": ["unified_finance"],
  "resource_init_configs": {
    "unified_finance": { "content": {} }
  },

  "sandbox_server_url": "http://127.0.0.1:18890",
  "sandbox_auto_start": true,
  "sandbox_config_path": "configs/sandbox-server/finance_research_config.json",
  "sandbox_timeout": 120,

  "available_tools": ["unified_finance:*"],
  "seed_description": "金融投资咨询问题",

  "sampling_tips": [
    "【重要】系统编排两轮流程:",
    "Round 1: 调用 skill(name='market_data') 选择合适的 Skill",
    "Round 2: 直接调用具体工具 (如 market_data.get_quote, market_data.search_stock)",
    "注意: 参数必须使用 ts_code 格式，如 '600519.SH'",
    "多轮查询，逐步深入，直到信息充分"
  ],

  "synthesis_tips": [
    "生成与金融投资相关的问题",
    "问题应该需要多轮工具调用才能回答",
    "答案要有具体数据支撑",
    "包含明确的分析结论和建议"
  ],

  "qa_examples": [
    {
      "question": "分析贵州茅台(600519)的投资价值",
      "answer": "贵州茅台当前股价1413.64元，ROE 26.37%，毛利率91.29%，财务状况优秀。"
    }
  ],

  "seeds_file": "seeds/finance_research/our_seeds.jsonl",
  "output_dir": "results/finance_research"
}
```

### 场景 2：Web 搜索（Deep Research）

```json
{
  "model_name": "openai/gpt-4o",
  "api_key": "${OPENAI_API_KEY}",
  "base_url": "https://api.openai.com/v1",

  "max_depth": 50,
  "branching_factor": 2,
  "depth_threshold": 2,
  "min_depth": 3,
  "max_selected_traj": 2,

  "available_tools": ["web-search", "web-visit"],

  "sampling_tips": [
    "深入探索构建多跳推理链",
    "使用 web-search 搜索信息",
    "使用 web-visit 访问具体页面提取证据",
    "建立依赖链 (A→B→C→D...)"
  ],

  "seeds_file": "seeds/web/seeds.jsonl",
  "output_dir": "results/web"
}
```

### 场景 3：RAG 问答

```json
{
  "model_name": "qwen-max",
  "api_key": "sk-xxx",
  "base_url": "https://dashscope...",

  "max_depth": 5,
  "branching_factor": 3,
  "min_depth": 2,
  "max_selected_traj": 3,

  "available_tools": ["retrieval:search", "retrieval:get_document"],
  "resource_types": ["knowledge_base"],

  "sampling_tips": [
    "使用 retrieval:search 搜索相关文档",
    "使用 retrieval:get_document 获取详细内容",
    "基于检索结果构建答案"
  ],

  "seeds_file": "seeds/rag/seeds.jsonl",
  "output_dir": "results/rag"
}
```

---

## 3. 关键参数调优指南

### max_depth（最大深度）

| 场景 | 推荐值 | 说明 |
|------|--------|------|
| 金融研究 | 10-15 | 需要多轮工具调用，但不能太深 |
| Web 搜索 | 30-50 | 需要深入浏览多个页面 |
| RAG 问答 | 5-10 | 检索+生成，不需要太深 |
| GUI 操作 | 20-30 | 需要多步操作 |

**⚠️ 注意**: max_depth 越大，耗时越长，成本越高

### branching_factor（分支因子）

| 场景 | 推荐值 | 说明 |
|------|--------|------|
| 简单任务 | 2 | 每个节点探索 2 个分支 |
| 复杂任务 | 3 | 每个节点探索 3 个分支 |

**⚠️ 注意**: 分支越多，并行度越高，但轨迹质量可能下降

### max_selected_traj（选择轨迹数）

| 场景 | 推荐值 | 说明 |
|------|--------|------|
| 快速验证 | 1 | 每 Seed 只选 1 条最优轨迹 |
| 标准生产 | 2-3 | 每 Seed 选 2-3 条高质量轨迹 |
| 数据增强 | 5+ | 生成更多样化数据 |

---

## 4. 常用配置模板

### 快速测试配置（10 Seed，快速验证）

```json
{
  "model_name": "qwen-turbo",
  "max_depth": 5,
  "branching_factor": 2,
  "max_selected_traj": 1,
  "number_of_seed": 10,
  "sandbox_timeout": 60
}
```

### 标准生产配置（100 Seed，平衡质量速度）

```json
{
  "model_name": "qwen-max",
  "max_depth": 10,
  "branching_factor": 2,
  "max_selected_traj": 2,
  "number_of_seed": 100,
  "sandbox_timeout": 120
}
```

### 高质量配置（少量 Seed，追求质量）

```json
{
  "model_name": "qwen-max",
  "max_depth": 15,
  "branching_factor": 3,
  "max_selected_traj": 3,
  "number_of_seed": 50,
  "sandbox_timeout": 180
}
```

---

## 5. 配置检查清单

运行前检查：

- [ ] `model_name` 和 `api_key` 正确
- [ ] `seeds_file` 文件存在且格式正确
- [ ] `output_dir` 目录可写
- [ ] `sandbox_server_url` 与沙盒配置一致
- [ ] `sandbox_config_path` 文件存在
- [ ] `available_tools` 与沙盒支持的工具匹配
- [ ] `max_depth` 和 `number_of_seed` 符合预期

---

**推荐直接使用我们创建的 `our_config.json`，它针对金融场景已经优化好了！**
