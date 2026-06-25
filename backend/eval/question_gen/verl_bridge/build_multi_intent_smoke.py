"""生成多 intent smoke 数据集(逐类测)。

聚焦**单股** intent(code 注入无歧义):stock_study/snapshot_quote/financial_report/
financial_verify/trend_signal/position_calc。每条 prompt 注入:股票代码 + 相关日期/期间
(从 meta)+ 可用工具提示,让模型自己选工具取数→run_python 算。ground_truth 同 oracle 口径。
多股(portfolio/valuation)需 name→code 映射,本 smoke 暂不含(见设计文档)。

用法:PYTHONPATH=backend python -m eval.question_gen.verl_bridge.build_multi_intent_smoke
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from eval.question_gen import case as cm

_SERVER = "http://127.0.0.1:8731"
_SYS = (
    "你是金融指标计算 agent。先用 lookup_ts_code 把股票简称查成 ts_code,再按题意选工具取真实数据"
    "(get_stock_daily 区间收盘、get_daily_basic 某日 PE/PB、get_financials 财报 ROE/营收/净利/EPS),"
    "再用 run_python 按题中口径计算,run_python 里把最终数值赋给变量 result,最后一句话给出明确数值答案。"
)
# 纳入的 intent(含多股 portfolio/valuation;多股靠 lookup_ts_code 查代码)
_INTENTS = {
    "stock_study", "snapshot_quote", "financial_report", "financial_verify",
    "trend_signal", "position_calc", "portfolio_calc", "valuation_calc",
    "valuation_percentile",
}
# tool_config 里登记的工具名(每题 tools_kwargs 给它们各注一份 as_of)
_TOOL_NAMES = [
    "lookup_ts_code", "get_stock_daily", "get_daily_basic",
    "get_financials", "get_stock_quote", "get_pe_history", "run_python",
]


def _context(c: cm.ComputationCase) -> str:
    """按 intent/meta 给模型上下文:单股注入代码,多股让模型自己 lookup;附日期/期间。"""
    m = c.meta
    bits = [f"股票代码 {c.stocks[0]}"] if len(c.stocks) == 1 else ["题中多只股票请用 lookup_ts_code 逐个查代码"]
    if m.get("window_dates"):
        wd = m["window_dates"]
        bits.append(f"区间 [{wd[0]}, {wd[-1]}]")
    if m.get("trade_date"):
        bits.append(f"交易日 {m['trade_date']}")
    if m.get("period_label"):
        bits.append(f"财报期 {m['period_label']}")
    if m.get("as_of"):
        bits.append(f"as_of={m['as_of']}")
    if m.get("qty"):
        bits.append(f"持有 {m['qty']} 股")
    return ";".join(bits) + "。"


def build(src_jsonl: str, out_dir: str, *, per_intent: int = 3) -> None:
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
            gt = {"gold": c.gold, "gold_shape": "scalar", "tolerance": c.tolerance, "candidate_names": []}
            as_of = c.meta.get("as_of") or c.meta.get("trade_date")
            # 每个工具的 create_kwargs 注本题 as_of → 服务端给"最新值"工具(quote/pe_history)钉基准日
            tk = {t: {"create_kwargs": {"as_of": as_of}} for t in _TOOL_NAMES}
            rows.append({
                "data_source": "fin_indicator_oracle", "agent_name": "tool_agent",
                "prompt": [{"role": "system", "content": _SYS}, {"role": "user", "content": user}],
                "ability": intent,
                "reward_model": {"style": "rule", "ground_truth": json.dumps(gt, ensure_ascii=False)},
                "extra_info": {"index": len(rows), "case_id": c.case_id, "intent": intent,
                               "need_tools_kwargs": True, "tools_kwargs": tk},
            })
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(out / "train.parquet")
    pd.DataFrame(rows).to_parquet(out / "val.parquet")
    # tool_config:全 5 数据工具 + run_python(schema 见 build_smoke_dataset 的精简口径)
    from eval.question_gen.verl_bridge.build_smoke_dataset import _DATA_TOOL_SCHEMA, _RUN_PY_SCHEMA  # noqa

    proxy = "eval.question_gen.verl_bridge.http_tool_proxy.HttpToolProxy"

    def _schema(name: str, props: dict, req: list[str], desc: str) -> dict:
        return {"type": "function", "function": {"name": name, "description": desc,
                "parameters": {"type": "object", "properties": props, "required": req}}}

    tools = [
        {"class_name": proxy, "config": {"type": "native", "server_url": _SERVER, "tool_name": "lookup_ts_code"},
         "tool_schema": _schema("lookup_ts_code", {"name": {"type": "string", "description": "股票简称,如 贝达药业"}}, ["name"], "按股票简称查 ts_code")},
        {"class_name": proxy, "config": {"type": "native", "server_url": _SERVER, "tool_name": "get_stock_daily"}, "tool_schema": _DATA_TOOL_SCHEMA},
        {"class_name": proxy, "config": {"type": "native", "server_url": _SERVER, "tool_name": "get_daily_basic"},
         "tool_schema": _schema("get_daily_basic", {"ts_code": {"type": "string"}, "trade_date": {"type": "string", "description": "某交易日 YYYYMMDD"}}, ["ts_code"], "取某股某日 PE/PB/换手等估值快照")},
        {"class_name": proxy, "config": {"type": "native", "server_url": _SERVER, "tool_name": "get_financials"},
         "tool_schema": _schema("get_financials", {"ts_code": {"type": "string"}, "period": {"type": "string", "description": "latest/quarterly/annual"}}, ["ts_code"], "取财报 ROE/营收/净利/EPS 等")},
        {"class_name": proxy, "config": {"type": "native", "server_url": _SERVER, "tool_name": "get_stock_quote"},
         "tool_schema": _schema("get_stock_quote", {"ts_code": {"type": "string"}}, ["ts_code"], "取某股(基准日)最新报价 price/change_pct;基准日由服务端注入")},
        {"class_name": proxy, "config": {"type": "native", "server_url": _SERVER, "tool_name": "get_pe_history"},
         "tool_schema": _schema("get_pe_history", {"ts_code": {"type": "string"}, "years_back": {"type": "integer", "description": "回看年数,默认5"}}, ["ts_code"], "取某股 PE 历史分位(截至基准日)+ current_pe/分位/估值带;基准日由服务端注入")},
        {"class_name": proxy, "config": {"type": "native", "server_url": _SERVER, "tool_name": "run_python"}, "tool_schema": _RUN_PY_SCHEMA},
    ]
    (out / "tool_config.yaml").write_text(yaml.safe_dump({"tools": tools}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"wrote {len(rows)} rows across {len(by_intent)} intents: { {k: len(v) for k, v in by_intent.items()} }")


if __name__ == "__main__":
    build("eval/question_gen/data/datasets/train.jsonl", "eval/question_gen/data/verl_multi")
