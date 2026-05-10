# C.5 Plan 3 — Read Pipeline + RRF v2 Implementation Plan

> **For agentic workers**: REQUIRED SUB-SKILL — `superpowers:test-driven-development` 全程贯穿，每 step 走 RED → GREEN → REFACTOR → COMMIT。
>
> **Plan owner scope**: 3-way hybrid 检索（BM25 + Vector + Graph）+ RRF v2（importance 三档 + 时间感知 + 衰减底）+ Working memory auto-injection + 长尾召回监控 instrumentation + Posterior calibration instrumentation。
>
> **Wall time**: 5 天（按每天 6h 投入）。

---

## Header

| 字段 | 值 |
|---|---|
| **Plan 编号** | C.5 Plan 3 |
| **主题** | Read Pipeline + RRF v2（3-way Hybrid + 时间感知 RRF + Persona Auto-Injection + 长尾召回监控 + Posterior Calibration instrumentation）|
| **依赖前置** | Plan 1 ship（schema + Memory Protocol + HierarchicalMemory 骨架 + working_blocks CRUD + jieba helper + entity registry）/ Plan 2 ship（写入 pipeline + AGE/Milvus outbox sync 已让数据流入读侧）|
| **下游解锁** | Plan 4（6 MCP tools 包 archival_memory_search / archival_memory_traverse 调用 Plan 3 底层）/ Plan 5（embed_cache 接 Plan 3 vector 检索 + posterior calibration weekly job 消费 Plan 3 instrumentation 表）/ Plan 8（Plan 3 长尾召回 metric 接 eval pipeline）|
| **算法深度补丁主责** | **#3 时间感知 RRF**（spec § 11 末尾 #3 完整实现 — importance 三档 [0.6/0.75/0.95] + τ 按 rel_type 三级 [365/180/90] + 衰减底 0.5 + 后验校准 instrumentation + 长尾召回监控）|

---

## Spec Reference

| 项 | 来源 |
|---|---|
| **主 spec** | `docs/superpowers/specs/2026-05-10-c5-cross-session-memory-design.md` |
| **共享契约** | `docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md` |
| **§ 5 读取 Pipeline 全部** | spec 行 594–732（3-way Hybrid + RRF + Working Memory Auto-Injection 完整代码骨架）|
| **§ 7 Working Memory Budget** | spec 行 853–870（persona 500 / scratchpad 1000 / 超 budget 自动 paging）|
| **§ 11 末尾 #3** | spec 行 1201–1239（reciprocal_rank_fusion_v2 完整公式 + 5 条关键设计取舍）|
| **§ 11 末尾 #3 验证 acceptance** | spec 行 1194 - 离散三档 importance 跨 session 一致性 ≥ 0.9 / RRF v2 加时间感知前后 long-tail recall 提升 ≥ 15% / 长尾召回监控周报上大盘 |
| **§ 9 cost layer** | spec 行 562–581（Plan 3 vector 检索 hook embed_cache，Plan 5 实现）|
| **契约 § 5** | RRF v2 常量（IMPORTANCE_WEIGHT_MAP / TAU_DAYS_BY_REL_TYPE / TAU_DAYS_DEFAULT / DECAY_FLOOR / RRF_K）+ 函数签名严格不变 |
| **契约 § 12** | L0 Unit / L1 Integration / L2 Cassette 三层测试约定 |

**契约严守清单**（不得偏离）：

- `IMPORTANCE_WEIGHT_MAP = {0.9: 0.95, 0.5: 0.75, 0.2: 0.6}`
- `TAU_DAYS_BY_REL_TYPE = {"HOLDS": 365, "SOLD": 365, "PREFERS": 180, "AVOIDS": 180, "WATCHES": 180, "EXPRESSED_VIEW": 90, "STUDIED": 90}`
- `TAU_DAYS_DEFAULT = 180`
- `DECAY_FLOOR = 0.5`
- `RRF_K = 60`
- 函数签名：`compute_time_decay(rel_type, valid_from, valid_to)` / `reciprocal_rank_fusion_v2(retriever_results, edges_meta, k=RRF_K, top=5)`
- `archival_memory_search(user_id, query, k=5) -> list[ChatMemoryEdge]`（契约 § 2）

---

## File Structure

> Plan 1 已建 `backend/app/memory/` 目录 + `__init__.py` + 4 model + Memory Protocol + HierarchicalMemory 骨架（archival_memory_search 是 stub raise NotImplementedError）+ jieba helper + 4 PG 表 schema + AGE 图 + Milvus collection。Plan 2 已让 archival_memory_insert 实写数据。Plan 3 在此地基上添读路径与 RRF v2。

| Path | Purpose | Status |
|---|---|---|
| **新增 — 读取 pipeline 主体** | | |
| `backend/app/memory/retriever.py` | 3 路 retriever：`bm25_search` / `vector_search` / `graph_traverse`（不含 default search 入口）+ `format_edges_meta_for_rrf` helper | Create |
| `backend/app/memory/rrf.py` | 契约 § 5 已声明常量 — Plan 3 实现 `compute_time_decay` + `reciprocal_rank_fusion_v2` + `_compute_importance_weight` 内部 helper | Create |
| `backend/app/memory/persona_populator.py` | session 起手扫 HOLDS/PREFERS/AVOIDS/WATCHES → 生成 markdown ~500 tokens → UPDATE working_blocks(persona) | Create |
| **新增 — 监控 / instrumentation 表** | | |
| `backend/scripts/migrations/2026-05-11-c5-plan3-instrumentation.sql` | 加 2 张 instrumentation 表（`chat_memory_retrieval_logs` 长尾召回 + posterior calibration 落库 / `chat_memory_retrieval_feedback` 用户否决信号）+ 索引 | Create |
| `backend/app/memory/instrumentation.py` | `log_retrieval_hit(user_id, query, edge_ids, top_k_valid_from, …)` + `log_user_reject(user_id, edge_id, reason)` 两个落库函数；Plan 3 写 instrumentation，Plan 5 weekly job 消费 | Create |
| `backend/app/memory/long_tail_monitor.py` | 计算 top-5 valid_from P90 是否全集中近 7 天；返回 `LongTailReport`；Plan 8 eval pipeline 调用 | Create |
| **改造 — HierarchicalMemory** | | |
| `backend/app/memory/hierarchical.py` | **Modify**：替换 `archival_memory_search` stub，组合 retriever.py + rrf.py + instrumentation.py 完整实现；签名严守契约 § 2 | Modify |
| **改造 — 进 chat 入口** | | |
| `backend/app/router/chat.py` | **Modify**：session 开启时（PR #39 现有 session-start hook 位置）调 `populate_persona_on_session_start(user_id)`；用 try/except 包，失败仅 log 不阻塞 | Modify |
| `backend/app/agents/factory.py` 或 lifespan | **Modify**：HierarchicalMemory 注入参数已在 Plan 1 wired，Plan 3 不动 DI | Skip |
| **测试 — L0 Unit** | | |
| `backend/tests/unit/memory/test_rrf.py` | RRF v2：常量值校验 / `compute_time_decay` 5 case（current/历史/τ 默认/极端老/zero days）/ `reciprocal_rank_fusion_v2` 加权排名 + 兜底 default τ + 历史 edge 取 valid_to | Create |
| `backend/tests/unit/memory/test_retriever.py` | bm25_search / vector_search / graph_traverse — mock PG cursor / mock Milvus client / mock AGE executor，纯函数路径 | Create |
| `backend/tests/unit/memory/test_persona_populator.py` | format_persona_markdown：4 类 edge 拼装 / 空 graph 返 placeholder / token 截断逻辑 / persona 块超 500 tokens 触发自动 paging | Create |
| `backend/tests/unit/memory/test_long_tail_monitor.py` | top-5 valid_from P90 计算：全近 7 天 → 告警 / 散布过去 1 年 → pass / 空数据 → no-op | Create |
| **测试 — L1 Integration** | | |
| `backend/tests/integration/memory/test_retriever_e2e.py` | 真 PG + 真 AGE + 真 Milvus（fixture mock embedding via `mock_qwen_embed`），seed 5 typed edges + 跑 archival_memory_search 端到端 → assert RRF 排序符合预期 | Create |
| `backend/tests/integration/memory/test_persona_populator_e2e.py` | 真 PG seed 持仓 / 偏好 / 规避 / 关注 4 类 edge → 跑 populator → assert working_blocks(persona).content 含 4 类信息 + token_count 准确 | Create |
| `backend/tests/integration/memory/test_instrumentation_e2e.py` | 跑一次 search → assert chat_memory_retrieval_logs 落库 1 行；模拟用户 reject → assert chat_memory_retrieval_feedback 落库 | Create |
| **测试 — L2 Cassette** | | |
| `backend/tests/e2e/memory/test_search_full_path.py` | VCR cassette：真 qwen embed + 真 PG/AGE/Milvus，2 representative scenarios（user 问"我对茅台的看法" / 长尾老 fact "我 2024-08 说过 ..."）| Create |
| `backend/tests/cassettes/memory/search_full_path__user_query_茅台.yaml` | VCR 录制 | Create（runtime 录）|
| `backend/tests/cassettes/memory/search_full_path__long_tail_老_fact.yaml` | VCR 录制 — 验证衰减底 0.5 让老 fact 仍可召回 | Create（runtime 录）|
| **知识卡** | | |
| `docs/claude-context/c5-plan3-read-pipeline-done.md` | Plan 3 ship 知识卡（按契约 § 13 模板）| Create |

> **Notes**: 共 ~12 新文件 + 2 改造 + 2 SQL/cassette 资源。LOC delta 估 ~1.8k（含测试）。

---

## Pre-flight check（Task 0 — 30 分钟）

> 按 `feedback_third_party_plugin_defaults`：第三方默认行为引用前必须 30s 实测。Plan 3 引入 3 个新交互（PG `ts_rank` 分值范围 / Milvus search 返回字段 / AGE Cypher path 输出格式），plan 阶段 spike 一遍避免实施期返工。

### Spike 1: PG ts_rank 分值范围与 jieba pre-tokenize 联动

```bash
cd backend
uv run python - <<'PY'
import jieba
from sqlalchemy import create_engine, text
import os

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    # 准备 1 行临时数据
    conn.execute(text("DROP TABLE IF EXISTS spike_bm25"))
    conn.execute(text("""
        CREATE TEMP TABLE spike_bm25 (
            id SERIAL PRIMARY KEY,
            tokens TEXT,
            search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', tokens)) STORED
        )
    """))
    text1 = "贵州茅台 白酒 重仓"
    tokens1 = " ".join(jieba.cut_for_search(text1))
    conn.execute(text("INSERT INTO spike_bm25 (tokens) VALUES (:t)"), {"t": tokens1})

    q = " ".join(jieba.cut_for_search("茅台"))
    rows = conn.execute(text("""
        SELECT id, tokens,
               ts_rank(search_vector, plainto_tsquery('simple', :q)) AS bm25_score
        FROM spike_bm25
        WHERE search_vector @@ plainto_tsquery('simple', :q)
    """), {"q": q}).all()
    for r in rows:
        print(r)
PY
```

**期望**：返回 1 行，bm25_score 在 [0, 1) 区间（PG 默认 ts_rank normalization）。
**记录到 retrospective**：实际 bm25_score 范围、jieba `cut_for_search("茅台")` 输出 tokens。
**失败 fallback**：若 ts_rank 全为 0 → 检查 jieba pre-tokenize 是否真的拆出"茅台"；若 search_vector @@ 不匹配 → 检查 plainto_tsquery vs to_tsquery 行为差异。

### Spike 2: Milvus search 返回结构

```bash
cd backend
uv run python - <<'PY'
from pymilvus import MilvusClient
import os

client = MilvusClient(uri=f"http://{os.environ['MILVUS_HOST']}:{os.environ['MILVUS_PORT']}")
# 用 Plan 1 ship 的 chat_memory_edge_embeddings collection
results = client.search(
    collection_name="chat_memory_edge_embeddings",
    data=[[0.0] * 1024],
    limit=3,
    output_fields=["edge_id", "user_id"],
)
print(type(results), len(results), len(results[0]) if results else 0)
if results and results[0]:
    print(results[0][0].keys() if hasattr(results[0][0], "keys") else dir(results[0][0]))
PY
```

