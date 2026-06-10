"""消融区分度(元评估第四步实跑)— 完整版 vs 削弱版逐对 separable 判定。

研报《元评估 · 怎么论证评估体系可信》第四步:区分度。光有 separable 工具不够,
要真跑一个**故意削弱**的系统,验证评估能把它和完整版拉开——拉不开说明评估
分不出好坏(地板/天花板效应、噪声盖过差距)。

两类削弱(knob 在 live_deps.build_live_runners):
- 写侧:llm_judge=None → 无冲突消解 → 所有冲突默认 APPEND_NEW → 旧版不作废、
  版本链不成形 → old_invalidated / invalidated_chain_intact 显著掉分。
- 读侧:空检索器 → 生成拿不到事实 → 可答题全拒答掉分;而克制弃答维度**不应**
  掉分(无记忆照样该拒答)——这条"该掉的掉、不该掉的不掉"本身就是区分度证据。

本模块是纯函数层(逐对 Wilson 区间 separable),live 编排在 run_ablation.py。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from eval.memory_dialogue.read_phase import ProbeResult
from eval.memory_dialogue.scoring import separable, wilson_interval
from eval.memory_dialogue.write_phase import SessionCheckResult


@dataclass
class SeparabilityRow:
    """一个 cell(读侧维度×档 或 写侧断言类型)在完整版 vs 削弱版上的对比。"""

    label: str
    full: tuple[int, int]  # (passed, total)
    ablated: tuple[int, int]
    separable: bool
    note: str  # 方向/解读:完整版更高(预期可区分)/ 无差异 / 反常(削弱版更高)


def write_rates_by_check_type(
    write_results: list[SessionCheckResult],
) -> dict[str, tuple[int, int]]:
    """按断言类型聚合写侧通过率:{check_type: (passed, total)}。

    消融要看的是 old_invalidated / invalidated_chain_intact 这类**依赖冲突消解**
    的断言在削弱版上掉多少,故按 check_type 而非聚合总率比较。
    """
    agg: dict[str, list[bool]] = defaultdict(list)
    for w in write_results:
        agg[w.check_type].append(w.passed)
    return {ct: (sum(v), len(v)) for ct, v in agg.items()}


def _read_rates(probes: list[ProbeResult]) -> dict[tuple[str, str], tuple[int, int]]:
    agg: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for r in probes:
        agg[(r.probe.dimension, r.probe.tier)].append(r.final_passed)
    return {k: (sum(v), len(v)) for k, v in agg.items()}


def _direction_note(full: tuple[int, int], ablated: tuple[int, int], is_sep: bool) -> str:
    fp, ft = full
    ap, at = ablated
    f_rate = fp / ft if ft else 0.0
    a_rate = ap / at if at else 0.0
    if not is_sep:
        return "无差异(区间重叠,不可区分)"
    if f_rate > a_rate:
        return "完整版更高(预期:削弱真把分拉低,评估有区分力)"
    return "反常:削弱版反而更高(评估或消融配置存疑,需排查)"


def _row(label: str, full: tuple[int, int], ablated: tuple[int, int]) -> SeparabilityRow:
    is_sep = separable(full[0], full[1], ablated[0], ablated[1])
    return SeparabilityRow(
        label=label,
        full=full,
        ablated=ablated,
        separable=is_sep,
        note=_direction_note(full, ablated, is_sep),
    )


def separability_report(
    full_probes: list[ProbeResult],
    full_writes: list[SessionCheckResult],
    ablated_probes: list[ProbeResult],
    ablated_writes: list[SessionCheckResult],
) -> list[SeparabilityRow]:
    """完整版 vs 削弱版,逐 cell 产出区分度行。

    读侧按(维度,档)、写侧按断言类型。某 cell 只在一版出现时,另一版按 (0,0)
    处理(separable 对空样本返 False —— 缺数据不妄下区分结论)。
    """
    rows: list[SeparabilityRow] = []

    full_r = _read_rates(full_probes)
    abl_r = _read_rates(ablated_probes)
    for key in sorted(set(full_r) | set(abl_r)):
        dim, tier = key
        rows.append(_row(f"读侧:{dim}/{tier}", full_r.get(key, (0, 0)), abl_r.get(key, (0, 0))))

    full_w = write_rates_by_check_type(full_writes)
    abl_w = write_rates_by_check_type(ablated_writes)
    for ct in sorted(set(full_w) | set(abl_w)):
        rows.append(_row(f"写侧:{ct}", full_w.get(ct, (0, 0)), abl_w.get(ct, (0, 0))))

    return rows


def format_separability_report(rows: list[SeparabilityRow]) -> str:
    """人读表:label | 完整版 [Wilson] | 削弱版 [Wilson] | 可区分? | 解读。"""
    lines = [
        "消融区分度报告 — 完整版 vs 削弱版(Wilson 95% 区间不重叠才算可区分)",
        "=" * 78,
    ]
    n_sep = sum(1 for r in rows if r.separable)
    for r in rows:
        fl, fh = wilson_interval(*r.full)
        al, ah = wilson_interval(*r.ablated)
        mark = "✓可区分" if r.separable else "·不可区分"
        lines.append(
            f"{r.label:<22} 完整{r.full[0]}/{r.full[1]}[{fl:.2f}-{fh:.2f}]"
            f"  削弱{r.ablated[0]}/{r.ablated[1]}[{al:.2f}-{ah:.2f}]  {mark}"
        )
        lines.append(f"{'':<22} └ {r.note}")
    lines.append("-" * 78)
    lines.append(f"可区分 cell:{n_sep}/{len(rows)}(越多说明评估对该削弱越敏感)")
    lines.append("(读侧'克制弃答'不可区分=符合预期:无记忆照样该拒答,不该因消融掉分)")
    return "\n".join(lines)
