"""prefill batch CLI 集成测试 — mock LLMService 验证流程。Plan 1 Task 7。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# backend/ 是 source root,test 跑在项目根,需要把 backend/ 加进 sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.scripts import prefill_deep_cards as pf  # noqa: E402

from dashboard.derive.deep_card_types import AlternativeItem, FieldProvenance  # noqa: E402
from dashboard.derive.llm_prefill_prompt import PrefillResponse  # noqa: E402
from dashboard.state.db import open_db  # noqa: E402
from dashboard.state.repositories import DeepCardRepo  # noqa: E402


def _mock_llm_returns(parsed: PrefillResponse) -> MagicMock:
    m = MagicMock()
    m.content = parsed.model_dump_json()
    m.parsed = parsed
    m.cost_cny = 0.001
    return m


def test_prefill_one_cap_success(tmp_path: Path) -> None:
    # 准备假 spec 文件让 provenance 命中
    src_dir = tmp_path / "docs" / "specs"
    src_dir.mkdir(parents=True)
    (src_dir / "fake.md").write_text(
        "LLM 输出强制走 JSON schema,避免下游解析失败", encoding="utf-8"
    )
    conn = open_db(tmp_path / "board.db")
    repo = DeepCardRepo(conn)

    # 配齐 5 字段 + 5 个 provenance,全部 quote 可命中
    fake_parsed = PrefillResponse(
        what="LLM 输出强制走 JSON schema",
        what_provenance=FieldProvenance(quote="LLM 输出强制走", source="docs/specs/fake.md"),
        why="避免下游解析失败",
        why_provenance=FieldProvenance(quote="避免下游解析失败", source="docs/specs/fake.md"),
        alternatives=[AlternativeItem(name="A", brief_tradeoff="a")],
        alternatives_provenance=FieldProvenance(quote="JSON schema", source="docs/specs/fake.md"),
        chosen_alternative="A",
        chosen_alternative_provenance=FieldProvenance(
            quote="JSON schema", source="docs/specs/fake.md"
        ),
        tradeoff="选 schema 因为协议支持",
        tradeoff_provenance=FieldProvenance(quote="JSON schema", source="docs/specs/fake.md"),
    )
    fake_llm = MagicMock()
    fake_llm.chat.return_value = _mock_llm_returns(fake_parsed)

    cap_ctx = pf.CapPrefillContext(
        cap_id="01.constrained_schema",
        cap_name_cn="输出 Schema 约束",
        linked_specs=["docs/specs/fake.md"],
        linked_memories=[],
        decisions_summary=[],
    )
    result = pf.prefill_one_cap(
        ctx=cap_ctx,
        llm_service=fake_llm,
        repo=repo,
        base_dir=tmp_path,
    )
    assert result.success_fields == 5
    assert result.rejected_fields == 0
    card = repo.get("01.constrained_schema")
    assert card is not None
    assert card.what == "LLM 输出强制走 JSON schema"
    assert card.prefill_source == "llm"


def test_prefill_rejects_fabricated_quote(tmp_path: Path) -> None:
    src_dir = tmp_path / "docs" / "specs"
    src_dir.mkdir(parents=True)
    (src_dir / "fake.md").write_text("Real content unrelated", encoding="utf-8")
    conn = open_db(tmp_path / "board.db")
    repo = DeepCardRepo(conn)

    fake_parsed = PrefillResponse(
        what="编造内容",
        what_provenance=FieldProvenance(quote="完全编造的引用", source="docs/specs/fake.md"),
    )
    fake_llm = MagicMock()
    fake_llm.chat.return_value = _mock_llm_returns(fake_parsed)

    cap_ctx = pf.CapPrefillContext(
        cap_id="x",
        cap_name_cn="x",
        linked_specs=["docs/specs/fake.md"],
        linked_memories=[],
        decisions_summary=[],
    )
    result = pf.prefill_one_cap(ctx=cap_ctx, llm_service=fake_llm, repo=repo, base_dir=tmp_path)
    assert result.rejected_fields >= 1
    card = repo.get("x")
    # what 应该是 None (reject) 而非编造值
    assert card is None or card.what is None


def test_prefill_log_records_status(tmp_path: Path) -> None:
    src_dir = tmp_path / "docs" / "specs"
    src_dir.mkdir(parents=True)
    (src_dir / "fake.md").write_text("LLM 输出 schema", encoding="utf-8")
    conn = open_db(tmp_path / "board.db")
    repo = DeepCardRepo(conn)

    fake_parsed = PrefillResponse(
        what="LLM 输出 schema",
        what_provenance=FieldProvenance(quote="LLM 输出 schema", source="docs/specs/fake.md"),
    )
    fake_llm = MagicMock()
    fake_llm.chat.return_value = _mock_llm_returns(fake_parsed)

    cap_ctx = pf.CapPrefillContext(
        cap_id="z",
        cap_name_cn="z",
        linked_specs=["docs/specs/fake.md"],
        linked_memories=[],
        decisions_summary=[],
    )
    pf.prefill_one_cap(ctx=cap_ctx, llm_service=fake_llm, repo=repo, base_dir=tmp_path)
    cur = conn.execute("SELECT field_name, status FROM prefill_log WHERE cap_id = 'z'")
    rows = cur.fetchall()
    assert len(rows) >= 1


def test_linked_specs_derived_from_provenance(tmp_path: Path) -> None:
    """spec § 4.2:linked_specs 从 provenance.source 自动 dedupe 派生(只取 docs/ 前缀)。"""
    src_dir = tmp_path / "docs" / "specs"
    src_dir.mkdir(parents=True)
    (src_dir / "a.md").write_text("aaa", encoding="utf-8")
    (src_dir / "b.md").write_text("bbb", encoding="utf-8")
    conn = open_db(tmp_path / "board.db")
    repo = DeepCardRepo(conn)

    fake_parsed = PrefillResponse(
        what="aaa",
        what_provenance=FieldProvenance(quote="aaa", source="docs/specs/a.md"),
        why="bbb",
        why_provenance=FieldProvenance(quote="bbb", source="docs/specs/b.md"),
    )
    fake_llm = MagicMock()
    fake_llm.chat.return_value = _mock_llm_returns(fake_parsed)

    cap_ctx = pf.CapPrefillContext(
        cap_id="multi",
        cap_name_cn="multi",
        linked_specs=[],
        linked_memories=[],
        decisions_summary=[],
    )
    pf.prefill_one_cap(ctx=cap_ctx, llm_service=fake_llm, repo=repo, base_dir=tmp_path)
    card = repo.get("multi")
    assert card is not None
    assert "docs/specs/a.md" in card.linked_specs
    assert "docs/specs/b.md" in card.linked_specs


def test_llm_error_logged(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "board.db")
    repo = DeepCardRepo(conn)
    fake_llm = MagicMock()
    fake_llm.chat.side_effect = RuntimeError("LLM timeout")
    cap_ctx = pf.CapPrefillContext(
        cap_id="errcap",
        cap_name_cn="x",
        linked_specs=[],
        linked_memories=[],
        decisions_summary=[],
    )
    result = pf.prefill_one_cap(ctx=cap_ctx, llm_service=fake_llm, repo=repo, base_dir=tmp_path)
    assert result.error is not None
    assert "LLM timeout" in result.error
    cur = conn.execute("SELECT status FROM prefill_log WHERE cap_id = 'errcap'")
    statuses = [r["status"] for r in cur.fetchall()]
    assert "llm_error" in statuses