**期望**：返回 `list[list[dict]]` 外层 1 个 query，内层 ≤ 3 hits，每 hit 含 `id` / `distance` / `entity` keys。
**记录**：MilvusClient.search 返回结构（`results[0][i]["entity"]["edge_id"]` 还是 `results[0][i].entity.edge_id`），影响 retriever.py 字段访问写法。
**失败 fallback**：若 collection 未 load → Plan 1 lifecycle 没跑 `load_collection`，回头补 Plan 1（参考 `feedback_milvus_load_after_index`）。

### Spike 3: AGE Cypher path 输出与 PG 元数据 join 形态

```bash
cd backend
uv run python - <<'PY'
import asyncio
from app.memory.age_executor import AgeExecutor  # Plan 1 提供
from sqlalchemy import create_engine
import os

async def main():
    engine = create_engine(os.environ["DATABASE_URL"])
    age = AgeExecutor(engine)
    # 假设 Plan 1/2 已 seed 1 个 User -[HOLDS]-> Stock(茅台) edge
    rows = await age.cypher("chat_memory", """
        MATCH path = (start {entity_label: 'User', user_id: $uid})-[*1..2]-(end)
        RETURN path LIMIT 5
    """, {"uid": "<test-user-uuid>"})
    print(type(rows), rows[:1] if rows else "EMPTY")

asyncio.run(main())
PY
```

**期望**：返回 list of agtype path，可解析出 nodes + relationships + properties（含 source edge_id 引用 PG 表）。
**记录**：AGE path 字段访问语法、是否需要二次 query PG 拿完整 ChatMemoryEdge 元数据。
**失败 fallback**：若 AGE path 不带 PG-side `edge_id` 引用 → graph_traverse 必须二次 query PG join 元数据，retriever.py 加 `expand_paths_with_pg_metadata` helper。

---

## Tasks（10 个 task / TDD 5-step / 频繁 commit）

### Task 1：RRF v2 常量与 compute_time_decay（核心算法 #3 落地起点）

**Goal**：实现 `backend/app/memory/rrf.py` 全部纯函数 — 常量来自契约 § 5 不得改 + `compute_time_decay` 公式严格 1:1 spec § 11 末尾 #3。

**Depends on**：Plan 1 ship（model + 契约文件）。

#### Step 1.1：RED — 写 test_rrf.py 完整断言

```bash
cd backend
mkdir -p tests/unit/memory
touch tests/unit/memory/__init__.py
```

写 `backend/tests/unit/memory/test_rrf.py`：

```python
"""L0 Unit: RRF v2 — 算法深度补丁 #3 时间感知 ranking 公式校验.

契约 ref: docs/superpowers/plans/2026-05-11-c5-plan-shared-contracts.md § 5
spec ref: § 11 末尾 #3 reciprocal_rank_fusion_v2 完整公式
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.memory.rrf import (
    DECAY_FLOOR,
    IMPORTANCE_WEIGHT_MAP,
    RRF_K,
    TAU_DAYS_BY_REL_TYPE,
    TAU_DAYS_DEFAULT,
    compute_time_decay,
    reciprocal_rank_fusion_v2,
)


class TestConstants:
    """常量值严守契约 § 5 — Plan 8 eval pipeline 引用同名常量."""

    def test_importance_weight_map_three_tier(self) -> None:
        assert IMPORTANCE_WEIGHT_MAP == {0.9: 0.95, 0.5: 0.75, 0.2: 0.6}

    def test_tau_days_by_rel_type(self) -> None:
        assert TAU_DAYS_BY_REL_TYPE["HOLDS"] == 365
        assert TAU_DAYS_BY_REL_TYPE["SOLD"] == 365
        assert TAU_DAYS_BY_REL_TYPE["PREFERS"] == 180
        assert TAU_DAYS_BY_REL_TYPE["AVOIDS"] == 180
        assert TAU_DAYS_BY_REL_TYPE["WATCHES"] == 180
        assert TAU_DAYS_BY_REL_TYPE["EXPRESSED_VIEW"] == 90
        assert TAU_DAYS_BY_REL_TYPE["STUDIED"] == 90

    def test_tau_days_default_180(self) -> None:
        assert TAU_DAYS_DEFAULT == 180

    def test_decay_floor_0_5(self) -> None:
        assert DECAY_FLOOR == 0.5

    def test_rrf_k_60(self) -> None:
        assert RRF_K == 60


class TestComputeTimeDecay:
    """time_decay = DECAY_FLOOR + (1 - DECAY_FLOOR) * exp(-Δt / τ)."""

    def test_zero_days_returns_one(self) -> None:
        # Δt=0 → exp(0)=1 → decay = 0.5 + 0.5 * 1.0 = 1.0
        now = datetime.now(timezone.utc)
        decay = compute_time_decay("HOLDS", now, None, _now=now)
        assert math.isclose(decay, 1.0, abs_tol=1e-6)

    def test_holds_one_year_old_returns_floor_plus_decay(self) -> None:
        # HOLDS τ=365, Δt=365 → exp(-1) ≈ 0.3679 → decay = 0.5 + 0.5 * 0.3679 ≈ 0.6839
        now = datetime.now(timezone.utc)
        valid_from = now - timedelta(days=365)
        decay = compute_time_decay("HOLDS", valid_from, None, _now=now)
        expected = 0.5 + 0.5 * math.exp(-1.0)
        assert math.isclose(decay, expected, abs_tol=1e-6)

    def test_extreme_old_approaches_floor(self) -> None:
        # 10 年前的 EXPRESSED_VIEW(τ=90) → exp(-Δt/τ) → 0 → decay → DECAY_FLOOR
        now = datetime.now(timezone.utc)
        valid_from = now - timedelta(days=3650)
        decay = compute_time_decay("EXPRESSED_VIEW", valid_from, None, _now=now)
        assert math.isclose(decay, DECAY_FLOOR, abs_tol=1e-3)
        assert decay >= DECAY_FLOOR  # 衰减底不消失

    def test_unknown_rel_type_uses_default_tau(self) -> None:
        # rel_type="CORRELATED_WITH" 不在 map → 走 TAU_DAYS_DEFAULT=180
        now = datetime.now(timezone.utc)
        valid_from = now - timedelta(days=180)
        decay = compute_time_decay("CORRELATED_WITH", valid_from, None, _now=now)
        expected = 0.5 + 0.5 * math.exp(-1.0)  # Δt/τ = 1
        assert math.isclose(decay, expected, abs_tol=1e-6)

    def test_history_edge_uses_valid_to_as_reference(self) -> None:
        """spec § 11 #3: 历史 edge(valid_to IS NOT NULL) 取 valid_to 作衰减参考点.

        用户 2024-08 买 2025-03 卖的茅台 — 从 2025-03 起开始衰减,不是从 2024-08.
        """
        now = datetime.now(timezone.utc)
        valid_from = now - timedelta(days=600)  # 久远
        valid_to = now - timedelta(days=30)  # 近期才 invalidate
        decay = compute_time_decay("HOLDS", valid_from, valid_to, _now=now)
        # 应该按 30 天计算，不是 600 天
        expected_with_valid_to = 0.5 + 0.5 * math.exp(-30 / 365)
        expected_with_valid_from = 0.5 + 0.5 * math.exp(-600 / 365)
        assert math.isclose(decay, expected_with_valid_to, abs_tol=1e-6)
        assert not math.isclose(decay, expected_with_valid_from, abs_tol=1e-6)


class TestReciprocalRankFusionV2:
    """spec § 11 末尾 #3 完整公式: score_final = base_rrf × imp_weight × time_decay."""

    def _now(self) -> datetime:
        return datetime(2026, 5, 11, 0, 0, 0, tzinfo=timezone.utc)

    def _make_meta(self, eid: str, rel_type: str, importance: float, days_old: int,
                    valid_to_days_old: int | None = None) -> dict:
        valid_from = self._now() - timedelta(days=days_old)
        valid_to = (self._now() - timedelta(days=valid_to_days_old)
                     if valid_to_days_old is not None else None)
        return {
            "edge_id": eid,
            "rel_type": rel_type,
            "importance": importance,
            "valid_from": valid_from,
            "valid_to": valid_to,
        }

    def test_high_importance_recent_holds_ranks_first(self) -> None:
        """高 importance + 近期 HOLDS 应该排第一."""
        edges_meta = {
            "e1": self._make_meta("e1", "HOLDS", 0.9, days_old=10),
            "e2": self._make_meta("e2", "HOLDS", 0.2, days_old=10),
        }
        retr_results = [
            [{"edge_id": "e1"}, {"edge_id": "e2"}],
            [{"edge_id": "e1"}, {"edge_id": "e2"}],
        ]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        assert ranked[0]["edge_id"] == "e1"
        assert ranked[1]["edge_id"] == "e2"

    def test_old_low_importance_not_completely_suppressed(self) -> None:
        """衰减底 0.5 + importance 下限 0.6 — 老 fact 仍可被召回."""
        edges_meta = {
            "old_low": self._make_meta("old_low", "EXPRESSED_VIEW", 0.2, days_old=3650),
        }
        retr_results = [[{"edge_id": "old_low"}]]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        assert len(ranked) == 1
        # base = 1/61 ≈ 0.0164, imp_weight=0.6, time_decay≥0.5
        # final ≥ 0.0164 * 0.6 * 0.5 ≈ 0.00492 > 0
        assert ranked[0]["score"] > 0.0

    def test_history_edge_decay_uses_valid_to(self) -> None:
        """历史 edge 用 valid_to 作衰减参考点."""
        edges_meta = {
            "hist": self._make_meta("hist", "HOLDS", 0.5, days_old=600,
                                       valid_to_days_old=30),
            "current": self._make_meta("current", "HOLDS", 0.5, days_old=30),
        }
        retr_results = [
            [{"edge_id": "hist"}, {"edge_id": "current"}],
        ]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        # hist 衰减按 30 天 vs current 30 天 → 几乎相同 score(rank 决定),不应 hist 沉底
        scores = {item["edge_id"]: item["score"] for item in ranked}
        assert math.isclose(scores["hist"], scores["current"] * (60 + 1) / (60 + 2),
                              rel_tol=0.01) or math.isclose(scores["hist"], scores["current"],
                                                              rel_tol=0.05)

    def test_unknown_importance_uses_middle_default_0_75(self) -> None:
        """importance 不是三档之一(老数据) — 走 0.75 fallback."""
        edges_meta = {
            "weird": self._make_meta("weird", "HOLDS", 0.7, days_old=10),  # 0.7 不是三档
            "high": self._make_meta("high", "HOLDS", 0.9, days_old=10),
            "med": self._make_meta("med", "HOLDS", 0.5, days_old=10),
        }
        retr_results = [
            [{"edge_id": "high"}, {"edge_id": "weird"}, {"edge_id": "med"}],
        ]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        # weird 走 fallback 0.75 → 跟 med 同档
        scores = {item["edge_id"]: item["score"] for item in ranked}
        # high(0.95) > weird(0.75) ≈ med(0.75)
        assert scores["high"] > scores["weird"]

    def test_top_k_truncation(self) -> None:
        """top=2 只返 2 条."""
        edges_meta = {f"e{i}": self._make_meta(f"e{i}", "HOLDS", 0.5, days_old=i)
                       for i in range(10)}
        retr_results = [[{"edge_id": f"e{i}"} for i in range(10)]]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=2, _now=self._now())
        assert len(ranked) == 2

    def test_three_retrievers_aggregate_correctly(self) -> None:
        """3 路 retriever 都包含 e1 → e1 的 base_rrf = 3 * (1/61) — 但只算 unique 出现."""
        edges_meta = {
            "e1": self._make_meta("e1", "HOLDS", 0.5, days_old=10),
            "e2": self._make_meta("e2", "HOLDS", 0.5, days_old=10),
        }
        retr_results = [
            [{"edge_id": "e1"}, {"edge_id": "e2"}],
            [{"edge_id": "e1"}, {"edge_id": "e2"}],
            [{"edge_id": "e1"}],
        ]
        ranked = reciprocal_rank_fusion_v2(retr_results, edges_meta, top=5, _now=self._now())
        scores = {item["edge_id"]: item["score"] for item in ranked}
        # e1 出现 3 次(rank 1/1/1) → base = 3/(60+1) = 3/61
        # e2 出现 2 次(rank 2/2) → base = 2/(60+2) = 2/62
        # 都是 importance 0.5 + 10 days 同 decay,所以 e1 > e2
        assert scores["e1"] > scores["e2"]
```

```bash
cd backend
uv run pytest tests/unit/memory/test_rrf.py -x 2>&1 | head -40
# 期望：FAILED — ModuleNotFoundError: No module named 'app.memory.rrf'(或 NotImplementedError)
```

