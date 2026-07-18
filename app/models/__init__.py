"""SQLAlchemy ORM models aligned with Scales portable SQL principles.

- UUID TEXT primary keys, app-generated (no DB-side generation).
- venue_id on every tenant table.
- Timestamps stored as TEXT (ISO 8601); application is source of truth.
- Booleans as Integer 0/1 for SQLite↔PostgreSQL portability.
- JSON columns stored as TEXT.
- Soft deletes via deleted_at (NULL = active).
"""

import uuid
import random
import string
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    Text,
    ForeignKey,
    REAL,
    UniqueConstraint,
    CheckConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from app.core.db import Base


_VALID_SUBSCRIPTION_STATUSES = {"trialing", "active", "past_due", "cancelled", "comped"}
_VALID_BILLING_STATUSES = {"trial", "active", "past_due", "cancelled"}
_VALID_SIGNUP_SOURCES = {"self_serve", "sales_assisted"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _venue_code() -> str:
    """Generate a short, readable venue code (6 uppercase alphanumeric)."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def _venue_code_unique(db=None) -> str:
    """Generate a venue code guaranteed unique against the DB."""
    code = _venue_code()
    # callers that pass a session can check collision; otherwise return and let
    # the UNIQUE constraint catch the (extremely unlikely) duplicate.
    return code


# Billing / subscription lifecycle events (Stripe webhook idempotency)
class BillingEvent(Base):
    __tablename__ = "billing_events"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    stripe_event_id = Column(Text, nullable=False)
    event_type = Column(Text, nullable=False)
    stripe_subscription_id = Column(Text)
    payload_json = Column(Text)
    processed = Column(Integer, default=0)
    created_at = Column(Text, default=_now_iso)

    __table_args__ = (
        UniqueConstraint("venue_id", "stripe_event_id", name="uq_billing_event"),
        Index("ix_billing_events_stripe_event_id", "stripe_event_id"),
        Index("ix_billing_events_venue", "venue_id", "created_at"),
    )

    venue = relationship("Venue")


class Venue(Base):
    __tablename__ = "venues"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    name = Column(Text, nullable=False)
    slug = Column(Text, nullable=False, unique=True)
    venue_code = Column(Text, nullable=False, unique=True, default=_venue_code)
    address = Column(Text)
    contact_json = Column(Text)
    timezone = Column(Text, default="UTC")
    locale = Column(Text, default="en")
    branding_json = Column(Text)
    subscription_tier = Column(Text, default="basic")
    is_active = Column(Integer, default=1)

    # Billing / signup fields (Phase 1)
    billing_email = Column(Text)
    subscription_status = Column(Text, default="trialing")
    billing_status = Column(Text, default="trial")
    plan_expires_at = Column(Text)
    trial_ends_at = Column(Text)
    stripe_customer_id = Column(Text)
    stripe_subscription_id = Column(Text)
    signup_source = Column(Text, default="self_serve")
    sales_rep_email = Column(Text)
    plan_features_json = Column(Text)
    admin_notes = Column(Text)

    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)

    __table_args__ = (
        CheckConstraint(
            f"subscription_status IS NULL OR subscription_status IN ({', '.join(repr(s) for s in _VALID_SUBSCRIPTION_STATUSES)})",
            name="ck_venues_subscription_status",
        ),
        CheckConstraint(
            f"billing_status IS NULL OR billing_status IN ({', '.join(repr(s) for s in _VALID_BILLING_STATUSES)})",
            name="ck_venues_billing_status",
        ),
        CheckConstraint(
            f"signup_source IS NULL OR signup_source IN ({', '.join(repr(s) for s in _VALID_SIGNUP_SOURCES)})",
            name="ck_venues_signup_source",
        ),
    )

    # relationships
    songs = relationship("Song", back_populates="venue")
    singers = relationship("Singer", back_populates="venue")
    queue_requests = relationship("QueueRequest", back_populates="venue")
    configs = relationship("VenueConfig", back_populates="venue")
    singer_favorites = relationship("SingerFavorite", back_populates="venue")


class SingerFavorite(Base):
    __tablename__ = "singer_favorites"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    song_id = Column(String(36), ForeignKey("songs.id"), nullable=False)
    created_at = Column(Text, default=_now_iso)

    venue = relationship("Venue", back_populates="singer_favorites")


class SingerFollow(Base):
    __tablename__ = "singer_follows"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    follower_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    followee_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    created_at = Column(Text, default=_now_iso)
    deleted_at = Column(Text)

    __table_args__ = (
        UniqueConstraint("venue_id", "follower_id", "followee_id", name="uq_follow"),
        Index("ix_singer_follows_venue", "venue_id"),
        Index("ix_singer_follows_follower", "follower_id"),
        Index("ix_singer_follows_followee", "followee_id"),
    )


class VenueConfig(Base):
    __tablename__ = "venue_configs"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    config_key = Column(Text, nullable=False)
    config_value = Column(Text)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)

    __table_args__ = (
        UniqueConstraint("venue_id", "config_key"),
    )

    venue = relationship("Venue", back_populates="configs")


class Song(Base):
    __tablename__ = "songs"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    catalog_id = Column(Text)
    title = Column(Text, nullable=False)
    artist = Column(Text, nullable=False)
    album = Column(Text)
    genre = Column(Text)
    category = Column(Text)
    language = Column(Text)
    duration_ms = Column(Integer)
    year = Column(Integer)
    lyrics_url = Column(Text)
    cover_art_url = Column(Text)
    is_available = Column(Integer, default=1)
    is_active = Column(Integer, default=1)
    meta_json = Column(Text)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)
    file_path = Column(Text)
    file_hash = Column(Text)
    file_size = Column(BigInteger)
    unavailable_reason = Column(Text)
    last_scanned_at = Column(Text)
    metadata_locked = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_songs_venue_id", "venue_id"),
        Index("ix_songs_venue_title", "venue_id", "title"),
        Index("ix_songs_venue_artist", "venue_id", "artist"),
        Index("ix_songs_venue_genre", "venue_id", "genre"),
        Index("ix_songs_venue_year", "venue_id", "year"),
        Index("ix_songs_venue_category", "venue_id", "category"),
    )

    venue = relationship("Venue", back_populates="songs")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    email = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text)
    auth_provider = Column(Text)
    auth_provider_id = Column(Text)
    stage_name = Column(Text)  # preferred stage name for new venue joins
    first_name = Column(Text)
    last_name = Column(Text)
    real_name = Column(Text)  # legacy full display name; derived from first/last when absent
    pronouns = Column(Text)
    phone = Column(Text)
    bio = Column(Text)
    avatar_url = Column(Text)
    social_links = Column(Text)
    is_active = Column(Integer, default=1)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)

    __table_args__ = (
        Index("ix_accounts_email", "email"),
    )

    singers = relationship("Singer", back_populates="account")


class Singer(Base):
    __tablename__ = "singers"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    account_id = Column(String(36), ForeignKey("accounts.id"), nullable=True)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    auth_provider = Column(Text)
    auth_provider_id = Column(Text)
    stage_name = Column(Text, nullable=False)
    first_name = Column(Text)
    last_name = Column(Text)
    real_name = Column(Text)  # legacy full display name; derived from first/last when absent
    pronouns = Column(Text)
    email = Column(Text)
    phone = Column(Text)
    notes = Column(Text)
    bio = Column(Text)
    avatar_url = Column(Text)
    social_links = Column(Text)
    role = Column(Text, default="singer")
    password_hash = Column(Text)
    loyalty_tier_id = Column(String(36), ForeignKey("loyalty_tiers.id"))
    total_points = Column(Integer, default=0)
    last_seen = Column(Text)
    deactivated_at = Column(Text)
    gdpr_erased_at = Column(Text)
    linked_singer_id = Column(String(36), ForeignKey("singers.id"))
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)

    __table_args__ = (
        Index("ix_singers_venue_id", "venue_id"),
        Index("singer_venue_idx", "venue_id", "deactivated_at"),
        Index("ix_singers_gdpr_erased", "venue_id", "gdpr_erased_at"),
        UniqueConstraint("account_id", "venue_id", name="uq_singer_account_venue"),
        UniqueConstraint("venue_id", "stage_name", name="uq_singer_venue_stage_name"),
    )

    account = relationship("Account", back_populates="singers")
    venue = relationship("Venue", back_populates="singers")
    check_in_sessions = relationship("CheckInSession", back_populates="singer", lazy="selectin", cascade="all, delete-orphan")
    linked_singer = relationship("Singer", remote_side=[id])


class SingerLinkMergeLog(Base):
    __tablename__ = "singer_link_merge_logs"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    source_singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    target_singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    merged_by_account_id = Column(String(36), ForeignKey("accounts.id"))
    merged_by_kj_device_id = Column(String(36), ForeignKey("kj_devices.id"))
    queue_requests_moved = Column(Integer, default=0)
    payments_moved = Column(Integer, default=0)
    favorites_moved = Column(Integer, default=0)
    achievements_moved = Column(Integer, default=0)
    created_at = Column(Text, default=_now_iso)

    __table_args__ = (
        Index("ix_singer_link_merge_logs_venue", "venue_id", "created_at"),
    )


class CheckInSession(Base):
    __tablename__ = "check_in_sessions"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    checked_in_at = Column(Text, default=_now_iso)
    expires_at = Column(Text)
    table_number = Column(Text)
    created_at = Column(Text, default=_now_iso)

    __table_args__ = (
        Index("ix_checkin_venue_expires", "venue_id", "expires_at"),
        Index("ix_checkin_singer_expires", "singer_id", "expires_at"),
        Index("checkin_session_singer_idx", "singer_id"),
    )

    singer = relationship("Singer", back_populates="check_in_sessions")
    venue = relationship("Venue")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    recipient_id = Column(String(36), ForeignKey("singers.id"), nullable=True)  # tip recipient
    amount_cents = Column(Integer, nullable=False)
    currency = Column(Text, default="USD")
    payment_type = Column(Text, nullable=False)  # tip | priority_bump
    stripe_payment_intent_id = Column(Text, unique=True)
    status = Column(Text, nullable=False, default="pending")  # pending | succeeded | failed | canceled | refunded
    message = Column(Text)  # tip message from sender (HTML-escaped on display)
    metadata_json = Column(Text)
    reference_type = Column(Text)  # e.g. queue_request
    reference_id = Column(Text)
    refunded_at = Column(Text)
    refund_amount_cents = Column(Integer, default=0)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)

    __table_args__ = (
        CheckConstraint("payment_type IN ('tip','priority_bump')"),
        CheckConstraint("status IN ('pending','succeeded','failed','canceled','refunded','partially_refunded')"),
        Index("ix_payments_venue_singer", "venue_id", "singer_id"),
        Index("ix_payments_stripe_pi", "stripe_payment_intent_id"),
    )


class SongCategory(Base):
    __tablename__ = "song_categories"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    name = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0)
    color = Column(Text)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)


class SongCategoryMapping(Base):
    __tablename__ = "song_category_mappings"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    song_id = Column(String(36), ForeignKey("songs.id"), nullable=False)
    category_id = Column(String(36), ForeignKey("song_categories.id"), nullable=False)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    created_at = Column(Text, default=_now_iso)


class QueueRequest(Base):
    __tablename__ = "queue_requests"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=True)  # nullable before link
    song_id = Column(String(36), ForeignKey("songs.id"), nullable=False)
    status = Column(Text, nullable=False)  # pending|approved|now_playing|completed|skipped|rejected
    notes = Column(Text)
    reject_reason = Column(Text)
    rotation_position = Column(Integer)
    kj_id = Column(Text)
    requested_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    played_at = Column(Text)
    deleted_at = Column(Text)

    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','up_next','now_playing','completed','skipped','rejected')"),
        Index("ix_queue_venue_status", "venue_id", "status"),
        Index("queue_position_idx", "venue_id", "rotation_position"),
        Index("ix_queue_requests_singer_status", "singer_id", "status"),
    )

    venue = relationship("Venue", back_populates="queue_requests")
    singer = relationship("Singer")
    song = relationship("Song")


class SingerRemoval(Base):
    __tablename__ = "singer_removals"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    removed_by_device_id = Column(String(36), ForeignKey("kj_devices.id"), nullable=True)
    removed_by_account_id = Column(String(36), ForeignKey("accounts.id"), nullable=True)
    removed_at = Column(Text, default=_now_iso)
    acknowledged_at = Column(Text)

    __table_args__ = (
        Index("ix_singer_removals_venue_singer", "venue_id", "singer_id"),
        Index("ix_singer_removals_venue_ack", "venue_id", "acknowledged_at"),
    )


class RotationSession(Base):
    __tablename__ = "rotation_sessions"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    name = Column(Text)
    mode = Column(Text, nullable=False)  # fifo|weighted|vip_priority
    started_at = Column(Text)
    ended_at = Column(Text)
    is_active = Column(Integer, default=1)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)

    __table_args__ = (
        CheckConstraint("mode IN ('fifo','weighted','vip_priority')"),
    )


class RotationEntry(Base):
    __tablename__ = "rotation_entries"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    rotation_session_id = Column(String(36), ForeignKey("rotation_sessions.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    queue_request_id = Column(String(36), ForeignKey("queue_requests.id"))
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    position = Column(Integer, nullable=False)
    weight = Column(REAL, default=1.0)
    sang_at = Column(Text)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)


class LoyaltyTier(Base):
    __tablename__ = "loyalty_tiers"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    name = Column(Text, nullable=False)
    min_points = Column(Integer, default=0)
    multiplier = Column(REAL, default=1.0)
    color = Column(Text)
    icon = Column(Text)
    is_active = Column(Integer, default=1)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)


class LoyaltyPoints(Base):
    __tablename__ = "loyalty_points"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    reason = Column(Text)
    reference_type = Column(Text)
    reference_id = Column(Text)
    created_at = Column(Text, default=_now_iso)


class LoyaltyQuest(Base):
    __tablename__ = "loyalty_quests"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    criteria_json = Column(Text)
    reward_points = Column(Integer, default=0)
    is_active = Column(Integer, default=1)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)


class LoyaltyQuestCompletion(Base):
    __tablename__ = "loyalty_quest_completions"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    quest_id = Column(String(36), ForeignKey("loyalty_quests.id"), nullable=False)
    completed_at = Column(Text)
    created_at = Column(Text, default=_now_iso)


class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text)
    sku = Column(Text)
    price_cents = Column(Integer, nullable=False)
    currency = Column(Text, default="USD")
    image_url = Column(Text)
    is_active = Column(Integer, default=1)
    stock_quantity = Column(Integer, default=0)
    dropshipper_id = Column(String(36), ForeignKey("dropshippers.id"))
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    stripe_payment_intent_id = Column(Text, unique=True)
    status = Column(Text, nullable=False)
    total_cents = Column(Integer, nullable=False)
    currency = Column(Text, default="USD")
    shipping_address_json = Column(Text)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price_cents = Column(Integer, nullable=False)
    created_at = Column(Text, default=_now_iso)


class Dropshipper(Base):
    __tablename__ = "dropshippers"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    name = Column(Text, nullable=False)
    api_endpoint = Column(Text)
    auth_config_json = Column(Text)
    is_active = Column(Integer, default=1)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)


class Leaderboard(Base):
    __tablename__ = "leaderboards"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    name = Column(Text, nullable=False)
    metric_type = Column(Text, nullable=False)
    period_start = Column(Text)
    period_end = Column(Text)
    is_active = Column(Integer, default=1)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)
    deleted_at = Column(Text)


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    leaderboard_id = Column(String(36), ForeignKey("leaderboards.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    score = Column(REAL, default=0.0)
    rank = Column(Integer)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)


class Consent(Base):
    __tablename__ = "consents"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    consent_type = Column(Text, nullable=False)
    granted = Column(Integer, default=0)
    granted_at = Column(Text)
    ip_address = Column(Text)
    metadata_json = Column(Text)
    created_at = Column(Text, default=_now_iso)


class ShareEvent(Base):
    __tablename__ = "share_events"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"))
    platform = Column(Text)
    url = Column(Text)
    content_type = Column(Text)
    created_at = Column(Text, default=_now_iso)


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    event_type = Column(Text, nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"))
    song_id = Column(String(36), ForeignKey("songs.id"))
    session_id = Column(Text)
    payload_json = Column(Text)
    created_at = Column(Text, default=_now_iso)


class AnalyticsMetric(Base):
    __tablename__ = "analytics_metrics"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    metric_name = Column(Text, nullable=False)
    dimensions_json = Column(Text)
    value = Column(REAL, default=0.0)
    bucket_start = Column(Text)
    bucket_end = Column(Text)
    granularity = Column(Text)
    created_at = Column(Text, default=_now_iso)


class Export(Base):
    __tablename__ = "exports"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    export_type = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    filter_params_json = Column(Text)
    file_url = Column(Text)
    file_size = Column(Integer)
    created_by = Column(Text)
    created_at = Column(Text, default=_now_iso)
    completed_at = Column(Text)
    deleted_at = Column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    user_id = Column(String(36), ForeignKey("singers.id"), nullable=True)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=True)
    action = Column(Text, nullable=False)
    resource_type = Column(Text)
    resource_id = Column(Text)
    result = Column(Text, nullable=False)
    status_code = Column(Integer)
    ip_address = Column(Text)
    user_agent = Column(Text)
    request_id = Column(Text)
    details_json = Column(Text)
    created_at = Column(Text, default=_now_iso)

    __table_args__ = (
        Index("ix_audit_logs_user", "user_id", "created_at"),
        Index("ix_audit_logs_venue", "venue_id", "created_at"),
        Index("ix_audit_logs_action", "action", "created_at"),
    )


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    admin_email = Column(Text, nullable=False)
    action = Column(Text, nullable=False)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=True)
    venue_name = Column(Text, nullable=True)
    details_json = Column(Text)
    created_at = Column(Text, default=_now_iso)

    __table_args__ = (
        Index("ix_admin_audit_logs_venue", "venue_id", "created_at"),
        Index("ix_admin_audit_logs_action", "action", "created_at"),
        Index("ix_admin_audit_logs_admin", "admin_email", "created_at"),
    )


class PointsLedger(Base):
    __tablename__ = "points_ledger"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    reason = Column(Text)
    reference_type = Column(Text)  # checkin | request | perform | tip
    reference_id = Column(Text)
    created_at = Column(Text, default=_now_iso)

    __table_args__ = (
        Index("ix_points_venue_singer", "venue_id", "singer_id"),
        Index("ix_points_venue_created", "venue_id", "created_at"),
        Index("ix_points_singer_type", "singer_id", "reference_type"),
    )


class SingerAchievement(Base):
    __tablename__ = "singer_achievements"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    achievement_key = Column(Text, nullable=False)  # first_song | iron_lungs | regular | big_spender
    unlocked_at = Column(Text)
    progress = Column(Integer, default=0)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)

    __table_args__ = (
        UniqueConstraint("venue_id", "singer_id", "achievement_key", name="uq_singer_achievement"),
        Index("ix_singer_achievements_singer", "singer_id"),
    )


class KJSession(Base):
    __tablename__ = "kj_sessions"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    device_id = Column(Text, nullable=False, unique=True)
    device_name = Column(Text)
    started_at = Column(Text)
    last_heartbeat_at = Column(Text)
    current_rotation_session_id = Column(String(36), ForeignKey("rotation_sessions.id"))
    state_snapshot_json = Column(Text)
    sync_checkpoint_at = Column(Text)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)


class SyncCheckpoint(Base):
    __tablename__ = "sync_checkpoints"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    kj_session_id = Column(String(36), ForeignKey("kj_sessions.id"), nullable=False)
    table_name = Column(Text, nullable=False)
    last_synced_at = Column(Text)
    last_record_id = Column(Text)
    checksum = Column(Text)
    direction = Column(Text, nullable=False)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)


class KJDevice(Base):
    __tablename__ = "kj_devices"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    name = Column(Text, nullable=False)
    api_key_hash = Column(Text, nullable=False)
    created_at = Column(Text, default=_now_iso)
    last_seen = Column(Text)
    revoked_at = Column(Text)


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    platform = Column(Text, nullable=False)  # fcm | apns
    token = Column(Text, nullable=False)
    device_name = Column(Text)
    is_active = Column(Integer, default=1)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)

    __table_args__ = (
        UniqueConstraint("singer_id", "platform", "token", name="uq_device_token"),
        Index("ix_device_tokens_singer", "singer_id"),
        Index("ix_device_tokens_venue", "venue_id"),
    )


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    up_soon = Column(Integer, default=1)
    on_stage = Column(Integer, default=1)
    bumped = Column(Integer, default=1)
    queue_update = Column(Integer, default=1)
    announcement = Column(Integer, default=1)
    social = Column(Integer, default=1)
    payment = Column(Integer, default=1)
    created_at = Column(Text, default=_now_iso)
    updated_at = Column(Text, default=_now_iso, onupdate=_now_iso)

    __table_args__ = (
        UniqueConstraint("singer_id", "venue_id", name="uq_notification_setting"),
        Index("ix_notification_settings_singer", "singer_id"),
        Index("ix_notification_settings_venue", "venue_id"),
    )


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    singer_id = Column(String(36), ForeignKey("singers.id"), nullable=False)
    venue_id = Column(String(36), ForeignKey("venues.id"), nullable=False)
    notification_type = Column(Text, nullable=False)  # up_soon | on_stage | bumped | general
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    data_json = Column(Text)  # extra payload
    is_read = Column(Integer, default=0)
    sent_at = Column(Text, default=_now_iso)
    read_at = Column(Text)
    created_at = Column(Text, default=_now_iso)

    __table_args__ = (
        Index("ix_notifications_singer", "singer_id", "created_at"),
        Index("ix_notifications_unread", "singer_id", "is_read"),
    )
