"""Commerce / merchandise router (stubs for Sprint 0 scaffold)."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import ProductOut, CartOut, CheckoutRequest, CheckoutResponse, OrderOut, PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[ProductOut])
async def list_merch(venue_id: str):
    return PaginatedResponse(items=[], total=0, page=1, per_page=20)


@router.get("/admin")
async def get_merch_admin(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.post("/admin")
async def create_product(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")
