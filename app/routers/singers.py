"""Singer / patron router (stubs for Sprint 0 scaffold)."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import (
    SingerCreate, SingerUpdate, SingerOut, CheckInRequest, CheckInResponse,
    PaginatedResponse,
)

router = APIRouter()


@router.post("/checkin", response_model=CheckInResponse)
async def check_in(venue_id: str, body: CheckInRequest):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/profile", response_model=SingerOut)
async def get_profile():
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.put("/profile", response_model=SingerOut)
async def update_profile(body: SingerUpdate):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/history")
async def get_history():
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/stats")
async def get_stats():
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account():
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")
