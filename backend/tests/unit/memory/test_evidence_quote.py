"""L0 — evidence_quote substring 校验 (algorithm 深度补丁 #2).

Plan 4 ship minimal version. Plan 5 will Edit injection_classifier.py to add
is_prompt_injection (NOT replacing evidence_quote_in_episode).
"""

from __future__ import annotations


def test_substring_exact_match() -> None:
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("我买了500股茅台", "今天我买了500股茅台,记一下") is True


def test_substring_with_whitespace_normalization() -> None:
    """Allow extra space normalization for robustness."""
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("买了 500 股", "我买了500股茅台") is True


def test_no_substring() -> None:
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("我卖了茅台", "今天我买了500股茅台") is False


def test_empty_quote_rejected() -> None:
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("", "anything") is False


def test_whitespace_only_quote_rejected() -> None:
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("   \n  ", "anything") is False


def test_empty_episode_text_rejected() -> None:
    from app.memory.injection_classifier import evidence_quote_in_episode

    assert evidence_quote_in_episode("我买了茅台", "") is False


def test_evidence_not_found_error_class() -> None:
    from app.memory.injection_classifier import EvidenceNotFoundError

    assert issubclass(EvidenceNotFoundError, ValueError)
