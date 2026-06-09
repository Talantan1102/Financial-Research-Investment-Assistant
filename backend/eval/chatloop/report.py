"""行为 × 难度 成绩单(blueprint § 9)。无聚合总分;分确定性闸 / 离线两段。"""

from __future__ import annotations

from collections import defaultdict

from eval.chatloop.passk import PassK, pass1_rate, passk_rate
from eval.chatloop.scenario import VALID_DIFFICULTY
from eval.chatloop.scorers import BehaviorScore


def _rate(passed: int, total: int) -> str:
    return f"{passed}/{total} ({passed / total:.0%})" if total else "—"


def format_dry(scenarios_count: int, by_diff: dict[str, int], by_bucket: dict[str, int]) -> str:
    lines = [
        "# chatloop 评估 — 场景构成(dry,零 LLM)",
        "",
        f"- 总 case:{scenarios_count}",
        "## 难度",
    ]
    for d in VALID_DIFFICULTY:
        if by_diff.get(d):
            lines.append(f"- {d}: {by_diff[d]}")
    lines.append("## 分桶")
    for b, n in sorted(by_bucket.items()):
        lines.append(f"- {b}: {n}")
    return "\n".join(lines)


def format_scorecard(
    scores: list[BehaviorScore],
    *,
    title: str,
    passk: dict[str, PassK] | None = None,
    errors: list[tuple[str, str]] | None = None,
) -> str:
    """scores:每 case 一条(k=1 noop 的确定性行为分)。

    行为 × 难度矩阵:路由/工具(非弃答)· 克制弃答 · 免责合规 · 方向性违例。
    """
    # 矩阵:rows = 行为,cols = 难度
    tool_rel: dict[str, list[bool]] = defaultdict(list)  # 非弃答 case 的 tool_passed
    abstain: dict[str, list[bool]] = defaultdict(list)  # 弃答 case 的 tool_passed
    disclaimer: dict[str, list[bool]] = defaultdict(list)
    advice: dict[str, list[bool]] = defaultdict(list)  # True = 违例
    for s in scores:
        (abstain if s.is_abstain else tool_rel)[s.difficulty].append(s.tool_passed)
        if s.disclaimer_required:  # 情境带:只评"该带"的场景
            disclaimer[s.difficulty].append(s.disclaimer_present)
        advice[s.difficulty].append(s.advice_violation)

    def row(label: str, data: dict[str, list[bool]], *, count_true: bool = True) -> str:
        cells = []
        for d in VALID_DIFFICULTY:
            vals = data.get(d, [])
            passed = sum(vals) if count_true else sum(1 for v in vals if not v)
            cells.append(_rate(passed, len(vals)))
        return f"| {label} | " + " | ".join(cells) + " |"

    n = len(scores)
    rel_total = sum(len(v) for v in tool_rel.values())
    rel_pass = sum(sum(v) for v in tool_rel.values())
    irr_total = sum(len(v) for v in abstain.values())
    irr_pass = sum(sum(v) for v in abstain.values())
    disc_req = [s for s in scores if s.disclaimer_required]
    disc_present = sum(s.disclaimer_present for s in disc_req)
    adv_viol = sum(s.advice_violation for s in scores)

    lines = [
        f"# {title}",
        "",
        f"- 总 case:{n}" + (f"(其中 {len(errors)} 例 SUT 报错)" if errors else ""),
        f"- **RelAcc**(该调时调对):{_rate(rel_pass, rel_total)}",
        f"- **IrrelAcc**(该弃权时正确弃权):{_rate(irr_pass, irr_total)}",
        f"- **免责合规**(情境带:该带场景带了没):{_rate(disc_present, len(disc_req))}"
        f"(另 {n - len(disc_req)} 条无需带)",
        f"- **方向性违例**:{adv_viol} 例" + (" ✓ 无" if adv_viol == 0 else " ✗"),
        "",
        "## 行为 × 难度",
        "",
        "| 行为 | 直球 | 自然难 | 对抗 |",
        "|---|---|---|---|",
        row("路由+工具选择(该调对)", tool_rel),
        row("克制弃答(该弃权)", abstain),
        row("免责合规(该带场景)", disclaimer),
        row("方向性违例(越少越好)", advice, count_true=False),
        "",
    ]

    if passk:
        lines += [
            "## 可靠性(离线 live,pass^k)",
            "",
            f"- 平均单次成功率 pass@1:{pass1_rate(passk):.0%}",
            f"- **连胜率 pass^k**(k 次全过):{passk_rate(passk):.0%}",
            "",
            "| case | k | pass@1 | pass^k |",
            "|---|---|---|---|",
        ]
        for cid, pk in sorted(passk.items()):
            mark = "✓" if pk.passk else "✗"
            lines.append(f"| `{cid}` | {pk.k} | {pk.pass1:.0%} | {mark} |")
        lines.append("")

    failed = [s for s in scores if not s.tool_passed]
    if failed:
        lines.append("## 工具/路由/弃答 未通过明细")
        for s in failed:
            lines.append(f"- `{s.case_id}` [{s.bucket}/{s.difficulty}]: {s.tool_detail}")
        lines.append("")
    bad_disc = [s for s in scores if s.disclaimer_required and not s.disclaimer_present]
    if bad_disc:
        lines.append("## 免责缺失明细(该带却没带)")
        for s in bad_disc:
            lines.append(f"- `{s.case_id}` [{s.difficulty}]")
        lines.append("")
    if errors:
        lines.append("## SUT 报错明细(scorer 看不到,系/环境问题)")
        for cid, err in errors:
            lines.append(f"- `{cid}`: {err}")
        lines.append("")

    return "\n".join(lines)


__all__ = ["format_scorecard", "format_dry"]
