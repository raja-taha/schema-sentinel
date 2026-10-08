"""Live PostgreSQL table-size metadata via TARGET_DATABASE_URL."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.scenarios import default_table_stats

logger = get_logger("db_stats")

_STATS_SQL = """
SELECT
  n.nspname AS schema_name,
  c.relname AS table_name,
  GREATEST(c.reltuples, 0)::bigint AS row_estimate,
  pg_total_relation_size(c.oid)::bigint AS size_bytes,
  (
    SELECT COUNT(*)::int
    FROM pg_index i
    WHERE i.indrelid = c.oid
  ) AS index_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY pg_total_relation_size(c.oid) DESC;
"""


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists() or Path("/app/app").is_dir()


def rewrite_target_url_for_runtime(url: str) -> str:
    """
    Host .env often uses localhost:5434; inside Docker that must become db:5432.
    """
    if not url:
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if _running_in_docker() and host in {"localhost", "127.0.0.1", "host.docker.internal"}:
        userinfo = ""
        if parsed.username:
            userinfo = parsed.username
            if parsed.password:
                userinfo += f":{parsed.password}"
            userinfo += "@"
        return urlunparse(
            (
                parsed.scheme,
                f"{userinfo}db:5432",
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )
    return url


def fetch_live_table_stats(database_url: str | None = None) -> dict[str, Any]:
    """
    Query pg_class for row estimates + total relation size.

    Returns:
      {
        "source": "live" | "synthetic",
        "url_host": "...",
        "rows": {table_name_lower: row_estimate},
        "details": [{schema, table, row_estimate, size_bytes, index_count}, ...],
        "error": optional str
      }
    """
    settings = get_settings()
    raw_url = database_url if database_url is not None else settings.target_database_url
    if not raw_url.strip():
        synthetic = default_table_stats()
        return {
            "source": "synthetic",
            "url_host": None,
            "rows": synthetic,
            "details": [
                {
                    "schema_name": "public",
                    "table_name": t,
                    "row_estimate": r,
                    "size_bytes": r * 256,
                    "index_count": 1,
                }
                for t, r in synthetic.items()
            ],
            "error": None,
        }

    url = rewrite_target_url_for_runtime(raw_url.strip())
    parsed = urlparse(url)
    host_label = f"{parsed.hostname}:{parsed.port or 5432}"

    try:
        conn = psycopg2.connect(url, connect_timeout=8)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(_STATS_SQL)
                rows = list(cur.fetchall())
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("live_stats_failed", error=str(exc), host=host_label)
        synthetic = default_table_stats()
        return {
            "source": "synthetic",
            "url_host": host_label,
            "rows": synthetic,
            "details": [
                {
                    "schema_name": "public",
                    "table_name": t,
                    "row_estimate": r,
                    "size_bytes": r * 256,
                    "index_count": 1,
                }
                for t, r in synthetic.items()
            ],
            "error": str(exc),
        }

    details = [
        {
            "schema_name": r["schema_name"],
            "table_name": r["table_name"],
            "row_estimate": int(r["row_estimate"] or 0),
            "size_bytes": int(r["size_bytes"] or 0),
            "index_count": int(r["index_count"] or 0),
        }
        for r in rows
    ]
    # Prefer public schema on name collisions; first occurrence wins after sort by size
    row_map: dict[str, int] = {}
    for d in sorted(details, key=lambda x: (0 if x["schema_name"] == "public" else 1, -x["size_bytes"])):
        key = d["table_name"].lower()
        if key not in row_map:
            row_map[key] = d["row_estimate"]

    # Do NOT overwrite live counts with synthetic millions.
    # Only use synthetic fallbacks when a referenced table is missing entirely.
    for table, estimate in default_table_stats().items():
        row_map.setdefault(table, estimate)

    logger.info("live_stats_ok", host=host_label, tables=len(details))
    return {
        "source": "live",
        "url_host": host_label,
        "rows": row_map,
        "details": details,
        "error": None,
    }


def resolve_table_stats() -> dict[str, Any]:
    """Convenience wrapper used by the analysis pipeline."""
    return fetch_live_table_stats()
