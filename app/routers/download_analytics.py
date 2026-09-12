"""Public download analytics — PII-free counters and logging.

This module is intentionally separate from the authenticated analytics router
so that anonymous download beacons from the marketing page can be recorded
without requiring auth.  Only the fields explicitly sent by the frontend are
stored; no IP addresses, user agents, or cookies are logged.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(tags=["Download Analytics"])

logger = logging.getLogger(__name__)

# Default analytics log path inside the API container. The /app directory is
# owned by the non-root scales user in the container, so /app/data is writable.
# In production Redis is the primary counter store; the log file is a fallback
# if Redis is unavailable.
ANALYTICS_LOG_DIR = Path(os.environ.get("DOWNLOAD_ANALYTICS_LOG_DIR", "/app/data"))
ANALYTICS_LOG_FILE = ANALYTICS_LOG_DIR / "download-analytics.log"

# Redis key prefix for daily platform counters.
REDIS_KEY_PREFIX = "scales:downloads"


class DownloadEvent(BaseModel):
    """PII-free download event payload from the marketing page."""

    event: str = Field(default="download", pattern=r"^download$")
    platform: str = Field(..., min_length=1, max_length=32)
    channel: str = Field(default="stable", min_length=1, max_length=32)
    version: str = Field(default="unknown", min_length=1, max_length=64)
    href: str = Field(default="", max_length=2048)
    t: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DownloadAnalyticsSummary(BaseModel):
    """Public summary of download counts."""

    total_today: int
    by_platform: dict[str, int]
    last_event_at: str | None


def _ensure_log_dir() -> None:
    ANALYTICS_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _append_log(event: DownloadEvent) -> None:
    """Append the event as a single JSON line to the analytics log."""
    try:
        _ensure_log_dir()
        line = event.model_dump_json() + "\n"
        with ANALYTICS_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:
        logger.warning("Failed to write download analytics log: %s", exc)


def _redis_client() -> Any | None:
    """Return an async Redis client if REDIS_URL is configured, else None."""
    if not settings.REDIS_URL:
        return None
    try:
        import redis.asyncio as aioredis
        return aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("Could not create Redis client for download analytics: %s", exc)
        return None


async def _incr_redis_counters(platform: str, channel: str) -> None:
    """Increment daily counters in Redis when available."""
    r = _redis_client()
    if r is None:
        return
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pipe = r.pipeline()
        pipe.hincrby(f"{REDIS_KEY_PREFIX}:{today}", platform, 1)
        pipe.hincrby(f"{REDIS_KEY_PREFIX}:{today}", f"{platform}:{channel}", 1)
        pipe.hincrby(f"{REDIS_KEY_PREFIX}:{today}", "_total", 1)
        await pipe.execute()
        await r.close()
    except Exception as exc:
        logger.warning("Redis download counter increment failed: %s", exc)


async def _load_summary() -> DownloadAnalyticsSummary:
    """Read today's totals from Redis or the log file fallback."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by_platform: dict[str, int] = {}
    total_today = 0
    last_event_at: str | None = None

    r = _redis_client()
    if r is not None:
        try:
            data = await r.hgetall(f"{REDIS_KEY_PREFIX}:{today}")
            await r.close()
            for key, value in data.items():
                if key.startswith("_"):
                    if key == "_total":
                        total_today = int(value)
                    continue
                if ":" in key:
                    continue
                by_platform[key] = int(value)
            if data:
                return DownloadAnalyticsSummary(
                    total_today=total_today,
                    by_platform=by_platform,
                    last_event_at=None,
                )
        except Exception as exc:
            logger.warning("Could not read Redis download counters: %s", exc)

    # Fallback: scan today's lines from the log file.
    try:
        if ANALYTICS_LOG_FILE.exists():
            with ANALYTICS_LOG_FILE.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        ts = record.get("t", "")
                        if ts.startswith(today):
                            platform = record.get("platform", "unknown")
                            by_platform[platform] = by_platform.get(platform, 0) + 1
                            total_today += 1
                            last_event_at = ts
                    except json.JSONDecodeError:
                        continue
    except Exception as exc:
        logger.warning("Could not read download analytics log: %s", exc)

    return DownloadAnalyticsSummary(
        total_today=total_today,
        by_platform=by_platform,
        last_event_at=last_event_at,
    )


@router.post("/analytics/download")
async def record_download(
    request: Request,
    event: DownloadEvent,
):
    """Record a PII-free download event from the public /download page.

    This endpoint is intentionally unauthenticated. It accepts only the fields
    the frontend sends (platform, channel, version, href, timestamp) and never
    stores client IP, user agent, or cookies.
    """
    # Validate timestamp format loosely.
    try:
        datetime.fromisoformat(event.t.replace("Z", "+00:00"))
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "Invalid timestamp format"},
        )

    _append_log(event)
    await _incr_redis_counters(event.platform, event.channel)

    return {"ok": True}


@router.get("/analytics/download")
async def get_download_summary():
    """Return a public summary of today's download counts."""
    summary = await _load_summary()
    return summary.model_dump()
