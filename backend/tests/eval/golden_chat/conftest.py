"""Shared fixtures for v0.9 chat differential golden cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel


class GoldenCase(BaseModel):
    """Schema for a v0.9 chat differential golden case JSON file."""

    id: str
    description: str
    persona: str = "default"
    chat_history: list[dict[str, Any]]
    final_user_message: str
    expected_signals: list[str]
    expected_tool_calls: list[str] = []
    expected_skills_loaded: list[str] = []
    expected_escalation: bool = False
    judge_rubric: dict[str, Any]


GOLDEN_DIR = Path(__file__).parent


def _load(name: str) -> GoldenCase:
    return GoldenCase(**json.loads((GOLDEN_DIR / f"{name}.json").read_text()))


@pytest.fixture(scope="module")
def golden_short() -> GoldenCase:
    return _load("golden_chat_short")


@pytest.fixture(scope="module")
def golden_medium() -> GoldenCase:
    return _load("golden_chat_medium_with_tools")


@pytest.fixture(scope="module")
def golden_skill() -> GoldenCase:
    return _load("golden_chat_skill_driven")


@pytest.fixture(scope="module")
def golden_escalation() -> GoldenCase:
    return _load("golden_chat_escalation_handoff")


@pytest.fixture(scope="module")
def golden_multi_chat() -> GoldenCase:
    return _load("golden_chat_multi_chat_reconnect")
