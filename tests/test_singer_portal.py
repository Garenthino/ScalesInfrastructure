"""Singer self-service portal tests — checkin, profile, history, stats, account."""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import Singer, Venue, QueueRequest, Song


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(session, name: str = "Test Venue") -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=f"test-{venue_id[:8]}",
        venue_code="".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6)),
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
    real_name: str | None = None,
    pronouns: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
) -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password) if password else None,
        role=role,
        real_name=real_name,
        pronouns=pronouns,
        phone=phone,
        notes=notes,
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
    notes: str | None = None,
) -> QueueRequest:
    req = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=singer_id,
        song_id=song_id,
        status=status,
        requested_at=requested_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        played_at=played_at,
        notes=notes,
    )
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return req


def _token_for_singer(jwt_encode, singer: Singer, expires=None) -> str:
    return jwt_encode(venue_id=singer.venue_id, role=singer.role, user_id=singer.id, expires=expires)


# ---------------------------------------------------------------------------
# 1. CHECKIN
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_checkin_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.post(f"/v1/venues/{venue_id}/singers/checkin", json={})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_checkin_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id, stage_name="Outsider")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        json={},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_checkin_updates_last_seen(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="CheckinMe")
    assert singer.last_seen is None
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        json={"nickname": "StageName"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["id"] == singer.id
    assert data["last_seen"] is not None
    # Should be an ISO string
    assert "T" in data["last_seen"]


@pytest.mark.anyio
async def test_checkin_singer_not_found(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    # Token references a non-existent singer — get_current_user returns 401
    fake_id = str(uuid.uuid4())
    token = jwt_encode(venue_id=venue_id, role="singer", user_id=fake_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        json={},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# 2. GET PROFILE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_profile_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/singers/profile")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_get_profile_success(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="ProfileMe", real_name="Real", pronouns="they/them")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/profile",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["id"] == singer.id
    assert data["stage_name"] == "ProfileMe"
    assert data["real_name"] == "Real"
    assert data["pronouns"] == "they/them"


@pytest.mark.anyio
async def test_get_profile_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id, stage_name="Outsider")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/profile",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 3. UPDATE PROFILE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_update_profile_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.put(f"/v1/venues/{venue_id}/singers/profile", json={"stage_name": "Hacker"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_update_profile_success(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="Old")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/profile",
        json={"stage_name": "NewName", "notes": "Fresh notes"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["stage_name"] == "NewName"
    assert data["notes"] == "Fresh notes"


@pytest.mark.anyio
async def test_update_profile_partial(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="Base", notes="KeepMe")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/profile",
        json={"stage_name": "Updated"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["stage_name"] == "Updated"
    assert data["notes"] == "KeepMe"


@pytest.mark.anyio
async def test_update_profile_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id, stage_name="Outsider")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/profile",
        json={"stage_name": "Hacker"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 4. HISTORY
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_history_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/singers/history")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_history_empty(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="NoHistory")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/history",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.anyio
async def test_history_returns_items(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="HistoryMe")
    song1 = await _seed_song(db, venue_id, title="Song A", genre="Rock")
    song2 = await _seed_song(db, venue_id, title="Song B", genre="Pop")
    await _seed_queue_request(db, venue_id, singer.id, song1.id, status="completed")
    await _seed_queue_request(db, venue_id, singer.id, song2.id, status="skipped")

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/history",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 2
    titles = {item["song_title"] for item in data["items"]}
    assert titles == {"Song A", "Song B"}
    # Verify genre and status present
    for item in data["items"]:
        assert item["status"] in ("completed", "skipped")
        assert item["genre"] in ("Rock", "Pop")


@pytest.mark.anyio
async def test_history_venue_scoped(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id, stage_name="OtherVenue")
    song = await _seed_song(db, other.id, title="OtherSong")
    await _seed_queue_request(db, other.id, singer.id, song.id, status="completed")

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/history",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 5. STATS
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_stats_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/singers/stats")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_stats_empty(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="NoStats")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["songs_sung"] == 0
    assert data["avg_wait_min"] is None
    assert data["favorite_genre"] is None


@pytest.mark.anyio
async def test_stats_computed(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="StatsMe")
    song1 = await _seed_song(db, venue_id, title="Rock Song", genre="Rock")
    song2 = await _seed_song(db, venue_id, title="Rock Song 2", genre="Rock")
    song3 = await _seed_song(db, venue_id, title="Pop Song", genre="Pop")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Simulate completed requests with played_at
    await _seed_queue_request(
        db, venue_id, singer.id, song1.id,
        status="completed",
        requested_at=now,
        played_at=now,
    )
    await _seed_queue_request(
        db, venue_id, singer.id, song2.id,
        status="completed",
        requested_at=now,
        played_at=now,
    )
    await _seed_queue_request(
        db, venue_id, singer.id, song3.id,
        status="completed",
        requested_at=now,
        played_at=now,
    )

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["songs_sung"] == 3
    # avg_wait_min should be ~0 since requested_at == played_at
    assert data["avg_wait_min"] == 0.0
    # favorite genre: Rock wins (2 vs 1)
    assert data["favorite_genre"] == "Rock"


@pytest.mark.anyio
async def test_stats_venue_scoped(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id, stage_name="OtherVenue")
    song = await _seed_song(db, other.id, title="OtherSong")
    await _seed_queue_request(db, other.id, singer.id, song.id, status="completed")

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 6. ACCOUNT DELETE (soft)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_account_delete_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.delete(f"/v1/venues/{venue_id}/singers/account")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_account_delete_success(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="DeleteMe")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/account",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    # subsequent auth using same token should fail (deactivated)
    resp2 = await client.get(
        f"/v1/venues/{venue_id}/singers/profile",
        headers=AUTHORIZATION(token),
    )
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_account_delete_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id, stage_name="Outsider")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/account",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
