"""Tests for singer favorites endpoints."""
from __future__ import annotations

import random
import uuid

import pytest
from fastapi import status
from sqlalchemy import select

from app.core.security import hash_password
from app.models import Singer, Venue, Song, SingerFavorite


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(session, name: str = "Favorites Test Venue") -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=f"fav-{venue_id[:8]}",
        venue_code="".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6)),
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(session, venue_id: str, stage_name: str = "Fav Singer") -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("secret123"),
        role="singer",
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


async def _seed_song(session, venue_id: str, title: str = "Fav Song") -> Song:
    song = Song(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        title=title,
        artist="Test Artist",
        is_available=1,
        is_active=1,
    )
    session.add(song)
    await session.commit()
    await session.refresh(song)
    return song


async def _seed_favorite(session, venue_id: str, singer_id: str, song_id: str) -> SingerFavorite:
    fav = SingerFavorite(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=singer_id,
        song_id=song_id,
        created_at="2026-01-01T00:00:00Z",
    )
    session.add(fav)
    await session.commit()
    await session.refresh(fav)
    return fav


def _token_for_singer(singer: Singer, venue_id: str | None = None) -> str:
    from datetime import datetime, timezone
    from jose import jwt
    from app.core.config import settings
    now = datetime.now(timezone.utc)
    payload = {
        "sub": singer.id,
        "venue_id": venue_id or singer.venue_id,
        "role": singer.role,
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_favorites_empty(client, db):
    """GET favorites returns empty list when singer has none."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    token = _token_for_singer(singer)

    response = await client.get(
        f"/v1/venues/{venue.id}/singers/favorites",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_favorites_with_data(client, db):
    """GET favorites returns favorites with hydrated song metadata."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id, title="Rocket Man")
    fav = await _seed_favorite(db, venue.id, singer.id, song.id)
    token = _token_for_singer(singer)

    response = await client.get(
        f"/v1/venues/{venue.id}/singers/favorites",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["song_id"] == song.id
    assert item["title"] == "Rocket Man"
    assert item["artist"] == "Test Artist"
    assert "id" in item
    assert "created_at" in item


@pytest.mark.asyncio
async def test_add_favorite_success(client, db):
    """POST favorites creates a new favorite and returns hydrated metadata."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id, title="Tiny Dancer")
    token = _token_for_singer(singer)

    response = await client.post(
        f"/v1/venues/{venue.id}/singers/favorites",
        headers=AUTHORIZATION(token),
        json={"song_id": song.id},
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["song_id"] == song.id
    assert data["title"] == "Tiny Dancer"
    assert "id" in data
    assert "created_at" in data

    # Verify DB state
    result = await db.execute(
        select(SingerFavorite).where(
            SingerFavorite.singer_id == singer.id,
            SingerFavorite.venue_id == venue.id,
            SingerFavorite.song_id == song.id,
        )
    )
    fav = result.scalar_one_or_none()
    assert fav is not None


@pytest.mark.asyncio
async def test_add_favorite_idempotent(client, db):
    """POST favorites twice with same song_id is idempotent."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id, title="Bennie")
    token = _token_for_singer(singer)

    response1 = await client.post(
        f"/v1/venues/{venue.id}/singers/favorites",
        headers=AUTHORIZATION(token),
        json={"song_id": song.id},
    )
    assert response1.status_code == status.HTTP_201_CREATED
    data1 = response1.json()
    fav_id = data1["id"]

    response2 = await client.post(
        f"/v1/venues/{venue.id}/singers/favorites",
        headers=AUTHORIZATION(token),
        json={"song_id": song.id},
    )
    assert response2.status_code == status.HTTP_201_CREATED
    data2 = response2.json()
    assert data2["id"] == fav_id  # Same record returned
    assert data2["title"] == "Bennie"

    # Ensure only one DB row
    result = await db.execute(
        select(SingerFavorite).where(
            SingerFavorite.singer_id == singer.id,
            SingerFavorite.venue_id == venue.id,
            SingerFavorite.song_id == song.id,
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_add_favorite_cross_venue_denied(client, db):
    """POST favorites with a song_id from a different venue is rejected."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer = await _seed_singer(db, venue_a.id)
    song_b = await _seed_song(db, venue_b.id, title="Other Venue Song")
    token = _token_for_singer(singer)

    response = await client.post(
        f"/v1/venues/{venue_a.id}/singers/favorites",
        headers=AUTHORIZATION(token),
        json={"song_id": song_b.id},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert "Song not found" in data["detail"]


@pytest.mark.asyncio
async def test_add_favorite_wrong_venue_url(client, db):
    """POST favorites to a URL venue different from the singer's venue is rejected."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer = await _seed_singer(db, venue_a.id)
    song_b = await _seed_song(db, venue_b.id, title="Venue B Song")
    token = _token_for_singer(singer)

    response = await client.post(
        f"/v1/venues/{venue_b.id}/singers/favorites",
        headers=AUTHORIZATION(token),
        json={"song_id": song_b.id},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    data = response.json()
    assert "Venue access denied" in data["detail"]


@pytest.mark.asyncio
async def test_delete_favorite_success(client, db):
    """DELETE favorites/{song_id} removes the favorite."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id, title="Goodbye Song")
    fav = await _seed_favorite(db, venue.id, singer.id, song.id)
    token = _token_for_singer(singer)

    response = await client.delete(
        f"/v1/venues/{venue.id}/singers/favorites/{song.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    # Verify removed from DB
    result = await db.execute(
        select(SingerFavorite).where(
            SingerFavorite.singer_id == singer.id,
            SingerFavorite.venue_id == venue.id,
            SingerFavorite.song_id == song.id,
        )
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_favorite_not_found(client, db):
    """DELETE favorites/{song_id} for a non-existing favorite returns 404."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id, title="Never Liked")
    token = _token_for_singer(singer)

    response = await client.delete(
        f"/v1/venues/{venue.id}/singers/favorites/{song.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    data = response.json()
    assert "Favorite not found" in data["detail"]


@pytest.mark.asyncio
async def test_list_favorites_cross_venue_denied(client, db):
    """GET favorites with wrong URL venue returns 403."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer = await _seed_singer(db, venue_a.id)
    token = _token_for_singer(singer)

    response = await client.get(
        f"/v1/venues/{venue_b.id}/singers/favorites",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Venue access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_favorite_wrong_venue(client, db):
    """DELETE favorites with wrong URL venue returns 403."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer = await _seed_singer(db, venue_a.id)
    song = await _seed_song(db, venue_b.id, title="Venue B Song")
    token = _token_for_singer(singer)

    response = await client.delete(
        f"/v1/venues/{venue_b.id}/singers/favorites/{song.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Venue access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_add_favorite_song_not_found(client, db):
    """POST favorites with a non-existent song_id returns 404."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    token = _token_for_singer(singer)

    response = await client.post(
        f"/v1/venues/{venue.id}/singers/favorites",
        headers=AUTHORIZATION(token),
        json={"song_id": str(uuid.uuid4())},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Song not found" in response.json()["detail"]
