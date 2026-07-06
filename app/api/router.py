"""Top-level API router aggregating domain routers."""

from fastapi import APIRouter

from app.routers import venues, songs, singers, singer_favorites, singer_follows, queue_singer, queue, queue_admin, loyalty, commerce, social, analytics, auth, kj_auth, kj_sync, payments, notifications, admin, onboarding, admin_venues, billing, accounts

api_router = APIRouter()

from app.routers.kj_auth import router as kj_auth_router, venue_router as kj_venue_router

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(accounts.router, prefix="/accounts", tags=["Accounts"])
api_router.include_router(kj_auth_router, prefix="/kj", tags=["KJ Auth"])
api_router.include_router(kj_venue_router)
api_router.include_router(kj_sync.router, prefix="/kj/sync", tags=["Sync"])

api_router.include_router(admin.router, prefix="/admin", tags=["Admin"])
api_router.include_router(admin_venues.router, prefix="/admin", tags=["Admin Venues"])
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["Onboarding"])
api_router.include_router(venues.router, prefix="/venues", tags=["Venues"])
api_router.include_router(songs.router, prefix="/venues/{venue_id}/songs", tags=["Songs"])
# Top-level songs alias (DragonHost2 compatibility)
api_router.include_router(songs.router, prefix="/songs", tags=["Songs"])
api_router.include_router(singer_favorites.router, prefix="/venues/{venue_id}/singers", tags=["Singer Favorites"])
api_router.include_router(singer_follows.router, prefix="/venues/{venue_id}/singers", tags=["Singer Follows"])
api_router.include_router(singers.router, prefix="/venues/{venue_id}/singers", tags=["Singers"])
api_router.include_router(queue_singer.router, prefix="/venues/{venue_id}/queue", tags=["Queue Singer"])
api_router.include_router(queue.router, prefix="/venues/{venue_id}/queue", tags=["Queue"])
api_router.include_router(queue_admin.router, prefix="/venues/{venue_id}/queue/admin", tags=["Queue Admin"])
api_router.include_router(loyalty.router, prefix="/singer/loyalty", tags=["Loyalty"])
api_router.include_router(commerce.router, prefix="/venues/{venue_id}/merch", tags=["Commerce"])
api_router.include_router(social.router, prefix="/venues/{venue_id}/leaderboard", tags=["Social"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])
api_router.include_router(payments.router, prefix="/venues/{venue_id}/payments", tags=["Payments"])
# Stripe webhook is intentionally unscoped; it is exposed here under /v1/stripe/
api_router.include_router(payments.router, prefix="/stripe", tags=["Stripe Webhook"])
api_router.include_router(billing.router, prefix="/venues/{venue_id}/billing", tags=["Billing"])
api_router.include_router(notifications.router, prefix="/venues/{venue_id}/singers", tags=["Notifications"])
