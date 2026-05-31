"""Tests for singer follow endpoints."""
from __future__ import annotations

import random
import uuid

import pytest
from fastapi import status
from sqlalchemy import select

from app.core.security import hash_password
from app.models import Singer, Venue, SingerFollow


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(session, name: str = "Follow Test Venue") -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=f"follow-{venue_id[:8]}",
        venue_code="".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6)),
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(session, venue_id: str, stage_name: str = "Test Singer") -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("secret123"),
        role="singer",
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


async def _seed_follow(session, venue_id: str, follower_id: str, followee_id: str) -> SingerFollow:
    follow = SingerFollow(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        follower_id=follower_id,
        followee_id=followee_id,
        created_at="2026-01-01T00:00:00Z",
        deleted_at=None,
    )
    session.add(follow)
    await session.commit()
    await session.refresh(follow)
    return follow


def _token_for_singer(singer: Singer, venue_id: str | None = None) -> str:
    from datetime import datetime, timezone
    from jose import jwt
    from app.core.config import settings
    now = datetime.now(timezone.utc)
    payload = {
        "sub": singer.id,
        "venue_id": venue_id or singer.venue_id,
        "role": singer.role,
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_follow_success(client, db):
    """POST follow/{id} creates a follow relationship."""
    venue = await _seed_venue(db)
    follower = await _seed_singer(db, venue.id, "Follower")
    followee = await _seed_singer(db, venue.id, "Followee")
    token = _token_for_singer(follower)

    response = await client.post(
        f"/v1/venues/{venue.id}/singers/follow/{followee.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["followee_id"] == followee.id
    assert data["follower_id"] == follower.id
    assert data["followee_name"] == "Followee"
    assert "id" in data
    assert "created_at" in data

    # Verify DB state
    result = await db.execute(
        select(SingerFollow).where(
            SingerFollow.follower_id == follower.id,
            SingerFollow.venue_id == venue.id,
            SingerFollow.followee_id == followee.id,
            SingerFollow.deleted_at.is_(None),
        )
    )
    follow = result.scalar_one_or_none()
    assert follow is not None


@pytest.mark.asyncio
async def test_follow_idempotent(client, db):
    """POST follow twice with same target is idempotent."""
    venue = await _seed_venue(db)
    follower = await _seed_singer(db, venue.id, "Follower")
    followee = await _seed_singer(db, venue.id, "Followee")
    token = _token_for_singer(follower)

    r1 = await client.post(
        f"/v1/venues/{venue.id}/singers/follow/{followee.id}",
        headers=AUTHORIZATION(token),
    )
    assert r1.status_code == status.HTTP_201_CREATED
    follow_id = r1.json()["id"]

    r2 = await client.post(
        f"/v1/venues/{venue.id}/singers/follow/{followee.id}",
        headers=AUTHORIZATION(token),
    )
    assert r2.status_code == status.HTTP_201_CREATED
    assert r2.json()["id"] == follow_id

    result = await db.execute(
        select(SingerFollow).where(
            SingerFollow.follower_id == follower.id,
            SingerFollow.venue_id == venue.id,
            SingerFollow.followee_id == followee.id,
            SingerFollow.deleted_at.is_(None),
        )
    )
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_self_follow_denied(client, db):
    """POST follow with own singer id returns 400."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id, "Solo")
    token = _token_for_singer(singer)

    response = await client.post(
        f"/v1/venues/{venue.id}/singers/follow/{singer.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Cannot follow yourself" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unfollow_success(client, db):
    """DELETE follow/{id} removes a follow."""
    venue = await _seed_venue(db)
    follower = await _seed_singer(db, venue.id, "Follower")
    followee = await _seed_singer(db, venue.id, "Followee")
    await _seed_follow(db, venue.id, follower.id, followee.id)
    token = _token_for_singer(follower)

    response = await client.delete(
        f"/v1/venues/{venue.id}/singers/follow/{followee.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    result = await db.execute(
        select(SingerFollow).where(
            SingerFollow.follower_id == follower.id,
            SingerFollow.venue_id == venue.id,
            SingerFollow.followee_id == followee.id,
            SingerFollow.deleted_at.is_(None),
        )
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_unfollow_not_found(client, db):
    """DELETE follow/{id} when no follow exists returns 404."""
    venue = await _seed_venue(db)
    follower = await _seed_singer(db, venue.id, "Follower")
    followee = await _seed_singer(db, venue.id, "Followee")
    token = _token_for_singer(follower)

    response = await client.delete(
        f"/v1/venues/{venue.id}/singers/follow/{followee.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Follow relationship not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_follow_status(client, db):
    """GET follow/status/{id} returns counts and is_following state."""
    venue = await _seed_venue(db)
    follower = await _seed_singer(db, venue.id, "Follower")
    followee = await _seed_singer(db, venue.id, "Followee")
    token = _token_for_singer(follower)

    # Before following
    r1 = await client.get(
        f"/v1/venues/{venue.id}/singers/follow/status/{followee.id}",
        headers=AUTHORIZATION(token),
    )
    assert r1.status_code == status.HTTP_200_OK
    d1 = r1.json()
    assert d1["is_following"] is False
    assert d1["follower_count"] == 0
    assert d1["following_count"] == 0

    # After following
    await _seed_follow(db, venue.id, follower.id, followee.id)
    r2 = await client.get(
        f"/v1/venues/{venue.id}/singers/follow/status/{followee.id}",
        headers=AUTHORIZATION(token),
    )
    assert r2.status_code == status.HTTP_200_OK
    d2 = r2.json()
    assert d2["is_following"] is True
    assert d2["follower_count"] == 1
    assert d2["following_count"] == 0  # followee is not following anyone back
    assert "created_at" in d2


@pytest.mark.asyncio
async def test_cross_venue_denied(client, db):
    """Follow endpoints reject cross-venue access."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer_a = await _seed_singer(db, venue_a.id, "Singer A")
    singer_b = await _seed_singer(db, venue_b.id, "Singer B")
    token = _token_for_singer(singer_a)

    response = await client.post(
        f"/v1/venues/{venue_b.id}/singers/follow/{singer_b.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Venue access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_follow_nonexistent_singer(client, db):
    """POST follow with unknown followee returns 404."""
    venue = await _seed_venue(db)
    follower = await _seed_singer(db, venue.id, "Follower")
    token = _token_for_singer(follower)

    response = await client.post(
        f"/v1/venues/{venue.id}/singers/follow/{uuid.uuid4()}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Singer not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_following(client, db):
    """GET following returns list of followed singers."""
    venue = await _seed_venue(db)
    follower = await _seed_singer(db, venue.id, "Follower")
    followee1 = await _seed_singer(db, venue.id, "Followee 1")
    followee2 = await _seed_singer(db, venue.id, "Followee 2")
    await _seed_follow(db, venue.id, follower.id, followee1.id)
    await _seed_follow(db, venue.id, follower.id, followee2.id)
    token = _token_for_singer(follower)

    response = await client.get(
        f"/v1/venues/{venue.id}/singers/following",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 2
    followee_ids = {item["followee_id"] for item in data}
    assert followee_ids == {followee1.id, followee2.id}
    for item in data:
        assert "followee_name" in item
        assert item["follower_id"] == follower.id


@pytest.mark.asyncio
async def test_list_followers(client, db):
    """GET followers returns list of singers following the current user."""
    venue = await _seed_venue(db)
    followee = await _seed_singer(db, venue.id, "Star")
    fan1 = await _seed_singer(db, venue.id, "Fan 1")
    fan2 = await _seed_singer(db, venue.id, "Fan 2")
    await _seed_follow(db, venue.id, fan1.id, followee.id)
    await _seed_follow(db, venue.id, fan2.id, followee.id)
    token = _token_for_singer(followee)

    response = await client.get(
        f"/v1/venues/{venue.id}/singers/followers",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 2
    follower_ids = {item["follower_id"] for item in data}
    assert follower_ids == {fan1.id, fan2.id}
    for item in data:
        # followee_name in list_followers is the follower name for the join
        assert "followee_name" in item
        assert item["followee_id"] == followee.id


@pytest.mark.asyncio
async def test_list_following_cross_venue_denied(client, db):
    """GET following with wrong venue returns 403."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer = await _seed_singer(db, venue_a.id, "Singer")
    token = _token_for_singer(singer)

    response = await client.get(
        f"/v1/venues/{venue_b.id}/singers/following",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Venue access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_followers_cross_venue_denied(client, db):
    """GET followers with wrong venue returns 403."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer = await _seed_singer(db, venue_a.id, "Singer")
    token = _token_for_singer(singer)

    response = await client.get(
        f"/v1/venues/{venue_b.id}/singers/followers",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Venue access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unfollow_cross_venue_denied(client, db):
    """DELETE follow/{id} with wrong venue returns 403."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer_a = await _seed_singer(db, venue_a.id, "Singer A")
    singer_b = await _seed_singer(db, venue_b.id, "Singer B")
    token = _token_for_singer(singer_a)

    response = await client.delete(
        f"/v1/venues/{venue_b.id}/singers/follow/{singer_b.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Venue access denied" in response.json()["detail"]


@pytest.mark.asyncio
async def test_follow_status_cross_venue_denied(client, db):
    """GET follow/status/{id} with wrong venue returns 403."""
    venue_a = await _seed_venue(db, name="Venue A")
    venue_b = await _seed_venue(db, name="Venue B")
    singer_a = await _seed_singer(db, venue_a.id, "Singer A")
    singer_b = await _seed_singer(db, venue_b.id, "Singer B")
    token = _token_for_singer(singer_a)

    response = await client.get(
        f"/v1/venues/{venue_b.id}/singers/follow/status/{singer_b.id}",
        headers=AUTHORIZATION(token),
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Venue access denied" in response.json()["detail"]
