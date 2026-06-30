"""OpenAI adapter — moved from app.data._llm_adapter to app.services.

Provides ``build_llm_service_from_env()`` so that the HTTP router and
data-layer modules can get an LLMService backed by a real OpenAI-compatible
endpoint without coupling to raw openai SDK usage in strict-typed code.

Why not in app.services strict tier?
  This module directly imports ``openai.OpenAI``, which violates the
  constraint that ``app.router.chat`` must not import openai.  The router
  imports only ``build_llm_service_from_env`` (which returns an opaque
  ``LLMService``); the openai SDK call is encapsulated here.

  mypy override for app.data.* was ignore_errors=true; this file lives in
  app.services.* (strict for disallow_untyped_defs) but openai stubs are
  covered by ignore_missing_imports=true at the global level, so type-checks
  pass without an explicit ignore.
"""

from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from openai import AsyncOpenAI, OpenAI

from app.config.llm_config import LLMConfig
from app.services.llm_service import LLMService
from app.services.llm_step import StepDelta, StepResult, StepToolCall
from app.services.tier_router import V0_DEFAULT_MODEL  # C45: SSOT for default model

if TYPE_CHECKING:
    from app.services.trace_service import TraceService


# ---------------------------------------------------------------------------
# 模型无关兼容垫片(承 2026-06-18 排查:非 deepseek 模型在 chatloop 里栽在 dashscope
# 的模型专属要求上)。两道 qwen3 专属坑(live 实测):
#   ① qwen3 是思考模型 → 不传 enable_thinking=false 直接 400;
#   ② tool_call 的 function.arguments 必须是合法 JSON(deepseek 容空串,qwen3 严)。
# 这俩对非 qwen3 模型无害(extra_body 仅 qwen3 传;args 合法化对所有模型安全)。
# ---------------------------------------------------------------------------


def _extra_body_for(model: str) -> dict[str, Any]:
    """qwen3 思考模型的 thinking 开关(两条线合一)。

    优先级:``LLM_QWEN3_THINKING=on`` 时一律不关思考(走 chat template 默认 thinking-on),
    供 reasoning-RL 训练线(D4 分带 / 采轨 / 评测,base 本地 sglang + 教师 qwen3.7-max)用
    同一思考模式、保分布对齐;未显式 on(默认)时按模型角色:max 级(qwen3-max / qwen3.7-max)
    当 SFT teacher 开思考(reasoning 进轨迹),其余 qwen3(如学生 qwen3-8b)关思考(避免 thinking
    把 tool_call args 搞坏,2026-06-18 实测)。非 qwen3 一律不传(避免传它们不认的参数)。
    sglang 与 dashscope 对显式开关参数风格不同,但「不传」两端默认都 thinking-on,故 on 档返回 {}。
    """
    if model.startswith("qwen3"):
        if os.getenv("LLM_QWEN3_THINKING", "off").strip().lower() == "on":
            return {}
        return {"enable_thinking": "max" in model}
    return {}


def _valid_json_args(s: Any) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    try:
        json.loads(s)
    except (ValueError, TypeError):
        return False
    return True


