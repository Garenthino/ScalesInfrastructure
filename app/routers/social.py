"""Social router — leaderboard + share.

Endpoints
---------
Public / Authenticated:
    GET  /venues/{venue_id}/leaderboard         — venue-wide rankings by period
    POST /venues/{venue_id}/leaderboard/share   — generate share link
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.models import Venue, Singer, ShareEvent, QueueRequest
from app.schemas import LeaderboardEntryOut, PaginatedResponse, ShareRequest, ShareResponse
from app.core.points_service import get_points_leaderboard

router = APIRouter()


def NOW() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
# Leaderboard
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[LeaderboardEntryOut])
async def get_leaderboard(
    venue_id: str,
    period: str = Query("alltime", pattern=r"^(week|month|alltime)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Venue-wide leaderboard ranked by points for the given period."""
    await _require_venue(db, venue_id)
    items, total = await get_points_leaderboard(db, venue_id, period, page, per_page)
    out = [
        LeaderboardEntryOut(
            rank=i["rank"],
            singer_id=i["singer_id"],
            nickname=i.get("nickname"),
            avatar_url=i.get("avatar_url"),
            score=i["score"],
            songs_sung=i.get("songs_sung", 0),
            trend="stable",
        )
        for i in items
    ]
    return PaginatedResponse(items=out, total=total, page=page, per_page=per_page)


@router.get("/{singer_id}", response_model=LeaderboardEntryOut)
async def get_leaderboard_entry(
    venue_id: str,
    singer_id: str,
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

    # Compute rank
    rank_stmt = (
        select(func.count())
        .select_from(Singer)
        .where(
            Singer.venue_id == venue_id,
            Singer.deleted_at.is_(None),
            Singer.deactivated_at.is_(None),
            Singer.total_points > singer.total_points,
        )
    )
    rank_result = await db.execute(rank_stmt)
    rank = int(rank_result.scalar_one() or 0) + 1

    songs_sung_result = await db.execute(
        select(func.count())
        .select_from(QueueRequest)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == singer_id,
            QueueRequest.status == "completed",
            QueueRequest.deleted_at.is_(None),
        )
    )
    songs_sung = int(songs_sung_result.scalar_one() or 0)

    return LeaderboardEntryOut(
        rank=rank,
        singer_id=str(singer.id),
        nickname=singer.stage_name,
        avatar_url=singer.avatar_url,
        score=float(singer.total_points or 0),
        songs_sung=songs_sung,
        trend="stable",
    )


# ---------------------------------------------------------------------------
# Share
# ---------------------------------------------------------------------------

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

    return ShareResponse(url=share_url, expires_at=(datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"))
