from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from app.core.config import get_settings

_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def set_analysis_progress(analysis_id: str, payload: dict[str, Any], ttl: int = 3600) -> None:
    try:
        client = await get_redis()
        await client.setex(f"analysis:{analysis_id}:progress", ttl, json.dumps(payload))
    except Exception:
        pass


async def get_analysis_progress(analysis_id: str) -> dict[str, Any] | None:
    try:
        client = await get_redis()
        raw = await client.get(f"analysis:{analysis_id}:progress")
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def enqueue_analysis(analysis_id: str) -> None:
    try:
        client = await get_redis()
        await client.lpush("schemasentinel:queue", analysis_id)
    except Exception:
        pass
