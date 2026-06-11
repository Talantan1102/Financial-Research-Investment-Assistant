"""四道终止闸 + 打转检测 + 烧签名 — 零 I/O 纯谓词(spec § 1.3)。

撞闸不是异常也不是静默截断:loop 拿到 halt reason 后走 force_conclude
(逼模型基于已有信息收尾)并向用户如实上报(loop_halt 事件)。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.chatloop.state import ChatLoopState, args_hash_of
from app.services.llm_step import StepToolCall


@dataclass(frozen=True)
class GateConfig:
    max_steps: int = 12  # 硬迭代上限(spec § 1.3:六只持仓场景约五圈,留一倍垫)
    max_cny: float = 0.10  # 预算闸:每 turn 金额
    max_tokens: int = 120_000  # 预算闸:每 turn token
    burn_threshold: int = 3  # 同签名失败 N 次后烧掉
    max_consecutive_failures: int = 5  # 跨签名尾部连续失败 N 次 → repeated_failures(乱试)
    budget_dispatch_margin_ratio: float = 0.2  # 分发前预检:剩余低于上限此比例 → 跳过整轮工具


def check_gates(state: ChatLoopState, cfg: GateConfig) -> str | None:
    """返回 halt reason("max_steps"|"budget"|"spinning")或 None。判定顺序固定。"""
    if state.step >= cfg.max_steps:
        return "max_steps"
    if state.budget_spent_cny >= cfg.max_cny or state.budget_spent_tokens >= cfg.max_tokens:
        return "budget"
    if state.step >= 2:
        # 契约:ToolHub 记账用 post-apply_step 的 state.step(第 N 圈的调用记在 step=N);
        # Task 2.4 ToolLoop 按此对齐
        cur = state.ledger.signature_set(state.step)
        prev = state.ledger.signature_set(state.step - 1)
        if cur and cur == prev:
            return "spinning"
    if state.ledger.trailing_failure_count() >= cfg.max_consecutive_failures:
        # 跨签名连续失败(换参数硬试):打转闸/烧签名都漏检的乱试模式
        return "repeated_failures"
    return None


def filter_burned(
    calls: list[StepToolCall], state: ChatLoopState
) -> tuple[list[StepToolCall], list[str]]:
    """剔除已烧签名的调用。返回 (放行的 calls, 被拒签名列表)。

    被拒的由 ToolHub 产出指导性错误结果喂回(不在本模块)。
    签名口径与 ToolLedger 一致: f"{tool_name}:{args_hash}"。

    注:call.parsed_args 对坏 JSON 抛 ValueError(模型流式可能产出残缺 JSON)。
    此时无法计算签名 → 放行进 allowed,让 ToolHub 的 schema 校验产出指导性错误
    喂回模型,自纠回路接住(比在此处静默丢弃更安全)。
    """
    allowed: list[StepToolCall] = []
    rejected: list[str] = []
    for call in calls:
        try:
            sig = f"{call.name}:{args_hash_of(call.parsed_args)}"
        except ValueError:
            # 坏 JSON → 无法计算签名,放行交 ToolHub schema 校验产指导性错误
            allowed.append(call)
            continue
        if sig in state.burned_signatures:
            rejected.append(sig)
        else:
            allowed.append(call)
    return allowed, rejected


def update_burned(state: ChatLoopState, cfg: GateConfig) -> None:
    """每圈工具结果记账后调用:把 fail_count ≥ burn_threshold 的签名并入 burned_signatures。

    幂等:set.add 天然去重,重复调用无副作用。
    """
    # 收集台账中出现过的全部签名(含成功/失败)
    all_sigs = {e.signature for e in state.ledger.entries}
    for sig in all_sigs:
        if state.ledger.fail_count(sig) >= cfg.burn_threshold:
            state.burned_signatures.add(sig)


def budget_margin_exhausted(state: ChatLoopState, cfg: GateConfig) -> bool:
    """分发前预检:剩余预算(cny 或 token 任一)低于安全余量 → True。

    用在"本圈 LLM 成本已入账、即将分发工具"的点上:据最新预算决定是否还要再起
    一轮工具(工具执行 + 又一轮 LLM)。预留的余量(上限 * ratio)给收尾那次 LLM 调用。
    """
    cny_remaining = cfg.max_cny - state.budget_spent_cny
    tokens_remaining = cfg.max_tokens - state.budget_spent_tokens
    return (
        cny_remaining < cfg.max_cny * cfg.budget_dispatch_margin_ratio
        or tokens_remaining < cfg.max_tokens * cfg.budget_dispatch_margin_ratio
    )
