"""Loyalty router (stubs for Sprint 0 scaffold)."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import LoyaltySummary, LoyaltyPointsTransaction, QuestOut, RewardOut, PaginatedResponse

router = APIRouter()


@router.get("", response_model=LoyaltySummary)
async def get_loyalty():
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/transactions", response_model=PaginatedResponse[LoyaltyPointsTransaction])
async def get_transactions():
    return PaginatedResponse(items=[], total=0, page=1, per_page=20)


@router.get("/quests", response_model=PaginatedResponse[QuestOut])
async def get_quests():
    return PaginatedResponse(items=[], total=0, page=1, per_page=20)


@router.post("/quests/{quest_id}/claim")
async def claim_quest(quest_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")
