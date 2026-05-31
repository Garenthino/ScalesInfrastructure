"""Top-level API router aggregating domain routers."""

from fastapi import APIRouter

from app.routers import venues, songs, singers, singer_favorites, singer_follows, queue_singer, queue, queue_admin, loyalty, commerce, social, analytics, auth, kj_auth, kj_sync, payments

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(kj_auth.router, prefix="/kj", tags=["KJ Auth"])
api_router.include_router(kj_sync.router, prefix="/sync", tags=["Sync"])
api_router.include_router(venues.router, prefix="/venues", tags=["Venues"])
api_router.include_router(songs.router, prefix="/venues/{venue_id}/songs", tags=["Songs"])
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
