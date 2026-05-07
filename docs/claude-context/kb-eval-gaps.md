---
name: KB 检索/切块/embedding 评估缺口
description: 当前仓库的 eval 通路只覆盖端到端 agent（LLM-as-Judge），KB 子系统缺独立评估。v0.8 检索调优 spec 是补这个缺口的位置
type: project
---

# 现状

`backend/tests/eval/` 是 **LLM-as-Judge 端到端 agent eval**：
- `eval_runner.py` 跑 GoldenCase → SUT → trace → Judge → EvalResult
- golden set: `backend/tests/fixtures/eval/golden_set_v0.jsonl`（含 v0-chat-001 等 case）
- 评的是 agent 输出文本对不对 / tool_calls 是否正确，**不评 chunk 边界 / embedding 召回**

# 缺口

KB 子系统的**离线指标评估**全部缺位：
1. **Chunking 质量**：semantic threshold 0.4 是不是最优？财报 800 token 上限是不是切得太碎？没人验
2. **Embedding 召回**：qwen v3 vs BGE-M3 谁更好？没 ground-truth 标注集
3. **检索 top_k / threshold 调参**：`KbSearchService.search` 暴露了这俩参数，但默认 top_k=5 / threshold=None 是拍的
4. **Reranker 收益**：v0.9 hybrid retrieval 计划接 reranker，没 baseline 不知道有没有用

# Why 这个缺口

v0.7 spec 显式把检索调优推到 v0.8：
> v0.7 不包括 ❌ 检索调优(top_k / threshold / reranker)→ v0.8（需要 nightly baseline）

工作量评估时的取舍 —— v0.7 已经塞了 Milvus 部署 + 3 个 Protocol + ingest 链路 + sample corpus 准备，再加调优会爆 scope。

# How to apply（要补这个缺口时的设计起点）

**评估通路应该长这样**（sketch，未实现）：
1. 准备 ground-truth：每条 query 标注哪个 chunk_id 是相关的（人工 / LLM 半自动）
2. 离线 metric：
   - `recall@k` / `mrr` / `ndcg@k` —— 标准 IR 指标
   - `chunk_oversize_rate` / `chunk_undersize_rate` —— chunk size 分布健康度
3. 实验脚本：`scripts/eval_kb_retrieval.py`，固定 query 集 × {chunker_config × embedding_config × top_k} 网格跑
4. 结果落 `tests/eval/results/kb_retrieval/`（已有 `.gitignore` 占位）

# 当前可立即做的低成本验证

不建评估通路也能做的 sanity check：
- `python -m app.scripts.ingest_kb` 后跑几个手写 query，肉眼看 top_k 是不是命中预期段
- 看 `.embedding_cache.sqlite` 命中率（开发期反复 ingest 应该 ~80%+）
- 看 chunk tokens 直方图：`SELECT tokens FROM ...` 是否大量 < 100 或卡 800 上限

# 项目作品故事点

按 `user_portfolio_target` 的标准，eval 通路本身就是 portfolio 故事 ——
"我评估了 chunker threshold 网格 / embedding A/B / top_k 曲线" 比 "我装了 Milvus" 显著强。
v0.8 要做这个时，重点放在**离线指标可重现** + **结果可视化**（比如 chunker × embedding × top_k 的 recall heatmap）。
