"""Cross-judge Spearman script — manual-trigger sanity check.

Reads two sets of EvalResult (e.g. judge=v4-flash vs judge=qwen-max) keyed
by case_id, computes Spearman over factuality scores. Spec § 8 e-alt
demands ≥ 0.70.

Not invoked from CI under v0 — `uv run python scripts/cross_judge_check.py
--judge-a results_a.jsonl --judge-b results_b.jsonl` only.

Pure functions (rank, spearman) are unit-tested; the CLI shell is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def rank(xs: list[float]) -> list[float]:
    """Average-rank — ties get the mean of their ordinal positions."""
    n = len(xs)
    indexed = sorted(range(n), key=lambda i: xs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[indexed[j + 1]] == xs[indexed[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-indexed
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("Spearman requires equal-length lists with len >= 2")
    rx = rank(xs)
    ry = rank(ys)
    n = len(rx)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    num = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
    den_x = sum((r - mean_x) ** 2 for r in rx) ** 0.5
    den_y = sum((r - mean_y) ** 2 for r in ry) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


def _load_factualities(path: Path) -> dict[str, float]:
    """Reads JSONL of EvalResult shape, returns {case_id: factuality_score}."""
    out: dict[str, float] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            out[row["case_id"]] = float(row["scores"]["factuality"])
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--judge-a", type=Path, required=True)
    p.add_argument("--judge-b", type=Path, required=True)
    p.add_argument("--threshold", type=float, default=0.70)
    args = p.parse_args(argv)

    a = _load_factualities(args.judge_a)
    b = _load_factualities(args.judge_b)
    common = sorted(set(a) & set(b))
    if len(common) < 2:
        print(f"ERROR: only {len(common)} cases in common; need >= 2", file=sys.stderr)
        return 2
    xs = [a[c] for c in common]
    ys = [b[c] for c in common]
    rho = spearman(xs, ys)
    print(f"Spearman over {len(common)} cases: {rho:.3f}")
    if rho < args.threshold:
        print(f"FAIL: rho < threshold ({args.threshold})", file=sys.stderr)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
