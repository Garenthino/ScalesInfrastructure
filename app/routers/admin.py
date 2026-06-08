"""Admin portal routes for song metadata management."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.core.db import get_db
from app.models import Song

router = APIRouter()


@router.patch("/songs/{song_id}", status_code=status.HTTP_200_OK)
async def patch_song_metadata(
    song_id: str,
    payload: dict,
    token: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin metadata correction. Locks the song so future KJ scans can't overwrite."""
    venue_id = token.get("venue_id")
    result = await db.execute(
        select(Song).where(
            and_(Song.id == song_id, Song.venue_id == str(venue_id))
        )
    )
    song = result.scalar_one_or_none()
    if not song:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Song not found")

    allowed_fields = {"title", "artist", "genre", "category", "year", "duration_ms"}
    for field, value in payload.items():
        if field in allowed_fields:
            setattr(song, field, value)
        elif field == "metadata_locked":
            song.metadata_locked = 1 if value else 0

    song.metadata_locked = 1  # Always lock after admin edit
    await db.commit()

    return {
        "id": str(song.id),
        "title": song.title,
        "artist": song.artist,
        "genre": song.genre,
        "category": song.category,
        "year": song.year,
        "duration_ms": song.duration_ms,
        "metadata_locked": bool(song.metadata_locked),
    }


@router.post("/songs/{song_id}/lock", status_code=status.HTTP_200_OK)
async def lock_song_metadata(
    song_id: str,
    token: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Prevent future KJ scans from overwriting this song's metadata."""
    venue_id = token.get("venue_id")
    result = await db.execute(
        select(Song).where(
            and_(Song.id == song_id, Song.venue_id == str(venue_id))
        )
    )
    song = result.scalar_one_or_none()
    if not song:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Song not found")

    song.metadata_locked = 1
    await db.commit()
    return {"id": str(song.id), "metadata_locked": 1}
