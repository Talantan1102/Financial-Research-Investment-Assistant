from __future__ import annotations

import json
from pathlib import Path

import pytest
from eval.chatloop.judge_calibration import (
    MIN_AGREEMENT,
    MIN_COHEN_KAPPA,
    MIN_SAMPLE_COUNT,
    CalibrationDataError,
    CalibrationLabel,
    JudgeCalibrationGate,
    JudgeCalibrationItem,
    JudgeNotCalibratedError,
    evaluate_calibration,
    load_calibration_jsonl,
)

_IDENTITY = {
    "judge_model": "judge-model-v1",
    "judge_prompt_sha256": "a" * 64,
    "rubric_version": "business-semantic-v1",
}


def _items(count: int = MIN_SAMPLE_COUNT) -> tuple[JudgeCalibrationItem, ...]:
    return tuple(
        JudgeCalibrationItem(
            id=f"sample-{index:02d}",
            human_label=(CalibrationLabel.PASS if index % 2 == 0 else CalibrationLabel.FAIL),
            judge_label=(CalibrationLabel.PASS if index % 2 == 0 else CalibrationLabel.FAIL),
            **_IDENTITY,
        )
        for index in range(count)
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_perfect_thirty_item_calibration_opens_gate() -> None:
    result = evaluate_calibration(_items())

    assert MIN_SAMPLE_COUNT == 30
    assert MIN_COHEN_KAPPA == 0.6
    assert MIN_AGREEMENT == 0.8
    assert result.sample_count == 30
    assert result.agreement == pytest.approx(1.0)
    assert result.cohen_kappa == pytest.approx(1.0)
    assert result.calibrated is True
    assert result.review_items == ()


def test_sample_count_below_thirty_keeps_gate_closed() -> None:
    result = evaluate_calibration(_items(MIN_SAMPLE_COUNT - 1))

    assert result.calibrated is False
    assert result.failure_reasons == ("sample_count_below_minimum",)


def test_single_label_calibration_has_undefined_kappa_and_keeps_gate_closed() -> None:
    rows = tuple(
        JudgeCalibrationItem(
            id=f"sample-{index:02d}",
            human_label=CalibrationLabel.PASS,
            judge_label=CalibrationLabel.PASS,
            **_IDENTITY,
        )
        for index in range(MIN_SAMPLE_COUNT)
    )

    result = evaluate_calibration(rows)

    assert result.agreement == pytest.approx(1.0)
    assert result.cohen_kappa is None
    assert result.calibrated is False
    assert result.failure_reasons == ("cohen_kappa_undefined",)


def test_unknown_never_opens_gate_and_is_always_reviewed() -> None:
    rows = list(_items())
    rows[0] = JudgeCalibrationItem(
        id=rows[0].id,
        human_label=CalibrationLabel.UNKNOWN,
        judge_label=CalibrationLabel.UNKNOWN,
        **_IDENTITY,
    )

    result = evaluate_calibration(rows)

    assert result.agreement == pytest.approx(1.0)
    assert result.calibrated is False
    assert result.failure_reasons == ("unknown_labels_present",)
    assert result.review_items == (rows[0],)


def test_disagreements_are_reviewed_even_when_thresholds_still_pass() -> None:
    rows = list(_items())
    rows[0] = JudgeCalibrationItem(
        id=rows[0].id,
        human_label=rows[0].human_label,
        judge_label=CalibrationLabel.FAIL,
        **_IDENTITY,
    )
    rows[1] = JudgeCalibrationItem(
        id=rows[1].id,
        human_label=rows[1].human_label,
        judge_label=CalibrationLabel.PASS,
        **_IDENTITY,
    )

    result = evaluate_calibration(rows)

    assert result.agreement == pytest.approx(28 / 30)
    assert result.cohen_kappa == pytest.approx(13 / 15)
    assert result.calibrated is True
    assert result.review_items == (rows[0], rows[1])


def test_gate_api_rejects_uncalibrated_result_and_accepts_calibrated_result() -> None:
    JudgeCalibrationGate.from_items(_items()).require_calibrated()

    gate = JudgeCalibrationGate.from_items(_items(MIN_SAMPLE_COUNT - 1))
    with pytest.raises(JudgeNotCalibratedError, match="sample_count_below_minimum"):
        gate.require_calibrated()


def test_jsonl_loader_returns_typed_three_label_contract(tmp_path: Path) -> None:
    path = tmp_path / "calibration.jsonl"
    _write_jsonl(
        path,
        [
            {"id": "pass", "human_label": "pass", "judge_label": "pass", **_IDENTITY},
            {"id": "fail", "human_label": "fail", "judge_label": "fail", **_IDENTITY},
            {
                "id": "unknown",
                "human_label": "unknown",
                "judge_label": "unknown",
                **_IDENTITY,
            },
        ],
    )

    rows = load_calibration_jsonl(path)

    assert rows == (
        JudgeCalibrationItem(
            id="pass",
            human_label=CalibrationLabel.PASS,
            judge_label=CalibrationLabel.PASS,
            **_IDENTITY,
        ),
        JudgeCalibrationItem(
            id="fail",
            human_label=CalibrationLabel.FAIL,
            judge_label=CalibrationLabel.FAIL,
            **_IDENTITY,
        ),
        JudgeCalibrationItem(
            id="unknown",
            human_label=CalibrationLabel.UNKNOWN,
            judge_label=CalibrationLabel.UNKNOWN,
            **_IDENTITY,
        ),
    )


def test_jsonl_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.jsonl"
    _write_jsonl(
        path,
        [
            {"id": "same", "human_label": "pass", "judge_label": "pass", **_IDENTITY},
            {"id": "same", "human_label": "fail", "judge_label": "fail", **_IDENTITY},
        ],
    )

    with pytest.raises(CalibrationDataError, match="duplicate id.*same"):
        load_calibration_jsonl(path)


@pytest.mark.parametrize(
    "missing",
    [
        "id",
        "human_label",
        "judge_label",
        "judge_model",
        "judge_prompt_sha256",
        "rubric_version",
    ],
)
def test_jsonl_loader_rejects_missing_fields(tmp_path: Path, missing: str) -> None:
    path = tmp_path / f"missing-{missing}.jsonl"
    row = {"id": "sample", "human_label": "pass", "judge_label": "pass", **_IDENTITY}
    del row[missing]
    _write_jsonl(path, [row])

    with pytest.raises(CalibrationDataError, match=f"missing fields.*{missing}"):
        load_calibration_jsonl(path)


@pytest.mark.parametrize("field", ["human_label", "judge_label"])
def test_jsonl_loader_rejects_illegal_labels(tmp_path: Path, field: str) -> None:
    path = tmp_path / f"illegal-{field}.jsonl"
    row = {"id": "sample", "human_label": "pass", "judge_label": "pass", **_IDENTITY}
    row[field] = "maybe"
    _write_jsonl(path, [row])

    with pytest.raises(CalibrationDataError, match=f"invalid {field}.*maybe"):
        load_calibration_jsonl(path)


def test_jsonl_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "extra.jsonl"
    _write_jsonl(
        path,
        [
            {
                "id": "sample",
                "human_label": "pass",
                "judge_label": "pass",
                **_IDENTITY,
                "notes": "not part of the contract",
            }
        ],
    )

    with pytest.raises(CalibrationDataError, match="unknown fields.*notes"):
        load_calibration_jsonl(path)


def test_gate_rejects_calibration_from_another_model_prompt_or_rubric() -> None:
    gate = JudgeCalibrationGate.from_items(
        _items(),
        expected_identity={
            "judge_model": "judge-model-v2",
            "judge_prompt_sha256": "b" * 64,
            "rubric_version": "business-semantic-v2",
        },
    )

    with pytest.raises(JudgeNotCalibratedError, match="identity_mismatch"):
        gate.require_calibrated()