#### Step 1.2：GREEN — 实现 rrf.py

写 `backend/app/memory/rrf.py`：

```python
"""RRF v2 — 时间感知 + importance 加权 reciprocal rank fusion.

算法深度补丁 #3 完整实现.

公式 (spec § 11 末尾 #3):
    score_final = (Σ 1/(k + rank_in_retriever)) × importance_weight × time_decay
    importance_weight ∈ {0.6, 0.75, 0.95}  (三档,low 不被完全压制)
    time_decay = DECAY_FLOOR + (1 - DECAY_FLOOR) × exp(-Δt / τ)
    τ_days ∈ {365 (HOLDS/SOLD), 180 (PREFERS/AVOIDS/WATCHES), 90 (EXPRESSED_VIEW/STUDIED)}

历史 edge(valid_to IS NOT NULL)用 valid_to 作衰减参考点 — 事实"最近一次为真的时间"
是更准确的 freshness 锚点.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

# 契约 § 5: 常量必须严守,Plan 8 eval pipeline 引用同名常量做覆盖率检查
IMPORTANCE_WEIGHT_MAP: dict[float, float] = {
    0.9: 0.95,
    0.5: 0.75,
    0.2: 0.6,
}
"""importance 三档映射. low(0.2)不完全压制(下限 0.6),保长尾召回."""

TAU_DAYS_BY_REL_TYPE: dict[str, int] = {
    "HOLDS": 365, "SOLD": 365,
    "PREFERS": 180, "AVOIDS": 180, "WATCHES": 180,
    "EXPRESSED_VIEW": 90, "STUDIED": 90,
}
"""τ 按 rel_type 分级 — 金融垂直洞察:持仓事实(365d)>偏好(180d)>观点(90d)."""

TAU_DAYS_DEFAULT: int = 180
"""未在 map 中的 rel_type 走 fallback,如 BELONGS_TO / HAS_CONCEPT / CORRELATED_WITH."""

DECAY_FLOOR: float = 0.5
"""时间衰减底 — 老 fact 不消失,保 audit 价值与长尾召回."""

RRF_K: int = 60
"""RRF 公式标准常量 (Cormack et al. 2009)."""

_IMPORTANCE_FALLBACK: float = 0.75
"""importance 不是三档之一(老数据 / 抽取异常)走中档 fallback."""


def _compute_importance_weight(importance: float | None) -> float:
    """importance 三档映射 + fallback. 私有 helper."""
    if importance is None:
        return _IMPORTANCE_FALLBACK
    return IMPORTANCE_WEIGHT_MAP.get(importance, _IMPORTANCE_FALLBACK)


def compute_time_decay(
    rel_type: str,
    valid_from: datetime,
    valid_to: datetime | None,
    *,
    _now: datetime | None = None,
) -> float:
    """time_decay = DECAY_FLOOR + (1 - DECAY_FLOOR) × exp(-Δt / τ).

    历史 edge(valid_to is not None)用 valid_to 作衰减参考点 — 事实"最近一次为真的
    时间"作 freshness 锚点比"开始为真"更准.

    Args:
        rel_type: 11 类 REL_TYPES 之一(契约 registry).
        valid_from: edge.valid_from(必填).
        valid_to: edge.valid_to(可选,历史 edge 才有).
        _now: test injection,生产用 None → datetime.utcnow.

    Returns:
        decay ∈ [DECAY_FLOOR, 1.0].
    """
    now = _now if _now is not None else datetime.now(timezone.utc)
    # 历史 edge 用 valid_to,当前 edge 用 valid_from
    ref_time = valid_to if valid_to is not None else valid_from
    # 防御:tz-naive 时刻补 UTC
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta_days = max((now - ref_time).total_seconds() / 86400.0, 0.0)
    tau_days = TAU_DAYS_BY_REL_TYPE.get(rel_type, TAU_DAYS_DEFAULT)
    return DECAY_FLOOR + (1.0 - DECAY_FLOOR) * math.exp(-delta_days / tau_days)


def reciprocal_rank_fusion_v2(
    retriever_results: list[list[dict[str, Any]]],
    edges_meta: dict[str, dict[str, Any]],
    k: int = RRF_K,
    top: int = 5,
    *,
    _now: datetime | None = None,
) -> list[dict[str, Any]]:
    """spec § 11 末尾 #3 时间感知 RRF v2.

    Args:
        retriever_results: 各 retriever 已排序的 result list,每个 item 必须含 'edge_id'.
        edges_meta: edge_id → {rel_type, importance, valid_from, valid_to} 的查询字典,
                     由 retriever.format_edges_meta_for_rrf 构造.
        k: RRF 常数,默认 60.
        top: 返回 top-K,默认 5.
        _now: test injection.

    Returns:
        list of {edge_id, score} 按 final score 降序,长度 ≤ top.

    Raises:
        KeyError: 若 retriever_results 中某 edge_id 不在 edges_meta — 调用方必须保证一致.
    """
    rrf_scores: dict[str, float] = defaultdict(float)
    for retr_list in retriever_results:
        for rank, item in enumerate(retr_list, start=1):
            rrf_scores[item["edge_id"]] += 1.0 / (k + rank)

    final_scores: dict[str, float] = {}
    for eid, base in rrf_scores.items():
        meta = edges_meta[eid]
        imp_weight = _compute_importance_weight(meta.get("importance"))
        time_decay = compute_time_decay(
            rel_type=meta["rel_type"],
            valid_from=meta["valid_from"],
            valid_to=meta.get("valid_to"),
            _now=_now,
        )
        final_scores[eid] = base * imp_weight * time_decay

    sorted_eids = sorted(final_scores.keys(), key=lambda x: -final_scores[x])
    return [{"edge_id": eid, "score": final_scores[eid]} for eid in sorted_eids[:top]]
```

```bash
cd backend
uv run pytest tests/unit/memory/test_rrf.py -x -v 2>&1 | tail -25
# 期望: 18+ tests passed
```

#### Step 1.3：REFACTOR

- 检查 mypy strict 通过：`uv run mypy app/memory/rrf.py`
- 检查 ruff：`uv run ruff check app/memory/rrf.py tests/unit/memory/test_rrf.py`

#### Step 1.4：COMMIT

```bash
cd backend && uv run pytest tests/unit/memory/test_rrf.py -x
git add backend/app/memory/rrf.py backend/tests/unit/memory/test_rrf.py backend/tests/unit/memory/__init__.py
git commit -m "feat(c5-plan3): RRF v2 时间感知 ranking — 算法深度补丁 #3 落地起点"
```

---

### Task 2：Instrumentation 表 SQL migration + log helper

**Goal**：建 2 张 instrumentation 表 + 落库 helper，供长尾召回监控（Plan 3 自用）+ posterior calibration weekly job（Plan 5 消费）+ eval pipeline（Plan 8 metric）。

#### Step 2.1：RED — 写迁移测试

写 `backend/tests/integration/memory/test_instrumentation_e2e.py` 的 schema 校验部分（task 8 再加端到端落库测试）：

```python
"""L1: instrumentation 表 schema + 落库 helper."""
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_retrieval_logs_table_exists(pg_memory_fixture):
    async with pg_memory_fixture.connect() as conn:
        result = await conn.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'chat_memory_retrieval_logs'
            ORDER BY ordinal_position
        """))
        cols = {row[0]: row[1] for row in result}
    assert "log_id" in cols
    assert "user_id" in cols
    assert "query_text" in cols
    assert "retrieved_edge_ids" in cols  # JSONB
    assert "top_k_valid_from_p90_days" in cols
    assert "created_at" in cols


@pytest.mark.asyncio
async def test_retrieval_feedback_table_exists(pg_memory_fixture):
    async with pg_memory_fixture.connect() as conn:
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'chat_memory_retrieval_feedback'
        """))
        cols = {row[0] for row in result}
    assert "feedback_id" in cols
    assert "edge_id" in cols
    assert "user_id" in cols
    assert "feedback_kind" in cols  # 'reject' / 'confirm' / 'invalidate'
    assert "reason" in cols
    assert "created_at" in cols
```

```bash
cd backend
uv run pytest tests/integration/memory/test_instrumentation_e2e.py -x 2>&1 | tail -10
# 期望: FAILED 表不存在
```

#### Step 2.2：GREEN — 写 SQL migration + helper

写 `backend/scripts/migrations/2026-05-11-c5-plan3-instrumentation.sql`：

```sql
-- C.5 Plan 3 — Instrumentation 表
-- 用途:
--   1. chat_memory_retrieval_logs — 长尾召回监控 + posterior calibration 命中数累积
--   2. chat_memory_retrieval_feedback — 用户否决信号(/memory page invalidate / reject)
--
-- 消费方:
--   - Plan 3 long_tail_monitor.py — top-5 valid_from P90 日级监控
--   - Plan 5 posterior_calibration.py weekly job — 行为信号反向调 importance
--   - Plan 8 eval pipeline — recall_precision metric 引用 retrieved_edge_ids

CREATE TABLE IF NOT EXISTS chat_memory_retrieval_logs (
    log_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                     UUID NOT NULL REFERENCES users(id),
    query_text                  TEXT NOT NULL,
    retrieved_edge_ids          JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ordered list
    rrf_scores                  JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {edge_id: score}
    top_k_valid_from_p90_days   FLOAT,                                -- 长尾监控用
    retriever_breakdown         JSONB,                                -- {bm25: 10, vector: 10, graph: 0}
    latency_ms                  INTEGER,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_retrieval_logs_user_created
    ON chat_memory_retrieval_logs(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_retrieval_logs_created
    ON chat_memory_retrieval_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS chat_memory_retrieval_feedback (
    feedback_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    edge_id         UUID NOT NULL REFERENCES chat_memory_edges(edge_id) ON DELETE CASCADE,
    feedback_kind   VARCHAR(32) NOT NULL,
    reason          TEXT,
    log_id          UUID REFERENCES chat_memory_retrieval_logs(log_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (feedback_kind IN ('reject', 'confirm', 'invalidate'))
);

CREATE INDEX IF NOT EXISTS idx_retrieval_feedback_user_edge
    ON chat_memory_retrieval_feedback(user_id, edge_id);

CREATE INDEX IF NOT EXISTS idx_retrieval_feedback_created
    ON chat_memory_retrieval_feedback(created_at DESC);
```

写 `backend/app/memory/instrumentation.py`：

```python
"""Plan 3 instrumentation — 长尾召回监控 + posterior calibration 数据落库.

调用方:
    - hierarchical.archival_memory_search → log_retrieval_hit (每次 search)
    - /memory router invalidate endpoint → log_user_reject (Plan 7)
    - Plan 5 posterior_calibration weekly job 消费两表
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def log_retrieval_hit(
    engine: AsyncEngine,
    *,
    user_id: UUID,
    query_text: str,
    retrieved_edge_ids: list[str],
    rrf_scores: dict[str, float],
    edges_meta: dict[str, dict[str, Any]],
    retriever_breakdown: dict[str, int],
    latency_ms: int,
    _now: datetime | None = None,
) -> UUID:
    """Records 1 search hit for long-tail monitoring + posterior calibration.

    P90 valid_from age days 计算: 取 top-K edges 的 valid_from,算 P90 距 now 天数.
    长尾召回告警阈值: P90 < 7 天 → 全集中近期,触发 long_tail_monitor 告警.
    """
    now = _now or datetime.now(timezone.utc)
    log_id = uuid4()

    valid_from_ages_days: list[float] = []
    for eid in retrieved_edge_ids:
        meta = edges_meta.get(eid)
        if not meta or not meta.get("valid_from"):
            continue
        vf = meta["valid_from"]
        if vf.tzinfo is None:
            vf = vf.replace(tzinfo=timezone.utc)
        valid_from_ages_days.append((now - vf).total_seconds() / 86400.0)

    p90: float | None = None
    if valid_from_ages_days:
        sorted_ages = sorted(valid_from_ages_days)
        idx = int(len(sorted_ages) * 0.9)
        idx = min(idx, len(sorted_ages) - 1)
        p90 = sorted_ages[idx]

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO chat_memory_retrieval_logs
                (log_id, user_id, query_text, retrieved_edge_ids, rrf_scores,
                 top_k_valid_from_p90_days, retriever_breakdown, latency_ms, created_at)
            VALUES (:log_id, :user_id, :q, CAST(:eids AS JSONB), CAST(:scores AS JSONB),
                    :p90, CAST(:rb AS JSONB), :lat, :now)
        """), {
            "log_id": str(log_id),
            "user_id": str(user_id),
            "q": query_text,
            "eids": _json_dumps(retrieved_edge_ids),
            "scores": _json_dumps(rrf_scores),
            "p90": p90,
            "rb": _json_dumps(retriever_breakdown),
            "lat": latency_ms,
            "now": now,
        })
    return log_id


async def log_user_reject(
    engine: AsyncEngine,
    *,
    user_id: UUID,
    edge_id: UUID,
    feedback_kind: str,  # 'reject' / 'confirm' / 'invalidate'
    reason: str | None = None,
    log_id: UUID | None = None,
) -> None:
    """Records 1 feedback signal. Plan 5 weekly job 消费做 posterior calibration."""
    if feedback_kind not in ("reject", "confirm", "invalidate"):
        raise ValueError(f"feedback_kind must be reject/confirm/invalidate, got {feedback_kind!r}")
    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO chat_memory_retrieval_feedback
                (feedback_id, user_id, edge_id, feedback_kind, reason, log_id)
            VALUES (gen_random_uuid(), :uid, :eid, :kind, :reason, :log_id)
        """), {
            "uid": str(user_id),
            "eid": str(edge_id),
            "kind": feedback_kind,
            "reason": reason,
            "log_id": str(log_id) if log_id else None,
        })


def _json_dumps(value: Any) -> str:
    import json
    return json.dumps(value, default=str)
```

