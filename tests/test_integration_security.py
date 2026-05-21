"""Sprint 1: Security Integration Tests.

Venue isolation, role-based access control, token expiration handling.

Invoke: pytest tests/test_integration_security.py -v --integration
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Venue, Singer, Song
from app.core.security import hash_password, create_access_token

AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sec_venue(db: AsyncSession):
    vid = str(uuid.uuid4())
    v = Venue(id=vid, name="Sec Venue A", slug=f"sec-a-{vid[:8]}")
    db.add(v)
    await db.commit()
    return vid


@pytest.fixture
async def sec_venue_b(db: AsyncSession):
    vid = str(uuid.uuid4())
    v = Venue(id=vid, name="Sec Venue B", slug=f"sec-b-{vid[:8]}")
    db.add(v)
    await db.commit()
    return vid


@pytest.fixture
async def sec_singer_a(db: AsyncSession, sec_venue):
    sid = str(uuid.uuid4())
    s = Singer(
        id=sid, venue_id=sec_venue, stage_name="Singer A",
        email="singer_a@sec.example.com", password_hash=hash_password("pw"), role="singer"
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return sec_venue, s


@pytest.fixture
async def sec_singer_b(db: AsyncSession, sec_venue_b):
    sid = str(uuid.uuid4())
    s = Singer(
        id=sid, venue_id=sec_venue_b, stage_name="Singer B",
        email="singer_b@sec.example.com", password_hash=hash_password("pw"), role="singer"
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return sec_venue_b, s


@pytest.fixture
async def sec_song_a(db: AsyncSession, sec_venue):
    sid = str(uuid.uuid4())
    s = Song(id=sid, venue_id=sec_venue, title="Sec Song A", artist="Artist A",
             is_available=1, duration_ms=180_000)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return sec_venue, s


# =====================================================================
# VENUE ISOLATION
# =====================================================================

@pytest.mark.anyio
@pytest.mark.integration
async def test_security_venue_isolation_song_read(
    client, jwt_encode, sec_singer_a, sec_singer_b, sec_song_a
):
    """Singer A cannot read Venue B songs (403)."""
    venue_a, singer_a = sec_singer_a
    venue_b, singer_b = sec_singer_b

    # Singer A token trying to access Venue B list
    token_a = jwt_encode(venue_a, role="singer", user_id=singer_a.id)
    resp = await client.get(
        f"/v1/venues/{venue_b}/songs",
        headers=AUTHORIZATION(token_a),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
@pytest.mark.integration
async def test_security_venue_isolation_song_create(
    client, jwt_encode, db, sec_venue, sec_venue_b, sec_singer_a
):
    """Singer A cannot create songs in Venue B (requires admin/kj anyway)."""
    venue_a, singer_a = sec_singer_a
    token_a = jwt_encode(venue_a, role="singer", user_id=singer_a.id)

    resp = await client.post(
        f"/v1/venues/{sec_venue_b}/songs",
        headers=AUTHORIZATION(token_a),
        json={"title": "Hacked Song", "artist": "Hacker", "is_available": True},
    )
    # Either 403 (venue mismatch) or 403 (role mismatch)
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# =====================================================================
# ROLE ENFORCEMENT
# =====================================================================

@pytest.mark.anyio
@pytest.mark.integration
async def test_security_singer_cannot_access_admin_queue(
    client, jwt_encode, db, sec_venue, sec_singer_a
):
    """Singer token calling /queue/admin returns 403."""
    venue_a, singer_a = sec_singer_a
    token = jwt_encode(venue_a, role="singer", user_id=singer_a.id)
    resp = await client.get(
        f"/v1/venues/{venue_a}/queue/admin",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
@pytest.mark.integration
async def test_security_singer_can_access_public_queue(
    client, jwt_encode, db, sec_venue, sec_singer_a
):
    """Singer token calling /queue/venue (public) succeeds."""
    venue_a, singer_a = sec_singer_a
    token = jwt_encode(venue_a, role="singer", user_id=singer_a.id)
    resp = await client.get(
        f"/v1/venues/{venue_a}/queue/venue",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.anyio
@pytest.mark.integration
async def test_security_singer_can_join_queue(
    client, jwt_encode, db, sec_venue, sec_song_a, sec_singer_a
):
    """Singer can join queue with own venue token."""
    venue_a, singer_a = sec_singer_a
    _, song_a = sec_song_a
    token = jwt_encode(venue_a, role="singer", user_id=singer_a.id)
    resp = await client.post(
        f"/v1/venues/{venue_a}/queue/join",
        headers=AUTHORIZATION(token),
        json={"song_id": song_a.id},
    )
    assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.anyio
@pytest.mark.integration
async def test_security_kj_can_access_admin_queue(
    client, jwt_encode, db, sec_venue
):
    """KJ token calling /queue/admin succeeds."""
    kj_id = str(uuid.uuid4())
    kj = Singer(id=kj_id, venue_id=sec_venue, stage_name="KJ",
                email="kj@sec.example.com", password_hash="$2b$12$bogus", role="kj")
    db.add(kj)
    await db.commit()
    token = jwt_encode(sec_venue, role="kj", user_id=kj_id)
    resp = await client.get(
        f"/v1/venues/{sec_venue}/queue/admin",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.anyio
@pytest.mark.integration
async def test_security_admin_can_delete_songs(
    client, jwt_encode, db, sec_venue, sec_song_a
):
    """Admin can delete a song; singer cannot."""
    _, song = sec_song_a
    admin_id = str(uuid.uuid4())
    admin = Singer(id=admin_id, venue_id=sec_venue, stage_name="Admin",
                   email="admin@sec.example.com", password_hash="$2b$12$bogus", role="admin")
    db.add(admin)
    singer_a = Singer(id=str(uuid.uuid4()), venue_id=sec_venue, stage_name="Singer",
                      email="singer@sec.example.com", password_hash="$2b$12$bogus", role="singer")
    db.add(singer_a)
    await db.commit()

    # Admin deletes
    admin_tok = jwt_encode(sec_venue, role="admin", user_id=admin_id)
    resp = await client.delete(
        f"/v1/venues/{sec_venue}/songs/{song.id}",
        headers=AUTHORIZATION(admin_tok),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    # Singer cannot
    singer_tok = jwt_encode(sec_venue, role="singer", user_id=singer_a.id)
    # Re-add song so we can test singer rejection
    song2 = Song(id=str(uuid.uuid4()), venue_id=sec_venue, title="Song 2",
                 artist="Artist 2", is_available=1, duration_ms=180_000)
    db.add(song2)
    await db.commit()
    resp2 = await client.delete(
        f"/v1/venues/{sec_venue}/songs/{song2.id}",
        headers=AUTHORIZATION(singer_tok),
    )
    assert resp2.status_code == status.HTTP_403_FORBIDDEN


# =====================================================================
# TOKEN EXPIRATION
# =====================================================================

@pytest.mark.anyio
@pytest.mark.integration
async def test_security_expired_token_rejected(
    client, db, sec_venue, sec_singer_a
):
    """Expired token is rejected with 401 on protected endpoint (/auth/me)."""
    venue_a, singer_a = sec_singer_a
    expired_token = create_access_token(
        str(singer_a.id),
        extra_claims={"venue_id": venue_a, "role": "singer"},
        expires_delta=timedelta(seconds=-1),  # expired 1 second ago
    )
    # /auth/me requires get_current_user which checks token expiry
    resp = await client.get(
        "/v1/auth/me",
        headers=AUTHORIZATION(expired_token),
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
@pytest.mark.integration
async def test_security_invalid_token_rejected(client):
    """Malformed token is rejected with 401 on protected endpoint."""
    resp = await client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer totally.invalid.token"},
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
@pytest.mark.integration
async def test_security_missing_token_rejected_on_protected_endpoints(
    client, sec_venue
):
    """No token on protected endpoint returns 401."""
    resp = await client.get(f"/v1/venues/{sec_venue}/queue/status")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# =====================================================================
# CROSS-VENUE DATA LEAKAGE
# =====================================================================

@pytest.mark.anyio
@pytest.mark.integration
async def test_security_no_cross_venue_list_leakage(
    client, jwt_encode, db, sec_venue, sec_venue_b
):
    """Venue A list does not include Venue B items even with mismatched token."""
    # Seed a song in each venue
    sa = Song(id=str(uuid.uuid4()), venue_id=sec_venue, title="A Song",
              artist="A", is_available=1, duration_ms=180_000)
    sb = Song(id=str(uuid.uuid4()), venue_id=sec_venue_b, title="B Song",
              artist="B", is_available=1, duration_ms=180_000)
    db.add_all([sa, sb])
    await db.commit()

    # Request Venue A list with no token (public)
    resp = await client.get(f"/v1/venues/{sec_venue}/songs")
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "A Song"

    # Request with Venue A token still only shows A
    singer_a = Singer(id=str(uuid.uuid4()), venue_id=sec_venue, stage_name="A",
                      email="a@example.com", password_hash="$2b$12$bogus", role="singer")
    db.add(singer_a)
    await db.commit()
    tok = jwt_encode(sec_venue, role="singer", user_id=singer_a.id)
    resp2 = await client.get(f"/v1/venues/{sec_venue}/songs", headers=AUTHORIZATION(tok))
    assert resp2.json()["total"] == 1
    assert resp2.json()["items"][0]["title"] == "A Song"

    # Request with Venue A token against Venue B should 403
    resp3 = await client.get(f"/v1/venues/{sec_venue_b}/songs", headers=AUTHORIZATION(tok))
    assert resp3.status_code == status.HTTP_403_FORBIDDEN
