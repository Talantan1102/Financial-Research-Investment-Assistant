"""裁判重测一致性(元评估落地第三项,位置翻转审计的适配版)。

元评估研报的位置翻转审计针对成对比较(把 A/B 位置对调双判取一致);本体系的
裁判是单答 pass/fail 判定,没有成对场景,故位置翻转不直接适用。诚实改造为
重测稳定性:同一(问题,答案,rubric)让裁判判 k 次,看判定翻不翻——温度>0 或
裁判内部不确定会导致同输入不同判,翻转率高的裁判不可单次信任。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class StabilityReport:
    n: int
    consistency_rate: float  # k 次判定全一致的 case 比例
    flipped: int  # 至少翻过一次的 case 数
    majority_verdicts: list[bool]  # 每条的多数判定


def compute_stability(repeats: list[list[bool]]) -> StabilityReport:
    n = len(repeats)
    if n == 0:
        return StabilityReport(0, 0.0, 0, [])
    consistent = 0
    flipped = 0
    majority: list[bool] = []
    for verdicts in repeats:
        if not verdicts:
            majority.append(False)
            continue
        uniq = set(verdicts)
        if len(uniq) == 1:
            consistent += 1
        else:
            flipped += 1
        majority.append(Counter(verdicts).most_common(1)[0][0])
    return StabilityReport(
        n=n,
        consistency_rate=consistent / n,
        flipped=flipped,
        majority_verdicts=majority,
    )


def format_stability(r: StabilityReport, repeats: int) -> str:
    return "\n".join(
        [
            "裁判重测一致性(单答判定,非成对;位置翻转审计的适配版)",
            "=" * 48,
            f"样本 n = {r.n},每条重测 {repeats} 次",
            f"重测一致率 = {r.consistency_rate:.3f}(k 次判定全同的 case 占比)",
            f"翻过的 case = {r.flipped}",
            "-" * 48,
            "纪律:翻转率高说明裁判单次判定不可信,关键判定取多数票或降温度。",
        ]
    )