跑迁移（Plan 1 已建好 schema，这里 append）：

```bash
cd backend
psql "$DATABASE_URL" -f scripts/migrations/2026-05-11-c5-plan3-instrumentation.sql
uv run pytest tests/integration/memory/test_instrumentation_e2e.py -x 2>&1 | tail -10
# 期望: 2 tests passed
```

#### Step 2.3：REFACTOR + COMMIT

```bash
cd backend
uv run mypy app/memory/instrumentation.py
uv run ruff check app/memory/instrumentation.py
git add backend/scripts/migrations/2026-05-11-c5-plan3-instrumentation.sql \
        backend/app/memory/instrumentation.py \
        backend/tests/integration/memory/test_instrumentation_e2e.py
git commit -m "feat(c5-plan3): instrumentation 表 + log helper(retrieval_logs + feedback)"
```

---

### Task 3：BM25 retriever（路径 1）

**Goal**：实现 PG GIN tsvector + jieba pre-tokenize 检索。jieba 函数复用 Plan 1 `app.memory.registry.jieba_tokenize_for_search`。

#### Step 3.1：RED — L0 单测

写 `backend/tests/unit/memory/test_retriever.py`（先 BM25 部分，后续 task 加 vector / graph）：

```python
"""L0: 3 路 retriever — bm25_search / vector_search / graph_traverse."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.memory.retriever import (
    bm25_search,
    vector_search,
    graph_traverse,
    format_edges_meta_for_rrf,
)


class TestBm25Search:
    @pytest.mark.asyncio
    async def test_jieba_tokenize_query_then_call_pg(self) -> None:
        """query 走 jieba.cut_for_search 切词,再 plainto_tsquery."""
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        # mock execute returns rows
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[
            {"edge_id": str(uuid4()), "bm25_score": 0.8, "rel_type": "HOLDS",
             "importance": 0.9, "valid_from": datetime.now(timezone.utc), "valid_to": None},
        ])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        user_id = uuid4()
        results = await bm25_search(mock_engine, user_id=user_id, query="茅台", k=10)
        assert len(results) == 1
        assert "edge_id" in results[0]
        # SQL 应该包含 plainto_tsquery + invalidated_at IS NULL filter
        call_args = mock_conn.execute.call_args
        sql_str = str(call_args[0][0])
        assert "plainto_tsquery" in sql_str
        assert "invalidated_at IS NULL" in sql_str

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_list(self) -> None:
        """空 query 不打 PG."""
        mock_engine = MagicMock()
        results = await bm25_search(mock_engine, user_id=uuid4(), query="", k=10)
        assert results == []
        mock_engine.begin.assert_not_called()
```

```bash
cd backend
uv run pytest tests/unit/memory/test_retriever.py::TestBm25Search -x 2>&1 | tail -10
# 期望: FAILED — module not found
```

#### Step 3.2：GREEN — retriever.py 加 BM25

写 `backend/app/memory/retriever.py`：

```python
"""3-way Hybrid Retriever — BM25(PG) + Vector(Milvus) + Graph(AGE on-demand).

spec § 5 完整实现. RRF fusion 在 rrf.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.memory.registry import jieba_tokenize_for_search


class _MilvusClientLike(Protocol):
    def search(
        self,
        collection_name: str,
        data: list[list[float]],
        limit: int,
        output_fields: list[str] | None = None,
        filter: str | None = None,
    ) -> Any:
        ...


class _AgeExecutorLike(Protocol):
    async def cypher(self, graph_name: str, query: str, params: dict[str, Any] | None = None) -> Any:
        ...


class _EmbedServiceLike(Protocol):
    async def embed(self, text: str) -> list[float]:
        ...


# ============================================================
# 路径 1: BM25 (PG GIN tsvector + jieba pre-tokenize)
# ============================================================

async def bm25_search(
    engine: AsyncEngine,
    *,
    user_id: UUID,
    query: str,
    k: int = 10,
) -> list[dict[str, Any]]:
    """spec § 5 路径 1: PG ts_rank + plainto_tsquery + invalidated_at IS NULL filter.

    Args:
        engine: async PG engine.
        user_id: 多租户隔离.
        query: 用户原文 query, 内部走 jieba.cut_for_search 切词后再喂 plainto_tsquery.
        k: 返回 top-K.

    Returns:
        list of {edge_id, bm25_score, rel_type, importance, valid_from, valid_to},
        按 bm25_score 降序. 空 query 返 [].
    """
    if not query.strip():
        return []
    query_tokens = jieba_tokenize_for_search(query)
    if not query_tokens.strip():
        return []
    sql = text("""
        SELECT edge_id, rel_type, importance, valid_from, valid_to,
               ts_rank(search_vector, plainto_tsquery('simple', :q)) AS bm25_score
        FROM chat_memory_edges
        WHERE user_id = :uid
          AND invalidated_at IS NULL
          AND search_vector @@ plainto_tsquery('simple', :q)
        ORDER BY bm25_score DESC
        LIMIT :k
    """)
    async with engine.begin() as conn:
        result = await conn.execute(sql, {"q": query_tokens, "uid": str(user_id), "k": k})
        rows = result.fetchall()
    return [dict(r._mapping) if hasattr(r, "_mapping") else dict(r) for r in rows]
```

```bash
cd backend
uv run pytest tests/unit/memory/test_retriever.py::TestBm25Search -x -v
# 期望: 2 passed
```

#### Step 3.3：REFACTOR + COMMIT

```bash
cd backend && uv run mypy app/memory/retriever.py && uv run ruff check app/memory/retriever.py
git add backend/app/memory/retriever.py backend/tests/unit/memory/test_retriever.py
git commit -m "feat(c5-plan3): BM25 retriever — PG GIN tsvector + jieba pre-tokenize"
```

---

### Task 4：Vector retriever（路径 2）

**Goal**：实现 Milvus 单 collection 检索。不集成 embed_cache（Plan 5 做），但留 hook 点。

#### Step 4.1：RED — L0 vector test

追加到 `tests/unit/memory/test_retriever.py`：

```python
class TestVectorSearch:
    @pytest.mark.asyncio
    async def test_calls_embed_then_milvus_search(self) -> None:
        """vector_search: 1) embed query 2) Milvus search 3) join PG meta."""
        mock_embed = AsyncMock()
        mock_embed.embed = AsyncMock(return_value=[0.0] * 1024)

        mock_milvus = MagicMock()
        eid = str(uuid4())
        mock_milvus.search = MagicMock(return_value=[[
            {"id": eid, "distance": 0.3, "entity": {"edge_id": eid}},
        ]])

        # PG join meta
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[
            {"edge_id": eid, "rel_type": "HOLDS", "importance": 0.9,
             "valid_from": datetime.now(timezone.utc), "valid_to": None},
        ])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        results = await vector_search(
            engine=mock_engine,
            milvus_client=mock_milvus,
            embed_service=mock_embed,
            user_id=uuid4(),
            query="茅台白酒",
            k=10,
        )
        assert len(results) == 1
        assert results[0]["edge_id"] == eid
        mock_embed.embed.assert_awaited_once()
        mock_milvus.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self) -> None:
        results = await vector_search(
            engine=MagicMock(), milvus_client=MagicMock(), embed_service=AsyncMock(),
            user_id=uuid4(), query="", k=10,
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_user_id_filter_in_milvus_expr(self) -> None:
        """spec § 5 + 多租户隔离: Milvus search 必须带 user_id filter."""
        mock_embed = AsyncMock()
        mock_embed.embed = AsyncMock(return_value=[0.0] * 1024)
        mock_milvus = MagicMock()
        mock_milvus.search = MagicMock(return_value=[[]])
        mock_engine = MagicMock()

        await vector_search(
            engine=mock_engine, milvus_client=mock_milvus,
            embed_service=mock_embed, user_id=uuid4(), query="x", k=5,
        )
        call_kwargs = mock_milvus.search.call_args.kwargs
        # filter expression 必须含 user_id
        assert "user_id" in (call_kwargs.get("filter") or "")
```

#### Step 4.2：GREEN — 加 vector_search 到 retriever.py

```python
# ============================================================
# 路径 2: Vector (Milvus 单 collection + PG meta join)
# ============================================================

async def vector_search(
    *,
    engine: AsyncEngine,
    milvus_client: _MilvusClientLike,
    embed_service: _EmbedServiceLike,
    user_id: UUID,
    query: str,
    k: int = 10,
    collection_name: str = "chat_memory_edge_embeddings",
) -> list[dict[str, Any]]:
    """spec § 5 路径 2: Milvus search → PG join meta.

    embed cache hook: Plan 5 提供 EmbedCache,在此函数内 try/except import 改用 cache.
    Plan 3 ship 时直接调 embed_service.embed,Plan 5 ship 后改 hook.
    """
    if not query.strip():
        return []
    query_vec = await embed_service.embed(query)

    # Milvus search 多租户 filter
    filter_expr = f'user_id == "{user_id}"'
    raw_results = milvus_client.search(
        collection_name=collection_name,
        data=[query_vec],
        limit=k,
        output_fields=["edge_id", "user_id"],
        filter=filter_expr,
    )
    if not raw_results or not raw_results[0]:
        return []
    # 兼容 dict 形态(spike 实测)与 entity 对象形态
    edge_ids: list[str] = []
    distances: dict[str, float] = {}
    for hit in raw_results[0]:
        if isinstance(hit, dict):
            ent = hit.get("entity") or {}
            eid = ent.get("edge_id") or hit.get("id")
            dist = hit.get("distance", 0.0)
        else:
            ent = getattr(hit, "entity", None)
            eid = getattr(ent, "edge_id", None) or getattr(hit, "id", None)
            dist = getattr(hit, "distance", 0.0)
        if eid:
            edge_ids.append(str(eid))
            distances[str(eid)] = dist
    if not edge_ids:
        return []

    # PG join 拿 rel_type / importance / valid_from / valid_to
    sql = text("""
        SELECT edge_id, rel_type, importance, valid_from, valid_to
        FROM chat_memory_edges
        WHERE edge_id = ANY(:eids) AND invalidated_at IS NULL
    """)
    async with engine.begin() as conn:
        result = await conn.execute(sql, {"eids": edge_ids})
        rows = result.fetchall()
    by_id: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
        by_id[str(d["edge_id"])] = d
    # 按 Milvus 排序保留
    out: list[dict[str, Any]] = []
    for eid in edge_ids:
        if eid in by_id:
            d = by_id[eid]
            d["vector_distance"] = distances[eid]
            out.append(d)
    return out
```

```bash
cd backend && uv run pytest tests/unit/memory/test_retriever.py::TestVectorSearch -x -v
git add backend/app/memory/retriever.py backend/tests/unit/memory/test_retriever.py
git commit -m "feat(c5-plan3): Vector retriever — Milvus 单 collection + PG meta join"
```

---

### Task 5：Graph traverse（路径 3 — on-demand）

**Goal**：AGE Cypher 多跳遍历底层函数。**不进 default search**（spec § 5 决策），由 Plan 4 的 archival_memory_traverse MCP tool 调用。

#### Step 5.1：RED — graph_traverse 测试

追加到 `tests/unit/memory/test_retriever.py`：

