"""裁判校准 — judge-vs-human 一致率 + Cohen's κ(blueprint § 8.1)。

κ ≥ 阈值(默认 0.6)→ 裁判"上岗"当 grounding 评分器;否则改裁判 prompt 重标重跑。

用法(WSL fria-venv + source ../.env):
    PYTHONPATH=. python -m eval.chatloop.calibrate
    PYTHONPATH=. python -m eval.chatloop.calibrate --model qwen-max --threshold 0.6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_DEFAULT = Path(__file__).resolve().parent / "calibration" / "grounding_label_template.jsonl"


def cohen_kappa(human: list[bool], judge: list[bool]) -> tuple[float, float]:
    """返回 (kappa, observed_agreement)。"""
    n = len(human)
    if n == 0:
        return 0.0, 0.0
    po = sum(1 for h, j in zip(human, judge) if h == j) / n
    hp, jp = sum(human) / n, sum(judge) / n
    pe = hp * jp + (1 - hp) * (1 - jp)
    kappa = 1.0 if pe == 1.0 else (po - pe) / (1 - pe)
    return kappa, po


def _load_labeled(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        r = json.loads(line)
        if str(r.get("label", "")).strip().lower() in ("pass", "fail"):
            rows.append(r)
    return rows


async def _run(labels: Path, model: str, threshold: float) -> int:
    from eval.chatloop.grounding_scorer import GroundingJudge, score_grounding_pass

    rows = _load_labeled(labels)
    if not rows:
        print("无已标注行(label 须为 pass/fail)。")
        return 1

    judge = GroundingJudge(model=model)
    human: list[bool] = []
    judge_lbl: list[bool] = []
    details: list[tuple] = []
    for r in rows:
        res = await score_grounding_pass(str(r["回答"]), str(r["证据"]), judge)
        hp = str(r["label"]).strip().lower() == "pass"
        jp = bool(res["pass"])
        human.append(hp)
        judge_lbl.append(jp)
        details.append((r["id"], hp, jp, res))

    kappa, po = cohen_kappa(human, judge_lbl)

    print(f"# grounding 裁判校准(model={model},n={len(rows)})\n")
    print("| id | 人工 | 裁判 | 一致 | 备注 |")
    print("|---|---|---|---|---|")
    for cid, hp, jp, res in details:
        ok = "✓" if hp == jp else "✗"
        note = "弃答" if res["abstain"] else f"faith={res['faithfulness']:.2f}"
        print(
            f"| {cid} | {'pass' if hp else 'fail'} | {'pass' if jp else 'fail'} | {ok} | {note} |"
        )

    print()
    print(f"- 一致率(observed agreement):{po:.0%}")
    print(f"- **Cohen's κ:{kappa:.3f}**(阈值 {threshold})")
    verdict = (
        "✅ 裁判可上岗"
        if kappa >= threshold
        else "🔴 裁判暂不上岗(改裁判 prompt 或复核人工标注后重跑)"
    )
    print(f"- 结论:**{verdict}**")
    if len(rows) < 30:
        print(f"- ⚠️ 仅 {len(rows)} 条,低于协议建议的 30-50;κ 置信度有限,补标后重跑更稳。")

    disagree = [(c, h, j, r) for c, h, j, r in details if h != j]
    if disagree:
        print("\n## 分歧明细(校准的价值所在)")
        for cid, hp, jp, res in disagree:
            print(
                f"- `{cid}`:人工={'pass' if hp else 'fail'} / 裁判={'pass' if jp else 'fail'}"
                f"(faith={res['faithfulness']:.2f},abstain={res['abstain']})"
            )

    return 0 if kappa >= threshold else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="grounding 裁判校准")
    p.add_argument("--labels", default=str(_DEFAULT))
    p.add_argument("--model", default="qwen-plus", help="裁判模型(独立于 SUT)")
    p.add_argument("--threshold", type=float, default=0.6)
    args = p.parse_args(argv)
    return asyncio.run(_run(Path(args.labels), args.model, args.threshold))


if __name__ == "__main__":
    sys.exit(main())
