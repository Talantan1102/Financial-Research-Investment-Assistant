"""Financial research skill bundle — references + deterministic helpers.

Loader for the financial_research skill bundle. Exposes ``load_skill()``
returning a ``SkillBundle`` containing 11 methodology markdowns, 3 reference
files (industry benchmarks JSON + recommendation rules YAML + position size
rules YAML), and the scripts namespace (3 deterministic helpers).

Module-level loads happen once at import time — Python's GIL makes this
thread-safe for read-only consumers. Pure read-only by design.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from app.skills.financial_research import scripts as _scripts

# ---------------------------------------------------------------------------
# Methodology — 11 markdown files, fixed concat order.
# ---------------------------------------------------------------------------

_METHODOLOGY_DIR = Path(__file__).parent / "methodology"
_METHODOLOGY_ORDER: tuple[str, ...] = (
    "solvency",
    "profitability",
    "growth",
    "cashflow_quality",
    "valuation",
    "industry",
    "shareholder_governance",
    "short_term_capital_flow",
    "event_driven",
    "risk_factors",
    "decision_framework",
)


def _load_methodology() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in _METHODOLOGY_ORDER:
        path = _METHODOLOGY_DIR / f"{name}.md"
        out[name] = path.read_text(encoding="utf-8")
    return out


_METHODOLOGY: dict[str, str] = _load_methodology()


# ---------------------------------------------------------------------------
# References — JSON + 2 YAML loaded as parsed Python objects.
# ---------------------------------------------------------------------------

_REFERENCES_DIR = Path(__file__).parent / "references"


def _load_references() -> dict[str, Any]:
    industry_benchmarks: dict[str, Any] = json.loads(
        (_REFERENCES_DIR / "industry_benchmarks.json").read_text(encoding="utf-8")
    )
    recommendation_rules: dict[str, Any] = yaml.safe_load(
        (_REFERENCES_DIR / "recommendation_rules.yaml").read_text(encoding="utf-8")
    )
    position_size_rules: dict[str, Any] = yaml.safe_load(
        (_REFERENCES_DIR / "position_size_rules.yaml").read_text(encoding="utf-8")
    )
    return {
        "industry_benchmarks": industry_benchmarks,
        "recommendation_rules": recommendation_rules,
        "position_size_rules": position_size_rules,
    }


_REFERENCES: dict[str, Any] = _load_references()


# ---------------------------------------------------------------------------
# SkillBundle dataclass + load_skill() factory.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillBundle:
    """Bundle of methodology + references + scripts for financial_research skill.

    Attributes:
        methodology: ``{name: markdown_text}`` for 11 methodology dimensions.
        references: ``{name: parsed_obj}`` for 3 reference files
            (``industry_benchmarks`` dict, ``recommendation_rules`` dict,
            ``position_size_rules`` dict).
        scripts: The ``app.skills.financial_research.scripts`` ModuleType
            (``classify_recommendation`` / ``compute_position_size_pct`` /
            ``lookup_industry_benchmark`` exposed as attributes).
    """

    methodology: dict[str, str]
    references: dict[str, Any]
    scripts: ModuleType

    def composed_sop(self) -> str:
        """Return concatenated 11-methodology SOP in fixed order.

        Useful for injecting into Analyst / Writer prompts as a single
        ``<methodology>...</methodology>`` block.
        """
        return "\n\n".join(self.methodology[name] for name in _METHODOLOGY_ORDER)


def load_skill() -> SkillBundle:
    """Load the financial_research skill bundle.

    Module-level objects are pre-loaded at import time; this factory is a
    thin wrapper that constructs a SkillBundle pointing to the same dicts /
    namespace each call (idempotent).
    """
    return SkillBundle(
        methodology=_METHODOLOGY,
        references=_REFERENCES,
        scripts=_scripts,
    )


__all__ = ["SkillBundle", "load_skill"]