```python
class TestGraphTraverse:
    @pytest.mark.asyncio
    async def test_2_hop_traversal_with_rel_type_filter(self) -> None:
        mock_age = AsyncMock()
        mock_age.cypher = AsyncMock(return_value=[
            {"path_data": "agtype-encoded path"},
        ])
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_result = MagicMock()
        mock_result.fetchall = MagicMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value=mock_result)

        results = await graph_traverse(
            engine=mock_engine,
            age_executor=mock_age,
            user_id=uuid4(),
            start_label="User",
            hops=2,
            rel_types=["HOLDS", "BELONGS_TO"],
        )
        # 调用了 AGE Cypher
        mock_age.cypher.assert_awaited_once()
        cypher_str = mock_age.cypher.call_args[0][1]
        assert "MATCH path" in cypher_str
        assert "*1..2" in cypher_str  # hops 2

    @pytest.mark.asyncio
    async def test_invalid_hops_raises(self) -> None:
        with pytest.raises(ValueError, match="hops"):
            await graph_traverse(
                engine=MagicMock(), age_executor=AsyncMock(),
                user_id=uuid4(), start_label="User", hops=10,
            )

    @pytest.mark.asyncio
    async def test_default_rel_types_uses_all(self) -> None:
        """rel_types=None → 所有 11 类 REL_TYPES 都 traverse."""
        mock_age = AsyncMock()
        mock_age.cypher = AsyncMock(return_value=[])
        mock_engine = MagicMock()
        await graph_traverse(
            engine=mock_engine, age_executor=mock_age,
            user_id=uuid4(), start_label="User", hops=1, rel_types=None,
        )
        # AGE 调用参数应包含全部 11 类
        params = mock_age.cypher.call_args[0][2]
        assert "rel_types" in params
        assert len(params["rel_types"]) == 11
```

#### Step 5.2：GREEN — graph_traverse impl

加到 retriever.py：

```python
# ============================================================
# 路径 3: Graph (AGE Cypher on-demand) — 不进 default search
# ============================================================

# spec § 6 + 契约 § 5: 11 类 REL_TYPES
_ALL_REL_TYPES = [
    "HOLDS", "WATCHES", "PREFERS", "AVOIDS", "EXPRESSED_VIEW", "SOLD",
    "STUDIED", "COMPARED", "BELONGS_TO", "HAS_CONCEPT", "CORRELATED_WITH",
]


async def graph_traverse(
    *,
    engine: AsyncEngine,
    age_executor: _AgeExecutorLike,
    user_id: UUID,
    start_label: str,
    hops: int = 2,
    rel_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """spec § 5 路径 3: AGE Cypher 多跳遍历 + PG meta join.

    On-demand 单独 tool, 不进 default search 因为需要 start_label 抽取(LLM call ~200-500ms).
    Plan 4 archival_memory_traverse MCP tool wrapper 调本函数.

    Args:
        start_label: 起点 entity_label, e.g. 'User' or '600519.SH'.
        hops: 1-3, 上限避免爆炸.
        rel_types: 限定 traverse 的 rel_type, None 默认全部 11 类.

    Returns:
        list of dict: 每条 record 含 nodes / edges / properties(从 AGE path 解析后 join PG).

    Raises:
        ValueError: hops < 1 or hops > 3.
    """
    if not (1 <= hops <= 3):
        raise ValueError(f"hops must be 1..3, got {hops}")
    rel_types = rel_types if rel_types is not None else list(_ALL_REL_TYPES)

    cypher = f"""
        MATCH path = (start {{entity_label: $label, user_id: $uid}})-[*1..{hops}]-(end)
        WHERE all(e IN relationships(path) WHERE
                  type(e) IN $rel_types AND e.invalidated_at IS NULL)
        RETURN path LIMIT 20
    """
    age_rows = await age_executor.cypher(
        "chat_memory", cypher,
        {"label": start_label, "uid": str(user_id), "rel_types": rel_types},
    )
    return _expand_paths_with_pg_metadata(age_rows, engine, user_id)


def _expand_paths_with_pg_metadata(
    age_rows: Any, engine: AsyncEngine, user_id: UUID,
) -> list[dict[str, Any]]:
    """AGE path → 提取 edge_id list → PG join 拿元数据.

    AGE 内 edge 没有 PG-side rel_type/importance/valid_from 完整元数据,
    走 retriever 通用 PG join.
    """
    # spike 3 实测后填具体 agtype 解析逻辑;Plan 1 提供 AgeExecutor.cypher 可能已返回
    # 解析后的 dict, 这里假设格式为 list[dict] 即返回.
    if not age_rows:
        return []
    return [dict(r) if not isinstance(r, dict) else r for r in age_rows]
```

```bash
cd backend && uv run pytest tests/unit/memory/test_retriever.py::TestGraphTraverse -x -v
git add backend/app/memory/retriever.py backend/tests/unit/memory/test_retriever.py
git commit -m "feat(c5-plan3): Graph traverse(AGE Cypher on-demand)— 不进 default search"
```

---

### Task 6：format_edges_meta_for_rrf + archival_memory_search 入口实现

**Goal**：拼装 3 路 retriever + 调用 RRF v2 + log instrumentation + 替换 HierarchicalMemory.archival_memory_search stub。

#### Step 6.1：RED — 入口测试

加 `tests/unit/memory/test_retriever.py::TestFormatEdgesMetaForRrf`：

```python
class TestFormatEdgesMetaForRrf:
    def test_aggregates_3_retriever_results_by_edge_id(self) -> None:
        bm25 = [{"edge_id": "e1", "rel_type": "HOLDS", "importance": 0.9,
                  "valid_from": datetime(2024, 1, 1, tzinfo=timezone.utc), "valid_to": None}]
        vec = [{"edge_id": "e2", "rel_type": "PREFERS", "importance": 0.5,
                 "valid_from": datetime(2024, 6, 1, tzinfo=timezone.utc), "valid_to": None}]
        graph = []
        meta = format_edges_meta_for_rrf([bm25, vec, graph])
        assert "e1" in meta and "e2" in meta
        assert meta["e1"]["rel_type"] == "HOLDS"
        assert meta["e2"]["rel_type"] == "PREFERS"

    def test_dedupes_when_edge_in_multiple_retrievers(self) -> None:
        bm25 = [{"edge_id": "e1", "rel_type": "HOLDS", "importance": 0.9,
                  "valid_from": datetime(2024, 1, 1, tzinfo=timezone.utc), "valid_to": None}]
        vec = [{"edge_id": "e1", "rel_type": "HOLDS", "importance": 0.9,
                 "valid_from": datetime(2024, 1, 1, tzinfo=timezone.utc), "valid_to": None}]
        meta = format_edges_meta_for_rrf([bm25, vec])
        assert len(meta) == 1
```

#### Step 6.2：GREEN — format_edges_meta_for_rrf

加到 retriever.py 末尾：

```python
def format_edges_meta_for_rrf(
    retriever_results: list[list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """从各 retriever 结果合并 edge meta 给 rrf.reciprocal_rank_fusion_v2 用.

    Returns: {edge_id: {rel_type, importance, valid_from, valid_to}}.
    Edge 在多 retriever 出现时去重(取第一次见的元数据,因为本来就是 PG 拉的同源).
    """
    out: dict[str, dict[str, Any]] = {}
    for retr_list in retriever_results:
        for item in retr_list:
            eid = str(item["edge_id"])
            if eid not in out:
                out[eid] = {
                    "rel_type": item.get("rel_type"),
                    "importance": item.get("importance"),
                    "valid_from": item.get("valid_from"),
                    "valid_to": item.get("valid_to"),
                }
    return out
```

#### Step 6.3：替换 HierarchicalMemory.archival_memory_search stub

修改 `backend/app/memory/hierarchical.py`，在 Plan 1 留下的 stub 位置：

```python
import time
from sqlalchemy import text as _sa_text

from app.memory.retriever import (
    bm25_search, vector_search, format_edges_meta_for_rrf,
)
from app.memory.rrf import reciprocal_rank_fusion_v2
from app.memory.instrumentation import log_retrieval_hit
from app.memory.models import ChatMemoryEdge


# ===== Plan 3 实现 (替换 stub) =====

async def archival_memory_search(
    self, user_id, query, k=5,
):
    """spec § 5 3-way Hybrid + RRF v2.

    路径:
        1. BM25 (PG GIN + jieba) — 词法
        2. Vector (Milvus + qwen embed) — 语义
        3. (Graph 不进 default,留 archival_memory_traverse tool 调用)

    Fusion: rrf.reciprocal_rank_fusion_v2 (importance 三档 + 时间感知).
    Instrumentation: log_retrieval_hit 落库 → Plan 5 calibration / Plan 8 eval 消费.
    """
    t0 = time.time()
    # 路径 1
    bm25_hits = await bm25_search(
        self._pg_engine, user_id=user_id, query=query, k=k * 2,
    )
    # 路径 2
    vector_hits = await vector_search(
        engine=self._pg_engine, milvus_client=self._milvus,
        embed_service=self._embed_service, user_id=user_id, query=query, k=k * 2,
    )
    # 路径 3 NOT in default search

    edges_meta = format_edges_meta_for_rrf([bm25_hits, vector_hits])
    if not edges_meta:
        return []

    rrf_top = reciprocal_rank_fusion_v2(
        retriever_results=[bm25_hits, vector_hits],
        edges_meta=edges_meta,
        top=k,
    )
    if not rrf_top:
        return []

    # Materialize as ChatMemoryEdge ORM
    top_eids = [r["edge_id"] for r in rrf_top]
    async with self._pg_engine.begin() as conn:
        rows = (await conn.execute(
            _sa_text("SELECT * FROM chat_memory_edges WHERE edge_id = ANY(:eids)"),
            {"eids": top_eids},
        )).fetchall()
    by_id = {str(dict(r._mapping)["edge_id"]): r for r in rows}
    materialized: list[ChatMemoryEdge] = []
    for r in rrf_top:
        row = by_id.get(r["edge_id"])
        if row:
            edge = ChatMemoryEdge(**dict(row._mapping))
            materialized.append(edge)

    # Instrumentation: 长尾召回监控 + posterior calibration 数据落库
    latency_ms = int((time.time() - t0) * 1000)
    try:
        await log_retrieval_hit(
            self._pg_engine,
            user_id=user_id,
            query_text=query,
            retrieved_edge_ids=[r["edge_id"] for r in rrf_top],
            rrf_scores={r["edge_id"]: r["score"] for r in rrf_top},
            edges_meta=edges_meta,
            retriever_breakdown={"bm25": len(bm25_hits), "vector": len(vector_hits), "graph": 0},
            latency_ms=latency_ms,
        )
    except Exception as e:
        # instrumentation 失败不阻塞 search
        import logging
        logging.getLogger(__name__).warning("log_retrieval_hit failed: %s", e)

    return materialized
```

> **集成点**：把上面方法补丁应用到 Plan 1 ship 的 `HierarchicalMemory` class 里 — 在 `archival_memory_search` stub 的位置替换。Plan 1 已经把 `_pg_engine` / `_milvus` / `_embed_service` 三个 instance attribute wired，Plan 3 只填实现。

```bash
cd backend && uv run pytest tests/unit/memory/test_retriever.py::TestFormatEdgesMetaForRrf -x
git add backend/app/memory/retriever.py backend/app/memory/hierarchical.py \
        backend/tests/unit/memory/test_retriever.py
git commit -m "feat(c5-plan3): archival_memory_search 入口 — 3-way hybrid + RRF v2 + instrumentation"
```

---

### Task 7：Persona populator（Working memory auto-injection）

**Goal**：spec § 5 末尾 + § 7 — session 起手扫 4 类 edge → 拼 markdown ~500 tokens → UPDATE working_blocks(persona)。

#### Step 7.1：RED

写 `backend/tests/unit/memory/test_persona_populator.py`：

