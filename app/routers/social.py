"""Social / leaderboard router (stubs for Sprint 0 scaffold)."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import LeaderboardEntryOut, PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[LeaderboardEntryOut])
async def get_leaderboard(venue_id: str):
    return PaginatedResponse(items=[], total=0, page=1, per_page=20)


@router.get("/songs")
async def get_top_songs(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")
