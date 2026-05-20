"""Song catalog router (stubs for Sprint 0 scaffold)."""

from fastapi import APIRouter, HTTPException, status

from app.schemas import SongCreate, SongUpdate, SongOut, PaginatedResponse

router = APIRouter()


@router.get("", response_model=PaginatedResponse[SongOut])
async def list_songs(venue_id: str):
    return PaginatedResponse(items=[], total=0, page=1, per_page=20)


@router.post("", response_model=SongOut, status_code=status.HTTP_201_CREATED)
async def create_song(venue_id: str, body: SongCreate):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/{song_id}", response_model=SongOut)
async def get_song(venue_id: str, song_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.put("/{song_id}", response_model=SongOut)
async def update_song(venue_id: str, song_id: str, body: SongUpdate):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.delete("/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_song(venue_id: str, song_id: str):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")


@router.get("/search")
async def search_songs(venue_id: str, q: str = "", type: str = "all", fuzzy: bool = True):
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented in Sprint 0")
