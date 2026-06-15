"""Queue management business logic: rotation fairness, VIP priorities, reordering."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import QueueRequest, RotationSession
from app.core.config import settings

logger = logging.getLogger(__name__)

def _NOW():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


ROTATION_MODES = {"fifo", "round_robin", "vip_priority", "balanced"}
ACTIVE_STATUSES = {"pending", "approved", "now_playing"}


# ---------------------------------------------------------------------------
# In-memory event bus (fallback when Redis + Gateway are absent)
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
    """Publishes queue events to Redis, Gateway, or in-memory bus."""

    _redis = None

    @classmethod
    async def publish(cls, venue_id: str, event_type: str, data: dict) -> None:
        payload = json.dumps({"venue_id": venue_id, "event_type": event_type, "data": data})

        # 1. Gateway broadcast (primary for multi-container)
        if settings.GATEWAY_URL and settings.GATEWAY_INTERNAL_SECRET:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(
                        f"{settings.GATEWAY_URL.rstrip('/')}/broadcast",
                        json={"venue_id": venue_id, "event_type": event_type, "payload": data},
                        headers={"Authorization": f"Bearer {settings.GATEWAY_INTERNAL_SECRET}"},
                    )
            except Exception:
                # Best-effort: gateway failure must not break queue ops
                logger.debug("gateway_publish_failed", exc_info=True)

        # 2. Redis pub/sub (legacy bridge + gateway fallback)
        if settings.REDIS_URL:
            try:
                import redis.asyncio as aioredis
                if cls._redis is None:
                    cls._redis = await aioredis.from_url(settings.REDIS_URL)
                await cls._redis.publish(f"queue:{venue_id}", payload)
            except Exception:
                # Best-effort: don't let Redis failures break queue ops
                logger.debug("redis_publish_failed", exc_info=True)

        # 3. In-memory bus fallback (single-process dev/test)
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

        if mode == "balanced":
            # Sort by min number of completed requests per singer (spread the love),
            # then by FIFO within same count
            def _balanced_key(item: QueueRequest):
                singer = getattr(item, "singer", None)
                perf_count = getattr(singer, "total_points", 0)  # proxy for activity level
                perf_count = perf_count // 25 if perf_count else 0
                return (perf_count, item.requested_at or "")
            return sorted(items, key=_balanced_key)

        # Default: round_robin
        return QueueService._interleave_by_singer(items)

    @staticmethod
    def _interleave_by_singer(items: list[QueueRequest]) -> list[QueueRequest]:
        singer_groups: dict[str, list[QueueRequest]] = {}
        for item in items:
            sid = getattr(item, "singer_id", "")
            singer_groups.setdefault(sid, []).append(item)

        for sid in singer_groups:
            singer_groups[sid].sort(key=lambda i: i.requested_at or "")

        ordered_groups = sorted(
            singer_groups.items(),
            key=lambda kv: kv[1][0].requested_at or "",
        )

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
        # Notification trigger: position may have changed
        await self._maybe_notify_position_change(venue_id)
        await self.broadcast_queue_state(venue_id)
        return item

    async def _maybe_notify_position_change(self, venue_id: str) -> None:
        """Check active queue and notify singers whose position hit 2."""
        try:
            items = await self.get_active_queue(venue_id, mode="round_robin", include_details=False)
            from app.core.notification_service import notify_singer
            for idx, item in enumerate(items, start=1):
                if idx == 2:
                    singer_id = str(item.singer_id)
                    request_id = str(item.id)
                    await notify_singer(
                        self.db, singer_id, venue_id,
                        notification_type="up_soon",
                        title="You're up soon!",
                        body="You are 2nd in the queue. Get ready to sing!",
                        data={"request_id": request_id, "position": 2},
                    )
        except Exception:
            # Best-effort: don't let notification failures break queue ops
            logger.debug("position notification failed", exc_info=True)

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
        await self.broadcast_queue_state(venue_id)
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
        result = await self._auto_advance(venue_id)
        await self.broadcast_queue_state(venue_id)
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
        # Notification: singer is now on stage
        try:
            from app.core.notification_service import notify_singer
            await notify_singer(
                self.db, str(item.singer_id), venue_id,
                notification_type="on_stage",
                title="You're on stage!",
                body="Your song is now playing. Break a leg!",
                data={"request_id": str(item.id)},
            )
        except Exception:
            logger.debug("on_stage notification failed", exc_info=True)
        await self.broadcast_queue_state(venue_id)
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
        await self.broadcast_queue_state(venue_id)
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
        await self.broadcast_queue_state(venue_id)

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

    async def reorder_by_singer(
        self,
        venue_id: str,
        singer_ids: list[str],
        mode: str = "round_robin",
    ) -> list[QueueRequest]:
        """Reorder the queue by providing an ordered list of singer_ids.

        For each singer in the list, fetch their active requests at this venue,
        ordered by requested_at (FIFO), then concatenate. Singers not in the
        list are appended after in FIFO order.
        """
        if not singer_ids:
            return await self.get_active_queue(venue_id, mode=mode)

        # Get all active requests at this venue
        from sqlalchemy.orm import selectinload
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
        all_items = list(result.scalars().all())

        # Group by singer_id
        by_singer: dict[str, list[QueueRequest]] = {}
        for item in all_items:
            sid = str(item.singer_id)
            by_singer.setdefault(sid, []).append(item)
        for sid in by_singer:
            by_singer[sid].sort(key=lambda i: i.requested_at or "")

        # Build ordered output
        ordered: list[QueueRequest] = []
        seen_singers: set[str] = set()
        for sid in singer_ids:
            if sid in by_singer:
                ordered.extend(by_singer[sid])
                seen_singers.add(sid)

        # Append remaining singers not in the input list, in FIFO order
        remaining = [sid for sid in by_singer if sid not in seen_singers]
        for sid in remaining:
            ordered.extend(by_singer[sid])

        # Rewrite rotation_position
        for idx, item in enumerate(ordered, start=1):
            item.rotation_position = idx
            item.updated_at = _NOW()

        await self.db.commit()
        await QueueEventPublisher.publish(
            venue_id, "queue_updated", {"action": "reordered_by_singer"}
        )
        return ordered

    async def skip_to_end(self, venue_id: str, request_id: str) -> QueueRequest:
        """Move a request to the end of the queue (max rotation_position + 1)."""
        item = await self._get_item(venue_id, request_id)
        if item.status not in {"pending", "approved", "now_playing"}:
            raise ValueError(f"Cannot skip a request with status '{item.status}'")
        # Find max rotation position
        from sqlalchemy import func
        max_pos = (
            await self.db.execute(
                select(func.coalesce(func.max(QueueRequest.rotation_position), 0))
                .select_from(QueueRequest)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        item.rotation_position = max_pos + 1
        item.updated_at = _NOW()
        await self.db.commit()
        await self.db.refresh(item)
        await QueueEventPublisher.publish(
            venue_id, "queue_updated", {"request_id": request_id, "action": "skipped_to_end"}
        )
        return item

    async def get_analytics(self, venue_id: str) -> dict[str, Any]:
        """Return queue throughput, avg wait, top songs for the venue."""
        from sqlalchemy import func
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_prefix = today[:10]

        # total requests today
        total_today = (
            await self.db.execute(
                select(func.count())
                .select_from(QueueRequest)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.requested_at.like(f"{today_prefix}%"),
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalar_one()

        # completed today
        completed_today = (
            await self.db.execute(
                select(func.count())
                .select_from(QueueRequest)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status == "completed",
                    QueueRequest.played_at.like(f"{today_prefix}%"),
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalar_one()

        # avg wait seconds (all completed requests)
        wait_rows = (
            await self.db.execute(
                select(QueueRequest.requested_at, QueueRequest.played_at)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status == "completed",
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).all()
        waits = []
        for req_at, play_at in wait_rows:
            if req_at and play_at:
                try:
                    dt_req = datetime.fromisoformat(req_at.replace("Z", "+00:00"))
                    dt_play = datetime.fromisoformat(play_at.replace("Z", "+00:00"))
                    waits.append((dt_play - dt_req).total_seconds())
                except Exception:
                    pass
        avg_wait = round(sum(waits) / len(waits), 2) if waits else None

        # top songs (all time, by request count)
        from app.models import Song
        top_rows = (
            await self.db.execute(
                select(
                    QueueRequest.song_id,
                    Song.title,
                    Song.artist,
                    func.count().label("cnt"),
                )
                .join(Song, QueueRequest.song_id == Song.id)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.deleted_at.is_(None),
                )
                .group_by(QueueRequest.song_id, Song.title, Song.artist)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
        top_songs = [
            {"song_id": str(r.song_id), "title": r.title, "artist": r.artist, "request_count": r.cnt}
            for r in top_rows
        ]

        # throughput per hour for today
        hour_rows = (
            await self.db.execute(
                select(QueueRequest.played_at)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status.in_(["completed", "skipped"]),
                    QueueRequest.played_at.like(f"{today_prefix}%"),
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).all()
        hour_counts = {h: 0 for h in range(24)}
        for (ts,) in hour_rows:
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    hour_counts[dt.hour] += 1
                except Exception:
                    pass
        throughput = [
            {"hour": h, "count": hour_counts[h]}
            for h in range(24)
        ]

        return {
            "total_requests_today": total_today,
            "completed_today": completed_today,
            "avg_wait_seconds": avg_wait,
            "top_songs": top_songs,
            "throughput_per_hour": throughput,
        }

    async def compute_queue_stats(self, venue_id: str) -> dict[str, Any]:
        """Compute real-time queue stats for WebSocket broadcast.

        Returns:
            total_pending: number of active (pending/approved) requests
            avg_wait_seconds: estimated wait per singer (280s = 4:40 fixed)
            songs_completed_tonight: number completed today
            now_playing: the currently playing item or None
        """
        from sqlalchemy import func
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_prefix = today[:10]

        # Count active (pending + approved) items
        pending_count = (
            await self.db.execute(
                select(func.count())
                .select_from(QueueRequest)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status.in_(["pending", "approved"]),
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalar_one()

        # Count singers in rotation (unique singers with active requests)
        singers_result = (
            await self.db.execute(
                select(func.count(func.distinct(QueueRequest.singer_id)))
                .select_from(QueueRequest)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                    QueueRequest.deleted_at.is_(None),
                )
            )
        )
        total_singers = singers_result.scalar_one()

        # Completed today (8 AM start logic — align with user's 8 AM suggestion)
        now = datetime.now(timezone.utc)
        cutoff = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now.hour < 8:
            cutoff = cutoff.replace(day=cutoff.day - 1)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

        completed_today = (
            await self.db.execute(
                select(func.count())
                .select_from(QueueRequest)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status == "completed",
                    QueueRequest.played_at >= cutoff_str,
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalar_one()

        # Now playing
        now_playing = await self._get_now_playing(venue_id)
        now_playing_out = None
        if now_playing:
            singer = getattr(now_playing, "singer", None)
            song = getattr(now_playing, "song", None)
            now_playing_out = {
                "request_id": str(now_playing.id),
                "singer_name": getattr(singer, "stage_name", "Unknown") if singer else "Unknown",
                "song_title": getattr(song, "title", "Unknown") if song else "Unknown",
                "started_at": str(now_playing.requested_at) if now_playing.requested_at else _NOW(),
                "elapsed_seconds": 0,
            }

        # Total active = pending + approved + now_playing
        total_active = (
            await self.db.execute(
                select(func.count())
                .select_from(QueueRequest)
                .where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalar_one()

        return {
            "total_pending": total_active,  # For "Rotation Total" card
            "avg_wait_seconds": 280,  # 4:40 fixed
            "songs_completed_tonight": completed_today,
            "now_playing": now_playing_out,
            "total_singers": total_singers,
        }

    async def get_now_playing_item(self, venue_id: str) -> QueueRequest | None:
        """Get the currently playing queue item with full details."""
        return await self._get_now_playing(venue_id)

    async def get_next_up_item(self, venue_id: str) -> QueueRequest | None:
        """Get the next item that will play (first pending/approved after now_playing)."""
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
        return result.scalar_one_or_none()

    async def broadcast_queue_state(self, venue_id: str) -> None:
        """Broadcast the full queue state + stats + now_playing via WebSocket."""
        # Get active queue
        items = await self.get_active_queue(venue_id, mode="round_robin", include_details=True)
        queue_data = []
        for idx, item in enumerate(items, start=1):
            singer = getattr(item, "singer", None)
            song = getattr(item, "song", None)
            queue_data.append({
                "request_id": str(item.id),
                "position": idx,
                "singer_id": str(item.singer_id) if item.singer_id else None,
                "singer_name": getattr(singer, "stage_name", "Unknown") if singer else "Unknown",
                "song_id": str(item.song_id) if item.song_id else None,
                "song_title": getattr(song, "title", "Unknown") if song else "Unknown",
                "song_artist": getattr(song, "artist", "Unknown") if song else "Unknown",
                "status": str(item.status),
                "notes": str(item.notes) if item.notes else None,
                "requested_at": str(item.requested_at) if item.requested_at else None,
                "estimated_wait_seconds": (idx - 1) * 280 if idx > 1 else 0,
            })

        # Stats
        stats = await self.compute_queue_stats(venue_id)

        # Now playing
        now_playing = stats.get("now_playing")

        # Broadcast queue_updated
        await QueueEventPublisher.publish(
            venue_id, "queue_updated", {"queue": queue_data, "total": len(queue_data)}
        )

        # Broadcast stats
        await QueueEventPublisher.publish(venue_id, "stats", stats)

        # Broadcast now_playing
        if now_playing:
            await QueueEventPublisher.publish(venue_id, "now_playing", now_playing)
        else:
            await QueueEventPublisher.publish(venue_id, "now_playing", {})

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
