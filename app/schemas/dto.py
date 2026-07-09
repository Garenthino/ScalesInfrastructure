"""Pydantic request/response schemas for the Scales API.

Organized by domain: venues, songs, singers, queue, loyalty, commerce, analytics.
"""

from typing import Any, Literal

import json

from pydantic import BaseModel, Field, ConfigDict, EmailStr, field_validator


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

class ScalesModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PaginatedResponse[T](ScalesModel):
    items: list[T]
    total: int
    page: int
    per_page: int


class ProblemDetail(ScalesModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None


# ---------------------------------------------------------------------------
# Accounts (global mobile identity)
# ---------------------------------------------------------------------------

class AccountRegisterRequest(ScalesModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    stage_name: str = Field(..., min_length=1, max_length=50)
    real_name: str | None = None
    pronouns: str | None = None
    phone: str | None = None
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=500)
    social_links: str | None = Field(None, max_length=1000)


class AccountLoginRequest(ScalesModel):
    email: EmailStr
    password: str


class AccountMeOut(ScalesModel):
    id: str
    email: str
    real_name: str | None = None
    pronouns: str | None = None
    phone: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    social_links: str | None = None
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None


class AccountMeUpdate(ScalesModel):
    real_name: str | None = None
    pronouns: str | None = None
    phone: str | None = None
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=500)
    social_links: list[dict[str, Any]] | str | None = None

    @field_validator("social_links", mode="before")
    @classmethod
    def _normalize_social_links(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)


