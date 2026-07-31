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
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Venue, Song, Singer, QueueRequest, VenueConfig, AnalyticsEvent, KJDevice, Account
from app.core.security import hash_password, create_access_token

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
        f"{SYNC_BASE}/queue/pull?venue_id={venue_id}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["server_modified_at"] is not None


@pytest.mark.anyio
async def test_queue_pull_excludes_soft_deleted(client, sync_queue, db):
    """Soft-deleted requests should not be re-sent to the KJ desktop."""
    venue_id, _, _, _, raw_key, items = sync_queue
    deleted_item = items[0]
    deleted_item.deleted_at = "2026-05-21T10:02:00Z"
    deleted_item.updated_at = "2026-05-21T10:02:00Z"
    await db.commit()

    resp = await client.get(
        f"{SYNC_BASE}/queue/pull?venue_id={venue_id}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["request_id"] != str(deleted_item.id)


@pytest.mark.anyio
async def test_queue_ack_soft_deletes(client, sync_queue, db):
    """KJ desktop can dismiss/ack a request so it is removed from future pulls."""
    venue_id, _, _, _, raw_key, items = sync_queue
    target_id = str(items[0].id)

    resp = await client.post(
        f"{SYNC_BASE}/queue/{target_id}/ack?venue_id={venue_id}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    # Verify the request is soft-deleted in the DB
    row = (await db.execute(
        select(QueueRequest).where(QueueRequest.id == target_id)
    )).scalar_one()
    assert row.deleted_at is not None

    resp = await client.get(
        f"{SYNC_BASE}/queue/pull?venue_id={venue_id}",
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["request_id"] != target_id


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
# Singer merge
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_kj_merge_local_singer_into_mobile(client, sync_venue, db):
    venue_id, _, _, _, raw_key = sync_venue

    # Create mobile-linked account + singer
    account = Account(
        id=str(uuid.uuid4()),
        email="merge-mobile@example.com",
        password_hash=hash_password("x"),
        stage_name="Mobile Star",
    )
    mobile = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        account_id=account.id,
        stage_name="Mobile Star",
    )
    local = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Old Local",
    )
    song = Song(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        title="Merge Song",
        artist="Artist",
        file_path="/merge.mp3",
    )
    db.add_all([account, mobile, local, song])
    await db.commit()

    qr = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=local.id,
        song_id=song.id,
        status="completed",
        requested_at="2026-07-14T10:00:00Z",
    )
    db.add(qr)
    await db.commit()

    resp = await client.post(
        f"{SYNC_BASE}/singers/{local.id}/link?venue_id={venue_id}",
        json={"target_singer_id": mobile.id},
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["local_singer_id"] == local.id
    assert data["target_singer_id"] == mobile.id
    assert data["merged_records"]["queue_requests"] == 1

    row = await db.get(QueueRequest, qr.id)
    assert row.singer_id == mobile.id


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

async def test_account_me_history_resolves_to_venue_singer(client, sync_venue, db):
    venue_id, kj_id, _, songs, raw_key = sync_venue

    account = Account(
        id="account-1",
        email="mobile@example.com",
        password_hash=hash_password("x"),
        stage_name="Mobile Star",
    )
    singer = Singer(
        id="venue-singer-1",
        venue_id=venue_id,
        account_id=account.id,
        stage_name="Mobile Star",
    )
    qr = QueueRequest(
        id="qr-account-1",
        venue_id=venue_id,
        singer_id=singer.id,
        song_id=songs[0].id,
        status="completed",
        requested_at="2026-07-14T14:00:00Z",
        played_at="2026-07-14T14:06:00Z",
    )
    db.add_all([account, singer, qr])
    await db.commit()

    token = create_access_token(
        subject=account.id,
        extra_claims={"role": "account"},
        expires_delta=timedelta(hours=1),
    )

    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/queue/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["song_title"] == "Song A"


async def test_admin_get_singer_history(client, sync_venue, db):
    venue_id, kj_id, _, songs, raw_key = sync_venue

    # Create a regular singer with completed queue requests
    singer = Singer(
        id="target-singer-1",
        venue_id=venue_id,
        stage_name="Target",
        role="singer",
    )
    qr = QueueRequest(
        id="qr-1",
        venue_id=venue_id,
        singer_id="target-singer-1",
        song_id=songs[0].id,
        status="completed",
        requested_at="2026-07-14T14:00:00Z",
        played_at="2026-07-14T14:06:00Z",
    )
    db.add_all([singer, qr])
    await db.commit()

    # KJ fetches history for the singer
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/target-singer-1/history",
        headers={"x-api-key": raw_key},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["song_title"] == "Song A"


async def test_push_queue_stub_singer_avoids_duplicate_stage_name(client, sync_venue, db):
    """Auto-created stub singers must not collide on (venue_id, stage_name)."""
    venue_id, _, _, _, raw_key = sync_venue
    # Pre-seed a singer with the colliding stage name
    existing = Singer(
        id="existing-singer",
        venue_id=venue_id,
        stage_name="Test User 6",
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )
    db.add(existing)
    await db.commit()

    payload = {
        "items": [
            {
                "request_id": "req-10",
                "singer_id": "10",
                "song_id": None,
                "song_title": "Song",
                "song_artist": "Artist",
                "status": "pending",
                "position": 1,
                "notes": "Test User 6",
                "requested_at": "2026-07-15T00:35:21Z",
            }
        ],
        "deleted_ids": [],
    }
    resp = await client.post("/v1/kj/sync/queue/push", json=payload, headers={"x-api-key": raw_key})
    assert resp.status_code == 200, resp.text

    # The new stub should have a suffix, preserving its ID
    stub = await db.get(Singer, "10")
    assert stub is not None
    assert stub.stage_name == "Test User 6 (2)"


async def test_kj_merge_local_singer_by_details(client, db):
    """Merging a local-only singer that has not been pushed to cloud yet."""
    venue = Venue(name="Merge By Details", slug="merge-by-details")
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    kj = KJDevice(venue_id=venue.id, name="KJ", api_key_hash=hash_password("kj-merge-2"))
    db.add(kj)
    await db.commit()
    await db.refresh(kj)

    acc = Account(email="target2@example.com", password_hash="x", stage_name="Target Star", first_name="T", last_name="S")
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    target = Singer(venue_id=venue.id, account_id=acc.id, stage_name="Target Star", email="target2@example.com")
    db.add(target)
    await db.commit()
    await db.refresh(target)

    # No source singer exists yet in the cloud.
    resp = await client.post(
        "/v1/kj/sync/singers/merge",
        json={
            "local_name": "Local Newbie",
            "local_email": "newbie@example.com",
            "target_singer_id": str(target.id),
        },
        headers={"x-api-key": "kj-merge-2"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["target_singer_id"] == str(target.id)
    assert data["merged_records"]["queue_requests"] == 0

    # Source was created and soft-deleted.
    source_result = await db.execute(select(Singer).where(Singer.id == data["local_singer_id"]))
    source = source_result.scalar_one_or_none()
    assert source is not None
    assert source.deleted_at is not None

async def test_kj_merge_by_details_creates_stub_when_registered_name_matches(client, db):
    """A local-only name matching a registered singer must not use that registered row as source."""
    venue = Venue(name="Merge Stub Venue", slug="merge-stub-venue")
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    kj = KJDevice(venue_id=venue.id, name="KJ", api_key_hash=hash_password("kj-merge-3"))
    db.add(kj)
    await db.commit()
    await db.refresh(kj)

    acc = Account(email="existing@example.com", password_hash="x", stage_name="Same Name", first_name="S", last_name="N")
    db.add(acc)
    await db.commit()
    await db.refresh(acc)
    target = Singer(venue_id=venue.id, account_id=acc.id, stage_name="Same Name", email="existing@example.com")
    db.add(target)
    await db.commit()
    await db.refresh(target)

    resp = await client.post(
        "/v1/kj/sync/singers/merge",
        json={
            "local_name": "Same Name",
            "local_email": "existing@example.com",
            "target_singer_id": str(target.id),
        },
        headers={"x-api-key": "kj-merge-3"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["target_singer_id"] == str(target.id)
    source_result = await db.execute(select(Singer).where(Singer.id == data["local_singer_id"]))
    source = source_result.scalar_one_or_none()
    assert source is not None
    assert source.deleted_at is not None
    assert source.account_id is None or source.account_id == ""

@pytest.mark.asyncio
async def test_queue_push_rejected_sets_reason_and_status(client, db, sync_venue, venue_with_songs):
    """KJ desktop can push a rejection for an existing queue request."""
    from datetime import datetime, timezone
    venue_id, songs = venue_with_songs
    from app.models import KJDevice
    from app.core.security import hash_password
    device = KJDevice(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Test KJ",
        api_key_hash=hash_password("kj-reject-test"),
    )
    db.add(device)
    from app.models import Singer
    singer = Singer(venue_id=venue_id, stage_name="Reject Me", email="reject@example.com")
    db.add(singer)
    await db.commit()
    await db.refresh(singer)
    song = songs[0]
    req_id = str(uuid.uuid4())
    q = QueueRequest(
        id=req_id,
        venue_id=venue_id,
        singer_id=str(singer.id),
        song_id=str(song.id),
        status="pending",
        rotation_position=1,
        requested_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(q)
    await db.commit()

    resp = await client.post(
        "/v1/kj/sync/queue/push",
        json={
            "items": [
                {
                    "request_id": req_id,
                    "singer_id": str(singer.id),
                    "status": "rejected",
                    "reject_reason": "This song is already in the queue for this singer",
                }
            ],
            "deleted_ids": [],
        },
        headers={"x-api-key": "kj-reject-test"},
    )
    assert resp.status_code == 200, resp.text
    await db.refresh(q)
    assert q.status == "rejected"
    assert q.reject_reason == "This song is already in the queue for this singer"


@pytest.mark.asyncio
async def test_remove_singer_from_rotation_creates_removal_record(client, db, sync_venue, venue_with_songs):
    """POST /v1/kj/sync/queue/singers/{id}/remove cancels requests and records removal."""
    from datetime import datetime, timezone
    from app.models import SingerRemoval
    venue_id, songs = venue_with_songs
    from app.models import KJDevice
    from app.core.security import hash_password
    device = KJDevice(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Test KJ",
        api_key_hash=hash_password("kj-remove-test"),
    )
    db.add(device)
    from app.models import Singer
    singer = Singer(venue_id=venue_id, stage_name="Remove Me", email="remove@example.com")
    db.add(singer)
    await db.commit()
    await db.refresh(singer)
    song = songs[0]
    q = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=str(singer.id),
        song_id=str(song.id),
        status="pending",
        rotation_position=1,
        requested_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(q)
    await db.commit()

    # KJ device x-api-key auth
    resp = await client.post(
        f"/v1/kj/sync/queue/singers/{singer.id}/remove?venue_id={venue_id}",
        headers={"x-api-key": "kj-remove-test"},
    )
    assert resp.status_code == 204, resp.text

    # Request should be rejected
    await db.refresh(q)
    assert q.status == "rejected"

    # Removal record should exist and appear in pull
    removal = await db.execute(select(SingerRemoval).where(SingerRemoval.singer_id == str(singer.id)))
    assert removal.scalar_one_or_none() is not None

    pull = await client.get(
        f"/v1/kj/sync/queue/pull?venue_id={venue_id}",
        headers={"x-api-key": "kj-remove-test"},
    )
    assert pull.status_code == 200
    data = pull.json()
    assert str(singer.id) in data.get("removed_singer_ids", [])


@pytest.mark.asyncio
async def test_pull_queue_includes_song_title_artist(client, db, sync_venue, venue_with_songs):
    """Regression: GET /v1/kj/sync/queue/pull should include song title/artist and singer_name."""
    from datetime import datetime, timezone
    venue_id, songs = venue_with_songs
    raw_key = "kj-pull-test"
    from app.models import KJDevice
    from app.core.security import hash_password
    device = KJDevice(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Test KJ",
        api_key_hash=hash_password(raw_key),
    )
    db.add(device)
    # Create a singer for this venue
    from app.models import Singer
    singer = Singer(venue_id=venue_id, stage_name="Test Stage", email="test@example.com")
    db.add(singer)
    await db.commit()
    await db.refresh(singer)
    song = songs[0]
    q = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=str(singer.id),
        song_id=str(song.id),
        status="pending",
        rotation_position=1,
        requested_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add(q)
    await db.commit()

    resp = await client.get(
        f"/v1/kj/sync/queue/pull?venue_id={venue_id}",
        headers={"x-api-key": raw_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["song_id"] == str(song.id)
    assert item["song_title"] == song.title
    assert item["song_artist"] == song.artist
    assert item["singer_name"] == singer.stage_name



# ---------------------------------------------------------------------------
# Queue pull source separation
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_pull_queue_requests_excludes_host_source(client, sync_venue, db):
    venue_id, _, _, _, raw_key = sync_venue
    # Seed two rows: one mobile (should be pulled) and one host (should not).
    mobile = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=str(uuid.uuid4()),
        song_id=str(uuid.uuid4()),
        status="pending",
        source="mobile",
        rotation_position=1,
        requested_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    host = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=str(uuid.uuid4()),
        song_id=str(uuid.uuid4()),
        status="approved",
        source="host",
        rotation_position=2,
        requested_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    db.add_all([mobile, host])
    await db.commit()

    resp = await client.get(
        f"/v1/kj/sync/queue/pull?venue_id={venue_id}",
        headers={"x-api-key": raw_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    pulled_ids = {it["request_id"] for it in data["items"]}
    assert str(mobile.id) in pulled_ids
    assert str(host.id) not in pulled_ids
