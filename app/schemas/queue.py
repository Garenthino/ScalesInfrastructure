"""Pydantic DTOs for singer-facing queue operations."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict


class _ScalesModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Singer Queue Operations
# ---------------------------------------------------------------------------

class QueueJoinRequest(_ScalesModel):
    song_id: str
    notes: str | None = Field(None, max_length=200)
    tempo: int = Field(0, ge=-50, le=50)
    pitch: int = Field(0, ge=-12, le=12)


class QueueJoinResponse(_ScalesModel):
    request_id: str
    estimated_position: int
    warning: str | None = None
    tempo: int = 0
    pitch: int = 0


class QueueStatusResponse(_ScalesModel):
    request_id: str
    position: int
    status: Literal["pending", "approved", "now_playing", "completed", "skipped"]
    song_title: str
    song_artist: str
    eta_seconds: int | None = None
    tempo: int = 0
    pitch: int = 0


class QueueLeaveAllResponse(_ScalesModel):
    removed: int


class QueueCancelResponse(_ScalesModel):
    request_id: str
    status: Literal["cancelled"]


class PublicQueueItem(_ScalesModel):
    position: int
    status: Literal["pending", "approved", "now_playing", "completed", "skipped"]
    song_title: str
    song_artist: str
    stage_name: str
    estimated_start: str | None = None


class PublicQueueOut(_ScalesModel):
    venue_id: str
    items: list[PublicQueueItem]
    current_song: dict[str, Any] | None = None
