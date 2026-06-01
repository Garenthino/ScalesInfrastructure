"""Sprint 1: Performance Smoke Tests.

Note: True concurrency with separate DB connections requires Docker.
ASGI tests use rapid sequential execution to approximate load.

Invoke: pytest tests/test_integration_performance.py -v --integration
"""
from __future__ import annotations

import time
import uuid

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Venue, Singer, Song
from app.core.security import hash_password

AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def perf_venue(db: AsyncSession):
    vid = str(uuid.uuid4())
    v = Venue(id=vid, name="Perf Venue", slug=f"perf-{vid[:8]}")
    db.add(v)
    await db.commit()
    return vid


@pytest.fixture
async def perf_songs(db: AsyncSession, perf_venue):
    songs = []
    for i in range(10):
        s = Song(
            id=str(uuid.uuid4()), venue_id=perf_venue,
            title=f"Perf Song {i}", artist=f"Artist {i}",
            is_available=1, duration_ms=180_000,
        )
        db.add(s)
        songs.append(s)
    await db.commit()
    for s in songs:
        await db.refresh(s)
    return perf_venue, songs


# =====================================================================
# PERFORMANCE: Rapid-fire /queue/join (sequential, ASGI limitation)
# =====================================================================

@pytest.mark.anyio
@pytest.mark.integration
async def test_perf_rapid_queue_join(
    client, jwt_encode, db: AsyncSession, perf_venue, perf_songs
):
    """50 singers rapidly join queue sequentially; each request under 500ms."""
    venue_id, songs = perf_songs
    target_song = songs[0]

    singers = []
    tokens = []
    for i in range(50):
        sid = str(uuid.uuid4())
        s = Singer(
            id=sid, venue_id=venue_id, stage_name=f"Singer {i}",
            email=f"s{i}@perf.example.com", password_hash=hash_password("pw"), role="singer"
        )
        db.add(s)
        singers.append(s)
        tokens.append(jwt_encode(venue_id, role="singer", user_id=sid))
    await db.commit()

    times = []
    for tok in tokens:
        start = time.perf_counter()
        r = await client.post(
            f"/v1/venues/{venue_id}/queue",
            headers=AUTHORIZATION(tok),
            json={"song_id": target_song.id},
        )
        times.append((time.perf_counter() - start) * 1000)
        assert r.status_code == status.HTTP_201_CREATED

    max_ms = max(times)
    avg_ms = sum(times) / len(times)
    assert avg_ms < 500, f"Average join time {avg_ms:.1f}ms exceeded 500ms"
    assert max_ms < 2000, f"Max join time {max_ms:.1f}ms exceeded 2000ms"

    pub = await client.get(
        f"/v1/venues/{venue_id}/queue/list?per_page=100",
        headers=AUTHORIZATION(tokens[0]),
    )
    assert pub.status_code == 200
    assert pub.json()["total"] == 50


# =====================================================================
# PERFORMANCE: Rapid-fire logins (sequential)
# =====================================================================

@pytest.mark.anyio
@pytest.mark.integration
async def test_perf_rapid_logins(client, db: AsyncSession, perf_venue):
    """25 rapid sequential logins; average under 300ms (ASGI local)."""
    venue_id = perf_venue
    singers = []
    for i in range(25):
        s = Singer(
            id=str(uuid.uuid4()), venue_id=venue_id, stage_name=f"LoginSinger {i}",
            email=f"login{i}@perf.example.com", password_hash=hash_password("password123"),
            role="singer",
        )
        db.add(s)
        singers.append(s)
    await db.commit()

    times = []
    for s in singers:
        start = time.perf_counter()
        r = await client.post(
            "/v1/auth/login",
            json={"email": s.email, "password": "password123"},
        )
        times.append((time.perf_counter() - start) * 1000)
        assert r.status_code == status.HTTP_200_OK

    avg_ms = sum(times) / len(times)
    max_ms = max(times)
    assert avg_ms < 300, f"Average login time {avg_ms:.1f}ms exceeded 300ms"
    assert max_ms < 1000, f"Max login time {max_ms:.1f}ms exceeded 1000ms"


# =====================================================================
# PERFORMANCE: Search under 500ms
# =====================================================================

@pytest.mark.anyio
@pytest.mark.integration
async def test_perf_search_response_time(client, jwt_encode, perf_venue, perf_songs):
    """Song search returns in under 500ms even with many items."""
    venue_id, songs = perf_songs

    start = time.perf_counter()
    resp = await client.get(f"/v1/venues/{venue_id}/songs?q=Song")
    elapsed = time.perf_counter() - start
    assert resp.status_code == status.HTTP_200_OK
    elapsed_ms = elapsed * 1000
    assert elapsed_ms < 500, f"Search took {elapsed_ms:.1f}ms"
    assert resp.json()["total"] == 10


# =====================================================================
# PERFORMANCE: Auth endpoint under 200ms
# =====================================================================

@pytest.mark.anyio
@pytest.mark.integration
async def test_perf_auth_token_validation(client, jwt_encode, db, perf_venue):
    """Token validation (/auth/me) under 200ms."""
    s = Singer(id=str(uuid.uuid4()), venue_id=perf_venue, stage_name="AuthPerf",
                email="auth@perf.example.com", password_hash="$2b$12$bogus", role="singer")
    db.add(s)
    await db.commit()
    tok = jwt_encode(perf_venue, role="singer", user_id=s.id)

    start = time.perf_counter()
    resp = await client.get("/v1/auth/me", headers=AUTHORIZATION(tok))
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert resp.status_code == status.HTTP_200_OK
    assert elapsed_ms < 200, f"Auth validation took {elapsed_ms:.1f}ms"
