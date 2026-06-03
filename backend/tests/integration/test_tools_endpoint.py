import pytest
from app.router.chat import router
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


class _StubMCP:
    async def list_tools(self):
        return [
            {
                "name": "get_stock_quote",
                "description": "quote",
                "inputSchema": {"type": "object", "required": ["ts_code"]},
            },
            {
                "name": "kb_search",
                "description": "kb",
                "inputSchema": {"type": "object", "required": ["query"]},
            },
        ]


def _client_with_mcp(mcp) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.mcp_client = mcp
    return TestClient(app)


def test_list_tools_returns_mcp_metadata() -> None:
    client = _client_with_mcp(_StubMCP())
    r = client.get("/api/v0/tools")
    assert r.status_code == 200
    body = r.json()
    names = [t["name"] for t in body["tools"]]
    assert names == ["get_stock_quote", "kb_search"]
    assert body["tools"][0]["inputSchema"]["required"] == ["ts_code"]


def test_list_tools_503_when_mcp_missing() -> None:
    app = FastAPI()
    app.include_router(router)
    app.state.mcp_client = None
    r = TestClient(app).get("/api/v0/tools")
    assert r.status_code == 503
