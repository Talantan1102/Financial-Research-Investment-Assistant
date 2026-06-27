"""生成对齐 MCP 工具面的 verl smoke 数据集 + tool_config(T2 AC7)。

与 build_multi_intent_smoke 同问题构造,但 **tool_config 从 McpToolBox().schemas() 自动生成**
(verl 工具列表 == tool_server 实际提供,单源不漂),工具面 = SFT/生产同款 MCP(分组 +
search_tools),非旧原子子集。验证"对齐后的工具面能跑 verl rollout + reward 非零"。

用法:PYTHONPATH=backend python -m eval.question_gen.verl_bridge.build_mcp_smoke <src_jsonl> <out_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import yaml

from eval.question_gen import case as cm
from eval.question_gen.verl_bridge.build_multi_intent_smoke import _INTENTS, _SERVER, _context
from eval.question_gen.verl_bridge.mcp_tool_box import McpToolBox

_SYS = (
    "你是金融指标计算 agent。可用工具与生产一致:不确定某工具参数时先用 search_tools 查文档;"
    "get_financial_statements 取财报(statement=income 给营收/净利/ROE/eps/毛利率/资产负债率,"
    "问某年年报传 end_date=该年1231);get_market_indicators 取估值/快照(metric=daily_basic 给 "
    "PE/PB/换手,metric=pe_history 给 PE 历史分位);get_daily 取区间日线(close+pct_chg);"
    "get_stock_quote 取基准日报价;compare_stocks 多股对比;trade_cal 交易日历。"
    "取数后用 run_python 按题中口径计算,把最终数值赋给变量 result,最后一句给明确数值答案。"
)


def build(src_jsonl: str, out_dir: str, *, per_intent: int = 3) -> None:
    # tool_config 从 McpToolBox.schemas() 派生(单源)
    box = McpToolBox(skills_root="/tmp/mcp_smoke_skills", workdir_root="/tmp/mcp_smoke_work")
    schemas = box.schemas()
    tool_names = [s["function"]["name"] for s in schemas]
    proxy = "eval.question_gen.verl_bridge.http_tool_proxy.HttpToolProxy"
    tools = [
        {
            "class_name": proxy,
            "config": {"type": "native", "server_url": _SERVER, "tool_name": s["function"]["name"]},
            "tool_schema": s,
        }
        for s in schemas
    ]

    cases = cm.load_jsonl(Path(src_jsonl))
    by_intent: dict[str, list] = {}
    for c in cases:
        if c.intent in _INTENTS and c.gold_shape == "scalar":
            by_intent.setdefault(c.intent, [])
            if len(by_intent[c.intent]) < per_intent:
                by_intent[c.intent].append(c)

    rows = []
    for intent, cs in by_intent.items():
        for c in cs:
            user = f"{c.question}\n{_context(c)}"
            gt = {
                "gold": c.gold,
                "gold_shape": "scalar",
                "tolerance": c.tolerance,
                "candidate_names": [],
            }
            as_of = c.meta.get("as_of") or c.meta.get("trade_date")
            tk = {t: {"create_kwargs": {"as_of": as_of}} for t in tool_names}
            rows.append(
                {
                    "data_source": "fin_indicator_oracle",
                    "agent_name": "tool_agent",
                    "prompt": [
                        {"role": "system", "content": _SYS},
                        {"role": "user", "content": user},
                    ],
                    "ability": intent,
                    "reward_model": {
                        "style": "rule",
                        "ground_truth": json.dumps(gt, ensure_ascii=False),
                    },
                    "extra_info": {
                        "index": len(rows),
                        "case_id": c.case_id,
                        "intent": intent,
                        "need_tools_kwargs": True,
                        "tools_kwargs": tk,
                    },
                }
            )

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(out / "train.parquet")
    pd.DataFrame(rows).to_parquet(out / "val.parquet")
    (out / "tool_config.yaml").write_text(
        yaml.safe_dump({"tools": tools}, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(
        f"wrote {len(rows)} rows / {len(by_intent)} intents; tool_config={len(tools)} 工具(MCP 面): "
        f"{tool_names}"
    )


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "eval/question_gen/data/datasets/train.jsonl"
    dst = sys.argv[2] if len(sys.argv) > 2 else "eval/question_gen/data/verl_mcp_smoke"
    build(src, dst)
