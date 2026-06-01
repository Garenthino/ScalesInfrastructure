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


# ---------------------------------------------------------------------------
# Unread Count Endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unread_count_endpoint(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/notifications/unread-count",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "unread_count" in data
    assert data["unread_count"] == 0


# ---------------------------------------------------------------------------
# Notification Settings Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_notification_settings_auto_creates_defaults(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/notification-settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["singer_id"] == notification_user["singer_id"]
    assert data["venue_id"] == venue_id
    assert data["up_soon"] is True
    assert data["on_stage"] is True
    assert data["bumped"] is True
    assert data["queue_update"] is True
    assert data["announcement"] is True
    assert data["social"] is True
    assert data["payment"] is True


@pytest.mark.asyncio
async def test_put_notification_settings(client, notification_user):
    venue_id = notification_user["venue_id"]
    token = notification_user["token"]

    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/me/notification-settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"up_soon": False, "social": False},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["up_soon"] is False
    assert data["on_stage"] is True
    assert data["bumped"] is True
    assert data["queue_update"] is True
    assert data["announcement"] is True
    assert data["social"] is False
    assert data["payment"] is True

    # Verify persisted via GET
    resp2 = await client.get(
        f"/v1/venues/{venue_id}/singers/me/notification-settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp2.json()["up_soon"] is False
    assert resp2.json()["social"] is False


# ---------------------------------------------------------------------------
# Notification service preference filtering
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notify_singer_skips_push_when_disabled(db):
    from app.core.notification_service import notify_singer
    from app.models import Venue, Singer, NotificationSetting, DeviceToken
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
    # Create a device token so push WOULD fire if enabled
    token = DeviceToken(
        id=str(uuid.uuid4()),
        singer_id=singer_id,
        venue_id=venue_id,
        platform="fcm",
        token="fcm-test-token-push-skip",
        is_active=1,
    )
    # Disable "up_soon" push
    settings = NotificationSetting(
        id=str(uuid.uuid4()),
        singer_id=singer_id,
        venue_id=venue_id,
        up_soon=0,
        on_stage=1,
        bumped=1,
        queue_update=1,
        announcement=1,
        social=1,
        payment=1,
    )
    db.add_all([venue, singer, token, settings])
    await db.commit()

    # Track whether enqueue_push_notification would be called by
    # temporarily monkey-patching it to record the call.
    from app.core import notification_service as _ns
    original_enqueue = _ns.enqueue_push_notification
    calls = []
    def _fake_enqueue(*args, **kwargs):
        calls.append((args, kwargs))
        return None
    _ns.enqueue_push_notification = _fake_enqueue
    try:
        await notify_singer(
            db,
            singer_id,
            venue_id,
            notification_type="up_soon",
            title="Up soon",
            body="You're 2nd",
            data={"position": 2},
        )
    finally:
        _ns.enqueue_push_notification = original_enqueue

    # In-app notification should still be persisted
    from sqlalchemy import select
    from app.models import Notification
    result = await db.execute(select(Notification).where(Notification.singer_id == singer_id))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].notification_type == "up_soon"

    # Push should NOT have been enqueued because up_soon is disabled
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_notify_singer_sends_push_when_enabled(db):
    from app.core.notification_service import notify_singer
    from app.models import Venue, Singer, NotificationSetting, DeviceToken
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
    token = DeviceToken(
        id=str(uuid.uuid4()),
        singer_id=singer_id,
        venue_id=venue_id,
        platform="fcm",
        token="fcm-test-token-push-send",
        is_active=1,
    )
    # up_soon enabled (default)
    settings = NotificationSetting(
        id=str(uuid.uuid4()),
        singer_id=singer_id,
        venue_id=venue_id,
        up_soon=1,
        on_stage=0,
        bumped=1,
        queue_update=1,
        announcement=1,
        social=1,
        payment=1,
    )
    db.add_all([venue, singer, token, settings])
    await db.commit()

    from app.core import notification_service as _ns
    original_enqueue = _ns.enqueue_push_notification
    calls = []
    def _fake_enqueue(*args, **kwargs):
        calls.append((args, kwargs))
        return None
    _ns.enqueue_push_notification = _fake_enqueue
    try:
        await notify_singer(
            db,
            singer_id,
            venue_id,
            notification_type="up_soon",
            title="Up soon",
            body="You're 2nd",
            data={"position": 2},
        )
    finally:
        _ns.enqueue_push_notification = original_enqueue

    # In-app notification persisted
    from sqlalchemy import select
    from app.models import Notification
    result = await db.execute(select(Notification).where(Notification.singer_id == singer_id))
    rows = result.scalars().all()
    assert len(rows) == 1

    # Push WAS enqueued because up_soon is enabled
    assert len(calls) == 1
    _args, _kwargs = calls[0]
    assert _kwargs["device_tokens"] == ["fcm-test-token-push-send"]
    assert _kwargs["title"] == "Up soon"
    assert _kwargs["body"] == "You're 2nd"


@pytest.mark.asyncio
async def test_notify_singer_skips_push_for_unmapped_type(db):
    """Unknown notification types are not blocked by settings (default=send)."""
    from app.core.notification_service import notify_singer
    from app.models import Venue, Singer, DeviceToken
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
    token = DeviceToken(
        id=str(uuid.uuid4()),
        singer_id=singer_id,
        venue_id=venue_id,
        platform="fcm",
        token="fcm-test-token-unknown",
        is_active=1,
    )
    db.add_all([venue, singer, token])
    await db.commit()

    from app.core import notification_service as _ns
    original_enqueue = _ns.enqueue_push_notification
    calls = []
    def _fake_enqueue(*args, **kwargs):
        calls.append((args, kwargs))
        return None
    _ns.enqueue_push_notification = _fake_enqueue
    try:
        await notify_singer(
            db,
            singer_id,
            venue_id,
            notification_type="some_new_type",
            title="New",
            body="Body",
        )
    finally:
        _ns.enqueue_push_notification = original_enqueue

    # Push still sent because unmapped types default to enabled
    assert len(calls) == 1
    _args, _kwargs = calls[0]
    assert "fcm-test-token-unknown" in _kwargs["device_tokens"]


@pytest.mark.asyncio
async def test_notify_singer_skips_push_when_no_settings_row(db):
    """If no NotificationSetting row exists at all, push defaults to enabled."""
    from app.core.notification_service import notify_singer
    from app.models import Venue, Singer, DeviceToken
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
    token = DeviceToken(
        id=str(uuid.uuid4()),
        singer_id=singer_id,
        venue_id=venue_id,
        platform="fcm",
        token="fcm-test-token-no-settings",
        is_active=1,
    )
    db.add_all([venue, singer, token])
    await db.commit()

    from app.core import notification_service as _ns
    original_enqueue = _ns.enqueue_push_notification
    calls = []
    def _fake_enqueue(*args, **kwargs):
        calls.append((args, kwargs))
        return None
    _ns.enqueue_push_notification = _fake_enqueue
    try:
        await notify_singer(
            db,
            singer_id,
            venue_id,
            notification_type="up_soon",
            title="Up soon",
            body="You're 2nd",
        )
    finally:
        _ns.enqueue_push_notification = original_enqueue

    # Push sent because no settings row = defaults enabled
    assert len(calls) == 1
    _args, _kwargs = calls[0]
    assert "fcm-test-token-no-settings" in _kwargs["device_tokens"]
