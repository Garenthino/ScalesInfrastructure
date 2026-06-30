"""Venue purge service: hard-delete or billing-aware anonymization.

Compliance rules
----------------
- If a venue has NO billing history (no Payment or Order rows with status in
  a successful/paid state), hard-delete the venue and all related tenant data.
- If billing history exists, anonymize personal data but keep financial
  records (amounts, dates, tiers, commission/affiliate payout data).

Deletion order is determined by foreign keys:
    leaf tables first, then parent tables.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import delete, func

from app.models import (
    Venue,
    Singer,
    Song,
    QueueRequest,
    VenueConfig,
    SingerFavorite,
    SingerFollow,
    CheckInSession,
    Payment,
    Order,
    OrderItem,
    Product,
    Dropshipper,
    SongCategory,
    SongCategoryMapping,
    RotationSession,
    RotationEntry,
    LoyaltyTier,
    LoyaltyPoints,
    LoyaltyQuest,
    LoyaltyQuestCompletion,
    Leaderboard,
    LeaderboardEntry,
    Consent,
    ShareEvent,
    AnalyticsEvent,
    AnalyticsMetric,
    Export,
    AuditLog,
    AdminAuditLog,
    PointsLedger,
    SingerAchievement,
    KJSession,
    SyncCheckpoint,
    KJDevice,
    DeviceToken,
    NotificationSetting,
    Notification,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _anonymize_token() -> str:
    """Return a short random token used for hashing/anonymization."""
    return uuid.uuid4().hex[:16]


def _hash(text: str | None, salt: str) -> str | None:
    if not text:
        return None
    return hmac.new(salt.encode(), text.encode(), hashlib.sha256).hexdigest()[:32]


# Statuses that constitute actual billing history we must preserve.
_PAYMENT_BILLING_STATUSES = {"succeeded", "refunded", "partially_refunded"}
_ORDER_BILLING_STATUSES = {"paid", "shipped", "delivered", "refunded", "partially_refunded"}


async def venue_has_billing_history(db: AsyncSession, venue_id: str) -> bool:
    """Return True if the venue has any payment or order records that are
    financially material (paid, refunded, etc.)."""
    payment_count = (
        await db.execute(
            select(func.count())
            .select_from(Payment)
            .where(
                Payment.venue_id == venue_id,
                Payment.status.in_(_PAYMENT_BILLING_STATUSES),
                Payment.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if payment_count:
        return True

    order_count = (
        await db.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.venue_id == venue_id,
                Order.status.in_(_ORDER_BILLING_STATUSES),
                Order.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    return order_count > 0


async def anonymize_venue(db: AsyncSession, venue_id: str) -> dict[str, Any]:
    """Anonymize all personal data for a venue while keeping financial records."""
    venue = (
        await db.execute(select(Venue).where(Venue.id == venue_id))
    ).scalar_one_or_none()
    if venue is None:
        raise ValueError(f"Venue {venue_id} not found")

    salt = _anonymize_token()
    now = _now_iso()

    # Anonymize venue identity/contact
    venue.name = f"Anonymized Venue ({venue.id[:8]})"
    venue.slug = f"anonymized-{venue.id[:8]}"
    venue.venue_code = f"ANON{venue.id[:4].upper()}"
    venue.address = None
    venue.contact_json = json.dumps({"phone": None, "email": None})
    venue.branding_json = None
    venue.billing_email = None
    venue.admin_notes = None
    venue.sales_rep_email = None
    venue.stripe_customer_id = _hash(str(venue.stripe_customer_id), salt)
    venue.stripe_subscription_id = _hash(str(venue.stripe_subscription_id), salt)
    venue.is_active = 0
    # Keep: subscription_tier, subscription_status, billing_status,
    # plan_expires_at, trial_ends_at, signup_source, plan_features_json.
    venue.updated_at = now

    # Anonymize singers
    singers = (
        await db.execute(select(Singer).where(Singer.venue_id == venue_id))
    ).scalars().all()
    for singer in singers:
        singer.stage_name = f"Singer {singer.id[:8]}"
        singer.real_name = None
        singer.email = _hash(str(singer.email), salt)
        singer.phone = _hash(str(singer.phone), salt)
        singer.bio = None
        singer.notes = None
        singer.social_links = None
        singer.avatar_url = None
        singer.pronouns = None
        singer.auth_provider_id = _hash(str(singer.auth_provider_id), salt)
        singer.password_hash = None

    # Remove non-financial PII: device tokens, notification settings,
    # notification content, consents, share events.
    await db.execute(delete(DeviceToken).where(DeviceToken.venue_id == venue_id))
    await db.execute(delete(NotificationSetting).where(NotificationSetting.venue_id == venue_id))
    await db.execute(delete(Notification).where(Notification.venue_id == venue_id))
    await db.execute(delete(Consent).where(Consent.venue_id == venue_id))
    await db.execute(delete(ShareEvent).where(ShareEvent.venue_id == venue_id))
    await db.execute(delete(Export).where(Export.venue_id == venue_id))

    # Audit trail: keep the log rows but scrub references to PII where safe.
    audit_rows = (
        await db.execute(select(AuditLog).where(AuditLog.venue_id == venue_id))
    ).scalars().all()
    for row in audit_rows:
        row.ip_address = None
        row.user_agent = None
        row.details_json = None

    await db.commit()

    return {
        "action": "anonymize",
        "venue_id": venue_id,
        "salt_truncated": salt[:4],
        "anonymized_singer_count": len(singers),
        "anonymized_at": now,
    }


async def hard_delete_venue(db: AsyncSession, venue_id: str) -> dict[str, Any]:
    """Hard-delete a venue and all related tenant data in FK-safe order."""
    venue = (
        await db.execute(select(Venue).where(Venue.id == venue_id))
    ).scalar_one_or_none()
    if venue is None:
        raise ValueError(f"Venue {venue_id} not found")

    # Order matters: delete child rows before parents.
    # 1. Queue / rotation (children of singers/songs)
    await db.execute(delete(RotationEntry).where(RotationEntry.venue_id == venue_id))
    await db.execute(delete(RotationSession).where(RotationSession.venue_id == venue_id))
    await db.execute(delete(QueueRequest).where(QueueRequest.venue_id == venue_id))

    # 2. Commerce
    await db.execute(
        delete(OrderItem).where(
            OrderItem.order_id.in_(
                select(Order.id).where(Order.venue_id == venue_id)
            )
        )
    )
    await db.execute(delete(Order).where(Order.venue_id == venue_id))
    await db.execute(delete(Product).where(Product.venue_id == venue_id))
    await db.execute(delete(Dropshipper).where(Dropshipper.venue_id == venue_id))

    # 3. Payments
    await db.execute(delete(Payment).where(Payment.venue_id == venue_id))

    # 4. Songs + categories
    await db.execute(
        delete(SongCategoryMapping).where(
            SongCategoryMapping.song_id.in_(
                select(Song.id).where(Song.venue_id == venue_id)
            )
        )
    )
    await db.execute(
        delete(SongCategoryMapping).where(SongCategoryMapping.category_id.in_(
            select(SongCategory.id).where(SongCategory.venue_id == venue_id)
        ))
    )
    await db.execute(delete(SingerFavorite).where(SingerFavorite.venue_id == venue_id))
    await db.execute(delete(Song).where(Song.venue_id == venue_id))
    await db.execute(delete(SongCategory).where(SongCategory.venue_id == venue_id))

    # 5. Loyalty + leaderboard + points
    await db.execute(delete(LoyaltyPoints).where(LoyaltyPoints.venue_id == venue_id))
    await db.execute(delete(LoyaltyQuestCompletion).where(LoyaltyQuestCompletion.venue_id == venue_id))
    await db.execute(delete(LoyaltyQuest).where(LoyaltyQuest.venue_id == venue_id))
    await db.execute(delete(LoyaltyTier).where(LoyaltyTier.venue_id == venue_id))
    await db.execute(delete(PointsLedger).where(PointsLedger.venue_id == venue_id))
    await db.execute(delete(SingerAchievement).where(SingerAchievement.venue_id == venue_id))
    await db.execute(delete(LeaderboardEntry).where(LeaderboardEntry.venue_id == venue_id))
    await db.execute(delete(Leaderboard).where(Leaderboard.venue_id == venue_id))

    # 6. Singer social/checkins
    await db.execute(delete(SingerFollow).where(SingerFollow.venue_id == venue_id))
    await db.execute(delete(CheckInSession).where(CheckInSession.venue_id == venue_id))
    await db.execute(delete(DeviceToken).where(DeviceToken.venue_id == venue_id))
    await db.execute(delete(NotificationSetting).where(NotificationSetting.venue_id == venue_id))
    await db.execute(delete(Notification).where(Notification.venue_id == venue_id))

    # 7. Analytics / audit / exports / consents / share events
    await db.execute(delete(AnalyticsEvent).where(AnalyticsEvent.venue_id == venue_id))
    await db.execute(delete(AnalyticsMetric).where(AnalyticsMetric.venue_id == venue_id))
    await db.execute(delete(AuditLog).where(AuditLog.venue_id == venue_id))
    await db.execute(delete(AdminAuditLog).where(AdminAuditLog.venue_id == venue_id))
    await db.execute(delete(Export).where(Export.venue_id == venue_id))
    await db.execute(delete(Consent).where(Consent.venue_id == venue_id))
    await db.execute(delete(ShareEvent).where(ShareEvent.venue_id == venue_id))

    # 8. KJ / sync
    await db.execute(delete(SyncCheckpoint).where(SyncCheckpoint.venue_id == venue_id))
    await db.execute(delete(KJSession).where(KJSession.venue_id == venue_id))
    await db.execute(delete(KJDevice).where(KJDevice.venue_id == venue_id))

    # 9. Venue config + singers
    await db.execute(delete(VenueConfig).where(VenueConfig.venue_id == venue_id))
    await db.execute(delete(Singer).where(Singer.venue_id == venue_id))

    # 10. Venue itself
    await db.execute(delete(Venue).where(Venue.id == venue_id))
    await db.commit()

    return {
        "action": "hard_delete",
        "venue_id": venue_id,
        "deleted_at": _now_iso(),
    }


async def purge_venue(db: AsyncSession, venue_id: str) -> dict[str, Any]:
    """Public entrypoint: hard-delete if no billing history, otherwise anonymize."""
    has_billing = await venue_has_billing_history(db, venue_id)
    if has_billing:
        return await anonymize_venue(db, venue_id)
    return await hard_delete_venue(db, venue_id)


async def purge_expired_soft_deleted_venues(
    db: AsyncSession,
    retention_days: int | None = None,
) -> list[dict[str, Any]]:
    """Find venues whose deleted_at is older than retention_days and purge them.

    Returns a list of purge result dicts for each venue processed.
    """
    from app.core.config import settings

    if retention_days is None:
        retention_days = settings.PURGE_RETENTION_DAYS

    cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=retention_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = (
        await db.execute(
            select(Venue.id).where(
                Venue.deleted_at.isnot(None),
                Venue.deleted_at < cutoff_iso,
            )
        )
    ).scalars().all()

    results: list[dict[str, Any]] = []
    for venue_id in rows:
        try:
            results.append(await purge_venue(db, venue_id))
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to purge venue %s: %s", venue_id, exc)
            results.append({"action": "error", "venue_id": venue_id, "error": str(exc)})
    return results
