"""一次性诊断:跑 viewpoint-baijiu 写阶段,dump 该 user 全部 EXPRESSED_VIEW 边
(active + 作废 + 演化),看「转中性」到底有没有被抽出、valid_from/作废链长啥样。

用法:PYTHONPATH=. python -m eval.memory_dialogue._diag_viewpoint_edges
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import text


async def main() -> None:
    from eval.memory_dialogue.live_deps import build_live_runners
    from eval.memory_dialogue.script_schema import load_script

    write_runner, _ = await build_live_runners()
    script = load_script(
        Path(__file__).parent / "scripts" / "viewpoint-baijiu.yaml"
    )
    await write_runner.run(script)

    from app.core.database import SessionLocal

    s = SessionLocal()
    try:
        uid = s.execute(
            text(
                "SELECT id FROM users WHERE username LIKE 'eval-dialogue-%' "
                "ORDER BY created_at DESC LIMIT 1"
            )
        ).scalar()
        rows = s.execute(
            text(
                """
                SELECT n.entity_label AS tgt, e.rel_type, e.valid_from, e.valid_to,
                       e.invalidated_at, e.properties, e.reasoning
                FROM chat_memory_edges e
                JOIN chat_memory_nodes n ON n.node_id = e.target_node_id
                WHERE e.user_id = :u AND e.rel_type = 'EXPRESSED_VIEW'
                ORDER BY e.valid_from
                """
            ),
            {"u": uid},
        ).fetchall()
        print(f"\n=== user {uid} 的 EXPRESSED_VIEW 边({len(rows)} 条)===")
        for r in rows:
            status = (
                "作废" if r.invalidated_at else ("结束" if r.valid_to else "★active")
            )
            props = r.properties or {}
            print(
                f"[{status:>7}] → {r.tgt} | from={str(r.valid_from)[:10]} "
                f"to={str(r.valid_to)[:10] if r.valid_to else '-'} "
                f"| props={props} | reason={(r.reasoning or '')[:60]}"
            )
        # 专门看有没有「中性」
        neutral = [
            r
            for r in rows
            if "中性" in str(r.properties) or "中性" in (r.reasoning or "")
        ]
        print(f"\n含「中性」的边:{len(neutral)} 条", "→ 抽到了" if neutral else "→ 根本没抽出")
    finally:
        s.close()


if __name__ == "__main__":
    asyncio.run(main())
