"""build_kb_search_service_from_env — KB_MODE switch."""

from __future__ import annotations

import os

from app.services.embedding_factory import build_embedding_service_from_env
from app.services.kb_search_service import KbSearchService, MilvusKbSearchService
from app.services.milvus_client import MilvusKbClient
from app.services.mock_kb_service import MockKbSearchService
from app.services.reliable_kb_service import ReliableKbSearchService


def build_kb_search_service_from_env() -> KbSearchService:
    """Build KbSearchService based on KB_MODE env var.

    Modes:
      - "mock"(default): MockKbSearchService(returns stub data)
      - "real": MilvusKbSearchService wrapped in ReliableKbSearchService
    """
    mode = os.getenv("KB_MODE", "mock")
    if mode == "mock":
        return MockKbSearchService()
    if mode == "real":
        host = os.environ.get("MILVUS_HOST", "127.0.0.1")
        port = int(os.environ.get("MILVUS_PORT", "19530"))
        milvus = MilvusKbClient(host=host, port=port)
        embedding = build_embedding_service_from_env()
        inner = MilvusKbSearchService(milvus=milvus, embedding_service=embedding)
        return ReliableKbSearchService(inner=inner)
    raise ValueError(f"Unknown KB_MODE: {mode!r}; expected 'mock' or 'real'")
