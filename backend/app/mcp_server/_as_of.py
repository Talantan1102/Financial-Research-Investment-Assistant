"""评测/RL 基准日:MCP 数据工具透明钉 as_of(模型不可见)。

第一性原理:as_of 是"让训练采轨/打分时工具返回的数据 == 生成 gold 时的数据"的**复现
机制**,不是任务的一部分,对模型应完全不可见 —— 模型像生产一样只传 ts_code(MCP
inputSchema 不暴露 as_of),运行时按本 env 把"取最新/当前"的查询透明截到 ≤ as_of。
生产不设此 env → 用真实"今天",行为不变。模型学到的是通用技能(调价格工具→算),
而非"传某个特定日期"这个 artifact,故训练分布 == 生产分布。

由评测 runner 在起 MCP 子进程前 ``os.environ[ENV]=as_of`` 设置;子进程继承该 env。
窗口型查询(get_daily 的 start/end)不在此列 —— 区间由模型按系统提示的基准日自行算。
"""

from __future__ import annotations

import os

ENV = "CHAT_TOOLS_AS_OF"


def eval_as_of() -> str | None:
    """返回钉定基准日 YYYYMMDD;未设(生产)则 None。"""
    v = os.getenv(ENV, "").strip()
    return v or None
