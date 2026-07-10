"""Singer CRUD router — venue-scoped with RBAC."""

from datetime import datetime, timezone, timedelta
import os
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, DateTime

from app.core.auth import get_current_user, SingerUser
from app.core.permissions import Role, has_role
from app.core.db import get_db
from app.models import Singer, QueueRequest, Song, CheckInSession, PointsLedger, SingerFavorite, SingerFollow, Payment, LeaderboardEntry, Consent, ShareEvent, SingerAchievement, Notification
from pydantic import BaseModel, Field
from app.core.points_service import add_points, get_points_leaderboard, get_achievements_for_singer
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
    SingerProfileStats,
    SingerMeUpdate,
    SingerQueueItem,
    SingerQueueOut,
    SingerQueueHistoryItem,
    SingerQueueHistoryOut,
    SingerQueueStatus,
    AchievementOut,
    PointsLedgerOut,
    BanRequest,
    BanResponse,
    DataExportOut,
    GDPRDeleteResponse,
)

class TipRequest(BaseModel):
    amount_cents: int = Field(..., gt=0)
    message: str | None = Field(None, max_length=200)

from app.core.queue_service import QueueService, ACTIVE_STATUSES

router = APIRouter()

DEFAULT_AVG_SONG_MS = 210_000  # 3.5 min fallback


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _singer_out(singer: Singer) -> SingerOut:
    """Map ORM Singer to Pydantic SingerOut with frontend-compatible aliases."""
    account_id_str = None
    if singer.account_id:
        account_id_str = str(singer.account_id)
    data = {
        "id": str(singer.id),
        "singer_id": str(singer.id),
        "venue_id": str(singer.venue_id),
        "stage_name": str(singer.stage_name),
        "name": str(singer.stage_name),
        "display_name": str(singer.stage_name),
        "first_name": singer.first_name,
        "last_name": singer.last_name,
        "display_real_name": None,
        "real_name": singer.real_name,
        "pronouns": singer.pronouns,
        "email": singer.email,
        "phone": singer.phone,
        "notes": singer.notes,
        "total_points": singer.total_points or 0,
        "loyalty_tier_id": str(singer.loyalty_tier_id) if singer.loyalty_tier_id else None,
        "tier": str(singer.loyalty_tier_id) if singer.loyalty_tier_id else "none",
        "total_visits": 0,
        "last_visit_date": str(singer.last_seen) if singer.last_seen else None,
        "last_seen": str(singer.last_seen) if singer.last_seen else None,
        "is_checked_in": False,
        "checked_in_at": None,
        "status": "active" if singer.deactivated_at is None else "banned",
        "bio": singer.bio,
        "avatar_url": singer.avatar_url,
        "social_links": singer.social_links,
        "account_id": account_id_str,
        "deactivated_at": str(singer.deactivated_at) if singer.deactivated_at else None,
        "created_at": str(singer.created_at),
        "updated_at": str(singer.updated_at) if singer.updated_at else None,
    }
    return SingerOut(**data)


