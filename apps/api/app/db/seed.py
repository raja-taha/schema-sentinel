"""Initialize schema and seed synthetic table stats + optional demo analysis."""

from __future__ import annotations

import asyncio

from sqlalchemy import select, text

from app.core.logging import configure_logging, get_logger
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.analysis import TableStat
from app.services.scenarios import default_table_stats

logger = get_logger("seed")


async def _ensure_table_stats_bigint(conn) -> None:
    """Widen size_bytes/row_estimate if an older INTEGER schema already exists."""
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


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_table_stats_bigint(conn)
    await seed_table_stats()


async def seed_table_stats() -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(TableStat).limit(1))
        if existing.scalar_one_or_none():
            return
        for table, rows in default_table_stats().items():
            session.add(
                TableStat(
                    schema_name="public",
                    table_name=table,
                    row_estimate=rows,
                    size_bytes=rows * 256,
                    has_indexes=1,
                )
            )
        await session.commit()
        logger.info("seeded_table_stats", tables=len(default_table_stats()))


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.debug)
    await init_db()
    print("SchemaSentinel DB ready.")


if __name__ == "__main__":
    asyncio.run(main())
