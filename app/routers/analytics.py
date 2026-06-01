"""Analytics router — read-only venue and singer performance statistics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, DateTime

from app.core.auth import get_current_user, SingerUser
from app.core.permissions import Role, has_role
from app.core.db import get_db
from app.models import Venue, Song, Singer, QueueRequest
from app.schemas import (
    VenueOverviewOut,
    SingerLeaderboardEntry,
    SongPopularityEntry,
    HourlyBreakdownItem,
    SingerStatsOut,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------

def _require_venue_access(current: SingerUser, venue_id: str) -> None:
    """Enforce that current user can access venue_id."""
    if not has_role(current.role, Role.ADMIN) and str(current.venue_id) != str(venue_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )


async def _require_singer_access(
    current: SingerUser,
    singer_id: str,
    db: AsyncSession,
) -> Singer:
    """Load singer and enforce that current user can read their stats."""
    singer = (
        await db.execute(
            select(Singer).where(
                Singer.id == singer_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    # Admin can read any singer
    if has_role(current.role, Role.ADMIN):
        return singer

    # Singer can read their own stats
    if str(current.id) == str(singer_id):
        return singer

    # KJ / venue_admin can read any singer at their venue
    if has_role(current.role, Role.KJ) and str(current.venue_id) == str(singer.venue_id):
        return singer

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Singer access denied",
    )

# ---------------------------------------------------------------------------
# Venue overview
# ---------------------------------------------------------------------------

@router.get("/venue/{venue_id}/overview", response_model=VenueOverviewOut)
async def get_venue_overview(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return high-level venue performance statistics."""
    _require_venue_access(current, venue_id)

    # Ensure venue exists
    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    # total_songs_played: completed queue requests at this venue
    total_songs_played = (
        await db.execute(
            select(func.count()).select_from(QueueRequest).where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status == "completed",
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    # total_singers: active singers at this venue
    total_singers = (
        await db.execute(
            select(func.count()).select_from(Singer).where(
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    # avg_queue_wait_seconds: average time between requested_at and played_at
    # NOTE: client-side computation for SQLite compat; PostgreSQL could use EXTRACT(epoch)
    wait_rows = (
        await db.execute(
            select(
                QueueRequest.requested_at,
                QueueRequest.played_at,
            )
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status == "completed",
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).all()

    avg_wait = None
    waits = []
    for req_at, play_at in wait_rows:
        if req_at and play_at:
            try:
                dt_req = datetime.fromisoformat(req_at.replace("Z", "+00:00"))
                dt_play = datetime.fromisoformat(play_at.replace("Z", "+00:00"))
                waits.append((dt_play - dt_req).total_seconds())
            except Exception:
                pass
    if waits:
        avg_wait = round(sum(waits) / len(waits), 2)

    # busiest_day and busiest_hour via SQL aggregation (cross-DB string slicing on ISO 8601)
    day_rows = (
        await db.execute(
            select(
                func.substr(QueueRequest.requested_at, 1, 10).label("day"),
                func.count().label("cnt"),
            )
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.deleted_at.is_(None),
            )
            .group_by(func.substr(QueueRequest.requested_at, 1, 10))
            .order_by(func.count().desc())
            .limit(1)
        )
    ).first()
    busiest_day = day_rows.day if day_rows else None

    hour_rows = (
        await db.execute(
            select(
                func.substr(QueueRequest.requested_at, 12, 2).label("hour"),
                func.count().label("cnt"),
            )
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.deleted_at.is_(None),
            )
            .group_by(func.substr(QueueRequest.requested_at, 12, 2))
            .order_by(func.count().desc())
            .limit(1)
        )
    ).first()
    busiest_hour = int(hour_rows.hour) if hour_rows else None

    return VenueOverviewOut(
        venue_id=venue_id,
        total_songs_played=total_songs_played,
        total_singers=total_singers,
        avg_queue_wait_seconds=avg_wait,
        busiest_day=busiest_day,
        busiest_hour=busiest_hour,
    )


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

@router.get("/venue/{venue_id}/leaderboard")
async def get_leaderboard(
    venue_id: str,
    limit: int = Query(10, ge=1, le=50),
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Top N singers by completed performance count at this venue."""
    _require_venue_access(current, venue_id)

    # Ensure venue exists
    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    rows = (
        await db.execute(
            select(
                QueueRequest.singer_id,
                func.count().label("cnt"),
            )
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status == "completed",
                QueueRequest.deleted_at.is_(None),
            )
            .group_by(QueueRequest.singer_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()

    if not rows:
        return {"items": []}

    singer_ids = [row.singer_id for row in rows]
    singers_result = (
        await db.execute(
            select(Singer).where(Singer.id.in_(singer_ids))
        )
    ).scalars().all()
    singer_map = {s.id: s for s in singers_result}

    items: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, start=1):
        singer = singer_map.get(row.singer_id)
        items.append(
            SingerLeaderboardEntry(
                rank=rank,
                singer_id=row.singer_id,
                stage_name=singer.stage_name if singer else "",
                performance_count=row.cnt,
            ).model_dump()
        )

    return {"items": items}


# ---------------------------------------------------------------------------
# Song popularity
# ---------------------------------------------------------------------------

@router.get("/venue/{venue_id}/song-popularity")
async def get_song_popularity(
    venue_id: str,
    limit: int = Query(20, ge=1, le=100),
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Most requested songs at this venue, ordered by request count desc."""
    _require_venue_access(current, venue_id)

    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    rows = (
        await db.execute(
            select(
                QueueRequest.song_id,
                func.count().label("cnt"),
            )
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.deleted_at.is_(None),
            )
            .group_by(QueueRequest.song_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()

    if not rows:
        return {"items": []}

    song_ids = [row.song_id for row in rows]
    songs_result = (
        await db.execute(
            select(Song).where(Song.id.in_(song_ids))
        )
    ).scalars().all()
    song_map = {s.id: s for s in songs_result}

    items: list[dict[str, Any]] = []
    for row in rows:
        song = song_map.get(row.song_id)
        items.append(
            SongPopularityEntry(
                song_id=row.song_id,
                title=song.title if song else "",
                artist=song.artist if song else "",
                request_count=row.cnt,
            ).model_dump()
        )

    return {"items": items}


# ---------------------------------------------------------------------------
# Hourly breakdown
# ---------------------------------------------------------------------------

@router.get("/venue/{venue_id}/hourly-breakdown")
async def get_hourly_breakdown(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Request count per hour of day (0-23) for heatmap rendering."""
    _require_venue_access(current, venue_id)

    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    rows = (
        await db.execute(
            select(
                QueueRequest.requested_at,
            )
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).all()

    hour_counts = {h: 0 for h in range(24)}
    for (ts,) in rows:
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            hour_counts[dt.hour] += 1
        except Exception:
            pass

    items = [
        HourlyBreakdownItem(hour=h, request_count=hour_counts[h]).model_dump()
        for h in range(24)
    ]

    return {"items": items}


# ---------------------------------------------------------------------------
# Singer stats
# ---------------------------------------------------------------------------

@router.get("/singer/{singer_id}/stats", response_model=SingerStatsOut)
async def get_singer_stats(
    singer_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Individual singer performance statistics."""
    singer = await _require_singer_access(current, singer_id, db)

    # performances_count
    performances_count = (
        await db.execute(
            select(func.count()).select_from(QueueRequest).where(
                QueueRequest.singer_id == singer_id,
                QueueRequest.status == "completed",
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    # venues_visited: distinct venue_ids across all queue requests by this singer
    venues_result = (
        await db.execute(
            select(QueueRequest.venue_id)
            .where(
                QueueRequest.singer_id == singer_id,
                QueueRequest.deleted_at.is_(None),
            )
            .distinct()
        )
    ).all()
    venues_visited = len(venues_result)

    # favorite_genre: genre of the most-completed song
    genre_rows = (
        await db.execute(
            select(
                Song.genre,
                func.count().label("cnt"),
            )
            .select_from(QueueRequest)
            .join(Song, QueueRequest.song_id == Song.id)
            .where(
                QueueRequest.singer_id == singer_id,
                QueueRequest.status == "completed",
                QueueRequest.deleted_at.is_(None),
            )
            .group_by(Song.genre)
            .order_by(func.count().desc())
            .limit(1)
        )
    ).all()

    favorite_genre = str(genre_rows[0].genre) if genre_rows else None

    return SingerStatsOut(
        singer_id=singer_id,
        stage_name=singer.stage_name,
        performances_count=performances_count,
        venues_visited=venues_visited,
        favorite_genre=favorite_genre,
    )
