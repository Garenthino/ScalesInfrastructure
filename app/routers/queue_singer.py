"""Singer-facing queue operations.

Endpoints:
    POST /queue/join      - join queue (body: {song_id, notes?})
    GET  /queue/status    - get my position(s) in queue
    DELETE /queue/leave   - remove self from queue
    GET  /queue/venue     - public queue view (no sensitive data)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.core.queue_service import QueueService, QueueEventPublisher, ACTIVE_STATUSES
from app.models import QueueRequest, Singer, Song, Venue
from app.schemas.queue import (
    QueueJoinRequest,
    QueueJoinResponse,
    QueueStatusResponse,
    QueueLeaveAllResponse,
    PublicQueueItem,
    PublicQueueOut,
)

router = APIRouter()

NOW = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
DEFAULT_AVG_SONG_MS = 210_000  # 3.5 min fallback


async def _require_venue(venue_id: str, db: AsyncSession) -> Venue:
    """Verify venue exists and is active."""
    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.is_active == 1,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


def _singer_owns(current: SingerUser, item: QueueRequest) -> None:
    if str(current.id) != str(item.singer_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your request")


async def _avg_song_ms(db: AsyncSession, venue_id: str) -> int:
    """Average duration of available songs at this venue, or default."""
    result = await db.execute(
        select(func.coalesce(func.avg(Song.duration_ms), DEFAULT_AVG_SONG_MS)).where(
            Song.venue_id == venue_id,
            Song.is_available == 1,
            Song.is_active == 1,
            Song.deleted_at.is_(None),
        )
    )
    avg = result.scalar_one()
    return int(avg) if avg else DEFAULT_AVG_SONG_MS


async def _compute_positions(db: AsyncSession, venue_id: str, mode: str = "round_robin") -> dict[str, int]:
    """Return mapping request_id -> position for active queue items."""
    svc = QueueService(db)
    items = await svc.get_active_queue(venue_id, mode=mode, include_details=False)
    return {str(item.id): idx + 1 for idx, item in enumerate(items)}


async def _get_active_request_for_singer(db: AsyncSession, venue_id: str, singer_id: str) -> QueueRequest | None:
    result = await db.execute(
        select(QueueRequest)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == singer_id,
            QueueRequest.status.in_(list(ACTIVE_STATUSES)),
            QueueRequest.deleted_at.is_(None),
        )
        .order_by(QueueRequest.rotation_position)
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# JOIN
# ---------------------------------------------------------------------------

@router.post("/join", response_model=QueueJoinResponse, status_code=status.HTTP_201_CREATED)
async def join_queue(
    venue_id: str,
    body: QueueJoinRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # venue scoping
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    await _require_venue(venue_id, db)

    # verify song exists and is available at this venue
    song = (
        await db.execute(
            select(Song).where(
                Song.id == body.song_id,
                Song.venue_id == venue_id,
                Song.is_available == 1,
                Song.is_active == 1,
                Song.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if song is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Song not found or unavailable")

    # max 3 active requests per singer
    active_count = (
        await db.execute(
            select(func.count()).select_from(QueueRequest).where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.singer_id == current.id,
                QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if active_count >= 3:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Maximum of 3 active requests reached",
        )

    # duplicate song check (warn but allow)
    duplicate = (
        await db.execute(
            select(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.singer_id == current.id,
                QueueRequest.song_id == body.song_id,
                QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    req_id = str(uuid.uuid4())
    # figure rotation_position at tail
    tail = (
        await db.execute(
            select(func.coalesce(func.max(QueueRequest.rotation_position), 0))
            .select_from(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    q = QueueRequest(
        id=req_id,
        venue_id=venue_id,
        singer_id=current.id,
        song_id=body.song_id,
        status="pending",
        notes=body.notes,
        rotation_position=tail + 1,
        requested_at=NOW(),
        updated_at=NOW(),
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)

    # recompute positions so estimated_position is accurate
    positions = await _compute_positions(db, venue_id)
    est_pos = positions.get(req_id)

    warning = None
    if duplicate is not None:
        warning = "You already have this song in the queue"

    await QueueEventPublisher.publish(
        venue_id, "queue_updated", {"request_id": req_id, "action": "joined"}
    )

    return QueueJoinResponse(
        request_id=req_id,
        estimated_position=est_pos or tail + 1,
        warning=warning,
    )


# ---------------------------------------------------------------------------
# STATUS
# ---------------------------------------------------------------------------

@router.get("/status", response_model=list[QueueStatusResponse])
async def queue_status(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    avg_ms = await _avg_song_ms(db, venue_id)
    positions = await _compute_positions(db, venue_id)

    result = await db.execute(
        select(QueueRequest, Song.title, Song.artist, Song.duration_ms)
        .join(Song, Song.id == QueueRequest.song_id)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == current.id,
            QueueRequest.status.in_(list(ACTIVE_STATUSES)),
            QueueRequest.deleted_at.is_(None),
        )
        .order_by(QueueRequest.rotation_position)
    )
    rows = result.all()
    out = []
    for item, title, artist, dur in rows:
        pos = positions.get(str(item.id))
        # ETA = (position - 1) * avg song duration
        eta = ((pos or 1) - 1) * avg_ms // 1000 if pos else None
        out.append(QueueStatusResponse(
            request_id=str(item.id),
            position=pos or 0,
            status=str(item.status),
            song_title=title or "Unknown",
            song_artist=artist or "Unknown",
            eta_seconds=eta,
        ))
    return out


# ---------------------------------------------------------------------------
# LEAVE
# ---------------------------------------------------------------------------

@router.delete("/leave", response_model=QueueLeaveAllResponse)
async def leave_queue(
    venue_id: str,
    request_id: str | None = Query(None, description="Specific request to cancel; if omitted, cancels all active"),
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    if request_id:
        item = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.id == request_id,
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Request not found")
        _singer_owns(current, item)
        item.deleted_at = NOW()
        item.updated_at = NOW()
        removed = 1
    else:
        # cancel all active for this singer
        result = await db.execute(
            select(QueueRequest).where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.singer_id == current.id,
                QueueRequest.status.in_(list(ACTIVE_STATUSES)),
                QueueRequest.deleted_at.is_(None),
            )
        )
        items = result.scalars().all()
        now = NOW()
        for item in items:
            item.deleted_at = now
            item.updated_at = now
        removed = len(items)

    await db.commit()

    await QueueEventPublisher.publish(
        venue_id, "queue_updated", {"singer_id": current.id, "action": "left"}
    )

    return QueueLeaveAllResponse(removed=removed)


# ---------------------------------------------------------------------------
# VENUE PUBLIC VIEW
# ---------------------------------------------------------------------------

@router.get("/venue", response_model=PublicQueueOut)
async def public_queue(
    venue_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _require_venue(venue_id, db)

    avg_ms = await _avg_song_ms(db, venue_id)
    svc = QueueService(db)
    items = await svc.get_active_queue(venue_id, mode="round_robin", include_details=True)

    out_items = []
    current_song = None
    for idx, item in enumerate(items, start=1):
        singer = getattr(item, "singer", None)
        song = getattr(item, "song", None)

        # If this is the first approved/now_playing item, treat as current
        if current_song is None and str(item.status) in ("approved", "now_playing", "pending"):
            # We'll expose the actual now_playing item if present
            pass

        # Public-safe: only stage_name, no email/phone/etc.
        stage_name = getattr(singer, "stage_name", "Unknown") if singer else "Unknown"

        est_start = None
        if idx > 1:  # item deeper in queue
            est_start_sec = (idx - 1) * avg_ms // 1000
            est_start = f"~{est_start_sec // 60}m"

        out_items.append(PublicQueueItem(
            position=idx,
            status=str(item.status),
            song_title=getattr(song, "title", "Unknown") if song else "Unknown",
            song_artist=getattr(song, "artist", "Unknown") if song else "Unknown",
            stage_name=stage_name,
            estimated_start=est_start,
        ))

    # Identify current song (now_playing first, else first approved)
    for item in items:
        if str(item.status) == "now_playing":
            song = getattr(item, "song", None)
            singer = getattr(item, "singer", None)
            current_song = {
                "song_title": getattr(song, "title", "Unknown") if song else "Unknown",
                "song_artist": getattr(song, "artist", "Unknown") if song else "Unknown",
                "stage_name": getattr(singer, "stage_name", "Unknown") if singer else "Unknown",
            }
            break
    else:
        for item in items:
            if str(item.status) == "approved":
                song = getattr(item, "song", None)
                singer = getattr(item, "singer", None)
                current_song = {
                    "song_title": getattr(song, "title", "Unknown") if song else "Unknown",
                    "song_artist": getattr(song, "artist", "Unknown") if song else "Unknown",
                    "stage_name": getattr(singer, "stage_name", "Unknown") if singer else "Unknown",
                }
                break

    return PublicQueueOut(
        venue_id=venue_id,
        items=out_items,
        current_song=current_song,
    )
