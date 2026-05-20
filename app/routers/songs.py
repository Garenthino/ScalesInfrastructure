"""Song catalog router — full CRUD with search, filter, sort, pagination."""

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, asc

from app.core.auth import require_admin, optional_token, venue_match
from app.core.db import get_db
from app.models import Song, Venue
from app.schemas import (
    SongCreate, SongUpdate, SongOut,
    PaginatedResponse, SongListParams,
)

router = APIRouter()


def _song_out(s: Song) -> SongOut:
    """Map ORM Song to Pydantic SongOut, normalizing booleans."""
    data = {k: getattr(s, k) for k in Song.__table__.columns.keys()}
    data["is_active"] = bool(data.get("is_active", 1))
    data["is_available"] = bool(data.get("is_available", 1))
    return SongOut(**data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def _base_song_query():
    return select(Song).where(Song.is_active == 1, Song.deleted_at.is_(None))


async def _require_venue_owner_or_match(
    venue_id: str,
    token: dict | None,
    db: AsyncSession,
) -> None:
    """If a token is present, venue must match; if no token, venue must exist."""
    # Ensure venue exists (soft-deleted venues not discoverable)
    stmt = select(Venue).where(
        Venue.id == venue_id,
        Venue.is_active == 1,
        Venue.deleted_at.is_(None),
    )
    venue = (await db.execute(stmt)).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")
    if token is not None and not venue_match(venue_id, token):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[SongOut])
async def list_songs(
    venue_id: str,
    params: SongListParams = Depends(),
    db: AsyncSession = Depends(get_db),
    token: dict | None = Depends(optional_token),
):
    await _require_venue_owner_or_match(venue_id, token, db)

    # Base filters
    filters = [
        Song.venue_id == venue_id,
        Song.is_active == 1,
        Song.deleted_at.is_(None),
        Song.is_available == 1,
    ]
    if params.available_only:
        # already enforced above, keep explicit for API contract
        pass
    if params.genre:
        filters.append(Song.genre == params.genre)
    if params.category:
        filters.append(Song.category == params.category)
    if params.language:
        filters.append(Song.language == params.language)
    if params.decade:
        if not re.fullmatch(r"\d{4}s", params.decade):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="decade must match pattern e.g. 1980s",
            )
        start = int(params.decade[:4])
        filters.append(Song.year >= start)
        filters.append(Song.year < start + 10)

    # Search across title and artist
    if params.q:
        like_term = f"%{params.q}%"
        filters.append(
            or_(
                Song.title.ilike(like_term),
                Song.artist.ilike(like_term),
            )
        )

    # Ordering
    sort_col = {
        "title": Song.title,
        "artist": Song.artist,
        "year": Song.year,
        "created_at": Song.created_at,
    }.get(params.sort, Song.title)

    order_fn = desc if params.order == "desc" else asc

    # Count total
    count_stmt = select(func.count()).select_from(Song).where(and_(*filters))
    total = (await db.execute(count_stmt)).scalar_one()

    # Page query
    offset = (params.page - 1) * params.per_page
    stmt = (
        select(Song)
        .where(and_(*filters))
        .order_by(order_fn(sort_col))
        .offset(offset)
        .limit(params.per_page)
    )
    result = await db.execute(stmt)
    items = [_song_out(row) for row in result.scalars().all()]

    return PaginatedResponse(
        items=items,
        total=total,
        page=params.page,
        per_page=params.per_page,
    )


# ---------------------------------------------------------------------------
# SEARCH (standalone endpoint mirroring list with /search path)
# ---------------------------------------------------------------------------

@router.get("/search", response_model=PaginatedResponse[SongOut])
async def search_songs(
    venue_id: str,
    q: str = "",
    type: str = "all",
    fuzzy: bool = True,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    token: dict | None = Depends(optional_token),
):
    params = SongListParams(
        page=page,
        per_page=per_page,
        q=q,
        sort="title",
        order="asc",
    )
    return await list_songs(venue_id=venue_id, params=params, db=db, token=token)


# ---------------------------------------------------------------------------
# CREATE
# ---------------------------------------------------------------------------

@router.post("", response_model=SongOut, status_code=status.HTTP_201_CREATED)
async def create_song(
    venue_id: str,
    body: SongCreate,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )

    # Ensure venue exists
    venue = (await db.execute(
        select(Venue).where(
            Venue.id == venue_id,
            Venue.is_active == 1,
            Venue.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    song = Song(
        venue_id=venue_id,
        catalog_id=body.catalog_id,
        title=body.title,
        artist=body.artist,
        album=body.album,
        genre=body.genre,
        category=body.category,
        language=body.language,
        duration_ms=body.duration_ms,
        year=body.year,
        lyrics_url=body.lyrics_url,
        cover_art_url=body.cover_art_url,
        is_available=1 if body.is_available else 0,
        meta_json=body.meta_json,
    )
    db.add(song)
    await db.commit()
    await db.refresh(song)
    return _song_out(song)


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------

@router.get("/{song_id}", response_model=SongOut)
async def get_song(
    venue_id: str,
    song_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict | None = Depends(optional_token),
):
    await _require_venue_owner_or_match(venue_id, token, db)

    song = (await db.execute(
        _base_song_query().where(
            Song.id == song_id,
            Song.venue_id == venue_id,
        )
    )).scalar_one_or_none()
    if song is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Song not found")
    return _song_out(song)


# ---------------------------------------------------------------------------
# UPDATE
# ---------------------------------------------------------------------------

@router.put("/{song_id}", response_model=SongOut)
async def update_song(
    venue_id: str,
    song_id: str,
    body: SongUpdate,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )

    song = (await db.execute(
        _base_song_query().where(
            Song.id == song_id,
            Song.venue_id == venue_id,
        )
    )).scalar_one_or_none()
    if song is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Song not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "is_available" and value is not None:
            value = 1 if value else 0
        setattr(song, key, value)
    song.updated_at = _now_iso()

    await db.commit()
    await db.refresh(song)
    return _song_out(song)


# ---------------------------------------------------------------------------
# DELETE (soft)
# ---------------------------------------------------------------------------

@router.delete("/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_song(
    venue_id: str,
    song_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(require_admin),
):
    if not venue_match(venue_id, token):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )

    song = (await db.execute(
        _base_song_query().where(
            Song.id == song_id,
            Song.venue_id == venue_id,
        )
    )).scalar_one_or_none()
    if song is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Song not found")

    song.is_active = 0
    song.deleted_at = _now_iso()
    await db.commit()
    return None

