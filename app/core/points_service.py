"""Points engine: ledger entries, leaderboard queries, achievement rules.

Points rules (per task spec):
- check-in  : +10
- request   : +5
- performed : +25
- tip       : +amount

Achievements:
- first_song  : 1 completed song
- iron_lungs  : 10 completed songs
- regular     : 5 check-ins
- big_spender : $50 (5000 cents) tips total
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import (
    Singer,
    PointsLedger,
    SingerAchievement,
    QueueRequest,
    CheckInSession,
)


def _NOW() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _period_start(period: str) -> str | None:
    """ISO 8601 cutoff for period-based queries."""
    now = datetime.now(timezone.utc)
    if period == "week":
        start = now - timedelta(days=7)
    elif period == "month":
        start = now - timedelta(days=30)
    elif period == "alltime" or not period:
        return None
    else:
        return None
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Core ledger primitive
# ---------------------------------------------------------------------------

async def add_points(
    db: AsyncSession,
    venue_id: str,
    singer_id: str,
    amount: int,
    reason: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> None:
    """Write a ledger entry and bump singer.total_points."""
    if amount == 0:
        return

    ledger = PointsLedger(
        venue_id=venue_id,
        singer_id=singer_id,
        amount=amount,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        created_at=_NOW(),
    )
    db.add(ledger)
    await db.flush()

    singer = await db.get(Singer, singer_id)
    if singer is not None:
        setattr(singer, "total_points", (singer.total_points or 0) + amount)
        setattr(singer, "updated_at", _NOW())
    await db.commit()


async def get_points_leaderboard(
    db: AsyncSession,
    venue_id: str,
    period: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """Return (items, total) ranked by points for the period."""
    # For alltime, just rank by total_points directly (includes both legacy LoyaltyPoints
    # and new PointsLedger, since both bump Singer.total_points).
    if period in (None, "", "alltime"):
        return await _leaderboard_alltime(db, venue_id, page, per_page)

    cutoff = _period_start(period)

    subq = (
        select(
            PointsLedger.singer_id.label("singer_id"),
            func.coalesce(func.sum(PointsLedger.amount), 0).label("period_score"),
        )
        .where(
            PointsLedger.venue_id == venue_id,
            PointsLedger.created_at >= cutoff,
        )
        .group_by(PointsLedger.singer_id)
    ).subquery()

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

    stmt = (
        select(
            Singer,
            func.coalesce(subq.c.period_score, 0).label("score"),
        )
        .outerjoin(subq, Singer.id == subq.c.singer_id)
        .where(
            Singer.venue_id == venue_id,
            Singer.deleted_at.is_(None),
            Singer.deactivated_at.is_(None),
        )
        .order_by(func.coalesce(subq.c.period_score, 0).desc(), Singer.created_at.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )

    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for idx, (singer, score) in enumerate(rows, start=(page - 1) * per_page + 1):
        items.append({
            "rank": idx,
            "singer_id": str(singer.id),
            "nickname": singer.stage_name,
            "avatar_url": singer.avatar_url,
            "score": float(score or 0),
            "songs_sung": 0,
        })

    # Backfill songs_sung
    singer_ids = [i["singer_id"] for i in items]
    if singer_ids:
        counts = await db.execute(
            select(QueueRequest.singer_id, func.count(QueueRequest.id))
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.singer_id.in_(singer_ids),
                QueueRequest.status == "completed",
                QueueRequest.deleted_at.is_(None),
            )
            .group_by(QueueRequest.singer_id)
        )
        count_map = {str(sid): int(c) for sid, c in counts.all()}
        for item in items:
            item["songs_sung"] = count_map.get(item["singer_id"], 0)

    return items, total


async def _leaderboard_alltime(
    db: AsyncSession, venue_id: str, page: int, per_page: int
) -> tuple[list[dict[str, Any]], int]:
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

    singers = (
        await db.execute(
            select(Singer)
            .where(
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
            .order_by(Singer.total_points.desc().nulls_last(), Singer.created_at.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    items: list[dict[str, Any]] = []
    for idx, singer in enumerate(singers, start=(page - 1) * per_page + 1):
        items.append({
            "rank": idx,
            "singer_id": str(singer.id),
            "nickname": singer.stage_name,
            "avatar_url": singer.avatar_url,
            "score": float(singer.total_points or 0),
            "songs_sung": 0,
        })

    singer_ids = [i["singer_id"] for i in items]
    if singer_ids:
        counts = await db.execute(
            select(QueueRequest.singer_id, func.count(QueueRequest.id))
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.singer_id.in_(singer_ids),
                QueueRequest.status == "completed",
                QueueRequest.deleted_at.is_(None),
            )
            .group_by(QueueRequest.singer_id)
        )
        count_map = {str(sid): int(c) for sid, c in counts.all()}
        for item in items:
            item["songs_sung"] = count_map.get(item["singer_id"], 0)

    return items, total


async def get_singer_period_points(
    db: AsyncSession,
    venue_id: str,
    singer_id: str,
    period: str | None = None,
) -> int:
    """Return total ledger points for a singer in the given period."""
    cutoff = _period_start(period) if period and period != "alltime" else None
    stmt = select(func.coalesce(func.sum(PointsLedger.amount), 0)).where(
        PointsLedger.venue_id == venue_id,
        PointsLedger.singer_id == singer_id,
    )
    if cutoff:
        stmt = stmt.where(PointsLedger.created_at >= cutoff)
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


# ---------------------------------------------------------------------------
# Achievement rules
# ---------------------------------------------------------------------------

ACHIEVEMENT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "first_song": {
        "name": "First Song",
        "description": "Complete your first performance.",
        "icon": "microphone",
        "target": 1,
        "evaluator": "completed_songs",
    },
    "iron_lungs": {
        "name": "Iron Lungs",
        "description": "Complete 10 performances.",
        "icon": "shield",
        "target": 10,
        "evaluator": "completed_songs",
    },
    "regular": {
        "name": "Regular",
        "description": "Check in 5 times.",
        "icon": "calendar-check",
        "target": 5,
        "evaluator": "checkins",
    },
    "big_spender": {
        "name": "Big Spender",
        "description": "Tip $50 total.",
        "icon": "coins",
        "target": 5000,  # cents = $50
        "evaluator": "tips",
    },
}


async def _eval_completed_songs(
    db: AsyncSession, venue_id: str, singer_id: str
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(QueueRequest)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == singer_id,
            QueueRequest.status == "completed",
            QueueRequest.deleted_at.is_(None),
        )
    )
    return int(result.scalar_one() or 0)


async def _eval_checkins(db: AsyncSession, venue_id: str, singer_id: str) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(CheckInSession)
        .where(
            CheckInSession.venue_id == venue_id,
            CheckInSession.singer_id == singer_id,
        )
    )
    return int(result.scalar_one() or 0)


async def _eval_tips(db: AsyncSession, venue_id: str, singer_id: str) -> int:
    result = await db.execute(
        select(func.coalesce(func.sum(PointsLedger.amount), 0))
        .where(
            PointsLedger.venue_id == venue_id,
            PointsLedger.singer_id == singer_id,
            PointsLedger.reference_type == "tip",
        )
    )
    return int(result.scalar_one() or 0)


_EVALUATORS = {
    "completed_songs": _eval_completed_songs,
    "checkins": _eval_checkins,
    "tips": _eval_tips,
}


async def get_achievements_for_singer(
    db: AsyncSession,
    venue_id: str,
    singer_id: str,
) -> list[dict[str, Any]]:
    """Return achievement list with progress and unlock state for a singer."""
    # Load existing rows
    result = await db.execute(
        select(SingerAchievement).where(
            SingerAchievement.venue_id == venue_id,
            SingerAchievement.singer_id == singer_id,
        )
    )
    existing = {str(a.achievement_key): a for a in result.scalars().all()}

    out: list[dict[str, Any]] = []
    for key, defn in ACHIEVEMENT_DEFINITIONS.items():
        row = existing.get(key)
        progress = row.progress if row else 0
        unlocked_at = row.unlocked_at if row else None

        # Re-evaluate current progress
        evaluator = _EVALUATORS.get(defn["evaluator"])
        if evaluator:
            current_progress = await evaluator(db, venue_id, singer_id)
        else:
            current_progress = progress

        target = defn["target"]
        is_unlocked = bool(unlocked_at) or current_progress >= target

        if current_progress != progress or (is_unlocked and not unlocked_at):
            if row is None:
                row = SingerAchievement(
                    id=str(__import__("uuid").uuid4()),
                    venue_id=venue_id,
                    singer_id=singer_id,
                    achievement_key=key,
                    progress=current_progress,
                    unlocked_at=_NOW() if is_unlocked else None,
                    created_at=_NOW(),
                    updated_at=_NOW(),
                )
                db.add(row)
            else:
                setattr(row, "progress", current_progress)
                if is_unlocked and not getattr(row, "unlocked_at", None):
                    setattr(row, "unlocked_at", _NOW())
                setattr(row, "updated_at", _NOW())
            await db.commit()
            await db.refresh(row)
            progress = int(getattr(row, "progress", 0))
            unlocked_at = getattr(row, "unlocked_at", None)

        out.append({
            "achievement_key": key,
            "name": defn["name"],
            "description": defn["description"],
            "icon": defn.get("icon"),
            "progress": progress,
            "target": target,
            "unlocked_at": unlocked_at,
            "unlocked": bool(unlocked_at),
        })

    return out


async def ensure_achievement_progress(
    db: AsyncSession,
    venue_id: str,
    singer_id: str,
) -> None:
    """After any points event, update achievement rows for the singer (lazy)."""
    # Triggers re-evaluation on next GET /achievements; if callers want eager
    # unlock they can call get_achievements_for_singer.
    pass
