# 测试指南

## 测试结构

```
backend/
├── app/
│   ├── mcp_server/
│   │   └── tests/           # MCP Server 单元测试
│   └── mcp_client/
│       └── tests/           # MCP Client 单元测试
└── tests/
    ├── integration/         # 集成测试
    └── e2e/                 # 端到端测试
```

## 运行测试

### 单元测试

```bash
# MCP Server 测试
python -m pytest backend/app/mcp_server/tests/ -v

# MCP Client 测试
python -m pytest backend/app/mcp_client/tests/ -v
```

### 集成测试

```bash
# 需要先启动 MCP Server
python -m pytest backend/tests/integration/ -v
```

### 端到端测试

```bash
# 需要完整环境
python -m pytest backend/tests/e2e/ -v
```

## 测试命名规范

| 测试类型 | 文件名格式 | 示例 |
|----------|-----------|------|
| 单元测试 | `test_<模块>.py` | `test_client.py` |
| 集成测试 | `test_integration_*.py` | `test_integration_mcp.py` |
| E2E 测试 | `test_e2e_*.py` | `test_e2e_research.py` |

## 测试用例规范

### 单元测试示例

```python
import pytest

@pytest.mark.asyncio
async def test_mcp_client_connect():
    """测试 MCP Client 连接"""
    client = MCPClient(server_script_path="...")
    assert await client.connect()
    assert client.is_connected
    await client.disconnect()
```

### 集成测试示例

```python
@pytest.mark.asyncio
async def test_tool_adapter_with_mcp():
    """测试 ToolAdapter MCP 调用"""
    async with MCPClient("...") as client:
        adapter = ToolAdapter(mcp_client=client)
        result = await adapter.get_quote("sh600519")
        assert result["success"]
```

## 测试数据

测试数据存放在 `backend/tests/data/` 目录：

```
backend/tests/data/
├── mock_responses/          # Mock 响应数据
├── fixtures/                # 测试夹具
└── samples/                 # 样本数据
```

## 环境配置

### 测试环境变量

```bash
# .env.test
USE_MCP=true
MCP_TIMEOUT=30.0
TEST_DB_URL=postgresql://localhost/test_db
```

### pytest 配置

```ini
# pytest.ini
[pytest]
testpaths = backend/app/mcp_server/tests backend/app/mcp_client/tests backend/tests
asyncio_mode = auto
```

## 测试报告

测试报告归档在 `docs/testing/test-reports/` 目录。

### 历史报告

| 日期 | 报告 | 说明 |
|------|------|------|
| 2026-03-08 | [E2E 测试报告](./test-reports/E2E_TEST_REPORT.md) | 端到端测试 |
| 2026-03-08 | [QA 测试报告](./test-reports/QA_TEST_REPORT.md) | QA 验收测试 |
| 2026-03-08 | [自定义 URL 测试](./test-reports/CUSTOM_URL_TEST_REPORT.md) | 自定义 URL 功能 |

## 持续集成

建议在 CI 中运行：

```yaml
# .github/workflows/test.yml
- name: Run Unit Tests
  run: |
    pytest backend/app/mcp_server/tests/ -v
    pytest backend/app/mcp_client/tests/ -v

- name: Run Integration Tests
  run: pytest backend/tests/integration/ -v
```
