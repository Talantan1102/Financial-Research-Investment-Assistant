"""L0 smoke tests for E9 extraction quality metric functions (no DB)."""

from __future__ import annotations

from tests.eval.extraction_quality_eval import (
    compute_entity_metrics,
    compute_field_accuracy,
    compute_missing_field_quality,
    compute_preference_f1,
    flatten_paths,
)


def make_packet(
    *,
    entities: list[dict] | None = None,
    preferences: list[dict] | None = None,
    missing_hints: list[dict] | None = None,
) -> dict:
    return {
        "explicit_task": {
            "raw_last_user_turn": "x",
            "extracted_intent": "y",
            "target_ts_code": "601398.SH",
            "target_entity_name": "工商银行",
            "user_extra_message": None,
        },
        "chat_derived_signals": {
            "entities": entities or [],
            "preferences": preferences or [],
            "open_questions": [],
            "inferred_persona": None,
            "extraction_confidence": 0.8,
        },
        "known_facts": {"tool_results": []},
        "session_metadata": {
            "chat_session_id": "s1",
            "chat_turn_count": 1,
            "chat_history_summary": None,
            "user_confirmed_at": "",
            "user_edits": [],
        },
        "missing_field_hints": missing_hints or [],
    }


class TestFlattenPaths:
    def test_flat_dict(self):
        paths = flatten_paths({"a": 1, "b": "x"})
        assert paths == {"a", "b"}

    def test_nested(self):
        paths = flatten_paths({"a": {"b": 1, "c": 2}})
        assert paths == {"a.b", "a.c"}


class TestFieldAccuracy:
    def test_no_edits_perfect(self):
        draft = make_packet()
        assert compute_field_accuracy(draft, []) == 1.0

    def test_one_edit_drops_below_one(self):
        draft = make_packet()
        edits = [
            {
                "field_path": "explicit_task.target_ts_code",
                "llm_value": "601398.SH",
                "user_value": "600036.SH",
                "edit_type": "modify",
            }
        ]
        acc = compute_field_accuracy(draft, edits)
        assert 0.0 < acc < 1.0


class TestEntityMetrics:
    def test_perfect_match(self):
        ent = [
            {
                "name": "工商银行",
                "ts_code": "601398.SH",
                "role": "primary_target",
                "mention_turn_indices": [0],
            }
        ]
        d = make_packet(entities=ent)
        c = make_packet(entities=ent)
        recall, precision = compute_entity_metrics(d, c)
        assert recall == 1.0
        assert precision == 1.0

    def test_missing_entity_lowers_recall(self):
        d = make_packet(entities=[])
        c = make_packet(
            entities=[
                {
                    "name": "工商银行",
                    "ts_code": "601398.SH",
                    "role": "primary_target",
                    "mention_turn_indices": [0],
                }
            ],
        )
        recall, _ = compute_entity_metrics(d, c)
        assert recall == 0.0

    def test_extra_entity_lowers_precision(self):
        d = make_packet(
            entities=[
                {
                    "name": "工商银行",
                    "ts_code": "601398.SH",
                    "role": "primary_target",
                    "mention_turn_indices": [0],
                },
                {
                    "name": "招商银行",
                    "ts_code": "600036.SH",
                    "role": "comparative_target",
                    "mention_turn_indices": [],
                },
            ]
        )
        c = make_packet(
            entities=[
                {
                    "name": "工商银行",
                    "ts_code": "601398.SH",
                    "role": "primary_target",
                    "mention_turn_indices": [0],
                }
            ]
        )
        _, precision = compute_entity_metrics(d, c)
        assert precision == 0.5


class TestPreferenceF1:
    def test_perfect_match_returns_one(self):
        p = [{"text": "看股息", "category": "focus_metric", "confidence": 0.7}]
        d = make_packet(preferences=p)
        c = make_packet(preferences=p)
        assert compute_preference_f1(d, c) == 1.0

    def test_partial_overlap(self):
        d = make_packet(
            preferences=[
                {"text": "看股息", "category": "focus_metric", "confidence": 0.7},
                {"text": "保守", "category": "risk_tolerance", "confidence": 0.8},
            ]
        )
        c = make_packet(
            preferences=[
                {"text": "看股息", "category": "focus_metric", "confidence": 0.7},
            ]
        )
        f1 = compute_preference_f1(d, c)
        assert 0.0 < f1 < 1.0


class TestMissingFieldQuality:
    def test_no_hints_perfect(self):
        d = make_packet()
        c = make_packet()
        assert compute_missing_field_quality(d, c) == 1.0

    def test_user_filled_hint_perfect(self):
        d = make_packet(
            missing_hints=[
                {
                    "field_path": "explicit_task.user_extra_message",
                    "reason": "llm_uncertain",
                    "llm_question_for_user": "any preference?",
                }
            ]
        )
        c = make_packet()
        c["explicit_task"]["user_extra_message"] = "保守 + 看股息"
        assert compute_missing_field_quality(d, c) == 1.0

    def test_user_skipped_hint_zero(self):
        d = make_packet(
            missing_hints=[
                {
                    "field_path": "explicit_task.user_extra_message",
                    "reason": "llm_uncertain",
                    "llm_question_for_user": "any preference?",
                }
            ]
        )
        c = make_packet()
        # user_extra_message stays None
        assert compute_missing_field_quality(d, c) == 0.0
