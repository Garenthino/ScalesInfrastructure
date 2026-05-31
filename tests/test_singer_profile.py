"""MS-04A tests: profile endpoints, avatar upload, stats aggregation."""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import Singer, Venue, QueueRequest, Song, CheckInSession
from sqlalchemy import select


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers (mirrors test_singer_portal.py)
# ---------------------------------------------------------------------------

async def _seed_venue(session, name: str = "Test Venue") -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=f"test-{venue_id[:8]}",
        venue_code="".join(__import__("random").choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6)),
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(
    session,
    venue_id: str,
    stage_name: str = "Test Singer",
    role: str = "singer",
    password: str | None = "secret123",
    email: str | None = None,
    bio: str | None = None,
    avatar_url: str | None = None,
    social_links: str | None = None,
    total_points: int = 0,
) -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password) if password else None,
        role=role,
        bio=bio,
        avatar_url=avatar_url,
        social_links=social_links,
        total_points=total_points,
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


async def _seed_song(session, venue_id: str, title: str = "Test Song", genre: str = "Rock") -> Song:
    song = Song(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        title=title,
        artist="Test Artist",
        genre=genre,
        is_available=1,
        is_active=1,
    )
    session.add(song)
    await session.commit()
    await session.refresh(song)
    return song


async def _seed_queue_request(
    session,
    venue_id: str,
    singer_id: str,
    song_id: str,
    status: str = "completed",
    requested_at: str | None = None,
    played_at: str | None = None,
) -> QueueRequest:
    req = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=singer_id,
        song_id=song_id,
        status=status,
        requested_at=requested_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        played_at=played_at,
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


def _token_for_singer(jwt_encode, singer: Singer, expires=None) -> str:
    return jwt_encode(venue_id=singer.venue_id, role=singer.role, user_id=singer.id, expires=expires)


# ---------------------------------------------------------------------------
# 1. PUT /me — profile update (bio, social_links, stage_name, etc.)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_update_me_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.put(f"/v1/venues/{venue_id}/singers/me", json={"bio": "hello"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_update_me_bio_and_social_links(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="MeSinger")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/me",
        json={
            "stage_name": "UpdatedName",
            "bio": "I love karaoke.",
            "social_links": "https://twitter.com/test https://instagram.com/test",
        },
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["stage_name"] == "UpdatedName"
    assert data["bio"] == "I love karaoke."
    assert data["social_links"] == "https://twitter.com/test https://instagram.com/test"


@pytest.mark.anyio
async def test_update_me_ignores_disallowed_fields(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="Singer", total_points=100)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/me",
        json={
            "stage_name": "NiceName",
            "total_points": 9999,  # disallowed field
            "email": "hacker@evil.com",  # disallowed field
        },
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["stage_name"] == "NiceName"
    assert data["total_points"] == 100  # unchanged


@pytest.mark.anyio
async def test_update_me_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/me",
        json={"bio": "hello"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 2. POST /me/avatar — multipart upload
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_upload_avatar_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.post(f"/v1/venues/{venue_id}/singers/me/avatar")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_upload_avatar_success_png(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id)
    token = _token_for_singer(jwt_encode, singer)

    # minimal 1x1 PNG
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452"
        "000000010000000108020000009025de"
        "470000000a49444154789c6300000001"
        "00015a4a1d490000000049454e44ae42"
        "6082"
    )
    files = {"file": ("avatar.png", io.BytesIO(png_bytes), "image/png")}
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/me/avatar",
        files=files,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["avatar_url"] is not None
    assert data["avatar_url"].startswith("/uploads/avatars/")
    assert "avatar.png" not in data["avatar_url"]  # generated filename


@pytest.mark.anyio
async def test_upload_avatar_invalid_type(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id)
    token = _token_for_singer(jwt_encode, singer)

    files = {"file": ("malicious.exe", io.BytesIO(b"fake data"), "application/x-msdownload")}
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/me/avatar",
        files=files,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


@pytest.mark.anyio
async def test_upload_avatar_too_large(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id)
    token = _token_for_singer(jwt_encode, singer)

    # Create a 6 MB blob
    files = {"file": ("big.png", io.BytesIO(b"0" * (6 * 1024 * 1024)), "image/png")}
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/me/avatar",
        files=files,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


@pytest.mark.anyio
async def test_upload_avatar_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id)
    token = _token_for_singer(jwt_encode, singer)
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452"
        "000000010000000108020000009025de"
        "470000000a49444154789c6300000001"
        "00015a4a1d490000000049454e44ae42"
        "6082"
    )
    files = {"file": ("avatar.png", io.BytesIO(png_bytes), "image/png")}
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/me/avatar",
        files=files,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 3. GET /me/stats — extended aggregation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_me_stats_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/singers/me/stats")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_me_stats_empty(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["songs_sung"] == 0
    assert data["total_checkins"] == 0
    assert data["total_points"] == 0
    assert data["top_songs"] == []
    assert data["avg_wait_min"] is None
    assert data["favorite_genre"] is None


@pytest.mark.anyio
async def test_me_stats_computed(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, total_points=42)
    song1 = await _seed_song(db, venue_id, title="Rock A", genre="Rock")
    song2 = await _seed_song(db, venue_id, title="Rock B", genre="Rock")
    song3 = await _seed_song(db, venue_id, title="Pop A", genre="Pop")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await _seed_queue_request(db, venue_id, singer.id, song1.id, status="completed", requested_at=now, played_at=now)
    await _seed_queue_request(db, venue_id, singer.id, song2.id, status="completed", requested_at=now, played_at=now)
    await _seed_queue_request(db, venue_id, singer.id, song3.id, status="completed", requested_at=now, played_at=now)

    # Seed check-in sessions
    session = CheckInSession(singer_id=singer.id, venue_id=venue_id, checked_in_at=now, expires_at=now)
    db.add(session)
    await db.commit()

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["songs_sung"] == 3
    assert data["total_checkins"] == 1
    assert data["total_points"] == 42
    assert data["avg_wait_min"] == 0.0
    assert data["favorite_genre"] == "Rock"
    assert len(data["top_songs"]) == 3
    titles = {s["title"] for s in data["top_songs"]}
    assert titles == {"Rock A", "Rock B", "Pop A"}


@pytest.mark.anyio
async def test_me_stats_venue_scoped(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 4. SingerOut includes new fields
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_profile_includes_bio_avatar_social(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(
        db, venue_id,
        stage_name="SocialSinger",
        bio="Singing since 2020",
        avatar_url="https://example.com/avatar.jpg",
        social_links="https://twitter.com/socialsinger",
    )
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/profile",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["bio"] == "Singing since 2020"
    assert data["avatar_url"] == "https://example.com/avatar.jpg"
    assert data["social_links"] == "https://twitter.com/socialsinger"


@pytest.mark.anyio
async def test_list_singers_includes_new_fields(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(
        db, venue_id,
        stage_name="ListSinger",
        bio="List bio",
        avatar_url="https://example.com/a.jpg",
        social_links="insta",
    )
    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    s = next(item for item in data["items"] if item["stage_name"] == "ListSinger")
    assert s["bio"] == "List bio"
    assert s["avatar_url"] == "https://example.com/a.jpg"
    assert s["social_links"] == "insta"
