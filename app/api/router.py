"""Top-level API router aggregating domain routers."""

from fastapi import APIRouter

from app.routers import venues, songs, singers, queue, loyalty, commerce, social, analytics

api_router = APIRouter()

api_router.include_router(venues.router, prefix="/venues", tags=["Venues"])
api_router.include_router(songs.router, prefix="/venues/{venue_id}/songs", tags=["Songs"])
api_router.include_router(singers.router, prefix="/singer", tags=["Singers"])
api_router.include_router(queue.router, prefix="/venues/{venue_id}/queue", tags=["Queue"])
api_router.include_router(loyalty.router, prefix="/singer/loyalty", tags=["Loyalty"])
api_router.include_router(commerce.router, prefix="/venues/{venue_id}/merch", tags=["Commerce"])
api_router.include_router(social.router, prefix="/venues/{venue_id}/leaderboard", tags=["Social"])
api_router.include_router(analytics.router, prefix="/venues/{venue_id}/analytics", tags=["Analytics"])
