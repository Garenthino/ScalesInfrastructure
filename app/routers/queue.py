"""Core karaoke show control surface.

Endpoints:
    POST   /queue            - submit request (singer)
    DELETE /queue/{id}       - cancel own request (singer)
    PATCH  /queue/{id}       - edit notes on own request (singer)
    GET    /queue/list       - list queue with full details (any authenticated singer)
    POST   /queue/{id}/start    - mark request now_playing (KJ/ADMIN only)
    POST   /queue/{id}/complete - mark request completed (KJ/ADMIN only)
    POST   /queue/{id}/skip     - skip a request (KJ/ADMIN only)
    PUT    /queue/reorder     - atomic reorder (KJ/ADMIN only)

Only KJ/ADMIN can start/complete/skip/reorder.
Complete auto-advances rotation.
Only 1 NOW_PLAYING per venue.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.core.queue_service import QueueService, ACTIVE_STATUSES
from app.core.permissions import Role
from app.core.dependencies import require_role
from app.models import QueueRequest, Song, Venue, KJDevice, HostRotation
from app.schemas import QueueRequestCreate, QueueRequestUpdate, QueueReorder, QueueAdminListOut
from app.schemas.queue import QueueCancelResponse

from app.core.loyalty_service import award_performance_points
from app.core.queue_service import QueueEventPublisher

from datetime import datetime, timezone


from app.core.host_rotation_service import HostRotationService

router = APIRouter()

# How long since last KJ push before we consider the KJ offline.
# The client syncs every few seconds, but we allow a generous window
# for technical difficulties, pauses, etc. before clearing the portal.
KJ_OFFLINE_THRESHOLD_SECONDS = 3600


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

async def _is_kj_online(db: AsyncSession, venue_id: str) -> bool:
    """Check if any KJ device for this venue has been seen recently."""
    from sqlalchemy import func as sa_func
    cutoff = (
        datetime.now(timezone.utc)
        - __import__("datetime").timedelta(seconds=KJ_OFFLINE_THRESHOLD_SECONDS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = await db.execute(
        select(sa_func.count())
        .select_from(KJDevice)
        .where(
            KJDevice.venue_id == venue_id,
            KJDevice.last_seen >= cutoff,
            KJDevice.revoked_at.is_(None),
        )
    )
    return result.scalar_one() > 0


NOW = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _song_out(song) -> dict[str, Any]:
    if song is None:
        return None  # type: ignore[return-value]
    data = {k: getattr(song, k) for k in song.__table__.columns.keys()}
    data["is_active"] = bool(data.get("is_active", 1))
    data["is_available"] = bool(data.get("is_available", 1))
    return {
        "id": data["id"],
        "venue_id": data["venue_id"],
        "title": data["title"],
        "artist": data["artist"],
        "album": data.get("album"),
        "genre": data.get("genre"),
        "category": data.get("category"),
        "language": data.get("language"),
        "duration_ms": data.get("duration_ms"),
        "year": data.get("year"),
        "lyrics_url": data.get("lyrics_url"),
        "cover_art_url": data.get("cover_art_url"),
        "is_available": data["is_available"],
        "catalog_id": data.get("catalog_id"),
        "is_active": data["is_active"],
        "meta_json": data.get("meta_json"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def _singer_out(singer) -> dict[str, Any] | None:
    if singer is None:
        return None
    data = {k: getattr(singer, k) for k in singer.__table__.columns.keys()}
    return {
        "id": data["id"],
        "singer_id": data["id"],
        "venue_id": data["venue_id"],
        "name": data["stage_name"],
        "stage_name": data["stage_name"],
        "display_name": data.get("stage_name"),
        "real_name": data.get("real_name"),
        "pronouns": data.get("pronouns"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "notes": data.get("notes"),
        "bio": data.get("bio"),
        "avatar_url": data.get("avatar_url"),
        "social_links": data.get("social_links"),
        "total_points": data.get("total_points", 0),
        "loyalty_tier_id": data.get("loyalty_tier_id"),
        "tier": data.get("loyalty_tier_id", "none") or "none",
        "total_visits": 0,
        "last_visit_date": data.get("last_seen"),
        "last_seen": data.get("last_seen"),
        "status": "banned" if data.get("deactivated_at") else "active",
        "is_checked_in": False,
        "checked_in_at": None,
        "deactivated_at": data.get("deactivated_at"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def _host_rotation_out(item: HostRotation, position: int | None = None, est_wait: int = 0) -> dict[str, Any]:
    song = item.song if "song" in item.__dict__ else None
    singer = item.singer if "singer" in item.__dict__ else None
    song_data = _song_out(song) or {}
    singer_data = _singer_out(singer) or {}
    return {
        "request_id": str(item.id),
        "venue_id": str(item.venue_id),
        "singer_id": str(item.singer_id),
        "song_id": str(item.song_id) if item.song_id else None,
        "position": position if position is not None else (item.rotation_position if item.rotation_position is not None else None),
        "status": str(item.status),
        "song": song_data,
        "singer": singer_data,
        "song_title": song_data.get("title") if song_data else "",
        "singer_name": singer_data.get("stage_name") or singer_data.get("name") if singer_data else "",
        "submitted_at": str(item.requested_at) if item.requested_at else None,
        "estimated_wait_seconds": est_wait,
        "estimated_start": None,
        "notes": str(item.notes) if item.notes is not None else None,
        "dedication": None,
        "tempo": int(item.tempo) if item.tempo is not None else 0,
        "pitch": int(item.pitch) if item.pitch is not None else 0,
    }


def _queue_request_out(item: QueueRequest, position: int | None = None, est_wait: int = 0) -> dict[str, Any]:
    song = getattr(item, "song", None)
    singer = getattr(item, "singer", None)
    song_data = _song_out(song) or {}
    singer_data = _singer_out(singer) or {}
    return {
        "request_id": str(item.id),
        "singer_id": str(item.singer_id),
        "position": position if position is not None else int(item.rotation_position) if item.rotation_position is not None else None,
        "status": str(item.status),
        "song": song_data,
        "singer": singer_data,
        "song_title": song_data.get("title") if song_data else "",
        "singer_name": singer_data.get("stage_name") or singer_data.get("name") if singer_data else "",
        "submitted_at": str(item.requested_at),
        "estimated_wait_seconds": est_wait,
        "estimated_start": None,
        "notes": str(item.notes) if item.notes is not None else None,
        "dedication": None,
        "tempo": int(item.tempo) if item.tempo is not None else 0,
        "pitch": int(item.pitch) if item.pitch is not None else 0,
    }


def _queue_item_out(item: QueueRequest, position: int | None = None) -> dict[str, Any]:
    song = getattr(item, "song", None)
    singer = getattr(item, "singer", None)
    song_data = _song_out(song) or {}
    singer_data = _singer_out(singer) or {}
    return {
        "request_id": str(item.id),
        "singer_id": str(item.singer_id),
        "venue_id": str(item.venue_id),
        "position": position if position is not None else int(item.rotation_position) if item.rotation_position is not None else None,
        "status": str(item.status),
        "song": song_data,
        "singer": singer_data,
        "song_title": song_data.get("title") if song_data else "",
        "singer_name": singer_data.get("stage_name") or singer_data.get("name") if singer_data else "",
        "notes": str(item.notes) if item.notes is not None else None,
        "reject_reason": str(item.reject_reason) if item.reject_reason is not None else None,
        "requested_at": str(item.requested_at),
        "tempo": int(item.tempo) if item.tempo is not None else 0,
        "pitch": int(item.pitch) if item.pitch is not None else 0,
        "updated_at": str(item.updated_at) if item.updated_at is not None else None,
        "played_at": str(item.played_at) if item.played_at is not None else None,
    }


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------

@router.get("/list")
async def get_queue_list(
    venue_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    # If no KJ device has been seen recently, return empty queue
    # (the show is offline — stale DB data shouldn't display as live).
    if not await _is_kj_online(db, venue_id):
        return {"items": [], "total": 0, "page": page, "per_page": per_page}

    svc = HostRotationService(db)
    rotation_items = await svc.get_active_items(venue_id)

    # Collapse to one row per singer in the live rotation, picking the highest
    # priority status (now_playing > up_next > pending).
    by_singer: dict[str, HostRotation] = {}
    priority = {"now_playing": 0, "up_next": 1, "pending": 2}
    for item in rotation_items:
        sid = str(item.singer_id)
        existing = by_singer.get(sid)
        if existing is None or priority.get(str(item.status), 99) < priority.get(str(existing.status), 99):
            by_singer[sid] = item
    rotation_items = sorted(
        by_singer.values(),
        key=lambda i: (i.rotation_position or 0, priority.get(str(i.status), 99)),
    )

    # Calculate estimated wait starting from now_playing, wrapping around
    AVG_SONG_SECONDS = 280
    now_playing_idx = -1
    for i, item in enumerate(rotation_items):
        if str(item.status) == "now_playing":
            now_playing_idx = i
            break

    total = len(rotation_items)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = rotation_items[start:end]

    out = []
    for i, item in enumerate(paginated):
        abs_idx = start + i  # 0-based index in full list
        if now_playing_idx == -1 or str(item.status) == "now_playing":
            est_wait = 0
        else:
            positions_after = abs_idx - now_playing_idx
            if positions_after <= 0:
                positions_after = total - now_playing_idx + abs_idx
            est_wait = positions_after * AVG_SONG_SECONDS
        out.append(_host_rotation_out(item, position=abs_idx + 1, est_wait=est_wait))
    return {"items": out, "total": total, "page": page, "per_page": per_page}


# ---------------------------------------------------------------------------
# CANCEL OWN REQUEST
# ---------------------------------------------------------------------------

@router.delete("/me/{request_id}", response_model=QueueCancelResponse, status_code=status.HTTP_200_OK)
async def cancel_my_request(
    venue_id: str,
    request_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """An authenticated singer cancels their own pending request.

    Only `pending` requests can be cancelled by the singer. Requests that have
    already been approved, started, completed, skipped, rejected, or removed
    by the KJ return a 400 or 404 as appropriate.
    """
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

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

    if str(current.id) != str(item.singer_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your request")

    if str(item.status) not in {"pending"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel a request with status '{item.status}'",
        )

    item.status = "rejected"
    item.reject_reason = "Cancelled by singer"
    item.updated_at = _now_iso()
    await db.commit()

    svc = QueueService(db)
    await svc.broadcast_queue_state(venue_id)
    await QueueEventPublisher.publish(
        venue_id, "request_cancelled", {"request_id": request_id, "singer_id": str(current.id)}
    )
    return QueueCancelResponse(request_id=request_id, status="cancelled")


# ---------------------------------------------------------------------------
# CANCEL OWN REQUEST (legacy path kept for compatibility)
# ---------------------------------------------------------------------------

@router.delete("/me/queue/{request_id}", status_code=status.HTTP_200_OK)
async def cancel_my_queue_request_legacy(
    venue_id: str,
    request_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy path. Delegates to the canonical /queue/me/{request_id} behaviour."""
    return await cancel_my_request(venue_id, request_id, current, db)


