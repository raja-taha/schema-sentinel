"""Background worker — drains Redis queue and re-runs analyses."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

# Allow importing the API package:
# - Docker: API code is at /app (same image), worker script at /worker/main.py
# - Local:  .../schema-sentinel/services/worker/main.py → ../../apps/api
_HERE = Path(__file__).resolve()
_API_CANDIDATES = [
    Path("/app"),
    Path.cwd(),
]
try:
    _API_CANDIDATES.append(_HERE.parents[2] / "apps" / "api")
except IndexError:
    pass
try:
    _API_CANDIDATES.append(_HERE.parents[1].parent / "apps" / "api")
except IndexError:
    pass

for _root in _API_CANDIDATES:
    if (_root / "app").is_dir() and str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
        break

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.seed import init_db
from app.db.session import AsyncSessionLocal
from app.services import analysis_service
from app.services.redis_state import get_redis

logger = get_logger("worker")


async def process_one(analysis_id: str) -> None:
    async with AsyncSessionLocal() as session:
        await analysis_service.run_analysis(session, UUID(analysis_id))
        logger.info("worker_processed", analysis_id=analysis_id)


async def loop() -> None:
    settings = get_settings()
    configure_logging(settings.debug)
    await init_db()
    client = await get_redis()
    logger.info("worker_started", redis=settings.redis_url)

    while True:
        try:
            item = await client.brpop("schemasentinel:queue", timeout=5)
            if not item:
                await asyncio.sleep(1)
                continue
            _, analysis_id = item
            await process_one(analysis_id)
        except Exception as exc:
            logger.warning("worker_loop_error", error=str(exc))
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(loop())
