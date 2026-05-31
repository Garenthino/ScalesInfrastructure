"""Singer follows router — venue-scoped social follow/unfollow/status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.models import Singer, SingerFollow
from app.schemas import FollowOut, FollowStatusOut

router = APIRouter()


def _require_venue(venue_id: str, current: SingerUser) -> None:
    """Enforce that the current user's venue matches the URL venue."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )


@router.post("/follow/{followee_id}", response_model=FollowOut, status_code=status.HTTP_201_CREATED)
async def follow_singer(
    venue_id: str,
    followee_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Follow a singer in this venue (idempotent; prevents self-follow)."""
    _require_venue(venue_id, current)

    if str(current.id) == str(followee_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot follow yourself",
        )

    # Verify followee exists in this venue
    followee = (
        await db.execute(
            select(Singer).where(
                Singer.id == followee_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if followee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Singer not found",
        )

    # Check for existing active follow (idempotent)
    existing = (
        await db.execute(
            select(SingerFollow).where(
                SingerFollow.follower_id == current.id,
                SingerFollow.followee_id == followee_id,
                SingerFollow.venue_id == venue_id,
                SingerFollow.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        return FollowOut(
            id=existing.id,
            venue_id=existing.venue_id,
            follower_id=existing.follower_id,
            followee_id=existing.followee_id,
            followee_name=followee.stage_name,
            created_at=existing.created_at,
        )

    from app.models import _new_uuid, _now_iso
    new_follow = SingerFollow(
        id=_new_uuid(),
        venue_id=venue_id,
        follower_id=current.id,
        followee_id=followee_id,
        created_at=_now_iso(),
        deleted_at=None,
    )
    db.add(new_follow)
    await db.commit()
    await db.refresh(new_follow)

    return FollowOut(
        id=new_follow.id,
        venue_id=new_follow.venue_id,
        follower_id=new_follow.follower_id,
        followee_id=new_follow.followee_id,
        followee_name=followee.stage_name,
        created_at=new_follow.created_at,
    )


@router.delete("/follow/{followee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_singer(
    venue_id: str,
    followee_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unfollow a singer in this venue (idempotent)."""
    _require_venue(venue_id, current)

    result = await db.execute(
        select(SingerFollow).where(
            SingerFollow.follower_id == current.id,
            SingerFollow.followee_id == followee_id,
            SingerFollow.venue_id == venue_id,
            SingerFollow.deleted_at.is_(None),
        )
    )
    follow = result.scalar_one_or_none()
    if follow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Follow relationship not found",
        )

    await db.delete(follow)
    await db.commit()
    return None


@router.get("/follow/status/{followee_id}", response_model=FollowStatusOut)
async def follow_status(
    venue_id: str,
    followee_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return whether the current user follows this singer, plus counts."""
    _require_venue(venue_id, current)

    # Verify followee exists
    followee = (
        await db.execute(
            select(Singer).where(
                Singer.id == followee_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if followee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Singer not found",
        )

    # Is current user following?
    active_follow = (
        await db.execute(
            select(SingerFollow).where(
                SingerFollow.follower_id == current.id,
                SingerFollow.followee_id == followee_id,
                SingerFollow.venue_id == venue_id,
                SingerFollow.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    follower_count_result = await db.execute(
        select(func.count())
        .select_from(SingerFollow)
        .where(
            SingerFollow.followee_id == followee_id,
            SingerFollow.venue_id == venue_id,
            SingerFollow.deleted_at.is_(None),
        )
    )
    follower_count = follower_count_result.scalar_one()

    following_count_result = await db.execute(
        select(func.count())
        .select_from(SingerFollow)
        .where(
            SingerFollow.follower_id == followee_id,
            SingerFollow.venue_id == venue_id,
            SingerFollow.deleted_at.is_(None),
        )
    )
    following_count = following_count_result.scalar_one()

    return FollowStatusOut(
        is_following=active_follow is not None,
        follower_count=follower_count,
        following_count=following_count,
        created_at=active_follow.created_at if active_follow else None,
    )


@router.get("/following", response_model=list[FollowOut])
async def list_following(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all singers the current user is following in this venue."""
    _require_venue(venue_id, current)

    stmt = (
        select(SingerFollow, Singer)
        .join(Singer, SingerFollow.followee_id == Singer.id)
        .where(
            SingerFollow.follower_id == current.id,
            SingerFollow.venue_id == venue_id,
            SingerFollow.deleted_at.is_(None),
            Singer.deleted_at.is_(None),
            Singer.deactivated_at.is_(None),
        )
        .order_by(SingerFollow.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    items: list[FollowOut] = []
    for follow, followee in rows:
        items.append(
            FollowOut(
                id=follow.id,
                venue_id=follow.venue_id,
                follower_id=follow.follower_id,
                followee_id=follow.followee_id,
                followee_name=followee.stage_name,
                created_at=follow.created_at,
            )
        )
    return items


@router.get("/followers", response_model=list[FollowOut])
async def list_followers(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all singers following the current user in this venue."""
    _require_venue(venue_id, current)

    stmt = (
        select(SingerFollow, Singer)
        .join(Singer, SingerFollow.follower_id == Singer.id)
        .where(
            SingerFollow.followee_id == current.id,
            SingerFollow.venue_id == venue_id,
            SingerFollow.deleted_at.is_(None),
            Singer.deleted_at.is_(None),
            Singer.deactivated_at.is_(None),
        )
        .order_by(SingerFollow.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    items: list[FollowOut] = []
    for follow, follower in rows:
        items.append(
            FollowOut(
                id=follow.id,
                venue_id=follow.venue_id,
                follower_id=follow.follower_id,
                followee_id=follow.followee_id,
                followee_name=follower.stage_name,
                created_at=follow.created_at,
            )
        )
    return items
