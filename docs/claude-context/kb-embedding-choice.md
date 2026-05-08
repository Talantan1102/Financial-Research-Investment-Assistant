---
name: KB Embedding 模型选型 — qwen text-embedding-v3 主力，BGE-M3 留 v0.9
description: EmbeddingService Protocol + EMBEDDING_MODE switch；qwen 1024 维 / BGE-M3 1024 维同维互换不需重建 collection
type: project
---

# Embedding 选型

文件：`backend/app/services/embedding_service.py` + `embedding_factory.py`

## 当前实现

| backend | mode 值 | 维度 | 模型 | 状态 |
|---|---|---|---|---|
| **QwenEmbeddingService** | `EMBEDDING_MODE=qwen`（default） | **1024** | `text-embedding-v3`（dashscope） | ✅ v0.7 已落 |
| BGEEmbeddingService | `EMBEDDING_MODE=bge_local` | 1024 | `BAAI/bge-m3` | 🚧 stub，调用即 raise，留 v0.9 真实现 |

调度由 `build_embedding_service_from_env()` 读 `EMBEDDING_MODE` 决定（factory 模式第 5 次复用）。

## 关键技术细节（踩过的坑）

- **batch size = 10**，不是文档说的 25。Spike 5 实测 11+ 被 dashscope API 拒（`embedding_service.py:14` 注释）。`embed()` 内部自动切批。
- **`dashscope.base_http_api_url` 不要随便覆盖**：`.env` 的 `DASHSCOPE_BASE_URL` 是 OpenAI compatible-mode endpoint（给 LLMService 走 openai SDK 用），dashscope SDK `TextEmbedding.call` 用 native API，覆盖成 compatible-mode URL 会 404。代码里只在 `"compatible-mode" not in base_url` 时才覆盖。
- **同维 1024 是 v0.9 切 BGE-M3 的意外利好**：qwen v3 维度可选 {64,128,256,512,768,1024}（Spike 5 实测 1536 被拒），BGE-M3 默认 1024 → 切 backend **不需要 drop & recreate Milvus collection**，只需 reingest 重算 vector。

## 为什么选 qwen v3（v0.7 阶段决策）

依据：`docs/superpowers/specs/2026-05-02-v0.7-kb-search-milvus-design.md` § 6

候选评估（中文金融场景）：
| 候选 | 维度 | 取舍 |
|---|---|---|
| **qwen-embedding-v3 API**（选） | 1024 | ✅ 复用 `DASHSCOPE_API_KEY` + LLMService reliability(RateLimiter/CostBudget) |
| BGE-M3 本地 | 1024 | ⚠️ 需 GPU 服务，v0.7 scope 不做，留 v0.9 + hybrid retrieval |
| m3e-large 本地 | 1024 | 已被 BGE 取代 |
| OpenAI text-embedding-3 | 3072/可降 | ❌ 跨 vendor，丢失 dashscope reliability 复用 |
| bge-large-zh 本地 | 1024 | 已被 BGE-M3 取代 |

**核心动机**：embedding call 走 LLMService → 自动复用 v0.6 reliability 4 件套（RateLimiter / CostBudget / retry / sanitize）—— 这是 v0.6 reliability 沉淀真正用上的关键故事点。

## 模型选型评估维度（面试可讲）

1. **同 vendor 复用**：减少凭证管理 + 复用 reliability 层
2. **中文金融语料表现**：qwen / BGE-M3 在 C-MTEB 榜单中文金融子集都强；OpenAI 多语言但中文不专项
3. **维度 vs Milvus collection 锁定**：维度是 collection schema 的硬约束，换 backend 必须维度对齐才能 in-place 切换
4. **本地 vs API**：API 简单、贵 + 有限流；本地需 GPU 但延迟稳、可微调
5. **是否支持 hybrid（dense+sparse）**：BGE-M3 原生支持 dense+sparse+multi-vector → v0.9 hybrid retrieval 价值点

## How to apply

- 切 backend：改 `.env` 的 `EMBEDDING_MODE`，**不要**直接 new 类
- 加新 backend（比如真接 BGE-M3）：在 `embedding_service.py` 写新类，在 `embedding_factory.py` 加 if 分支
- 维度变了：必须 drop & recreate 全部 3 个 Milvus collection（`kb_research / kb_financial / kb_policy`）+ reingest，**没有平滑迁移路径**
- chunk-embedding 重复调用走 `.embedding_cache.sqlite` 缓存（key = sha256(chunk_text + model + dim)），开发期反复 ingest 命中率 ~80%

## 评估点（待补）

仓库当前**没有** embedding 模型对比的离线评估。要评估应建立：
- **同一 query 集在 qwen vs BGE-M3 下 recall@k 对比**（需要 ground-truth chunk 标注）
- **embedding 召回 vs LLM judge 答案正确率**的相关性曲线 —— 验证 embedding 质量真的影响最终答案
- **batch latency / cost**：1k chunks ingest 总耗时与 ¥
- v0.7 spec 估算：13 docs 全量 ingest ≈ ¥0.14-0.35（400-1000 chunks × 500 tokens × ¥0.0007/1k）
