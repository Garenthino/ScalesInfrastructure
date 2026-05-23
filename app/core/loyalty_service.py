"""Loyalty point awarding, tier recomputation, and quest helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import (
    Singer,
    LoyaltyPoints,
    LoyaltyTier,
    LoyaltyQuest,
    QueueRequest,
    Order,
)

def _NOW() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

PERFORMANCE_POINTS = 10          # base points per completed song
PURCHASE_POINTS_PER_CENT = 0.01  # 1 point per dollar spent
FIRST_PERFORMANCE_BONUS = 50
FIRST_PURCHASE_BONUS = 100


# ---------------------------------------------------------------------------
# Tier
# ---------------------------------------------------------------------------

async def _compute_tier(db: AsyncSession, venue_id: str, points: int) -> LoyaltyTier | None:
    result = await db.execute(
        select(LoyaltyTier)
        .where(
            LoyaltyTier.venue_id == venue_id,
            LoyaltyTier.is_active == 1,
            LoyaltyTier.deleted_at.is_(None),
            LoyaltyTier.min_points <= points,
        )
        .order_by(LoyaltyTier.min_points.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Core award primitive
# ---------------------------------------------------------------------------

async def award_points(
    db: AsyncSession,
    venue_id: str,
    singer_id: str,
    amount: int,
    reason: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> None:
    """Insert a LoyaltyPoints row and bump singer.total_points + recompute tier."""
    if amount == 0:
        return

    txn = LoyaltyPoints(
        venue_id=venue_id,
        singer_id=singer_id,
        amount=amount,
        reason=reason,
        reference_type=reference_type,
        reference_id=reference_id,
        created_at=_NOW(),
    )
    db.add(txn)
    await db.flush()

    singer_result = await db.execute(select(Singer).where(Singer.id == singer_id))
    singer = singer_result.scalar_one_or_none()
    if singer is not None:
        total = int(singer.total_points or 0)
        singer.total_points = total + amount
        new_tier = await _compute_tier(db, venue_id, singer.total_points)
        if new_tier is not None and str(new_tier.id) != str(singer.loyalty_tier_id or ""):
            singer.loyalty_tier_id = str(new_tier.id)
    await db.commit()


# ---------------------------------------------------------------------------
# Performance (queue complete)
# ---------------------------------------------------------------------------

async def award_performance_points(
    db: AsyncSession, venue_id: str, singer_id: str, request_id: str
) -> None:
    await award_points(
        db, venue_id, singer_id, PERFORMANCE_POINTS,
        "Performance completed", "queue_request", request_id,
    )

    # First performance ever at this venue?
    completed_result = await db.execute(
        select(func.count())
        .select_from(QueueRequest)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.singer_id == singer_id,
            QueueRequest.status == "completed",
            QueueRequest.deleted_at.is_(None),
        )
    )
    completed_count = int(completed_result.scalar_one() or 0)
    if completed_count == 1:
        await award_points(
            db, venue_id, singer_id, FIRST_PERFORMANCE_BONUS,
            "First performance at venue", "achievement", None,
        )


# ---------------------------------------------------------------------------
# Purchase (commerce checkout)
# ---------------------------------------------------------------------------

async def award_purchase_points(
    db: AsyncSession, venue_id: str, singer_id: str, order_id: str, total_cents: int
) -> None:
    points = max(1, int(total_cents * PURCHASE_POINTS_PER_CENT))
    await award_points(
        db, venue_id, singer_id, points,
        "Merch purchase", "order", order_id,
    )

    # First purchase ever?
    order_result = await db.execute(
        select(func.count())
        .select_from(Order)
        .where(
            Order.venue_id == venue_id,
            Order.singer_id == singer_id,
            Order.deleted_at.is_(None),
        )
    )
    order_count = int(order_result.scalar_one() or 0)
    if order_count == 1:
        await award_points(
            db, venue_id, singer_id, FIRST_PURCHASE_BONUS,
            "First merch purchase", "achievement", None,
        )


# ---------------------------------------------------------------------------
# Manual award (admin)
# ---------------------------------------------------------------------------

async def manual_award(
    db: AsyncSession,
    venue_id: str,
    singer_id: str,
    amount: int,
    reason: str,
) -> None:
    await award_points(
        db, venue_id, singer_id, amount,
        reason or "Manual award", "manual", None,
    )


# ---------------------------------------------------------------------------
# Quest criteria helpers
# ---------------------------------------------------------------------------

def parse_criteria(criteria_json: str | None) -> dict:
    if not criteria_json:
        return {}
    try:
        return json.loads(criteria_json)
    except Exception:
        return {}


def build_criteria(
    quest_type: str,
    target: int,
    start_date: str | None = None,
    end_date: str | None = None,
    is_recurring: bool = False,
) -> str:
    return json.dumps({
        "type": quest_type,
        "target": target,
        "start_date": start_date,
        "end_date": end_date,
        "is_recurring": is_recurring,
    })


# ---------------------------------------------------------------------------
# Quest progress evaluation
# ---------------------------------------------------------------------------

async def quest_progress(
    db: AsyncSession,
    quest: LoyaltyQuest,
    singer_id: str,
) -> tuple[int, int]:
    """Return (current, target) for a quest."""
    criteria = parse_criteria(quest.criteria_json)
    quest_type = criteria.get("type")
    target = criteria.get("target", 0)

    if quest_type == "perform_N_songs":
        current_result = await db.execute(
            select(func.count())
            .select_from(QueueRequest)
            .where(
                QueueRequest.venue_id == quest.venue_id,
                QueueRequest.singer_id == singer_id,
                QueueRequest.status == "completed",
                QueueRequest.deleted_at.is_(None),
            )
        )
        current = int(current_result.scalar_one() or 0)
    elif quest_type == "spend_N_currency":
        current_result = await db.execute(
            select(func.coalesce(func.sum(Order.total_cents), 0))
            .where(
                Order.venue_id == quest.venue_id,
                Order.singer_id == singer_id,
                Order.deleted_at.is_(None),
            )
        )
        current = int(current_result.scalar_one() or 0)
    elif quest_type == "visit_N_times":
        # Distinct performance dates as a proxy for visits
        current_result = await db.execute(
            select(func.count(func.distinct(func.strftime("%Y-%m-%d", QueueRequest.played_at))))
            .where(
                QueueRequest.venue_id == quest.venue_id,
                QueueRequest.singer_id == singer_id,
                QueueRequest.status == "completed",
                QueueRequest.played_at.isnot(None),
                QueueRequest.deleted_at.is_(None),
            )
        )
        current = int(current_result.scalar_one() or 0)
    else:
        current = 0

    return current, target
