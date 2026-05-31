"""Singer favorites router — venue-scoped song favorites."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.models import SingerFavorite, Song
from app.schemas import FavoriteOut, FavoriteCreate, PaginatedResponse

router = APIRouter()


def _require_venue(venue_id: str, current: SingerUser) -> None:
    """Enforce that the current user's venue matches the URL venue."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )


async def _song_in_venue(db: AsyncSession, song_id: str, venue_id: str) -> Song | None:
    """Return the song only if it exists and belongs to the given venue."""
    result = await db.execute(
        select(Song).where(
            Song.id == song_id,
            Song.venue_id == venue_id,
            Song.deleted_at.is_(None),
            Song.is_active == 1,
        )
    )
    return result.scalar_one_or_none()


@router.get("/favorites", response_model=PaginatedResponse[FavoriteOut])
async def list_favorites(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current singer's favorite songs with song metadata."""
    _require_venue(venue_id, current)

    # Join favorites with songs to hydrate metadata in one query
    stmt = (
        select(SingerFavorite, Song)
        .join(Song, SingerFavorite.song_id == Song.id)
        .where(
            SingerFavorite.singer_id == current.id,
            SingerFavorite.venue_id == venue_id,
        )
        .order_by(SingerFavorite.created_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    total = len(rows)
    items = []
    for fav, song in rows:
        items.append(
            FavoriteOut(
                id=fav.id,
                song_id=song.id,
                title=song.title,
                artist=song.artist,
                album=song.album,
                genre=song.genre,
                cover_art_url=song.cover_art_url,
                duration_ms=song.duration_ms,
                created_at=fav.created_at,
            )
        )

    return PaginatedResponse(
        items=items,
        total=total,
        page=1,
        per_page=total or 20,
    )


@router.post("/favorites", response_model=FavoriteOut, status_code=status.HTTP_201_CREATED)
async def add_favorite(
    venue_id: str,
    body: FavoriteCreate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a song to the current singer's favorites (idempotent)."""
    _require_venue(venue_id, current)

    # Verify the song exists in this venue
    song = await _song_in_venue(db, body.song_id, venue_id)
    if song is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Song not found in this venue",
        )

    # Check for existing favorite (idempotent — return the existing one)
    existing = (
        await db.execute(
            select(SingerFavorite).where(
                SingerFavorite.singer_id == current.id,
                SingerFavorite.venue_id == venue_id,
                SingerFavorite.song_id == body.song_id,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Idempotent: return the existing favorite as if newly created
        return FavoriteOut(
            id=existing.id,
            song_id=song.id,
            title=song.title,
            artist=song.artist,
            album=song.album,
            genre=song.genre,
            cover_art_url=song.cover_art_url,
            duration_ms=song.duration_ms,
            created_at=existing.created_at,
        )

    from app.models import _new_uuid, _now_iso
    new_fav = SingerFavorite(
        id=_new_uuid(),
        venue_id=venue_id,
        singer_id=current.id,
        song_id=body.song_id,
        created_at=_now_iso(),
    )
    db.add(new_fav)
    await db.commit()
    await db.refresh(new_fav)

    return FavoriteOut(
        id=new_fav.id,
        song_id=song.id,
        title=song.title,
        artist=song.artist,
        album=song.album,
        genre=song.genre,
        cover_art_url=song.cover_art_url,
        duration_ms=song.duration_ms,
        created_at=new_fav.created_at,
    )


@router.delete("/favorites/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    venue_id: str,
    song_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a song from the current singer's favorites."""
    _require_venue(venue_id, current)

    result = await db.execute(
        select(SingerFavorite).where(
            SingerFavorite.singer_id == current.id,
            SingerFavorite.venue_id == venue_id,
            SingerFavorite.song_id == song_id,
        )
    )
    fav = result.scalar_one_or_none()
    if fav is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Favorite not found",
        )

    await db.delete(fav)
    await db.commit()
    return None
