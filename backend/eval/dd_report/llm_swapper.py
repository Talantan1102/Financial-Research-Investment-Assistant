"""LLMSwapper — DashScope (阿里百炼) API wrapper for evaluator LLM swap.

spec § 4.1 决策 1 / § 5.3:Pipeline-as-SUT 评估的核心组件,允许 BacktestRunner
在运行时切换 evaluator LLM。**2026-05-17 切到 DashScope**(项目级 provider 决策,
撞实 OpenRouter region/credit/free-tier 问题后,见
docs/claude-context/phase-2-dogfood-real-blockers.md)。

支持的 evaluator model(DashScope 实际可用 + spec § 4.1 用 cutoff 接近的 LLM
cross-check 维持跨厂商多样性):
  - deepseek-v4-flash       (cutoff 2026-04, DeepSeek)
  - qwen-plus               (中量级 Qwen, cutoff ≥ 2024)
  - qwen-max                (大量级 Qwen, cutoff ≥ 2024)
  - qwen-turbo              (轻量, cross-LLM 矩阵备选)

**关键 caveat**: DashScope 主推模型 cutoff 全 ≥ 2024,原 spec § 4.1 "用 cutoff
< 2024 LLM 跑 leak-free backtest" 设计**实际不可行** under DashScope-only
provider 约束。Backtest 主线变成 sanity 副线(cut_off=2026-04-30, model
cutoff 之后)+ 接受 backtest 主线 (2024-2025 时点) 有 leak。简历叙事需调整。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import cast

import httpx
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject, ResponseFormatText

# Backtest 主线 evaluator (DashScope 3 LLM cross-check)
BACKTEST_EVALUATOR_MODELS: tuple[str, ...] = (
    "deepseek-v4-flash",
    "qwen-plus",
    "qwen-max",
)

# Cross-LLM 矩阵 (spec § 4.8.2):上述 3 个 + 轻量备选
CROSS_LLM_MATRIX_MODELS: tuple[str, ...] = (
    *BACKTEST_EVALUATOR_MODELS,
    "qwen-turbo",
)

# 公共白名单
EVALUATOR_MODELS: tuple[str, ...] = CROSS_LLM_MATRIX_MODELS

DASHSCOPE_BASE_URL_DEFAULT = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class EvaluatorClient:
    """已绑定 model id 的 OpenAI-compatible client (走 DashScope endpoint).

    暴露 chat(prompt, response_format) 形态,与 LLMService.chat 类似;evaluator
    跟生产 LLMService 共用 DashScope provider (single-provider 项目约束),
    但 backtest swap 仍能跑不同 model 做 cross-LLM consensus / ablation。
    """

    model: str
    api_key: str = field(repr=False)
    _client: OpenAI

    def chat(
        self,
        prompt: str,
        response_format: ResponseFormatJSONObject | ResponseFormatText | None = None,
    ) -> str:
        """Chat completion via DashScope, 返回 content str."""
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
    """Evaluator LLM swap orchestrator (DashScope-backed).

    使用方式:
        swapper = LLMSwapper()  # 从 env 读 DASHSCOPE_API_KEY + base_url
        client = swapper.get_client("deepseek-v4-flash")
        out = client.chat("Hello")

    Env vars:
        DASHSCOPE_API_KEY  — required
        LLM_BASE_URL       — optional, defaults DASHSCOPE_BASE_URL_DEFAULT
                             (与生产 LLMConfig env 命名一致, 见 app/config/llm_config.py)
    """

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self.base_url = (
            base_url
            or os.environ.get("LLM_BASE_URL")
            or os.environ.get("DASHSCOPE_BASE_URL")
            or DASHSCOPE_BASE_URL_DEFAULT
        )

    def get_client(self, model_id: str) -> EvaluatorClient:
        """返回已绑定 model 的 EvaluatorClient.

        Network note: httpx.Client 用 trust_env=False 构造, 避免 SOCKS proxy 环境变量
        (ALL_PROXY / HTTPS_PROXY) 干扰对 DashScope 直连。DashScope 在国内直连,
        不需要 proxy,trust_env=False 是干净选择。

        Args:
            model_id: 必须在 EVALUATOR_MODELS 白名单内。

        Raises:
            ValueError: model_id 不在白名单。

        Returns:
            EvaluatorClient: 已绑定该 model_id 的 OpenAI-compatible client (DashScope)。
        """
        if model_id not in EVALUATOR_MODELS:
            raise ValueError(f"unknown evaluator model {model_id!r}; allowed: {EVALUATOR_MODELS}")
        # trust_env=False: 明确提供 base_url,不需要系统代理(防止 socks proxy 干扰)
        http_client = httpx.Client(trust_env=False)
        client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=http_client,
        )
        return EvaluatorClient(model=model_id, api_key=self.api_key, _client=client)
