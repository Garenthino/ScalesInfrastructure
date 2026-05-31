"""Singer self-service portal tests — checkin, profile, history, stats, account."""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import Singer, Venue, QueueRequest, Song, CheckInSession
from sqlalchemy import select


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


# ---------------------------------------------------------------------------
# 7. CHECK-IN SESSION (real presence tracking)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_checkin_creates_session_and_sets_checked_in(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="CheckinMe")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        json={"table_number": "12"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["is_checked_in"] is True
    assert data["checked_in_at"] is not None
    assert "T" in data["checked_in_at"]
    # last_seen also updated
    assert data["last_seen"] is not None


@pytest.mark.anyio
async def test_checkout_clears_session(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="CheckoutMe")
    token = _token_for_singer(jwt_encode, singer)
    # check in first
    resp_in = await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        json={},
        headers=AUTHORIZATION(token),
    )
    assert resp_in.status_code == status.HTTP_200_OK
    assert resp_in.json()["is_checked_in"] is True

    # check out
    resp_out = await client.post(
        f"/v1/venues/{venue_id}/singers/checkout",
        json={},
        headers=AUTHORIZATION(token),
    )
    assert resp_out.status_code == status.HTTP_200_OK
    data = resp_out.json()
    assert data["is_checked_in"] is False
    assert data["checked_in_at"] is None


@pytest.mark.anyio
async def test_list_checked_in_requires_kj_or_admin(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="Singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/checked-in",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_list_checked_in_returns_checked_in_singers(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    # Seed two singers, check one in
    s1 = await _seed_singer(db, venue_id, stage_name="CheckedIn")
    s2 = await _seed_singer(db, venue_id, stage_name="NotCheckedIn")

    token1 = _token_for_singer(jwt_encode, s1)
    await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        json={},
        headers=AUTHORIZATION(token1),
    )

    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    admin_token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/checked-in",
        headers=AUTHORIZATION(admin_token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["stage_name"] == "CheckedIn"
    assert data["items"][0]["is_checked_in"] is True


@pytest.mark.anyio
async def test_checkin_expires_previous_session(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="DoubleCheckin")
    token = _token_for_singer(jwt_encode, singer)
    # First check-in
    r1 = await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        json={"table_number": "1"},
        headers=AUTHORIZATION(token),
    )
    assert r1.status_code == status.HTTP_200_OK

    # Second check-in should still succeed and expire the first
    r2 = await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        json={"table_number": "2"},
        headers=AUTHORIZATION(token),
    )
    assert r2.status_code == status.HTTP_200_OK
    assert r2.json()["is_checked_in"] is True

    # Only one active session in DB (the second one)
    from app.models import CheckInSession
    result = await db.execute(
        select(CheckInSession).where(
            CheckInSession.singer_id == singer.id,
            CheckInSession.venue_id == venue_id,
        )
    )
    sessions = result.scalars().all()
    assert len(sessions) == 2
    active = [s for s in sessions if s.expires_at > datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert len(active) == 1
    assert active[0].table_number == "2"


@pytest.mark.anyio
async def test_checked_in_list_venue_scoped(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    s = await _seed_singer(db, other.id, stage_name="OtherVenue")
    token = _token_for_singer(jwt_encode, s)
    await client.post(
        f"/v1/venues/{other.id}/singers/checkin",
        json={},
        headers=AUTHORIZATION(token),
    )

    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    admin_token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/checked-in",
        headers=AUTHORIZATION(admin_token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 0


# ---------------------------------------------------------------------------
# 8. MY QUEUE POSITION / ETA / HISTORY / STATUS
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_my_queue_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/singers/me/queue")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_my_queue_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other.id, stage_name="Outsider")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_my_queue_empty(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="NoQueue")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.anyio
async def test_my_queue_returns_position_eta(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="QueueMe")
    song1 = await _seed_song(db, venue_id, title="Song A", genre="Rock")
    song2 = await _seed_song(db, venue_id, title="Song B", genre="Pop")

    # Seed active queue requests
    req1 = await _seed_queue_request(db, venue_id, singer.id, song1.id, status="pending")
    req2 = await _seed_queue_request(db, venue_id, singer.id, song2.id, status="pending")

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 2
    positions = [item["position"] for item in data["items"]]
    assert all(p > 0 for p in positions)
    assert all("eta_seconds" in item for item in data["items"])
    assert all(item["song_title"] in {"Song A", "Song B"} for item in data["items"])
    assert all(item["status"] == "pending" for item in data["items"])


@pytest.mark.anyio
async def test_my_queue_history_paginated(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="HistoryMe")
    song1 = await _seed_song(db, venue_id, title="Song A", genre="Rock")
    song2 = await _seed_song(db, venue_id, title="Song B", genre="Pop")
    await _seed_queue_request(db, venue_id, singer.id, song1.id, status="completed")
    await _seed_queue_request(db, venue_id, singer.id, song2.id, status="skipped")

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/history?page=1&per_page=1",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["page"] == 1
    assert data["per_page"] == 1


@pytest.mark.anyio
async def test_my_queue_status_active(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="ActiveMe")
    song = await _seed_song(db, venue_id, title="Song A")
    req = await _seed_queue_request(db, venue_id, singer.id, song.id, status="pending")

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/status",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "active"
    assert data["position"] is not None
    assert data["request_id"] == req.id
    assert "eta_seconds" in data


@pytest.mark.anyio
async def test_my_queue_status_waiting_no_active(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="WaitingMe")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/status",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "waiting"
    assert data["position"] is None
    assert data["request_id"] is None
    assert data["eta_seconds"] is None

