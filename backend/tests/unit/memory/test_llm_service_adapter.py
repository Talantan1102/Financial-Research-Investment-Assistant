"""LLMService → 记忆抽取层客户端协议适配器测试。

对话流评估冒烟发现(2026-06-05 #3):LLMExtractor/ConflictResolver 期望
``async chat(prompt, system, model, max_tokens) -> str``,而生产两处 wiring
(MCP _common.py / Celery tasks/memory.py)直接塞 LLMService(同步,
``chat(prompt, tier, schema) -> LLMResponse``),真实 LLM 下批量抽取
全灭于 TypeError、被 failure_matrix 吞成 retry 耗尽。
"""

from __future__ import annotations

from typing import Any

from app.memory.llm_service_adapter import MemoryLLMClientAdapter


class _FakeLLMService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(self, prompt: str, tier: str = "fast", schema: Any = None) -> Any:
        self.calls.append({"prompt": prompt, "tier": tier, "schema": schema})

        class _Resp:
            content = '{"facts": []}'

        return _Resp()


async def test_adapter_folds_system_into_prompt_and_returns_str() -> None:
    svc = _FakeLLMService()
    adapter = MemoryLLMClientAdapter(svc, tier="fast")
    raw = await adapter.chat(
        prompt="抽取这段对话",
        system="你是抽取器",
        model="ignored-by-tier-router",
        max_tokens=2000,
    )
    assert isinstance(raw, str)
    assert raw == '{"facts": []}'
    assert len(svc.calls) == 1
    sent = svc.calls[0]
    assert sent["tier"] == "fast"
    # system 提示折叠进 prompt 开头,语义不丢
    assert sent["prompt"].startswith("你是抽取器")
    assert "抽取这段对话" in sent["prompt"]


async def test_adapter_without_system() -> None:
    svc = _FakeLLMService()
    adapter = MemoryLLMClientAdapter(svc)
    raw = await adapter.chat(prompt="只有用户提示")
    assert raw == '{"facts": []}'
    assert svc.calls[0]["prompt"] == "只有用户提示"