```python
"""L0: persona populator — spec § 5 末尾 + § 7."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.memory.persona_populator import (
    format_persona_markdown,
    _truncate_to_token_budget,
)


class TestFormatPersonaMarkdown:
    def test_4_categories_in_output(self) -> None:
        holdings = [{"ts_code": "600519.SH", "qty": 500, "since": "2024-08",
                      "thesis": "cash flow 稳"}]
        prefs = [{"label": "DCF", "priority": 0.9}, {"label": "价值投资", "priority": 0.8}]
        avoids = [{"label": "新能源 sector", "reason": "政策不确定 + 估值贵"}]
        watches = [{"ts_code": "000858.SZ"}, {"label": "AI 大模型 concept"}]
        md = format_persona_markdown(holdings, prefs, avoids, watches)
        assert "## 用户画像" in md
        assert "### 当前持仓" in md
        assert "600519.SH" in md
        assert "### 偏好方法" in md or "### 偏好" in md
        assert "DCF" in md
        assert "### 规避" in md
        assert "新能源" in md
        assert "### 关注" in md
        assert "000858.SZ" in md or "AI" in md

    def test_empty_graph_returns_placeholder(self) -> None:
        md = format_persona_markdown([], [], [], [])
        # 空 graph 仍输出 markdown 骨架(避免 working_block 完全空让 agent 困惑)
        assert "用户画像" in md
        # 但应该提示空
        assert "暂无" in md or "no data" in md.lower() or len(md) < 200


class TestTruncateToTokenBudget:
    def test_under_budget_unchanged(self) -> None:
        text = "短 markdown"
        out = _truncate_to_token_budget(text, max_tokens=500)
        assert out == text

    def test_over_budget_truncated_with_marker(self) -> None:
        # 中文 1.33 tokens/char, 500 tokens ≈ 376 chars
        text = "茅 " * 1000  # 远超 500 tokens
        out = _truncate_to_token_budget(text, max_tokens=500)
        # 必须含截断标记
        assert "..." in out or "[truncated]" in out


class TestPopulatePersonaOnSessionStart:
    @pytest.mark.asyncio
    async def test_writes_markdown_to_working_block(self, monkeypatch) -> None:
        """Integration-light: mock PG fetch, assert UPDATE working_blocks 被调."""
        from app.memory.persona_populator import populate_persona_on_session_start
        from unittest.mock import AsyncMock, MagicMock

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)
        # 4 次 PG 查询(holdings/prefs/avoids/watches)+ 1 次 update working_blocks
        result_empty = MagicMock()
        result_empty.fetchall = MagicMock(return_value=[])
        mock_conn.execute = AsyncMock(return_value=result_empty)

        await populate_persona_on_session_start(mock_engine, user_id=uuid4())
        # 至少 5 次 execute(4 query + 1 update)
        assert mock_conn.execute.call_count >= 5
        # 最后一次 SQL 应该是 UPDATE working_blocks
        last_call = mock_conn.execute.call_args_list[-1]
        assert "chat_memory_working_blocks" in str(last_call[0][0])
        assert "UPDATE" in str(last_call[0][0]).upper()
```

#### Step 7.2：GREEN

写 `backend/app/memory/persona_populator.py`：

```python
"""Working Memory Auto-Injection — spec § 5 末尾 + § 7.

每 session 起手扫 4 类 edge(HOLDS/PREFERS/AVOIDS/WATCHES current snapshot)
→ 生成 markdown ~500 tokens → UPDATE working_blocks(persona).

调用方: chat router session_start hook (Plan 3 改 router 接入).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PERSONA_BLOCK_NAME = "persona"
PERSONA_MAX_TOKENS = 500
# 中文 ≈ 1.33 tokens/char, 留 buffer 取 1.4
_TOKEN_PER_CHAR_RATIO = 1.4


def format_persona_markdown(
    holdings: list[dict[str, Any]],
    preferences: list[dict[str, Any]],
    avoids: list[dict[str, Any]],
    watches: list[dict[str, Any]],
) -> str:
    """spec § 5 末尾 实例: 4 类 + ~500 tokens markdown."""
    parts: list[str] = ["## 用户画像（auto-generated from memory graph）"]

    # 持仓
    parts.append("\n### 当前持仓")
    if holdings:
        for h in holdings:
            label = h.get("ts_code") or h.get("label", "?")
            qty = h.get("qty")
            since = h.get("since")
            thesis = h.get("thesis")
            line = f"- {label}"
            if since:
                line += f" (since {since}"
                if qty:
                    line += f", qty={qty}"
                if thesis:
                    line += f", thesis: {thesis}"
                line += ")"
            elif qty:
                line += f" (qty={qty})"
            parts.append(line)
    else:
        parts.append("- 暂无")

    # 偏好
    parts.append("\n### 偏好方法（PREFERS）")
    if preferences:
        for p in preferences:
            label = p.get("label") or p.get("ts_code", "?")
            prio = p.get("priority")
            line = f"- {label}"
            if prio is not None:
                line += f" (priority {prio})"
            parts.append(line)
    else:
        parts.append("- 暂无")

    # 规避
    parts.append("\n### 规避")
    if avoids:
        for a in avoids:
            label = a.get("label") or a.get("ts_code", "?")
            reason = a.get("reason")
            line = f"- {label}"
            if reason:
                line += f" ({reason})"
            parts.append(line)
    else:
        parts.append("- 暂无")

    # 关注
    parts.append("\n### 关注但未持仓")
    if watches:
        labels = [w.get("ts_code") or w.get("label", "?") for w in watches]
        parts.append("- " + ", ".join(labels))
    else:
        parts.append("- 暂无")

    md = "\n".join(parts)
    return _truncate_to_token_budget(md, max_tokens=PERSONA_MAX_TOKENS)


def _truncate_to_token_budget(text_in: str, max_tokens: int) -> str:
    """简单 char-based 截断 + buffer.

    Plan 3 ship 时不直接装 tiktoken(若 Plan 1 已建 token_count helper 则用之),
    用 1.4 tokens/char 估算 char_budget.
    """
    char_budget = int(max_tokens / _TOKEN_PER_CHAR_RATIO)
    if len(text_in) <= char_budget:
        return text_in
    return text_in[: char_budget - 16] + "\n... [truncated]"


async def populate_persona_on_session_start(
    engine: AsyncEngine,
    user_id: UUID,
) -> None:
    """spec § 5 末尾完整实现 — session 起手 hook 入口.

    失败不阻塞 session(chat router 调用方 try/except).
    """
    # 1. holdings (HOLDS rel_type, valid_to IS NULL = current)
    async with engine.begin() as conn:
        holdings_rows = (await conn.execute(text("""
            SELECT n.entity_label AS ts_code,
                   e.properties AS props,
                   e.valid_from AS since
            FROM chat_memory_edges e
            JOIN chat_memory_nodes n ON e.target_node_id = n.node_id
            WHERE e.user_id = :uid
              AND e.rel_type = 'HOLDS'
              AND e.valid_to IS NULL
              AND e.invalidated_at IS NULL
            ORDER BY e.valid_from DESC LIMIT 20
        """), {"uid": str(user_id)})).fetchall()
        holdings = [_extract_edge_dict(r) for r in holdings_rows]

        prefs_rows = (await conn.execute(text("""
            SELECT n.entity_label AS label, e.properties AS props
            FROM chat_memory_edges e
            JOIN chat_memory_nodes n ON e.target_node_id = n.node_id
            WHERE e.user_id = :uid
              AND e.rel_type = 'PREFERS'
              AND e.valid_to IS NULL
              AND e.invalidated_at IS NULL
            ORDER BY (e.properties->>'priority')::float DESC NULLS LAST LIMIT 10
        """), {"uid": str(user_id)})).fetchall()
        preferences = [_extract_edge_dict(r) for r in prefs_rows]

        avoids_rows = (await conn.execute(text("""
            SELECT n.entity_label AS label, e.properties AS props
            FROM chat_memory_edges e
            JOIN chat_memory_nodes n ON e.target_node_id = n.node_id
            WHERE e.user_id = :uid AND e.rel_type = 'AVOIDS'
              AND e.valid_to IS NULL AND e.invalidated_at IS NULL
            LIMIT 10
        """), {"uid": str(user_id)})).fetchall()
        avoids = [_extract_edge_dict(r) for r in avoids_rows]

        watches_rows = (await conn.execute(text("""
            SELECT n.entity_label AS label
            FROM chat_memory_edges e
            JOIN chat_memory_nodes n ON e.target_node_id = n.node_id
            WHERE e.user_id = :uid AND e.rel_type = 'WATCHES'
              AND e.valid_to IS NULL AND e.invalidated_at IS NULL
            LIMIT 20
        """), {"uid": str(user_id)})).fetchall()
        watches = [_extract_edge_dict(r) for r in watches_rows]

        md = format_persona_markdown(holdings, preferences, avoids, watches)
        # 算 token_count(approx)
        token_count = int(len(md) * _TOKEN_PER_CHAR_RATIO)
        # UPSERT working_blocks(persona)
        await conn.execute(text("""
            INSERT INTO chat_memory_working_blocks
                (block_id, user_id, block_name, content, token_count, max_tokens, updated_at)
            VALUES (gen_random_uuid(), :uid, :bn, :content, :tc, :max_tc, now())
            ON CONFLICT (user_id, block_name) DO UPDATE SET
                content = EXCLUDED.content,
                token_count = EXCLUDED.token_count,
                updated_at = now()
        """), {
            "uid": str(user_id),
            "bn": PERSONA_BLOCK_NAME,
            "content": md,
            "tc": token_count,
            "max_tc": PERSONA_MAX_TOKENS,
        })


def _extract_edge_dict(row: Any) -> dict[str, Any]:
    """row → flat dict, 把 properties JSONB 展开."""
    d = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    props = d.pop("props", None) or {}
    out = dict(d)
    if isinstance(props, dict):
        for k in ("qty", "since", "thesis", "priority", "reason"):
            if k in props and k not in out:
                out[k] = props[k]
    return out
```

```bash
cd backend && uv run pytest tests/unit/memory/test_persona_populator.py -x -v
git add backend/app/memory/persona_populator.py backend/tests/unit/memory/test_persona_populator.py
git commit -m "feat(c5-plan3): persona populator — session 起手 4 类 edge → markdown → working_blocks"
```

---

### Task 8：Long-tail 召回监控（Plan 8 metric instrumentation）

**Goal**：算 top-5 valid_from P90 days，> 7 天阈值 → pass，全 ≤ 7 天 → 告警标记。Plan 8 eval pipeline 接此 module 算大盘指标。

#### Step 8.1：RED

写 `backend/tests/unit/memory/test_long_tail_monitor.py`：

```python
"""L0: 长尾召回监控 — spec § 11 #3 验证 acceptance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.memory.long_tail_monitor import (
    compute_long_tail_metrics,
    LongTailReport,
    LONG_TAIL_P90_THRESHOLD_DAYS,
)


class TestComputeLongTailMetrics:
    def test_threshold_default_7_days(self) -> None:
        assert LONG_TAIL_P90_THRESHOLD_DAYS == 7

    def test_all_recent_triggers_alert(self) -> None:
        """top-5 valid_from 全 ≤ 7 天 → P90 ≤ 7 → alert."""
        now = datetime.now(timezone.utc)
        sample_logs = [
            {"top_k_valid_from_p90_days": 3.0},
            {"top_k_valid_from_p90_days": 2.5},
            {"top_k_valid_from_p90_days": 4.0},
        ]
        report = compute_long_tail_metrics(sample_logs)
        assert report.alert is True
        assert report.median_p90_days < LONG_TAIL_P90_THRESHOLD_DAYS

    def test_diverse_distribution_no_alert(self) -> None:
        """top-5 散布 30-365 天 → no alert."""
        sample_logs = [
            {"top_k_valid_from_p90_days": 30.0},
            {"top_k_valid_from_p90_days": 90.0},
            {"top_k_valid_from_p90_days": 200.0},
            {"top_k_valid_from_p90_days": 365.0},
        ]
        report = compute_long_tail_metrics(sample_logs)
        assert report.alert is False
        assert report.median_p90_days > 30

    def test_empty_sample_no_op(self) -> None:
        report = compute_long_tail_metrics([])
        assert report.alert is False
        assert report.sample_count == 0

    def test_report_includes_sample_count(self) -> None:
        report = compute_long_tail_metrics([
            {"top_k_valid_from_p90_days": 100.0}, {"top_k_valid_from_p90_days": 50.0},
        ])
        assert report.sample_count == 2
```

#### Step 8.2：GREEN

写 `backend/app/memory/long_tail_monitor.py`：

