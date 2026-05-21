"""Pydantic request/response schemas for the Scales API.

Organized by domain: venues, songs, singers, queue, loyalty, commerce, analytics.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict, field_validator


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
    instance: str | None = None


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
    primary_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
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
    timezone: str
    is_active: bool


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


class SingerOut(SingerBase):
    id: str
    venue_id: str
    total_points: int
    loyalty_tier_id: str | None = None
    created_at: str
    updated_at: str


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
    requested_at: str
    updated_at: str | None = None
    played_at: str | None = None


class QueueAdminListOut(ScalesModel):
    items: list[QueueItemOut]
    total: int
    active_mode: Literal["fifo", "round_robin", "vip_priority"] = "round_robin"


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


class RewardOut(ScalesModel):
    id: str
    name: str
    description: str | None = None
    points_cost: int
    is_available: bool = True


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
