"""Deduplicate venue singers that share the same account_id."""
import asyncio
from sqlalchemy import select, update, and_, func
from app.core.db import AsyncSessionLocal
from app.models import (
    Singer, Account,
    QueueRequest, RotationEntry, CheckInSession,
    Payment, Order, LoyaltyPoints, LoyaltyQuestCompletion,
    PointsLedger, SingerAchievement, LeaderboardEntry,
    DeviceToken, NotificationSetting, Notification, ShareEvent,
    SingerFavorite, SingerFollow, AuditLog,
)

TABLES_AND_COLUMNS = [
    (QueueRequest, "singer_id"),
    (RotationEntry, "singer_id"),
    (CheckInSession, "singer_id"),
    (Payment, "singer_id"),
    (Order, "singer_id"),
    (LoyaltyPoints, "singer_id"),
    (LoyaltyQuestCompletion, "singer_id"),
    (PointsLedger, "singer_id"),
    (SingerAchievement, "singer_id"),
    (LeaderboardEntry, "singer_id"),
    (DeviceToken, "singer_id"),
    (NotificationSetting, "singer_id"),
    (Notification, "singer_id"),
    (ShareEvent, "singer_id"),
    (SingerFavorite, "singer_id"),
    (SingerFollow, "singer_id"),
    (SingerFollow, "followed_singer_id"),
    (AuditLog, "user_id"),
]


async def _count_records(db, singer_id, venue_id):
    total = 0
    for table, col in TABLES_AND_COLUMNS:
        stmt = select(func.count()).select_from(table).where(getattr(table, col) == singer_id)
        if hasattr(table, "venue_id"):
            stmt = stmt.where(table.venue_id == venue_id)
        result = await db.execute(stmt)
        total += result.scalar() or 0
    return total


async def deduplicate():
    async with AsyncSessionLocal() as db:
        subq = (
            select(Singer.venue_id, Singer.account_id)
            .where(
                and_(
                    Singer.account_id.is_not(None),
                    Singer.account_id != "",
                    Singer.deleted_at.is_(None),
                )
            )
            .group_by(Singer.venue_id, Singer.account_id)
            .having(func.count(Singer.id) > 1)
        )
        result = await db.execute(subq)
        groups = result.all()
        if not groups:
            return {"message": "No duplicate (venue_id, account_id) groups found.", "groups": 0, "deleted": 0}
        log = []
        total_deleted = 0
        for venue_id, account_id in groups:
            singers_result = await db.execute(
                select(Singer, Account)
                .outerjoin(Account, Singer.account_id == Account.id)
                .where(
                    and_(
                        Singer.venue_id == venue_id,
                        Singer.account_id == account_id,
                        Singer.deleted_at.is_(None),
                    )
                )
            )
            rows = singers_result.all()
            singers = [r[0] for r in rows]
            account = rows[0][1] if rows else None

            async def score(s):
                recs = await _count_records(db, s.id, venue_id)
                name_match = 0
                if account:
                    names = {account.stage_name or "", account.email.split("@")[0] if account.email else ""}
                    if s.stage_name and s.stage_name.strip() in names:
                        name_match = 1
                return (recs, name_match, s.created_at or "")

            scored = [(await score(s), s) for s in singers]
            scored.sort(key=lambda x: x[0], reverse=True)
            canonical = scored[0][1]
            duplicates = [s for _, s in scored[1:]]
            moved_total = 0
            for dup in duplicates:
                for table, col in TABLES_AND_COLUMNS:
                    stmt = (
                        update(table)
                        .where(getattr(table, col) == dup.id)
                        .values({col: canonical.id})
                    )
                    if hasattr(table, "venue_id"):
                        stmt = stmt.where(table.venue_id == venue_id)
                    res = await db.execute(stmt)
                    moved_total += res.rowcount
                dup.deleted_at = func.now()
                total_deleted += 1
            log.append({
                "venue_id": str(venue_id),
                "account_id": str(account_id),
                "canonical_singer_id": str(canonical.id),
                "canonical_stage_name": canonical.stage_name,
                "duplicate_ids": [str(s.id) for s in duplicates],
                "moved_records": moved_total,
            })
        await db.commit()
        return {"groups": len(groups), "duplicates_deleted": total_deleted, "details": log}


if __name__ == "__main__":
    outcome = asyncio.run(deduplicate())
    print(outcome)
