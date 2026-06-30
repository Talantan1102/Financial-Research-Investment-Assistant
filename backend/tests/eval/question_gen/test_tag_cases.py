import json

from eval.question_gen import case as case_mod
from eval.question_gen import runner, tag_cases


def _case(cid, intent="snapshot_quote", shape="scalar", difficulty="简单"):
    return case_mod.ComputationCase(
        case_id=cid,
        intent=intent,
        difficulty=difficulty,
        question="?",
        stocks=["600519.SH"],
        indicator="PE",
        window="snapshot",
        gold=1.0,
        gold_shape=shape,
        tolerance={"kind": "rel", "value": 0.01},
        meta={},
    )


def test_build_manifest_rows():
    cases = [_case("a"), _case("b", intent="stock_study", shape="ranking")]
    counts = {"a": 4, "b": 0}  # a 黄金带, b too_hard
    clean = {"a": 2, "b": 0}
    rows = {r["case_id"]: r for r in tag_cases.build_manifest_rows(counts, 8, clean, cases)}
    assert rows["a"]["tags"]["label"] == "rl_band" and rows["a"]["tags"]["prime"] is True
    assert rows["a"]["reward_eligible"] is True and rows["a"]["sft_clean_count"] == 2
    assert rows["a"]["intent"] == "snapshot_quote"
    assert rows["b"]["tags"]["label"] == "too_hard"
    assert rows["b"]["reward_eligible"] is False  # ranking 不进奖励


def test_build_manifest_rows_missing_counts_default_zero():
    rows = tag_cases.build_manifest_rows({}, 8, {}, [_case("z")])
    assert rows[0]["pass_count"] == 0 and rows[0]["tags"]["label"] == "too_hard"


def test_dump_manifest_roundtrip(tmp_path):
    rows = tag_cases.build_manifest_rows({"a": 4}, 8, {"a": 1}, [_case("a")])
    p = tmp_path / "m.jsonl"
    tag_cases.dump_manifest(rows, p)
    loaded = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]
    assert loaded[0]["case_id"] == "a" and loaded[0]["reward_eligible"] is True


def _patch_run_passk(monkeypatch, base_counts, trajs_by_strong):
    """mock runner.run_passk:无 collect_dir = 基座(返回 per_case_counts);
    带 collect_dir = 强模型采集(写 trajectories_raw.jsonl)。记录每次调用。"""
    calls = []

    async def fake_run_passk(cases, *, k, model=None, collect_dir=None, **kw):
        calls.append({"k": k, "model": model, "collect": collect_dir is not None})
        if collect_dir is None:
            return {"per_case_counts": dict(base_counts)}
        collect_dir.mkdir(parents=True, exist_ok=True)
        with (collect_dir / "trajectories_raw.jsonl").open("w", encoding="utf-8") as f:
            for t in trajs_by_strong:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        return {}

    monkeypatch.setattr(runner, "run_passk", fake_run_passk)
    return calls


async def test_run_tagging_produces_manifest(tmp_path, monkeypatch):
    # a 简单(ideal=4), b 中等(ideal=6)
    cases = [
        _case("a", difficulty="简单"),
        _case("b", intent="financial_report", difficulty="中等"),
    ]
    cand = tmp_path / "cand.jsonl"
    case_mod.dump_jsonl(cases, cand)

    trajs = [
        {"case_id": "a", "halt_reason": "natural", "n_steps": 3},  # 干净(≤4)
        {"case_id": "a", "halt_reason": "natural", "n_steps": 9},  # 步数超 → 不干净
        {"case_id": "b", "halt_reason": "hit_cap", "n_steps": 2},  # halt 非自然 → 不干净
        {"case_id": "b", "halt_reason": "natural", "n_steps": 6},  # 干净(≤6)
    ]
    calls = _patch_run_passk(monkeypatch, {"a": 5, "b": 1}, trajs)

    manifest = tmp_path / "manifest.jsonl"
    await tag_cases.run_tagging(
        candidate_path=cand,
        out_manifest=manifest,
        base_model="qwen3-8b",
        strong_model="deepseek-chat",
        collect_dir=tmp_path / "traj",
        n_base=8,
        k_strong=5,
        ideal_steps_by_diff={"简单": 4, "中等": 6},
    )

    # 编排:先基座(无 collect)再强模型(collect),k 与 model 正确
    assert calls == [
        {"k": 8, "model": "qwen3-8b", "collect": False},
        {"k": 5, "model": "deepseek-chat", "collect": True},
    ]
    rows = {
        r["case_id"]: r for r in (json.loads(x) for x in manifest.read_text("utf-8").splitlines())
    }
    assert rows["a"]["pass_count"] == 5 and rows["a"]["n"] == 8
    assert rows["a"]["sft_clean_count"] == 1  # 4 条里仅 n_steps=3 干净
    assert rows["b"]["pass_count"] == 1
    assert rows["b"]["sft_clean_count"] == 1  # 仅 natural∧≤6 那条


async def test_run_tagging_ideal_steps_fallback(tmp_path, monkeypatch):
    # 难度"复杂"不在 ideal_steps_by_diff → fallback 默认 8 步
    cases = [_case("c", difficulty="复杂")]
    cand = tmp_path / "cand.jsonl"
    case_mod.dump_jsonl(cases, cand)
    trajs = [{"case_id": "c", "halt_reason": "natural", "n_steps": 7}]  # ≤8 默认 → 干净
    _patch_run_passk(monkeypatch, {"c": 3}, trajs)

    manifest = tmp_path / "m.jsonl"
    await tag_cases.run_tagging(
        candidate_path=cand,
        out_manifest=manifest,
        base_model="b",
        strong_model="s",
        collect_dir=tmp_path / "traj",
        ideal_steps_by_diff={"简单": 4},  # 不含"复杂"
    )
    row = json.loads(manifest.read_text("utf-8").splitlines()[0])
    assert row["sft_clean_count"] == 1
