"""Loyalty router — gamification, quests, rewards.

Endpoints
---------
Singer:
    GET  /singer/loyalty                       — summary (points + tier)
    GET  /singer/loyalty/transactions          — paginated points history
    GET  /singer/loyalty/quests                — available quests
    POST /singer/loyalty/quests/{quest_id}/claim — claim quest reward

Admin (KJ only):
    POST /singer/loyalty/admin/tiers           — create tier
    POST /singer/loyalty/admin/quests          — create quest
    POST /singer/loyalty/admin/award           — manual point award
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.core.permissions import Role
from app.core.dependencies import require_role
from app.core.loyalty_service import (
    manual_award,
    quest_progress,
    parse_criteria,
    build_criteria,
    award_points,
)
from app.models import (
    Singer,
    LoyaltyPoints,
    LoyaltyTier,
    LoyaltyQuest,
    LoyaltyQuestCompletion,
)
from app.schemas import (
    LoyaltySummary,
    LoyaltyPointsTransaction,
    QuestOut,
    PaginatedResponse,
    LoyaltyTierOut,
    LoyaltyTierCreate,
    QuestCreate,
    ManualAwardRequest,
)

def NOW() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

router = APIRouter()


# ---------------------------------------------------------------------------
# Singer endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=LoyaltySummary)
async def get_loyalty_summary(
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current points, tier name, and next-tier progress."""
    venue_id = current.venue_id

    singer_result = await db.execute(
        select(Singer).where(
            Singer.id == current.id,
            Singer.venue_id == venue_id,
            Singer.deleted_at.is_(None),
        )
    )
    singer = singer_result.scalar_one_or_none()
    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    points = int(singer.total_points or 0)

    tier_name = None
    if singer.loyalty_tier_id:
        tier_result = await db.execute(
            select(LoyaltyTier).where(LoyaltyTier.id == singer.loyalty_tier_id)
        )
        tier_obj = tier_result.scalar_one_or_none()
        if tier_obj is not None:
            tier_name = tier_obj.name

    next_tier_result = await db.execute(
        select(LoyaltyTier)
        .where(
            LoyaltyTier.venue_id == venue_id,
            LoyaltyTier.is_active == 1,
            LoyaltyTier.deleted_at.is_(None),
            LoyaltyTier.min_points > points,
        )
        .order_by(LoyaltyTier.min_points.asc())
        .limit(1)
    )
    next_tier = next_tier_result.scalar_one_or_none()

    if next_tier is not None and next_tier.min_points > 0:
        progress = min(1.0, float(points) / float(next_tier.min_points))
    else:
        progress = 1.0

    return LoyaltySummary(
        current_points=points,
        tier=tier_name,
        next_tier_progress=progress,
    )


