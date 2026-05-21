"""Singer CRUD router — venue-scoped with RBAC."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, SingerUser
from app.core.permissions import Role, has_role
from app.core.db import get_db
from app.models import Singer
from app.schemas import (
    SingerCreate,
    SingerUpdate,
    SingerOut,
    PaginatedResponse,
    CheckInRequest,
    CheckInResponse,
)

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _singer_out(singer: Singer) -> SingerOut:
    """Map ORM Singer to Pydantic SingerOut."""
    data = {
        k: getattr(singer, k, None)
        for k in Singer.__table__.columns.keys()
        if k != "password_hash"
    }
    return SingerOut(**data)


def _require_venue(venue_id: str, current: SingerUser) -> None:
    """Enforce that the current user's venue matches the URL venue."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )


# ---------------------------------------------------------------------------
# Sprint 0 stubs (static routes first so they match before dynamic params)
# ---------------------------------------------------------------------------


@router.post("/checkin", response_model=CheckInResponse)
async def check_in(venue_id: str, body: CheckInRequest):
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented in Sprint 0",
    )


@router.get("/profile", response_model=SingerOut)
async def get_profile():
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented in Sprint 0",
    )


@router.put("/profile", response_model=SingerOut)
async def update_profile(body: SingerUpdate):
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented in Sprint 0",
    )


@router.get("/history")
async def get_history():
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented in Sprint 0",
    )


@router.get("/stats")
async def get_stats():
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented in Sprint 0",
    )


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account():
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="Not implemented in Sprint 0",
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

# --- List (venue-scoped) ----------------------------------------------------


@router.get("", response_model=PaginatedResponse[SingerOut])
async def list_singers(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List singers for the current user's venue (soft-deleted excluded)."""
    _require_venue(venue_id, current)

    filters = [
        Singer.venue_id == venue_id,
        Singer.deleted_at.is_(None),
    ]

    total = (
        await db.execute(
            select(func.count()).select_from(Singer).where(*filters)
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    stmt = (
        select(Singer)
        .where(*filters)
        .order_by(Singer.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    items = [_singer_out(row) for row in result.scalars().all()]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


# --- Create -----------------------------------------------------------------


@router.post("", response_model=SingerOut, status_code=status.HTTP_201_CREATED)
async def create_singer(
    venue_id: str,
    body: SingerCreate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new singer in the current venue (admin or kj only)."""
    _require_venue(venue_id, current)
    if not has_role(current.role, Role.KJ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Admin or KJ access required",
        )

    singer = Singer(
        venue_id=venue_id,
        stage_name=body.stage_name,
        real_name=body.real_name,
        pronouns=body.pronouns,
        email=body.email,
        phone=body.phone,
        notes=body.notes,
    )
    db.add(singer)
    await db.commit()
    await db.refresh(singer)
    return _singer_out(singer)


# --- Get --------------------------------------------------------------------


@router.get("/{singer_id}", response_model=SingerOut)
async def get_singer(
    venue_id: str,
    singer_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single singer in the current venue."""
    _require_venue(venue_id, current)

    singer = (
        await db.execute(
            select(Singer)
            .where(
                Singer.id == singer_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    return _singer_out(singer)


# --- Update -----------------------------------------------------------------


@router.put("/{singer_id}", response_model=SingerOut)
async def update_singer(
    venue_id: str,
    singer_id: str,
    body: SingerUpdate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update singer profile. Self-update or admin/kj only."""
    _require_venue(venue_id, current)
    is_admin_or_kj = has_role(current.role, Role.KJ)

    if not is_admin_or_kj and str(current.id) != str(singer_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Cannot update another singer's profile",
        )

    singer = (
        await db.execute(
            select(Singer)
            .where(
                Singer.id == singer_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(singer, key, value)

    singer.updated_at = _now_iso()
    await db.commit()
    await db.refresh(singer)
    return _singer_out(singer)


# --- Delete (soft) ----------------------------------------------------------


@router.delete("/{singer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_singer(
    venue_id: str,
    singer_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a singer (admin or kj only)."""
    _require_venue(venue_id, current)
    if not has_role(current.role, Role.KJ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Admin or KJ access required",
        )

    singer = (
        await db.execute(
            select(Singer)
            .where(
                Singer.id == singer_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    singer.deleted_at = _now_iso()
    await db.commit()
    return None
