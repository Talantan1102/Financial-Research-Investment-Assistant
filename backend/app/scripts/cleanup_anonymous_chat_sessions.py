"""一次性维护脚本:删 user_id IS NULL 的 chat_sessions 及级联子表。

C.6 chat 子系统接真 auth(强制登录 + 按 user.id 隔离)上线前,清掉 pre-auth
留下的匿名会话池(这些会话 user_id 为 NULL,对任何真实用户都不可见 = 孤儿)。

事务内执行;删前打印计数。级联顺序:episodes → messages → tasks → sessions。
运行:WSL fria-venv + source .env(真 PG),`python -m app.scripts.cleanup_anonymous_chat_sessions`
"""

from __future__ import annotations

import os

import psycopg2


def main() -> None:
    conn = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )
    cur = conn.cursor()
    cur.execute("SELECT id FROM chat_sessions WHERE user_id IS NULL")
    sids = [str(r[0]) for r in cur.fetchall()]
    print(f"NULL-user sessions to delete: {len(sids)}")
    if not sids:
        print("nothing to clean.")
        conn.close()
        return

    cur.execute(
        "SELECT episode_id FROM chat_memory_episodes WHERE session_id = ANY(%s::uuid[])",
        (sids,),
    )
    eids = [str(r[0]) for r in cur.fetchall()]
    if eids:
        cur.execute(
            "DELETE FROM chat_memory_edges WHERE source_episode_id = ANY(%s::uuid[])",
            (eids,),
        )
        print("  edges deleted:", cur.rowcount)
    cur.execute("DELETE FROM chat_memory_episodes WHERE session_id = ANY(%s::uuid[])", (sids,))
    print("  episodes deleted:", cur.rowcount)
    cur.execute("DELETE FROM chat_messages WHERE session_id = ANY(%s::uuid[])", (sids,))
    print("  messages deleted:", cur.rowcount)
    cur.execute("DELETE FROM chat_tasks WHERE session_id = ANY(%s::uuid[])", (sids,))
    print("  tasks deleted:", cur.rowcount)
    cur.execute("DELETE FROM chat_sessions WHERE id = ANY(%s::uuid[])", (sids,))
    print("  sessions deleted:", cur.rowcount)

    conn.commit()
    print("committed.")
    conn.close()


if __name__ == "__main__":
    main()
