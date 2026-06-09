"""LLMService → 记忆抽取层客户端协议适配器。

记忆模块(LLMExtractor / ConflictResolver / batch_extractor)写在
``async chat(prompt, system, model, max_tokens) -> str`` 协议上;
应用层真实客户端是 LLMService(同步, ``chat(prompt, tier, schema) -> LLMResponse``)。
两处生产 wiring(MCP tools/_common.py 与 Celery tasks/memory.py)曾直接把
LLMService 当抽取客户端塞入,真实 LLM 下抽取调用全灭于
``TypeError: unexpected keyword argument 'system'``、被 failure_matrix 吞掉
(2026-06-05 对话流评估冒烟发现 #3)。本适配器是唯一的合法桥。

语义映射:
- system 折叠进 prompt 开头(LLMService 单 prompt 接口)
- model/max_tokens 忽略 —— LLMService 由 tier 路由选模型,档位在构造时定
"""

from __future__ import annotations

from typing import Any


class MemoryLLMClientAdapter:
    def __init__(self, llm_service: Any, tier: str = "fast") -> None:
        self._svc = llm_service
        self._tier = tier

    async def chat(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        resp = self._svc.chat(prompt=full_prompt, tier=self._tier)
        return str(resp.content)
