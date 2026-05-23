"""Sprint 3: End-to-End Show Flow Integration Tests.

Exercises the full karaoke show lifecycle through the REST API:
venue open → KJ login → singers join → KJ approves → KJ starts → KJ completes
(auto-advance) → KJ skips → singer checks history/stats → venue closes.

Invoke: pytest tests/test_integration_show_flow.py -v --integration
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Venue, Singer, Song, QueueRequest
from app.core.security import hash_password
from app.core.queue_service import ACTIVE_STATUSES

AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def showflow_venue(db: AsyncSession):
    """A fresh active venue for the show flow test."""
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name="ShowFlow Venue",
        slug=f"show-{venue_id[:8]}",
        is_active=1,
    )
    db.add(venue)
    await db.commit()
    return venue_id


@pytest.fixture
async def showflow_kj(db: AsyncSession, showflow_venue):
    """A KJ with a real hashed password for login flows."""
    venue_id = showflow_venue
    kj_id = str(uuid.uuid4())
    kj = Singer(
        id=kj_id,
        venue_id=venue_id,
        stage_name="ShowFlow KJ",
        email="kj@showflow.example.com",
        password_hash=hash_password("kjpassword"),
        role="kj",
    )
    db.add(kj)
    await db.commit()
    await db.refresh(kj)
    return venue_id, kj_id


@pytest.fixture
async def showflow_songs(db: AsyncSession, showflow_venue):
    """Seed 4 available songs in the venue."""
    venue_id = showflow_venue
    songs = [
        Song(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            title="Song A",
            artist="Artist A",
            is_available=1,
            duration_ms=180_000,
            genre="Rock",
        ),
        Song(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            title="Song B",
            artist="Artist B",
            is_available=1,
            duration_ms=240_000,
            genre="Pop",
        ),
        Song(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            title="Song C",
            artist="Artist C",
            is_available=1,
            duration_ms=200_000,
            genre="Jazz",
        ),
        Song(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            title="Song D",
            artist="Artist D",
            is_available=0,
            duration_ms=300_000,
            genre="Classical",
        ),
    ]
    for s in songs:
        db.add(s)
    await db.commit()
    for s in songs:
        await db.refresh(s)
    return venue_id, songs


# =====================================================================
# SHOW FLOW: Full karaoke lifecycle
# =====================================================================


@pytest.mark.anyio
@pytest.mark.integration
async def test_show_flow_full_lifecycle(
    client, db, showflow_venue, showflow_kj, showflow_songs
):
    """End-to-end show flow: venue open → singers join → KJ manages queue
    through completion and skip → singer checks history/stats → venue closes.
    """
    venue_id, kj_id = showflow_kj
    _, songs = showflow_songs

    # -----------------------------------------------------------------
    # Setup: create singers with hashed passwords
    # -----------------------------------------------------------------
    singer_a_id = str(uuid.uuid4())
    singer_a = Singer(
        id=singer_a_id,
        venue_id=venue_id,
        stage_name="Singer A",
        email="singer-a@showflow.example.com",
        password_hash=hash_password("password123"),
        role="singer",
    )
    db.add(singer_a)

    singer_b_id = str(uuid.uuid4())
    singer_b = Singer(
        id=singer_b_id,
        venue_id=venue_id,
        stage_name="Singer B",
        email="singer-b@showflow.example.com",
        password_hash=hash_password("password123"),
        role="singer",
    )
    db.add(singer_b)
    await db.commit()

    # -----------------------------------------------------------------
    # Step 0: KJ and singers log in
    # -----------------------------------------------------------------
    kj_login = await client.post(
        "/v1/auth/login",
        json={"email": "kj@showflow.example.com", "password": "kjpassword"},
    )
    assert kj_login.status_code == status.HTTP_200_OK
    kj_token = kj_login.json()["access_token"]

    a_login = await client.post(
        "/v1/auth/login",
        json={"email": "singer-a@showflow.example.com", "password": "password123"},
    )
    assert a_login.status_code == status.HTTP_200_OK
    a_token = a_login.json()["access_token"]

    b_login = await client.post(
        "/v1/auth/login",
        json={"email": "singer-b@showflow.example.com", "password": "password123"},
    )
    assert b_login.status_code == status.HTTP_200_OK
    b_token = b_login.json()["access_token"]

    # -----------------------------------------------------------------
    # Step 1: Singer A joins queue
    # -----------------------------------------------------------------
    join_a = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(a_token),
        json={"song_id": songs[0].id, "notes": "For the crowd!"},
    )
    assert join_a.status_code == status.HTTP_201_CREATED
    req_a = join_a.json()
    req_a_id = req_a["request_id"]
    assert req_a["estimated_position"] == 1

    # -----------------------------------------------------------------
    # Step 2: Singer B joins queue
    # -----------------------------------------------------------------
    join_b = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(b_token),
        json={"song_id": songs[1].id},
    )
    assert join_b.status_code == status.HTTP_201_CREATED
    req_b = join_b.json()
    req_b_id = req_b["request_id"]
    assert req_b["estimated_position"] == 2

    # Verify public queue shows both
    public_q1 = await client.get(f"/v1/venues/{venue_id}/queue/venue")
    assert public_q1.status_code == status.HTTP_200_OK
    pub1 = public_q1.json()
    assert len(pub1["items"]) == 2
    assert pub1["items"][0]["stage_name"] == "Singer A"
    assert pub1["items"][1]["stage_name"] == "Singer B"

    # -----------------------------------------------------------------
    # Step 3: KJ approves both
    # -----------------------------------------------------------------
    approve_a = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{req_a_id}/approve",
        headers=AUTHORIZATION(kj_token),
    )
    assert approve_a.status_code == status.HTTP_200_OK
    assert approve_a.json()["status"] == "approved"

    approve_b = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{req_b_id}/approve",
        headers=AUTHORIZATION(kj_token),
    )
    assert approve_b.status_code == status.HTTP_200_OK
    assert approve_b.json()["status"] == "approved"

    # Verify both approved via admin view
    admin_q2 = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(kj_token),
    )
    assert admin_q2.status_code == status.HTTP_200_OK
    aq2 = admin_q2.json()
    statuses2 = {item["request_id"]: item["status"] for item in aq2["items"]}
    assert statuses2[req_a_id] == "approved"
    assert statuses2[req_b_id] == "approved"
    assert aq2["items"][0]["position"] == 1
    assert aq2["items"][1]["position"] == 2

    # Verify rotation order through DB
    db_items_pre = (
        await db.execute(
            select(QueueRequest).where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    db_pos_pre = {str(i.id): i.rotation_position for i in db_items_pre}
    assert db_pos_pre[req_a_id] < db_pos_pre[req_b_id]

    # -----------------------------------------------------------------
    # Step 4: KJ starts A
    # -----------------------------------------------------------------
    start_a = await client.post(
        f"/v1/venues/{venue_id}/queue/{req_a_id}/start",
        headers=AUTHORIZATION(kj_token),
    )
    assert start_a.status_code == status.HTTP_200_OK
    assert start_a.json()["status"] == "now_playing"

    # Verify A is now_playing, B is still approved
    admin_q3 = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(kj_token),
    )
    assert admin_q3.status_code == status.HTTP_200_OK
    aq3 = admin_q3.json()
    statuses3 = {item["request_id"]: item["status"] for item in aq3["items"]}
    assert statuses3[req_a_id] == "now_playing"
    assert statuses3[req_b_id] == "approved"

    # Verify singer A sees their request as now_playing
    a_status = await client.get(
        f"/v1/venues/{venue_id}/queue/status",
        headers=AUTHORIZATION(a_token),
    )
    assert a_status.status_code == status.HTTP_200_OK
    a_stats = a_status.json()
    assert len(a_stats) == 1
    assert a_stats[0]["request_id"] == req_a_id
    assert a_stats[0]["status"] == "now_playing"

    # -----------------------------------------------------------------
    # Step 5: KJ completes A (auto-advances to B)
    # -----------------------------------------------------------------
    complete_a = await client.post(
        f"/v1/venues/{venue_id}/queue/{req_a_id}/complete",
        headers=AUTHORIZATION(kj_token),
    )
    assert complete_a.status_code == status.HTTP_200_OK
    assert complete_a.json()["status"] == "completed"

    # Verify A is completed in DB
    db_req_a = (
        await db.execute(
            select(QueueRequest).where(QueueRequest.id == req_a_id)
        )
    ).scalar_one()
    assert str(db_req_a.status) == "completed"
    assert db_req_a.played_at is not None

    # Verify B auto-advanced to now_playing
    admin_q4 = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(kj_token),
    )
    assert admin_q4.status_code == status.HTTP_200_OK
    aq4 = admin_q4.json()
    assert aq4["total"] == 1
    assert aq4["items"][0]["request_id"] == req_b_id
    assert aq4["items"][0]["status"] == "now_playing"

    # Verify singer B sees their request as now_playing
    b_status = await client.get(
        f"/v1/venues/{venue_id}/queue/status",
        headers=AUTHORIZATION(b_token),
    )
    assert b_status.status_code == status.HTTP_200_OK
    b_stats = b_status.json()
    assert len(b_stats) == 1
    assert b_stats[0]["request_id"] == req_b_id
    assert b_stats[0]["status"] == "now_playing"

    # -----------------------------------------------------------------
    # Step 6: KJ skips B
    # -----------------------------------------------------------------
    skip_b = await client.post(
        f"/v1/venues/{venue_id}/queue/{req_b_id}/skip",
        headers=AUTHORIZATION(kj_token),
    )
    assert skip_b.status_code == status.HTTP_200_OK
    assert skip_b.json()["status"] == "skipped"

    # Verify B is skipped in DB
    db_req_b = (
        await db.execute(
            select(QueueRequest).where(QueueRequest.id == req_b_id)
        )
    ).scalar_one()
    assert str(db_req_b.status) == "skipped"
    assert db_req_b.played_at is not None

    # Verify no active items remain
    admin_q5 = await client.get(
        f"/v1/venues/{venue_id}/queue/admin",
        headers=AUTHORIZATION(kj_token),
    )
    assert admin_q5.status_code == status.HTTP_200_OK
    aq5 = admin_q5.json()
    assert aq5["total"] == 0

    # Verify public queue is empty / no current song
    public_q5 = await client.get(f"/v1/venues/{venue_id}/queue/venue")
    assert public_q5.status_code == status.HTTP_200_OK
    pub5 = public_q5.json()
    assert len(pub5["items"]) == 0
    assert pub5["current_song"] is None

    # -----------------------------------------------------------------
    # Step 7: Singer B checks history and stats
    # -----------------------------------------------------------------
    history_b = await client.get(
        f"/v1/venues/{venue_id}/singers/history",
        headers=AUTHORIZATION(b_token),
    )
    assert history_b.status_code == status.HTTP_200_OK
    hist = history_b.json()
    assert hist["total"] == 1
    assert hist["items"][0]["request_id"] == req_b_id
    assert hist["items"][0]["status"] == "skipped"
    assert hist["items"][0]["song_title"] == "Song B"
    assert hist["items"][0]["song_artist"] == "Artist B"

    stats_b = await client.get(
        f"/v1/venues/{venue_id}/singers/stats",
        headers=AUTHORIZATION(b_token),
    )
    assert stats_b.status_code == status.HTTP_200_OK
    st = stats_b.json()
    assert st["songs_sung"] == 0
    assert st["avg_wait_min"] is None
    assert st["favorite_genre"] is None

    # Singer A history: should show the completed request
    history_a = await client.get(
        f"/v1/venues/{venue_id}/singers/history",
        headers=AUTHORIZATION(a_token),
    )
    assert history_a.status_code == status.HTTP_200_OK
    hist_a = history_a.json()
    assert hist_a["total"] == 1
    assert hist_a["items"][0]["status"] == "completed"
    assert hist_a["items"][0]["song_title"] == "Song A"

    stats_a = await client.get(
        f"/v1/venues/{venue_id}/singers/stats",
        headers=AUTHORIZATION(a_token),
    )
    assert stats_a.status_code == status.HTTP_200_OK
    st_a = stats_a.json()
    assert st_a["songs_sung"] == 1
    assert st_a["avg_wait_min"] is not None
    assert st_a["favorite_genre"] == "Rock"

    # -----------------------------------------------------------------
    # Step 8: Verify analytics updated at venue level
    # -----------------------------------------------------------------
    overview = await client.get(
        f"/v1/analytics/venue/{venue_id}/overview",
        headers=AUTHORIZATION(kj_token),
    )
    assert overview.status_code == status.HTTP_200_OK
    ov = overview.json()
    assert ov["total_songs_played"] == 1
    assert ov["total_singers"] == 3  # KJ + Singer A + Singer B
    assert ov["avg_queue_wait_seconds"] is not None

    # -----------------------------------------------------------------
    # Step 9: Venue closes
    # -----------------------------------------------------------------
    venue = (
        await db.execute(select(Venue).where(Venue.id == venue_id))
    ).scalar_one()
    venue.is_active = 0
    await db.commit()

    # Verify no new joins accepted
    new_join = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(a_token),
        json={"song_id": songs[2].id},
    )
    assert new_join.status_code == status.HTTP_404_NOT_FOUND
