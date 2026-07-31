"""Queue core router tests — KJ live show operations.

Endpoints under test:
    POST   /queue             submit
    DELETE /queue/{id}       cancel
    PATCH  /queue/{id}       edit
    GET    /queue/list       list
    POST   /queue/{id}/start
    POST   /queue/{id}/complete
    POST   /queue/{id}/skip
    PUT    /queue/reorder
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import Venue, Song, Singer, QueueRequest

AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def kj_venue(db: AsyncSession):
    """Venue + 3 songs + 2 singers (one KJ, one regular)."""
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="KJ Venue", slug=f"kj-venue-{venue_id[:8]}")
    db.add(venue)
    await db.commit()

    songs = [
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song A", artist="A", is_available=1, duration_ms=180_000),
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song B", artist="B", is_available=1, duration_ms=240_000),
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song C", artist="C", is_available=1, duration_ms=220_000),
    ]
    for s in songs:
        db.add(s)

    kj_id = str(uuid.uuid4())
    singer_id = str(uuid.uuid4())
    kj = Singer(id=kj_id, venue_id=venue_id, stage_name="KJ Doug", role="kj", email="kj@example.com")
    singer = Singer(id=singer_id, venue_id=venue_id, stage_name="Stagey", role="singer", email="singer@example.com")
    db.add(kj)
    db.add(singer)
    await db.commit()
    for s in songs:
        await db.refresh(s)
    await db.refresh(kj)
    await db.refresh(singer)
    return venue_id, kj_id, singer_id, songs


@pytest.fixture
async def populated_queue(db: AsyncSession, kj_venue):
    """Seed 4 queue requests (2 pending, 2 approved) — no now_playing."""
    venue_id, kj_id, singer_id, songs = kj_venue

    # Mark the KJ as recently seen so queue/list considers the show online.
    from app.models import KJDevice
    from app.core.security import hash_password
    device = KJDevice(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Test KJ",
        api_key_hash=hash_password("test-key"),
        last_seen=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.add(device)

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
            singer_id=kj_id,
            song_id=songs[1].id,
            status="approved",
            source="host",
            requested_at="2026-05-21T10:01:00Z",
            rotation_position=2,
        ),
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=singer_id,
            song_id=songs[2].id,
            status="approved",
            source="host",
            requested_at="2026-05-21T10:02:00Z",
            rotation_position=3,
        ),
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=kj_id,
            song_id=songs[0].id,
            status="pending",
            source="host",
            requested_at="2026-05-21T10:03:00Z",
            rotation_position=4,
        ),
    ]
    for it in items:
        db.add(it)
    await db.commit()
    for it in items:
        await db.refresh(it)
    return venue_id, kj_id, singer_id, songs, items


# ---------------------------------------------------------------------------
# LIST
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_queue_singer(client, jwt_encode, populated_queue):
    venue_id, kj_id, singer_id, _, _ = populated_queue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/queue/list",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    # Rotation view collapses to one row per singer (2 singers).
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert {it["singer_id"] for it in data["items"]} == {singer_id, kj_id}


@pytest.mark.anyio
async def test_list_queue_no_token(client, populated_queue):
    venue_id, *_ = populated_queue
    resp = await client.get(f"/v1/venues/{venue_id}/queue/list")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# SUBMIT
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_submit_request(client, jwt_encode, kj_venue):
    venue_id, _, singer_id, songs = kj_venue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id, "notes": "For mom"},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert "request_id" in data
    assert data["status"] == "pending"
    assert data["notes"] == "For mom"


@pytest.mark.anyio
async def test_submit_max_3(client, jwt_encode, kj_venue):
    venue_id, _, singer_id, songs = kj_venue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    for i in range(3):
        resp = await client.post(
            f"/v1/venues/{venue_id}/queue",
            headers=AUTHORIZATION(token),
            json={"song_id": songs[i].id},
        )
        assert resp.status_code == status.HTTP_201_CREATED
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id},
    )
    assert resp.status_code == status.HTTP_409_CONFLICT


@pytest.mark.anyio
async def test_submit_unavailable_song(client, jwt_encode, kj_venue):
    venue_id, _, singer_id, songs = kj_venue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue",
        headers=AUTHORIZATION(token),
        json={"song_id": str(uuid.uuid4())},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_submit_venue_mismatch(client, jwt_encode, kj_venue):
    venue_id, _, singer_id, songs = kj_venue
    other = str(uuid.uuid4())
    token = jwt_encode(other, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue",
        headers=AUTHORIZATION(token),
        json={"song_id": songs[0].id},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# CANCEL OWN REQUEST (/queue/me/{request_id})
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cancel_my_request_success(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/me/{pending.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["request_id"] == str(pending.id)
    assert data["status"] == "cancelled"


@pytest.mark.anyio
async def test_cancel_my_request_not_owner(client, jwt_encode, populated_queue):
    venue_id, kj_id, singer_id, _, items = populated_queue
    kj_pending = [i for i in items if i.status == "pending" and str(i.singer_id) == kj_id][0]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/me/{kj_pending.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_cancel_my_request_not_pending(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, items = populated_queue
    approved = [i for i in items if i.status == "approved" and str(i.singer_id) == singer_id][0]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/me/{approved.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.anyio
async def test_cancel_my_request_nonexistent(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, _ = populated_queue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/me/{str(uuid.uuid4())}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_cancel_my_request_wrong_venue(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]
    wrong_venue_id = str(uuid.uuid4())
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{wrong_venue_id}/queue/me/{pending.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# CANCEL
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_cancel_own_request(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/{pending.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.anyio
async def test_cancel_not_own_request(client, jwt_encode, populated_queue):
    venue_id, kj_id, singer_id, _, items = populated_queue
    kj_item = [i for i in items if str(i.singer_id) == kj_id][0]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/{kj_item.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_cancel_nonexistent(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, _ = populated_queue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/queue/{str(uuid.uuid4())}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# EDIT
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_edit_own_request(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.patch(
        f"/v1/venues/{venue_id}/queue/{pending.id}",
        headers=AUTHORIZATION(token),
        json={"notes": "Updated notes", "dedication_to": "Mom"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "Updated notes" in data["notes"]
    assert "[Dedication to Mom]" in data["notes"]


@pytest.mark.anyio
async def test_edit_not_own_request(client, jwt_encode, populated_queue):
    venue_id, kj_id, singer_id, _, items = populated_queue
    kj_item = [i for i in items if str(i.singer_id) == kj_id][0]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.patch(
        f"/v1/venues/{venue_id}/queue/{kj_item.id}",
        headers=AUTHORIZATION(token),
        json={"notes": "Hacked"},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_edit_completed_fails(client, jwt_encode, populated_queue, db):
    venue_id, _, singer_id, _, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]
    # put this into a non-editable state by creating a new completed one
    pending.status = "completed"
    await db.commit()
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.patch(
        f"/v1/venues/{venue_id}/queue/{pending.id}",
        headers=AUTHORIZATION(token),
        json={"notes": "Updated"},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# START
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_start_request_kj(client, jwt_encode, populated_queue):
    venue_id, kj_id, _, _, items = populated_queue
    approved = [i for i in items if i.status == "approved"][0]
    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/{approved.id}/start",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "now_playing"


@pytest.mark.anyio
async def test_start_already_playing(client, jwt_encode, populated_queue):
    venue_id, kj_id, _, _, items = populated_queue
    # promote first approved -> now_playing via start
    approved = [i for i in items if i.status == "approved"][0]
    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    await client.post(
        f"/v1/venues/{venue_id}/queue/{approved.id}/start",
        headers=AUTHORIZATION(token),
    )
    # try starting the second approved
    next_approved = [i for i in items if i.status == "approved" and i.id != approved.id][0]
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/{next_approved.id}/start",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "already playing" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_start_singer_forbidden(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, items = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/{pending.id}/start",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# COMPLETE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_complete_now_playing_auto_advance(client, jwt_encode, populated_queue, db):
    venue_id, kj_id, singer_id, songs, items = populated_queue
    # Manually set one approved item to now_playing for this test
    now_playing = [i for i in items if i.status == "approved"][0]
    now_playing.status = "now_playing"
    await db.commit()

    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/{now_playing.id}/complete",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "completed"
    # Auto-advance: another now_playing should appear
    list_resp = await client.get(
        f"/v1/venues/{venue_id}/queue/list",
        headers=AUTHORIZATION(token),
    )
    statuses = [i["status"] for i in list_resp.json()["items"]]
    now_count = statuses.count("now_playing")
    assert now_count == 1


@pytest.mark.anyio
async def test_complete_pending_fails(client, jwt_encode, populated_queue):
    venue_id, kj_id, _, _, items = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/{pending.id}/complete",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# SKIP
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_skip_now_playing_auto_advance(client, jwt_encode, populated_queue, db):
    venue_id, kj_id, singer_id, songs, items = populated_queue
    now_playing = [i for i in items if i.status == "approved"][0]
    now_playing.status = "now_playing"
    await db.commit()

    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/{now_playing.id}/skip",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "skipped"


@pytest.mark.anyio
async def test_skip_pending(client, jwt_encode, populated_queue):
    venue_id, kj_id, _, _, items = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/{pending.id}/skip",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "skipped"


# ---------------------------------------------------------------------------
# REORDER
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_reorder_queue(client, jwt_encode, populated_queue):
    venue_id, kj_id, _, _, items = populated_queue
    ids = [i.id for i in items]
    new_order = list(reversed(ids))
    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp = await client.put(
        f"/v1/venues/{venue_id}/queue/reorder",
        headers=AUTHORIZATION(token),
        json={"order": new_order},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    returned_ids = [i["request_id"] for i in data["items"]]
    assert returned_ids == new_order
    assert data["total"] == 4


@pytest.mark.anyio
async def test_reorder_singer_forbidden(client, jwt_encode, populated_queue):
    venue_id, _, singer_id, _, items = populated_queue
    ids = [i.id for i in items]
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.put(
        f"/v1/venues/{venue_id}/queue/reorder",
        headers=AUTHORIZATION(token),
        json={"order": ids},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_reorder_with_invalid_id(client, jwt_encode, populated_queue):
    venue_id, kj_id, _, _, items = populated_queue
    ids = [i.id for i in items]
    ids.append(str(uuid.uuid4()))
    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp = await client.put(
        f"/v1/venues/{venue_id}/queue/reorder",
        headers=AUTHORIZATION(token),
        json={"order": ids},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "do not belong" in resp.json()["detail"]


@pytest.mark.anyio
async def test_rejected_request_excluded_from_history(client, jwt_encode, populated_queue, db):
    """A request rejected by the KJ must not appear in /singers/me/queue/history."""
    venue_id, kj_id, singer_id, songs, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]

    kj_token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/reject",
        headers=AUTHORIZATION(kj_token),
        json={"reason": "rotation_full", "rejected_by": "KJ Doug"},
    )

    singer_token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/history",
        headers=AUTHORIZATION(singer_token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert not any(it["request_id"] == str(pending.id) for it in data["items"])


@pytest.mark.anyio
async def test_rejected_requests_endpoint(client, jwt_encode, populated_queue, db):
    """Rejected requests surface on /singers/me/queue/rejected with metadata."""
    venue_id, kj_id, singer_id, songs, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]

    kj_token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/reject",
        headers=AUTHORIZATION(kj_token),
        json={"reason": "explicit_content", "rejected_by": "KJ Doug"},
    )

    singer_token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/rejected",
        headers=AUTHORIZATION(singer_token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["request_id"] == str(pending.id)
    assert item["status"] == "rejected"
    assert item["rejected_reason"] == "explicit_content"
    assert item["rejected_by"] == "KJ Doug"
    assert "rejected_at" in item


@pytest.mark.anyio
async def test_rejected_requests_retention_cutoff(client, jwt_encode, populated_queue, db):
    """Rejected requests older than PURGE_RETENTION_DAYS are hidden."""
    from app.core.config import settings
    from datetime import datetime, timedelta, timezone

    venue_id, kj_id, singer_id, songs, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]

    kj_token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/reject",
        headers=AUTHORIZATION(kj_token),
        json={"reason": "not_available"},
    )

    # Simulate a rejection outside the retention window
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.PURGE_RETENTION_DAYS + 1)
    pending.rejected_at = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    await db.commit()

    singer_token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/rejected",
        headers=AUTHORIZATION(singer_token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["items"] == []


@pytest.mark.anyio
async def test_rejected_request_includes_song_title_in_event(client, jwt_encode, populated_queue, db, monkeypatch):
    """Rejection event payload contains song_title and rejected_by."""
    venue_id, kj_id, singer_id, songs, items = populated_queue
    pending = [i for i in items if i.status == "pending" and str(i.singer_id) == singer_id][0]
    captured = []

    from app.core import queue_service
    original_publish = queue_service.QueueEventPublisher.publish

    async def _capture_publish(vid, event_type, data):
        if event_type == "request_rejected":
            captured.append(data)
        await original_publish(vid, event_type, data)

    monkeypatch.setattr(queue_service.QueueEventPublisher, "publish", _capture_publish)

    kj_token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{pending.id}/reject",
        headers=AUTHORIZATION(kj_token),
        json={"reason": "venue_policy", "rejected_by": "KJ Doug"},
    )
    assert resp.status_code == status.HTTP_200_OK
    assert captured
    assert captured[0]["song_title"] is not None
    assert captured[0]["rejected_by"] == "KJ Doug"
    assert captured[0]["rejected_at"] is not None


@pytest.mark.anyio
async def test_history_still_includes_completed_and_skipped(client, jwt_encode, populated_queue, db):
    """History continues to include completed and skipped after the change."""
    venue_id, kj_id, singer_id, songs, items = populated_queue
    singer_items = [i for i in items if str(i.singer_id) == singer_id]
    completed = singer_items[0]
    skipped = singer_items[1]
    completed.status = "completed"
    completed.played_at = "2026-05-21T11:00:00Z"
    skipped.status = "skipped"
    skipped.played_at = "2026-05-21T11:05:00Z"
    await db.commit()

    singer_token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/history",
        headers=AUTHORIZATION(singer_token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    ids = {it["request_id"] for it in data["items"]}
    assert str(completed.id) in ids
    assert str(skipped.id) in ids


# ---------------------------------------------------------------------------
# RBAC cross-checks
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_start_requires_kj_or_admin(client, jwt_encode, populated_queue):
    """Owner role in token should work if DB singer role is at least KJ."""
    venue_id, kj_id, singer_id, _, items = populated_queue
    pending = [i for i in items if i.status == "pending"][0]
    # Use kj_id with role="owner" in token — DB says kj, hierarchy says kj >= kj
    token = jwt_encode(venue_id, role="owner", user_id=kj_id)
    resp = await client.post(
        f"/v1/venues/{venue_id}/queue/{pending.id}/start",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK  # DB role 'kj', token says 'owner' — get_current_user uses DB role via SingerUser


@pytest.mark.anyio
async def test_reorder_requires_kj_or_admin(client, jwt_encode, populated_queue):
    venue_id, kj_id, _, _, items = populated_queue
    ids = [i.id for i in items]
    # Use kj_id — DB role is 'kj' which outranks KJ requirement
    token = jwt_encode(venue_id, role="owner", user_id=kj_id)
    resp = await client.put(
        f"/v1/venues/{venue_id}/queue/reorder",
        headers=AUTHORIZATION(token),
        json={"order": ids},
    )
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.anyio
async def test_only_one_now_playing_after_start(client, jwt_encode, populated_queue, db):
    """Start two items separately — second should fail if first is still playing."""
    venue_id, kj_id, _, _, items = populated_queue
    approved = [i for i in items if i.status == "approved"]
    token = jwt_encode(venue_id, role="kj", user_id=kj_id)
    resp1 = await client.post(
        f"/v1/venues/{venue_id}/queue/{approved[0].id}/start",
        headers=AUTHORIZATION(token),
    )
    assert resp1.status_code == status.HTTP_200_OK
    resp2 = await client.post(
        f"/v1/venues/{venue_id}/queue/{approved[1].id}/start",
        headers=AUTHORIZATION(token),
    )
    assert resp2.status_code == status.HTTP_400_BAD_REQUEST
    assert "already playing" in resp2.json()["detail"].lower()



class TestNowPlayingDedupe:
    @pytest.mark.anyio
    async def test_broadcast_queue_state_handles_multiple_now_playing_rows(self, db, venue_with_songs):
        venue_id, _ = venue_with_songs
        from app.models import QueueRequest, KJDevice
        from app.core.queue_service import QueueService

        # Seed a KJ device so the broadcast treats the venue as online.
        kj = KJDevice(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            api_key_hash="test-key-hash",
            name="Test KJ",
            last_seen=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        db.add(kj)

        song_result = await db.execute(select(Song).where(Song.venue_id == venue_id).limit(1))
        song = song_result.scalar_one_or_none()
        assert song is not None

        s1 = Singer(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            stage_name="Dedupe Singer One",
        )
        s2 = Singer(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            stage_name="Dedupe Singer Two",
        )
        db.add_all([s1, s2])
        await db.commit()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        q1 = QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=s1.id,
            song_id=song.id,
            status="now_playing",
            source="host",
            rotation_position=1,
            requested_at=now,
            updated_at=now,
        )
        q2 = QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=s2.id,
            song_id=song.id,
            status="now_playing",
            source="host",
            rotation_position=2,
            requested_at=now,
            updated_at=now,
        )
        db.add_all([q1, q2])
        await db.commit()

        svc = QueueService(db)
        await svc.broadcast_queue_state(venue_id)

        result = await db.execute(
            select(func.count())
            .select_from(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status == "now_playing",
                QueueRequest.deleted_at.is_(None),
            )
        )
        assert result.scalar_one() == 1
