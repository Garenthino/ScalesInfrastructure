"""WebSocket queue live-update tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models import Singer, Venue, Song, QueueRequest
from app.core.config import settings
from app.core.queue_service import QueueEventPublisher
from starlette.websockets import WebSocketDisconnect


def NOW():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_token(user_id: str, venue_id: str, role: str = "singer") -> str:
    from jose import jwt
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "venue_id": venue_id,
        "role": role,
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------------------
# WebSocket TestClient fixture (patches factories to use test DB)
# ---------------------------------------------------------------------------

@pytest.fixture
async def ws_client(db):
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    import app.core.db as _db_mod
    import app.core.auth as _auth_mod
    import app.routers.auth as _auth_router
    import app.websockets.queue_ws as _ws_mod
    from app.core.db import get_db

    _orig_db_factory = _db_mod.async_session_factory
    _orig_auth_factory = _auth_mod.async_session_factory
    _orig_router_factory = _auth_router.async_session_factory
    _orig_ws_factory = _ws_mod.async_session_factory

    _fresh_factory = async_sessionmaker(
        db.bind, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    _db_mod.async_session_factory = _fresh_factory
    _auth_mod.async_session_factory = _fresh_factory
    _auth_router.async_session_factory = _fresh_factory
    _ws_mod.async_session_factory = _fresh_factory

    async def _override():
        yield db
    app.dependency_overrides[get_db] = _override

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    _db_mod.async_session_factory = _orig_db_factory
    _auth_mod.async_session_factory = _orig_auth_factory
    _auth_router.async_session_factory = _orig_router_factory
    _ws_mod.async_session_factory = _orig_ws_factory

@pytest.fixture
async def ws_venue(db: AsyncSession):
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="WS Venue", slug=f"ws-{venue_id[:8]}")
    db.add(venue)
    await db.commit()
    return venue_id


@pytest.fixture
async def ws_singer(db: AsyncSession, ws_venue: str):
    singer_id = str(uuid.uuid4())
    singer = Singer(
        id=singer_id,
        venue_id=ws_venue,
        stage_name="WS Singer",
        email="ws_singer@test.com",
        password_hash="",
        role="singer",
    )
    db.add(singer)
    await db.commit()
    await db.refresh(singer)
    return singer


@pytest.fixture
async def ws_kj(db: AsyncSession, ws_venue: str):
    kj_id = str(uuid.uuid4())
    kj = Singer(
        id=kj_id,
        venue_id=ws_venue,
        stage_name="WS KJ",
        email="ws_kj@test.com",
        password_hash="",
        role="kj",
    )
    db.add(kj)
    await db.commit()
    await db.refresh(kj)
    return kj


@pytest.fixture
async def ws_songs(db: AsyncSession, ws_venue: str):
    songs = []
    for title in ["Song A", "Song B"]:
        song = Song(
            id=str(uuid.uuid4()),
            venue_id=ws_venue,
            title=title,
            artist="Artist",
            is_available=1,
            duration_ms=240000,
        )
        db.add(song)
        songs.append(song)
    await db.commit()
    for s in songs:
        await db.refresh(s)
    return songs


@pytest.fixture
async def ws_queue_item(db: AsyncSession, ws_venue: str, ws_singer: Singer, ws_songs: list):
    q = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=ws_venue,
        singer_id=str(ws_singer.id),
        song_id=str(ws_songs[0].id),
        status="approved",
        rotation_position=1,
        requested_at=NOW(),
        updated_at=NOW(),
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_ws_connect_valid_token(
    ws_client: TestClient,
    ws_venue: str,
    ws_singer: Singer,
):
    token = _make_token(str(ws_singer.id), ws_venue, "singer")
    with ws_client.websocket_connect(
        f"/ws/venues/{ws_venue}/queue?token={token}"
    ) as ws:
        # The first message is the snapshot we deliver to every client.
        data = ws.receive_json()
        assert data["event_type"] == "queue_updated"


@pytest.mark.anyio
async def test_ws_reject_unauthenticated(ws_client: TestClient, ws_venue: str):
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(
            f"/ws/venues/{ws_venue}/queue"
        ) as ws:
            ws.receive_json()


@pytest.mark.anyio
async def test_ws_reject_wrong_venue(
    ws_client: TestClient,
    ws_venue: str,
    ws_singer: Singer,
):
    token = _make_token(str(ws_singer.id), ws_venue, "singer")
    other_venue = str(uuid.uuid4())
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(
            f"/ws/venues/{other_venue}/queue?token={token}"
        ) as ws:
            ws.receive_json()


@pytest.mark.anyio
async def test_ws_kj_receives_full_queue(
    ws_client: TestClient,
    ws_venue: str,
    ws_kj: Singer,
    ws_queue_item,
):
    token = _make_token(str(ws_kj.id), ws_venue, "kj")
    with ws_client.websocket_connect(
        f"/ws/venues/{ws_venue}/queue?token={token}"
    ) as ws:
        data = ws.receive_json()
        assert data["event_type"] == "queue_updated"
        assert "items" in data.get("data", {})


@pytest.mark.anyio
async def test_ws_receive_event_on_queue_change(
    ws_client: TestClient,
    ws_venue: str,
    ws_singer: Singer,
):
    token = _make_token(str(ws_singer.id), ws_venue, "singer")
    with ws_client.websocket_connect(
        f"/ws/venues/{ws_venue}/queue?token={token}"
    ) as ws:
        # First message is initial snapshot
        data = ws.receive_json()
        assert data["event_type"] == "queue_updated"

        # Publish a new event
        await QueueEventPublisher.publish(
            ws_venue, "queue_updated", {"action": "test_event"}
        )

        data = ws.receive_json()
        assert data["event_type"] == "queue_updated"
