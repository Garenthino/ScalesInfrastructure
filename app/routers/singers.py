"""Singer CRUD router — venue-scoped with RBAC."""

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, SingerUser
from app.core.permissions import Role, has_role
from app.core.db import get_db
from app.models import Singer, QueueRequest, Song, CheckInSession
from app.schemas import (
    SingerCreate,
    SingerUpdate,
    SingerOut,
    PaginatedResponse,
    CheckInRequest,
    CheckInResponse,
    SingerHistoryOut,
    SingerHistoryItem,
    SingerPortalStats,
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
# Singer Self-Service Portal
# ---------------------------------------------------------------------------


@router.post("/checkin", response_model=SingerOut)
async def check_in(
    venue_id: str,
    body: CheckInRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark singer as present at the venue (creates check-in session, updates last_seen)."""
    _require_venue(venue_id, current)

    singer = (
        await db.execute(
            select(Singer).where(
                Singer.id == current.id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    now = _now_iso()
    expire_before = (
        datetime.now(timezone.utc) - timedelta(hours=4)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Expire any existing active sessions for this singer at this venue
    existing_sessions = (
        await db.execute(
            select(CheckInSession).where(
                CheckInSession.singer_id == current.id,
                CheckInSession.venue_id == venue_id,
                CheckInSession.expires_at > expire_before,
            )
        )
    ).scalars().all()

    for sess in existing_sessions:
        sess.expires_at = now

    # Create new session with 4-hour default timeout
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=4)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    new_session = CheckInSession(
        singer_id=current.id,
        venue_id=venue_id,
        checked_in_at=now,
        expires_at=expires_at,
        table_number=body.table_number,
    )
    db.add(new_session)

    singer.last_seen = now
    singer.updated_at = now
    await db.commit()
    await db.refresh(singer)

    # Hydrate is_checked_in / checked_in_at on the response
    out = _singer_out(singer)
    out.is_checked_in = True
    out.checked_in_at = now
    return out


@router.post("/checkout", response_model=SingerOut)
async def check_out(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """End the singer's active check-in session at this venue."""
    _require_venue(venue_id, current)

    singer = (
        await db.execute(
            select(Singer).where(
                Singer.id == current.id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    now = _now_iso()

    # Expire all active sessions for this singer at this venue
    active_sessions = (
        await db.execute(
            select(CheckInSession).where(
                CheckInSession.singer_id == current.id,
                CheckInSession.venue_id == venue_id,
                CheckInSession.expires_at > now,
            )
        )
    ).scalars().all()

    for sess in active_sessions:
        sess.expires_at = now

    singer.updated_at = now
    await db.commit()
    await db.refresh(singer)

    out = _singer_out(singer)
    out.is_checked_in = False
    return out


@router.get("/checked-in", response_model=PaginatedResponse[SingerOut])
async def list_checked_in_singers(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List singers currently checked in at this venue (web portal / KJ view)."""
    _require_venue(venue_id, current)
    if not has_role(current.role, Role.KJ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Admin or KJ access required",
        )

    now = _now_iso()

    # Subquery: singer IDs with active check-in sessions
    subq = (
        select(CheckInSession.singer_id)
        .where(
            CheckInSession.venue_id == venue_id,
            CheckInSession.expires_at > now,
        )
        .distinct()
    )

    filters = [
        Singer.id.in_(subq),
        Singer.venue_id == venue_id,
        Singer.deleted_at.is_(None),
        Singer.deactivated_at.is_(None),
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
        .order_by(Singer.last_seen.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    items = [_singer_out(row) for row in result.scalars().all()]

    # Hydrate checked-in state for each by looking up their CheckInSession
    for item in items:
        item.is_checked_in = True
        # Fetch latest active session for this singer to get checked_in_at
        session_result = await db.execute(
            select(CheckInSession)
            .where(
                CheckInSession.singer_id == item.id,
                CheckInSession.venue_id == venue_id,
                CheckInSession.expires_at > now,
            )
            .order_by(CheckInSession.checked_in_at.desc())
            .limit(1)
        )
        session_row = session_result.scalar_one_or_none()
        if session_row:
            item.checked_in_at = session_row.checked_in_at
        else:
            item.checked_in_at = None

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/profile", response_model=SingerOut)
async def get_profile(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get own singer profile."""
    _require_venue(venue_id, current)

    singer = (
        await db.execute(
            select(Singer).where(
                Singer.id == current.id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    return _singer_out(singer)


@router.put("/profile", response_model=SingerOut)
async def update_profile(
    venue_id: str,
    body: SingerUpdate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update own singer profile."""
    _require_venue(venue_id, current)

    singer = (
        await db.execute(
            select(Singer).where(
                Singer.id == current.id,
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


@router.get("/history", response_model=SingerHistoryOut)
async def get_history(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return queue request history for the authenticated singer, with song titles."""
    _require_venue(venue_id, current)

    stmt = (
        select(
            QueueRequest.id,
            Song.title,
            Song.artist,
            Song.genre,
            QueueRequest.status,
            QueueRequest.requested_at,
            QueueRequest.played_at,
            QueueRequest.notes,
        )
        .join(Song, Song.id == QueueRequest.song_id)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == current.id,
            QueueRequest.deleted_at.is_(None),
        )
        .order_by(QueueRequest.requested_at.desc())
    )

    result = await db.execute(stmt)
    rows = result.all()

    items = [
        SingerHistoryItem(
            request_id=str(r.id),
            song_title=str(r.title) if r.title else "Unknown",
            song_artist=str(r.artist) if r.artist else "Unknown",
            genre=str(r.genre) if r.genre else None,
            status=str(r.status),
            requested_at=str(r.requested_at),
            played_at=str(r.played_at) if r.played_at else None,
            notes=str(r.notes) if r.notes else None,
        )
        for r in rows
    ]

    return SingerHistoryOut(items=items, total=len(items))


@router.get("/stats", response_model=SingerPortalStats)
async def get_stats(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return singer portal stats: songs sung, avg wait time, favorite genre."""
    _require_venue(venue_id, current)

    # Songs sung: completed queue requests
    songs_sung_result = await db.execute(
        select(func.count())
        .select_from(QueueRequest)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == current.id,
            QueueRequest.status == "completed",
            QueueRequest.deleted_at.is_(None),
        )
    )
    songs_sung = songs_sung_result.scalar_one() or 0

    # Avg wait (completed requests with played_at)
    avg_wait_result = await db.execute(
        select(
            func.avg(
                func.strftime("%s", QueueRequest.played_at)
                - func.strftime("%s", QueueRequest.requested_at)
            )
        )
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == current.id,
            QueueRequest.status == "completed",
            QueueRequest.played_at.isnot(None),
            QueueRequest.deleted_at.is_(None),
        )
    )
    avg_wait_sec = avg_wait_result.scalar_one()
    avg_wait_min = round(avg_wait_sec / 60.0, 2) if avg_wait_sec is not None else None

    # Favorite genre: mode of Song.genre for completed requests
    fav_genre_result = await db.execute(
        select(Song.genre, func.count())
        .join(QueueRequest, QueueRequest.song_id == Song.id)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == current.id,
            QueueRequest.status == "completed",
            QueueRequest.deleted_at.is_(None),
        )
        .group_by(Song.genre)
        .order_by(func.count().desc())
        .limit(1)
    )
    fav_genre_row = fav_genre_result.first()
    favorite_genre = str(fav_genre_row[0]) if fav_genre_row and fav_genre_row[0] else None

    return SingerPortalStats(
        songs_sung=songs_sung,
        avg_wait_min=avg_wait_min,
        favorite_genre=favorite_genre,
    )


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete own account (sets deactivated_at)."""
    _require_venue(venue_id, current)

    singer = (
        await db.execute(
            select(Singer).where(
                Singer.id == current.id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    singer.deactivated_at = _now_iso()
    await db.commit()
    return None


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
        Singer.deactivated_at.is_(None),
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
