"""KJ-facing queue admin router.

All endpoints require kj or admin role.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin, venue_match
from app.core.db import get_db
from app.core.queue_service import QueueService, ACTIVE_STATUSES
from app.schemas import QueueAdminListOut, QueueItemOut, QueueRejectRequest, QueueReorder, SongOut, SingerOut
from app.models import QueueRequest

router = APIRouter()


def _song_out_model(song) -> SongOut | None:
    if song is None:
        return None
    data = {k: getattr(song, k) for k in song.__table__.columns.keys()}
    data["is_active"] = bool(data.get("is_active", 1))
    data["is_available"] = bool(data.get("is_available", 1))
    return SongOut(**data)


def _singer_out_model(singer) -> SingerOut | None:
    if singer is None:
        return None
    data = {k: getattr(singer, k) for k in singer.__table__.columns.keys()}
    # Frontend-compatible aliases (must match SingerOut expectations)
    data["singer_id"] = data["id"]
    data["name"] = data.get("stage_name", "")
    data["display_name"] = data.get("stage_name", "")
    data["tier"] = data.get("loyalty_tier_id", "none") or "none"
    data["total_visits"] = 0
    data["last_visit_date"] = data.get("last_seen", None)
    data["status"] = "banned" if data.get("deactivated_at") else "active"
    return SingerOut(**data)


def _queue_item_out(item: QueueRequest, position: int | None = None) -> QueueItemOut:
    song = getattr(item, "song", None)
    singer = getattr(item, "singer", None)
    return QueueItemOut(
        request_id=str(item.id),
        venue_id=str(item.venue_id),
        position=position if position is not None else int(item.rotation_position) if item.rotation_position is not None else None,
        status=str(item.status),
        song=_song_out_model(song),
        singer=_singer_out_model(singer),
        notes=str(item.notes) if item.notes is not None else None,
        reject_reason=str(item.reject_reason) if item.reject_reason is not None else None,
        requested_at=str(item.requested_at),
        updated_at=str(item.updated_at) if item.updated_at is not None else None,
        played_at=str(item.played_at) if item.played_at is not None else None,
    )


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------

@router.get("", response_model=QueueAdminListOut)
async def get_admin_queue(
    venue_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    svc = QueueService(db)
    items = await svc.get_active_queue(venue_id, mode="round_robin", include_details=True)
    out_items = [_queue_item_out(item, position=idx + 1) for idx, item in enumerate(items)]
    return QueueAdminListOut(
        items=out_items,
        total=len(out_items),
        active_mode="round_robin",
    )


# ---------------------------------------------------------------------------
# APPROVE
# ---------------------------------------------------------------------------

@router.post("/{request_id}/approve", response_model=QueueItemOut)
async def approve_request(
    venue_id: str,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    svc = QueueService(db)
    try:
        item = await svc.approve(venue_id, request_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _queue_item_out(item)


# ---------------------------------------------------------------------------
# REJECT
# ---------------------------------------------------------------------------

@router.post("/{request_id}/reject", response_model=QueueItemOut)
async def reject_request(
    venue_id: str,
    request_id: str,
    body: QueueRejectRequest,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    svc = QueueService(db)
    try:
        item = await svc.reject(venue_id, request_id, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _queue_item_out(item)


# ---------------------------------------------------------------------------
# COMPLETE
# ---------------------------------------------------------------------------

@router.post("/{request_id}/complete", response_model=QueueItemOut)
async def complete_request(
    venue_id: str,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    svc = QueueService(db)
    try:
        item = await svc.complete(venue_id, request_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _queue_item_out(item)


# ---------------------------------------------------------------------------
# REORDER
# ---------------------------------------------------------------------------

@router.post("/reorder", response_model=QueueAdminListOut)
async def reorder_queue(
    venue_id: str,
    body: QueueReorder,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
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


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------

@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_request(
    venue_id: str,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    svc = QueueService(db)
    try:
        await svc.remove(venue_id, request_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return None
