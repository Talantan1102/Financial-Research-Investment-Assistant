# Skill 分层设计

本项目的 7 个 skill 不是按"数据源/API 分组",而是模仿卖方研究员的**工作链**分层。每层回答不同阶段的问题,层间依赖单向向下,层内正交。

## 四层架构

```
┌─────────────────────────────────────────────────────────────┐
│  L4 综合产出层  "怎么办 / 买不买 / 可投资性"                   │
│  └─ deep-research            (3 tools, orchestrator)        │
├─────────────────────────────────────────────────────────────┤
│  L3 评估决策层  "好不好 / 风险多大 / 对比如何"                 │
│  ├─ risk-assessment          (5 tools, 个股诊断)             │
│  └─ sector-analysis          (7 tools, 同业对标)             │
├─────────────────────────────────────────────────────────────┤
│  L2 分析计算层  "多少 / 怎么变 / 什么信号"                    │
│  ├─ financial-analysis       (7 tools, 财报 + 比率)          │
│  └─ data-analysis            (6 tools, 量价 + 统计)          │
├─────────────────────────────────────────────────────────────┤
│  L1 数据采集层  "是什么 / 有什么"                             │
│  ├─ market-data              (11 tools, 行情/资金/估值)      │
│  └─ web-research             (4 tools, 新闻/公告/研报)       │
└─────────────────────────────────────────────────────────────┘
```

## 分层的三个理由

### 1. 能力边界清晰,用户意图天然映射

| 用户问法示例 | 匹配层 | 主导 skill |
|---|---|---|
| "茅台多少钱" / "北向资金今天流入多少" | L1 | market-data |
| "茅台最近有什么新闻" | L1 | web-research |
| "茅台的 ROE 趋势" / "茅台和五粮液相关性" | L2 | financial/data-analysis |
| "茅台估值贵不贵" / "茅台风险多大" | L3 | risk-assessment |
| "白酒行业龙头" / "银行 vs 保险" | L3 | sector-analysis |
| "帮我深度分析茅台" / "生成研报" | L4 | deep-research |

模型做意图识别时,先定"回答这个问题需要到哪一层",再在层内选 skill,决策复杂度从 `O(7)` 降到 `O(2)` 级。

### 2. 依赖方向单向,避免循环调用

- **上层可调用下层**,反之不行。L4 的 deep-research 会编排 L1-L3;L3 的 risk-assessment 会调用 L1 的 market-data 和 L2 的 financial-analysis,但 L1 绝不反调 L3。
- 新增能力只改对应层:新数据源 → L1;新指标 → L2;新风险维度 → L3;新报告模板 → L4。其它层零改动。

### 3. LLM 规划友好,避免"一锅炖"

扁平 7 skill × 43 工具的排列组合 = 巨大搜索空间。分层后模型"先定层,再选工具",类似 LangGraph 的 hierarchical agent。配合 deep-research 作为显式 orchestrator,深度研究任务不会退化成"挨个调工具"的堆叠模式。

## skill 间调用规则

- **L4 → L1/L2/L3**:`deep-research` 通过 orchestration 显式调度
- **L3 → L1 + L2**:`risk-assessment` 综合估值(L1)+ 财务(L2)+ 波动(L2)打分
- **L3 ↔ L3** 允许:`sector-analysis` 的行业均值可作为 `risk-assessment` 的对标基线
- **L2 → L1**:`data-analysis` 的技术指标基于 L1 的 K 线;`financial-analysis` 的比率基于 L1 的财报原始字段
- **L1 ↔ L1** 禁止:`market-data` 和 `web-research` 数据源不同,无依赖
- **同层互调** 需要理由:若 `financial-analysis` 频繁调用 `data-analysis`,应考虑把共用逻辑下沉为 L2 内部工具

## 与官方规范的对齐

- 每个 skill 一个 kebab-case 目录,内含 `SKILL.md`(入口)+ `references/*.md`(progressive disclosure)
- `SKILL.md` frontmatter 只保留官方承认的 `name` + `description`;删除历史遗留的 `version`、`tool_count`
- `SKILL.md` 主体保持精简(~70 行),模型按需 Read `references/tools.md` 取参数详情,节省 context window
- 详细参数/示例/工作流存放于 `references/`,避免每次对话都塞入 1 万字符

## 从历史版本迁移的变化

| 原(`backend/claude_skills/`) | 新(`.claude/skills/`) | 变化 |
|---|---|---|
| `market_data/SKILL.md` | `market-data/SKILL.md` + `references/tools.md` | 拆分 + 改名 + 加层级标注 |
| ...(同上 7 个) | ...(同上 7 个) | 同上 |
| `market_data/SKILL.md.backup` | 删除 | 历史备份冗余 |

原 `backend/claude_skills/` 保留作为 MCP Server 内部资源(被 `backend/app/mcp_server/skills/base.py` 的 `get_skill_md()` 读取),Claude Code 原生加载认 `.claude/skills/`。
