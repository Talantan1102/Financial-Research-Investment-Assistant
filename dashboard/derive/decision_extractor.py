"""Decision extractor:从 spec sections + memory frontmatter 派生 ~47 项 Decision。

spec § 3:layer 用 dimensions.yaml.keywords 反向归类
spec § 9:memory_path resolve(env override + auto-detect + None fallback)
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .types import Decision, DimensionConfig, compute_decision_id

PROJECT_ROOT = Path(__file__).parent.parent.parent  # dashboard 顶级到 repo 根

# spec filename:2026-05-05-v0.8.5-...md → v0.8.5
# spec filename:2026-05-07-harness-board-m2-design.md → m2
# 允许 date 与 version token 之间有任意前缀(如 harness-board-),非贪婪匹配第一个 version token。
SPEC_VERSION_RE = re.compile(r"\d{4}-\d{2}-\d{2}-.*?(v\d+\.\d+(?:\.\d+)?|M\d+|m\d+)")
# memory filename:project_v0.8.5_architecture_landed.md → v0.8.5
MEM_VERSION_RE = re.compile(r"^project_v(\d+\.\d+(?:\.\d+)?)_")
# spec section header:## § 2 决策一:Constrained Router → "Constrained Router"
SPEC_DECISION_RE = re.compile(r"^## § \d+ 决策\S*[:：](.*)$", re.MULTILINE)
# memory frontmatter delimiters
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def resolve_memory_path() -> Path | None:
    """三层 fallback:env override → auto-detect → None。spec § 9.1。"""
    env = os.environ.get("HARNESS_MEMORY_PATH")
    if env:
        p = Path(env)
        return p if p.exists() else None
    # Claude Code project dir convention:absolute path → 替换 "/" 和 "." 都为 "-"
    # e.g. /Users/x/.foo/bar → -Users-x--foo-bar
    slug = str(PROJECT_ROOT).replace("/", "-").replace(".", "-")
    auto = Path.home() / ".claude" / "projects" / slug / "memory"
    return auto if auto.exists() else None


def classify_layer(text: str, main_dims: list[DimensionConfig]) -> str:
    """text 里 keyword scan 8 dim,返回最高分 dim id;无匹配返 'META'。

    score = sum(len(kw)) 命中累加 — 长 keyword 更具体优先(spec § 3.1):
    e.g. "TierRouter" hit "TierRouter"(10) 优先于 "tier"(4)。
    """
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for d in main_dims:
        for kw in d.keywords:
            if kw.lower() in text_lower:
                scores[d.id] = scores.get(d.id, 0) + len(kw)
    if not scores:
        return "META"
    return max(scores.items(), key=lambda kv: kv[1])[0]


def _spec_version(filename: str) -> str:
    m = SPEC_VERSION_RE.search(filename)
    return m.group(1) if m else "unknown"


def _mem_version(filename: str) -> str:
    m = MEM_VERSION_RE.match(filename)
    if m:
        return f"v{m.group(1)}"
    if filename.startswith("feedback_"):
        return "unversioned"
    return "unknown"


def extract_from_specs(specs_dir: Path) -> list[Decision]:
    """扫 specs_dir 下 *.md,抓每个 ## § X 决策\\S*[:：] 段为 Decision。"""
    out: list[Decision] = []
    if not specs_dir.exists():
        return out
    # 加载 dimensions for layer classify
    config_dir = PROJECT_ROOT / "dashboard" / "config"
    from .path_router import load_dimensions

    main_dims, _ = load_dimensions(config_dir / "dimensions.yaml")

    for spec_file in sorted(specs_dir.glob("*.md")):
        version = _spec_version(spec_file.name)
        date = datetime.fromtimestamp(spec_file.stat().st_mtime).strftime("%Y-%m-%d")
        text = spec_file.read_text(encoding="utf-8")
        # 拆分 sections,每个 ## 开头之间是一段
        sections = re.split(r"^## ", text, flags=re.MULTILINE)
        for sec in sections:
            m = SPEC_DECISION_RE.match("## " + sec)
            if not m:
                continue
            title = m.group(1).strip()
            # why = 第一个非空段(在 ## 行之后)
            lines = sec.splitlines()[1:]
            why = ""
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    why = stripped[:200]
                    break
            layer = classify_layer(title + " " + why, main_dims)
            out.append(
                Decision(
                    id=compute_decision_id(version, layer, title),
                    date=date,
                    version=version,
                    layer=layer,
                    title=title,
                    why=why,
                    refs=(spec_file.name,),
                )
            )
    return out


def extract_from_memory(memory_dir: Path, main_dims: list[DimensionConfig]) -> list[Decision]:
    """扫 memory_dir 下 *.md frontmatter,filter type ∈ {feedback, project}。"""
    out: list[Decision] = []
    if not memory_dir.exists():
        return out
    for mem_file in sorted(memory_dir.glob("*.md")):
        if mem_file.name == "MEMORY.md":
            continue
        text = mem_file.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        if not m:
            continue
        try:
            fm_raw = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            continue
        # safe_load 可返回 str / list / dict / None;非 dict frontmatter 跳过(防 AttributeError)
        if not isinstance(fm_raw, dict):
            continue
        fm: dict[str, Any] = fm_raw
        if fm.get("type") not in ("feedback", "project"):
            continue
        title = str(fm.get("name", mem_file.stem))
        why = str(fm.get("description", ""))[:200]
        version = _mem_version(mem_file.name)
        layer = classify_layer(title + " " + why, main_dims)
        date = datetime.fromtimestamp(mem_file.stat().st_mtime).strftime("%Y-%m-%d")
        out.append(
            Decision(
                id=compute_decision_id(version, layer, title),
                date=date,
                version=version,
                layer=layer,
                title=title,
                why=why,
                refs=(mem_file.name,),
            )
        )
    return out


def extract_all() -> list[Decision]:
    """spec + memory 合并,去重(同 id 取 spec)+ 时间倒序。"""
    specs_dir = PROJECT_ROOT / "docs" / "superpowers" / "specs"
    config_dir = PROJECT_ROOT / "dashboard" / "config"
    from .path_router import load_dimensions

    main_dims, _ = load_dimensions(config_dir / "dimensions.yaml")

    spec_decisions = extract_from_specs(specs_dir)
    seen_ids = {d.id for d in spec_decisions}

    memory_dir = resolve_memory_path()
    mem_decisions = extract_from_memory(memory_dir, main_dims) if memory_dir else []
    # 去重:spec 优先于 memory
    mem_decisions = [d for d in mem_decisions if d.id not in seen_ids]

    all_decisions = spec_decisions + mem_decisions
    all_decisions.sort(key=lambda d: d.date, reverse=True)
    return all_decisions
