"""模型 allowlist + 元信息(SSOT)。dashscope_id / size / available / supports_tools 由 live smoke 实测。

smoke 结论(2026-06-18):deepseek-v4-flash / qwen-plus / qwen-max / qwen3-8b 均支持原生流式函数调用;
qwen2.5-7b-instruct 返回 403 Access denied(账号未开通)→ available=False,开通后改 True。
小模型(qwen2.5-7b / qwen3-8b)= RL 微调候选;大模型 = 能力天花板。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    key: str
    dashscope_id: str
    size: str  # "large" | "small"
    available: bool  # 账号当前能否调用(smoke 实测)
    supports_tools: bool  # 是否支持原生函数调用(smoke 实测;弱/不支持也照实记,不兜底)


_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("deepseek-v4-flash", "deepseek-v4-flash", "large", True, True),
    ModelSpec("qwen-plus", "qwen-plus", "large", True, True),
    ModelSpec("qwen-max", "qwen-max", "large", True, True),
    ModelSpec("qwen2.5-7b", "qwen2.5-7b-instruct", "small", False, False),  # 403 未开通;开通后改 True/True
    ModelSpec("qwen3-8b", "qwen3-8b", "small", True, True),
)
_BY_KEY = {m.key: m for m in _MODELS}


def is_allowed(key: str) -> bool:
    return key in _BY_KEY


def spec(key: str) -> ModelSpec:
    if key not in _BY_KEY:
        raise ValueError(f"model 不在清单: {key!r}(允许:{sorted(_BY_KEY)})")
    return _BY_KEY[key]


def dashscope_id(key: str) -> str:
    return spec(key).dashscope_id


def all_keys() -> list[str]:
    return [m.key for m in _MODELS]


def available_keys() -> list[str]:
    return [m.key for m in _MODELS if m.available]


__all__ = ["ModelSpec", "is_allowed", "spec", "dashscope_id", "all_keys", "available_keys"]
