"""Tests for venue priority-bump feature flag."""
from __future__ import annotations

import uuid
import random

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import Singer, Venue, Account


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


async def _seed_venue(session, **kwargs) -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=kwargs.get("name", "Priority Bump Venue"),
        slug=kwargs.get("slug") or f"pb-{venue_id[:8]}",
        venue_code=kwargs.get("venue_code") or "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6)),
        timezone=kwargs.get("timezone", "UTC"),
        is_active=1,
        allow_priority_bump=kwargs.get("allow_priority_bump", 0),
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(session, venue_id: str, role: str = "singer") -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Test Singer",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("secret123"),
        role=role,
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


def _token_for_singer(jwt_encode, singer: Singer) -> str:
    return jwt_encode(venue_id=singer.venue_id, role=singer.role, user_id=singer.id)


@pytest.mark.anyio
async def test_venue_get_defaults_allow_priority_bump_false(client, db, jwt_encode):
    v = await _seed_venue(db, allow_priority_bump=0)
    singer = await _seed_singer(db, str(v.id), role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["allow_priority_bump"] is False


@pytest.mark.anyio
async def test_venue_lookup_returns_allow_priority_bump(client, db):
    v = await _seed_venue(db, allow_priority_bump=1)
    resp = await client.get("/v1/venues/lookup", params={"code": v.venue_code})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["allow_priority_bump"] is True


@pytest.mark.anyio
async def test_venue_join_includes_allow_priority_bump(client, db, jwt_encode):
    v = await _seed_venue(db, allow_priority_bump=1)
    # join requires an Account role token; fixture always sets venue_id.
    # The endpoint resolves via account_id, so we need an Account row.
    account_id = str(uuid.uuid4())
    account = Account(
        id=account_id,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("secret123"),
        stage_name="Test Singer",
    )
    db.add(account)
    await db.commit()
    account_token = jwt_encode(user_id=account_id, role="account", venue_id=str(v.id))
    resp = await client.post(f"/v1/venues/{v.id}/join", headers=AUTHORIZATION(account_token))
    assert resp.status_code == status.HTTP_200_OK
    # The join endpoint returns token pair, not venue; the flag is exposed on the
    # venue GET/lookup/check-in endpoints consumed by the Android queue.
    get_resp = await client.get(f"/v1/venues/{v.id}", headers=AUTHORIZATION(resp.json()["access_token"]))
    assert get_resp.status_code == status.HTTP_200_OK
    assert get_resp.json()["allow_priority_bump"] is True


@pytest.mark.anyio
async def test_venue_list_includes_allow_priority_bump(client, db, jwt_encode):
    v = await _seed_venue(db, allow_priority_bump=1)
    singer = await _seed_singer(db, str(v.id), role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get("/v1/venues", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["allow_priority_bump"] is True
