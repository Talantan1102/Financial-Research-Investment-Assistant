---
name: KB 切块策略 — 类型路由 + 中文金融定制
description: v0.7 KB 摄取链路按语料类型分发到 3 套 chunker(研报 semantic / 财报 section / 政策 clause),关键参数与设计动机
type: project
---

# 切块策略 = 按 corpus 形态路由 (`backend/app/kb/chunkers/`)

按语料类型分 3 套 chunker，由 `router.py:16-32` 通过 `source_type` 分发：

| source_type | chunker | 形态依据 |
|---|---|---|
| `research`(研报) | `SemanticChunkerForResearch` | 连续叙述，段落边界靠语义判断 |
| `financial`(财报) | `SectionChunkerForFinancial` | MinerU 已识别明确章节，表格多 |
| `policy`(政策) | `ClauseChunkerForPolicy` | 天然条款边界（"第X条"） |

## 共享参数（spec 锁死，影响 reingest）

- `chunk_size_max = 800 tokens`（financial / research 共用上限）
- `RecursiveCharacterTextSplitter`: `chunk_size=600 chars` ≈ 800 tokens（中文 1.33 tokens/char），`overlap=50 chars`
- 中文 separators: `["\n\n", "。", "\n", "?", "!", ";", " ", ""]` —— 替换 LangChain 默认英文 `.\n\n`
- token 计数走 `tiktoken cl100k_base`（qwen tokenizer 的近似，误差 ±20%，base.py:35）

## 1. SemanticChunkerForResearch（研报）

**算法**（`semantic.py:31-78`）：
1. MinerU section 内按中文句末标点 `[。!?]` 拆 sentences
2. < 5 句的 section 直接合并成 1 chunk（不做语义切）
3. ≥ 5 句：调 `EmbeddingService.embed(sentences)` 拿每句向量
4. 算相邻句 cosine **distance**（1 - similarity）
5. distance > `breakpoint_threshold = 0.4` 处切边界
6. 后处理：超 800 tokens 的 chunk 用 RecursiveSplitter 强制切

**为什么不用 LangChain SemanticChunker**：避免 LangChain 全家桶依赖，自己实现 ~50 行 numpy-free 余弦距离。

**threshold = 0.4 是初值**，spec 标注"Spike 后调"（实际未在代码里看到自动调优逻辑）—— **这是评估点 #1**。

## 2. SectionChunkerForFinancial（财报）

**算法**（`section.py:31-74`）：
1. 每个 MinerU section 直接当 chunk（≤ 800 tokens 时）
2. 超 800 tokens → 走 `RecursiveCharacterTextSplitter(chunk_size=600, overlap=50, 中文 separators)`
3. **每个 table 独立成 chunk**（HTML → markdown，避免被 splitter 切碎），`is_table=True` + `extra={"section_index": ...}` 标记

**关键决策**：财报表格不进 splitter —— 表格信息密度高，被切碎会丢上下文。

## 3. ClauseChunkerForPolicy（政策）

**算法**（`clause.py:13-46`）：
1. 拼接所有 sections（政策 corpus 的 section 边界不重要，条款边界才重要）
2. 用 lookahead regex 切：`第[一二三四五六七八九十百千零0-9]+条/款` + `\n\d+\.\d+\s`
3. 每条独立 chunk，**无 overlap，无大小下限**（短条款 < 500 tokens 也保留）

**为什么不用 SemanticChunker**：天然边界已存在，语义切是 over-engineering 且贵（每句 1 次 embed）。

## Why（设计动机）

按 corpus 内容形态选最合适策略 = senior 信号。
- 全统一 fixed-size = demo 形态
- 全 SemanticChunker = 政策上 over-engineering + 贵
- 全 LLM-judge propositional = 每段 1 次 LLM call，成本不可控

## How to apply

- 加新语料类型：在 `chunkers/router.py` 加 case + 写新 chunker 子类继承 `Chunker` ABC
- 改 `chunk_size_max` / `threshold` 是 **breaking change** —— 所有已 ingest 的 chunk 边界都会变，必须 drop & reingest Milvus collection
- 不要改 `tiktoken cl100k_base` —— 它是 qwen tokenizer 的近似，换 encoder 会让历史 chunk 的 tokens 字段失真

## 评估点（待补的工程）

仓库当前**没有**针对 chunking 质量的独立评估通路。`backend/tests/eval/` 是 LLM-as-Judge 的端到端 agent eval（golden_set_v0.jsonl），不直接测 chunk 边界质量。
要评估 chunking 应建立的指标（v0.8 检索调优 spec 涉及）：
- **检索 recall@k**：固定 query 集 → 看 ground-truth chunk 是否在 top-k
- **chunk 完整性**：人工/LLM 判断 chunk 是否切碎了关键信息（表格/数字/语义）
- **threshold 网格搜索**：semantic chunker 的 `breakpoint_threshold` ∈ {0.3, 0.4, 0.5, 0.6} 看 recall 曲线
- **chunk size 分布**：tokens 直方图看是否有大量 < 100 或 > 800 outlier

参考 spec：`docs/superpowers/specs/2026-05-02-v0.7-kb-search-milvus-design.md` § 9
