"""KJ Queue Admin tests."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Venue, Song, Singer, QueueRequest


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures (local to this test file)
# ---------------------------------------------------------------------------

@pytest.fixture
async def venue_with_singers_and_songs(db: AsyncSession):
    """Create a venue, 2 singers, and 3 songs."""
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name="KJ Venue",
        slug=f"kj-venue-{venue_id[:8]}",
    )
    db.add(venue)
    await db.commit()

    songs = [
        Song(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            title="Song A",
            artist="Artist A",
            is_available=1,
        ),
        Song(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            title="Song B",
            artist="Artist B",
            is_available=1,
        ),
        Song(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            title="Song C",
            artist="Artist C",
            is_available=1,
        ),
    ]
    for s in songs:
        db.add(s)

    singers = [
        Singer(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            stage_name="Singer1",
            role="singer",
        ),
        Singer(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            stage_name="Singer2",
            role="singer",
        ),
    ]
    for s in singers:
        db.add(s)

    await db.commit()
    for s in songs + singers:
        await db.refresh(s)

    return venue_id, singers, songs


@pytest.fixture
async def populated_queue(db: AsyncSession, venue_with_singers_and_songs):
    """Seed 4 queue requests (2 per singer) in mixed statuses."""
    venue_id, singers, songs = venue_with_singers_and_songs
    s1, s2 = singers
    items = [
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=s1.id,
            song_id=songs[0].id,
            status="pending",
            requested_at="2026-05-21T10:00:00Z",
            rotation_position=1,
        ),
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=s2.id,
            song_id=songs[1].id,
            status="pending",
            requested_at="2026-05-21T10:01:00Z",
            rotation_position=2,
        ),
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=s1.id,
            song_id=songs[2].id,
            status="approved",
            requested_at="2026-05-21T10:02:00Z",
            rotation_position=3,
        ),
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=s2.id,
            song_id=songs[0].id,
            status="now_playing",
            requested_at="2026-05-21T10:03:00Z",
            rotation_position=4,
        ),
    ]
    for it in items:
        db.add(it)
    await db.commit()
    for it in items:
        await db.refresh(it)
    return venue_id, items, singers, songs


# ---------------------------------------------------------------------------
# 1. LIST
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_admin_queue_list_admin(client, jwt_encode, populated_queue):
    venue_id, items, singers, songs = populated_queue
    token = jwt_encode(venue_id, role="admin")
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 4
    assert len(data["items"]) == 4
    # Round-robin: singer1, singer2, singer1, singer2
    assert data["items"][0]["singer"]["stage_name"] == "Singer1"
    assert data["items"][1]["singer"]["stage_name"] == "Singer2"


@pytest.mark.anyio
async def test_admin_queue_list_kj(client, jwt_encode, populated_queue):
    venue_id, items, singers, songs = populated_queue
    token = jwt_encode(venue_id, role="kj")
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 4


@pytest.mark.anyio
async def test_admin_queue_list_singer_forbidden(client, jwt_encode, populated_queue):
    venue_id, *_ = populated_queue
    token = jwt_encode(venue_id, role="singer")
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_admin_queue_list_no_token(client, populated_queue):
    venue_id, *_ = populated_queue
    resp = await client.get(f"/v1/venues/{venue_id}/queue/admin")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_admin_queue_list_venue_mismatch(client, jwt_encode, populated_queue):
    venue_id, *_ = populated_queue
    other = str(uuid.uuid4())
    token = jwt_encode(other, role="admin")
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 2. APPROVE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_approve_pending(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    token = jwt_encode(venue_id, role="kj")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/approve",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "approved"


@pytest.mark.anyio
async def test_approve_already_rejected(client, jwt_encode, populated_queue, db):
    venue_id, items, *_ = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    # reject it first
    pending.status = "rejected"
    pending.reject_reason = "nope"
    await db.commit()

    token = jwt_encode(venue_id, role="kj")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/approve",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# 3. REJECT
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_reject_with_reason(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    token = jwt_encode(venue_id, role="admin")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/reject",
        json={"reason": "Song not available"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["reject_reason"] == "Song not available"


@pytest.mark.anyio
async def test_reject_without_reason(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    token = jwt_encode(venue_id, role="admin")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/reject",
        json={},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "rejected"


# ---------------------------------------------------------------------------
# 4. COMPLETE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_complete_approved(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    approved = [i for i in items if i.status == "approved"][0]
    token = jwt_encode(venue_id, role="kj")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{approved.id}/complete",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "completed"
    assert data["played_at"] is not None


@pytest.mark.anyio
async def test_complete_pending_fails(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    token = jwt_encode(venue_id, role="kj")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/complete",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# 5. REORDER
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_reorder_queue(client, jwt_encode, populated_queue):
    venue_id, items, singers, songs = populated_queue
    # Test NEW reorder: PUT /queue/admin/reorder with singer_ids
    ids = [s.id for s in singers]
    # reverse singer order
    new_order = list(reversed(ids))
    token = jwt_encode(venue_id, role="admin")
    resp = await client.put(
        f"/v1/venues/{venue_id}/queue/admin/reorder",
        json={"singer_ids": new_order},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    returned_singer_names = [i["singer"]["stage_name"] for i in data["items"]]
    # Singer2 has items 0,1 (positions 1,2), Singer1 has items 2,3 (positions 3,4)
    assert returned_singer_names == ["Singer2", "Singer2", "Singer1", "Singer1"]


@pytest.mark.anyio
async def test_reorder_by_request_id_legacy(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    ids = [i.id for i in items]
    # reverse
    new_order = list(reversed(ids))
    token = jwt_encode(venue_id, role="admin")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/reorder-by-request",
        json={"order": new_order},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    returned_ids = [i["request_id"] for i in data["items"]]
    assert returned_ids == new_order


@pytest.mark.anyio
async def test_reorder_with_invalid_id(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    ids = [i.id for i in items]
    ids.append(str(uuid.uuid4()))  # extra invalid id
    token = jwt_encode(venue_id, role="admin")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/reorder-by-request",
        json={"order": ids},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "do not belong" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 6. SKIP TO END
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_skip_to_end(client, jwt_encode, populated_queue):
    venue_id, items, singers, songs = populated_queue
    target = items[0]  # first item
    token = jwt_encode(venue_id, role="admin")
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/skip-to-end",
        json={"request_id": target.id},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    # It should now be the last position (5, after all 4 existing items)
    assert data["position"] == 5


# ---------------------------------------------------------------------------
# 7. ANALYTICS
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_queue_analytics(client, jwt_encode, populated_queue):
    venue_id, *_ = populated_queue
    token = jwt_encode(venue_id, role="admin")
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/admin/analytics",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "total_requests_today" in data
    assert "completed_today" in data
    assert "avg_wait_seconds" in data
    assert "top_songs" in data
    assert "throughput_per_hour" in data
    assert len(data["throughput_per_hour"]) == 24


# ---------------------------------------------------------------------------
# 8. ROTATION MODE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_rotation_mode(client, jwt_encode, populated_queue):
    venue_id, *_ = populated_queue
    token = jwt_encode(venue_id, role="admin")
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/admin/mode",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["mode"] == "round_robin"
    assert data["venue_id"] == venue_id


@pytest.mark.anyio
async def test_set_rotation_mode_fifo(client, jwt_encode, populated_queue):
    venue_id, *_ = populated_queue
    token = jwt_encode(venue_id, role="admin")
    resp = await client.put(
        f"/v1/venues/{venue_id}/queue/admin/mode",
        json={"mode": "fifo"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["mode"] == "fifo"


@pytest.mark.anyio
async def test_set_rotation_mode_invalid(client, jwt_encode, populated_queue):
    venue_id, *_ = populated_queue
    token = jwt_encode(venue_id, role="admin")
    resp = await client.put(
        f"/v1/venues/{venue_id}/queue/admin/mode",
        json={"mode": "invalid"},
        headers=AUTHORIZATION(token),
    )
    # Pydantic rejects invalid enum values with 422 before business logic
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# 9. SINGER BAN (via singers router)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_ban_singer(client, jwt_encode, populated_queue, db):
    venue_id, items, singers, songs = populated_queue
    target = singers[0]
    # Seed an admin singer with password for login token
    from tests.test_singers import _seed_singer
    admin_singer = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    from tests.test_singers import _token_for_singer
    token = _token_for_singer(jwt_encode, admin_singer)
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/{target.id}/ban",
        json={"reason": "Disruptive behavior"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["singer_id"] == target.id
    assert data["status"] == "banned"
    assert data["reason"] == "Disruptive behavior"


@pytest.mark.anyio
async def test_ban_singer_kj_allowed(client, jwt_encode, populated_queue, db):
    venue_id, items, singers, songs = populated_queue
    target = singers[0]
    from tests.test_singers import _seed_singer, _token_for_singer
    kj = await _seed_singer(db, venue_id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/{target.id}/ban",
        json={},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "banned"


@pytest.mark.anyio
async def test_ban_singer_singer_forbidden(client, jwt_encode, populated_queue, db):
    venue_id, items, singers, songs = populated_queue
    target = singers[0]
    from tests.test_singers import _token_for_singer
    token = _token_for_singer(jwt_encode, singers[1])
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/{target.id}/ban",
        json={},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 10. ROUND-ROBIN VERIFICATION
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_round_robin_ordering(client, jwt_encode, populated_queue):
    venue_id, items, singers, songs = populated_queue
    # With 4 items and 2 singers: singer1 at pos 1,3; singer2 at pos 2,4
    token = jwt_encode(venue_id, role="admin")
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(token),
    )
    data = resp.json()
    names = [i["singer"]["stage_name"] for i in data["items"]]
    # Singer1 at positions 1,3; Singer2 at positions 2,4
    assert names[0] == "Singer1"
    assert names[1] == "Singer2"
    assert names[2] == "Singer1"
    assert names[3] == "Singer2"


# ---------------------------------------------------------------------------
# 11. DELETE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_remove_request(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    target = items[0]
    token = jwt_encode(venue_id, role="kj")
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/admin/{target.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    # verify it vanishes from list
    list_resp = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(token),
    )
    assert list_resp.json()["total"] == 3


@pytest.mark.anyio
async def test_remove_wrong_venue(client, jwt_encode, populated_queue):
    venue_id, items, *_ = populated_queue
    other = str(uuid.uuid4())
    token = jwt_encode(other, role="admin")
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/admin/{items[0].id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN

