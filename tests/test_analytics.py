"""Analytics router tests — full coverage for read-only analytics endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import Singer, Venue, Song, QueueRequest


def AUTHORIZATION(token: str) -> dict[str, str]:
     return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(session, name: str = "Test Venue", **kwargs) -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=kwargs.get("slug") or f"test-{venue_id[:8]}",
        timezone=kwargs.get("timezone", "UTC"),
        is_active=1,
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(
    session,
    venue_id: str,
    stage_name: str = "Test Singer",
    role: str = "singer",
) -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("secret123"),
        role=role,
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


async def _seed_song(
    session,
    venue_id: str,
    title: str = "Test Song",
    artist: str = "Test Artist",
    genre: str = "Rock",
) -> Song:
    song = Song(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        title=title,
        artist=artist,
        genre=genre,
        is_available=1,
    )
    session.add(song)
    await session.commit()
    await session.refresh(song)
    return song


async def _seed_queue_request(
    session,
    venue_id: str,
    singer_id: str,
    song_id: str,
    status: str = "completed",
    requested_at: str | None = None,
    played_at: str | None = None,
) -> QueueRequest:
    qr = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=singer_id,
        song_id=song_id,
        status=status,
        requested_at=requested_at or _now_iso(),
        played_at=played_at,
        updated_at=_now_iso(),
    )
    session.add(qr)
    await session.commit()
    await session.refresh(qr)
    return qr


def _token_for_singer(jwt_encode, singer: Singer, expires=None) -> str:
    return jwt_encode(
        venue_id=singer.venue_id,
        role=singer.role,
        user_id=singer.id,
        expires=expires,
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(hour: int, day_offset: int = 0) -> str:
    dt = datetime.now(timezone.utc).replace(hour=hour, minute=0, second=0, microsecond=0)
    dt = dt + timedelta(days=day_offset)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# =====================================================================
# Venue overview
# =====================================================================

@pytest.mark.anyio
async def test_overview_requires_auth(client, db):
    resp = await client.get("/v1/analytics/venue/123/overview")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_overview_cross_venue_denied(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue A")
    v2 = await _seed_venue(db, "Venue B")
    singer = await _seed_singer(db, v1.id, role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v2.id}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_overview_admin_sees_any_venue(client, db, jwt_encode):
    v = await _seed_venue(db, "Venue A")
    admin = await _seed_singer(db, v.id, role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["venue_id"] == v.id
    assert data["total_songs_played"] == 0
    assert data["total_singers"] == 1  # admin counts too
    assert data["avg_queue_wait_seconds"] is None
    assert data["busiest_day"] is None
    assert data["busiest_hour"] is None


@pytest.mark.anyio
async def test_overview_with_populated_data(client, db, jwt_encode):
    v = await _seed_venue(db, "Populated Venue")
    s1 = await _seed_singer(db, v.id, "Alice")
    s2 = await _seed_singer(db, v.id, "Bob")
    song = await _seed_song(db, v.id, title="Hit Song", artist="Band", genre="Pop")

    await _seed_queue_request(
        db, v.id, s1.id, song.id,
        requested_at=_iso(hour=10, day_offset=-1),
        played_at=_iso(hour=10, day_offset=-1),
    )
    await _seed_queue_request(
        db, v.id, s2.id, song.id,
        requested_at=_iso(hour=14),
        played_at=_iso(hour=14),
    )

    token = _token_for_singer(jwt_encode, s1)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total_songs_played"] == 2
    assert data["total_singers"] == 2  # s1, s2 only
    assert data["avg_queue_wait_seconds"] == 0.0
    assert data["busiest_day"] is not None
    assert data["busiest_hour"] in {10, 14}


@pytest.mark.anyio
async def test_overview_singer_reads_own_venue(client, db, jwt_encode):
    v = await _seed_venue(db, "Own Venue")
    singer = await _seed_singer(db, v.id, role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["venue_id"] == v.id


@pytest.mark.anyio
async def test_overview_kj_reads_own_venue(client, db, jwt_encode):
    v = await _seed_venue(db, "KJ Venue")
    kj = await _seed_singer(db, v.id, role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["venue_id"] == v.id


@pytest.mark.anyio
async def test_overview_unknown_venue_singer_gets_403(client, db, jwt_encode):
    v = await _seed_venue(db, "Exists")
    singer = await _seed_singer(db, v.id, role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{uuid.uuid4()}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_overview_unknown_venue_admin_gets_404(client, db, jwt_encode):
    v = await _seed_venue(db, "Exists")
    admin = await _seed_singer(db, v.id, role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/analytics/venue/{uuid.uuid4()}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =====================================================================
# Leaderboard
# =====================================================================

@pytest.mark.anyio
async def test_leaderboard_requires_auth(client, db):
    resp = await client.get("/v1/analytics/venue/123/leaderboard")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_leaderboard_cross_venue_denied(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue A")
    v2 = await _seed_venue(db, "Venue B")
    singer = await _seed_singer(db, v1.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v2.id}/leaderboard",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_leaderboard_empty_venue(client, db, jwt_encode):
    v = await _seed_venue(db, "Empty")
    singer = await _seed_singer(db, v.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/leaderboard",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["items"] == []


@pytest.mark.anyio
async def test_leaderboard_ordering_and_limit(client, db, jwt_encode):
    v = await _seed_venue(db, "Leaderboard Venue")
    s1 = await _seed_singer(db, v.id, "Alice")
    s2 = await _seed_singer(db, v.id, "Bob")
    s3 = await _seed_singer(db, v.id, "Charlie")
    song = await _seed_song(db, v.id)

    # Alice: 3 performances, Bob: 1, Charlie: 2
    for _ in range(3):
        await _seed_queue_request(db, v.id, s1.id, song.id)
    await _seed_queue_request(db, v.id, s2.id, song.id)
    for _ in range(2):
        await _seed_queue_request(db, v.id, s3.id, song.id)

    token = _token_for_singer(jwt_encode, s1)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/leaderboard?limit=2",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert len(items) == 2
    assert items[0]["rank"] == 1
    assert items[0]["singer_id"] == s1.id
    assert items[0]["performance_count"] == 3
    assert items[1]["rank"] == 2
    assert items[1]["performance_count"] == 2


@pytest.mark.anyio
async def test_leaderboard_limit_bounds(client, db, jwt_encode):
    v = await _seed_venue(db, "Limit Venue")
    singer = await _seed_singer(db, v.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/leaderboard?limit=0",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/leaderboard?limit=51",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# =====================================================================
# Song popularity
# =====================================================================

@pytest.mark.anyio
async def test_song_popularity_requires_auth(client, db):
    resp = await client.get("/v1/analytics/venue/123/song-popularity")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_song_popularity_cross_venue_denied(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue A")
    v2 = await _seed_venue(db, "Venue B")
    singer = await _seed_singer(db, v1.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v2.id}/song-popularity",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_song_popularity_ordering(client, db, jwt_encode):
    v = await _seed_venue(db, "Pop Venue")
    s = await _seed_singer(db, v.id)
    sa = await _seed_song(db, v.id, title="Song A")
    sb = await _seed_song(db, v.id, title="Song B")
    sc = await _seed_song(db, v.id, title="Song C")

    for _ in range(5):
        await _seed_queue_request(db, v.id, s.id, sa.id)
    for _ in range(2):
        await _seed_queue_request(db, v.id, s.id, sb.id)
    await _seed_queue_request(db, v.id, s.id, sc.id)

    token = _token_for_singer(jwt_encode, s)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/song-popularity?limit=2",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert len(items) == 2
    assert items[0]["song_id"] == sa.id
    assert items[0]["request_count"] == 5
    assert items[1]["song_id"] == sb.id
    assert items[1]["request_count"] == 2


@pytest.mark.anyio
async def test_song_popularity_empty_venue(client, db, jwt_encode):
    v = await _seed_venue(db, "Empty")
    singer = await _seed_singer(db, v.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/song-popularity",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["items"] == []


# =====================================================================
# Hourly breakdown
# =====================================================================

@pytest.mark.anyio
async def test_hourly_breakdown_requires_auth(client, db):
    resp = await client.get("/v1/analytics/venue/123/hourly-breakdown")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_hourly_breakdown_cross_venue_denied(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue A")
    v2 = await _seed_venue(db, "Venue B")
    singer = await _seed_singer(db, v1.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v2.id}/hourly-breakdown",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_hourly_breakdown_returns_24_hours(client, db, jwt_encode):
    v = await _seed_venue(db, "Hour Venue")
    singer = await _seed_singer(db, v.id)
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/hourly-breakdown",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert len(items) == 24
    for h in range(24):
        assert items[h]["hour"] == h
        assert items[h]["request_count"] == 0


@pytest.mark.anyio
async def test_hourly_breakdown_counts_correctly(client, db, jwt_encode):
    v = await _seed_venue(db, "Count Venue")
    s = await _seed_singer(db, v.id)
    song = await _seed_song(db, v.id)

    await _seed_queue_request(db, v.id, s.id, song.id, requested_at=_iso(hour=9))
    await _seed_queue_request(db, v.id, s.id, song.id, requested_at=_iso(hour=9))
    await _seed_queue_request(db, v.id, s.id, song.id, requested_at=_iso(hour=21))

    token = _token_for_singer(jwt_encode, s)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/hourly-breakdown",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert items[9]["request_count"] == 2
    assert items[21]["request_count"] == 1
    for h in {9, 21}:
        continue
    other_hours = [items[h]["request_count"] for h in range(24) if h not in {9, 21}]
    assert all(c == 0 for c in other_hours)


# =====================================================================
# Singer stats
# =====================================================================

@pytest.mark.anyio
async def test_singer_stats_requires_auth(client, db):
    resp = await client.get("/v1/analytics/singer/123/stats")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_singer_stats_self_read(client, db, jwt_encode):
    v = await _seed_venue(db, "Self Venue")
    singer = await _seed_singer(db, v.id, role="singer", stage_name="Self")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/singer/{singer.id}/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["singer_id"] == singer.id
    assert data["stage_name"] == "Self"
    assert data["performances_count"] == 0
    assert data["venues_visited"] == 0
    assert data["favorite_genre"] is None


@pytest.mark.anyio
async def test_singer_stats_admin_reads_any(client, db, jwt_encode):
    v = await _seed_venue(db, "Admin Venue")
    s1 = await _seed_singer(db, v.id, role="singer")
    admin = await _seed_singer(db, v.id, role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/analytics/singer/{s1.id}/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["singer_id"] == s1.id


@pytest.mark.anyio
async def test_singer_stats_kj_reads_venue_singer(client, db, jwt_encode):
    v = await _seed_venue(db, "KJ Venue")
    s1 = await _seed_singer(db, v.id, role="singer")
    kj = await _seed_singer(db, v.id, role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.get(
        f"/v1/analytics/singer/{s1.id}/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["singer_id"] == s1.id


@pytest.mark.anyio
async def test_singer_stats_kj_denied_for_other_venue(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue A")
    v2 = await _seed_venue(db, "Venue B")
    s1 = await _seed_singer(db, v1.id, role="singer")
    kj = await _seed_singer(db, v2.id, role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.get(
        f"/v1/analytics/singer/{s1.id}/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_singer_stats_singer_denied_for_other(client, db, jwt_encode):
    v = await _seed_venue(db, "Venue A")
    s1 = await _seed_singer(db, v.id, role="singer")
    s2 = await _seed_singer(db, v.id, role="singer")
    token = _token_for_singer(jwt_encode, s1)
    resp = await client.get(
        f"/v1/analytics/singer/{s2.id}/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_singer_stats_unknown_singer(client, db, jwt_encode):
    v = await _seed_venue(db, "Venue")
    singer = await _seed_singer(db, v.id, role="admin")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/analytics/singer/{uuid.uuid4()}/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_singer_stats_with_data(client, db, jwt_encode):
    v1 = await _seed_venue(db, "V1")
    v2 = await _seed_venue(db, "V2")
    s1 = await _seed_singer(db, v1.id, "Alice", role="singer")
    song_a = await _seed_song(db, v1.id, title="Song A", genre="Pop")
    song_b = await _seed_song(db, v2.id, title="Song B", genre="Rock")

    # 2 performances in v1 (Pop)
    await _seed_queue_request(db, v1.id, s1.id, song_a.id)
    await _seed_queue_request(db, v1.id, s1.id, song_a.id)
    # 1 performance in v2 (Rock) — cross-venue visit
    await _seed_queue_request(db, v2.id, s1.id, song_b.id)

    token = _token_for_singer(jwt_encode, s1)
    resp = await client.get(
        f"/v1/analytics/singer/{s1.id}/stats",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["performances_count"] == 3
    assert data["venues_visited"] == 2
    assert data["favorite_genre"] == "Pop"


# =====================================================================
# 404 coverage for deleted/unknown venues (admin path)
# =====================================================================

@pytest.mark.anyio
async def test_leaderboard_unknown_venue_admin_gets_404(client, db, jwt_encode):
    v = await _seed_venue(db, "Exists")
    admin = await _seed_singer(db, v.id, role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/analytics/venue/{uuid.uuid4()}/leaderboard",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_song_popularity_unknown_venue_admin_gets_404(client, db, jwt_encode):
    v = await _seed_venue(db, "Exists")
    admin = await _seed_singer(db, v.id, role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/analytics/venue/{uuid.uuid4()}/song-popularity",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_hourly_breakdown_unknown_venue_admin_gets_404(client, db, jwt_encode):
    v = await _seed_venue(db, "Exists")
    admin = await _seed_singer(db, v.id, role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/analytics/venue/{uuid.uuid4()}/hourly-breakdown",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =====================================================================
# Malformed timestamp handling (defensive branches)
# =====================================================================

@pytest.mark.anyio
async def test_overview_survives_malformed_timestamps(client, db, jwt_encode):
    v = await _seed_venue(db, "Bad Timestamps")
    s = await _seed_singer(db, v.id)
    song = await _seed_song(db, v.id)

    # Seed a request with an unparseable requested_at and played_at
    from sqlalchemy import update
    qr = await _seed_queue_request(db, v.id, s.id, song.id)
    await db.execute(
        update(QueueRequest)
        .where(QueueRequest.id == qr.id)
        .values(requested_at="not-a-date", played_at="also-bad")
    )
    await db.commit()

    token = _token_for_singer(jwt_encode, s)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    # avg_wait should remain None since parsing fails
    assert data["avg_queue_wait_seconds"] is None
    # busiest_day should also remain None
    assert data["busiest_day"] is None


@pytest.mark.anyio
async def test_hourly_breakdown_survives_malformed_timestamp(client, db, jwt_encode):
    v = await _seed_venue(db, "Bad Timestamps")
    s = await _seed_singer(db, v.id)
    song = await _seed_song(db, v.id)

    from sqlalchemy import update
    qr = await _seed_queue_request(db, v.id, s.id, song.id)
    await db.execute(
        update(QueueRequest)
        .where(QueueRequest.id == qr.id)
        .values(requested_at="garbage")
    )
    await db.commit()

    token = _token_for_singer(jwt_encode, s)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/hourly-breakdown",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert all(item["request_count"] == 0 for item in items)


# =====================================================================
# Null timestamp handling (continue branches)
# =====================================================================

@pytest.mark.anyio
async def test_overview_skips_null_requested_at(client, db, jwt_encode):
    v = await _seed_venue(db, "Null Timestamps")
    s = await _seed_singer(db, v.id)
    song = await _seed_song(db, v.id)

    from sqlalchemy import update
    qr = await _seed_queue_request(db, v.id, s.id, song.id)
    await db.execute(
        update(QueueRequest)
        .where(QueueRequest.id == qr.id)
        .values(requested_at=None, played_at=None)
    )
    await db.commit()

    token = _token_for_singer(jwt_encode, s)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/overview",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["avg_queue_wait_seconds"] is None
    assert data["busiest_day"] is None
    assert data["busiest_hour"] is None


@pytest.mark.anyio
async def test_hourly_breakdown_skips_null_requested_at(client, db, jwt_encode):
    v = await _seed_venue(db, "Null Timestamps")
    s = await _seed_singer(db, v.id)
    song = await _seed_song(db, v.id)

    from sqlalchemy import update
    qr = await _seed_queue_request(db, v.id, s.id, song.id)
    await db.execute(
        update(QueueRequest)
        .where(QueueRequest.id == qr.id)
        .values(requested_at=None)
    )
    await db.commit()

    token = _token_for_singer(jwt_encode, s)
    resp = await client.get(
        f"/v1/analytics/venue/{v.id}/hourly-breakdown",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert all(item["request_count"] == 0 for item in items)
