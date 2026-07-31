"""Singer-facing queue operations tests."""

from __future__ import annotations

import uuid

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Venue, Song, Singer, QueueRequest

AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def venue_with_singer(db: AsyncSession):
    """Create venue, singer (with password_hash for auth), and 4 songs."""
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name="Singer Venue",
        slug=f"singer-venue-{venue_id[:8]}",
    )
    db.add(venue)
    await db.commit()

    singer_id = str(uuid.uuid4())
    singer = Singer(
        id=singer_id,
        venue_id=venue_id,
        stage_name="Stagey McStagename",
        email="singer@example.com",
        password_hash="$2b$12$bogus",  # never used directly — we issue JWT manually
        role="singer",
    )
    db.add(singer)
    await db.commit()

    songs = [
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song A", artist="Artist A", is_available=1, duration_ms=180_000),
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song B", artist="Artist B", is_available=1, duration_ms=240_000),
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song C", artist="Artist C", is_available=1, duration_ms=200_000),
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song D", artist="Artist D", is_available=0, duration_ms=150_000),
    ]
    for s in songs:
        db.add(s)
    await db.commit()
    for s in songs:
        await db.refresh(s)
    await db.refresh(singer)

    return venue_id, singer_id, songs


@pytest.fixture
async def populated_singer_queue(db: AsyncSession, venue_with_singer):
    """Seed 2 active requests for the singer."""
    venue_id, singer_id, songs = venue_with_singer
    items = [
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=singer_id,
            song_id=songs[0].id,
            status="pending",
            source="host",
            requested_at="2026-05-21T10:00:00Z",
            rotation_position=1,
        ),
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=singer_id,
            song_id=songs[1].id,
            status="pending",
            source="host",
            requested_at="2026-05-21T10:01:00Z",
            rotation_position=2,
        ),
    ]
    for it in items:
        db.add(it)
    await db.commit()
    for it in items:
        await db.refresh(it)
    return venue_id, singer_id, songs, items


# ---------------------------------------------------------------------------
# 1. JOIN
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_join_queue_success(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id, "notes": "For mom"},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert "request_id" in data
    assert data["estimated_position"] == 1
    assert data["warning"] is None


@pytest.mark.anyio
async def test_join_queue_duplicate_warning(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp1 = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id},
    )
    assert resp1.status_code == status.HTTP_201_CREATED

    resp2 = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id},
    )
    assert resp2.status_code == status.HTTP_201_CREATED
    data = resp2.json()
    assert data["warning"] == "You already have this song in the queue"


