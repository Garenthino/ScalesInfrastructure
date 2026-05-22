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
from app.models import QueueRequest, Singer, Song, Venue
from app.schemas import QueueRequestCreate, QueueRequestUpdate, QueueReorder, QueueAdminListOut

router = APIRouter()

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


def _singer_out(singer) -> dict[str, Any]:
    if singer is None:
        return {"id": None, "stage_name": "Unknown", "venue_id": None, "total_points": 0, "loyalty_tier_id": None, "created_at": None, "updated_at": None}
    data = {k: getattr(singer, k) for k in singer.__table__.columns.keys()}
    return {
        "id": data["id"],
        "venue_id": data["venue_id"],
        "stage_name": data["stage_name"],
        "real_name": data.get("real_name"),
        "pronouns": data.get("pronouns"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "notes": data.get("notes"),
        "total_points": data.get("total_points", 0),
        "loyalty_tier_id": data.get("loyalty_tier_id"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def _queue_request_out(item: QueueRequest, position: int | None = None) -> dict[str, Any]:
    song = getattr(item, "song", None)
    singer = getattr(item, "singer", None)
    return {
        "request_id": str(item.id),
        "position": position if position is not None else int(item.rotation_position) if item.rotation_position is not None else None,
        "status": str(item.status),
        "song": _song_out(song),
        "singer": _singer_out(singer),
        "submitted_at": str(item.requested_at),
        "estimated_start": None,
        "notes": str(item.notes) if item.notes is not None else None,
        "dedication": None,
    }


def _queue_item_out(item: QueueRequest, position: int | None = None) -> dict[str, Any]:
    song = getattr(item, "song", None)
    singer = getattr(item, "singer", None)
    return {
        "request_id": str(item.id),
        "venue_id": str(item.venue_id),
        "position": position if position is not None else int(item.rotation_position) if item.rotation_position is not None else None,
        "status": str(item.status),
        "song": _song_out(song),
        "singer": _singer_out(singer),
        "notes": str(item.notes) if item.notes is not None else None,
        "reject_reason": str(item.reject_reason) if item.reject_reason is not None else None,
        "requested_at": str(item.requested_at),
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

    svc = QueueService(db)
    items = await svc.get_active_queue(venue_id, mode="round_robin", include_details=True)

    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = items[start:end]

    out = [_queue_request_out(item, position=idx + 1 + start) for idx, item in enumerate(paginated)]
    return {"items": out, "total": total, "page": page, "per_page": per_page}


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
        rotation_position=tail + 1,
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

    svc = QueueService(db)
    try:
        item = await svc.start(venue_id, request_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    try:
        await db.refresh(item, attribute_names=["singer", "song"])
    except Exception:
        pass
    return _queue_item_out(item)


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

    svc = QueueService(db)
    try:
        item = await svc.complete(venue_id, request_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    try:
        await db.refresh(item, attribute_names=["singer", "song"])
    except Exception:
        pass
    return _queue_item_out(item)


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

    svc = QueueService(db)
    try:
        item = await svc.skip(venue_id, request_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    try:
        await db.refresh(item, attribute_names=["singer", "song"])
    except Exception:
        pass
    return _queue_item_out(item)


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

    svc = QueueService(db)
    try:
        items = await svc.reorder(venue_id, body.order)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    out_items = [_queue_item_out(item, position=idx + 1) for idx, item in enumerate(items)]
    return QueueAdminListOut(items=out_items, total=len(out_items), active_mode="round_robin")
