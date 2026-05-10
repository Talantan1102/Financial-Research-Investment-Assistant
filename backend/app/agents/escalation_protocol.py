"""EscalationPacket — wire format for chat→research escalation handoff (E1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ExplicitTask(BaseModel):
    raw_last_user_turn: str
    extracted_intent: str
    target_ts_code: str | None = None
    target_entity_name: str | None = None
    user_extra_message: str | None = None


class Entity(BaseModel):
    name: str
    ts_code: str | None = None
    role: Literal["primary_target", "comparative_target", "mentioned_in_passing"]
    mention_turn_indices: list[int] = Field(default_factory=list)


class Preference(BaseModel):
    text: str
    category: Literal[
        "risk_tolerance",
        "focus_metric",
        "comparative_focus",
        "horizon",
        "other",
    ]
    confidence: float = Field(ge=0.0, le=1.0)


class ChatDerivedSignals(BaseModel):
    entities: list[Entity] = Field(default_factory=list)
    preferences: list[Preference] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    inferred_persona: str | None = None
    extraction_confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class ToolResultRef(BaseModel):
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    result_summary: str
    cached_at: datetime
    cache_id: str


class KnownFacts(BaseModel):
    tool_results: list[ToolResultRef] = Field(default_factory=list)


class FieldEdit(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    field_path: str
    llm_value: Any
    user_value: Any
    edit_type: Literal["modify", "delete", "add"]


class SessionMetadata(BaseModel):
    chat_session_id: str
    chat_turn_count: int
    chat_history_summary: str | None = None
    user_confirmed_at: datetime
    user_edits: list[FieldEdit] = Field(default_factory=list)


class MissingFieldHint(BaseModel):
    field_path: str
    reason: Literal["llm_uncertain", "schema_required_but_empty", "user_skipped"]
    llm_question_for_user: str


class EscalationPacket(BaseModel):
    explicit_task: ExplicitTask
    chat_derived_signals: ChatDerivedSignals
    known_facts: KnownFacts
    session_metadata: SessionMetadata
    missing_field_hints: list[MissingFieldHint] = Field(default_factory=list)
