"""启动期 schema reconciler：为「已存在的表」补上 ORM 模型里有、但 DB 里缺的列。

# 为什么需要
`create_all()` 只 CREATE 缺失的表，**从不 ALTER 已存在的表**。当某个 ORM 模型
新增了列(如 v0.9 给 chat_sessions 加 message_count / last_msg_preview，给
chat_messages 加 message_type / status 等),而该表早已由 docker/init-db/01-init.sql
或更早的 create_all 建好时 —— 新列永远不会落到 DB，于是任何 INSERT/SELECT 碰到该列
都 500(`UndefinedColumn`)。单测因为 fixture 自己 ALTER 补列而绿，真实 serving DB /
新容器却缺列 —— 典型 schema 漂移,只有端到端联调才暴露。

# 做法
对每张「DB 里已存在」的 Base 表,对比模型列与 DB 列,对缺失列用 SQLAlchemy 自己的
`CreateColumn` 渲染出方言正确的列 DDL(含类型 / DEFAULT / NOT NULL 的正确引号),
再 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。逐列容错:某列失败(如 NOT NULL 无
默认值且表里已有行)只记 warning 跳过,不阻断其余列。幂等,可每次启动跑。

# 调用
- app_main lifespan 启动时跑一次(在 create_all 之后)。
- 也可独立 CLI: `uv run python -m app.scripts.reconcile_schema`。
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateColumn

import app.models  # noqa: F401 — 确保所有模型注册到 Base.metadata
from app.core.database import Base

logger = logging.getLogger(__name__)


def reconcile_columns(engine: Engine) -> list[str]:
    """为已存在的表补齐 ORM 缺失列。返回新增的 "table.column" 列表。"""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: list[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # 整表缺失交给 create_all
        db_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in db_cols:
                continue
            try:
                # 用 SQLAlchemy 自身渲染列 DDL(类型/DEFAULT/NOT NULL 引号都正确),
                # FK 是表级约束不会被 CreateColumn 渲染 — 只补裸列,足够消除 UndefinedColumn。
                col_ddl = str(CreateColumn(col).compile(dialect=engine.dialect)).strip()
                ddl = f"ALTER TABLE {table.name} ADD COLUMN IF NOT EXISTS {col_ddl}"
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
            except Exception as e:  # noqa: BLE001 — 单列失败不阻断其余列
                logger.warning(
                    "reconcile_columns: 跳过 %s.%s (%s: %s)",
                    table.name,
                    col.name,
                    type(e).__name__,
                    e,
                )
    if added:
        logger.info("reconcile_columns: 补齐缺失列 %s", added)
    return added


if __name__ == "__main__":
    from app.core.database import engine

    cols = reconcile_columns(engine)
    print(f"reconciled {len(cols)} missing columns: {cols}")
