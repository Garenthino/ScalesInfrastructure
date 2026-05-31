"""Queue management business logic: rotation fairness, VIP priorities, reordering."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import QueueRequest, RotationSession
from app.core.config import settings

logger = logging.getLogger(__name__)

def _NOW():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ROTATION_MODES = {"fifo", "round_robin", "vip_priority"}
ACTIVE_STATUSES = {"pending", "approved", "now_playing"}


# ---------------------------------------------------------------------------
# In-memory event bus (fallback when Redis is absent)
# ---------------------------------------------------------------------------

class InMemoryEventBus:
    """Asyncio.Queue-based fan-out bus for a single venue."""

    def __init__(self):
        self._queues: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._queues.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._queues.discard(q)

    async def publish(self, payload: str) -> None:
        dead: list[asyncio.Queue] = []
        async with self._lock:
            queues = list(self._queues)
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        if dead:
            async with self._lock:
                for q in dead:
                    self._queues.discard(q)


venues_bus: dict[str, InMemoryEventBus] = {}
_venues_bus_lock = asyncio.Lock()


async def get_venue_bus(venue_id: str) -> InMemoryEventBus:
    async with _venues_bus_lock:
        if venue_id not in venues_bus:
            venues_bus[venue_id] = InMemoryEventBus()
        return venues_bus[venue_id]


# ---------------------------------------------------------------------------
# Queue Event Publisher
# ---------------------------------------------------------------------------

class QueueEventPublisher:
    """Publishes queue events to Redis (if configured) or in-memory bus."""

    _redis = None

    @classmethod
    async def publish(cls, venue_id: str, event_type: str, data: dict) -> None:
        payload = json.dumps({"venue_id": venue_id, "event_type": event_type, "data": data})
        if settings.REDIS_URL:
            try:
                import redis.asyncio as aioredis
                if cls._redis is None:
                    cls._redis = await aioredis.from_url(settings.REDIS_URL)
                await cls._redis.publish(f"queue:{venue_id}", payload)
            except Exception:
                # Best-effort: don't let Redis failures break queue ops
                logger.debug("redis_publish_failed", exc_info=True)

        # Always broadcast via in-memory bus so WS clients get events regardless of Redis
        bus = await get_venue_bus(venue_id)
        await bus.publish(payload)


# ---------------------------------------------------------------------------
# Queue Service
# ---------------------------------------------------------------------------

class QueueService:
    """High-level queue operations with rotation modes and priority support."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    async def get_active_queue(
        self,
        venue_id: str,
        mode: str = "round_robin",
        include_details: bool = True,
    ) -> list[QueueRequest]:
        """Return active queue items ordered by the selected rotation mode."""
        stmt = (
            select(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                QueueRequest.deleted_at.is_(None),
            )
        )
        if include_details:
            stmt = stmt.options(selectinload(QueueRequest.singer), selectinload(QueueRequest.song))

        result = await self.db.execute(stmt)
        items = result.scalars().all()
        return self._order_by_mode(list(items), mode)

    @staticmethod
    def _order_by_mode(items: list[QueueRequest], mode: str) -> list[QueueRequest]:
        if mode == "fifo":
            return sorted(items, key=lambda i: i.requested_at or "")

        if mode == "vip_priority":
            # Sort by VIP weight (higher first), then FIFO within equal weight
            return sorted(
                items,
                key=lambda i: (
                    -_singer_priority_weight(i),
                    i.requested_at or "",
                ),
            )

        # Default: round_robin — group by singer, each singer gets one turn before repeating
        singer_groups: dict[str, list[QueueRequest]] = {}
        for item in items:
            sid = getattr(item, "singer_id", "")
            singer_groups.setdefault(sid, []).append(item)

        # Order groups by their first request time
        for sid in singer_groups:
            singer_groups[sid].sort(key=lambda i: i.requested_at or "")

        ordered_groups = sorted(
            singer_groups.items(),
            key=lambda kv: kv[1][0].requested_at or "",
        )

        # Interleave: take first from each group, then seconds, etc.
        round_robin: list[QueueRequest] = []
        group_iters = [iter(g) for _, g in ordered_groups]
        while group_iters:
            next_iters = []
            for it in group_iters:
                try:
                    round_robin.append(next(it))
                except StopIteration:
                    pass
                else:
                    next_iters.append(it)
            group_iters = next_iters
        return round_robin

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------

    async def approve(self, venue_id: str, request_id: str) -> QueueRequest:
        item = await self._get_item(venue_id, request_id)
        if item.status in {"completed", "skipped", "rejected"}:
            raise ValueError(f"Cannot approve a request with status '{item.status}'")
        item.status = "approved"
        item.updated_at = _NOW()
        await self.db.commit()
        await self.db.refresh(item)
        await QueueEventPublisher.publish(
            venue_id, "request_approved", {"request_id": request_id, "status": "approved"}
        )
        return item

    async def reject(self, venue_id: str, request_id: str, reason: str | None = None) -> QueueRequest:
        item = await self._get_item(venue_id, request_id)
        if item.status in {"completed", "skipped", "rejected"}:
            raise ValueError(f"Cannot reject a request with status '{item.status}'")
        item.status = "rejected"
        item.reject_reason = reason
        item.updated_at = _NOW()
        await self.db.commit()
        await self.db.refresh(item)
        await QueueEventPublisher.publish(
            venue_id, "request_rejected", {"request_id": request_id, "reason": reason}
        )
        return item

    async def complete(self, venue_id: str, request_id: str) -> QueueRequest:
        item = await self._get_item(venue_id, request_id)
        if item.status not in {"approved", "now_playing"}:
            raise ValueError(f"Cannot complete a request with status '{item.status}'")
        item.status = "completed"
        item.played_at = _NOW()
        item.updated_at = _NOW()
        await self.db.commit()
        await self.db.refresh(item)
        # Award performance points
        from app.core.points_service import add_points
        await add_points(
            self.db, venue_id, str(item.singer_id), 25,
            "Performance completed", "perform", request_id,
        )
        await QueueEventPublisher.publish(
            venue_id, "singer_completed", {"request_id": request_id, "status": "completed"}
        )
        # Auto-advance: start next approved item in rotation order
        await self._auto_advance(venue_id)
        return item
    async def start(self, venue_id: str, request_id: str) -> QueueRequest:
        """Mark request as now_playing; enforce only 1 now_playing per venue."""
        existing = await self._get_now_playing(venue_id)
        if existing is not None:
            raise ValueError("Another request is already playing")
        item = await self._get_item(venue_id, request_id)
        if item.status not in {"pending", "approved"}:
            raise ValueError(f"Cannot start a request with status '{item.status}'")
        item.status = "now_playing"
        item.updated_at = _NOW()
        await self.db.commit()
        await self.db.refresh(item)
        await QueueEventPublisher.publish(
            venue_id, "request_started", {"request_id": request_id, "status": "now_playing"}
        )
        return item

    async def skip(self, venue_id: str, request_id: str) -> QueueRequest:
        """Skip a playing or approved request and auto-advance."""
        item = await self._get_item(venue_id, request_id)
        if item.status not in {"approved", "now_playing", "pending"}:
            raise ValueError(f"Cannot skip a request with status '{item.status}'")
        item.status = "skipped"
        item.played_at = _NOW()
        item.updated_at = _NOW()
        await self.db.commit()
        await self.db.refresh(item)
        await QueueEventPublisher.publish(
            venue_id, "request_skipped", {"request_id": request_id, "status": "skipped"}
        )
        # Auto-advance if we skipped the now_playing item
        if item.status == "skipped":
            pass  # already committed; _auto_advance looks at DB state
        await self._auto_advance(venue_id)
        return item

    async def remove(self, venue_id: str, request_id: str) -> None:
        """Alias for cancel (backward compat with queue_admin router)."""
        return await self.cancel(venue_id, request_id)

    async def cancel(self, venue_id: str, request_id: str) -> None:
        """Soft-delete (cancel) a queue request."""
        item = await self._get_item(venue_id, request_id)
        item.deleted_at = _NOW()
        item.updated_at = _NOW()
        await self.db.commit()
        await QueueEventPublisher.publish(
            venue_id, "queue_updated", {"request_id": request_id, "action": "cancelled"}
        )

    async def update(self, venue_id: str, request_id: str, **kwargs) -> QueueRequest:
        """Edit notes/dedication on a queue request."""
        item = await self._get_item(venue_id, request_id)
        if "notes" in kwargs and kwargs["notes"] is not None:
            item.notes = kwargs["notes"]
        if "dedication_to" in kwargs and kwargs["dedication_to"] is not None:
            item.notes = (item.notes or "") + f"\n[Dedication to {kwargs['dedication_to']}]"
        item.updated_at = _NOW()
        await self.db.commit()
        await self.db.refresh(item)
        await QueueEventPublisher.publish(
            venue_id, "queue_updated", {"request_id": request_id, "action": "edited"}
        )
        return item

    # -----------------------------------------------------------------------
    # internals
    # -----------------------------------------------------------------------

    async def _get_now_playing(self, venue_id: str) -> QueueRequest | None:
        stmt = (
            select(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status == "now_playing",
                QueueRequest.deleted_at.is_(None),
            )
            .options(selectinload(QueueRequest.singer), selectinload(QueueRequest.song))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _auto_advance(self, venue_id: str) -> QueueRequest | None:
        """If no now_playing exists, start the next approved item."""
        existing = await self._get_now_playing(venue_id)
        if existing is not None:
            return None
        # Find next approved item in rotation order
        stmt = (
            select(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status.in_(["pending", "approved"]),
                QueueRequest.deleted_at.is_(None),
            )
            .order_by(QueueRequest.rotation_position.asc(), QueueRequest.requested_at.asc())
            .limit(1)
            .options(selectinload(QueueRequest.singer), selectinload(QueueRequest.song))
        )
        result = await self.db.execute(stmt)
        next_item = result.scalar_one_or_none()
        if next_item is not None:
            next_item.status = "now_playing"
            next_item.updated_at = _NOW()
            await self.db.commit()
            await self.db.refresh(next_item)
            await QueueEventPublisher.publish(
                venue_id, "request_started", {"request_id": str(next_item.id), "status": "now_playing", "auto": True}
            )
            return next_item
        return None

    async def reorder(
        self,
        venue_id: str,
        ordered_ids: list[str],
        mode: str = "round_robin",
    ) -> list[QueueRequest]:
        """Validate all IDs belong to venue, then rewrite rotation_position."""
        if not ordered_ids:
            return await self.get_active_queue(venue_id, mode=mode)

        # Ensure every id belongs to this venue and is active
        stmt = (
            select(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                QueueRequest.deleted_at.is_(None),
            )
            .options(selectinload(QueueRequest.singer), selectinload(QueueRequest.song))
        )
        result = await self.db.execute(stmt)
        existing = {r.id: r for r in result.scalars().all()}

        if not set(ordered_ids).issubset(existing.keys()):
            raise ValueError("One or more IDs do not belong to this venue or are not active")

        # Overwrite rotation_position to match the new order
        for idx, rid in enumerate(ordered_ids, start=1):
            existing[rid].rotation_position = idx
            existing[rid].updated_at = _NOW()

        await self.db.commit()
        await QueueEventPublisher.publish(
            venue_id, "queue_updated", {"action": "reordered", "new_order": ordered_ids}
        )

        # Return in the requested order
        return [existing[rid] for rid in ordered_ids]

    # -----------------------------------------------------------------------
    # Rotation session helpers
    # -----------------------------------------------------------------------

    async def get_active_rotation_session(self, venue_id: str) -> RotationSession | None:
        stmt = (
            select(RotationSession)
            .where(
                RotationSession.venue_id == venue_id,
                RotationSession.is_active == 1,
                RotationSession.deleted_at.is_(None),
            )
            .order_by(RotationSession.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # -----------------------------------------------------------------------
    # internals
    # -----------------------------------------------------------------------

    async def _get_item(self, venue_id: str, request_id: str) -> QueueRequest:
        stmt = (
            select(QueueRequest)
            .where(
                QueueRequest.id == request_id,
                QueueRequest.venue_id == venue_id,
                QueueRequest.deleted_at.is_(None),
            )
            .options(selectinload(QueueRequest.singer), selectinload(QueueRequest.song))
        )
        result = await self.db.execute(stmt)
        item = result.scalar_one_or_none()
        if item is None:
            raise ValueError("Queue item not found")
        return item


def _singer_priority_weight(item: QueueRequest) -> int:
    """Higher weight = higher priority. Base is 0; loyalty tiers add."""
    singer = getattr(item, "singer", None)
    if singer is None:
        return 0
    role = getattr(singer, "role", "")
    if role in {"admin", "owner", "kj"}:
        return 100
    tier = getattr(singer, "loyalty_tier_id", None)
    return 50 if tier else 0
