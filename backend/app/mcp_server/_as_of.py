"""评测/RL 基准日:MCP 数据工具透明钉 as_of(模型不可见)。

第一性原理:as_of 是"让训练采轨/打分时工具返回的数据 == 生成 gold 时的数据"的**复现
机制**,不是任务的一部分,对模型应完全不可见 —— 模型像生产一样只传 ts_code(MCP
inputSchema 不暴露 as_of),运行时按本 env 把"取最新/当前"的查询透明截到 ≤ as_of。
生产不设此 env → 用真实"今天",行为不变。模型学到的是通用技能(调价格工具→算),
而非"传某个特定日期"这个 artifact,故训练分布 == 生产分布。

两种注入路径(优先级:ContextVar > env):
  - **env**(``CHAT_TOOLS_AS_OF``):评测 runner 起 MCP 子进程前设置,子进程继承——
    一个子进程一个固定 as_of。SFT 采轨/生产沿用此路径。
  - **ContextVar**(``set_eval_as_of``):同进程内**逐调用**注入,asyncio task-local,
    并发安全。verl RL 工具服务(单进程并发处理多题、每题 as_of 不同)走此路径——
    env 是进程全局会串题,ContextVar 按 task 隔离不串。

窗口型查询(get_daily 的 start/end)不在此列 —— 区间由模型按系统提示的基准日自行算。
"""

from __future__ import annotations

import contextvars
import os

ENV = "CHAT_TOOLS_AS_OF"

# 逐调用基准日(asyncio task-local);默认 None → 回落 env。
_ASOF_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "eval_as_of", default=None
)


def eval_as_of() -> str | None:
    """返回钉定基准日 YYYYMMDD;未设(生产)则 None。

    优先 ContextVar(逐调用,并发安全)→ 回落 env(子进程级)。
    """
    v = _ASOF_VAR.get()
    if v:
        return v.strip() or None
    e = os.getenv(ENV, "").strip()
    return e or None


def set_eval_as_of(as_of: str | None) -> contextvars.Token:
    """在当前 task 上下文设逐调用基准日(verl 工具服务每题 exec 前调)。

    返回 Token 可用 ``reset`` 还原(可选)。传 None/空 → 清除本上下文覆盖、回落 env。
    """
    return _ASOF_VAR.set(as_of or None)
