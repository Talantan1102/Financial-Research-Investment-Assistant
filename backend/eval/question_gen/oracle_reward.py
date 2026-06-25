# backend/eval/question_gen/oracle_reward.py
"""verl 自定义奖励函数:确定性 oracle,复用 question_gen.judge(零口径漂移)。

verl 用 importlib 按文件路径加载本模块,NaiveRewardManager 每条 rollout 解码后逐条同步调
`compute_score(data_source, solution_str, ground_truth, extra_info)`。签名/调用时序锚:
docs/research/2026-06-09-verl-multistep-tool-rl-recipe.md §3.4/§3.5。

复用 judge.judge —— 跟评测端同一套判分(scalar/multi_scalar/ranking/set),训练奖励与评测口径一致。
注:verl 跑训练时进程环境须能 import `eval.question_gen.judge`(judge 仅依赖 re,设 PYTHONPATH=backend 即可)。
"""

from __future__ import annotations

import json
from typing import Any

from eval.question_gen import judge

_TAIL_CLIP = 600  # 数值题尾部裁剪,防多步中间数字误命中(§3.4 建议)
_NUMERIC_SHAPES = ("scalar", "multi_scalar")


def _zero(format_ok: float, extra_info: dict[str, Any]) -> dict[str, Any]:
    return {"score": 0.0, "format_ok": format_ok, "num_turns": float(extra_info.get("num_turns") or 0)}


def compute_score(
    data_source: str,
    solution_str: str,
    ground_truth: Any,
    extra_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回 {"score": 1.0/0.0, "format_ok":..., "num_turns":...}。score=outcome reward。"""
    extra_info = extra_info or {}
    gt = json.loads(ground_truth) if isinstance(ground_truth, str) else ground_truth
    gold, shape = gt["gold"], gt["gold_shape"]
    tol, names = gt.get("tolerance", {}), gt.get("candidate_names", [])

    # 数值题裁尾部聚焦最终答案;名单题(ranking/set)按名匹配,用全文不裁。
    answer = solution_str[-_TAIL_CLIP:] if shape in _NUMERIC_SHAPES else solution_str

    # 数值题但尾部抓不到任何数 → 没按要求作答(format 错),区别于"答了但错"。
    if shape in _NUMERIC_SHAPES and not judge.nums(answer):
        return _zero(0.0, extra_info)

    try:
        ok = judge.judge(gold, shape, tol, answer, names)
    except Exception:
        return _zero(0.0, extra_info)

    return {
        "score": 1.0 if ok else 0.0,
        "format_ok": 1.0,
        "num_turns": float(extra_info.get("num_turns") or 0),
    }


__all__ = ["compute_score"]
