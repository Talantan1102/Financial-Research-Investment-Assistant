"""Immutable, content-addressed references for complete trial evidence bundles."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

__all__ = [
    "ArtifactConflictError",
    "ArtifactIntegrityError",
    "ArtifactReference",
    "ArtifactStore",
    "read_verified_artifact",
]


_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REQUIRED_EVIDENCE = {
    "transcript": list,
    "tool_ledger": list,
    "database_before_after": dict,
    "versions": dict,
    "random_seed": int,
    "duration_ms": int,
    "cost": dict,
}
_REQUIRED_VERSIONS = {
    "case",
    "policy",
    "evaluator",
    "model",
    "prompt_sha256",
    "git_sha",
}
_TOOL_LEDGER_KEYS = {"tool_name", "arguments", "result", "error", "idempotency_key"}


class ArtifactConflictError(RuntimeError):
    """Raised when one trial identity is reused for different evidence."""


class ArtifactIntegrityError(RuntimeError):
    """Raised when a stored artifact is missing, malformed, or has changed."""


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    path: Path
    sha256: str


class ArtifactStore:
    """Write canonical JSON bundles atomically beneath one result root."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def write(self, bundle: Mapping[str, Any]) -> ArtifactReference:
        _validate_complete_evidence(bundle)
        run_id = _identity(bundle, "run_id")
        trial_id = _identity(bundle, "trial_id")
        case_id = _identity(bundle, "case_id")
        trial_index = bundle.get("trial_index")
        if isinstance(trial_index, bool) or not isinstance(trial_index, int) or trial_index < 0:
            raise ValueError("trial_index must be a non-negative integer")

        payload = _canonical_json(bundle)
        digest = sha256(payload).hexdigest()
        # ``run_id`` and ``case_id`` were already restricted to single safe path
        # components. Avoid ``Path.resolve()`` here: concurrent first writes can
        # race while Windows resolves a directory that another thread is creating.
        directory = self.root / run_id / case_id
        if not directory.is_relative_to(self.root):
            raise ValueError("artifact path must remain inside the result root")
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{trial_index:03d}-{trial_id}.json"

        if target.exists():
            return _existing_reference(target, payload, digest, trial_id)

        temporary = directory / f".{target.name}.{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                return _existing_reference(target, payload, digest, trial_id)
        finally:
            temporary.unlink(missing_ok=True)

        return ArtifactReference(path=target, sha256=digest)


def _identity(bundle: Mapping[str, Any], field: str) -> str:
    value = bundle.get(field)
    if not isinstance(value, str) or not _IDENTITY.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"{field} must be a safe non-empty identifier")
    return value


def _validate_complete_evidence(bundle: Mapping[str, Any]) -> None:
    schema_version = bundle.get("schema_version")
    if isinstance(schema_version, bool) or schema_version != 1:
        raise ValueError("schema_version must equal 1")
    for field, expected_type in _REQUIRED_EVIDENCE.items():
        value = bundle.get(field)
        if isinstance(value, bool) or not isinstance(value, expected_type):
            raise ValueError(f"{field} is required and has an invalid type")
    transcript = bundle["transcript"]
    for index, entry in enumerate(transcript):
        if not isinstance(entry, Mapping):
            raise ValueError(f"transcript[{index}] must be an object")
        if not isinstance(entry.get("role"), str) or not entry["role"].strip():
            raise ValueError(f"transcript[{index}].role must be a non-empty string")
        if "content" not in entry:
            raise ValueError(f"transcript[{index}] is missing content")

    tool_ledger = bundle["tool_ledger"]
    for index, entry in enumerate(tool_ledger):
        if not isinstance(entry, Mapping):
            raise ValueError(f"tool_ledger[{index}] must be an object")
        missing_tool_fields = sorted(_TOOL_LEDGER_KEYS.difference(entry))
        if missing_tool_fields:
            raise ValueError(
                f"tool_ledger[{index}] is missing required keys: {', '.join(missing_tool_fields)}"
            )
        if not isinstance(entry["tool_name"], str) or not entry["tool_name"].strip():
            raise ValueError(f"tool_ledger[{index}].tool_name must be non-empty")
        if not isinstance(entry["arguments"], Mapping):
            raise ValueError(f"tool_ledger[{index}].arguments must be an object")

    snapshots = bundle["database_before_after"]
    if not {"before", "after"}.issubset(snapshots):
        raise ValueError("database_before_after must contain before and after")
    for field in ("before", "after"):
        if not isinstance(snapshots[field], Mapping):
            raise ValueError(f"database_before_after.{field} must be an object")

    versions = bundle["versions"]
    missing_versions = sorted(_REQUIRED_VERSIONS.difference(versions))
    if missing_versions:
        raise ValueError(f"versions is missing required keys: {', '.join(missing_versions)}")
    for field in _REQUIRED_VERSIONS:
        value = versions[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"versions.{field} must be a non-empty string")
    prompt_digest = versions["prompt_sha256"]
    if len(prompt_digest) != 64 or any(
        character not in "0123456789abcdef" for character in prompt_digest
    ):
        raise ValueError("versions.prompt_sha256 must be 64 lowercase hexadecimal characters")

    cost = bundle["cost"]
    missing_cost = sorted({"cny", "total_tokens"}.difference(cost))
    if missing_cost:
        raise ValueError(f"cost is missing required keys: {', '.join(missing_cost)}")
    cny = cost["cny"]
    if cny is not None and (
        isinstance(cny, bool)
        or not isinstance(cny, (int, float))
        or not math.isfinite(float(cny))
        or not float(cny) >= 0
    ):
        raise ValueError("cost.cny must be a non-negative number or null")
    total_tokens = cost["total_tokens"]
    if total_tokens is not None and (
        isinstance(total_tokens, bool) or not isinstance(total_tokens, int) or total_tokens < 0
    ):
        raise ValueError("cost.total_tokens must be a non-negative integer or null")
    if bundle["random_seed"] < 0:
        raise ValueError("random_seed must be non-negative")
    if bundle["duration_ms"] < 0:
        raise ValueError("duration_ms must be non-negative")


def _canonical_json(bundle: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(
            dict(bundle),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("artifact bundle must be finite JSON data") from exc
    return (text + "\n").encode("utf-8")


def read_verified_artifact(reference: ArtifactReference) -> dict[str, Any]:
    try:
        payload = Path(reference.path).read_bytes()
    except OSError as exc:
        raise ArtifactIntegrityError(f"artifact is unavailable: {reference.path}") from exc
    actual_digest = sha256(payload).hexdigest()
    if actual_digest != reference.sha256:
        raise ArtifactIntegrityError(f"artifact hash mismatch: {reference.path}")
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactIntegrityError(f"artifact is not valid JSON: {reference.path}") from exc
    if not isinstance(decoded, dict):
        raise ArtifactIntegrityError(f"artifact root must be an object: {reference.path}")
    try:
        _validate_complete_evidence(decoded)
    except ValueError as exc:
        raise ArtifactIntegrityError(
            f"artifact evidence is incomplete: {reference.path}: {exc}"
        ) from exc
    return decoded


def _existing_reference(
    target: Path,
    payload: bytes,
    digest: str,
    trial_id: str,
) -> ArtifactReference:
    if target.read_bytes() != payload:
        raise ArtifactConflictError(f"artifact already exists with different evidence: {trial_id}")
    return ArtifactReference(path=target, sha256=digest)
