"""脚本 schema 加载器测试:合法脚本全字段类型化,非法脚本 fail loud。"""

from __future__ import annotations

from pathlib import Path

import pytest
from eval.memory_dialogue.script_schema import load_script


def _write_minimal(tmp_path: Path) -> Path:
    p = tmp_path / "s.yaml"
    p.write_text(
        """
script_id: viewpoint-minimal
title: "最小观点脚本"
family: 观点演化族
substrate: 观点演化
sessions:
  - n: 1
    date: 2025-01-06
    length: 中
    turns:
      - u: "白酒我研究完了,结论是看多,逻辑是提价权"
      - a: "(回应)"
  - n: 2
    date: 2025-02-03
    length: 短
    turns:
      - u: "美联储议息怎么看"
      - a: "(简要分析)"
db_assertions:
  - after: 1
    assert:
      - {type: fact_active, rel_type: HOLDS_VIEW, target_label: 白酒, value_contains: ["看多"]}
probes:
  - tier: 直球
    dimension: 知识更新
    q: "我对白酒什么看法?"
    expect_contain: ["看多"]
    expect_not: []
    judge_rubric: "答案应包含看多观点与提价权逻辑"
""",
        encoding="utf-8",
    )
    return p


def test_load_minimal_script(tmp_path: Path) -> None:
    s = load_script(_write_minimal(tmp_path))
    assert s.script_id == "viewpoint-minimal"
    assert s.family == "观点演化族"
    assert len(s.sessions) == 2
    assert s.sessions[0].date.isoformat() == "2025-01-06"
    assert s.sessions[0].turns[0].role == "u"
    assert s.db_assertions[0].after_session == 1
    assert s.db_assertions[0].checks[0].type == "fact_active"
    assert s.probes[0].tier == "直球"
    assert s.probes[0].dimension == "知识更新"
    assert s.probes[0].swap_order_invariant is False  # 默认关
    assert s.probes[0].answerable is True  # 默认可答


def test_missing_required_field_fails_loud(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "script_id: x\ntitle: t\nfamily: 观点演化族\nsubstrate: 观点演化\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sessions"):
        load_script(p)


def test_invalid_tier_fails_loud(tmp_path: Path) -> None:
    good = _write_minimal(tmp_path).read_text(encoding="utf-8")
    p = tmp_path / "bad_tier.yaml"
    p.write_text(good.replace("tier: 直球", "tier: 入门"), encoding="utf-8")
    with pytest.raises(ValueError, match="tier"):
        load_script(p)
