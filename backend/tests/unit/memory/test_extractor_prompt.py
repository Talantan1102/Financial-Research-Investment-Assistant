"""抽取 prompt 含裁决规则 + 日期纪律(回归守护;强验证靠 eval --repeat)。

对话流评估写侧根因:抽取 prompt 只列实体/关系类型名,不给"该挑哪个"的规则,
弱模型系统性地挑错(看多白酒→PREFERS→茅台)。探针实证:加裁决规则后 4/4 纠正。
本测试守护这些规则不被回退。
"""

from __future__ import annotations

from uuid import uuid4

from app.memory.extractor import _EXTRACTION_SYSTEM_PROMPT as P
from app.memory.extractor import _build_cross_turn_user_prompt


def test_prompt_has_entity_type_decision_rule() -> None:
    # 板块观点落 Industry、不替用户补个股、逻辑进 properties 不单独成边
    assert "主体粒度" in P or "板块" in P
    assert "不要替他补" in P or "不要替用户补" in P
    assert "properties.logic" in P


def test_prompt_has_relation_arbitration() -> None:
    assert "EXPRESSED_VIEW" in P and "PREFERS" in P
    # 死规则:看多白酒必为 EXPRESSED_VIEW,绝不 PREFERS
    assert "看多白酒" in P and "绝不" in P


def test_prompt_forbids_stance_phrase_label() -> None:
    assert "名词性实体" in P
    assert "谓词短语" in P


def test_cross_turn_prompt_injects_dialogue_date() -> None:
    turns = [
        {
            "episode_id": "e1",
            "episode_index": 0,
            "user_message": "看多白酒",
            "agent_response": "",
            "created_at": "2025-01-06T00:00:00+00:00",
        }
    ]
    out = _build_cross_turn_user_prompt(turns, session_id=uuid4())
    assert "2025-01-06" in out  # 对话日期进了 prompt


def test_prompt_has_date_discipline() -> None:
    assert "对话日期" in P
    assert "不许" in P or "不要编" in P
    assert "未结束" in P and "null" in P