async def _sync_singer_profile_to_account(db: AsyncSession, singer: Singer) -> None:
    """Push singer profile edits up to the linked global account.

    Keeps the account record in sync so other venues see consistent first/last
    name, pronouns, phone, bio, avatar, and social_links.
    """
    if not singer.account_id:
        return

    from app.models import Account

    account = (
        await db.execute(
            select(Account).where(
                Account.id == singer.account_id,
                Account.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return

    # Only copy fields that are part of the public profile; never copy venue-scoped notes.
    fields = ["first_name", "last_name", "real_name", "pronouns", "phone", "bio", "avatar_url", "social_links"]
    for field in fields:
        singer_value = getattr(singer, field, None)
        if singer_value is not None:
            setattr(account, field, singer_value)
    account.updated_at = _now_iso()
    db.add(account)
    await db.commit()


def _require_venue(venue_id: str, current: SingerUser) -> None:
    """Enforce that the current user's venue matches the URL venue, or admin/KJ."""
    if str(current.venue_id) == str(venue_id):
        return
    if current.role.lower() in ("admin", "kj"):
        return
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

    # Award check-in points
    from app.core.points_service import add_points
    await add_points(
        db, venue_id, current.id, 10,
        "Checked in", "checkin", new_session.id,
    )

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
    page: int = Query(1, ge=0),
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

    effective_page = page if page >= 1 else 1
    offset = (effective_page - 1) * per_page
    stmt = (
        select(Singer)
        .where(*filters)
        .order_by(Singer.last_seen.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    items = [_singer_out(row) for row in result.scalars().all()]

    # Batch-hydrate checked-in state: single query for all active sessions
    singer_ids = [item.id for item in items]
    if singer_ids:
        session_result = await db.execute(
            select(CheckInSession)
            .where(
                CheckInSession.singer_id.in_(singer_ids),
                CheckInSession.venue_id == venue_id,
                CheckInSession.expires_at > now,
            )
            .order_by(CheckInSession.checked_in_at.desc())
        )
        sessions_by_singer: dict[str, CheckInSession] = {}
        for sess in session_result.scalars().all():
            sid = str(sess.singer_id)
            if sid not in sessions_by_singer:
                sessions_by_singer[sid] = sess
    else:
        sessions_by_singer = {}

    for item in items:
        item.is_checked_in = True
        sess = sessions_by_singer.get(item.id)
        item.checked_in_at = str(sess.checked_in_at) if sess and sess.checked_in_at else None

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

    # Normalize stage_name before uniqueness check
    new_stage_name = update_data.get("stage_name")
    if new_stage_name is not None:
        new_stage_name = new_stage_name.strip()
        if not new_stage_name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="stage_name cannot be empty",
            )
        update_data["stage_name"] = new_stage_name

    # If stage_name is changing, ensure no other singer at this venue already uses it.
    if new_stage_name is not None and new_stage_name != singer.stage_name:
        existing = (
            await db.execute(
                select(Singer.id).where(
                    Singer.venue_id == venue_id,
                    Singer.stage_name == new_stage_name,
                    Singer.id != singer.id,
                    Singer.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Stage name '{new_stage_name}' is already taken at this venue",
            )

    for key, value in update_data.items():
        if value is not None:
            setattr(singer, key, value)

    singer.updated_at = _now_iso()
    await db.commit()
    await db.refresh(singer)

    # If this singer is linked to a global account, propagate profile changes upward
    if singer.account_id:
        await _sync_singer_profile_to_account(db, singer)

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
                func.extract('epoch', cast(QueueRequest.played_at, DateTime))
                - func.extract('epoch', cast(QueueRequest.requested_at, DateTime))
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


@router.get("/me/queue", response_model=SingerQueueOut)
async def get_my_queue(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /singers/me/queue — current position, ETA, song info."""
    _require_venue(venue_id, current)

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
    items: list[SingerQueueItem] = []
    for item, title, artist, dur in rows:
        pos = positions.get(str(item.id))
        eta = ((pos or 1) - 1) * avg_ms // 1000 if pos else None
        items.append(
            SingerQueueItem(
                request_id=str(item.id),
                position=pos or 0,
                status=str(item.status),
                song_title=title or "Unknown",
                song_artist=artist or "Unknown",
                song_duration_ms=dur,
                eta_seconds=eta,
                notes=str(item.notes) if item.notes else None,
                requested_at=str(item.requested_at),
            )
        )
    return SingerQueueOut(items=items, total=len(items))


@router.get("/me/queue/history", response_model=SingerQueueHistoryOut)
async def get_my_queue_history(
    venue_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /singers/me/queue/history — paginated past entries."""
    _require_venue(venue_id, current)

    filters = [
        QueueRequest.venue_id == venue_id,
        QueueRequest.singer_id == current.id,
        QueueRequest.deleted_at.is_(None),
        QueueRequest.status.in_(("completed", "skipped", "rejected")),
    ]
    total = (
        await db.execute(
            select(func.count())
            .select_from(QueueRequest)
            .where(*filters)
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    stmt = (
        select(QueueRequest, Song.title, Song.artist, Song.genre)
        .join(Song, Song.id == QueueRequest.song_id)
        .where(*filters)
        .order_by(QueueRequest.requested_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    rows = result.all()
    items = [
        SingerQueueHistoryItem(
            request_id=str(r.QueueRequest.id),
            song_title=r.title or "Unknown",
            song_artist=r.artist or "Unknown",
            genre=str(r.genre) if r.genre else None,
            status=str(r.QueueRequest.status),
            requested_at=str(r.QueueRequest.requested_at),
            played_at=str(r.QueueRequest.played_at) if r.QueueRequest.played_at else None,
            notes=str(r.QueueRequest.notes) if r.QueueRequest.notes else None,
        )
        for r in rows
    ]

    return SingerQueueHistoryOut(items=items, total=total, page=page, per_page=per_page)


@router.get("/me/queue/status", response_model=SingerQueueStatus)
async def get_my_queue_status(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /singers/me/queue/status: active/waiting/completed."""
    _require_venue(venue_id, current)

    avg_ms = await _avg_song_ms(db, venue_id)
    positions = await _compute_positions(db, venue_id)

    result = await db.execute(
        select(QueueRequest)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == current.id,
            QueueRequest.status.in_(list(ACTIVE_STATUSES)),
            QueueRequest.deleted_at.is_(None),
        )
        .order_by(QueueRequest.rotation_position)
        .limit(1)
    )
    item = result.scalar_one_or_none()

    if item is None:
        # Check if there are any completed/skipped requests today
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result2 = await db.execute(
            select(func.count())
            .select_from(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.singer_id == current.id,
                QueueRequest.status.in_(("completed", "skipped")),
                QueueRequest.deleted_at.is_(None),
                QueueRequest.requested_at >= today,
            )
        )
        count = result2.scalar_one()
        return SingerQueueStatus(
            status="completed" if count > 0 else "waiting",
            position=None,
            eta_seconds=None,
            request_id=None,
        )

    pos = positions.get(str(item.id))
    eta = ((pos or 1) - 1) * avg_ms // 1000 if pos else None
    return SingerQueueStatus(
        status="active",
        position=pos,
        eta_seconds=eta,
        request_id=str(item.id),
    )


_AVATAR_UPLOAD_DIR = os.environ.get(
    "AVATAR_UPLOAD_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "avatars"),
)
_MAX_AVATAR_BYTES = 5 * 1024 * 1024
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.put("/me", response_model=SingerOut)
async def update_me(
    venue_id: str,
    body: SingerMeUpdate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update own singer profile (self-service, narrow scope)."""
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
    allowed = {"stage_name", "real_name", "pronouns", "phone", "bio", "social_links"}
    for key, value in update_data.items():
        if key in allowed:
            if value is not None:
                setattr(singer, key, value)

    singer.updated_at = _now_iso()
    await db.commit()
    await db.refresh(singer)
    return _singer_out(singer)


@router.post("/me/avatar", response_model=SingerOut)
async def upload_avatar(
    venue_id: str,
    file: UploadFile = File(...),
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload singer avatar image (self-service). Max 5MB. JPEG/PNG/WebP/GIF only."""
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

    content_type = file.content_type or ""
    if content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Invalid image type: {content_type}. Allowed: JPEG, PNG, WebP, GIF",
        )

    contents = await file.read()
    if len(contents) > _MAX_AVATAR_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Avatar too large. Max {_MAX_AVATAR_BYTES // (1024 * 1024)}MB allowed.",
        )

    os.makedirs(_AVATAR_UPLOAD_DIR, exist_ok=True)
    ext = content_type.split("/")[-1].replace("jpeg", "jpg")
    filename = f"{singer.id}_{_uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(_AVATAR_UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    singer.avatar_url = f"/uploads/avatars/{filename}"
    singer.updated_at = _now_iso()
    await db.commit()
    await db.refresh(singer)
    return _singer_out(singer)


@router.get("/me/stats", response_model=SingerProfileStats)
async def get_me_stats(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return comprehensive self-service stats for the authenticated singer."""
    _require_venue(venue_id, current)

    # Songs sung
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

    # Total check-ins (count of sessions ever created)
    checkins_result = await db.execute(
        select(func.count())
        .select_from(CheckInSession)
        .where(
            CheckInSession.venue_id == venue_id,
            CheckInSession.singer_id == current.id,
        )
    )
    total_checkins = checkins_result.scalar_one() or 0

    # Avg wait
    avg_wait_result = await db.execute(
        select(
            func.avg(
                func.extract('epoch', cast(QueueRequest.played_at, DateTime))
                - func.extract('epoch', cast(QueueRequest.requested_at, DateTime))
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

    # Favorite genre
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

    # Top songs
    top_songs_result = await db.execute(
        select(Song.title, Song.artist, func.count())
        .join(QueueRequest, QueueRequest.song_id == Song.id)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == current.id,
            QueueRequest.status.in_(("completed", "now_playing")),
            QueueRequest.deleted_at.is_(None),
        )
        .group_by(Song.id)
        .order_by(func.count().desc())
        .limit(5)
    )
    top_songs = [
        {"title": str(row[0]), "artist": str(row[1]), "count": row[2]}
        for row in top_songs_result.all()
    ]

    # Total points from singer record
    singer = (
        await db.execute(
            select(Singer).where(Singer.id == current.id, Singer.venue_id == venue_id)
        )
    ).scalar_one_or_none()
    total_points = singer.total_points if singer else 0

    return SingerProfileStats(
        songs_sung=songs_sung,
        total_checkins=total_checkins,
        total_points=total_points,
        top_songs=top_songs,
        avg_wait_min=avg_wait_min,
        favorite_genre=favorite_genre,
    )


# ---------------------------------------------------------------------------
# GDPR Compliance Endpoints
# ---------------------------------------------------------------------------

@router.get("/me/export", response_model=DataExportOut)
async def export_personal_data(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GET /me/export — GDPR Article 20 data portability.

    Returns a structured JSON export of all personal data the system holds
    about the authenticated singer, including profile, queue history,
    favorites, follows, payments, points, achievements, and consents.
    """
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

    # Profile
    profile = {
        "id": singer.id,
        "venue_id": singer.venue_id,
        "stage_name": singer.stage_name,
        "real_name": singer.real_name,
        "pronouns": singer.pronouns,
        "email": singer.email,
        "phone": singer.phone,
        "bio": singer.bio,
        "avatar_url": singer.avatar_url,
        "social_links": singer.social_links,
        "role": singer.role,
        "total_points": singer.total_points,
        "loyalty_tier_id": singer.loyalty_tier_id,
        "last_seen": singer.last_seen,
        "deactivated_at": singer.deactivated_at,
        "gdpr_erased_at": singer.gdpr_erased_at,
        "created_at": singer.created_at,
        "updated_at": singer.updated_at,
    }

    # Queue history
    qr_result = await db.execute(
        select(
            QueueRequest.id,
            Song.title,
            Song.artist,
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
    queue_history = [
        {
            "request_id": str(r.id),
            "song_title": r.title,
            "song_artist": r.artist,
            "status": r.status,
            "requested_at": r.requested_at,
            "played_at": r.played_at,
            "notes": r.notes,
        }
        for r in qr_result.all()
    ]

    # Favorites
    fav_result = await db.execute(
        select(SingerFavorite).where(
            SingerFavorite.venue_id == venue_id,
            SingerFavorite.singer_id == current.id,
        )
    )
    favorites = [
        {"favorite_id": f.id, "song_id": f.song_id, "created_at": f.created_at}
        for f in fav_result.scalars().all()
    ]

    # Follows
    follow_result = await db.execute(
        select(SingerFollow).where(
            SingerFollow.venue_id == venue_id,
            SingerFollow.follower_id == current.id,
            SingerFollow.deleted_at.is_(None),
        )
    )
    follows = [
        {"follow_id": f.id, "followee_id": f.followee_id, "created_at": f.created_at}
        for f in follow_result.scalars().all()
    ]

    # Payments
    pay_result = await db.execute(
        select(Payment).where(
            Payment.venue_id == venue_id,
            Payment.singer_id == current.id,
            Payment.deleted_at.is_(None),
        )
        .order_by(Payment.created_at.desc())
    )
    payments = [
        {
            "payment_id": p.id,
            "amount_cents": p.amount_cents,
            "currency": p.currency,
            "payment_type": p.payment_type,
            "status": p.status,
            "message": p.message,
            "stripe_payment_intent_id": p.stripe_payment_intent_id,
            "reference_type": p.reference_type,
            "reference_id": p.reference_id,
            "refunded_at": p.refunded_at,
            "refund_amount_cents": p.refund_amount_cents,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
        }
        for p in pay_result.scalars().all()
    ]

    # Points ledger
    points_result = await db.execute(
        select(PointsLedger).where(
            PointsLedger.venue_id == venue_id,
            PointsLedger.singer_id == current.id,
        )
        .order_by(PointsLedger.created_at.desc())
    )
    points_ledger = [
        {
            "entry_id": p.id,
            "amount": p.amount,
            "reason": p.reason,
            "reference_type": p.reference_type,
            "reference_id": p.reference_id,
            "created_at": p.created_at,
        }
        for p in points_result.scalars().all()
    ]

    # Leaderboard entries
    lb_result = await db.execute(
        select(LeaderboardEntry).where(
            LeaderboardEntry.venue_id == venue_id,
            LeaderboardEntry.singer_id == current.id,
        )
        .order_by(LeaderboardEntry.updated_at.desc())
    )
    leaderboard_entries = [
        {
            "entry_id": e.id,
            "leaderboard_id": e.leaderboard_id,
            "score": e.score,
            "rank": e.rank,
            "updated_at": e.updated_at,
        }
        for e in lb_result.scalars().all()
    ]

    # Achievements (SingerAchievement)
    ach_result = await db.execute(
        select(SingerAchievement).where(
            SingerAchievement.venue_id == venue_id,
            SingerAchievement.singer_id == current.id,
        )
        .order_by(SingerAchievement.unlocked_at.desc())
    )
    achievements = [
        {
            "achievement_id": a.id,
            "key": a.achievement_key,
            "unlocked_at": a.unlocked_at,
            "progress": a.progress,
            "created_at": a.created_at,
        }
        for a in ach_result.scalars().all()
    ]

    # Check-in sessions
    checkin_result = await db.execute(
        select(CheckInSession).where(
            CheckInSession.venue_id == venue_id,
            CheckInSession.singer_id == current.id,
        )
        .order_by(CheckInSession.checked_in_at.desc())
    )
    check_in_sessions = [
        {
            "session_id": c.id,
            "checked_in_at": c.checked_in_at,
            "expires_at": c.expires_at,
            "table_number": c.table_number,
            "created_at": c.created_at,
        }
        for c in checkin_result.scalars().all()
    ]

    # Consents
    consent_result = await db.execute(
        select(Consent).where(
            Consent.venue_id == venue_id,
            Consent.singer_id == current.id,
        )
    )
    consents = [
        {
            "consent_id": c.id,
            "consent_type": c.consent_type,
            "granted": bool(c.granted),
            "granted_at": c.granted_at,
            "ip_address": c.ip_address,
            "metadata_json": c.metadata_json,
            "created_at": c.created_at,
        }
        for c in consent_result.scalars().all()
    ]

    # Share events
    share_result = await db.execute(
        select(ShareEvent).where(
            ShareEvent.venue_id == venue_id,
            ShareEvent.singer_id == current.id,
        )
        .order_by(ShareEvent.created_at.desc())
    )
    share_events = [
        {
            "share_id": s.id,
            "platform": s.platform,
            "url": s.url,
            "content_type": s.content_type,
            "created_at": s.created_at,
        }
        for s in share_result.scalars().all()
    ]

    return DataExportOut(
        singer_id=singer.id,
        venue_id=singer.venue_id,
        exported_at=now,
        profile=profile,
        queue_history=queue_history,
        favorites=favorites,
        follows=follows,
        payments=payments,
        points_ledger=points_ledger,
        leaderboard_entries=leaderboard_entries,
        achievements=achievements,
        check_in_sessions=check_in_sessions,
        consents=consents,
        share_events=share_events,
    )


@router.delete("/me", response_model=GDPRDeleteResponse)
async def delete_me(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """DELETE /me — GDPR Article 17 right to erasure.

    Soft-deletes the singer and sets gdpr_erased_at.  The system retains
    non-identifiable transactional data (e.g. aggregate analytics) but marks
    personal records so downstream processing can exclude them.
    """
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
    singer.gdpr_erased_at = now
    singer.deactivated_at = now
    singer.email = None
    singer.phone = None
    singer.social_links = None
    singer.bio = None
    singer.avatar_url = None
    singer.real_name = None
    singer.notes = None
    await db.commit()

    # Best-effort audit log
    try:
        from app.core.audit_service import log_audit
        await log_audit(
            action="gdpr_erasure",
            user_id=str(singer.id),
            venue_id=venue_id,
            result="success",
            resource_type="singer",
            resource_id=str(singer.id),
        )
    except Exception:
        pass

    return GDPRDeleteResponse(
        singer_id=str(singer.id),
        status="erasure_initiated",
        erased_at=now,
        retention_days=30,
        message="Your personal data has been marked for erasure and will be permanently deleted within 30 days.",
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
    page: int = Query(1, ge=0),
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

    effective_page = page if page >= 1 else 1
    offset = (effective_page - 1) * per_page
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


@router.get("/me", response_model=SingerOut)
async def get_me(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the authenticated singer's own profile in this venue."""
    _require_venue(venue_id, current)

    singer = (
        await db.execute(
            select(Singer)
            .where(
                Singer.id == current.id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    return _singer_out(singer)


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
            select(Singer).where(
                Singer.id == singer_id,
                Singer.venue_id == venue_id,
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    # Hard delete: permanently remove singer from current venue.
    # Related rows are left as-is (DB may cascade or orphan; avoids table-guessing).
    await db.delete(singer)
    await db.commit()
    return None


# --- Ban (venue-scoped) -------------------------------------------------------


@router.post("/{singer_id}/ban", response_model=BanResponse)
async def ban_singer(
    venue_id: str,
    singer_id: str,
    body: BanRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ban a singer at this venue (admin or kj only). Sets deactivated_at."""
    from app.schemas import BanRequest, BanResponse
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

    now = _now_iso()
    singer.deactivated_at = now
    singer.updated_at = now
    await db.commit()
    await db.refresh(singer)

    return BanResponse(
        singer_id=str(singer.id),
        status="banned",
        banned_at=now,
        reason=body.reason,
    )


# ---------------------------------------------------------------------------
# Achievements
# ---------------------------------------------------------------------------

@router.get("/me/achievements", response_model=list[AchievementOut])
async def list_achievements(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current singer's achievements with progress and unlock state."""
    _require_venue(venue_id, current)
    raw = await get_achievements_for_singer(db, venue_id, current.id)
    return [
        AchievementOut(
            achievement_key=r["achievement_key"],
            name=r["name"],
            description=r["description"],
            icon=r.get("icon"),
            progress=r["progress"],
            target=r["target"],
            unlocked_at=r["unlocked_at"],
            unlocked=r["unlocked"],
        )
        for r in raw
    ]


# ---------------------------------------------------------------------------
# Points history
# ---------------------------------------------------------------------------

@router.get("/me/points", response_model=PaginatedResponse[PointsLedgerOut])
async def get_my_points(
    venue_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated points ledger for the current singer."""
    _require_venue(venue_id, current)

    from sqlalchemy import func
    total_result = await db.execute(
        select(func.count())
        .select_from(PointsLedger)
        .where(
            PointsLedger.venue_id == venue_id,
            PointsLedger.singer_id == current.id,
        )
    )
    total = total_result.scalar_one()

    offset = (page - 1) * per_page
    result = await db.execute(
        select(PointsLedger)
        .where(
            PointsLedger.venue_id == venue_id,
            PointsLedger.singer_id == current.id,
        )
        .order_by(PointsLedger.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    items = result.scalars().all()
    out = [
        PointsLedgerOut(
            id=str(row.id),
            amount=int(row.amount) if row.amount is not None else 0,
            reason=str(row.reason) if row.reason is not None else None,
            reference_type=str(row.reference_type) if row.reference_type is not None else None,
            reference_id=str(row.reference_id) if row.reference_id is not None else None,
            created_at=str(row.created_at) if row.created_at is not None else "",
        )
        for row in items
    ]
    return PaginatedResponse(items=out, total=total, page=page, per_page=per_page)


# ---------------------------------------------------------------------------
# Tip (points purchase)
# ---------------------------------------------------------------------------

@router.post("/{singer_id}/tip", status_code=status.HTTP_204_NO_CONTENT)
async def tip_singer(
    venue_id: str,
    singer_id: str,
    body: TipRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tip another singer — awards points equal to tip amount in cents."""
    _require_venue(venue_id, current)

    target = (
        await db.execute(
            select(Singer).where(
                Singer.id == singer_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    await add_points(
        db, venue_id, singer_id, body.amount_cents,
        body.message or "Tip received", "tip", str(current.id),
    )
    return None
