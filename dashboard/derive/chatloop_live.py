"""chatloop 实时评估成绩单 —— 读 backend 导出的历史 JSON(blueprint § 9 闭环"读"半)。

数据源:dashboard/data/chatloop_eval_history.json(backend `eval.chatloop.export_dashboard`
每次落库后刷新)。看板 PG-free,按现成"读数据文件"模式渲染最新成绩单 + 历次趋势。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_HISTORY = Path(__file__).resolve().parent.parent / "data" / "chatloop_eval_history.json"

# 趋势列固定顺序(出现的才显示);其余按字母补在后面。
_KEY_METRICS: tuple[str, ...] = (
    "routing_tool/RelAcc",
    "abstain/IrrelAcc",
    "policy/disclaimer_compliance",
    "policy/advice_violations",
    "reliability/passk",
    "grounding/strict_faith",
    "grounding/lenient_faith_0.8",
    "multiturn/goal_met",
)

# 指标短名(表头)
_LABELS: dict[str, str] = {
    "routing_tool/RelAcc": "RelAcc",
    "abstain/IrrelAcc": "IrrelAcc",
    "policy/disclaimer_compliance": "免责合规",
    "policy/advice_violations": "方向性违例",
    "reliability/passk": "pass^k",
    "grounding/strict_faith": "grounding严格",
    "grounding/lenient_faith_0.8": "grounding宽松",
    "multiturn/goal_met": "多轮目标达成",
}


@dataclass(frozen=True)
class LiveScorecard:
    generated_at: str
    latest: dict
    runs: tuple[dict, ...]
    metric_keys: tuple[str, ...]

    def label(self, key: str) -> str:
        return _LABELS.get(key, key)

    def cell(self, run: dict, key: str) -> str:
        """一个 run 在某指标的展示值。比例→百分比(分子/分母);违例→计数。"""
        m = (run.get("metrics") or {}).get(key)
        if not m or m.get("value") is None:
            return "—"
        v = m["value"]
        if key.endswith("advice_violations"):
            return str(int(v))
        s = f"{v:.0%}"
        num, den = m.get("num"), m.get("den")
        if num is not None and den:
            s += f" ({num}/{den})"
        return s

    def short_time(self, run: dict) -> str:
        t = str(run.get("created_at") or "")
        return t.replace("T", " ")[5:16]  # MM-DD HH:MM


def load_live(path: Path = _HISTORY) -> LiveScorecard:
    if not path.exists():
        raise FileNotFoundError(f"chatloop 评估历史未生成:{path}(先跑一次 run_eval,会自动导出)")
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = tuple(data.get("runs") or [])
    present: set[str] = set()
    for r in runs:
        present.update((r.get("metrics") or {}).keys())
    keys = [k for k in _KEY_METRICS if k in present] + sorted(present - set(_KEY_METRICS))
    return LiveScorecard(
        generated_at=str(data.get("generated_at") or ""),
        latest=data.get("latest") or {},
        runs=runs,
        metric_keys=tuple(keys),
    )
