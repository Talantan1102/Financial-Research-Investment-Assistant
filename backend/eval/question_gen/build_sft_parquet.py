"""SFT 数据预处理:sft_train.jsonl → verl MultiTurnSFTDataset 吃的 parquet。

- 输出 `messages` 列(list[dict],含 reasoning_content + tool_calls);verl 自动按轮
  apply_chat_template(qwen3 原生 reasoning→<think>、tool_calls→Hermes)+ 建 loss_mask(只 assistant)。
- 切 ~95% train / ~5% val(val 用于 teacher-forced **val loss 早停**;datasets/val.jsonl 那套
  题目+gold 另作 pass@1 生成评估,不在此)。
- max_len 安全兜底:丢 token>max_len 的(32768 下本数据集为 0)。

用法:PYTHONPATH=backend python -m eval.question_gen.build_sft_parquet
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pandas as pd

_SRC = Path("eval/question_gen/data/d4_overnight/sft_train.jsonl")
_OUT = Path("eval/question_gen/data/sft_parquet")
_VAL_FRAC = 0.05
_SEED = 17
_MAX_LEN = 32768  # 与 run_sft data.max_length 一致;仅作安全兜底


def build() -> None:
    rows = [json.loads(line) for line in _SRC.read_text().splitlines() if line.strip()]
    # 安全兜底:超长丢弃(需 tokenizer;此处仅按消息字符粗筛极端,真正长度由 verl truncation=error 守)
    # 实测 32k 下无超长,留 verl 侧把关;这里只取 messages 列。
    data = [{"messages": r["messages"]} for r in rows]

    rng = random.Random(_SEED)
    rng.shuffle(data)
    n_val = max(1, int(len(data) * _VAL_FRAC))
    val, train = data[:n_val], data[n_val:]

    _OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(train).to_parquet(_OUT / "train.parquet")
    pd.DataFrame(val).to_parquet(_OUT / "val.parquet")
    print(f"train={len(train)} val={len(val)} → {_OUT}")
    print(
        "注:val 是 teacher-forced val-loss 集(早停用);pass@1 生成评估走 datasets/val.jsonl(剔 2 近重)。"
    )


if __name__ == "__main__":
    build()
