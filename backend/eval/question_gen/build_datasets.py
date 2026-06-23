"""评估数据集驱动: 中证800 → split → 抽样 → generate → train/val/test.jsonl。

spec: docs/superpowers/specs/2026-06-22-eval-data-pipeline-design.md § ④

用法:
    python -m eval.question_gen.build_datasets  (需 TUSHARE_MODE=real + .env)
"""

from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from eval.question_gen import generator
from eval.question_gen.split import split_by_stock
from eval.question_gen.stock_pool import Stock
from eval.question_gen.universe import load_csi800

_AS_OF_DEFAULT = "20260612"
_DATA_DIR = Path(__file__).resolve().parent / "data"

# 抽样规模 (可通过 build_datasets 参数覆盖)
_TRAIN_SAMPLE = 90
_VAL_SAMPLE = 10
_TEST_SAMPLE = 10


def _sample_balanced(stocks: list[Stock], n: int, rng: random.Random) -> tuple[Stock, ...]:
    """按行业保量抽样:确保结果尽量含一个 ≥3 成员行业 + 一个 ≥2 成员行业,余额随机补足。

    背景:估值题(同板块 ≥2 只)、组合题(同板块 ≥2 只)、排序/筛选题(同板块 ≥3 只)
    只在同行业凑够成员时才生成。纯随机抽样在小份(val/test)上常把同行业票拆散,
    导致这些意图在 val/test 直接为 0。本函数把"≥3 行业整组 3 只 + ≥2 行业整组 2 只"
    优先纳入,再随机补足名额,从而保住估值/组合/排序题在每份都能生成。

    - 确定性:行业按名排序选 1 个,组内按 ts_code 排序取前 k;余额用传入 rng 抽。
    - 尽力而为:n ≤ 5 或某类行业不存在时只保能保的,绝不报错。
    - len(stocks) ≤ n 时原样返回全部。

    Args:
        stocks: 该 split 的候选股票
        n: 目标抽样数
        rng: 确定性随机源(承 build_datasets 的 seed)

    Returns:
        n 只(或池子太小时 ≤ n 只)的 tuple
    """
    if len(stocks) <= n:
        return tuple(stocks)

    by_sector: dict[str, list[Stock]] = defaultdict(list)
    for s in stocks:
        by_sector[s.sector].append(s)
    # 组内按 ts_code 排序 → 取前 k 确定性
    for members in by_sector.values():
        members.sort(key=lambda s: s.ts_code)

    sorted_sectors = sorted(by_sector.keys())  # 行业按名排序 → 选 1 个确定性

    selected: list[Stock] = []
    selected_codes: set[str] = set()

    def _take(members: list[Stock], k: int) -> None:
        for m in members:
            if len(selected) >= n:
                break
            if m.ts_code not in selected_codes:
                selected.append(m)
                selected_codes.add(m.ts_code)
                k -= 1
                if k <= 0:
                    break

    # 1. 一个 ≥3 成员行业 → 取前 3
    ge3_sector = next((s for s in sorted_sectors if len(by_sector[s]) >= 3), None)
    if ge3_sector is not None:
        _take(by_sector[ge3_sector], 3)

    # 2. 另一个 ≥2 成员行业(与上一个不同)→ 取前 2
    ge2_sector = next(
        (s for s in sorted_sectors if s != ge3_sector and len(by_sector[s]) >= 2),
        None,
    )
    if ge2_sector is not None:
        _take(by_sector[ge2_sector], 2)

    # 3. 余额随机补足(从未入选的票里抽,确定性 rng)
    remaining = [s for s in stocks if s.ts_code not in selected_codes]
    need = n - len(selected)
    if need > 0 and remaining:
        rng.shuffle(remaining)
        selected.extend(remaining[:need])

    return tuple(selected[:n])


async def build_datasets(
    tushare: Any,
    as_of: str = _AS_OF_DEFAULT,
    out_dir: Path = _DATA_DIR,
    train_sample: int = _TRAIN_SAMPLE,
    val_sample: int = _VAL_SAMPLE,
    test_sample: int = _TEST_SAMPLE,
    seed: int = 42,
) -> dict[str, Path]:
    """完整管线: universe → split → sample → generate → 写文件。

    Args:
        tushare: TushareService
        as_of: 截面日期 YYYYMMDD
        out_dir: 输出目录
        train_sample: train 抽取股票数
        val_sample: val 抽取股票数
        test_sample: test 抽取股票数
        seed: 确定性随机种子

    Returns:
        dict with keys 'train', 'val', 'test' → Path to written .jsonl files
    """
    # 1. Load universe
    universe = await load_csi800(tushare, as_of)
    if not universe:
        raise RuntimeError("universe 为空,请检查 tushare index_weight 接口")

    # 2. Split by stock (stratified)
    train_stocks, val_stocks, test_stocks = split_by_stock(universe, seed=seed)

    # 3. Sample from each split (按行业保量,救 val/test 的估值/组合/排序题)
    rng = random.Random(seed)

    train_pool = _sample_balanced(train_stocks, train_sample, rng)
    val_pool = _sample_balanced(val_stocks, val_sample, rng)
    test_pool = _sample_balanced(test_stocks, test_sample, rng)

    # 4. Generate cases for each split
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    for split_name, pool in [("train", train_pool), ("val", val_pool), ("test", test_pool)]:
        out_path = out_dir / f"{split_name}.jsonl"
        await generator.generate(as_of=as_of, out_path=out_path, pool=pool, tushare=tushare)
        paths[split_name] = out_path

    return paths


async def _main() -> None:
    from app.services.tushare_factory import build_tushare_service

    tushare = build_tushare_service()
    paths = await build_datasets(tushare)
    for split_name, path in paths.items():
        print(f"{split_name}: {path}")


if __name__ == "__main__":
    asyncio.run(_main())