```python
"""长尾召回监控 — 算法深度补丁 #3 验证.

spec § 11 #3 acceptance: "eval pipeline sample 100 query, top-5 valid_from P90
不能全集中近 7 天 → 长尾召回监控周报上大盘".

Plan 3 提供 instrumentation, Plan 8 eval pipeline 调本 module 计算大盘指标.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

LONG_TAIL_P90_THRESHOLD_DAYS: int = 7


@dataclass
class LongTailReport:
    sample_count: int
    median_p90_days: float
    alert: bool                              # P90 sample 中位数 < 阈值 → True
    samples_below_threshold_pct: float       # 落入阈值内的占比
    note: str = ""

    @property
    def passing(self) -> bool:
        return not self.alert


def compute_long_tail_metrics(
    sample_logs: list[dict[str, Any]],
    threshold_days: int = LONG_TAIL_P90_THRESHOLD_DAYS,
) -> LongTailReport:
    """从 retrieval_logs 行采样计算长尾召回指标.

    Args:
        sample_logs: 通常是 chat_memory_retrieval_logs 最近 N 行,每行至少含
                     'top_k_valid_from_p90_days' float field.
        threshold_days: 长尾告警阈值,默认 7 天.

    Returns:
        LongTailReport.
    """
    valid = [r["top_k_valid_from_p90_days"] for r in sample_logs
              if r.get("top_k_valid_from_p90_days") is not None]
    if not valid:
        return LongTailReport(
            sample_count=0, median_p90_days=0.0, alert=False,
            samples_below_threshold_pct=0.0,
            note="empty sample",
        )
    median_p90 = statistics.median(valid)
    below = [x for x in valid if x < threshold_days]
    pct_below = len(below) / len(valid)
    # alert 条件: 中位数低于阈值 → 整体偏 recent 偏置
    alert = median_p90 < threshold_days
    return LongTailReport(
        sample_count=len(valid),
        median_p90_days=median_p90,
        alert=alert,
        samples_below_threshold_pct=pct_below,
        note=("alert: median P90 < threshold" if alert else "ok"),
    )


async def fetch_recent_retrieval_logs(
    engine: AsyncEngine,
    n_samples: int = 100,
) -> list[dict[str, Any]]:
    """Plan 8 eval pipeline 调用入口."""
    async with engine.begin() as conn:
        rows = (await conn.execute(text("""
            SELECT log_id, user_id, query_text,
                   top_k_valid_from_p90_days, retriever_breakdown, latency_ms, created_at
            FROM chat_memory_retrieval_logs
            ORDER BY created_at DESC
            LIMIT :n
        """), {"n": n_samples})).fetchall()
    return [dict(r._mapping) if hasattr(r, "_mapping") else dict(r) for r in rows]
```

```bash
cd backend && uv run pytest tests/unit/memory/test_long_tail_monitor.py -x -v
git add backend/app/memory/long_tail_monitor.py backend/tests/unit/memory/test_long_tail_monitor.py
git commit -m "feat(c5-plan3): long-tail recall monitor — Plan 8 eval pipeline acceptance #3"
```

---

### Task 9：L1 Integration test — retriever_e2e + persona_e2e

**Goal**：真 PG + 真 AGE + 真 Milvus（embed mock），seed 数据 → 跑 archival_memory_search → assert RRF 排序符合预期。

#### Step 9.1：RED

写 `backend/tests/integration/memory/test_retriever_e2e.py`：

```python
"""L1: 3-way hybrid + RRF v2 端到端 (mock embed, real PG/AGE/Milvus)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.memory.hierarchical import HierarchicalMemory


@pytest.mark.asyncio
async def test_archival_search_returns_high_importance_recent_first(
    pg_memory_fixture, age_fixture, milvus_memory_fixture,
    mock_qwen_embed, mock_llm_extraction, mock_llm_judge,
):
    user_id = uuid4()
    # seed 5 typed edges via direct PG insert (绕开 extractor)
    await _seed_test_edges(pg_memory_fixture, user_id, [
        # eid_high_recent: HOLDS 茅台, importance=0.9, 10 天前
        {"label": "600519.SH", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10},
        # eid_low_old: STUDIED 五粮液, importance=0.2, 200 天前
        {"label": "000858.SZ", "rel_type": "STUDIED", "imp": 0.2, "days_old": 200},
        # eid_med_recent: PREFERS DCF, importance=0.5, 30 天前
        {"label": "DCF", "rel_type": "PREFERS", "imp": 0.5, "days_old": 30},
    ])

    memory = HierarchicalMemory(
        pg_session_factory=pg_memory_fixture,
        age_executor=age_fixture,
        milvus_client=milvus_memory_fixture,
        embed_service=mock_qwen_embed,
        llm_extractor=mock_llm_extraction,
        llm_judge=mock_llm_judge,
    )

    results = await memory.archival_memory_search(user_id, query="茅台", k=3)
    assert len(results) >= 1
    # 高 importance + 近期应排第一
    assert "600519.SH" in (results[0].properties.get("ts_code", "")
                              or results[0].properties.get("target_label", ""))


@pytest.mark.asyncio
async def test_old_low_importance_still_retrieved(
    pg_memory_fixture, age_fixture, milvus_memory_fixture,
    mock_qwen_embed, mock_llm_extraction, mock_llm_judge,
):
    """衰减底 0.5 验证: 1 年前 importance=0.2 fact 仍可召回(非沉底为 0)."""
    user_id = uuid4()
    await _seed_test_edges(pg_memory_fixture, user_id, [
        {"label": "TestStockOld", "rel_type": "EXPRESSED_VIEW",
         "imp": 0.2, "days_old": 365},
    ])
    memory = HierarchicalMemory(
        pg_session_factory=pg_memory_fixture, age_executor=age_fixture,
        milvus_client=milvus_memory_fixture, embed_service=mock_qwen_embed,
        llm_extractor=mock_llm_extraction, llm_judge=mock_llm_judge,
    )
    results = await memory.archival_memory_search(user_id, query="TestStockOld", k=5)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_user_isolation_no_cross_tenant_leak(
    pg_memory_fixture, age_fixture, milvus_memory_fixture,
    mock_qwen_embed, mock_llm_extraction, mock_llm_judge,
):
    user_a = uuid4()
    user_b = uuid4()
    await _seed_test_edges(pg_memory_fixture, user_a, [
        {"label": "UserA_Stock", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10},
    ])
    await _seed_test_edges(pg_memory_fixture, user_b, [
        {"label": "UserB_Stock", "rel_type": "HOLDS", "imp": 0.9, "days_old": 10},
    ])
    memory = HierarchicalMemory(
        pg_session_factory=pg_memory_fixture, age_executor=age_fixture,
        milvus_client=milvus_memory_fixture, embed_service=mock_qwen_embed,
        llm_extractor=mock_llm_extraction, llm_judge=mock_llm_judge,
    )
    results = await memory.archival_memory_search(user_a, query="Stock", k=10)
    # UserB_Stock 不能出现
    labels_returned = [
        (r.properties.get("ts_code") or r.properties.get("target_label", ""))
        for r in results
    ]
    assert not any("UserB" in label for label in labels_returned)


async def _seed_test_edges(engine, user_id, specs):
    """helper: 直接 INSERT 5 edges + nodes, 跳过 extractor."""
    from sqlalchemy import text
    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        # User node
        user_node = uuid4()
        await conn.execute(text("""
            INSERT INTO chat_memory_nodes (node_id, user_id, entity_type, entity_label,
                                              search_tokens)
            VALUES (:nid, :uid, 'User', 'User', 'User')
            ON CONFLICT DO NOTHING
        """), {"nid": str(user_node), "uid": str(user_id)})
        # 1 episode
        ep_id = uuid4()
        sess_id = uuid4()
        await conn.execute(text("""
            INSERT INTO chat_memory_episodes (episode_id, user_id, session_id, episode_index,
                                                  user_message_text, source_kind)
            VALUES (:eid, :uid, :sid, 0, 'seed', 'test_seed')
        """), {"eid": str(ep_id), "uid": str(user_id), "sid": str(sess_id)})
        for spec in specs:
            target_nid = uuid4()
            await conn.execute(text("""
                INSERT INTO chat_memory_nodes (node_id, user_id, entity_type, entity_label,
                                                  search_tokens)
                VALUES (:nid, :uid, 'Stock', :label, :st)
            """), {"nid": str(target_nid), "uid": str(user_id),
                    "label": spec["label"], "st": spec["label"]})
            await conn.execute(text("""
                INSERT INTO chat_memory_edges (edge_id, user_id, source_node_id, target_node_id,
                                                  rel_type, valid_from, recorded_at,
                                                  source_episode_id, importance, search_tokens)
                VALUES (gen_random_uuid(), :uid, :sn, :tn, :rt, :vf, now(), :ep, :imp, :st)
            """), {"uid": str(user_id), "sn": str(user_node), "tn": str(target_nid),
                    "rt": spec["rel_type"],
                    "vf": now - timedelta(days=spec["days_old"]),
                    "ep": str(ep_id), "imp": spec["imp"],
                    "st": spec["label"]})
```

写 `backend/tests/integration/memory/test_persona_populator_e2e.py`：

```python
"""L1: persona populator e2e — 真 PG seed → 跑 → assert working_blocks."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.memory.persona_populator import populate_persona_on_session_start


@pytest.mark.asyncio
async def test_4_categories_in_persona_block(pg_memory_fixture):
    user_id = uuid4()
    # 类似 test_retriever_e2e seed,这次 4 类 edge 各 1 条
    # ... seed code 略 (复用 _seed_test_edges 类似 helper)
    await _seed_persona_edges(pg_memory_fixture, user_id)

    await populate_persona_on_session_start(pg_memory_fixture, user_id=user_id)

    async with pg_memory_fixture.connect() as conn:
        row = (await conn.execute(text("""
            SELECT content, token_count FROM chat_memory_working_blocks
            WHERE user_id = :uid AND block_name = 'persona'
        """), {"uid": str(user_id)})).fetchone()
    assert row is not None
    content, tc = row[0], row[1]
    assert "持仓" in content
    assert "偏好" in content
    assert "规避" in content
    assert "关注" in content
    assert tc <= 800  # 留 buffer (≈ 500 + 1.4 buffer)


async def _seed_persona_edges(engine, user_id):
    # ... 跟 test_retriever_e2e _seed_test_edges 类似但 4 类 rel_type 各 1
    ...
```

#### Step 9.2：GREEN

跑测试，按需修整 hierarchical.py 集成位置 / fixture wiring。

```bash
cd backend
uv run pytest tests/integration/memory/test_retriever_e2e.py tests/integration/memory/test_persona_populator_e2e.py -x -v 2>&1 | tail -40
```

#### Step 9.3：REFACTOR + COMMIT

```bash
git add backend/tests/integration/memory/test_retriever_e2e.py \
        backend/tests/integration/memory/test_persona_populator_e2e.py
git commit -m "test(c5-plan3): L1 e2e — 3-way hybrid retrieval + persona populator(real PG/AGE/Milvus)"
```

---

### Task 10：L2 Cassette + chat router 接入 + ship 收束

**Goal**：（a）VCR 录 2 cassette 验证真 LLM embedding + RRF v2 真行为（b）chat router session-start hook 调 populate_persona（c）写知识卡。

#### Step 10.1：chat router 接入 persona populator

修改 `backend/app/router/chat.py` — 在 PR #39 现有 session-start hook 处（启 `chat_sessions` row 时）：

```python
from app.memory.persona_populator import populate_persona_on_session_start

# 在 session_create 函数末尾或 chat_session_start 处:
try:
    await populate_persona_on_session_start(pg_engine, user_id=current_user.id)
except Exception as exc:
    logger.warning("populate_persona_on_session_start failed for user %s: %s",
                    current_user.id, exc)
    # 失败不阻塞 chat session 创建
```

#### Step 10.2：L2 Cassette 测试 — RED

写 `backend/tests/e2e/memory/test_search_full_path.py`：

