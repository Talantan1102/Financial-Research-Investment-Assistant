"""生成 D3 smoke 数据集 + tool_config.yaml(可复现)。

挑 stock_study 涨幅类(scalar,2 端点窗口),增强 prompt 给 ts_code/窗口/公式(模型只看题面
不知 code 与 as_of);tool_config 用 get_stock_daily + run_python 的 schema(run_python 精简为
code-only,避开 verl OpenAIFunctionToolSchema 对 anyOf 的拒绝)。
用法:PYTHONPATH=backend python -m eval.question_gen.verl_bridge.build_smoke_dataset
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from eval.question_gen import case as cm

_SERVER = "http://127.0.0.1:8731"
_SYS = (
    "你是金融指标计算 agent。用 get_stock_daily 取区间收盘价、用 run_python 计算,"
    "最后用一句话给出明确数值答案(百分数)。run_python 里把结果赋给变量 result。"
)
_DATA_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_stock_daily",
        "description": "取某只 A 股在 [start_date, end_date] 区间的日线收盘价序列(升序),自行算指标。",
        "parameters": {
            "type": "object",
            "properties": {
                "ts_code": {"type": "string", "description": "股票代码,如 000938.SZ"},
                "start_date": {"type": "string", "description": "起始交易日 YYYYMMDD"},
                "end_date": {"type": "string", "description": "结束交易日 YYYYMMDD"},
            },
            "required": ["ts_code", "start_date", "end_date"],
        },
    },
}
_RUN_PY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": "执行 Python 做数值计算。把最终结果赋给变量 result(如 result=(a/b-1)*100)。",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python 代码;结果赋给 result"}
            },
            "required": ["code"],
        },
    },
}


def build(src_jsonl: str, out_dir: str, *, n: int = 16) -> None:
    cases = cm.load_jsonl(Path(src_jsonl))
    rows: list[dict] = []
    for c in cases:
        wd = c.meta.get("window_dates")
        if not (
            c.gold_shape == "scalar"
            and c.indicator == "涨幅"
            and isinstance(wd, list)
            and len(wd) == 2
            and len(c.stocks) == 1
        ):
            continue
        ts = c.stocks[0]
        user = (
            f"{c.question}\n股票代码 {ts};区间 [{wd[0]}, {wd[1]}](as_of={c.meta.get('as_of')})。"
            f"涨幅(%) = (区间末收盘/区间初收盘 - 1)*100。"
        )
        gt = {
            "gold": c.gold,
            "gold_shape": "scalar",
            "tolerance": c.tolerance,
            "candidate_names": [],
        }
        rows.append(
            {
                "data_source": "fin_indicator_oracle",
                "agent_name": "tool_agent",
                "prompt": [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
                "ability": c.intent,
                "reward_model": {
                    "style": "rule",
                    "ground_truth": json.dumps(gt, ensure_ascii=False),
                },
                "extra_info": {"index": len(rows), "case_id": c.case_id, "ts_code": ts},
            }
        )
        if len(rows) >= n:
            break
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(out / "train.parquet")
    pd.DataFrame(rows[: max(1, n // 4)]).to_parquet(out / "val.parquet")
    proxy = "eval.question_gen.verl_bridge.http_tool_proxy.HttpToolProxy"
    tools = [
        {
            "class_name": proxy,
            "config": {"type": "native", "server_url": _SERVER, "tool_name": "get_stock_daily"},
            "tool_schema": _DATA_TOOL_SCHEMA,
        },
        {
            "class_name": proxy,
            "config": {"type": "native", "server_url": _SERVER, "tool_name": "run_python"},
            "tool_schema": _RUN_PY_SCHEMA,
        },
    ]
    (out / "tool_config.yaml").write_text(
        yaml.safe_dump({"tools": tools}, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"wrote {len(rows)} rows + tool_config.yaml -> {out}")


if __name__ == "__main__":
    build("eval/question_gen/data/datasets/train.jsonl", "eval/question_gen/data/verl_smoke")
