"""评估数据集驱动: 中证800 → split → 抽样 → generate → train/val/test.jsonl。

spec: docs/superpowers/specs/2026-06-22-eval-data-pipeline-design.md § ④

用法:
    python -m eval.question_gen.build_datasets  (需 TUSHARE_MODE=real + .env)
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path
from typing import Any

from eval.question_gen import generator, stock_pool
from eval.question_gen.universe import load_csi800
from eval.question_gen.split import split_by_stock

_AS_OF_DEFAULT = "20260612"
_DATA_DIR = Path(__file__).resolve().parent / "data"

# 抽样规模 (可通过 build_datasets 参数覆盖)
_TRAIN_SAMPLE = 90
_VAL_SAMPLE = 10
_TEST_SAMPLE = 10


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

    # 3. Sample from each split
    rng = random.Random(seed)

    def _sample(stocks: list, n: int) -> tuple:
        if len(stocks) <= n:
            return tuple(stocks)
        return tuple(rng.sample(stocks, n))

    train_pool = _sample(train_stocks, train_sample)
    val_pool = _sample(val_stocks, val_sample)
    test_pool = _sample(test_stocks, test_sample)

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