class TokenPairOut(ScalesModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    account_id: str


class AccountRegisterResponse(TokenPairOut):
    message: str = "Account created"


class ProblemDetail(ScalesModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None


class SingerLinkRequest(ScalesModel):
    target_singer_id: str | None = None
    target_account_email: str | None = None


class SingerLinkMergeOut(ScalesModel):
    local_singer_id: str
    target_singer_id: str
    account_id: str | None = None
    merged_records: dict[str, int]


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------

class VenueAddress(ScalesModel):
    """Venue address fields; all optional."""

    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    country: str | None = None


class VenueContact(ScalesModel):
    phone: str | None = None
    email: str | None = None


class VenueBranding(ScalesModel):
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    logo_url: str | None = None
    favicon_url: str | None = None


class VenueSettings(ScalesModel):
    max_queue_depth: int = 50
    require_approval: bool = False
    allow_duplicates: bool = True
    rotation_mode: Literal["fifo", "weighted", "vip_priority"] = "fifo"


class VenueOperatingHours(ScalesModel):
    timezone: str = "America/New_York"
    schedule: list[dict[str, Any]] = Field(default_factory=list)


class VenueBase(ScalesModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)
    venue_code: str | None = Field(None, min_length=6, max_length=6, pattern=r"^[A-Z0-9]{6}$")
    address: VenueAddress = Field(default_factory=lambda: VenueAddress())
    contact: VenueContact = Field(default_factory=lambda: VenueContact())
    timezone: str = Field(default="UTC", max_length=50)
    branding: VenueBranding = Field(default_factory=lambda: VenueBranding())
    settings: VenueSettings = Field(default_factory=lambda: VenueSettings())
    operating_hours: VenueOperatingHours = Field(default_factory=lambda: VenueOperatingHours())


class VenueCreate(VenueBase):
    pass


class VenueUpdate(ScalesModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    slug: str | None = Field(None, min_length=1, max_length=100)
    venue_code: str | None = Field(None, min_length=6, max_length=6, pattern=r"^[A-Z0-9]{6}$")
    address: VenueAddress | None = None
    contact: VenueContact | None = None
    timezone: str | None = Field(None, max_length=50)
    branding: VenueBranding | None = None
    settings: VenueSettings | None = None
    operating_hours: VenueOperatingHours | None = None


class VenueStats(ScalesModel):
    queue_depth: int = 0
    current_song: dict[str, Any] | None = None
    total_songs: int = 0
    total_singers: int = 0
    active_singers: int = 0


class VenueOut(ScalesModel):
    id: str
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)
    venue_code: str
    address: VenueAddress = Field(default_factory=lambda: VenueAddress())
    contact: VenueContact = Field(default_factory=lambda: VenueContact())
    timezone: str = "UTC"
    branding: VenueBranding = Field(default_factory=lambda: VenueBranding())
    settings: VenueSettings | None = None
    operating_hours: VenueOperatingHours | None = None
    is_active: bool
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    stats: VenueStats | None = None


class VenueCompactOut(ScalesModel):
    id: str
    name: str
    slug: str
    venue_code: str
    timezone: str
    is_active: bool


# ---------------------------------------------------------------------------
# Onboarding / billing
# ---------------------------------------------------------------------------

class VenueSignupRequest(ScalesModel):
    venue_name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=8, max_length=128)
    owner_stage_name: str = Field(..., min_length=1, max_length=50)
    timezone: str = Field(default="UTC", max_length=50)
    signup_source: Literal["self_serve", "sales_assisted"] = "self_serve"
    sales_rep_email: EmailStr | None = None


class VenueSignupResponse(ScalesModel):
    venue_id: str
    singer_id: str
    venue_code: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str


class VenueBillingOut(ScalesModel):
    subscription_tier: str
    subscription_status: str
    billing_status: str
    plan_expires_at: str | None = None
    trial_ends_at: str | None = None
    billing_email: str | None = None
    signup_source: str
    sales_rep_email: str | None = None


class AdminVenueOut(VenueOut):
    admin_notes: str | None = None
    billing: VenueBillingOut
    owner_email: str | None = None
    total_singers: int = 0
    total_kj_devices: int = 0
    queue_depth: int = 0


class AdminVenueListItem(ScalesModel):
    id: str
    name: str
    slug: str
    venue_code: str
    timezone: str
    is_active: bool
    admin_notes: str | None = None
    billing: VenueBillingOut
    owner_email: str | None = None
    total_singers: int = 0
    total_kj_devices: int = 0
    queue_depth: int = 0
    created_at: str


class AdminVenueStatusUpdate(ScalesModel):
    is_active: bool | None = None
    subscription_tier: str | None = None
    subscription_status: str | None = None
    billing_status: str | None = None
    plan_expires_at: str | None = None
    trial_ends_at: str | None = None
    sales_rep_email: EmailStr | None = None
    admin_notes: str | None = Field(None, max_length=5000)


class AdminVenueProvisionRequest(ScalesModel):
    venue_name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    owner_email: EmailStr
    owner_password: str = Field(..., min_length=8, max_length=128)
    owner_stage_name: str = Field(..., min_length=1, max_length=50)
    timezone: str = Field(default="UTC", max_length=50)
    subscription_tier: str = Field(default="basic")
    sales_rep_email: EmailStr | None = None


class AdminDashboardOut(ScalesModel):
    total_venues: int = 0
    active_venues: int = 0
    trialing_venues: int = 0
    past_due_venues: int = 0
    total_singers: int = 0
    total_kj_devices: int = 0
    queue_depth: int = 0
    by_tier: dict[str, int] = Field(default_factory=dict)


class AdminBillingMetricsOut(ScalesModel):
    mrr_cents: int = 0
    active_subscriptions: int = 0
    trialing_venues: int = 0
    past_due_venues: int = 0
    churned_last_30_days: int = 0
    upcoming_renewals_7d: int = 0
    upcoming_renewals_30d: int = 0
    revenue_by_tier_cents: dict[str, int] = Field(default_factory=dict)


class CheckoutSessionRequest(ScalesModel):
    tier: Literal["basic", "enterprise"] = "basic"
    success_url: str = Field(..., min_length=1, max_length=500)
    cancel_url: str = Field(..., min_length=1, max_length=500)


class CheckoutSessionOut(ScalesModel):
    checkout_url: str
    session_id: str
    stripe_customer_id: str | None = None


class SubscriptionStatusOut(ScalesModel):
    venue_id: str
    subscription_tier: str
    subscription_status: str
    billing_status: str
    trial_ends_at: str | None = None
    plan_expires_at: str | None = None
    stripe_subscription_id: str | None = None
    is_trialing: bool
    in_grace_period: bool
    grace_period_ends_at: str | None = None


class WebhookEventOut(ScalesModel):
    status: str
    event_id: str | None = None
    handled_at: str | None = None
    message: str | None = None


class BillingPortalRequest(ScalesModel):
    return_url: str = Field(..., min_length=1, max_length=500)


class BillingPortalOut(ScalesModel):
    url: str


class AdminVenuePurgeResult(ScalesModel):
    action: Literal["hard_delete", "anonymize"]
    venue_id: str
    performed_at: str
    anonymized_singer_count: int | None = None


class AdminVenueRestore(ScalesModel):
    is_active: bool = True
    admin_notes: str | None = None


class AdminAuditLogOut(ScalesModel):
    id: str
    admin_email: str
    action: str
    venue_id: str | None = None
    venue_name: str | None = None
    details_json: str | None = None
    created_at: str


# ---------------------------------------------------------------------------
# Songs
# ---------------------------------------------------------------------------

class SongBase(ScalesModel):
    title: str = Field(..., min_length=1, max_length=200)
    artist: str = Field(..., min_length=1, max_length=200)
    album: str | None = None
    genre: str | None = None
    category: str | None = None
    language: str | None = None
    duration_ms: int | None = None
    year: int | None = None
    lyrics_url: str | None = None
    cover_art_url: str | None = None
    is_available: bool = True
    meta_json: str | None = None


class SongCreate(SongBase):
    catalog_id: str | None = None


class SongUpdate(ScalesModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    artist: str | None = Field(None, min_length=1, max_length=200)
    album: str | None = None
    genre: str | None = None
    category: str | None = None
    language: str | None = None
    duration_ms: int | None = None
    year: int | None = None
    lyrics_url: str | None = None
    cover_art_url: str | None = None
    is_available: bool | None = None
    meta_json: str | None = None


class SongOut(SongBase):
    id: str
    venue_id: str
    catalog_id: str | None = None
    is_active: bool
    created_at: str
    updated_at: str


class SongSearchQuery(ScalesModel):
    q: str = ""
    type: Literal["title", "artist", "all"] = "all"
    fuzzy: bool = True


class SongListParams(ScalesModel):
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)
    q: str = ""
    sort: Literal["title", "artist", "year", "created_at"] = "title"
    order: Literal["asc", "desc"] = "asc"
    genre: str | None = None
    category: str | None = None
    decade: str | None = None
    language: str | None = None
    available_only: bool = False


# ---------------------------------------------------------------------------
# Singers
# ---------------------------------------------------------------------------

class SingerBase(ScalesModel):
    stage_name: str = Field(..., min_length=1, max_length=50)
    real_name: str | None = None
    pronouns: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


class SingerCreate(SingerBase):
    pass


class SingerUpdate(ScalesModel):
    stage_name: str | None = Field(None, min_length=1, max_length=50)
    real_name: str | None = None
    pronouns: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    bio: str | None = Field(None, max_length=500)
    avatar_url: str | None = Field(None, max_length=500)
    social_links: str | None = Field(None, max_length=1000)
    loyalty_tier_id: str | None = None


class SingerOut(SingerBase):
    id: str
    singer_id: str  # alias for id (frontend compat)
    venue_id: str
    name: str       # alias for stage_name (frontend compat)
    display_name: str | None = None  # alias for stage_name
    tier: str = "none"  # alias for loyalty_tier_id
    total_visits: int = 0
    last_visit_date: str | None = None  # alias for last_seen
    status: str = "active"  # computed from deactivated_at
    total_points: int
    loyalty_tier_id: str | None = None
    last_seen: str | None = None
    is_checked_in: bool = False
    checked_in_at: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    social_links: str | None = None
    account_id: str | None = None
    deactivated_at: str | None = None
    created_at: str
    updated_at: str


class CheckInSessionOut(ScalesModel):
    id: str
    singer_id: str
    venue_id: str
    checked_in_at: str
    expires_at: str | None = None
    table_number: str | None = None
    created_at: str


class CheckInRequest(ScalesModel):
    nickname: str | None = Field(None, min_length=1, max_length=30)
    table_number: str | None = None
    party_size: int | None = None
    phone: str | None = None
    marketing_consent: bool = False


class CheckInResponse(ScalesModel):
    singer_id: str
    access_token: str
    access_token_expires: str
    refresh_token: str
    refresh_token_expires: str
    venue: VenueOut
    loyalty: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

class QueueRequestBase(ScalesModel):
    song_id: str
    notes: str | None = Field(None, max_length=200)
    dedication_to: str | None = None
    priority_boost: bool = False


class QueueRequestCreate(QueueRequestBase):
    pass


class QueueRequestOut(ScalesModel):
    request_id: str
    position: int
    status: Literal["pending", "approved", "now_playing", "completed", "skipped"]
    song: SongOut
    singer: dict[str, Any]
    submitted_at: str
    estimated_start: str | None = None
    notes: str | None = None
    dedication: str | None = None


class QueueAction(ScalesModel):
    action: Literal["approve", "reject", "prioritize"]


class QueueReorder(ScalesModel):
    order: list[str]


class QueueRejectRequest(ScalesModel):
    reason: str | None = Field(None, max_length=500)

class QueueRequestUpdate(ScalesModel):
    song_id: str | None = None
    notes: str | None = Field(None, max_length=200)
    dedication_to: str | None = None
    priority_boost: bool | None = None



class QueueItemOut(ScalesModel):
    """Single queue item with full singer and song details for admin panel."""

    request_id: str
    venue_id: str
    position: int | None = None
    status: str  # Literal expanded to str for runtime flexibility
    song: SongOut | None = None
    singer: SingerOut | None = None
    notes: str | None = None
    reject_reason: str | None = None
    requested_at: str | None = None
    updated_at: str | None = None
    played_at: str | None = None


class QueueAdminListOut(ScalesModel):
    items: list[QueueItemOut]
    total: int
    active_mode: Literal["fifo", "round_robin", "vip_priority", "balanced"] = "round_robin"


class QueueReorderBySinger(ScalesModel):
    singer_ids: list[str]


class QueueSkipToEnd(ScalesModel):
    request_id: str


class RotationModeSet(ScalesModel):
    mode: Literal["fifo", "round_robin", "vip_priority", "balanced"]


class RotationModeOut(ScalesModel):
    mode: str
    venue_id: str


class QueueAnalyticsOut(ScalesModel):
    total_requests_today: int
    completed_today: int
    avg_wait_seconds: float | None
    top_songs: list[dict[str, Any]]
    throughput_per_hour: list[dict[str, Any]]


class BanRequest(ScalesModel):
    reason: str | None = Field(None, max_length=500)


class BanResponse(ScalesModel):
    singer_id: str
    status: str
    banned_at: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# Loyalty
# ---------------------------------------------------------------------------

class LoyaltyTierOut(ScalesModel):
    id: str
    name: str
    min_points: int
    multiplier: float
    color: str | None = None
    icon: str | None = None


class LoyaltyTierCreate(ScalesModel):
    name: str = Field(..., min_length=1, max_length=50)
    min_points: int = Field(0, ge=0)
    multiplier: float = Field(1.0, ge=0.0)
    color: str | None = None
    icon: str | None = None


class LoyaltySummary(ScalesModel):
    current_points: int
    tier: str | None = None
    next_tier_progress: float


class LoyaltyPointsTransaction(ScalesModel):
    id: str
    amount: int
    reason: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    created_at: str


class QuestCreate(ScalesModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    quest_type: str = Field(..., pattern=r"^(perform_N_songs|spend_N_currency|visit_N_times)$")
    target: int = Field(..., ge=1)
    reward_points: int = Field(..., ge=0)
    start_date: str | None = None
    end_date: str | None = None
    is_recurring: bool = False


class QuestOut(ScalesModel):
    id: str
    name: str
    description: str | None = None
    type: str
    target: int
    reward_points: int
    start_date: str | None = None
    end_date: str | None = None
    is_recurring: bool = False
    current_progress: int = 0
    is_claimable: bool = False


class RewardOut(ScalesModel):
    id: str
    name: str
    description: str | None = None
    points_cost: int
    is_available: bool = True


class ManualAwardRequest(ScalesModel):
    singer_id: str
    amount: int = Field(..., ge=1)
    reason: str | None = None


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

class PaymentCreate(ScalesModel):
    amount_cents: int = Field(..., ge=100, description="Minimum $1 (100 cents)")
    currency: str = "USD"


class TipRequest(PaymentCreate):
    recipient_id: str
    kj_id: str | None = None  # Optional: if different from recipient
    message: str | None = Field(None, max_length=200)


class PriorityBumpRequest(PaymentCreate):
    request_id: str


class PaymentIntentOut(ScalesModel):
    client_secret: str
    payment_intent_id: str


class PaymentOut(ScalesModel):
    id: str
    venue_id: str
    singer_id: str
    recipient_id: str | None = None
    amount_cents: int
    currency: str
    payment_type: Literal["tip", "priority_bump"]
    status: Literal["pending", "succeeded", "failed", "canceled", "refunded", "partially_refunded"]
    message: str | None = None
    refunded_at: str | None = None
    refund_amount_cents: int = 0
    created_at: str
    updated_at: str
    formatted_amount: str | None = None


class PaymentHistoryOut(ScalesModel):
    items: list[PaymentOut]
    total: int
    page: int
    per_page: int


class RefundRequest(ScalesModel):
    amount_cents: int | None = Field(None, ge=1, description="Partial refund amount; null = full refund")
    reason: str | None = Field(None, max_length=200)


class RefundOut(ScalesModel):
    payment_id: str
    status: Literal["refunded", "partially_refunded"]
    refund_amount_cents: int
    original_amount_cents: int
    refunded_at: str
    reason: str | None = None


class WebhookSimulationRequest(ScalesModel):
    event_type: Literal["payment_intent.succeeded", "payment_intent.payment_failed"]
    payment_id: str
    stripe_payment_intent_id: str | None = None  # optional override


# ---------------------------------------------------------------------------
# Commerce
# ---------------------------------------------------------------------------

class ProductBase(ScalesModel):
    name: str
    description: str | None = None
    sku: str | None = None
    price_cents: int = Field(..., ge=0)
    currency: str = "USD"
    image_url: str | None = None
    stock_quantity: int = 0
    is_active: bool = True


class ProductCreate(ProductBase):
    dropshipper_id: str | None = None


class ProductOut(ProductBase):
    id: str
    venue_id: str
    created_at: str
    updated_at: str


class CartItemCreate(ScalesModel):
    product_id: str
    quantity: int = Field(..., ge=1)


class CartOut(ScalesModel):
    items: list[dict[str, Any]]
    total_cents: int


class CheckoutRequest(ScalesModel):
    cart_id: str
    success_url: str
    cancel_url: str


class CheckoutResponse(ScalesModel):
    checkout_url: str


class OrderOut(ScalesModel):
    id: str
    status: str
    total_cents: int
    currency: str
    items: list[dict[str, Any]]
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class AnalyticsSummary(ScalesModel):
    total_checkins: int
    unique_singers: int
    return_rate: float
    average_party_size: float
    by_day: list[dict[str, Any]]
    by_hour: list[dict[str, Any]]


class TimeRangeQuery(ScalesModel):
    from_date: str | None = None
    to_date: str | None = None
    granularity: Literal["hour", "day", "week", "month"] = "day"


class VenueOverviewOut(ScalesModel):
    venue_id: str
    total_songs_played: int
    total_singers: int
    avg_queue_wait_seconds: float | None = None
    busiest_day: str | None = None
    busiest_hour: int | None = None


class SingerLeaderboardEntry(ScalesModel):
    rank: int
    singer_id: str
    stage_name: str
    performance_count: int


class SongPopularityEntry(ScalesModel):
    song_id: str
    title: str
    artist: str
    request_count: int


class HourlyBreakdownItem(ScalesModel):
    hour: int = Field(..., ge=0, le=23)
    request_count: int


class SingerStatsOut(ScalesModel):
    singer_id: str
    stage_name: str
    performances_count: int
    venues_visited: int
    favorite_genre: str | None = None


# ---------------------------------------------------------------------------
# Social
# ---------------------------------------------------------------------------

class LeaderboardEntryOut(ScalesModel):
    rank: int
    singer_id: str
    nickname: str | None = None
    avatar_url: str | None = None
    score: float
    songs_sung: int
    trend: Literal["up", "down", "stable"] = "stable"


# ---------------------------------------------------------------------------
# Points & Achievements
# ---------------------------------------------------------------------------

class PointsLedgerOut(ScalesModel):
    id: str
    amount: int
    reason: str | None = None
    reference_type: str | None = None
    reference_id: str | None = None
    created_at: str


class AchievementOut(ScalesModel):
    achievement_key: str
    name: str
    description: str
    icon: str | None = None
    progress: int
    target: int
    unlocked_at: str | None = None
    unlocked: bool


class LeaderboardPeriodQuery(ScalesModel):
    period: Literal["week", "month", "alltime"] = "alltime"
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


class ConsentSettings(ScalesModel):
    allow_leaderboard: bool = True
    allow_sharing: bool = True
    share_nickname_publicly: bool = True
    allow_tagging: bool = True
    allow_friends_find_by_phone: bool = False
    allow_marketing: bool = False


class ShareRequest(ScalesModel):
    content_type: str
    content_id: str


class ShareResponse(ScalesModel):
    url: str
    expires_at: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthCheck(ScalesModel):
    status: Literal["ok", "degraded", "down"] = "ok"
    version: str
    timestamp: str
    checks: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Singer Portal (Self-Service)
# ---------------------------------------------------------------------------

class SingerHistoryItem(ScalesModel):
    request_id: str
    song_title: str
    song_artist: str
    genre: str | None = None
    status: str
    requested_at: str
    played_at: str | None = None
    notes: str | None = None


class SingerHistoryOut(ScalesModel):
    items: list[SingerHistoryItem]
    total: int


class SingerPortalStats(ScalesModel):
    songs_sung: int
    avg_wait_min: float | None = None
    favorite_genre: str | None = None


class SingerQueueItem(ScalesModel):
    request_id: str
    position: int
    status: str
    song_title: str
    song_artist: str
    song_duration_ms: int | None = None
    eta_seconds: int | None = None
    notes: str | None = None
    requested_at: str


class SingerQueueOut(ScalesModel):
    items: list[SingerQueueItem]
    total: int


class SingerQueueHistoryItem(ScalesModel):
    request_id: str
    song_title: str
    song_artist: str
    genre: str | None = None
    status: str
    requested_at: str
    played_at: str | None = None
    notes: str | None = None


class SingerQueueHistoryOut(ScalesModel):
    items: list[SingerQueueHistoryItem]
    total: int
    page: int
    per_page: int


class SingerQueueStatus(ScalesModel):
    status: Literal["active", "waiting", "completed"]
    position: int | None = None
    eta_seconds: int | None = None
    request_id: str | None = None


class SingerProfileStats(ScalesModel):
    """Extended self-service stats: songs sung, check-ins, total points, top songs."""
    songs_sung: int
    total_checkins: int
    total_points: int
    top_songs: list[dict]
    avg_wait_min: float | None = None
    favorite_genre: str | None = None


class SingerMeUpdate(ScalesModel):
    """Self-service profile update body (singer can update only their own profile)."""
    stage_name: str | None = Field(None, min_length=1, max_length=50)
    real_name: str | None = None
    pronouns: str | None = None
    phone: str | None = None
    bio: str | None = Field(None, max_length=500)
    social_links: str | None = Field(None, max_length=1000)


# ---------------------------------------------------------------------------
# Sync (KJ Desktop App)
# ---------------------------------------------------------------------------

class SyncQueueItem(ScalesModel):
    request_id: str
    singer_id: str
    song_id: str | None = None
    song_title: str | None = None
    song_artist: str | None = None
    status: Literal["pending", "approved", "up_next", "now_playing", "completed", "skipped", "rejected"]
    position: int | None = None
    notes: str | None = None
    requested_at: str | None = None
    updated_at: str | None = None
    played_at: str | None = None
    reject_reason: str | None = None


class SyncQueuePushPayload(ScalesModel):
    items: list[SyncQueueItem]
    deleted_ids: list[str] = Field(default_factory=list)
    last_modified_at: str | None = None


class SyncQueuePullOut(ScalesModel):
    items: list[SyncQueueItem]
    deleted_ids: list[str] = Field(default_factory=list)
    server_modified_at: str


class SyncSingerItem(ScalesModel):
    id: str
    stage_name: str
    real_name: str | None = None
    pronouns: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None
    total_points: int = 0
    loyalty_tier_id: str | None = None
    last_seen: str | None = None
    deactivated_at: str | None = None
    created_at: str
    updated_at: str


class SyncSingersPushPayload(ScalesModel):
    items: list[SyncSingerItem]
    deleted_ids: list[str] = Field(default_factory=list)
    last_modified_at: str | None = None


class SyncSingersPullOut(ScalesModel):
    items: list[SyncSingerItem]
    deleted_ids: list[str] = Field(default_factory=list)
    server_modified_at: str


class SyncSongItem(ScalesModel):
    id: str
    catalog_id: str | None = None
    title: str
    artist: str
    album: str | None = None
    genre: str | None = None
    category: str | None = None
    language: str | None = None
    duration_ms: int | None = None
    year: int | None = None
    is_available: bool = True
    is_active: bool = True
    created_at: str
    updated_at: str


class SyncSongsPushPayload(ScalesModel):
    items: list[SyncSongItem]
    deleted_ids: list[str] = Field(default_factory=list)
    plays: list[dict[str, Any]] = Field(default_factory=list)
    last_modified_at: str | None = None



class SyncSongPullItem(ScalesModel):
    id: str
    title: str
    artist: str
    genre: str | None = None
    duration: int | None = None
    year: int | None = None
    category: str | None = None
    available: bool = True
    metadata_locked: bool = False
    file_path: str | None = None
    file_hash: str | None = None


class SyncSongsScanPayload(ScalesModel):
    venue_id: str | None = None
    device_id: str | None = None
    scan_timestamp: str
    new_or_updated: list[dict[str, Any]] = Field(default_factory=list)
    missing_from_disk: list[str] = Field(default_factory=list)
    corrupted: list[dict[str, Any]] = Field(default_factory=list)


class SyncSongsAvailabilityBatch(ScalesModel):
    venue_id: str | None = None
    device_id: str | None = None
    updates: list[dict[str, Any]] = Field(default_factory=list)


class SyncSongsPullOut(ScalesModel):
    sync_timestamp: str
    updated_songs: list[SyncSongPullItem] = Field(default_factory=list)


class SyncSettingItem(ScalesModel):
    key: str
    value: str | None = None
    updated_at: str


class SyncSettingsPushPayload(ScalesModel):
    items: list[SyncSettingItem]
    last_modified_at: str | None = None


class SyncSettingsPullOut(ScalesModel):
    items: list[SyncSettingItem]
    server_modified_at: str


class SyncConflictDetail(ScalesModel):
    entity_type: str
    entity_id: str
    server_state: dict[str, Any]
    client_state: dict[str, Any]
    resolution: Literal["server_wins", "last_write_wins", "client_wins"]


class SyncConflictResponse(ScalesModel):
    type: str = "about:blank"
    title: str = "Sync conflict detected"
    status: int = 409
    detail: str | None = None
    conflicts: list[SyncConflictDetail] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class DeviceTokenBase(ScalesModel):
    platform: Literal["fcm", "apns"] = Field(...)
    token: str = Field(..., min_length=10, max_length=500)
    device_name: str | None = Field(None, max_length=100)


class DeviceTokenCreate(DeviceTokenBase):
    pass


class DeviceTokenOut(DeviceTokenBase):
    id: str
    singer_id: str
    venue_id: str
    is_active: bool
    created_at: str
    updated_at: str | None = None


class NotificationOut(ScalesModel):
    id: str
    singer_id: str
    venue_id: str
    notification_type: str
    title: str
    body: str
    data_json: str | None = None
    is_read: bool
    sent_at: str
    read_at: str | None = None
    created_at: str


class NotificationListOut(ScalesModel):
    items: list[NotificationOut]
    total: int
    unread_count: int
    page: int
    per_page: int


class NotificationMarkReadRequest(ScalesModel):
    notification_ids: list[str] | None = None  # None = mark all as read


class NotificationMarkReadResponse(ScalesModel):
    marked_count: int


class NotificationSettingsOut(ScalesModel):
    singer_id: str
    venue_id: str
    up_soon: bool = True
    on_stage: bool = True
    bumped: bool = True
    queue_update: bool = True
    announcement: bool = True
    social: bool = True
    payment: bool = True
    created_at: str
    updated_at: str | None = None


class NotificationSettingsUpdate(ScalesModel):
    up_soon: bool | None = None
    on_stage: bool | None = None
    bumped: bool | None = None
    queue_update: bool | None = None
    announcement: bool | None = None
    social: bool | None = None
    payment: bool | None = None


# ---------------------------------------------------------------------------
# GDPR / Data Privacy
# ---------------------------------------------------------------------------

class DataExportOut(ScalesModel):
    """Machine-readable personal data export for GDPR Article 20 data portability."""

    singer_id: str
    venue_id: str
    exported_at: str
    profile: dict[str, Any]
    queue_history: list[dict[str, Any]]
    favorites: list[dict[str, Any]]
    follows: list[dict[str, Any]]
    payments: list[dict[str, Any]]
    points_ledger: list[dict[str, Any]]
    leaderboard_entries: list[dict[str, Any]]
    achievements: list[dict[str, Any]]
    check_in_sessions: list[dict[str, Any]]
    consents: list[dict[str, Any]]
    share_events: list[dict[str, Any]]


class GDPRDeleteResponse(ScalesModel):
    """Right to erasure (GDPR Article 17): confirmation response."""

    singer_id: str
    status: str
    erased_at: str
    retention_days: int
    message: str
