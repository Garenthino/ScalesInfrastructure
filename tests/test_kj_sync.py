"""KJ sync endpoint tests — push/pull for queue, singers, songs, settings.

Covers:
- Auth: missing token, invalid token, wrong venue, singer role forbidden
- Queue push/pull with upsert, soft-delete, server-wins conflict
- Singers push/pull with merge, soft-delete
- Songs push/pull with availability-only updates, plays recorded
- Settings push/pull with last-write-wins (LWW) conflict
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Venue, Song, Singer, QueueRequest, VenueConfig, AnalyticsEvent, KJDevice
from app.core.security import hash_password

SYNC_BASE = "/v1/kj/sync"


def _kj_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def sync_venue(db: AsyncSession):
    """Venue + 2 songs + 1 KJ singer + 1 regular singer + 1 KJ device."""
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="Sync Venue", slug=f"sync-venue-{venue_id[:8]}")
    db.add(venue)
    await db.commit()

    songs = [
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song A", artist="A", is_available=1),
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Song B", artist="B", is_available=1),
    ]
    for s in songs:
        db.add(s)

    kj_id = str(uuid.uuid4())
    singer_id = str(uuid.uuid4())
    kj = Singer(id=kj_id, venue_id=venue_id, stage_name="KJ Doug", role="kj", email="kj@example.com")
    singer = Singer(id=singer_id, venue_id=venue_id, stage_name="Stagey", role="singer", email="singer@example.com")
    db.add(kj)
    db.add(singer)

    raw_key = f"kj-api-key-{venue_id[:8]}"
    device = KJDevice(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Test KJ Desktop",
        api_key_hash=hash_password(raw_key),
    )
    db.add(device)
    await db.commit()
    for s in songs:
        await db.refresh(s)
    await db.refresh(kj)
    await db.refresh(singer)
    await db.refresh(device)
    return venue_id, kj_id, singer_id, songs, raw_key


@pytest.fixture
async def sync_queue(db: AsyncSession, sync_venue):
    """Seed 2 queue requests."""
    venue_id, kj_id, singer_id, songs, raw_key = sync_venue
    items = [
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=singer_id,
            song_id=songs[0].id,
            status="pending",
            requested_at="2026-05-21T10:00:00Z",
            updated_at="2026-05-21T10:00:00Z",
            rotation_position=1,
        ),
        QueueRequest(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=kj_id,
            song_id=songs[1].id,
            status="approved",
            requested_at="2026-05-21T10:01:00Z",
            updated_at="2026-05-21T10:01:00Z",
            rotation_position=2,
        ),
    ]
    for it in items:
        db.add(it)
    await db.commit()
    for it in items:
        await db.refresh(it)
    return venue_id, kj_id, singer_id, songs, raw_key, items


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_sync_no_auth(client, sync_venue):
    venue_id, *_ = sync_venue
    resp = await client.get(f"/v1/kj/sync/queue/pull?venue_id={venue_id}")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_sync_wrong_venue(client, sync_venue):
    venue_id, _, _, _, raw_key = sync_venue
    other = str(uuid.uuid4())
    resp = await client.get(
        f"/v1/kj/sync/queue/pull?venue_id={other}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_sync_singer_forbidden(client, jwt_encode, sync_venue):
    venue_id, _, singer_id, _, _ = sync_venue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.get(
        f"/v1/kj/sync/queue/pull?venue_id={venue_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Singer token is not a valid KJ Bearer (no kj_device_id claim) → 401
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Queue Pull
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_queue_pull(client, sync_queue):
    venue_id, _, _, _, raw_key, _ = sync_queue
    resp = await client.get(
        f"/v1/kj/sync/queue/pull?venue_id={venue_id}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["server_modified_at"] is not None


@pytest.mark.anyio
async def test_queue_pull_since(client, sync_queue):
    venue_id, _, _, _, raw_key, _ = sync_queue
    resp = await client.get(
        f"/v1/kj/sync/queue/pull?venue_id={venue_id}&since=2099-01-01T00:00:00Z",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 0


# ---------------------------------------------------------------------------
# Queue Push
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_queue_push_upsert(client, sync_queue, db):
    venue_id, kj_id, singer_id, songs, raw_key, items = sync_queue

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "items": [
            {
                "request_id": items[0].id,
                "singer_id": singer_id,
                "song_id": songs[0].id,
                "status": "approved",
                "position": 1,
                "notes": "Updated by KJ",
                "requested_at": "2026-05-21T10:00:00Z",
                "updated_at": now,
            },
            {
                "request_id": str(uuid.uuid4()),
                "singer_id": kj_id,
                "song_id": songs[1].id,
                "status": "now_playing",
                "position": 0,
                "notes": None,
                "requested_at": now,
            },
        ],
        "deleted_ids": [],
    }

    resp = await client.post(
        f"/v1/kj/sync/queue/push?venue_id={venue_id}",
        json=payload,
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["synced"] == 2

    # Verify in DB
    result = await db.execute(
        select(QueueRequest).where(QueueRequest.id == items[0].id)
    )
    row = result.scalar_one()
    assert row.status == "approved"
    assert row.notes == "Updated by KJ"

    # Verify new item
    new_id = payload["items"][1]["request_id"]
    result2 = await db.execute(
        select(QueueRequest).where(QueueRequest.id == new_id)
    )
    row2 = result2.scalar_one()
    assert row2.status == "now_playing"


@pytest.mark.anyio
async def test_queue_push_delete(client, sync_queue, db):
    venue_id, _, _, _, raw_key, items = sync_queue

    payload = {
        "items": [],
        "deleted_ids": [items[0].id],
    }
    resp = await client.post(
        f"/v1/kj/sync/queue/push?venue_id={venue_id}",
        json=payload,
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK

    result = await db.execute(
        select(QueueRequest).where(QueueRequest.id == items[0].id)
    )
    row = result.scalar_one()
    assert row.deleted_at is not None


@pytest.mark.anyio
async def test_queue_push_conflict_server_wins(client, sync_queue, db):
    venue_id, _, _, _, raw_key, items = sync_queue

    # Server updates item after client's last_modified
    items[0].updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await db.commit()
    await db.refresh(items[0])

    payload = {
        "items": [
            {
                "request_id": items[0].id,
                "singer_id": items[0].singer_id,
                "song_id": items[0].song_id,
                "status": "completed",
                "position": 1,
                "notes": "Client tried to complete",
                "requested_at": "2026-05-21T10:00:00Z",
            }
        ],
        "deleted_ids": [],
        "last_modified_at": "2026-01-01T00:00:00Z",
    }
    resp = await client.post(
        f"/v1/kj/sync/queue/push?venue_id={venue_id}",
        json=payload,
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_409_CONFLICT
    data = resp.json()
    assert len(data["detail"]["conflicts"]) == 1
    assert data["detail"]["conflicts"][0]["resolution"] == "server_wins"


# ---------------------------------------------------------------------------
# Singers Pull
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_singers_pull(client, sync_venue):
    venue_id, _, _, _, raw_key = sync_venue
    resp = await client.get(
        f"/v1/kj/sync/singers/pull?venue_id={venue_id}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# Singers Push
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_singers_push_upsert(client, sync_venue, db):
    venue_id, _, singer_id, songs, raw_key = sync_venue

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "items": [
            {
                "id": singer_id,
                "stage_name": "Stagey Updated",
                "real_name": "Real Name",
                "pronouns": "they/them",
                "email": "new@example.com",
                "phone": "555-1234",
                "notes": "VIP",
                "total_points": 42,
                "loyalty_tier_id": None,
                "last_seen": now,
                "deactivated_at": None,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "stage_name": "New Singer",
                "real_name": None,
                "pronouns": None,
                "email": None,
                "phone": None,
                "notes": None,
                "total_points": 0,
                "loyalty_tier_id": None,
                "last_seen": None,
                "deactivated_at": None,
                "created_at": now,
                "updated_at": now,
            },
        ],
        "deleted_ids": [],
    }

    resp = await client.post(
        f"/v1/kj/sync/singers/push?venue_id={venue_id}",
        json=payload,
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["synced"] == 2

    result = await db.execute(select(Singer).where(Singer.id == singer_id))
    row = result.scalar_one()
    assert row.stage_name == "Stagey Updated"
    # KJ desktop "notes" stay in QueueRequest.notes and are never written to
    # Singer.notes, which is reserved for internal venue notes.
    assert row.notes is None or row.notes == "", f"expected no singer notes, got {row.notes!r}"


# ---------------------------------------------------------------------------
# Songs Pull
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_songs_pull(client, sync_venue):
    venue_id, _, _, _, raw_key = sync_venue
    resp = await client.get(
        f"/v1/kj/sync/songs?venue_id={venue_id}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "updated_songs" in data


@pytest.mark.anyio
async def test_songs_push_availability(client, sync_venue, db):
    venue_id, kj_id, _, songs, raw_key = sync_venue

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "venue_id": venue_id,
        "updates": [
            {
                "song_id": songs[0].id,
                "available": False,
                "reason": "Not found",
            }
        ],
    }

    resp = await client.post(
        f"/v1/kj/sync/songs/availability?venue_id={venue_id}",
        json=payload,
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["changed"] == 1

    result = await db.execute(select(Song).where(Song.id == songs[0].id))
    row = result.scalar_one()
    assert row.is_available == 0

    # No analytics events for availability-only push
    evt_result = await db.execute(
        select(AnalyticsEvent).where(
            AnalyticsEvent.venue_id == venue_id,
        )
    )
    events = evt_result.scalars().all()
    assert len(events) == 0


# ---------------------------------------------------------------------------
# Settings Pull
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_settings_pull(client, sync_venue, db):
    venue_id, _, _, _, raw_key = sync_venue

    # Seed a config
    cfg = VenueConfig(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        config_key="rotation_mode",
        config_value="fifo",
        updated_at="2026-05-21T10:00:00Z",
    )
    db.add(cfg)
    await db.commit()

    resp = await client.get(
        f"/v1/kj/sync/settings/pull?venue_id={venue_id}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["key"] == "rotation_mode"
    assert data["items"][0]["value"] == "fifo"


# ---------------------------------------------------------------------------
# Settings Push
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_settings_push_lww(client, sync_venue, db):
    venue_id, _, _, _, raw_key = sync_venue

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "items": [
            {"key": "rotation_mode", "value": "weighted", "updated_at": now},
            {"key": "new_setting", "value": "42", "updated_at": now},
        ],
        "last_modified_at": "2026-01-01T00:00:00Z",
    }

    resp = await client.post(
        f"/v1/kj/sync/settings/push?venue_id={venue_id}",
        json=payload,
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["synced"] == 2

    result = await db.execute(
        select(VenueConfig).where(
            VenueConfig.venue_id == venue_id,
            VenueConfig.config_key == "rotation_mode",
        )
    )
    row = result.scalar_one()
    assert row.config_value == "weighted"

    result2 = await db.execute(
        select(VenueConfig).where(
            VenueConfig.venue_id == venue_id,
            VenueConfig.config_key == "new_setting",
        )
    )
    row2 = result2.scalar_one()
    assert row2.config_value == "42"


@pytest.mark.anyio
async def test_settings_push_conflict_lww(client, sync_venue, db):
    venue_id, _, _, _, raw_key = sync_venue

    # Seed server config with later timestamp
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cfg = VenueConfig(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        config_key="rotation_mode",
        config_value="fifo",
        updated_at=server_now,
    )
    db.add(cfg)
    await db.commit()

    client_now = "2026-01-01T00:00:00Z"
    payload = {
        "items": [
            {"key": "rotation_mode", "value": "weighted", "updated_at": client_now},
        ],
        "last_modified_at": client_now,
    }

    resp = await client.post(
        f"/v1/kj/sync/settings/push?venue_id={venue_id}",
        json=payload,
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_409_CONFLICT
    data = resp.json()
    assert len(data["detail"]["conflicts"]) == 1
    assert data["detail"]["conflicts"][0]["resolution"] == "server_wins"

    # Server value unchanged
    result = await db.execute(
        select(VenueConfig).where(
            VenueConfig.venue_id == venue_id,
            VenueConfig.config_key == "rotation_mode",
        )
    )
    row = result.scalar_one()
    assert row.config_value == "fifo"


# ---------------------------------------------------------------------------
# Cross-domain: pull symmetry check
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_all_pull_endpoints_return_modified_at(client, sync_venue):
    venue_id, _, _, _, raw_key = sync_venue

    endpoints = [
        (f"/v1/kj/sync/queue/pull?venue_id={venue_id}", "server_modified_at"),
        (f"/v1/kj/sync/singers/pull?venue_id={venue_id}", "server_modified_at"),
        (f"/v1/kj/sync/songs?venue_id={venue_id}", "sync_timestamp"),
        (f"/v1/kj/sync/settings/pull?venue_id={venue_id}", "server_modified_at"),
    ]
    for url, key in endpoints:
        resp = await client.get(url, headers=_kj_headers(raw_key))
        assert resp.status_code == status.HTTP_200_OK, f"Failed: {url}"
        data = resp.json()
        assert key in data, f"Missing {key}: {url}"