@router.get("/transactions", response_model=PaginatedResponse[LoyaltyPointsTransaction])
async def get_transactions(
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """Paginated points transaction history for the current singer."""
    venue_id = current.venue_id

    offset = (page - 1) * per_page

    result = await db.execute(
        select(LoyaltyPoints)
        .where(
            LoyaltyPoints.venue_id == venue_id,
            LoyaltyPoints.singer_id == current.id,
        )
        .order_by(LoyaltyPoints.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    items = result.scalars().all()

    count_result = await db.execute(
        select(func.count())
        .select_from(LoyaltyPoints)
        .where(
            LoyaltyPoints.venue_id == venue_id,
            LoyaltyPoints.singer_id == current.id,
        )
    )
    total = count_result.scalar_one()

    out = [
        LoyaltyPointsTransaction(
            id=str(r.id),
            amount=int(r.amount),
            reason=r.reason,
            reference_type=r.reference_type,
            reference_id=r.reference_id,
            created_at=str(r.created_at),
        )
        for r in items
    ]

    return PaginatedResponse(items=out, total=total, page=page, per_page=per_page)


@router.get("/quests", response_model=PaginatedResponse[QuestOut])
async def get_quests(
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List available (active) quests for the current singer, with progress."""
    venue_id = current.venue_id

    offset = (page - 1) * per_page

    result = await db.execute(
        select(LoyaltyQuest)
        .where(
            LoyaltyQuest.venue_id == venue_id,
            LoyaltyQuest.is_active == 1,
            LoyaltyQuest.deleted_at.is_(None),
        )
        .order_by(LoyaltyQuest.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    quests = result.scalars().all()

    count_result = await db.execute(
        select(func.count())
        .select_from(LoyaltyQuest)
        .where(
            LoyaltyQuest.venue_id == venue_id,
            LoyaltyQuest.is_active == 1,
            LoyaltyQuest.deleted_at.is_(None),
        )
    )
    total = count_result.scalar_one()

    out_items: list[QuestOut] = []
    for q in quests:
        criteria = parse_criteria(q.criteria_json)
        current_progress, target = await quest_progress(db, q, current.id)
        is_completed = current_progress >= target if target > 0 else False

        # Check if already claimed
        claimed_result = await db.execute(
            select(LoyaltyQuestCompletion).where(
                LoyaltyQuestCompletion.quest_id == str(q.id),
                LoyaltyQuestCompletion.singer_id == current.id,
            )
        )
        claimed = claimed_result.scalar_one_or_none() is not None

        out_items.append(
            QuestOut(
                id=str(q.id),
                name=q.name,
                description=q.description,
                type=criteria.get("type", ""),
                target=target,
                reward_points=int(q.reward_points or 0),
                start_date=criteria.get("start_date"),
                end_date=criteria.get("end_date"),
                is_recurring=criteria.get("is_recurring", False),
                current_progress=current_progress,
                is_claimable=is_completed and not claimed,
            )
        )

    return PaginatedResponse(items=out_items, total=total, page=page, per_page=per_page)


@router.post("/quests/{quest_id}/claim")
async def claim_quest(
    quest_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Claim quest reward if completed and not already claimed."""
    venue_id = current.venue_id

    quest = (
        await db.execute(
            select(LoyaltyQuest).where(
                LoyaltyQuest.id == quest_id,
                LoyaltyQuest.venue_id == venue_id,
                LoyaltyQuest.is_active == 1,
                LoyaltyQuest.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if quest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Quest not found")

    existing = (
        await db.execute(
            select(LoyaltyQuestCompletion).where(
                LoyaltyQuestCompletion.quest_id == quest_id,
                LoyaltyQuestCompletion.singer_id == current.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Quest already claimed")

    current_progress, target = await quest_progress(db, quest, current.id)
    if target <= 0 or current_progress < target:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Quest progress not met")

    await award_points(
        db, venue_id, current.id, int(quest.reward_points or 0),
        f"Quest completed: {quest.name}", "quest", quest_id,
    )

    completion = LoyaltyQuestCompletion(
        venue_id=venue_id,
        singer_id=current.id,
        quest_id=quest_id,
        completed_at=NOW(),
    )
    db.add(completion)
    await db.commit()

    return {"claimed": True, "reward_points": int(quest.reward_points or 0)}


# ---------------------------------------------------------------------------
# Admin (KJ only)
# ---------------------------------------------------------------------------

@router.post("/admin/tiers", response_model=LoyaltyTierOut, status_code=status.HTTP_201_CREATED)
async def create_tier(
    body: LoyaltyTierCreate,
    current: SingerUser = Depends(require_role(Role.KJ)),
    db: AsyncSession = Depends(get_db),
):
    """Create a loyalty tier for the current venue (KJ+ only)."""
    venue_id = current.venue_id

    tier = LoyaltyTier(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name=body.name,
        min_points=int(body.min_points),
        multiplier=float(body.multiplier),
        color=body.color,
        icon=body.icon,
        is_active=1,
        created_at=NOW(),
        updated_at=NOW(),
    )
    db.add(tier)
    await db.commit()
    await db.refresh(tier)

    return LoyaltyTierOut(
        id=str(tier.id),
        name=tier.name,
        min_points=int(tier.min_points),
        multiplier=float(tier.multiplier),
        color=tier.color,
        icon=tier.icon,
    )


@router.post("/admin/quests", response_model=QuestOut, status_code=status.HTTP_201_CREATED)
async def create_quest(
    body: QuestCreate,
    current: SingerUser = Depends(require_role(Role.KJ)),
    db: AsyncSession = Depends(get_db),
):
    """Create a loyalty quest for the current venue (KJ+ only)."""
    venue_id = current.venue_id

    criteria_json = build_criteria(
        quest_type=body.quest_type,
        target=int(body.target),
        start_date=body.start_date,
        end_date=body.end_date,
        is_recurring=body.is_recurring,
    )

    quest = LoyaltyQuest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name=body.name,
        description=body.description,
        criteria_json=criteria_json,
        reward_points=int(body.reward_points),
        is_active=1,
        created_at=NOW(),
        updated_at=NOW(),
    )
    db.add(quest)
    await db.commit()
    await db.refresh(quest)

    return QuestOut(
        id=str(quest.id),
        name=quest.name,
        description=quest.description,
        type=body.quest_type,
        target=int(body.target),
        reward_points=int(quest.reward_points or 0),
        start_date=body.start_date,
        end_date=body.end_date,
        is_recurring=body.is_recurring,
        current_progress=0,
        is_claimable=False,
    )


@router.post("/admin/award", status_code=status.HTTP_204_NO_CONTENT)
async def manual_award_points(
    body: ManualAwardRequest,
    current: SingerUser = Depends(require_role(Role.KJ)),
    db: AsyncSession = Depends(get_db),
):
    """Manually award points to a singer at the current venue (KJ+ only)."""
    venue_id = current.venue_id

    singer = (
        await db.execute(
            select(Singer).where(
                Singer.id == body.singer_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if singer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Singer not found")

    await manual_award(
        db, venue_id, body.singer_id, int(body.amount), body.reason or "Manual award"
    )
    return None
