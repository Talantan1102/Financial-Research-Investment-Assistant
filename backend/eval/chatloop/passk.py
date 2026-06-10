"""pass^k 连胜率(blueprint § 8.2)。

pass^k = 同一 case 独立跑 k 次**全部通过**的概率(τ-bench 的 pass^k)。区别于
pass@1(单次成功率):暴露"偶尔蒙对 vs 稳定做对"。纯函数,确定性可直测。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PassK:
    case_id: str
    k: int
    pass1: float  # k 次里通过的比例(经验单次成功率)
    passk: bool  # k 次是否全部通过


def pass_power_k(per_run_pass: dict[str, list[bool]]) -> dict[str, PassK]:
    """per_run_pass: {case_id: [run0_pass, run1_pass, ...]} → {case_id: PassK}。"""
    out: dict[str, PassK] = {}
    for cid, runs in per_run_pass.items():
        n = len(runs)
        out[cid] = PassK(
            case_id=cid,
            k=n,
            pass1=(sum(runs) / n) if n else 0.0,
            passk=bool(runs) and all(runs),
        )
    return out


def passk_rate(results: dict[str, PassK]) -> float:
    """整体连胜率:passk 为 True 的 case 占比。"""
    if not results:
        return 0.0
    return sum(1 for r in results.values() if r.passk) / len(results)


def pass1_rate(results: dict[str, PassK]) -> float:
    """整体平均单次成功率(各 case pass1 的均值)。"""
    if not results:
        return 0.0
    return sum(r.pass1 for r in results.values()) / len(results)


__all__ = ["PassK", "pass_power_k", "passk_rate", "pass1_rate"]
