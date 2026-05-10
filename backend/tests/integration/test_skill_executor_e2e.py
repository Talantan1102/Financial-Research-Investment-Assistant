"""L1 — SkillExecutor + real calculate_dcf.py end-to-end."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.skills.script_schemas import SkillScriptArgs, SkillScriptRef
from app.skills.skill_executor import SkillExecutor


@pytest.fixture
def skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "claude_skills"


@pytest.fixture
def workdir_root(tmp_path) -> Path:
    return tmp_path / "wd"


@pytest.mark.asyncio
async def test_calculate_dcf_through_executor(skills_root, workdir_root):
    ex = SkillExecutor(skills_root=skills_root, workdir_root=workdir_root)
    ref = SkillScriptRef(
        skill_name="financial_analysis",
        script_path="scripts/calculate_dcf.py",
    )
    args = SkillScriptArgs(
        payload={
            "free_cash_flows": [100, 110, 121, 133, 146],
            "wacc": 0.10,
            "terminal_growth": 0.03,
            "shares_outstanding": 1000,
            "net_debt": 200,
        }
    )
    result = await ex.execute(ref=ref, args=args)
    assert result.ok is True
    assert result.stdout_json is not None
    assert "enterprise_value" in result.stdout_json
    assert "per_share" in result.stdout_json
    assert result.elapsed_s < 5.0
