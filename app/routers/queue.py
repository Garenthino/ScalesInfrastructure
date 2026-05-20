"""Request queue router (stubs for Sprint 0 scaffold)."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import QueueRequestCreate, QueueRequestOut, QueueAction, QueueReorder, PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[QueueRequestOut])
async def get_queue(venue_id: str):
    return PaginatedResponse(items=[], total=0, page=1, per_page=20)


@router.post("", response_model=QueueRequestOut, status_code=status.HTTP_201_CREATED)
async def submit_request(venue_id: str, body: QueueRequestCreate):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/my")
async def my_requests(venue_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_request(venue_id: str, request_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.patch("/{request_id}")
async def modify_request(venue_id: str, request_id: str, body: QueueAction):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.post("/{request_id}/start")
async def start_song(venue_id: str, request_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.post("/{request_id}/complete")
async def complete_song(venue_id: str, request_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.post("/{request_id}/skip")
async def skip_song(venue_id: str, request_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.put("/reorder")
async def reorder_queue(venue_id: str, body: QueueReorder):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")
