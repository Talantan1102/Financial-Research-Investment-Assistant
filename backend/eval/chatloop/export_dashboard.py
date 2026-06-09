"""把落库的评估历史导出成 JSON,供看板读(blueprint § 9 闭环的"读"半的数据源)。

看板是 PG-free 的(Milvus + yaml/sqlite 数据文件驱动),不直连 backend 的 PG。所以由
**backend 侧**(有 DB 访问)查 chatloop_eval_runs/metrics → 写 dashboard/data/
chatloop_eval_history.json,看板按它现成的"读数据文件"模式渲染。每次 `_record_run` 落库后
best-effort 自动刷新;也可 `python -m eval.chatloop.export_dashboard` 手动跑。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# repo 根 / dashboard / data / chatloop_eval_history.json
_DEFAULT_OUT = Path(__file__).resolve().parents[3] / "dashboard" / "data" / "chatloop_eval_history.json"

_RUN_COLS = (
    "run_id, created_at, git_sha, mode, dispatch, sut_model, judge_model, simulator_model, "
    "k, max_steps, max_turns, case_count, duration_ms, cost_cny, total_tokens, "
    "system_prompt_sha, sampling_json, thresholds_json, status"
)


def export_history(out_path: Path = _DEFAULT_OUT, *, limit: int = 50) -> dict[str, Any]:
    """查最近 limit 次 run + 指标 → 写 JSON。返回写出的 dict。"""
    from sqlalchemy import text

    from app.core.database import SessionLocal

    with SessionLocal() as s:
        runs = s.execute(
            text(f"SELECT {_RUN_COLS} FROM chatloop_eval_runs ORDER BY created_at DESC LIMIT :n"),
            {"n": limit},
        ).all()
        run_dicts = [dict(r._mapping) for r in runs]
        run_ids = [r["run_id"] for r in run_dicts]
        mets = []
        if run_ids:
            mets = s.execute(
                text(
                    "SELECT run_id, behavior, metric, value, numerator, denominator "
                    "FROM chatloop_eval_metrics WHERE run_id = ANY(:ids)"
                ),
                {"ids": run_ids},
            ).all()

    by_run: dict[str, dict] = defaultdict(dict)
    for m in mets:
        by_run[m.run_id][f"{m.behavior}/{m.metric}"] = {
            "value": m.value,
            "num": m.numerator,
            "den": m.denominator,
        }

    # 时间正序(趋势横轴)
    run_dicts.reverse()
    runs_out = [{**r, "metrics": by_run.get(r["run_id"], {})} for r in run_dicts]
    data: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "latest": runs_out[-1] if runs_out else None,
        "runs": runs_out,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return data


def main() -> int:
    data = export_history()
    print(f"导出 {len(data['runs'])} 次 run → {_DEFAULT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
