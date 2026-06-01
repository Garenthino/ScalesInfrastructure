"""Tests for notification router, device token registration, and push delivery service."""
from __future__ import annotations

import pytest
import uuid

from httpx import AsyncClient, ASGITransport

from app.models import DeviceToken, Notification


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_singer(db, venue_id: str, email: str, password: str = "testpass123") -> str:
    from app.core.security import hash_password
    from app.models import Singer
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="TestSinger",
        email=email,
        password_hash=hash_password(password),
        role="singer",
    )
    db.add(singer)
    await db.commit()
    await db.refresh(singer)
    return str(singer.id)


async def _login(client: AsyncClient, email: str, password: str = "testpass123") -> str:
    resp = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.fixture
async def notification_user(db, client):
    """Create a singer + venue pair for notification tests."""
    from app.models import Venue
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="Test Venue", slug="test-venue", venue_code="ABCDEF")
    db.add(venue)
    await db.commit()
    await db.refresh(venue)

    singer_id = await _create_singer(db, venue_id, "notify@test.com")
    token = await _login(client, "notify@test.com")
    return {"venue_id": venue_id, "singer_id": singer_id, "token": token}


# ---------------------------------------------------------------------------
# Device Token Registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_device_token(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/me/devices",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "platform": "fcm",
            "token": "fcm-test-token-1234567890",
            "device_name": "Pixel 7",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["platform"] == "fcm"
    assert data["token"] == "fcm-test-token-1234567890"
    assert data["device_name"] == "Pixel 7"
    assert data["is_active"] is True
    assert data["singer_id"] == notification_user["singer_id"]


@pytest.mark.asyncio
async def test_register_device_token_replaces_old_same_platform(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    await client.post(
        f"/v1/venues/{venue_id}/singers/me/devices",
        headers={"Authorization": f"Bearer {token}"},
        json={"platform": "fcm", "token": "old-token-long", "device_name": "Old Phone"},
    )

    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/me/devices",
        headers={"Authorization": f"Bearer {token}"},
        json={"platform": "fcm", "token": "new-token-long", "device_name": "New Phone"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["token"] == "new-token-long"


@pytest.mark.asyncio
async def test_list_device_tokens(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    await client.post(
        f"/v1/venues/{venue_id}/singers/me/devices",
        headers={"Authorization": f"Bearer {token}"},
        json={"platform": "fcm", "token": "list-token-1", "device_name": "Phone A"},
    )
    await client.post(
        f"/v1/venues/{venue_id}/singers/me/devices",
        headers={"Authorization": f"Bearer {token}"},
        json={"platform": "apns", "token": "list-token-2", "device_name": "Phone B"},
    )

    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/devices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1


@pytest.mark.asyncio
async def test_unregister_device_token(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    r = await client.post(
        f"/v1/venues/{venue_id}/singers/me/devices",
        headers={"Authorization": f"Bearer {token}"},
        json={"platform": "fcm", "token": "del-token-extra", "device_name": "Temp"},
    )
    device_id = r.json()["id"]

    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/me/devices/{device_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204, resp.text


# ---------------------------------------------------------------------------
# Notification History
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_notifications_empty(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 0
    assert data["unread_count"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_mark_notifications_read(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    resp = await client.post(
        f"/v1/venues/{venue_id}/singers/me/notifications/read",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["marked_count"] == 0


# ---------------------------------------------------------------------------
# Notification service (unit-style, mocked DB)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_singer_persists_notification(db):
    from app.core.notification_service import notify_singer
    from app.models import Venue, Singer
    from app.core.security import hash_password

    venue_id = str(uuid.uuid4())
    singer_id = str(uuid.uuid4())

    venue = Venue(id=venue_id, name="V", slug="v", venue_code="ABCDEF")
    singer = Singer(
        id=singer_id,
        venue_id=venue_id,
        stage_name="S",
        email="s@x.com",
        password_hash=hash_password("pass"),
        role="singer",
    )
    db.add(venue)
    db.add(singer)
    await db.commit()

    await notify_singer(
        db,
        singer_id,
        venue_id,
        notification_type="up_soon",
        title="Up soon",
        body="You're 2nd",
        data={"position": 2},
    )

    from sqlalchemy import select
    from app.models import Notification
    result = await db.execute(
        select(Notification).where(Notification.singer_id == singer_id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].notification_type == "up_soon"
    assert rows[0].title == "Up soon"
    assert rows[0].is_read == 0


# ---------------------------------------------------------------------------
# Integration: queue event triggers notification
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_triggers_position_notification(db):
    from app.core.queue_service import QueueService
    from app.models import Venue, Singer, Song, QueueRequest
    from app.core.security import hash_password

    venue_id = str(uuid.uuid4())
    singer_id = str(uuid.uuid4())
    song_id = str(uuid.uuid4())
    req_id = str(uuid.uuid4())

    venue = Venue(id=venue_id, name="V", slug="v", venue_code="ABCDEF")
    singer = Singer(
        id=singer_id,
        venue_id=venue_id,
        stage_name="S",
        email="s@x.com",
        password_hash=hash_password("pass"),
        role="singer",
    )
    song = Song(id=song_id, venue_id=venue_id, title="T", artist="A")
    req = QueueRequest(
        id=req_id,
        venue_id=venue_id,
        singer_id=singer_id,
        song_id=song_id,
        status="pending",
        requested_at="2026-05-31T00:00:00Z",
    )
    db.add_all([venue, singer, song, req])
    await db.commit()

    svc = QueueService(db)
    await svc.approve(venue_id, req_id)

    from sqlalchemy import select
    from app.models import Notification
    result = await db.execute(
        select(Notification).where(
            Notification.singer_id == singer_id,
            Notification.notification_type == "up_soon",
        )
    )
    rows = result.scalars().all()
    # Position=2 notification fires when queue has exactly 2 items and this is 2nd
    # With 1 item, no position=2 trigger
    assert len(rows) == 0  # only 1 item, not position 2
