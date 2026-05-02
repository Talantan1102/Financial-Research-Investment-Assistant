"""MockKbSearchService — KB_MODE=mock backend.

返回固定 stub 数据(不调外部 API);开发期 / 测试用,L2 cassette 不依赖此实现。
"""

from __future__ import annotations

from typing import Any

from app.services.kb_search_service import KbHit

_STUB_HITS = [
    KbHit(
        chunk_id="mock_research::0",
        chunk_text="模拟研报片段:招商证券对宁德时代未来 5 年新能源车电池业务展望乐观。",
        similarity=0.92,
        metadata={
            "doc_id": "mock_research_001",
            "source_type": "research",
            "broker": "招商证券",
            "industry": "新能源",
            "rating": "买入",
            "pub_date": "2024-06-01",
        },
    ),
    KbHit(
        chunk_id="mock_financial::0",
        chunk_text="模拟财报片段:贵州茅台 2024 年 Q3 营收同比增长 18%。",
        similarity=0.85,
        metadata={
            "doc_id": "mock_financial_001",
            "source_type": "financial",
            "company_code": "600519",
            "company_name": "贵州茅台",
            "fiscal_year": 2024,
            "fiscal_quarter": "Q3",
            "pub_date": "2024-10-31",
        },
    ),
    KbHit(
        chunk_id="mock_policy::0",
        chunk_text="模拟政策片段:第三条 新能源车补贴标准按续航里程分级核算。",
        similarity=0.78,
        metadata={
            "doc_id": "mock_policy_001",
            "source_type": "policy",
            "issuer": "国家发改委",
            "doc_number": "发改能源[2024]100号",
            "pub_date": "2024-01-15",
        },
    ),
]


class MockKbSearchService:
    """KB_MODE=mock backend.

    Mock 行为:
      - 不实际 embedding / Milvus
      - 返回固定 3 条 stub(每类 corpus 一条)
      - 按 collections / top_k 简单过滤
    """

    async def search(
        self,
        query: str,
        collections: list[str] | None = None,
        top_k: int = 5,
        threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[KbHit]:
        results = list(_STUB_HITS)
        if collections:
            target_types = {c.replace("kb_", "") for c in collections}
            results = [h for h in results if h.metadata.get("source_type") in target_types]
        if threshold is not None:
            results = [h for h in results if h.similarity >= threshold]
        return results[:top_k]