# ---------------------------------------------------------------------------
# SUBMIT
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_request(
    venue_id: str,
    body: QueueRequestCreate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

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
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=current.id,
        song_id=body.song_id,
        status="pending",
        notes=body.notes,
        source="mobile",
        rotation_position=tail + 1,
        tempo=getattr(body, "tempo", 0) or 0,
        pitch=getattr(body, "pitch", 0) or 0,
        requested_at=NOW,
        updated_at=NOW,
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    try:
        await db.refresh(q, attribute_names=["singer", "song"])
    except Exception:
        pass  # lazy relationships may not eagerly load on SQLite + async

    return _queue_request_out(q, position=q.rotation_position)


# ---------------------------------------------------------------------------
# CANCEL
# ---------------------------------------------------------------------------

@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_request(
    venue_id: str,
    request_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

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

    if str(current.id) != str(item.singer_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your request")

    svc = QueueService(db)
    await svc.cancel(venue_id, request_id)
    return None


# ---------------------------------------------------------------------------
# EDIT
# ---------------------------------------------------------------------------

@router.patch("/{request_id}")
async def edit_request(
    venue_id: str,
    request_id: str,
    body: QueueRequestUpdate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

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

    if str(current.id) != str(item.singer_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not your request")

    if str(item.status) not in ("pending", "approved", "now_playing"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot edit a request with status '{item.status}'",
        )

    svc = QueueService(db)
    updated = await svc.update(
        venue_id,
        request_id,
        notes=body.notes,
        dedication_to=body.dedication_to,
    )
    try:
        await db.refresh(updated, attribute_names=["singer", "song"])
    except Exception:
        pass
    return _queue_request_out(updated, position=updated.rotation_position)


# ---------------------------------------------------------------------------
# START (KJ/ADMIN only)
# ---------------------------------------------------------------------------

@router.post("/{request_id}/start")
async def start_song(
    venue_id: str,
    request_id: str,
    current: SingerUser = Depends(require_role(Role.KJ)),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    svc = HostRotationService(db)
    # Enforce only one now_playing at a time for the public KJ start endpoint.
    existing = await svc._get_now_playing(venue_id)
    if existing is not None and str(existing.id) != str(request_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Another request is already playing")
    try:
        item = await svc.set_now_playing(
            venue_id=venue_id,
            singer_id=None,
            song_id=None,
            request_id=request_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rotation item not found")
    return item


# ---------------------------------------------------------------------------
# COMPLETE (KJ/ADMIN only)
# ---------------------------------------------------------------------------

@router.post("/{request_id}/complete")
async def complete_song(
    venue_id: str,
    request_id: str,
    current: SingerUser = Depends(require_role(Role.KJ)),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    svc = HostRotationService(db)
    try:
        item = await svc.complete(venue_id, request_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Award loyalty points for performance
    singer_id = getattr(item, "singer_id", None)
    if singer_id:
        await award_performance_points(db, venue_id, str(singer_id), request_id)

    return _host_rotation_out(item)


# ---------------------------------------------------------------------------
# SKIP (KJ/ADMIN only)
# ---------------------------------------------------------------------------

@router.post("/{request_id}/skip")
async def skip_song(
    venue_id: str,
    request_id: str,
    current: SingerUser = Depends(require_role(Role.KJ)),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    svc = HostRotationService(db)
    try:
        item = await svc.skip(venue_id, request_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    try:
        await db.refresh(item, attribute_names=["singer", "song"])
    except Exception:
        pass
    return _host_rotation_out(item)


# ---------------------------------------------------------------------------
# REORDER (KJ/ADMIN only)
# ---------------------------------------------------------------------------

@router.put("/reorder", response_model=QueueAdminListOut)
async def reorder_queue(
    venue_id: str,
    body: QueueReorder,
    current: SingerUser = Depends(require_role(Role.KJ)),
    db: AsyncSession = Depends(get_db),
):
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    if not body.order or not isinstance(body.order, list):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Body must contain 'order': list of request IDs",
        )

    svc = HostRotationService(db)
    try:
        items = await svc.reorder(venue_id, body.order)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    out_items = [_host_rotation_out(item, position=idx + 1) for idx, item in enumerate(items)]
    return QueueAdminListOut(items=out_items, total=len(out_items), active_mode="round_robin")
