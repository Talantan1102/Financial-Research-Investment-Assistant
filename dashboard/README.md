# Harness Board

把本项目(一个金融研究 Agent)按论文 **ETCLOVG**(*Agent Harness Engineering: A Survey*, Li et al. 2026)
七个工程维度逐条拆解展示的项目知识看板。Starlette + htmx + sqlite,可选 Milvus 相关推荐。

ETCLOVG = **E** 执行环境 · **T** 工具 · **C** 上下文 · **L** 生命周期 · **O** 可观测 · **V** 验证 · **G** 治理。

## 启动

```bash
make board        # = uv run --project backend python -m dashboard.server,起在 127.0.0.1:8910
make board-stop   # 停
make board-test   # 跑 dashboard/tests
```

启动时自动把 `data/deep_cards_seed.jsonl` seed 到 `../backend/data/board.db`(db 卡数 < seed 时 insert-if-missing)。

## 三个页面

- **`/`** — ETCLOVG 7 模块 Topology 关系图,点模块进维度页。
- **`/m/{dim}`** — 单维度全部 capability,三色状态(已实现/开发中/未开发);**单击 chip 就地展开** DeepCard(这是什么/为什么/取舍/踩坑/候选方案/代码锚点/关联),**右键改状态**。
- **`/story`** — 按 git commit-time 的三段式(问题/决策/结果)时间线。

## 数据真源(SSOT)

- `config/capabilities.yaml` — 87 个 capability + `derive_rule`(code_grep / file_exists / spec_section / memory_frontmatter / manual),自动判定本项目有没有该能力。
- `config/dimensions.yaml` — 7 维主泳道 + path 归类。
- `data/deep_cards_seed.jsonl` — hand-curated DeepCard 深读内容,server 启动时 insert-if-missing 入库。

改了代码 → `make board-refresh` 重扫,新写的能力会自动从"未开发"翻成"已实现"。
