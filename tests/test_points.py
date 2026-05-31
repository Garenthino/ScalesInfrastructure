"""Points engine, leaderboard, and achievements tests.

Covers:
- PointsLedger writes on check-in, request, perform
- Leaderboard by period (week|month|alltime)
- Achievements: first_song, iron_lungs, regular, big_spender
- Tip endpoint
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import (
    Venue, Singer, Song, QueueRequest, CheckInSession,
    PointsLedger, SingerAchievement,
)
from app.core.db import get_db as _orig_get_db


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(session) -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="Points Venue", slug=f"points-{venue_id[:8]}", venue_code="POINTS01")
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(session, venue_id: str, stage_name: str = "Singer", total_points: int = 0) -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()), venue_id=venue_id, stage_name=stage_name,
        role="singer", total_points=total_points,
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


async def _seed_song(session, venue_id: str, title: str = "Test Song") -> Song:
    song = Song(
        id=str(uuid.uuid4()), venue_id=venue_id, title=title, artist="Artist",
        is_available=1, is_active=1,
    )
    session.add(song)
    await session.commit()
    await session.refresh(song)
    return song


async def _seed_checkin(session, venue_id: str, singer_id: str) -> CheckInSession:
    sess = CheckInSession(
        id=str(uuid.uuid4()), venue_id=venue_id, singer_id=singer_id,
        checked_in_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    session.add(sess)
    await session.commit()
    return sess


async def _seed_queue_request(
    session, venue_id: str, singer_id: str, song_id: str,
    status: str = "completed",
) -> QueueRequest:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    req = QueueRequest(
        id=str(uuid.uuid4()), venue_id=venue_id, singer_id=singer_id, song_id=song_id,
        status=status, requested_at=now, played_at=now if status == "completed" else None,
    )
    session.add(req)
    await session.commit()
    return req


def _token(singer: Singer) -> str:
    import jose.jwt as jwt
    from app.core.config import settings
    now = datetime.now(timezone.utc)
    payload = {
        "sub": singer.id,
        "venue_id": singer.venue_id,
        "role": singer.role,
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------------------
# 1. Check-in points
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_checkin_awards_points(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    token = jwt_encode(venue_id=venue.id, role="singer", user_id=singer.id)

    resp = await client.post(
        f"/v1/venues/{venue.id}/singers/checkin",
        json={},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    # points should be bumped to 10
    assert data["total_points"] == 10

    # Ledger row
    resp2 = await client.get(
        f"/v1/venues/{venue.id}/singers/me/points",
        headers=AUTHORIZATION(token),
    )
    assert resp2.status_code == 200
    ledger = resp2.json()
    assert ledger["total"] == 1
    assert ledger["items"][0]["amount"] == 10
    assert ledger["items"][0]["reference_type"] == "checkin"


# ---------------------------------------------------------------------------
# 2. Request points
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_request_awards_points(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id)
    token = jwt_encode(venue_id=venue.id, role="singer", user_id=singer.id)

    resp = await client.post(
        f"/v1/venues/{venue.id}/queue/join",
        json={"song_id": song.id, "notes": "Test"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()

    # points now 5
    singer_db = (await db.execute(select(Singer).where(Singer.id == singer.id))).scalar_one()
    assert singer_db.total_points == 5

    resp2 = await client.get(
        f"/v1/venues/{venue.id}/singers/me/points",
        headers=AUTHORIZATION(token),
    )
    assert resp2.json()["items"][0]["amount"] == 5


# ---------------------------------------------------------------------------
# 3. Perform points (via queue_admin complete)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_complete_awards_perform_points(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id)
    token = jwt_encode(venue_id=venue.id, role="kj", user_id=singer.id)

    q = await _seed_queue_request(db, venue.id, singer.id, song.id, status="approved")

    # KJ complete
    resp = await client.post(
        f"/v1/venues/{venue.id}/queue/admin/{q.id}/complete",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK

    singer_db = (await db.execute(select(Singer).where(Singer.id == singer.id))).scalar_one()
    # 25 perform points
    assert singer_db.total_points == 25


# ---------------------------------------------------------------------------
# 4. Tip endpoint
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_tip_awards_points(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer_a = await _seed_singer(db, venue.id, stage_name="Tipper")
    singer_b = await _seed_singer(db, venue.id, stage_name="Tipped")
    token = jwt_encode(venue_id=venue.id, role="singer", user_id=singer_a.id)

    resp = await client.post(
        f"/v1/venues/{venue.id}/singers/{singer_b.id}/tip",
        json={"amount_cents": 500, "message": "Great performance!"},
        headers=AUTHORIZATION(token),
    )
    # tip currently returns 204
    # Let's see actual code — tip endpoint in singers.py
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    singer_b_db = (await db.execute(select(Singer).where(Singer.id == singer_b.id))).scalar_one()
    assert singer_b_db.total_points == 500


# ---------------------------------------------------------------------------
# 5. Leaderboard
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_leaderboard_alltime(client, db, jwt_encode):
    venue = await _seed_venue(db)
    s1 = await _seed_singer(db, venue.id, "Alice", 100)
    s2 = await _seed_singer(db, venue.id, "Bob", 50)

    # seed some completed songs so songs_sung > 0
    song = await _seed_song(db, venue.id)
    for _ in range(2):
        await _seed_queue_request(db, venue.id, s1.id, song.id, "completed")
    await _seed_queue_request(db, venue.id, s2.id, song.id, "completed")

    resp = await client.get(f"/v1/venues/{venue.id}/leaderboard?period=alltime")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["items"][0]["singer_id"] == s1.id
    assert data["items"][0]["score"] == 100
    assert data["items"][0]["songs_sung"] == 2


@pytest.mark.anyio
async def test_leaderboard_week_month_differentiation(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id, "WeekSinger", total_points=0)
    song = await _seed_song(db, venue.id)

    # Create a point entry older than 7 days
    old_time = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.add(PointsLedger(
        venue_id=venue.id, singer_id=singer.id, amount=100, reason="Old",
        reference_type="checkin", created_at=old_time,
    ))

    # Create a point entry within last 7 days
    new_time = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.add(PointsLedger(
        venue_id=venue.id, singer_id=singer.id, amount=50, reason="Recent",
        reference_type="checkin", created_at=new_time,
    ))
    await db.commit()

    singer.total_points = 150
    await db.commit()

    # Alltime: 150
    r1 = await client.get(f"/v1/venues/{venue.id}/leaderboard?period=alltime")
    assert r1.json()["items"][0]["score"] == 150

    # Week: only 50
    r2 = await client.get(f"/v1/venues/{venue.id}/leaderboard?period=week")
    assert r2.json()["items"][0]["score"] == 50

    # Month: also 150 (both entries < 30 days)
    r3 = await client.get(f"/v1/venues/{venue.id}/leaderboard?period=month")
    assert r3.json()["items"][0]["score"] == 150


# ---------------------------------------------------------------------------
# 6. Achievements
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_achievements_all_locked_initially(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    token = jwt_encode(venue_id=venue.id, role="singer", user_id=singer.id)

    resp = await client.get(
        f"/v1/venues/{venue.id}/singers/me/achievements",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    # 4 achievements
    assert len(data) == 4
    for a in data:
        assert a["unlocked"] is False
        assert a["progress"] == 0


@pytest.mark.anyio
async def test_achievement_first_song_unlocks(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id)
    token = jwt_encode(venue_id=venue.id, role="singer", user_id=singer.id)

    # Complete a queue request
    await _seed_queue_request(db, venue.id, singer.id, song.id, "completed")

    resp = await client.get(
        f"/v1/venues/{venue.id}/singers/me/achievements",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    first_song = next(a for a in data if a["achievement_key"] == "first_song")
    assert first_song["unlocked"] is True
    assert first_song["progress"] == 1
    assert first_song["unlocked_at"] is not None


@pytest.mark.anyio
async def test_achievement_iron_lungs_progress(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    song = await _seed_song(db, venue.id)
    token = jwt_encode(venue_id=venue.id, role="singer", user_id=singer.id)

    for _ in range(7):
        await _seed_queue_request(db, venue.id, singer.id, song.id, "completed")

    resp = await client.get(
        f"/v1/venues/{venue.id}/singers/me/achievements",
        headers=AUTHORIZATION(token),
    )
    data = resp.json()
    iron = next(a for a in data if a["achievement_key"] == "iron_lungs")
    assert iron["progress"] == 7
    assert iron["unlocked"] is False
    assert iron["target"] == 10


@pytest.mark.anyio
async def test_achievement_regular_unlocks_after_checkins(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    token = jwt_encode(venue_id=venue.id, role="singer", user_id=singer.id)

    for _ in range(5):
        await _seed_checkin(db, venue.id, singer.id)

    resp = await client.get(
        f"/v1/venues/{venue.id}/singers/me/achievements",
        headers=AUTHORIZATION(token),
    )
    data = resp.json()
    regular = next(a for a in data if a["achievement_key"] == "regular")
    assert regular["progress"] == 5
    assert regular["unlocked"] is True
    assert regular["unlocked_at"] is not None


@pytest.mark.anyio
async def test_achievement_big_spender_unlocks_after_tips(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    token = jwt_encode(venue_id=venue.id, role="singer", user_id=singer.id)

    # Create tip ledger entries totaling 5000 cents ($50)
    for i in range(5):
        db.add(PointsLedger(
            venue_id=venue.id, singer_id=singer.id,
            amount=1000, reason="Tip", reference_type="tip",
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ))
    await db.commit()

    resp = await client.get(
        f"/v1/venues/{venue.id}/singers/me/achievements",
        headers=AUTHORIZATION(token),
    )
    data = resp.json()
    bs = next(a for a in data if a["achievement_key"] == "big_spender")
    assert bs["progress"] == 5000
    assert bs["unlocked"] is True
    assert bs["target"] == 5000
