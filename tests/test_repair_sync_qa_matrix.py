"""QA test matrix for full repair sync.

Extends the existing tests/test_repair_sync.py suite to cover drift from
merges, restores, and offline operation, plus conflict reconciliation,
NOT NULL rotation handling, progress/error UX, and rollback/cleanup.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import QueueRequest, Singer, VenueConfig
from app.services import repair_sync as service


REPAIR_BASE = "/v1/kj/sync/repair"


def _kj_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key}


@pytest.fixture
async def repair_venue_cleared(db):
    # Local copy of repair_venue fixture with in-memory store cleared.
    venue_id = str(uuid.uuid4())
    from app.core.security import hash_password
    from app.models import KJDevice, Singer, Song, Venue

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

    service._jobs.clear()
    service._idempotency_map.clear()
    return venue_id, singer_id, songs, raw_key


def _singer_item(
    singer_id: str,
    stage_name: str = "Client Stage",
    last_modified_at: str = "2026-01-01T00:00:00Z",
    updated_at: str = "2026-01-01T00:00:00Z",
) -> dict:
    return {
        "id": singer_id,
        "stage_name": stage_name,
        "real_name": "",
        "first_name": "",
        "last_name": "",
        "pronouns": None,
        "email": None,
        "phone": None,
        "notes": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": updated_at,
    }


# -----------------------------------------------------------------------------
# Drift from merges, restores, and offline operation
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_repair_sync_merge_restores_deleted_singer(client, repair_venue_cleared, db):
    """After a merge/restore, a singer client thinks is deleted can be pushed back."""
    venue_id, singer_id, songs, raw_key = repair_venue_cleared

    # Server has the singer deactivated (merged/soft-deleted) after client's last_modified_at.
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = await db.get(Singer, singer_id)
    row.deactivated_at = server_now
    row.updated_at = server_now
    await db.commit()

    snapshot = {
        "singers": {
            "items": [_singer_item(singer_id, stage_name="Client Stage")],
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
    data = resp.json()
    assert data["status"] == "completed"

    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Client Stage"


@pytest.mark.anyio
async def test_repair_sync_offline_queue_reconcile(client, repair_venue_cleared, db):
    """Client comes back online with queue state older than server; prompt mode detects conflict."""
    venue_id, singer_id, songs, raw_key = repair_venue_cleared
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    req_id = str(uuid.uuid4())
    q = QueueRequest(
        id=req_id,
        venue_id=venue_id,
        singer_id=singer_id,
        song_id=songs[0].id,
        status="pending",
        rotation_position=1,
        requested_at="2026-01-01T00:00:00Z",
        updated_at=server_now,
    )
    db.add(q)
    await db.commit()

    snapshot = {
        "queue": {
            "items": [
                {
                    "request_id": req_id,
                    "singer_id": singer_id,
                    "singer_name": "Repair Singer",
                    "song_id": str(songs[0].id),
                    "song_title": "Repair Song A",
                    "song_artist": "A",
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
    assert len(data["conflicts"]) == 1
    assert data["conflicts"][0]["entity_type"] == "queue"

    # Resolve server_wins so the server state is untouched.
    conflict = data["conflicts"][0]
    resolve = await client.post(
        f"{REPAIR_BASE}/{data['sync_id']}/resolve",
        json={
            "resolutions": [
                {
                    "entity_type": "queue",
                    "entity_id": req_id,
                    "resolution": "server_wins",
                    "server_state": conflict["server_state"],
                    "client_state": conflict["client_state"],
                    "changed_fields": conflict["changed_fields"],
                    "display_label": conflict["display_label"],
                }
            ]
        },
        headers=_kj_headers(raw_key),
    )
    assert resolve.status_code == status.HTTP_200_OK
    row_after = await db.get(QueueRequest, req_id)
    assert row_after.status == "pending"


@pytest.mark.anyio
async def test_repair_sync_push_all_local_state(client, repair_venue_cleared, db):
    """A full snapshot with new singers, queue, settings, and now_playing applies cleanly."""
    venue_id, _, songs, raw_key = repair_venue_cleared
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_singer_id = str(uuid.uuid4())
    new_request_id = str(uuid.uuid4())

    snapshot = {
        "singers": {
            "items": [
                {
                    "id": new_singer_id,
                    "stage_name": "New Singer",
                    "real_name": "",
                    "first_name": "",
                    "last_name": "",
                    "pronouns": None,
                    "email": None,
                    "phone": None,
                    "notes": None,
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
                    "request_id": new_request_id,
                    "singer_id": new_singer_id,
                    "singer_name": "New Singer",
                    "song_id": str(songs[0].id),
                    "song_title": "Repair Song A",
                    "song_artist": "A",
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
                {"key": "rotation_mode", "value": "fifo", "updated_at": now},
                {"key": "repair_test", "value": "yes", "updated_at": now},
            ],
            "last_modified_at": "2026-01-01T00:00:00Z",
        },
        "now_playing": {
            "singer_id": new_singer_id,
            "song_id": str(songs[0].id),
            "song_title": "Repair Song A",
            "song_artist": "A",
            "singer_name": "New Singer",
            "is_dj_track": False,
            "started_at": now,
        },
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    data = resp.json()
    assert data["status"] == "completed"
    assert data["summary"]["singers_synced"] == 1
    assert data["summary"]["queue_synced"] == 1
    assert data["summary"]["settings_synced"] == 2
    assert data["summary"]["now_playing_synced"] is True

    singer_rows = (await db.execute(select(Singer).where(Singer.venue_id == venue_id))).scalars().all()
    assert any(s.id == new_singer_id for s in singer_rows)

    cfg = (
        await db.execute(
            select(VenueConfig).where(
                VenueConfig.venue_id == venue_id, VenueConfig.config_key == "repair_test"
            )
        )
    ).scalar_one_or_none()
    assert cfg is not None
    assert cfg.config_value == "yes"


@pytest.mark.anyio
async def test_repair_sync_pull_and_reconcile(client, repair_venue_cleared, db):
    """After applying client_wins, GETing the job returns reconciled server_modified_at."""
    venue_id, singer_id, _, raw_key = repair_venue_cleared
    snapshot = {
        "singers": {
            "items": [_singer_item(singer_id, stage_name="Pulled Stage")],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    resp = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    sync_id = resp.json()["sync_id"]

    status_resp = await client.get(
        f"{REPAIR_BASE}/{sync_id}",
        headers=_kj_headers(raw_key),
    )
    data = status_resp.json()
    assert data["status"] == "completed"
    assert data["summary"]["server_modified_at"] is not None

    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Pulled Stage"


# -----------------------------------------------------------------------------
# NOT NULL rotation handling
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_repair_sync_queue_not_null_rotation(client, repair_venue_cleared, db):
    """Queue items without rotation_position still get a position assigned."""
    venue_id, _, songs, raw_key = repair_venue_cleared
    unknown_singer_id = str(uuid.uuid4())
    req_id = str(uuid.uuid4())

    snapshot = {
        "queue": {
            "items": [
                {
                    "request_id": req_id,
                    "singer_id": unknown_singer_id,
                    "singer_name": "No Rot Singer",
                    "song_id": str(songs[0].id),
                    "song_title": "Repair Song A",
                    "song_artist": "A",
                    "status": "pending",
                    "position": 0,
                    "requested_at": "2026-01-01T00:00:00Z",
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
        headers=_kj_headers(raw_key),
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED
    assert resp.json()["status"] == "completed"

    row = await db.get(QueueRequest, req_id)
    assert row is not None
    assert row.rotation_position is not None


# -----------------------------------------------------------------------------
# Settings per-field merge
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_repair_sync_prompt_merge_settings_per_field(client, repair_venue_cleared, db):
    """Settings conflict resolved per-field via merge."""
    venue_id, *_ = repair_venue_cleared
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

    snapshot = {
        "settings": {
            "items": [
                {"key": "rotation_mode", "value": "weighted", "updated_at": "2026-01-01T00:00:00Z"}
            ],
            "last_modified_at": "2025-01-01T00:00:00Z",
        }
    }

    start = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(repair_venue_cleared[3]),
    )
    sync_id = start.json()["sync_id"]
    conflict = start.json()["conflicts"][0]

    resolve = await client.post(
        f"{REPAIR_BASE}/{sync_id}/resolve",
        json={
            "resolutions": [
                {
                    "entity_type": "settings",
                    "entity_id": "rotation_mode",
                    "resolution": "merge",
                    "field_resolutions": {"value": "client"},
                    "server_state": conflict["server_state"],
                    "client_state": conflict["client_state"],
                    "changed_fields": conflict["changed_fields"],
                    "display_label": conflict["display_label"],
                    "locked_fields": conflict["locked_fields"],
                    "mergeable_fields": conflict["mergeable_fields"],
                }
            ]
        },
        headers=_kj_headers(repair_venue_cleared[3]),
    )
    assert resolve.status_code == status.HTTP_200_OK
    cfg_after = (
        await db.execute(
            select(VenueConfig).where(
                VenueConfig.venue_id == venue_id, VenueConfig.config_key == "rotation_mode"
            )
        )
    ).scalar_one()
    assert cfg_after.config_value == "weighted"


# -----------------------------------------------------------------------------
# Rollback / cleanup
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_repair_sync_cancel_rolls_back_unapplied_changes(client, repair_venue_cleared, db):
    """Cancelling a prompt-mode job before resolve leaves DB unchanged."""
    venue_id, singer_id, _, raw_key = repair_venue_cleared
    server_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = await db.get(Singer, singer_id)
    row.stage_name = "Server Stage"
    row.updated_at = server_now
    await db.commit()

    snapshot = {
        "singers": {
            "items": [_singer_item(singer_id, stage_name="Client Stage")],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    start = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "prompt", "snapshot": snapshot},
        headers=_kj_headers(raw_key),
    )
    sync_id = start.json()["sync_id"]
    assert start.json()["status"] == "needs_resolution"

    cancel = await client.delete(
        f"{REPAIR_BASE}/{sync_id}",
        headers=_kj_headers(raw_key),
    )
    assert cancel.status_code == status.HTTP_202_ACCEPTED

    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Server Stage"


@pytest.mark.anyio
async def test_repair_sync_idempotency_prevents_duplicate_apply(client, repair_venue_cleared, db):
    """Same idempotency key does not re-apply snapshot."""
    venue_id, singer_id, _, raw_key = repair_venue_cleared
    idempotency = str(uuid.uuid4())
    snapshot = {
        "singers": {
            "items": [_singer_item(singer_id, stage_name="Idempotent Stage")],
            "deleted_ids": [],
            "last_modified_at": "2026-01-01T00:00:00Z",
        }
    }

    resp1 = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers={**_kj_headers(raw_key), "X-Idempotency-Key": idempotency},
    )
    sync_id_1 = resp1.json()["sync_id"]

    # Mutate the server row so a re-apply would cause a prompt-mode conflict if not idempotent.
    row = await db.get(Singer, singer_id)
    row.stage_name = "Mutated Stage"
    await db.commit()

    resp2 = await client.post(
        REPAIR_BASE,
        json={"venue_id": venue_id, "mode": "client_wins", "snapshot": snapshot},
        headers={**_kj_headers(raw_key), "X-Idempotency-Key": idempotency},
    )
    assert resp2.json()["sync_id"] == sync_id_1
    assert resp2.json()["status"] == "completed"

    # Server row should remain mutated (idempotent replay did not re-apply).
    row_after = await db.get(Singer, singer_id)
    assert row_after.stage_name == "Mutated Stage"
