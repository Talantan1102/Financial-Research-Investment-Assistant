"""窗口四区组装 — 每圈把 ChatLoopState 投影成发给 LLM 的 messages 数组(spec § 2.2)。

设计要点:
- 四区顺序:稳定前缀区 → 历史区 → 本 turn 轨迹区 → 尾部动态区;
- 稳定前缀区(system 消息):三段拼接(system_prompt / persona_block / skill_listing),
  turn 内逐字节恒定,吃 KV-cache 折扣;
- 历史区:history_block 元组透传,Phase 4 注入,本模块不做 I/O;
- 本 turn 轨迹区:state.messages 原样(含降级处理);
- 尾部动态区:单条 user 消息 "(第 N/M 步,预算剩 ¥x.xx。)",每圈唯一变化部分;
- 降级(改本体,幂等):老圈大 tool 消息 content 替换为 [全文已缓存 ref=...] + digest;
  协议红线:只改 content,绝不删消息、绝不动 role/tool_call_id。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from app.chatloop.state import ChatLoopState

# ---------------------------------------------------------------------------
# token 估算
# ---------------------------------------------------------------------------

# CJK 统一汉字 Unicode 范围:U+4E00–U+9FFF
_CJK_LOW = "一"
_CJK_HIGH = "鿿"


def estimate_tokens(text: str) -> int:
    """CJK 字符按 1.65 字符/token,其余按 4 字符/token(qwen 官方口径,spec § 2.2)。

    中文标点(,。等)在 CJK 区间外按 /4 计,轻微低估可接受(真实值走 usage 回填)。
    """
    cjk = sum(1 for ch in text if _CJK_LOW <= ch <= _CJK_HIGH)
    other = len(text) - cjk
    return math.ceil(cjk / 1.65 + other / 4)


# ---------------------------------------------------------------------------
# ContextDeps
# ---------------------------------------------------------------------------

_SEP = "\n\n---\n\n"


@dataclass(frozen=True)
class ContextDeps:
    """窗口组装的静态依赖 — turn 开始时构建一次,圈间不变(前缀稳定性的来源)。"""

    system_prompt: str
    persona_block: str = ""
    skill_listing: str = ""
    history_block: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    max_steps: int = 12
    max_cny: float = 0.10
    downgrade_char_threshold: int = 1320

    def __post_init__(self) -> None:
        # frozen dataclass 用 object.__setattr__ 也不可改;tuple 是 immutable,
        # 但 field(default_factory=tuple) 在 frozen dataclass 里等效 ()
        # 注:dataclass(frozen=True) 不允许 __post_init__ 里赋值;
        # 为安全起见,不修改任何字段。
        pass

    @property
    def system_message_content(self) -> str:
        """三段拼接,空段跳过,保证前缀逐字节恒定。"""
        parts = [p for p in (self.system_prompt, self.persona_block, self.skill_listing) if p]
        return _SEP.join(parts)


# ---------------------------------------------------------------------------
# 降级内部逻辑
# ---------------------------------------------------------------------------


def _find_assistant_before_tool(
    messages: list[dict[str, Any]], tool_idx: int
) -> dict[str, Any] | None:
    """从 tool_idx 往前找到紧前方的 assistant(tool_calls) 消息。

    OpenAI 协议:assistant(tool_calls) 后紧跟其全部 tool 消息。
    因此 tool_idx 前面的第一个 assistant 消息就是对应的调用方。
    """
    for i in range(tool_idx - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            return messages[i]
    return None


def _last_round_boundary(messages: list[dict[str, Any]]) -> int:
    """返回"最近一圈"起始消息的索引。

    "最近一圈" = 最后一个 assistant(tool_calls) 消息及其后的 tool 消息。
    返回该 assistant 消息的下标;若不存在则返回 len(messages)(全部不属于最近一圈)。
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            return i
    return len(messages)


def _downgrade_old_tool_messages(
    state: ChatLoopState, threshold: int
) -> None:
    """对 state.messages 中"老圈"大 tool 消息做降级(改本体,幂等)。

    保护名单(永不降级):
    1. 失败消息(content 以 "[ERROR]" 开头);
    2. 最近一圈的全部消息(last_round_start 及之后);
    3. 对应工具名为 load_skill 的 tool 消息;
    4. user / assistant 消息(role 判断自然跳过)。
    """
    messages = state.messages
    last_round_start = _last_round_boundary(messages)

    for idx, msg in enumerate(messages):
        # 只处理 tool 消息
        if msg.get("role") != "tool":
            continue
        # 幂等:已降级跳过
        if idx in state.downgraded_msg_indices:
            continue
        # 保护:最近一圈
        if idx >= last_round_start:
            continue
        content = msg.get("content", "")
        # 保护:失败消息
        if isinstance(content, str) and content.startswith("[ERROR]"):
            continue
        # 内容长度检查
        if not isinstance(content, str) or len(content) <= threshold:
            continue
        # 反查 assistant 消息,一次遍历同时获取工具名与 cache_key
        assistant_msg = _find_assistant_before_tool(messages, idx)
        tool_call_id = msg.get("tool_call_id")
        tool_name: str | None = None
        cache_key: str | None = None
        if assistant_msg is not None:
            for tc in assistant_msg.get("tool_calls", []):
                if tc.get("id") == tool_call_id:
                    tool_name = tc.get("function", {}).get("name")
                    raw_args = tc.get("function", {}).get("arguments", "{}")
                    try:
                        args_dict = json.loads(raw_args)
                    except (json.JSONDecodeError, ValueError):
                        args_dict = {}
                    if tool_name is not None:
                        entry = state.ledger.find_success(
                            tool_name=tool_name, args=args_dict
                        )
                        if entry is not None:
                            cache_key = entry.cache_key
                    break

        # 保护:load_skill 的 tool 消息
        if tool_name == "load_skill":
            continue

        ref = cache_key if cache_key is not None else "n/a"
        digest = content[:200]
        msg["content"] = f"[全文已缓存 ref={ref}] {digest}"
        state.downgraded_msg_indices.add(idx)


# ---------------------------------------------------------------------------
# assemble_context
# ---------------------------------------------------------------------------


def assemble_context(
    state: ChatLoopState, deps: ContextDeps
) -> list[dict[str, Any]]:
    """state → OpenAI messages。

    会先对 state.messages 做降级(改本体,幂等),再拼四区。
    纯函数语义:除降级与 downgraded_msg_indices 记账外无其它副作用。
    """
    # 1. 降级(改本体)
    _downgrade_old_tool_messages(state, deps.downgrade_char_threshold)

    result: list[dict[str, Any]] = []

    # 区一:稳定前缀区
    result.append(
        {"role": "system", "content": deps.system_message_content}
    )

    # 区二:历史区(rebuild 产物,透传)
    result.extend(deps.history_block)

    # 区三:本 turn 轨迹区
    result.extend(state.messages)

    # 区四:尾部动态区
    remaining = max(0.0, deps.max_cny - state.budget_spent_cny)
    tail_content = f"(第 {state.step + 1}/{deps.max_steps} 步,预算剩 ¥{remaining:.2f}。)"
    result.append({"role": "user", "content": tail_content})

    return result
