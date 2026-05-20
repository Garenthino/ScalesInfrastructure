"""Venue management router (stubs for Sprint 0 scaffold)."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas import (
    VenueCreate, VenueUpdate, VenueOut, VenueStatusOut,
    PaginatedResponse, ProblemDetail,
)

router = APIRouter()


@router.get("", response_model=PaginatedResponse[VenueOut])
async def list_venues():
    return PaginatedResponse(items=[], total=0, page=1, per_page=20)


@router.post("", response_model=VenueOut, status_code=status.HTTP_201_CREATED)
async def create_venue(body: VenueCreate):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/{venue_id}", response_model=VenueOut)
async def get_venue(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.put("/{venue_id}", response_model=VenueOut)
async def update_venue(venue_id: str, body: VenueUpdate):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.delete("/{venue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_venue(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/{venue_id}/status", response_model=VenueStatusOut)
async def venue_status(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/{venue_id}/admin")
async def get_venue_admin(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.put("/{venue_id}/branding")
async def update_venue_branding(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/{venue_id}/analytics")
async def get_venue_analytics(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")
