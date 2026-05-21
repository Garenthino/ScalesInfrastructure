"""Redis pub/sub notification helpers for queue state changes."""
from __future__ import annotations

import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    Redis = None


async def get_redis_client() -> Redis | None:
    """Return an async Redis client if configured, else None."""
    if Redis is None or not settings.REDIS_URL:
        return None
    try:
        return Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        logger.warning("Failed to create Redis client", exc_info=True)
        return None


async def publish_queue_event(venue_id: str, event_type: str, **kwargs) -> None:
    """Publish a queue state-change event to Redis channel ``queue:{venue_id}``.

    Supported event_type values:
      - request_approved  → kwargs: song_id, position
      - singer_called     → kwargs: song_id
      - performance_complete → kwargs: (none)
    """
    redis = await get_redis_client()
    if redis is None:
        logger.debug("Redis unavailable; dropping event %s for venue %s", event_type, venue_id)
        return

    payload = {"type": event_type}
    payload.update(kwargs)
    channel = f"queue:{venue_id}"
    try:
        await redis.publish(channel, json.dumps(payload))
    except Exception:
        logger.warning("Failed to publish event to %s", channel, exc_info=True)
    finally:
        try:
            await redis.close()
        except Exception:
            pass
