from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256

import pytest
from eval.chatloop.artifact_store import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    ArtifactReference,
    ArtifactStore,
    read_verified_artifact,
)


def _bundle(*, final_answer: str = "先别急着下单") -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "run-001",
        "trial_id": "trial-001",
        "case_id": "B6-01",
        "trial_index": 0,
        "transcript": [{"role": "assistant", "content": final_answer}],
        "tool_ledger": [],
        "database_before_after": {"before": {}, "after": {}},
        "versions": {
            "case": "2026.1",
            "policy": "2026.1",
            "evaluator": "2026.1",
            "model": "fake-model",
            "prompt_sha256": "a" * 64,
            "git_sha": "deadbeef",
        },
        "random_seed": 7,
        "duration_ms": 123,
        "cost": {"cny": 0.01, "total_tokens": 42},
    }


def _canonical_forged_payload_with_cost(value: str) -> bytes:
    bundle = _bundle()
    bundle["cost"] = {"cny": 0, "total_tokens": 42}
    text = json.dumps(
        bundle,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (text.replace('"cny":0', f'"cny":{value}', 1) + "\n").encode("utf-8")


def test_artifact_bundle_is_atomic_canonical_and_hashed(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    reference = store.write(_bundle())

    assert reference.path.exists()
    payload = reference.path.read_bytes()
    assert reference.sha256 == sha256(payload).hexdigest()
    assert json.loads(payload) == _bundle()
    assert not list(tmp_path.rglob("*.tmp"))


def test_identical_artifact_write_is_idempotent_but_conflicting_rewrite_is_rejected(
    tmp_path,
) -> None:
    store = ArtifactStore(tmp_path)
    first = store.write(_bundle())

    assert store.write(_bundle()) == first

    with pytest.raises(ArtifactConflictError, match="trial-001"):
        store.write(_bundle(final_answer="已经替你买好了"))


def test_artifact_hash_detects_post_write_tampering(tmp_path) -> None:
    reference = ArtifactStore(tmp_path).write(_bundle())
    reference.path.write_bytes(reference.path.read_bytes() + b" ")

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        read_verified_artifact(reference)


@pytest.mark.parametrize("field", ["run_id", "trial_id", "case_id"])
def test_artifact_identity_rejects_path_traversal(tmp_path, field: str) -> None:
    bundle = _bundle()
    bundle[field] = "../escape"

    with pytest.raises(ValueError, match=field):
        ArtifactStore(tmp_path).write(bundle)


@pytest.mark.parametrize(
    "field",
    [
        "transcript",
        "tool_ledger",
        "database_before_after",
        "versions",
        "random_seed",
        "duration_ms",
        "cost",
    ],
)
def test_artifact_rejects_incomplete_evidence(tmp_path, field: str) -> None:
    bundle = _bundle()
    del bundle[field]

    with pytest.raises(ValueError, match=field):
        ArtifactStore(tmp_path).write(bundle)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda bundle: bundle.update(schema_version=True), "schema_version"),
        (lambda bundle: bundle.update(cost={}), "cost"),
        (lambda bundle: bundle.update(cost={"cny": float("inf"), "total_tokens": 1}), "cost.cny"),
        (
            lambda bundle: bundle.update(database_before_after={"before": None, "after": {}}),
            "before",
        ),
        (lambda bundle: bundle["versions"].update(model=None), "versions.model"),
        (
            lambda bundle: bundle.update(transcript=[{"role": "assistant"}]),
            "transcript",
        ),
        (
            lambda bundle: bundle.update(tool_ledger=[{"tool_name": "quote"}]),
            "tool_ledger",
        ),
    ],
)
def test_artifact_rejects_incomplete_nested_evidence(tmp_path, mutation, match) -> None:
    bundle = _bundle()
    mutation(bundle)

    with pytest.raises(ValueError, match=match):
        ArtifactStore(tmp_path).write(bundle)


def test_verified_read_rejects_a_hashed_but_incomplete_bundle(tmp_path) -> None:
    path = tmp_path / "forged.json"
    payload = b'{"case_id":"B6-01","run_id":"run-001","trial_id":"trial-001","trial_index":0}\n'
    path.write_bytes(payload)

    with pytest.raises(ArtifactIntegrityError, match="incomplete"):
        read_verified_artifact(ArtifactReference(path=path, sha256=sha256(payload).hexdigest()))


def test_verified_read_rejects_nonfinite_cost_from_forged_json(tmp_path) -> None:
    path = tmp_path / "forged-infinite-cost.json"
    payload = _canonical_forged_payload_with_cost("1e9999")
    path.write_bytes(payload)

    with pytest.raises(ArtifactIntegrityError, match="cost.cny"):
        read_verified_artifact(ArtifactReference(path=path, sha256=sha256(payload).hexdigest()))


def test_concurrent_identical_writes_are_idempotent(tmp_path) -> None:
    store = ArtifactStore(tmp_path)

    with ThreadPoolExecutor(max_workers=16) as executor:
        references = list(executor.map(lambda _: store.write(_bundle()), range(32)))

    assert len(set(references)) == 1
    assert len(list(tmp_path.rglob("*.json"))) == 1
    assert not list(tmp_path.rglob("*.tmp"))


def test_concurrent_conflicting_writes_publish_exactly_one_bundle(tmp_path) -> None:
    store = ArtifactStore(tmp_path)
    bundles = [_bundle(final_answer="版本一"), _bundle(final_answer="版本二")]

    def write(bundle):
        try:
            return store.write(bundle)
        except ArtifactConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, bundles))

    assert sum(isinstance(result, ArtifactConflictError) for result in results) == 1
    assert len(list(tmp_path.rglob("*.json"))) == 1
    assert not list(tmp_path.rglob("*.tmp"))


def test_link_failure_cleans_up_temporary_file(tmp_path, monkeypatch) -> None:
    def fail_link(*_args, **_kwargs):
        raise OSError("simulated link failure")

    monkeypatch.setattr(os, "link", fail_link)

    with pytest.raises(OSError, match="simulated"):
        ArtifactStore(tmp_path).write(_bundle())

    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("*.tmp"))
