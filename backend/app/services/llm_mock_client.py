"""MockLLMClient — deterministic ChatClient for L0/L1 tests.

Dispatch order per call:
  1. ``__recorded__:<id>`` prefix  → recorded fixture from recorded/*.json
  2. Exact-match in static dict    → MC1 layer
  3. Regex pattern (first match)   → MC2 layer  (``{group_1}`` interpolation)
  4. raise MockMissError           → fail-loud; no silent empty responses
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

from app.services.llm_service import ChatCompletionRaw

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class MockMissError(LookupError):
    """Raised when no static / pattern / recorded match exists for a prompt."""


# ---------------------------------------------------------------------------
# Internal response model (satisfies ChatCompletionRaw protocol)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RawCompletion:
    """Frozen dataclass — satisfies the ChatCompletionRaw Protocol."""

    content: str
    prompt_tokens: int
    completion_tokens: int


# ---------------------------------------------------------------------------
# Pydantic models for YAML schema parsing
# ---------------------------------------------------------------------------


class _ResponseBlock(BaseModel):
    content: str
    prompt_tokens: int
    completion_tokens: int


class _Entry(BaseModel):
    exact: str | None = None
    pattern: str | None = None
    response: _ResponseBlock


class _FixtureFile(BaseModel):
    entries: list[_Entry]


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------


class MockLLMClient:
    """Implements the ChatClient protocol for test usage — zero I/O per call."""

    def __init__(
        self,
        static: dict[str, _RawCompletion],
        patterns: list[tuple[re.Pattern[str], str, _RawCompletion]],
        recorded: dict[str, _RawCompletion],
    ) -> None:
        self._static = static
        self._patterns = patterns
        self._recorded = recorded

    @classmethod
    def from_fixture_dir(cls, path: Path) -> MockLLMClient:
        """Load ``agent_decisions.yaml`` and index ``recorded/*.json`` from *path*."""
        yaml_path = path / "agent_decisions.yaml"
        raw_yaml: Any = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        fixture_file = _FixtureFile.model_validate(raw_yaml)

        static: dict[str, _RawCompletion] = {}
        patterns: list[tuple[re.Pattern[str], str, _RawCompletion]] = []

        for entry in fixture_file.entries:
            completion = _RawCompletion(
                content=entry.response.content,
                prompt_tokens=entry.response.prompt_tokens,
                completion_tokens=entry.response.completion_tokens,
            )
            if entry.exact is not None:
                static[entry.exact] = completion
            elif entry.pattern is not None:
                compiled = re.compile(entry.pattern)
                patterns.append((compiled, entry.response.content, completion))

        recorded: dict[str, _RawCompletion] = {}
        recorded_dir = path / "recorded"
        if recorded_dir.is_dir():
            for json_file in sorted(recorded_dir.glob("*.json")):
                raw_json: Any = json.loads(json_file.read_text(encoding="utf-8"))
                record_id: str = raw_json["id"]
                resp = raw_json["response"]
                recorded[record_id] = _RawCompletion(
                    content=resp["content"],
                    prompt_tokens=int(resp["prompt_tokens"]),
                    completion_tokens=int(resp["completion_tokens"]),
                )

        return cls(static=static, patterns=patterns, recorded=recorded)

    def chat(
        self,
        prompt: str,
        model: str,
        schema: dict[str, Any] | None,
    ) -> ChatCompletionRaw:
        """Dispatch prompt through MC4 → MC1 → MC2 → fail-loud."""
        # 1. Recorded fixture short-circuit
        if prompt.startswith("__recorded__:"):
            record_id = prompt[len("__recorded__:") :]
            if record_id in self._recorded:
                return self._recorded[record_id]

        # 2. Exact-match static dict
        if prompt in self._static:
            return self._static[prompt]

        # 3. Regex pattern entries (first match wins, {group_1} interpolation)
        for compiled_pattern, template, base_completion in self._patterns:
            m = compiled_pattern.search(prompt)
            if m is not None:
                try:
                    interpolated = template.format(group_1=m.group(1))
                except IndexError:
                    interpolated = template
                # If the interpolated content is a recorded-fixture pointer,
                # resolve it through the recorded-fixture index.
                if interpolated.startswith("__recorded__:"):
                    record_id = interpolated[len("__recorded__:") :]
                    if record_id in self._recorded:
                        return self._recorded[record_id]
                return _RawCompletion(
                    content=interpolated,
                    prompt_tokens=base_completion.prompt_tokens,
                    completion_tokens=base_completion.completion_tokens,
                )

        # 4. Fail-loud
        raise MockMissError(f"no static / pattern / recorded match for prompt: {prompt!r}")
