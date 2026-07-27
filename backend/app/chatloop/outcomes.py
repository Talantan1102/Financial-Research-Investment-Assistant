"""Bounded terminal outcomes emitted by completed chat runs."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ActionRequiredOutcome(BaseModel):
    """A completed run that directs the user to an internal next action only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Literal["action_required"] = "action_required"
    action_type: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    action_url: str = Field(min_length=1, max_length=512, pattern=r"^/")
    action_label: str = Field(min_length=1, max_length=80)
    resume_hint: str = Field(min_length=1, max_length=240)
    intent_summary: str = Field(min_length=1, max_length=500)

    @field_validator("action_url")
    @classmethod
    def reject_protocol_relative_url(cls, value: str) -> str:
        """Allow only a site-local, relative navigation path."""
        if value.startswith("//"):
            raise ValueError("action_url must be an internal relative path")
        return value
