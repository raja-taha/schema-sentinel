"""Initialize schema, demo application tables, and table_stats cache."""

from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.analysis import TableStat
from app.services.db_stats import fetch_live_table_stats
from app.services.scenarios import default_table_stats

logger = get_logger("seed")

# Demo "application" tables so TARGET_DATABASE_URL pointed at this DB has real stats.
# One statement each — asyncpg rejects multi-command prepared statements.
_DEMO_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
      id BIGSERIAL PRIMARY KEY,
      name TEXT NOT NULL,
      email TEXT,
      full_name TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS orders (
      id BIGSERIAL PRIMARY KEY,
      user_id BIGINT,
      status TEXT,
      amount NUMERIC(12,2),
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS payments (
      id BIGSERIAL PRIMARY KEY,
      order_id BIGINT,
      amount NUMERIC(12,2),
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
      id BIGSERIAL PRIMARY KEY,
      sku TEXT,
      name TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
      id BIGSERIAL PRIMARY KEY,
      name TEXT,
      note TEXT
    )
    """,
]


async def _ensure_table_stats_bigint(conn) -> None:
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'table_stats' AND column_name = 'size_bytes'
                  AND data_type = 'integer'
              ) THEN
                ALTER TABLE table_stats
                  ALTER COLUMN size_bytes TYPE BIGINT,
                  ALTER COLUMN row_estimate TYPE BIGINT;
              END IF;
            END $$;
            """
        )
    )


async def seed_demo_app_tables() -> None:
    """Create sample app tables and bulk-load enough rows for meaningful pg stats."""
    async with engine.begin() as conn:
        for stmt in _DEMO_DDL_STATEMENTS:
            await conn.execute(text(stmt))

        # Idempotent fills — only insert when empty
        counts = {}
        for table in ("users", "orders", "payments", "products", "accounts"):
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            counts[table] = int(result.scalar() or 0)

        # Target volumes for meaningful live lock-risk scores (top-up if undersized)
        targets = {
            "users": 50_000,
            "orders": 120_000,
            "payments": 200_000,
            "products": 25_000,
            "accounts": 15_000,
        }
        if counts["users"] < targets["users"]:
            need = targets["users"] - counts["users"]
            await conn.execute(
                text(
                    """
                    INSERT INTO users (name, email)
                    SELECT 'user_' || g, 'user_' || g || '@example.com'
                    FROM generate_series(1, :need) AS g
                    """
                ),
                {"need": need},
            )
        if counts["orders"] < targets["orders"]:
            need = targets["orders"] - counts["orders"]
            await conn.execute(
                text(
                    """
                    INSERT INTO orders (user_id, status, amount)
                    SELECT (g % 50000) + 1,
                           CASE WHEN g % 3 = 0 THEN 'pending' ELSE 'paid' END,
                           (g % 100)::numeric
                    FROM generate_series(1, :need) AS g
                    """
                ),
                {"need": need},
            )
        if counts["payments"] < targets["payments"]:
            need = targets["payments"] - counts["payments"]
            await conn.execute(
                text(
                    """
                    INSERT INTO payments (order_id, amount, created_at)
                    SELECT (g % 120000) + 1,
                           (g % 50)::numeric,
                           NOW() - ((g % 30) || ' days')::interval
                    FROM generate_series(1, :need) AS g
                    """
                ),
                {"need": need},
            )
        if counts["products"] < targets["products"]:
            need = targets["products"] - counts["products"]
            await conn.execute(
                text(
                    """
                    INSERT INTO products (sku, name)
                    SELECT 'SKU-' || g, 'Product ' || g
                    FROM generate_series(1, :need) AS g
                    """
                ),
                {"need": need},
            )
        if counts["accounts"] < targets["accounts"]:
            need = targets["accounts"] - counts["accounts"]
            await conn.execute(
                text(
                    """
                    INSERT INTO accounts (name)
                    SELECT 'account_' || g FROM generate_series(1, :need) AS g
                    """
                ),
                {"need": need},
            )
        # ANALYZE one table at a time (same asyncpg multi-command restriction)
        for table in ("users", "orders", "payments", "products", "accounts"):
            await conn.execute(text(f"ANALYZE {table}"))
    logger.info("seeded_demo_app_tables")


async def seed_table_stats(force_refresh: bool = False) -> None:
    """Cache live (or synthetic) stats into table_stats for the console/API."""
    payload = fetch_live_table_stats()
    details = payload.get("details") or []
    # Prefer live details for demo tables; fall back to synthetic defaults
    if payload.get("source") != "live" or not details:
        details = [
            {
                "schema_name": "public",
                "table_name": t,
                "row_estimate": r,
                "size_bytes": r * 256,
                "index_count": 1,
            }
            for t, r in default_table_stats().items()
        ]

    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(TableStat).limit(1))
        has_rows = existing.scalar_one_or_none() is not None
        if has_rows and not force_refresh:
            return
        if has_rows and force_refresh:
            await session.execute(text("DELETE FROM table_stats"))

        for d in details:
            session.add(
                TableStat(
                    schema_name=d.get("schema_name") or "public",
                    table_name=d["table_name"],
                    row_estimate=int(d.get("row_estimate") or 0),
                    size_bytes=int(d.get("size_bytes") or 0),
                    has_indexes=1 if int(d.get("index_count") or 0) > 0 else 0,
                )
            )
        await session.commit()
        logger.info(
            "seeded_table_stats",
            source=payload.get("source"),
            tables=len(details),
            error=payload.get("error"),
        )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_table_stats_bigint(conn)
    await seed_demo_app_tables()
    # Refresh cache from live target when configured
    await seed_table_stats(force_refresh=True)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.debug)
    await init_db()
    stats = fetch_live_table_stats()
    print(
        f"SchemaSentinel DB ready. stats_source={stats['source']} "
        f"tables={len(stats.get('details') or [])} host={stats.get('url_host')}"
    )


if __name__ == "__main__":
    asyncio.run(main())
