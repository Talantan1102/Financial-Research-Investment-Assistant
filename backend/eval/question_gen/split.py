"""按股票分层切分 train/val/test。

spec: docs/superpowers/specs/2026-06-22-eval-data-pipeline-design.md § ③
核心红线: train/val/test 股票集合不相交。
按 sector 分层: 每个 sector 内按 ratios 切, 保证各行业都有覆盖。
确定性: seed 固定。
"""
from __future__ import annotations

import random
from collections import defaultdict

from eval.question_gen.stock_pool import Stock


def split_by_stock(
    stocks: list[Stock],
    ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
    seed: int = 42,
) -> tuple[list[Stock], list[Stock], list[Stock]]:
    """分层切分股票 → (train, val, test)。

    - 按 sector 分组后各组内 shuffle(固定 seed) + 按比例切
    - 三套股票集合不相交 (each stock appears in exactly one split)
    - 确定性: 相同 seed → 相同结果

    Args:
        stocks: 待切分股票列表
        ratios: (train, val, test) 比例, 须 sum ≈ 1.0
        seed: 随机种子 (确定性)

    Returns:
        (train_stocks, val_stocks, test_stocks) 三个不相交列表
    """
    assert abs(sum(ratios) - 1.0) < 1e-9, f"ratios 须和为 1: {ratios}"

    # 1. 按 sector 分组
    by_sector: dict[str, list[Stock]] = defaultdict(list)
    for s in stocks:
        by_sector[s.sector].append(s)

    # 2. 每组内 shuffle + 按比例切
    rng = random.Random(seed)
    train: list[Stock] = []
    val: list[Stock] = []
    test: list[Stock] = []

    for sector in sorted(by_sector.keys()):  # sorted → 确定性
        members = list(by_sector[sector])
        rng.shuffle(members)
        n = len(members)
        # 计算切分点: 确保 val/test 各至少1只(若 sector 成员够多)
        n_train = max(1, round(n * ratios[0]))
        n_val = max(0, round(n * ratios[1]))
        # test 取剩余
        n_test = n - n_train - n_val
        if n_test < 0:
            # 调整: 缩减 val
            n_val = max(0, n_val + n_test)
            n_test = 0
        train.extend(members[:n_train])
        val.extend(members[n_train : n_train + n_val])
        test.extend(members[n_train + n_val :])

    return train, val, test
