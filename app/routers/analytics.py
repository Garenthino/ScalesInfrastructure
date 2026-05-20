"""Analytics router (stubs for Sprint 0 scaffold)."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import AnalyticsSummary, TimeRangeQuery

router = APIRouter()


@router.get("/summary")
async def get_summary(venue_id: str, q: TimeRangeQuery | None = None):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/attendance")
async def get_attendance(venue_id: str, q: TimeRangeQuery | None = None):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/engagement")
async def get_engagement(venue_id: str, q: TimeRangeQuery | None = None):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/songs")
async def get_song_analytics(venue_id: str, q: TimeRangeQuery | None = None):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/loyalty")
async def get_loyalty_analytics(venue_id: str, q: TimeRangeQuery | None = None):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/revenue")
async def get_revenue_analytics(venue_id: str, q: TimeRangeQuery | None = None):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/peaks")
async def get_peak_analytics(venue_id: str, q: TimeRangeQuery | None = None):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")
