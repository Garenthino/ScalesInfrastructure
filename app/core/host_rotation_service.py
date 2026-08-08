"""Host rotation (KJ desktop live queue) service.

This service is intentionally separate from QueueService. QueueRequest stores
mobile/portal inbound requests; HostRotation stores the KJ desktop's live
rotation state. Both tables share concepts (status, singer, song, position)
but should not be mixed in production code paths.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HostRotation, QueueRequest
from app.core.queue_service import (
    TERMINAL_STATUSES,
    AVG_SONG_SECONDS,
    is_kj_online,
)
from app.core.queue_service import QueueEventPublisher  # re-used broadcaster


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _song_out(song) -> dict[str, Any]:
    if song is None:
        return {}
    return {
        "id": str(song.id),
        "title": song.title or "",
        "artist": song.artist or "",
        "duration_seconds": getattr(song, "duration_seconds", None),
    }


def _singer_out(singer) -> dict[str, Any] | None:
    if singer is None:
        return None
    return {
        "id": str(singer.id),
        "stage_name": getattr(singer, "stage_name", None) or "",
        "name": getattr(singer, "name", None) or getattr(singer, "stage_name", None) or "",
    }


def _host_rotation_out(item: HostRotation, position: int | None = None, est_wait: int = 0) -> dict[str, Any]:
    return {
        "request_id": str(item.id),
        "singer_id": str(item.singer_id) if item.singer_id else None,
        "song_id": str(item.song_id) if item.song_id else None,
        "position": position if position is not None else (item.rotation_position if item.rotation_position is not None else None),
        "status": str(item.status),
        "notes": str(item.notes) if item.notes else None,
        "requested_at": str(item.requested_at) if item.requested_at else None,
        "updated_at": str(item.updated_at) if item.updated_at else None,
        "played_at": str(item.completed_at) if item.completed_at is not None else None,
        "estimated_wait_seconds": est_wait,
        "song": {},
        "singer": {},
    }
class HostRotationService:
    """Manage the KJ desktop live rotation stored in the HostRotation table."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_items(self, venue_id: str) -> list[HostRotation]:
        result = await self.db.execute(
            select(HostRotation)
            .where(
                HostRotation.venue_id == venue_id,
                HostRotation.deleted_at.is_(None),
                HostRotation.status.not_in(TERMINAL_STATUSES),
            )
            .order_by(HostRotation.sort_order, HostRotation.requested_at)
        )
        return list(result.scalars().all())

    async def get_all_items(self, venue_id: str) -> list[HostRotation]:
        result = await self.db.execute(
            select(HostRotation)
            .where(
                HostRotation.venue_id == venue_id,
                HostRotation.deleted_at.is_(None),
            )
            .order_by(HostRotation.sort_order, HostRotation.requested_at)
        )
        return list(result.scalars().all())

    async def upsert_snapshot(
        self,
        venue_id: str,
        items: list[Any],
        rotation_session_id: str | None = None,
    ) -> tuple[list[HostRotation], list[str]]:
        """Replace the venue's active host rotation with a new snapshot.

        ``items`` is a list of duck-typed objects with at least:
        id, singer_id, song_id, status, rotation_position, sort_order,
        notes, tempo, pitch, kj_id.

        Returns (created/updated rows, removed ids).
        """
        # Demote any existing now_playing row(s) before promoting a new one.
        if any(getattr(item, "status", None) == "now_playing" for item in items):
            await self.db.execute(
                update(HostRotation)
                .where(
                    HostRotation.venue_id == venue_id,
                    HostRotation.status == "now_playing",
                )
                .values(
                    status="completed",
                    completed_at=_now_iso(),
                    updated_at=_now_iso(),
                )
            )

        incoming_ids = {str(getattr(item, "id", "")) for item in items if getattr(item, "id", None)}

        # Load all venue rows (including soft-deleted) so we can match incoming
        # IDs and resurrect previously-deleted rotation items rather than
        # violating the primary key.
        result = await self.db.execute(
            select(HostRotation)
            .where(HostRotation.venue_id == venue_id)
            .options(selectinload(HostRotation.singer), selectinload(HostRotation.song))
        )
        existing_rows = list(result.scalars().all())

        # Soft-delete active rows not present in the new snapshot.
        removed_ids = []
        for existing in existing_rows:
            if existing.deleted_at is None and str(existing.id) not in incoming_ids:
                existing.deleted_at = _now_iso()
                existing.updated_at = _now_iso()
                removed_ids.append(str(existing.id))

        upserted = []
        for item in items:
            item_id = str(getattr(item, "id", "")) or str(uuid.uuid4())
            existing = next((r for r in existing_rows if str(r.id) == item_id), None)
            if existing:
                existing.singer_id = str(item.singer_id)
                if getattr(item, "song_id", None):
                    existing.song_id = str(item.song_id)
                if getattr(item, "song_title", None) is not None:
                    existing.song_title = str(item.song_title)
                existing.status = str(item.status)
                existing.rotation_position = getattr(item, "rotation_position", None)
                existing.sort_order = getattr(item, "sort_order", 0)
                existing.notes = getattr(item, "notes", None)
                existing.reject_reason = getattr(item, "reject_reason", None)
                existing.tempo = getattr(item, "tempo", 0)
                existing.pitch = getattr(item, "pitch", 0)
                existing.kj_id = getattr(item, "kj_id", None)
                if rotation_session_id:
                    existing.rotation_session_id = rotation_session_id
                existing.updated_at = _now_iso()
                existing.deleted_at = None
                upserted.append(existing)
            else:
                new_item = HostRotation(
                    id=item_id,
                    venue_id=venue_id,
                    singer_id=str(item.singer_id),
                    song_id=str(getattr(item, "song_id", "")) if getattr(item, "song_id", None) else None,
                    song_title=str(getattr(item, "song_title", "")) if getattr(item, "song_title", None) else None,
                    status=str(item.status),
                    rotation_position=getattr(item, "rotation_position", None),
                    sort_order=getattr(item, "sort_order", 0),
                    notes=getattr(item, "notes", None),
                    reject_reason=getattr(item, "reject_reason", None),
                    tempo=getattr(item, "tempo", 0),
                    pitch=getattr(item, "pitch", 0),
                    kj_id=getattr(item, "kj_id", None),
                    rotation_session_id=rotation_session_id,
                    requested_at=_now_iso(),
                    updated_at=_now_iso(),
                )
                self.db.add(new_item)
                upserted.append(new_item)

        await self.db.flush()
        return upserted, removed_ids

    async def set_now_playing(
        self,
        venue_id: str,
        singer_id: str | None,
        song_id: str | None = None,
        song_title: str | None = None,
        song_artist: str | None = None,
        singer_name: str | None = None,
        notes: str | None = None,
        is_dj_track: bool = False,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a singer/song (or a specific rotation item) as now playing."""
        if is_dj_track:
            return {
                "request_id": "dj_track",
                "singer_name": "DJ",
                "song_title": song_title,
                "song_artist": song_artist,
                "started_at": _now_iso(),
                "elapsed_seconds": 0,
                "is_dj_track": True,
            }

        if request_id:
            existing = (
                await self.db.execute(
                    select(HostRotation).where(
                        HostRotation.id == request_id,
                        HostRotation.venue_id == venue_id,
                        HostRotation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise ValueError("Rotation item not found")
        elif not singer_id:
            return None
        else:
            existing = (
                await self.db.execute(
                    select(HostRotation).where(
                        HostRotation.venue_id == venue_id,
                        HostRotation.singer_id == singer_id,
                        HostRotation.deleted_at.is_(None),
                    )
                )
            ).scalars().first()

        if existing is None and singer_id:
            existing = HostRotation(
                id=str(uuid.uuid4()),
                venue_id=venue_id,
                singer_id=singer_id,
                song_id=song_id,
                song_title=song_title,
                status="now_playing",
                rotation_position=0,
                sort_order=0,
                notes=notes or singer_name or "",
                source="host",
                requested_at=_now_iso(),
                updated_at=_now_iso(),
            )
            self.db.add(existing)

        # Demote any existing now_playing for this venue.
        if existing:
            await self.db.execute(
                update(HostRotation)
                .where(
                    HostRotation.venue_id == venue_id,
                    HostRotation.status == "now_playing",
                    HostRotation.id != existing.id,
                )
                .values(
                    status="completed",
                    completed_at=_now_iso(),
                    updated_at=_now_iso(),
                )
            )

        existing.status = "now_playing"
        existing.updated_at = _now_iso()
        if song_id:
            existing.song_id = song_id
        if song_title:
            existing.song_title = song_title
        if notes:
            existing.notes = notes

        await self.db.flush()
        await self.db.refresh(existing, attribute_names=["singer", "song"])
        await self.broadcast_queue_state(venue_id)
        return _host_rotation_out(existing)

    async def remove_singer(
        self,
        venue_id: str,
        singer_id: str,
        removed_by_device_id: str | None = None,
        removed_by_account_id: str | None = None,
    ) -> list[str]:
        """Soft-delete all active host rotation rows for a singer and record removal."""
        result = await self.db.execute(
            select(HostRotation).where(
                HostRotation.venue_id == venue_id,
                HostRotation.singer_id == singer_id,
                HostRotation.deleted_at.is_(None),
                HostRotation.status.not_in(TERMINAL_STATUSES),
            )
        )
        rows = result.scalars().all()
        removed_ids = []
        for row in rows:
            row.deleted_at = _now_iso()
            row.updated_at = _now_iso()
            removed_ids.append(str(row.id))

        # Record a SingerRemoval so the KJ desktop (and other clients) can pull it.
        if removed_ids:
            from app.models import SingerRemoval
            self.db.add(SingerRemoval(
                id=str(uuid.uuid4()),
                venue_id=venue_id,
                singer_id=singer_id,
                removed_by_device_id=removed_by_device_id,
                removed_by_account_id=removed_by_account_id,
                removed_at=_now_iso(),
            ))
            await self.db.flush()
        return removed_ids

    async def broadcast_queue_state(self, venue_id: str) -> None:
        """Emit the current host rotation to the portal via WebSocket."""
        items = await self.get_active_items(venue_id)
        now_playing = next((it for it in items if it.status == "now_playing"), None)
        queue_without_now_playing = [it for it in items if it.status != "now_playing"]

        estimated_wait = 0
        out_items = []
        for idx, item in enumerate(queue_without_now_playing):
            out_items.append(_host_rotation_out(item, position=idx, est_wait=estimated_wait))
            estimated_wait += AVG_SONG_SECONDS

        now_playing_out = None
        if now_playing:
            now_playing_out = _host_rotation_out(now_playing)
            now_playing_out["started_at"] = now_playing.requested_at or _now_iso()

        kj_online = await is_kj_online(venue_id, db=self.db)
        stats = {
            "total_pending": len(queue_without_now_playing),
            "avg_wait_seconds": estimated_wait,
            "songs_completed_tonight": 0,
            "now_playing": now_playing_out,
            "total_singers": len({it.singer_id for it in items}),
        }

        publisher = QueueEventPublisher()
        try:
            await publisher.emit(
                venue_id=venue_id,
                event_type="queue_updated",
                payload={"queue": out_items, "kj_online": kj_online},
            )
            if now_playing_out:
                await publisher.emit(
                    venue_id=venue_id,
                    event_type="now_playing",
                    payload=now_playing_out,
                )
            await publisher.emit(
                venue_id=venue_id,
                event_type="stats",
                payload=stats,
            )
        finally:
            await publisher.close()

    async def complete(self, venue_id: str, request_id: str) -> HostRotation:
        """Mark a host rotation item as completed."""
        item = await self._get_item(venue_id, request_id)
        if item.status not in {"up_next", "now_playing"}:
            raise ValueError(f"Cannot complete a rotation item with status '{item.status}'")
        was_playing = item.status == "now_playing"
        item.status = "completed"
        item.completed_at = _now_iso()
        item.updated_at = _now_iso()
        await self.db.commit()
        await self.db.refresh(item)
        if was_playing:
            await self._auto_advance(venue_id)
        await self.broadcast_queue_state(venue_id)
        return item

    async def skip(self, venue_id: str, request_id: str) -> HostRotation:
        """Skip a rotation item and auto-advance if it is now_playing."""
        item = await self._get_item(venue_id, request_id)
        if item.status not in {"up_next", "now_playing", "pending"}:
            raise ValueError(f"Cannot skip a rotation item with status '{item.status}'")
        item.status = "skipped"
        item.completed_at = _now_iso()
        item.updated_at = _now_iso()
        await self.db.commit()
        await self.db.refresh(item)
        was_playing = item.status == "skipped"  # already set
        # Auto-advance if we just skipped the current song
        await self._auto_advance(venue_id)
        await self.broadcast_queue_state(venue_id)
        return item

    async def skip_to_end(self, venue_id: str, request_id: str) -> HostRotation:
        """Move a rotation item to the end of the queue."""
        item = await self._get_item(venue_id, request_id)
        if item.status not in {"up_next", "now_playing", "pending"}:
            raise ValueError(f"Cannot skip-to-end a rotation item with status '{item.status}'")
        from sqlalchemy import func
        max_pos = (
            await self.db.execute(
                select(func.coalesce(func.max(HostRotation.rotation_position), 0))
                .select_from(HostRotation)
                .where(
                    HostRotation.venue_id == venue_id,
                    HostRotation.deleted_at.is_(None),
                    HostRotation.status.in_(["pending", "up_next", "now_playing"]),
                )
            )
        ).scalar_one()
        item.rotation_position = max_pos + 1
        item.updated_at = _now_iso()
        await self.db.commit()
        await self.db.refresh(item)
        await self.broadcast_queue_state(venue_id)
        return item

    async def remove(self, venue_id: str, request_id: str) -> None:
        """Soft-delete a single rotation item."""
        item = await self._get_item(venue_id, request_id)
        item.deleted_at = _now_iso()
        item.updated_at = _now_iso()
        await self.db.commit()
        await self.broadcast_queue_state(venue_id)

    async def reorder(self, venue_id: str, ordered_ids: list[str]) -> list[HostRotation]:
        """Validate all IDs belong to venue, then rewrite rotation_position."""
        if not ordered_ids:
            return await self.get_active_items(venue_id)
        result = await self.db.execute(
            select(HostRotation)
            .where(
                HostRotation.venue_id == venue_id,
                HostRotation.deleted_at.is_(None),
                HostRotation.status.in_(["pending", "up_next", "now_playing"]),
            )
            .options(selectinload(HostRotation.singer), selectinload(HostRotation.song))
        )
        existing = {str(r.id): r for r in result.scalars().all()}
        if not set(ordered_ids).issubset(existing.keys()):
            raise ValueError("One or more IDs do not belong to this venue or are not active")
        for idx, rid in enumerate(ordered_ids, start=1):
            existing[rid].rotation_position = idx
            existing[rid].updated_at = _now_iso()
        await self.db.commit()
        await self.broadcast_queue_state(venue_id)
        return [existing[rid] for rid in ordered_ids]

    async def reorder_by_singer(
        self, venue_id: str, singer_ids: list[str]
    ) -> list[HostRotation]:
        """Reorder rotation by singer order."""
        if not singer_ids:
            return await self.get_active_items(venue_id)
        result = await self.db.execute(
            select(HostRotation)
            .where(
                HostRotation.venue_id == venue_id,
                HostRotation.deleted_at.is_(None),
                HostRotation.status.in_(["pending", "up_next", "now_playing"]),
            )
            .options(selectinload(HostRotation.singer), selectinload(HostRotation.song))
        )
        all_items = list(result.scalars().all())
        by_singer: dict[str, list[HostRotation]] = {}
        for item in all_items:
            sid = str(item.singer_id)
            by_singer.setdefault(sid, []).append(item)
        for sid in by_singer:
            by_singer[sid].sort(key=lambda i: i.requested_at or "")
        ordered: list[HostRotation] = []
        seen: set[str] = set()
        for sid in singer_ids:
            if sid in by_singer:
                ordered.extend(by_singer[sid])
                seen.add(sid)
        for sid in by_singer:
            if sid not in seen:
                ordered.extend(by_singer[sid])
        for idx, item in enumerate(ordered, start=1):
            item.rotation_position = idx
            item.updated_at = _now_iso()
        await self.db.commit()
        await self.broadcast_queue_state(venue_id)
        return ordered

    async def _get_item(self, venue_id: str, request_id: str) -> HostRotation:
        result = await self.db.execute(
            select(HostRotation)
            .where(
                HostRotation.id == request_id,
                HostRotation.venue_id == venue_id,
                HostRotation.deleted_at.is_(None),
            )
            .options(selectinload(HostRotation.singer), selectinload(HostRotation.song))
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise ValueError("Rotation item not found")
        return item

    async def _get_now_playing(self, venue_id: str) -> HostRotation | None:
        result = await self.db.execute(
            select(HostRotation)
            .where(
                HostRotation.venue_id == venue_id,
                HostRotation.status == "now_playing",
                HostRotation.deleted_at.is_(None),
            )
            .order_by(HostRotation.updated_at.desc(), HostRotation.requested_at.desc())
            .limit(1)
            .options(selectinload(HostRotation.singer), selectinload(HostRotation.song))
        )
        return result.scalar_one_or_none()

    async def _auto_advance(self, venue_id: str) -> HostRotation | None:
        """If no now_playing exists, start the next pending/up_next item."""
        existing = await self._get_now_playing(venue_id)
        if existing is not None:
            return None
        result = await self.db.execute(
            select(HostRotation)
            .where(
                HostRotation.venue_id == venue_id,
                HostRotation.status.in_(["pending", "up_next"]),
                HostRotation.deleted_at.is_(None),
            )
            .order_by(HostRotation.rotation_position.asc(), HostRotation.requested_at.asc())
            .limit(1)
            .options(selectinload(HostRotation.singer), selectinload(HostRotation.song))
        )
        next_item = result.scalar_one_or_none()
        if next_item is not None:
            next_item.status = "now_playing"
            next_item.updated_at = _now_iso()
            await self.db.commit()
            await self.db.refresh(next_item)
            return next_item
        return None

