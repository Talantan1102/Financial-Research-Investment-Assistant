"""扫描已采轨迹 → 生成"需重采题目"清单(case_id 级,持久化)。

背景(2026-06-26 gold 审计收口):gold 基本可信,strong_6i 采轨的失败几乎全是
工具缺口。已修 4 个工具缺口(get_financials 暴露 eps/bps/gross_margin/
debt_to_assets + MCP financial_statements end_date nudge),但修复对 RUNNING
的采轨子进程不生效 → 需用修后工具重采受影响题目。本脚本把"需重采"落成 case_id
级清单,避免散落记忆里丢失。

分桶(reason):
  A tool_fixed_rerun  —— 类别命中已修工具(财报毛利率/财报资产负债率/PE理论价/
                          PB理论价),旧轨迹失效,全部重采。
  B coverage_rerun    —— 健康类别但该 case 0 条干净∧正确轨迹(proxy 旧伤片
                          shard_00/01 + 偶发 spinning/max_steps),补采。
  C pending_strong    —— train_2fixed(trend_signal/valuation_percentile)从未
                          strong 采轨,全部待采。
  D blocked_needs_fix —— TWR/归因 组合算法题,工具未修,先记录不重采。

干净∧正确(SFT 可用)定义:passed==True ∧ halt_reason=='natural' ∧ n_steps<=8。

用法:
  PYTHONPATH=backend python -m eval.question_gen.build_rerun_manifest
产物:
  data/d4_overnight/rerun_manifest.jsonl   (一行一 case:case_id/intent/category/reason/clean_correct/total_traj)
  data/d4_overnight/rerun_summary.md       (人读汇总)
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DATA = _HERE / "data"
_OVN = _DATA / "d4_overnight"

# 已修工具缺口命中的 case_id 类别 → 旧轨迹失效,全量重采。
TOOL_FIXED_CATEGORIES = {"财报毛利率", "财报资产负债率", "PE理论价", "PB理论价"}
# 工具未修(组合算法题),先记录不重采。
BLOCKED_CATEGORIES = {"TWR", "归因"}

_CID_CAT = re.compile(r"qg-([^-]+)-")


def _category(case_id: str) -> str:
    m = _CID_CAT.match(case_id or "")
    return m.group(1) if m else "?"


def _is_clean_correct(traj: dict) -> bool:
    return (
        bool(traj.get("passed"))
        and traj.get("halt_reason") == "natural"
        and isinstance(traj.get("n_steps"), int)
        and traj["n_steps"] <= 8
    )


def _load_candidates(path: Path) -> dict[str, dict]:
    """case_id -> {intent, category}。"""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        cid = d.get("case_id", "")
        out[cid] = {"intent": d.get("intent", "?"), "category": _category(cid)}
    return out


def _scan_trajectories(glob_dir: Path) -> dict[str, list[bool]]:
    """case_id -> [is_clean_correct ...] 跨所有片。"""
    by_case: dict[str, list[bool]] = collections.defaultdict(list)
    for tf in sorted(glob_dir.glob("shard_*/trajectories_raw.jsonl")):
        for line in tf.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_case[t.get("case_id", "")].append(_is_clean_correct(t))
    return by_case


def main() -> None:
    cand6 = _load_candidates(_DATA / "train_6intents.jsonl")
    cand2 = _load_candidates(_DATA / "train_2fixed.jsonl")
    traj6 = _scan_trajectories(_OVN / "strong_6i")

    rows: list[dict] = []

    # train_6intents:按类别 + 覆盖分桶。
    # 关键:strong_6i 仍在跑(6/18 片),未采到的 case total_traj==0 是"还没轮到",
    # 不是"采了全失败"。必须区分:total==0(健康类→当前 run 会覆盖,信息性)
    # vs total>0∧clean==0(采了全失败=真覆盖缺口,含 proxy 旧伤片 shard_00/01)。
    for cid, meta in cand6.items():
        cat = meta["category"]
        cc = traj6.get(cid, [])
        clean = sum(cc)
        total = len(cc)
        if cat in BLOCKED_CATEGORIES:
            reason = "blocked_needs_fix"
        elif cat in TOOL_FIXED_CATEGORIES:
            reason = "tool_fixed_rerun"  # 旧工具采的失效,全量重采(不论是否采到)
        elif clean > 0:
            continue  # 健康且已有干净∧正确轨迹,无需重采
        elif total > 0:
            reason = "coverage_rerun"  # 采了但 0 干净∧正确(真缺口)
        else:
            reason = "pending_current_run"  # 当前 old-tool run 还没采到,会覆盖(信息性)
        rows.append(
            {
                "case_id": cid,
                "intent": meta["intent"],
                "category": cat,
                "reason": reason,
                "clean_correct": clean,
                "total_traj": total,
            }
        )

    # train_2fixed:strong 从未采,全量 pending
    for cid, meta in cand2.items():
        rows.append(
            {
                "case_id": cid,
                "intent": meta["intent"],
                "category": meta["category"],
                "reason": "pending_strong",
                "clean_correct": 0,
                "total_traj": 0,
            }
        )

    # 写 manifest
    man = _OVN / "rerun_manifest.jsonl"
    man.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )

    # 汇总
    by_reason = collections.Counter(r["reason"] for r in rows)
    by_cat: dict[str, collections.Counter[str]] = collections.defaultdict(
        lambda: collections.Counter()
    )
    for r in rows:
        by_cat[r["reason"]][r["category"]] += 1

    attempted_cases = sum(1 for v in traj6.values() if v)
    lines = ["# D4 需重采题目清单(rerun_manifest)", ""]
    lines.append(
        f"生成自 train_6intents({len(cand6)}) + train_2fixed({len(cand2)});"
        f"strong_6i 已采 case={attempted_cases}(采轨 6/18 片仍在跑)"
    )
    reason_cn = {
        "tool_fixed_rerun": "A 工具已修需重采(旧轨迹失效·全量)",
        "coverage_rerun": "B 覆盖缺口(已采但 0 干净∧正确)",
        "pending_strong": "C 待 strong 采轨(从未采·train_2fixed)",
        "blocked_needs_fix": "D 阻塞·待修工具(先记录不重采)",
        "pending_current_run": "E 当前 run 未采到(健康类·会被覆盖·信息性非重采)",
    }
    must_rerun = ["tool_fixed_rerun", "coverage_rerun", "pending_strong"]
    runnable = sum(by_reason.get(r, 0) for r in must_rerun)
    lines.append(
        f"**必须重采(A+B+C)= {runnable} 题**;阻塞(D)= {by_reason.get('blocked_needs_fix', 0)};未采到(E,信息性)= {by_reason.get('pending_current_run', 0)}\n"
    )
    for reason in must_rerun + ["blocked_needs_fix", "pending_current_run"]:
        if reason not in by_reason:
            continue
        lines.append(f"## {reason_cn[reason]} —— {by_reason[reason]} 题")
        for cat, n in by_cat[reason].most_common():
            lines.append(f"- {cat}: {n}")
        lines.append("")
    lines.append(
        "**行动**:Track B 让出额度后,用修后工具对 A+B 重采(deepseek 便宜)+ C 的 356 题 "
        "strong 采轨;D 待修 TWR/归因 工具;E 由当前 run 跑完覆盖(若 run 未跑完则降级进 B)。"
    )

    summ = _OVN / "rerun_summary.md"
    summ.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    print(f"\n→ 清单:{man}")
    print(f"→ 汇总:{summ}")


if __name__ == "__main__":
    main()
