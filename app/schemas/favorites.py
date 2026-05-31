"""Pydantic schemas for singer favorites."""
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict


class ScalesModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Singer Favorites
# ---------------------------------------------------------------------------

class FavoriteBase(ScalesModel):
    song_id: str


class FavoriteCreate(FavoriteBase):
    pass


class FavoriteOut(ScalesModel):
    """A favorite song with hydrated song metadata."""
    id: str
    song_id: str
    title: str
    artist: str
    album: str | None = None
    genre: str | None = None
    cover_art_url: str | None = None
    duration_ms: int | None = None
    created_at: str

