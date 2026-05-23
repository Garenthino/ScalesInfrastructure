"""Social / leaderboard router — share achievements and view rankings.

Endpoints
---------
Public / Authenticated:
    GET  /venues/{venue_id}/leaderboard         — venue-wide rankings
    GET  /venues/{venue_id}/leaderboard/{singer_id} — single entry
    POST /venues/{venue_id}/leaderboard/share  — generate share link
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.models import Singer, QueueRequest, ShareEvent, Venue
from app.schemas import LeaderboardEntryOut, PaginatedResponse, ShareRequest, ShareResponse

router = APIRouter()


def NOW() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_plus(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _require_venue(db: AsyncSession, venue_id: str) -> Venue:
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


# ---------------------------------------------------------------------------
# Leaderboard helpers
# ---------------------------------------------------------------------------

async def _rank_by_points(
    db: AsyncSession, venue_id: str, page: int, per_page: int
) -> tuple[list[LeaderboardEntryOut], int]:
    """Rank singers by total_points (highest first)."""
    total = (
        await db.execute(
            select(func.count())
            .select_from(Singer)
            .where(
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    singers = (
        await db.execute(
            select(Singer)
            .where(
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
            .order_by(Singer.total_points.desc().nulls_last(), Singer.created_at.asc())
            .offset(offset)
            .limit(per_page)
        )
    ).scalars().all()

    items: list[LeaderboardEntryOut] = []
    for idx, singer in enumerate(singers, start=offset + 1):
        items.append(
            LeaderboardEntryOut(
                rank=idx,
                singer_id=str(singer.id),
                nickname=singer.stage_name or None,
                avatar_url=None,
                score=float(singer.total_points or 0),
                songs_sung=0,  # filled below
                trend="stable",
            )
        )
    return items, total


async def _rank_by_songs(
    db: AsyncSession, venue_id: str, page: int, per_page: int
) -> tuple[list[LeaderboardEntryOut], int]:
    """Rank singers by completed songs count."""
    stmt = (
        select(
            Singer,
            func.count(QueueRequest.id).label("songs_sung"),
        )
        .outerjoin(
            QueueRequest,
            (Singer.id == QueueRequest.singer_id)
            & (QueueRequest.status == "completed")
            & (QueueRequest.deleted_at.is_(None)),
        )
        .where(
            Singer.venue_id == venue_id,
            Singer.deleted_at.is_(None),
            Singer.deactivated_at.is_(None),
        )
        .group_by(Singer.id)
        .order_by(func.count(QueueRequest.id).desc(), Singer.created_at.asc())
    )

    total = (
        await db.execute(
            select(func.count())
            .select_from(Singer)
            .where(
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    result = await db.execute(stmt.offset(offset).limit(per_page))

    items: list[LeaderboardEntryOut] = []
    for idx, (singer, songs_sung) in enumerate(result.all(), start=offset + 1):
        items.append(
            LeaderboardEntryOut(
                rank=idx,
                singer_id=str(singer.id),
                nickname=singer.stage_name or None,
                avatar_url=None,
                score=float(songs_sung or 0),
                songs_sung=int(songs_sung or 0),
                trend="stable",
            )
        )
    return items, total


async def _rank_by_participation(
    db: AsyncSession, venue_id: str, page: int, per_page: int
) -> tuple[list[LeaderboardEntryOut], int]:
    """Rank singers by total queue requests (participation)."""
    stmt = (
        select(
            Singer,
            func.count(QueueRequest.id).label("participation"),
        )
        .outerjoin(
            QueueRequest,
            (Singer.id == QueueRequest.singer_id)
            & (QueueRequest.deleted_at.is_(None)),
        )
        .where(
            Singer.venue_id == venue_id,
            Singer.deleted_at.is_(None),
            Singer.deactivated_at.is_(None),
        )
        .group_by(Singer.id)
        .order_by(func.count(QueueRequest.id).desc(), Singer.created_at.asc())
    )

    total = (
        await db.execute(
            select(func.count())
            .select_from(Singer)
            .where(
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    result = await db.execute(stmt.offset(offset).limit(per_page))

    items: list[LeaderboardEntryOut] = []
    for idx, (singer, part) in enumerate(result.all(), start=offset + 1):
        items.append(
            LeaderboardEntryOut(
                rank=idx,
                singer_id=str(singer.id),
                nickname=singer.stage_name or None,
                avatar_url=None,
                score=float(part or 0),
                songs_sung=0,  # filled below if needed
                trend="stable",
            )
        )
    return items, total


async def _fill_songs_counts(
    db: AsyncSession, venue_id: str, items: list[LeaderboardEntryOut]
) -> None:
    """Back-fill songs_sung for singer rows in the result set."""
    singer_ids = [item.singer_id for item in items]
    if not singer_ids:
        return
    result = await db.execute(
        select(QueueRequest.singer_id, func.count(QueueRequest.id))
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id.in_(singer_ids),
            QueueRequest.status == "completed",
            QueueRequest.deleted_at.is_(None),
        )
        .group_by(QueueRequest.singer_id)
    )
    counts = {str(sid): int(cnt) for sid, cnt in result.all()}
    for item in items:
        item.songs_sung = counts.get(item.singer_id, 0)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[LeaderboardEntryOut])
async def get_leaderboard(
    venue_id: str,
    sort_by: str = Query("points", pattern=r"^(points|songs|participation)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Venue-wide rankings. Sortable by total_points, songs_sung, or participation."""
    await _require_venue(db, venue_id)

    if sort_by == "songs":
        items, total = await _rank_by_songs(db, venue_id, page, per_page)
    elif sort_by == "participation":
        items, total = await _rank_by_participation(db, venue_id, page, per_page)
    else:
        items, total = await _rank_by_points(db, venue_id, page, per_page)

    # Always enrich songs_sung
    await _fill_songs_counts(db, venue_id, items)

    # Re-score for points mode so score == points
    if sort_by == "points":
        for item in items:
            item.score = float(item.score)  # already points

    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{singer_id}", response_model=LeaderboardEntryOut)
async def get_leaderboard_entry(
    venue_id: str,
    singer_id: str,
    sort_by: str = Query("points", pattern=r"^(points|songs|participation)$"),
    db: AsyncSession = Depends(get_db),
):
    """Return a single singer's leaderboard standing."""
    await _require_venue(db, venue_id)

    singer = (
        await db.execute(
            select(Singer).where(
                Singer.id == singer_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    if sort_by == "songs":
        all_entries, _ = await _rank_by_songs(db, venue_id, page=1, per_page=100_000)
    elif sort_by == "participation":
        all_entries, _ = await _rank_by_participation(db, venue_id, page=1, per_page=100_000)
    else:
        all_entries, _ = await _rank_by_points(db, venue_id, page=1, per_page=100_000)

    await _fill_songs_counts(db, venue_id, all_entries)

    entry = next((entry for entry in all_entries if entry.singer_id == singer_id), None)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not ranked")
    return entry


@router.post("/share", response_model=ShareResponse)
async def share_achievement(
    venue_id: str,
    body: ShareRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a shareable link for a singer's achievement and record the event."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    await _require_venue(db, venue_id)

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

    share_id = str(uuid.uuid4())
    share_url = f"http://share.scales/{share_id}"

    event = ShareEvent(
        id=share_id,
        venue_id=venue_id,
        singer_id=current.id,
        platform=body.content_type,
        url=share_url,
        content_type=body.content_type,
    )
    db.add(event)
    await db.commit()

    return ShareResponse(url=share_url, expires_at=_now_plus(7))