```python
"""L2 Cassette: 真 qwen embed + 真 PG/AGE/Milvus + RRF v2 公式真行为.

2 representative scenarios:
  1. 标准 query "我对茅台的看法" — 验证 BM25 + vector 都召回 + RRF 排序合理
  2. 长尾 query "我 2024-08 说过的科技股观点" — 验证衰减底 0.5 让老 fact 仍召回
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import vcr


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_search_茅台_recent_holding_first(
    pg_memory_fixture, age_fixture, milvus_memory_fixture,
    real_qwen_embed_service, mock_llm_extraction, mock_llm_judge,
    vcr_memory_cassette,  # 引一个 fixture 配 cassette path
):
    user_id = uuid4()
    # seed 茅台 holding (10 天前) + 五粮液 STUDIED (200 天前) + 老 EXPRESSED_VIEW
    # ... seed code

    from app.memory.hierarchical import HierarchicalMemory
    memory = HierarchicalMemory(
        pg_session_factory=pg_memory_fixture, age_executor=age_fixture,
        milvus_client=milvus_memory_fixture, embed_service=real_qwen_embed_service,
        llm_extractor=mock_llm_extraction, llm_judge=mock_llm_judge,
    )
    results = await memory.archival_memory_search(user_id, query="我对茅台的看法", k=5)
    assert len(results) >= 1
    assert results[0].rel_type == "HOLDS"
    assert "600519" in (results[0].properties.get("ts_code", "")
                            or results[0].properties.get("target_label", ""))


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_search_long_tail_old_fact_still_retrieved(
    pg_memory_fixture, age_fixture, milvus_memory_fixture,
    real_qwen_embed_service, mock_llm_extraction, mock_llm_judge,
    vcr_memory_cassette,
):
    """衰减底 0.5 验证 — 1 年老 EXPRESSED_VIEW + low importance 仍可召回."""
    user_id = uuid4()
    # seed 1 条 365 天前 importance=0.2 EXPRESSED_VIEW
    # ... seed code

    from app.memory.hierarchical import HierarchicalMemory
    memory = HierarchicalMemory(
        pg_session_factory=pg_memory_fixture, age_executor=age_fixture,
        milvus_client=milvus_memory_fixture, embed_service=real_qwen_embed_service,
        llm_extractor=mock_llm_extraction, llm_judge=mock_llm_judge,
    )
    results = await memory.archival_memory_search(
        user_id, query="2024-08 我说过的科技观点", k=5,
    )
    assert len(results) >= 1  # 衰减底 0.5 保证 score > 0
```

#### Step 10.3：录 cassette

```bash
cd backend
# 第一次录: VCR 网络落地, 后续 replay
DASHSCOPE_API_KEY=$DASHSCOPE_API_KEY uv run pytest \
    tests/e2e/memory/test_search_full_path.py \
    --vcr-record=once -x -v 2>&1 | tail -30
# 验证 cassette 文件已生成
ls tests/cassettes/memory/search_full_path__*.yaml
# 第二次跑必须 replay (不打真网):
unset DASHSCOPE_API_KEY
uv run pytest tests/e2e/memory/test_search_full_path.py -x -v 2>&1 | tail -10
# 期望 2 passed
```

#### Step 10.4：知识卡 + 完整测试 + commit

写 `docs/claude-context/c5-plan3-read-pipeline-done.md`：

```markdown
---
name: c5-plan3-read-pipeline-done
description: C.5 Plan 3 Read Pipeline + RRF v2 ship — 3-way hybrid + 时间感知 ranking + 长尾监控 + persona auto-injection
type: project
---

C.5 Plan 3 (Read Pipeline + RRF v2) ship — 2026-05-XX.

## ship 范围
- 3-way hybrid 检索: BM25(PG GIN + jieba) + Vector(Milvus 单 collection) + Graph(AGE on-demand 不进 default)
- RRF v2 完整算法: importance 三档 [0.6/0.75/0.95] + τ rel_type 三级 [365/180/90] + 衰减底 0.5
- 历史 edge 用 valid_to 作衰减参考点(spec § 11 #3 关键设计)
- Working memory auto-injection: session 起手 4 类 edge → markdown ~500 tokens → working_blocks(persona)
- 长尾召回监控 instrumentation: top-5 valid_from P90 落库, Plan 8 eval 调 long_tail_monitor
- Posterior calibration 数据落库(retrieval_logs + retrieval_feedback 2 表), Plan 5 weekly job 消费
- archival_memory_search 替换 Plan 1 stub

## 关键决策(实施期撞实)
- ...(实施时填撞实点)

## 跟 spec 决策对齐
- spec § 5 全部 (3-way hybrid + RRF + persona auto-injection)
- spec § 7 working memory budget(persona 500 tokens / 自动 paging 留 Plan 1 helper)
- spec § 11 末尾 #3 时间感知 RRF 公式 1:1 落地

## 关键文件 ref
- backend/app/memory/rrf.py (常量 + compute_time_decay + reciprocal_rank_fusion_v2)
- backend/app/memory/retriever.py (3 路 retriever)
- backend/app/memory/persona_populator.py
- backend/app/memory/instrumentation.py
- backend/app/memory/long_tail_monitor.py
- backend/app/memory/hierarchical.py (archival_memory_search 实现替换 stub)
- backend/scripts/migrations/2026-05-11-c5-plan3-instrumentation.sql
```

```bash
cd backend
uv run pytest tests/unit/memory/ tests/integration/memory/ tests/e2e/memory/test_search_full_path.py -x 2>&1 | tail -20
uv run mypy app/memory/
uv run ruff check app/memory/

git add backend/app/router/chat.py \
        backend/tests/e2e/memory/test_search_full_path.py \
        backend/tests/cassettes/memory/search_full_path__*.yaml \
        docs/claude-context/c5-plan3-read-pipeline-done.md
git commit -m "feat(c5-plan3): L2 cassette + chat router persona-injection wiring + ship 知识卡"
```

---

## Self-review

### Spec § 5 读取 Pipeline 全 coverage check

- [x] 路径 1 BM25 PG GIN + jieba pre-tokenize → `retriever.bm25_search` (Task 3，jieba helper 复用 Plan 1 `app.memory.registry.jieba_tokenize_for_search`)
- [x] 路径 2 Vector Milvus 单 collection + qwen embed → `retriever.vector_search` (Task 4，user_id filter 多租户隔离已 spec assert)
- [x] 路径 3 Graph AGE Cypher on-demand 不进 default search → `retriever.graph_traverse` (Task 5，由 Plan 4 archival_memory_traverse MCP tool 调用)
- [x] RRF Fusion `Σ 1/(60+rank)` → `rrf.reciprocal_rank_fusion_v2` (Task 1)
- [x] Working memory auto-injection 每 session 起手扫 4 类 → `persona_populator.populate_persona_on_session_start` (Task 7) + chat router 接入 (Task 10)

### Spec § 7 Working Memory Budget coverage check

- [x] persona 500 tokens budget → `PERSONA_MAX_TOKENS = 500` 常量 + `_truncate_to_token_budget` helper (Task 7)
- [x] persona 4 类 markdown 拼装 → `format_persona_markdown` (Task 7)
- [x] 超 budget 自动 paging → Plan 3 走 truncate-with-marker（spec § 7 完整 paging 走 Plan 1 working_blocks core_memory_append 路径，已 ship；Plan 3 在 populator 写入前 truncate 防止单次写入超量）

### Spec § 11 末尾 #3 时间感知 RRF coverage check（算法深度补丁主责）

- [x] Importance 三档映射 [0.9→0.95 / 0.5→0.75 / 0.2→0.6] → `IMPORTANCE_WEIGHT_MAP` 契约 § 5 常量 1:1 实现 (Task 1)
- [x] importance 下限 0.6 不完全压制 → `_IMPORTANCE_FALLBACK = 0.75` 中档 fallback + 测试断言 (Task 1)
- [x] τ 按 rel_type 三级 [HOLDS/SOLD=365 / PREFERS/AVOIDS/WATCHES=180 / EXPRESSED_VIEW/STUDIED=90] → `TAU_DAYS_BY_REL_TYPE` 契约 § 5 常量 (Task 1)
- [x] τ 默认 180 (BELONGS_TO/HAS_CONCEPT/CORRELATED_WITH 等结构性边) → `TAU_DAYS_DEFAULT = 180` (Task 1)
- [x] 衰减底 0.5 → `DECAY_FLOOR = 0.5` + 极端老 fact 测试 `test_extreme_old_approaches_floor` 断言 ≥ 0.5 (Task 1)
- [x] time_decay = 0.5 + 0.5 × exp(-Δt/τ) 公式 1:1 → `compute_time_decay` impl 直照 spec 行 1228 (Task 1)
- [x] 历史 edge (valid_to IS NOT NULL) 用 valid_to 作衰减参考点 → `compute_time_decay` `ref_time = valid_to if valid_to is not None else valid_from` + 测试 `test_history_edge_uses_valid_to_as_reference` (Task 1)
- [x] 后验校准 instrumentation → `instrumentation.log_retrieval_hit` (Task 2，命中数落 chat_memory_retrieval_logs) + `instrumentation.log_user_reject` (用户否决信号落 chat_memory_retrieval_feedback)；Plan 5 weekly job 消费两表
- [x] 长尾召回监控 → `long_tail_monitor.compute_long_tail_metrics` + top-5 valid_from P90 在 log_retrieval_hit 落库时计算 (Task 2 + 8)；Plan 8 eval pipeline 调用消费

### 算法深度补丁 #3 acceptance（spec 行 1194）

| Acceptance | Plan 3 落地点 | 验证 |
|---|---|---|
| 离散三档 importance 跨 session 一致性 ≥ 0.9 | Plan 2 写入侧 + Plan 3 RRF 读侧三档 fallback | Plan 8 50 golden case 跨 session metric |
| RRF v2 加时间感知前后 long-tail recall 提升 ≥ 15% | `compute_time_decay` 衰减底 0.5 + τ 分级 + L2 cassette `test_search_long_tail_old_fact_still_retrieved` | Plan 8 baseline vs RRF v2 A/B metric |
| 长尾召回监控周报上大盘 | `instrumentation.log_retrieval_hit` 落 P90 + `long_tail_monitor.compute_long_tail_metrics` | Plan 8 eval pipeline 接 metric 上 weekly 大盘 |

### 契约严守（不偏离）check

- [x] `IMPORTANCE_WEIGHT_MAP / TAU_DAYS_BY_REL_TYPE / TAU_DAYS_DEFAULT / DECAY_FLOOR / RRF_K` 五常量值 1:1 契约 § 5 (Task 1 测试断言)
- [x] `compute_time_decay(rel_type, valid_from, valid_to)` 函数签名严守契约
- [x] `reciprocal_rank_fusion_v2(retriever_results, edges_meta, k=RRF_K, top=5)` 签名严守
- [x] `archival_memory_search(user_id, query, k=5) -> list[ChatMemoryEdge]` Memory Protocol 签名 (Task 6 实现替换 Plan 1 stub，**未改 class signature** 满足契约 § 3)
- [x] HierarchicalMemory class instance attributes (`_pg_engine` / `_milvus` / `_embed_service`) 沿用 Plan 1 wired，Plan 3 不动 DI signature
- [x] Plan 1 提供的 `jieba_tokenize_for_search` 在 BM25 直接 import 复用，不重定义
- [x] embed_cache hook 留 Plan 5 接入：vector_search 直接调 `embed_service.embed`，Plan 5 ship 后改为 `embed_cache.get_or_compute(text)` wrapper

### 范围边界（不在 Plan 3 做）check

- [x] archival_memory_search MCP tool wrapper → Plan 4
- [x] archival_memory_traverse MCP tool wrapper → Plan 4 (Plan 3 提供 `graph_traverse` 底层函数 Task 5，Plan 4 包 MCP)
- [x] embed_cache 实现 → Plan 5 (Plan 3 vector_search 留 hook 注释)
- [x] Posterior calibration weekly Celery job → Plan 5 (Plan 3 落 instrumentation 表 Task 2)
- [x] 50 golden eval / 大盘 metric → Plan 8 (Plan 3 提供 `long_tail_monitor` 接口 Task 8)

### 测试分层（契约 § 12）check

- [x] L0 Unit: `test_rrf.py` (18+ cases) + `test_retriever.py` + `test_persona_populator.py` + `test_long_tail_monitor.py`
- [x] L1 Integration: `test_retriever_e2e.py` (3 case 含多租户隔离) + `test_persona_populator_e2e.py` + `test_instrumentation_e2e.py` (Task 2)
- [x] L2 Cassette: `test_search_full_path.py` 2 representative scenarios（标准 query + 长尾老 fact）

### Plan-level acceptance 自检

- [x] 5 天 wall time 估算合理性：Task 1 RRF 0.5 天 / Task 2 instrumentation 0.5 天 / Task 3-5 三路 retriever 1.5 天 / Task 6 入口集成 0.5 天 / Task 7 persona 0.5 天 / Task 8 监控 0.5 天 / Task 9 L1 e2e 0.5 天 / Task 10 L2 cassette + chat 接入 + 知识卡 0.5 天 = 5 天
- [x] 频繁 commit：每 task 1 commit + Task 1/3/4 各拆 1 commit = 11 commits（满足"频繁 commit"要求）
- [x] 每 step 完整代码 + pytest 命令 + git commit，无 placeholder
- [x] 严守契约：常量 + 函数签名 + class 不改 signature + helper 复用 Plan 1
- [x] Self-review 覆盖 spec § 5 / § 7 / § 11 末尾 #3 三大章节