def _sanitize_tool_args(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把 assistant tool_call 的 arguments 兜底成合法 JSON(空/坏 → "{}");其余消息原样。

    严格模型(qwen3)要求 function.arguments 合法 JSON;把空/坏 arguments 原样回灌请求会 400。
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        tcs = m.get("tool_calls")
        if not tcs:
            out.append(m)
            continue
        new_tcs = []
        for tc in tcs:
            fn = tc.get("function") or {}
            if _valid_json_args(fn.get("arguments")):
                new_tcs.append(tc)
            else:
                new_tcs.append({**tc, "function": {**fn, "arguments": "{}"}})
        out.append({**m, "tool_calls": new_tcs})
    return out


class _Raw:
    """Minimal ChatCompletionRaw adapter (satisfies LLMService.ChatCompletionRaw protocol)."""

    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


# Public alias for use in tests that need a concrete ChatCompletionRaw-compatible type.
_RawClientResponse = _Raw


class StreamAssembler:
    """OpenAI 流式 chunk → 增量事件与最终聚合。纯状态机,不做 I/O,可用假 chunk 直测。

    分片契约(smoke item 2 实测):tool_calls 增量按 index 分组;id/name 首片到达,
    arguments 为跨片拼接的 JSON 字符串;reasoning_content 与 content 是独立 delta 流。
    """

    def __init__(self) -> None:
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self._frags: dict[int, dict[str, str | None]] = {}
        self.finish_reason: str | None = None
        self.usage: Any = None  # 最后一个带 usage 的 chunk

    def feed(self, chunk: Any) -> list[StepDelta]:
        """消化一个 chunk,返回应立即 emit 的增量(0..n 条)。"""
        emitted: list[StepDelta] = []

        # usage-only chunk (choices 为空但携带 usage)
        if not chunk.choices:
            if chunk.usage is not None:
                self.usage = chunk.usage
            return emitted

        choice = chunk.choices[0]
        delta = choice.delta

        # finish_reason
        if choice.finish_reason is not None:
            self.finish_reason = choice.finish_reason

        # usage 有时附在有 choices 的 chunk 上
        if getattr(chunk, "usage", None) is not None:
            self.usage = chunk.usage

        # reasoning_content — 不进 content_parts
        reasoning_text: str | None = getattr(delta, "reasoning_content", None)
        if reasoning_text:
            self.reasoning_parts.append(reasoning_text)
            emitted.append(StepDelta(kind="reasoning", text=reasoning_text))

        # content
        content_text: str | None = delta.content
        if content_text:
            self.content_parts.append(content_text)
            emitted.append(StepDelta(kind="content", text=content_text))

        # tool_calls — 按 index 分组累积
        tool_call_frags = delta.tool_calls
        if tool_call_frags:
            for frag in tool_call_frags:
                idx: int = frag.index
                if idx not in self._frags:
                    self._frags[idx] = {"id": None, "name": None, "arguments": ""}

                slot = self._frags[idx]
                frag_id: str | None = frag.id
                fn = frag.function
                if fn is not None:
                    frag_name: str | None = fn.name
                    frag_args: str = fn.arguments or ""
                else:
                    frag_name = None
                    frag_args = ""

                # qwen 流式契约(L2 cassette 实测):id/name 只在该 tool_call 的首片携带
                # 非空值,后续延续片把 id/name 置为空串 "" 而非省略/null。空串不能覆盖
                # 已拿到的真实 id/name(否则 name 被 "" 冲掉 → 下游抽不到工具名)。故按
                # 真值(而非 is not None)判定:仅非空片更新 slot。
                if frag_id:
                    slot["id"] = frag_id
                if frag_name:
                    # name 首次到达时 emit tool_call delta
                    if slot["name"] is None:
                        emitted.append(StepDelta(kind="tool_call", tool_name=frag_name))
                    slot["name"] = frag_name

                slot["arguments"] = (slot["arguments"] or "") + frag_args

        return emitted

    def result(self, cost_cny: float = 0.0) -> StepResult:
        """流结束后聚合。usage 缺失时 token 数取 0(调用方可再估算)。"""
        # tool_calls 按 index 排序产出
        tool_calls: list[StepToolCall] = []
        for idx in sorted(self._frags.keys()):
            slot = self._frags[idx]
            tc_id = slot["id"] or f"call_{idx}"
            tc_name = slot["name"] or ""
            tc_args = slot["arguments"] or ""
            tool_calls.append(StepToolCall(id=tc_id, name=tc_name, arguments=tc_args))

        # usage
        prompt_tokens = 0
        completion_tokens = 0
        cached_tokens = 0
        if self.usage is not None:
            prompt_tokens = getattr(self.usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(self.usage, "completion_tokens", 0) or 0
            details = getattr(self.usage, "prompt_tokens_details", None)
            if details is not None:
                cached_tokens = getattr(details, "cached_tokens", 0) or 0

        return StepResult(
            content="".join(self.content_parts),
            tool_calls=tool_calls,
            finish_reason=self.finish_reason or "stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_cny=cost_cny,
            reasoning="".join(self.reasoning_parts),
        )


class _OpenAIAdapter:
    """Thin wrapper around openai.OpenAI that satisfies the ChatClient protocol.

    Also exposes ``stream_chat`` for use by LLMService.stream_step.
    ``async_client`` is optional; build_llm_service_from_env always provides one.
    LangSmith wrapping covers only the sync client; async streaming is not
    wrapped by langsmith (no langsmith async wrappers available at this time).
    """

    def __init__(
        self,
        client: OpenAI,
        model: str,
        async_client: AsyncOpenAI | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._async_client = async_client

    def chat(self, prompt: str, model: str, schema: object) -> _Raw:  # noqa: ANN001
        # schema=None → 纯文本调用(如 chat-title 异步生成);schema 非空 → JSON 模式。
        # DashScope 当 response_format=json_object 时要求 prompt 含 "json" 字,
        # 不该强加给纯文本任务。
        model = model or self._model
        common: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8000,
        }
        eb = _extra_body_for(model)
        if eb:
            common["extra_body"] = eb
        if schema is None:
            r = self._client.chat.completions.create(**common)
        else:
            r = self._client.chat.completions.create(
                **common,
                response_format={"type": "json_object"},
            )
        return _Raw(
            content=r.choices[0].message.content or "",
            prompt_tokens=r.usage.prompt_tokens if r.usage else 0,
            completion_tokens=r.usage.completion_tokens if r.usage else 0,
        )

    async def stream_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        tool_choice: str,
        on_delta: Callable[[StepDelta], Awaitable[None]] | None = None,
    ) -> StepResult:
        """流式 chat-completion,返回聚合 StepResult。

        tools 为 None/空时不传 tools 也不传 tool_choice
        (协议要求 tool_choice 仅在有 tools 时有效)。
        """
        if self._async_client is None:
            raise RuntimeError(
                "_OpenAIAdapter.stream_chat 需要 AsyncOpenAI 实例 "
                "(build_llm_service_from_env 已配) — 直接构造 _OpenAIAdapter 时请传入 async_client"
            )
        model = model or self._model
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _sanitize_tool_args(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": 8000,
        }
        eb = _extra_body_for(model)
        if eb:
            kwargs["extra_body"] = eb
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        asm = StreamAssembler()
        stream = await self._async_client.chat.completions.create(**kwargs)
        async for chunk in stream:
            for delta in asm.feed(chunk):
                if on_delta is not None:
                    await on_delta(delta)
        return asm.result()


def build_llm_service_from_env(trace_service: TraceService | None = None) -> LLMService:
    """Construct an LLMService backed by a real OpenAI-compatible endpoint.

    Reads API credentials from environment via LLMConfig (DASHSCOPE_API_KEY /
    LLM_BASE_URL).  Used by the HTTP chat router and TushareClient to inject
    into MockTushareService.

    C27: wires a TraceService so LLMService.chat actually persists spans
    (cost/latency) — every factory caller (chat router, monitoring/memory Celery
    tasks, eval) gets observability. Defaults to TraceService(SessionLocal); span
    writes are best-effort and never break the LLM call.
    C45: default model comes from the canonical tier_router.V0_DEFAULT_MODEL (SSOT).

    async_client: AsyncOpenAI 专供流式 stream_step 使用。LangSmith 只包了 sync client,
    async 流式暂不接 LangSmith,直接传入原生 AsyncOpenAI 实例。
    """
    config = LLMConfig()
    model = os.getenv("MOCK_TUSHARE_MODEL", V0_DEFAULT_MODEL)
    # 超时 + 重试上限:不设则 openai 默认 600s/2retry —— maas 端偶发 hang 时整进程冻住
    # 数分钟(eval 并发槽全卡)。正常调用 ≤50s,故 timeout=90s 覆盖合法慢调用、把 hang
    # 的调用 90s fail-fast → 该 rollout 报错被 per-case try 兜住跳过、释放槽,进程不冻。
    # 可经 LLM_HTTP_TIMEOUT_S env 覆盖(生产链路默认值不变,仅 eval 大并发受益)。
    _timeout = float(os.getenv("LLM_HTTP_TIMEOUT_S", "90"))
    _retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
    raw_client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=_timeout,
        max_retries=_retries,
    )
    # LangSmith 追踪(P0):LANGSMITH_TRACING=true 时把 client 包一层,自动把每次 LLM
    # 调用的 prompt/completion/token/latency 作为 run 发到 LangSmith。包装锁在这个 DI
    # 缝里 —— router / strict 层既不感知 openai 也不感知 langsmith;关时零开销。
    # 注意: AsyncOpenAI 不走 LangSmith wrap(暂无 async wrapper 支持),维持现状。
    if os.getenv("LANGSMITH_TRACING", "").strip().lower() in {"true", "1", "yes"}:
        from langsmith.wrappers import wrap_openai

        raw_client = wrap_openai(raw_client)
    async_raw = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=_timeout,
        max_retries=_retries,
    )
    adapter = _OpenAIAdapter(client=raw_client, model=model, async_client=async_raw)
    if trace_service is None:
        from app.core.database import SessionLocal
        from app.services.trace_service import TraceService as _TraceService

        trace_service = _TraceService(SessionLocal)
    return LLMService(client=adapter, trace_service=trace_service)
