"""Nightly cleanup scheduler for compliance/retention tasks.

Usage:
    from app.services.retention import schedule_nightly_retention, run_retention_now

    schedule_nightly_retention(app_lifespan=True)  # background thread
    # or
    await run_retention_now()  # one-shot async

The scheduler runs the purge job at 04:00 UTC daily (configurable via
RETENTION_RUN_HOUR / RETENTION_RUN_MINUTE). It uses the async DB engine.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import engine
from app.core.config import settings
from app.services.venue_purge import purge_expired_soft_deleted_venues

logger = logging.getLogger(__name__)


def _get_session_factory() -> async_sessionmaker:
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def run_retention_now(retention_days: int | None = None) -> list[dict[str, Any]]:
    """Purge soft-deleted venues older than the retention window."""
    factory = _get_session_factory()
    async with factory() as session:
        return await purge_expired_soft_deleted_venues(session, retention_days)


def _seconds_until_next_run(hour: int, minute: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _retention_loop(
    retention_days: int | None = None,
    run_hour: int = 4,
    run_minute: int = 0,
) -> None:
    """Infinite loop: wait until 04:00 UTC, then purge."""
    while True:
        sleep_seconds = _seconds_until_next_run(run_hour, run_minute)
        logger.info("Retention scheduler: next run in %.0f seconds", sleep_seconds)
        await asyncio.sleep(sleep_seconds)
        try:
            results = await run_retention_now(retention_days)
            total = len(results)
            errors = sum(1 for r in results if r.get("action") == "error")
            logger.info(
                "Retention scheduler completed: %s venues processed, %s errors",
                total,
                errors,
            )
        except Exception as exc:
            logger.exception("Retention scheduler run failed: %s", exc)


def schedule_nightly_retention(
    retention_days: int | None = None,
    run_hour: int = 4,
    run_minute: int = 0,
    *,
    daemon: bool = True,
) -> threading.Thread:
    """Start the retention scheduler in a background thread.

    Returns the thread so callers can join it during shutdown if needed.
    """

    def _run_loop() -> None:
        asyncio.run(
            _retention_loop(
                retention_days=retention_days,
                run_hour=run_hour,
                run_minute=run_minute,
            )
        )

    thread = threading.Thread(target=_run_loop, name="retention-scheduler", daemon=daemon)
    thread.start()
    logger.info(
        "Retention scheduler started (daily at %02d:%02d UTC)",
        run_hour,
        run_minute,
    )
    return thread


# Convenience Celery task hook, in case a Celery beat deployment is preferred.
def register_retention_beat():
    """Return a Celery-beat schedule dict for retention.

    Add to a Celery app like:
        app.conf.beat_schedule = {**app.conf.beat_schedule, **register_retention_beat()}
    """
    return {
        "nightly-retention-purge": {
            "task": "retention.nightly_purge",
            "schedule": __import__("celery").schedulers.crontab(hour=4, minute=0),
        }
    }
