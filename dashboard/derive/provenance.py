"""provenance quote → source fuzzy match。spec § 7.3。

LLM prefill 输出含 quote + source,校验 normalize(quote) 是否在 normalize(source 文件内容)中。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MARKDOWN_EMPHASIS_RE = re.compile(r"[*_`]+")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ProvenanceCheckResult:
    ok: bool
    reason: str = ""


def normalize_text(text: str) -> str:
    """strip markdown emphasis (* _ `) + collapse whitespace。"""
    text = MARKDOWN_EMPHASIS_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def verify_quote_in_source(
    quote: str,
    source: Path | str,
    *,
    base_dir: Path,
) -> ProvenanceCheckResult:
    """检查 normalize(quote) 是否在 normalize(source 文件内容)中。

    source 可附 #anchor(spec § 7.3),verify 时剥离。
    """
    src_str = str(source)
    if "#" in src_str:
        src_str = src_str.split("#", 1)[0]
    src_path = (base_dir / src_str).resolve()
    if not src_path.exists():
        return ProvenanceCheckResult(ok=False, reason=f"source does not exist: {src_str}")
    try:
        content = src_path.read_text(encoding="utf-8")
    except OSError as e:
        return ProvenanceCheckResult(ok=False, reason=f"source read error: {e}")
    norm_quote = normalize_text(quote)
    norm_content = normalize_text(content)
    if norm_quote in norm_content:
        return ProvenanceCheckResult(ok=True)
    return ProvenanceCheckResult(ok=False, reason="quote not found in source (normalized)")
