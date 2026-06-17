"""按 gold 形状解析 agent 答案文本判分。

纯解析、无外部依赖：从答案文本里抓数字 / 候选名,按四种 gold 形状
(scalar / multi_scalar / ranking / set)逐一比对。供 question_gen 评估流程引用。

百分比语义统一按绝对值比较:命中条件只看 abs(abs(n) - abs(gold)),
这样 '-10.63%' 与 '10.63' 视作同一量级,不被正负号或 % 干扰。
"""

from __future__ import annotations

import re

# 抓数字:可选负号 + 首位数字 + (数字或千分位逗号)* + 可选小数部分。
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def nums(text: str) -> list[float]:
    """抓 text 里所有数,去千分位逗号后转 float,保持出现顺序。"""
    result: list[float] = []
    for raw in _NUM_RE.findall(text):
        cleaned = raw.replace(",", "")
        # 去逗号后可能留下 '-' 或 '' 等非法残片(极端输入),跳过转不动的。
        try:
            result.append(float(cleaned))
        except ValueError:
            continue
    return result


def hit_scalar(text: str, gold: float, tol: dict) -> bool:
    """text 里是否有任一数命中 gold(按绝对值语义)。

    tol = {"kind": "rel"|"abs", "value": float}
      abs: abs(abs(n) - abs(gold)) <= tol.value
      rel: abs(abs(n) - abs(gold)) <= tol.value * abs(gold)
    任一 n 命中即 True。
    """
    kind = tol["kind"]
    value = tol["value"]
    target = abs(gold)
    threshold = value if kind == "abs" else value * target
    return any(abs(abs(n) - target) <= threshold for n in nums(text))


def judge(
    gold,
    gold_shape: str,
    tol: dict,
    answer: str,
    candidate_names: list[str],
) -> bool:
    """按 gold_shape 判 answer 是否命中 gold。

    - scalar: gold 是 float;hit_scalar(answer, gold, tol)。
    - multi_scalar: gold 是 {label: value};对每个 value 各 hit_scalar,全中才 True。
    - ranking: gold 是 [[name, val], ...];按 candidate_names 在 answer 中"首次
      出现位置"排序得有序名单,取前 len(gold) 个,与 [g[0] for g in gold] 顺序逐一
      相等才 True(name 用包含匹配 name in answer)。
    - set: gold 是 [name, ...](可空);answer 里出现的 candidate_names 集合
      == set(gold) 才 True。
    """
    if gold_shape == "scalar":
        return hit_scalar(answer, gold, tol)

    if gold_shape == "multi_scalar":
        return all(hit_scalar(answer, value, tol) for value in gold.values())

    if gold_shape == "ranking":
        # 候选名按其在 answer 中首次出现的位置排序;未出现的剔除。
        present = [name for name in candidate_names if name in answer]
        ordered = sorted(present, key=lambda name: answer.index(name))
        top = ordered[: len(gold)]
        expected = [g[0] for g in gold]
        return top == expected

    if gold_shape == "set":
        selected = {name for name in candidate_names if name in answer}
        return selected == set(gold)

    raise ValueError(f"unknown gold_shape: {gold_shape!r}")
