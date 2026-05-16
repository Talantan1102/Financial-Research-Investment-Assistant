"""LLMSwapper — OpenRouter API wrapper for evaluator LLM swap.

spec § 4.1 决策 1 / § 5.3:Pipeline-as-SUT 评估的核心组件,允许 BacktestRunner
在运行时切换 evaluator LLM。生产 path 不受影响(OpenAIAdapter 走 dashscope)。

支持的 evaluator model(spec § 4.1 决策 1 选 cutoff < 2024):
  - gpt-4o-2024-05-13       (cutoff 2023-10)
  - qwen2.5-72b-instruct    (cutoff 2023-10)
  - deepseek-v3             (cutoff 早期 2024)

Cross-LLM 矩阵(决策 8.2)额外支持:
  - deepseek-v4-flash       (生产模型,cutoff 2026-04 — 只跑 sanity case)
  - claude-sonnet-4         (可选)
  - gpt-4-turbo             (可选)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import cast

import httpx
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject, ResponseFormatText

# Backtest 主线 evaluator (spec § 4.1 决策 1):cutoff < 2024 的 3 LLM cross-check
BACKTEST_EVALUATOR_MODELS: tuple[str, ...] = (
    "gpt-4o-2024-05-13",
    "qwen2.5-72b-instruct",
    "deepseek-v3",
)

# Cross-LLM 矩阵 (spec § 4.8.2):上述 3 个 + 生产 + 可选
CROSS_LLM_MATRIX_MODELS: tuple[str, ...] = (
    *BACKTEST_EVALUATOR_MODELS,
    "deepseek-v4-flash",
    "claude-sonnet-4",
    "gpt-4-turbo",
)

# 公共白名单
EVALUATOR_MODELS: tuple[str, ...] = CROSS_LLM_MATRIX_MODELS

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class EvaluatorClient:
    """已绑定 model id 的 OpenAI-compatible client.

    暴露 chat(prompt, response_format) 形态,与 LLMService.chat 类似但不走 dashscope。
    """

    model: str
    api_key: str = field(repr=False)
    _client: OpenAI

    def chat(
        self,
        prompt: str,
        response_format: ResponseFormatJSONObject | ResponseFormatText | None = None,
    ) -> str:
        """Chat completion via OpenRouter, 返回 content str."""
        messages: list[ChatCompletionMessageParam] = [
            cast(ChatCompletionMessageParam, {"role": "user", "content": prompt})
        ]
        create_kwargs: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 8000,
        }
        if response_format is not None:
            create_kwargs["response_format"] = response_format
        r = self._client.chat.completions.create(**create_kwargs)  # type: ignore[call-overload]
        return r.choices[0].message.content or ""


class LLMSwapper:
    """Evaluator LLM swap orchestrator.

    使用方式:
        swapper = LLMSwapper()  # 从 env 读 OPENROUTER_API_KEY
        client = swapper.get_client("gpt-4o-2024-05-13")
        out = client.chat("Hello")
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")

    def get_client(self, model_id: str) -> EvaluatorClient:
        """返回已绑定 model 的 EvaluatorClient.

        Network note: httpx.Client 用 trust_env=False 构造, 避免 SOCKS proxy 环境变量
        (ALL_PROXY / HTTPS_PROXY) 干扰对 openrouter.ai 的直连。**已知限制**: 用户若
        确实需要 HTTP proxy 才能访问 OpenRouter(如大陆网络环境), 此 proxy 会被
        静默忽略 — 需要时请设置 OPENROUTER_BASE_URL 指向可达的 mirror。

        Args:
            model_id: 必须在 EVALUATOR_MODELS 白名单内。

        Raises:
            ValueError: model_id 不在白名单。

        Returns:
            EvaluatorClient: 已绑定该 model_id 的 OpenAI-compatible client。
        """
        if model_id not in EVALUATOR_MODELS:
            raise ValueError(f"unknown evaluator model {model_id!r}; allowed: {EVALUATOR_MODELS}")
        # trust_env=False: 明确提供 base_url,不需要系统代理(防止 socks proxy 干扰)
        http_client = httpx.Client(trust_env=False)
        client = OpenAI(
            api_key=self.api_key,
            base_url=OPENROUTER_BASE_URL,
            http_client=http_client,
        )
        return EvaluatorClient(model=model_id, api_key=self.api_key, _client=client)
