"""trace-view — read spans (PG) and pretty-print a TraceTree.

Usage:
    uv run python scripts/trace_view.py --request-id req-foo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Bootstrap: add backend/ to sys.path so `app.*` is importable when the script
# is run directly (e.g. `uv run python scripts/trace_view.py`). pytest already
# inserts backend/ via rootdir detection, so this is a no-op in test context.
_BACKEND = Path(__file__).parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.database import SessionLocal  # noqa: E402
from app.services.trace_models import Span, TraceTree  # noqa: E402
from app.services.trace_service import TraceService  # noqa: E402


def format_trace_tree(tree: TraceTree) -> str:
    """ASCII-art tree of the trace. Each span shows: name, latency, cost."""
    lines: list[str] = []
    _format_span(tree.root_span, depth=0, prefix="", is_last=True, lines=lines)
    for i, child in enumerate(tree.root_span_children):
        is_last = i == len(tree.root_span_children) - 1
        _format_span(child, depth=1, prefix="", is_last=is_last, lines=lines)
    lines.append("")
    lines.append(
        f"  request_id={tree.request_id} total_latency_ms={tree.total_latency_ms} total_cost_cny=¥{tree.total_cost_cny:.4f}"
    )
    return "\n".join(lines)


def _format_span(span: Span, depth: int, prefix: str, is_last: bool, lines: list[str]) -> None:
    marker = "" if depth == 0 else "└─ " if is_last else "├─ "
    indent = "  " * (depth - 1) if depth > 0 else ""
    cost = float(span.metadata.get("cost_cny", 0.0))
    lines.append(
        f"{indent}{marker}{span.name} [{span.latency_ms}ms, ¥{cost:.4f}] (id={span.span_id})"
    )


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--request-id", required=True)
    args = p.parse_args(argv)

    # PR-B: TraceService 迁到 PG(SessionLocal),不再读 sqlite 文件。
    svc = TraceService(session_factory=SessionLocal)
    try:
        tree = svc.get_trace(args.request_id)
    except LookupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(format_trace_tree(tree))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
