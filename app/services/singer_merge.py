"""Service for merging a local (non-mobile) singer into a mobile-linked singer."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, or_

from datetime import datetime, timezone

from app.models import (
    Account,
    AuditLog,
    CheckInSession,
    DeviceToken,
    LeaderboardEntry,
    LoyaltyPoints,
    LoyaltyQuestCompletion,
    Notification,
    NotificationSetting,
    Order,
    Payment,
    PointsLedger,
    QueueRequest,
    RotationEntry,
    ShareEvent,
    Singer,
    SingerAchievement,
    SingerFavorite,
    SingerFollow,
    SingerLinkMergeLog,
)
from app.schemas.dto import SingerLinkMergeOut


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def merge_local_singer_into_mobile(
    db: AsyncSession,
    venue_id: str,
    local_singer_id: str,
    target_singer_id: str | None = None,
    target_account_email: str | None = None,
    merged_by_account_id: str | None = None,
    merged_by_kj_device_id: str | None = None,
) -> SingerLinkMergeOut:
    """Reassign all of a local singer's records to a mobile-linked target singer.

    The local singer is soft-deleted. The target singer's `linked_singer_id`
    may be set to the local singer's id for audit/traceability if it was not
    already linked.
    """
    # Resolve local singer
    local_result = await db.execute(
        select(Singer).where(
            and_(
                Singer.id == local_singer_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    )
    local = local_result.scalar_one_or_none()
    if local is None:
        raise ValueError("Local singer not found")
    if (local.account_id or "").strip():
        raise ValueError("Source singer is already mobile-linked; only local-only singers can be merged")

    # Resolve target singer
    target: Singer | None = None
    if target_singer_id:
        target_result = await db.execute(
            select(Singer).where(
                and_(
                    Singer.id == target_singer_id,
                    Singer.venue_id == venue_id,
                    Singer.deleted_at.is_(None),
                )
            )
        )
        target = target_result.scalar_one_or_none()
    elif target_account_email:
        # Find the account by email, then its venue singer row.
        account_result = await db.execute(
            select(Account).where(Account.email.ilike(target_account_email.strip()))
        )
        account = account_result.scalar_one_or_none()
        if account is not None:
            singer_result = await db.execute(
                select(Singer).where(
                    and_(
                        Singer.account_id == account.id,
                        Singer.venue_id == venue_id,
                        Singer.deleted_at.is_(None),
                    )
                )
            )
            target = singer_result.scalar_one_or_none()

    if target is None:
        raise ValueError("Target mobile-linked singer not found")
    if not (target.account_id or "").strip():
        raise ValueError("Target singer must be mobile-linked (have an account)")
    if target.id == local.id:
        raise ValueError("Cannot merge a singer into itself")

    # -----------------------------------------------------------------
    # Reassign records. Update statements are used for speed and to avoid
    # loading large histories into memory.
    # -----------------------------------------------------------------
    moved: dict[str, int] = {}

    async def _update_count(table, singer_col: str = "singer_id", venue_filter: bool = True) -> int:
        stmt = (
            update(table)
            .where(getattr(table, singer_col) == local.id)
            .values({singer_col: target.id})
        )
        if venue_filter and hasattr(table, "venue_id"):
            stmt = stmt.where(table.venue_id == venue_id)
        result = await db.execute(stmt)
        return result.rowcount

    moved["queue_requests"] = await _update_count(QueueRequest)
    moved["rotation_entries"] = await _update_count(RotationEntry)
    moved["check_in_sessions"] = await _update_count(CheckInSession)
    moved["payments"] = await _update_count(Payment)
    moved["orders"] = await _update_count(Order)
    moved["loyalty_points"] = await _update_count(LoyaltyPoints)
    moved["loyalty_quest_completions"] = await _update_count(LoyaltyQuestCompletion)
    moved["points_ledger"] = await _update_count(PointsLedger)
    moved["singer_achievements"] = await _update_count(SingerAchievement)
    moved["leaderboard_entries"] = await _update_count(LeaderboardEntry)
    moved["device_tokens"] = await _update_count(DeviceToken)
    moved["notification_settings"] = await _update_count(NotificationSetting)
    moved["notifications"] = await _update_count(Notification)
    moved["share_events"] = await _update_count(ShareEvent)

    # Favorites / follows: reassign source favorites to target, but skip
    # duplicate keys to avoid unique-constraint violations.
    fav_result = await db.execute(
        select(SingerFavorite.id).where(SingerFavorite.singer_id == local.id)
    )
    fav_ids = [r[0] for r in fav_result.all()]
    if fav_ids:
        # Collect source song ids for conflict detection.
        song_result = await db.execute(
            select(SingerFavorite.song_id).where(SingerFavorite.singer_id == local.id)
        )
        source_song_ids = {r[0] for r in song_result.all() if r[0]}
        if source_song_ids:
            await db.execute(
                SingerFavorite.__table__.delete().where(
                    and_(
                        SingerFavorite.singer_id == target.id,
                        SingerFavorite.song_id.in_(list(source_song_ids)),
                    )
                )
            )
        fav_update = await db.execute(
            update(SingerFavorite)
            .where(SingerFavorite.id.in_(fav_ids))
            .values(singer_id=target.id)
        )
        moved["favorites"] = fav_update.rowcount
    else:
        moved["favorites"] = 0

    follow_result = await db.execute(
        select(SingerFollow.id).where(
            or_(SingerFollow.follower_id == local.id, SingerFollow.followee_id == local.id)
        )
    )
    follow_ids = [r[0] for r in follow_result.all()]
    if follow_ids:
        follower_update = await db.execute(
            update(SingerFollow)
            .where(SingerFollow.follower_id == local.id)
            .values(follower_id=target.id)
        )
        followee_update = await db.execute(
            update(SingerFollow)
            .where(SingerFollow.followee_id == local.id)
            .values(followee_id=target.id)
        )
        moved["follows"] = follower_update.rowcount + followee_update.rowcount
    else:
        moved["follows"] = 0

    # Soft-delete the local singer.
    now = _now_iso()
    local.deleted_at = now
    local.linked_singer_id = target.id
    target.linked_singer_id = target.linked_singer_id or local.id
    target.updated_at = now

    # Audit log
    log = SingerLinkMergeLog(
        venue_id=venue_id,
        source_singer_id=str(local.id),
        target_singer_id=str(target.id),
        merged_by_account_id=merged_by_account_id,
        merged_by_kj_device_id=merged_by_kj_device_id,
        queue_requests_moved=moved.get("queue_requests", 0),
        payments_moved=moved.get("payments", 0),
        favorites_moved=moved.get("favorites", 0),
        achievements_moved=moved.get("singer_achievements", 0),
    )
    db.add(log)

    # Note: caller is responsible for committing the session.
    return SingerLinkMergeOut(
        local_singer_id=str(local.id),
        target_singer_id=str(target.id),
        account_id=target.account_id,
        merged_records=moved,
    )