@pytest.mark.anyio
async def test_join_queue_max_3(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    for i in range(4):
        resp = await client.post(
            f"/v1/venues/{venue_id}/queue/join",
            headers=AUTHORIZATION(token),
            json={"song_id": songs[i].id if i < 3 else songs[0].id},
        )
        if i < 3:
            assert resp.status_code == status.HTTP_201_CREATED
        else:
            assert resp.status_code == status.HTTP_409_CONFLICT
            assert "Maximum of 3" in resp.json()["detail"]


@pytest.mark.anyio
async def test_join_queue_song_unavailable_404(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[3].id},  # unavailable
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_join_queue_venue_mismatch_403(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    other_venue = str(uuid.uuid4())
    token = jwt_encode(other_venue, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_join_queue_no_token(client, venue_with_singer):
    venue_id, _, songs = venue_with_singer
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        json={"song_id": songs[0].id},
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_join_queue_nonexistent_venue(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    fake_venue = str(uuid.uuid4())
    token = jwt_encode(fake_venue, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{fake_venue}/queue/join",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id},
    )
    # Token venue does not match singer's actual venue = 403 before DB venue check
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 2. STATUS
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_queue_status_positions(client, jwt_encode, populated_singer_queue):
    venue_id, singer_id, songs, items = populated_singer_queue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/status",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data) == 2
    assert data[0]["position"] == 1
    assert data[0]["song_title"] == "Song A"
    assert data[1]["position"] == 2
    assert data[1]["status"] == "pending"
    assert "eta_seconds" in data[0]


@pytest.mark.anyio
async def test_queue_status_empty(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/status",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data == []


@pytest.mark.anyio
async def test_queue_status_wrong_venue(client, jwt_encode, populated_singer_queue):
    venue_id, singer_id, *_ = populated_singer_queue
    other = str(uuid.uuid4())
    token = jwt_encode(other, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/status",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 3. LEAVE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_leave_specific_request(client, jwt_encode, populated_singer_queue):
    venue_id, singer_id, songs, items = populated_singer_queue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/leave?request_id={items[0].id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["removed"] == 1

    status_resp = await client.get(
        f"/v1/venues/{venue_id}/queue/status",
        headers=AUTHORIZATION(token),
    )
    assert len(status_resp.json()) == 1


@pytest.mark.anyio
async def test_leave_all_requests(client, jwt_encode, populated_singer_queue):
    venue_id, singer_id, songs, items = populated_singer_queue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/leave",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["removed"] == 2

    status_resp = await client.get(
        f"/v1/venues/{venue_id}/queue/status",
        headers=AUTHORIZATION(token),
    )
    assert status_resp.json() == []


@pytest.mark.anyio
async def test_leave_not_own_request(client, jwt_encode, populated_singer_queue, db):
    venue_id, _, songs, items = populated_singer_queue
    other_id = str(uuid.uuid4())
    other = Singer(
        id=other_id,
        venue_id=venue_id,
        stage_name="Imposter",
        role="singer",
    )
    db.add(other)
    await db.commit()

    token = jwt_encode(venue_id, role="singer", user_id=other_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/leave?request_id={items[0].id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_leave_nonexistent_request(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/leave?request_id={str(uuid.uuid4())}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_leave_no_token(client, populated_singer_queue):
    venue_id, *_ = populated_singer_queue
    resp = await client.delete(f"/v1/venues/{venue_id}/queue/leave")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# 4. PUBLIC VIEW
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_public_queue_returns_items(client, populated_singer_queue):
    venue_id, *_ = populated_singer_queue
    resp = await client.get(f"/v1/venues/{venue_id}/queue/venue")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["venue_id"] == venue_id
    assert len(data["items"]) == 2
    item = data["items"][0]
    assert "song_title" in item
    assert "stage_name" in item
    assert "email" not in item
    assert "phone" not in item


@pytest.mark.anyio
async def test_public_queue_venue_not_found(client):
    resp = await client.get(f"/v1/venues/{str(uuid.uuid4())}/queue/venue")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_public_queue_empty(client, venue_with_singer):
    venue_id, *_ = venue_with_singer
    resp = await client.get(f"/v1/venues/{venue_id}/queue/venue")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["items"] == []
    assert data["current_song"] is None


@pytest.mark.anyio
async def test_public_queue_shows_current_song(client, jwt_encode, populated_singer_queue, db):
    venue_id, singer_id, songs, items = populated_singer_queue
    items[0].status = "now_playing"
    await db.commit()

    resp = await client.get(f"/v1/venues/{venue_id}/queue/venue")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["current_song"] is not None
    assert data["current_song"]["song_title"] == "Song A"
    assert data["current_song"]["stage_name"] == "Stagey McStagename"



# ---------------------------------------------------------------------------
# Tempo / Pitch
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_join_queue_with_tempo_pitch(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id, "notes": "For mom", "tempo": 5, "pitch": -2},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["tempo"] == 5
    assert data["pitch"] == -2


@pytest.mark.anyio
async def test_last_performance_defaults_to_zero(client, jwt_encode, venue_with_singer):
    venue_id, singer_id, songs = venue_with_singer
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/history/{songs[0].id}/last-performance",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["song_id"] == songs[0].id
    assert data["tempo"] == 0
    assert data["pitch"] == 0
    assert data["performed_at"] is None


@pytest.mark.anyio
async def test_last_performance_returns_latest_values(client, jwt_encode, venue_with_singer, db):
    venue_id, singer_id, songs = venue_with_singer
    # Seed a completed request with tempo/pitch
    from app.models import QueueRequest
    q = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=singer_id,
        song_id=songs[0].id,
        status="completed",
        tempo=7,
        pitch=-3,
        requested_at="2026-05-21T10:00:00Z",
        played_at="2026-05-21T10:05:00Z",
        rotation_position=1,
    )
    db.add(q)
    await db.commit()

    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/history/{songs[0].id}/last-performance",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["tempo"] == 7
    assert data["pitch"] == -3
    assert data["performed_at"] == "2026-05-21T10:05:00Z"
