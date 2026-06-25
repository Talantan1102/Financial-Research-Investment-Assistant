# backend/eval/question_gen/to_verl.py
"""ComputationCase → verl ToolAgentLoop parquet 行。

格式锚:docs/research/2026-06-09-verl-multistep-tool-rl-recipe.md §2.7。
- `agent_name="tool_agent"` 路由到 ToolAgentLoop。
- `reward_model.ground_truth` 自带 judge() 全部输入(gold/gold_shape/tolerance/candidate_names),
  D3 第 4 件(oracle reward)直接 `judge.judge(**ground_truth, answer=...)` 复用,零口径漂移。
- `extra_info.fetch` 带取数上下文(stocks/window/as_of),供 D3 第 2 件(tushare 工具)注入 create_kwargs。

注:`tools_kwargs` / `need_tools_kwargs` 留到 D3 第 2 件(工具注册)定稿——届时把 fetch 上下文
按工具名塞进 create_kwargs。现在先把题/oracle 真值/取数上下文摆成 verl 格式。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.question_gen import case as case_mod

DATA_SOURCE = "fin_indicator_oracle"  # reward manager 据此路由到我们的 oracle reward fn

SYSTEM_PROMPT = (
    "你是金融指标计算 agent。回答用户的数值/筛选类问题时,先用工具取真实行情/财务数据,"
    "再用 run_python 按正确口径计算(注意复权口径、回撤的路径依赖、多序列按交易日对齐),"
    "最后给出明确的数值或名单答案。"
)


def case_to_verl_row(
    c: case_mod.ComputationCase,
    *,
    split: str,
    index: int,
    candidate_names: list[str],
) -> dict[str, Any]:
    """单条 case → verl parquet 行(§2.7 结构)。candidate_names 由调用方算(export 走 stock_pool)。"""
    return {
        "data_source": DATA_SOURCE,
        "agent_name": "tool_agent",
        "prompt": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": c.question},
        ],
        "ability": c.intent,
        "reward_model": {
            "style": "rule",
            "ground_truth": {
                "gold": c.gold,
                "gold_shape": c.gold_shape,
                "tolerance": c.tolerance,
                "candidate_names": candidate_names,
            },
        },
        "extra_info": {
            "split": split,
            "index": index,
            "case_id": c.case_id,
            "intent": c.intent,
            # 取数上下文:D3 第 2 件(tushare 工具)把这些塞进 tools_kwargs.<tool>.create_kwargs
            "fetch": {"stocks": list(c.stocks), "window": c.window, "meta": dict(c.meta)},
        },
    }


def _candidate_names(c: case_mod.ComputationCase) -> list[str]:
    """股票代码 → 名(承 runner._candidate_names 口径,judge 的 ranking/set 用)。"""
    from eval.question_gen import stock_pool

    # 注:stock_pool.POOL 是固定清单,重生成数据的票来自 csi800 全集,可能不在其中(KeyError)。
    # scalar/multi_scalar 用不到候选名;ranking/set 的全量名解析是独立待办(见 export 说明)。查不到跳过。
    out: list[str] = []
    for ts in c.stocks:
        try:
            out.append(stock_pool.get(ts).name)
        except KeyError:
            continue
    return out


def _serialize_for_parquet(row: dict[str, Any]) -> dict[str, Any]:
    """把多态嵌套字段 JSON 化,避免 pyarrow 'cannot mix struct' —— gold 类型随 gold_shape 变
    (scalar=float/multi=dict/ranking=list),统一存 JSON 字符串(verl 惯例,oracle reward 端 json.loads)。"""
    row = {**row}
    row["reward_model"] = {
        **row["reward_model"],
        "ground_truth": json.dumps(row["reward_model"]["ground_truth"], ensure_ascii=False),
    }
    row["extra_info"] = {
        **row["extra_info"],
        "fetch": json.dumps(row["extra_info"]["fetch"], ensure_ascii=False),
    }
    return row


def export_verl_parquet(
    cases: list[case_mod.ComputationCase], out_path: Path | str, *, split: str
) -> Path:
    """整份 case → verl parquet。candidate_names 走 stock_pool 查名。返回写出的 Path。"""
    import pandas as pd

    rows = [
        _serialize_for_parquet(
            case_to_verl_row(c, split=split, index=i, candidate_names=_candidate_names(c))
        )
        for i, c in enumerate(cases)
    ]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(out_path)
    return out_path


__all__ = ["DATA_SOURCE", "SYSTEM_PROMPT", "case_to_verl_row", "export_verl_parquet"]
