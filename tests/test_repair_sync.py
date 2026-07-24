"""Full repair sync endpoint tests.

Covers:
- Auth: missing token, invalid token, wrong venue, singer role forbidden
- client_wins mode: push singers, queue, settings, now-playing in one call
- prompt mode: conflict detection returns needs_resolution
- resolve endpoint: apply client/server/merge resolutions
- idempotency: same X-Idempotency-Key returns same sync_id
- cancel endpoint
- Server-managed singer fields (loyalty/tier/account) are preserved
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import KJDevice, QueueRequest, Singer, Song, Venue, VenueConfig
from app.services import repair_sync as service

REPAIR_BASE = "/v1/kj/sync/repair"


def _kj_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key}


def _owner_token(venue_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "venue_id": venue_id,
        "role": "owner",
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


@pytest.fixture
async def repair_venue(db: AsyncSession):
    """Venue + 2 songs + 1 singer + 1 KJ device."""
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="Repair Venue", slug=f"repair-venue-{venue_id[:8]}")
    db.add(venue)
    await db.commit()

    songs = [
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Repair Song A", artist="A", is_available=1),
        Song(id=str(uuid.uuid4()), venue_id=venue_id, title="Repair Song B", artist="B", is_available=1),
    ]
    for s in songs:
        db.add(s)

    singer_id = str(uuid.uuid4())
    singer = Singer(
        id=singer_id,
        venue_id=venue_id,
        stage_name="Repair Singer",
        role="singer",
        email="repair@example.com",
    )
    db.add(singer)

    raw_key = f"repair-api-key-{venue_id[:8]}"
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
    await db.refresh(singer)
    await db.refresh(device)

    # Clear in-memory repair sync store for isolation
    service._jobs.clear()
    service._idempotency_map.clear()

    return venue_id, singer_id, songs, raw_key


def _make_snapshot(venue_id: str, singer_id: str, song_id: str, now: str) -> dict:
    return {
        "singers": {
            "items": [
                {
                    "id": singer_id,
                    "stage_name": "Repair Singer Updated",
                    "real_name": "Real Name",
                    "pronouns": "they/them",
                    "email": "new@example.com",
                    "phone": "555-1234",
                    "total_points": 9999,
                    "loyalty_tier_id": "client-tier",
                    "account_id": "client-account",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": now,
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        },
        "queue": {
            "items": [
                {
                    "request_id": str(uuid.uuid4()),
                    "singer_id": singer_id,
                    "song_id": song_id,
                    "status": "pending",
                    "position": 1,
                    "requested_at": now,
                    "updated_at": now,
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        },
        "settings": {
            "items": [
                {"key": "rotation_mode", "value": "weighted", "updated_at": now},
                {"key": "repair_flag", "value": "true", "updated_at": now},
            ],
            "last_modified_at": "2026-01-01T00:00:00Z",
        },
        "now_playing": {
            "singer_id": singer_id,
            "song_id": song_id,
            "song_title": "Repair Song A",
            "song_artist": "A",
            "singer_name": "Repair Singer Updated",
            "is_dj_track": False,
            "started_at": now,
        },
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_repair_sync_no_auth(client, repair_venue):
    venue_id, *_ = repair_venue
    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": {}},
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_repair_sync_wrong_venue(client, repair_venue):
    venue_id, *_, raw_key = repair_venue
    other = str(uuid.uuid4())
    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": other, "mode": "client_wins", "snapshot": {}},
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_repair_sync_singer_forbidden(client, repair_venue, jwt_encode):
    venue_id, singer_id, *_ = repair_venue
    token = jwt_encode(venue_id, role="singer", user_id=singer_id)
    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_repair_sync_owner_token(client, repair_venue):
    venue_id, *_ = repair_venue
    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": {}},
        headers={"Authorization": f"Bearer {_owner_token(venue_id)}"},
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED


# ---------------------------------------------------------------------------
# client_wins mode
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_repair_sync_client_wins(client, repair_venue, db):
    venue_id, singer_id, songs, raw_key = repair_venue
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = _make_snapshot(venue_id, singer_id, str(songs[0].id), now)

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    data = resp.json()
    assert data["status"] == "completed"
    assert data["mode"] == "client_wins"
    assert data["summary"]["singers_synced"] == 1
    assert data["summary"]["queue_synced"] == 1
    assert data["summary"]["settings_synced"] == 2
    assert data["summary"]["now_playing_synced"] is True
    assert data["conflicts"] is None

    # Singer editable fields updated; server-managed fields preserved.
    row = await db.get(Singer, singer_id)
    assert row.stage_name == "Repair Singer Updated"
    assert row.pronouns == "they/them"
    assert row.total_points == 0
    assert row.loyalty_tier_id is None or row.loyalty_tier_id == ""
    assert row.account_id is None or row.account_id == ""

    # Queue item created
    queue_rows = (await db.execute(select(QueueRequest).where(QueueRequest.venue_id == venue_id))).scalars().all()
    assert len(queue_rows) == 1
    assert queue_rows[0].status == "now_playing"  # now_playing logic created/updated a now_playing item

    # Settings created
    cfg_rows = (await db.execute(select(VenueConfig).where(VenueConfig.venue_id == venue_id))).scalars().all()
    cfg_by_key = {r.config_key: r.config_value for r in cfg_rows}
    assert cfg_by_key.get("rotation_mode") == "weighted"
    assert cfg_by_key.get("repair_flag") == "true"


@pytest.mark.anyio
async def test_repair_sync_idempotency(client, repair_venue):
    venue_id, singer_id, songs, raw_key = repair_venue
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = _make_snapshot(venue_id, singer_id, str(songs[0].id), now)
    idempotency = str(uuid.uuid4())

    resp1 = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers={**_kj_headers(raw_key), "X-Idempotency-Key": idempotency},
    )
    assert resp1.status_code == status.HTTP_202_ACCEPTED
    sync_id_1 = resp1.json()["sync_id"]

    # Second call with same key returns same sync_id.
    resp2 = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers={**_kj_headers(raw_key), "X-Idempotency-Key": idempotency},
    )
    assert resp2.status_code == status.HTTP_202_ACCEPTED
    assert resp2.json()["sync_id"] == sync_id_1


@pytest.mark.anyio
async def test_repair_sync_get_status(client, repair_venue):
    venue_id, singer_id, songs, raw_key = repair_venue
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snapshot = _make_snapshot(venue_id, singer_id, str(songs[0].id), now)

    start = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    sync_id = start.json()["sync_id"]

    status_resp = await client.get(
        f"{REPAIR_BASE}/{sync_id}",
        headers=_kj_headers(raw_key),
    )
    assert status_resp.status_code == status.HTTP_200_OK
    data = status_resp.json()
    assert data["sync_id"] == sync_id
    assert data["status"] == "completed"
    assert data["progress"]["total_steps"] == 6


@pytest.mark.anyio
async def test_repair_sync_cancel(client, repair_venue, db):
    venue_id, singer_id, *_ = repair_venue
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = await db.get(Singer, singer_id)
    row.stage_name = "Server Stage"
    row.updated_at = server_now
    await db.commit()

    snapshot = {
        "singers": {
            "items": [
                {
                    "id": singer_id,
                    "stage_name": "Client Stage",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(repair_venue[3]),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert resp.json()["status"] == "needs_resolution"
    sync_id = resp.json()["sync_id"]

    cancel = await client.delete(
        f"{REPAIR_BASE}/{sync_id}",
        headers=_kj_headers(repair_venue[3]),
    )
    assert cancel.status_code == status.HTTP_202_ACCEPTED
    assert cancel.json()["status"] == "cancelled"

    # Re-cancelling a terminal job returns current state (best-effort).
    again = await client.delete(
        f"{REPAIR_BASE}/{sync_id}",
        headers=_kj_headers(repair_venue[3]),
    )
    assert again.status_code == status.HTTP_202_ACCEPTED
    assert again.json()["status"] == "cancelled"


# ---------------------------------------------------------------------------
# prompt mode + conflicts
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_repair_sync_prompt_detects_singer_conflict(client, repair_venue, db):
    venue_id, singer_id, songs, raw_key = repair_venue

    # Server updates singer after client's last_modified_at.
    row = await db.get(Singer, singer_id)
    row.stage_name = "Server Stage"
    row.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await db.commit()

    now = "2026-01-01T00:00:00Z"
    snapshot = {
        "singers": {
            "items": [
                {
                    "id": singer_id,
                    "stage_name": "Client Stage",
                    "real_name": "",
                    "pronouns": None,
                    "email": None,
                    "phone": None,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": now,
                }
            ],
            "deleted_ids": [],
            "last_modified_at": now,
        }
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    data = resp.json()
    assert data["status"] == "needs_resolution"
    assert len(data["conflicts"]) == 1
    conflict = data["conflicts"][0]
    assert conflict["entity_type"] == "singers"
    assert conflict["entity_id"] == singer_id
    assert conflict["resolution"] == "server_wins"
    assert "total_points" in conflict["locked_fields"]
    assert "stage_name" in conflict["mergeable_fields"]

    # DB should remain unchanged because prompt mode does not apply until resolved.
    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Server Stage"


@pytest.mark.anyio
async def test_repair_sync_prompt_detects_queue_conflict(client, repair_venue, db):
    venue_id, singer_id, songs, raw_key = repair_venue

    req_id = str(uuid.uuid4())
    q = QueueRequest(
        id=req_id,
        venue_id=venue_id,
        singer_id=singer_id,
        song_id=songs[0].id,
        status="pending",
        rotation_position=1,
        requested_at="2026-01-01T00:00:00Z",
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.add(q)
    await db.commit()

    snapshot = {
        "queue": {
            "items": [
                {
                    "request_id": req_id,
                    "singer_id": singer_id,
                    "song_id": str(songs[0].id),
                    "status": "completed",
                    "position": 1,
                    "requested_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2025-01-01T00:00:00Z",
        }
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    data = resp.json()
    assert data["status"] == "needs_resolution"
    assert data["conflicts"][0]["entity_type"] == "queue"


@pytest.mark.anyio
async def test_repair_sync_prompt_detects_settings_conflict(client, repair_venue, db):
    venue_id, *_ = repair_venue
    cfg = VenueConfig(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        config_key="rotation_mode",
        config_value="fifo",
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    db.add(cfg)
    await db.commit()

    snapshot = {
        "settings": {
            "items": [
                {"key": "rotation_mode", "value": "weighted", "updated_at": "2026-01-01T00:00:00Z"}
            ],
            "last_modified_at": "2025-01-01T00:00:00Z",
        }
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(repair_venue[3]),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    data = resp.json()
    assert data["status"] == "needs_resolution"
    assert data["conflicts"][0]["entity_type"] == "settings"


@pytest.mark.anyio
async def test_repair_sync_resolve_client_wins(client, repair_venue, db):
    venue_id, singer_id, *_ = repair_venue
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = await db.get(Singer, singer_id)
    row.stage_name = "Server Stage"
    row.updated_at = server_now
    await db.commit()

    snapshot = {
        "singers": {
            "items": [
                {
                    "id": singer_id,
                    "stage_name": "Client Stage",
                    "real_name": "",
                    "pronouns": None,
                    "email": None,
                    "phone": None,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    start = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(repair_venue[3]),
    )
    sync_id = start.json()["sync_id"]
    conflict = start.json()["conflicts"][0]

    resolve = await client.post(
        f"{REPAIR_BASE}/{sync_id}/resolve",
        json={
            "resolutions": [
                {
                    "entity_type": "singers",
                    "entity_id": singer_id,
                    "resolution": "client_wins",
                    "server_state": conflict["server_state"],
                    "client_state": conflict["client_state"],
                    "changed_fields": conflict["changed_fields"],
                    "display_label": conflict["display_label"],
                    "locked_fields": conflict["locked_fields"],
                    "mergeable_fields": conflict["mergeable_fields"],
                }
            ]
        },
        headers=_kj_headers(repair_venue[3]),
    )
    assert resolve.status_code == status.HTTP_200_OK
    data = resolve.json()
    assert data["status"] == "completed"
    assert data["summary"]["conflicts_resolved"] == 1

    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Client Stage"


@pytest.mark.anyio
async def test_repair_sync_resolve_merge(client, repair_venue, db):
    venue_id, singer_id, *_ = repair_venue
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = await db.get(Singer, singer_id)
    row.stage_name = "Server Stage"
    row.pronouns = "she/her"
    row.updated_at = server_now
    await db.commit()

    snapshot = {
        "singers": {
            "items": [
                {
                    "id": singer_id,
                    "stage_name": "Client Stage",
                    "real_name": "",
                    "pronouns": "they/them",
                    "email": None,
                    "phone": None,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    start = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(repair_venue[3]),
    )
    sync_id = start.json()["sync_id"]
    conflict = start.json()["conflicts"][0]

    resolve = await client.post(
        f"{REPAIR_BASE}/{sync_id}/resolve",
        json={
            "resolutions": [
                {
                    "entity_type": "singers",
                    "entity_id": singer_id,
                    "resolution": "merge",
                    "server_state": conflict["server_state"],
                    "client_state": {**conflict["client_state"], "stage_name": "client", "pronouns": "server"},
                    "changed_fields": conflict["changed_fields"],
                    "display_label": conflict["display_label"],
                    "locked_fields": conflict["locked_fields"],
                    "mergeable_fields": conflict["mergeable_fields"],
                }
            ]
        },
        headers=_kj_headers(repair_venue[3]),
    )
    assert resolve.status_code == status.HTTP_200_OK
    data = resolve.json()
    assert data["status"] == "completed"

    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Client Stage"
    assert row_after.pronouns == "she/her"


@pytest.mark.anyio
async def test_repair_sync_resolve_missing_conflict_422(client, repair_venue, db):
    venue_id, singer_id, *_ = repair_venue
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = await db.get(Singer, singer_id)
    row.stage_name = "Server Stage"
    row.updated_at = server_now
    await db.commit()

    snapshot = {
        "singers": {
            "items": [
                {
                    "id": singer_id,
                    "stage_name": "Client Stage",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    start = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(repair_venue[3]),
    )
    sync_id = start.json()["sync_id"]

    resolve = await client.post(
        f"{REPAIR_BASE}/{sync_id}/resolve",
        json={"resolutions": []},
        headers=_kj_headers(repair_venue[3]),
    )
    assert resolve.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Unresolved conflicts" in resolve.json()["detail"]["detail"]


@pytest.mark.anyio
async def test_repair_sync_client_wins_with_conflict_overwrites(client, repair_venue, db):
    venue_id, singer_id, *_ = repair_venue
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = await db.get(Singer, singer_id)
    row.stage_name = "Server Stage"
    row.updated_at = server_now
    await db.commit()

    snapshot = {
        "singers": {
            "items": [
                {
                    "id": singer_id,
                    "stage_name": "Client Stage",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers=_kj_headers(repair_venue[3]),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    data = resp.json()
    assert data["status"] == "completed"
    assert data["summary"]["conflicts_resolved"] == 1

    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Client Stage"


@pytest.mark.anyio
async def test_repair_sync_queue_creates_stub_singer(client, repair_venue, db):
    venue_id, _, songs, raw_key = repair_venue
    unknown_singer_id = str(uuid.uuid4())

    snapshot = {
        "queue": {
            "items": [
                {
                    "request_id": str(uuid.uuid4()),
                    "singer_id": unknown_singer_id,
                    "song_id": str(songs[0].id),
                    "status": "pending",
                    "position": 1,
                    "requested_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "notes": "Stub Stage",
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert resp.json()["summary"]["queue_synced"] == 1

    stub = await db.get(Singer, unknown_singer_id)
    assert stub is not None
    assert stub.venue_id == venue_id
    assert stub.stage_name == "Stub Stage"



@pytest.mark.anyio
async def test_repair_sync_resolve_server_wins(client, repair_venue, db):
    venue_id, singer_id, *_ = repair_venue
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = await db.get(Singer, singer_id)
    row.stage_name = "Server Stage"
    row.pronouns = "she/her"
    row.updated_at = server_now
    await db.commit()

    snapshot = {
        "singers": {
            "items": [
                {
                    "id": singer_id,
                    "stage_name": "Client Stage",
                    "pronouns": "they/them",
                    "real_name": "",
                    "email": None,
                    "phone": None,
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    start = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(repair_venue[3]),
    )
    sync_id = start.json()["sync_id"]
    conflict = start.json()["conflicts"][0]

    resolve = await client.post(
        f"{REPAIR_BASE}/{sync_id}/resolve",
        json={
            "resolutions": [
                {
                    "entity_type": "singers",
                    "entity_id": singer_id,
                    "resolution": "server_wins",
                    "server_state": conflict["server_state"],
                    "client_state": conflict["client_state"],
                    "changed_fields": conflict["changed_fields"],
                    "display_label": conflict["display_label"],
                    "locked_fields": conflict["locked_fields"],
                    "mergeable_fields": conflict["mergeable_fields"],
                }
            ]
        },
        headers=_kj_headers(repair_venue[3]),
    )
    assert resolve.status_code == status.HTTP_200_OK
    assert resolve.json()["status"] == "completed"

    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Server Stage"
    assert row_after.pronouns == "she/her"


@pytest.mark.anyio
async def test_repair_sync_prompt_no_conflict_completes(client, repair_venue):
    venue_id, _, songs, raw_key = repair_venue
    snapshot = {
        "settings": {
            "items": [
                {"key": "rotation_mode", "value": "fifo", "updated_at": "2026-01-01T00:00:00Z"}
            ],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    data = resp.json()
    assert data["status"] == "completed"
    assert data["summary"]["settings_synced"] == 1
    assert data["conflicts"] is None
