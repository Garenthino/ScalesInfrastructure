"""Singer CRUD tests — venue-scoped, RBAC, soft delete."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import Singer, Venue


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(session, name: str = "Test Venue") -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=f"test-{venue_id[:8]}",
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(
    session,
    venue_id: str,
    stage_name: str = "Test Singer",
    role: str = "singer",
    password: str | None = "secret123",
    email: str | None = None,
    real_name: str | None = None,
    pronouns: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
) -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password) if password else None,
        role=role,
        real_name=real_name,
        pronouns=pronouns,
        phone=phone,
        notes=notes,
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


async def _login_token(client, email: str, password: str = "secret123") -> str:
    resp = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == status.HTTP_200_OK
    return resp.json()["access_token"]


def _token_for_singer(jwt_encode, singer: Singer, expires=None) -> str:
    """Return a JWT where sub == singer.id so get_current_user resolves in the test DB."""
    return jwt_encode(venue_id=singer.venue_id, role=singer.role, user_id=singer.id, expires=expires)


# ---------------------------------------------------------------------------
# 1. LIST
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_singers_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/singers")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_list_singers_venue_scoped(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s1 = await _seed_singer(db, venue_id, stage_name="Alpha")
    s2 = await _seed_singer(db, venue_id, stage_name="Beta")
    other_venue = await _seed_venue(db, "Other")
    await _seed_singer(db, other_venue.id, stage_name="Gamma")

    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 3
    names = {item["stage_name"] for item in data["items"]}
    assert names == {"Alpha", "Beta", "Admin"}


@pytest.mark.anyio
async def test_list_singers_paginated(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    for i in range(5):
        await _seed_singer(db, venue_id, stage_name=f"Singer-{i}")

    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers?page=1&per_page=3",
        headers=AUTHORIZATION(token),
    )
    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 3
    assert data["total"] == 6
    assert len(data["items"]) == 3

    resp2 = await client.get(
        f"/v1/venues/{venue_id}/singers?page=2&per_page=3",
        headers=AUTHORIZATION(token),
    )
    data2 = resp2.json()
    assert data2["page"] == 2
    assert len(data2["items"]) == 3


@pytest.mark.anyio
async def test_list_singers_excludes_soft_deleted(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="Deleted")
    s.deleted_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await db.commit()

    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers",
        headers=AUTHORIZATION(token),
    )
    data = resp.json()
    ids = {item["id"] for item in data["items"]}
    assert s.id not in ids


# ---------------------------------------------------------------------------
# 2. GET SINGLE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_singer_success(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="Charlie", role="singer", password="secret123")
    token = await _login_token(client, s.email)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/{s.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["id"] == s.id
    assert data["stage_name"] == "Charlie"


@pytest.mark.anyio
async def test_get_singer_not_found(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="Charlie", role="singer")
    token = _token_for_singer(jwt_encode, s)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/{uuid.uuid4()}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_get_singer_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other = await _seed_venue(db, "Other")
    outsider = await _seed_singer(db, other.id, stage_name="Outsider")
    token = _token_for_singer(jwt_encode, outsider)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/{outsider.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 3. CREATE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_singer_admin(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {
        "stage_name": "New Singer",
        "real_name": "Alice",
        "pronouns": "she/her",
        "email": "alice@example.com",
        "phone": "+1234567890",
        "notes": "Beginner",
    }
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["stage_name"] == "New Singer"
    assert data["real_name"] == "Alice"
    assert data["pronouns"] == "she/her"
    assert data["email"] == "alice@example.com"
    assert data["phone"] == "+1234567890"
    assert data["notes"] == "Beginner"
    assert data["venue_id"] == venue_id


@pytest.mark.anyio
async def test_create_singer_kj_allowed(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    kj = await _seed_singer(db, venue_id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers",
        json={"stage_name": "KJ Singer"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.anyio
async def test_create_singer_singer_forbidden(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="Hacker", role="singer")
    token = _token_for_singer(jwt_encode, s)
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers",
        json={"stage_name": "Hacker"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_create_singer_unauthorized(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.post(
        f"/v1/venues/{venue_id}/singers",
        json={"stage_name": "No Auth"},
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# 4. UPDATE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_update_singer_self(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="Old Name", role="singer", password="secret123")
    token = await _login_token(client, s.email)
    payload = {"stage_name": "New Name", "notes": "Updated"}
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/{s.id}",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["stage_name"] == "New Name"
    assert data["notes"] == "Updated"


@pytest.mark.anyio
async def test_update_singer_by_admin(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    target = await _seed_singer(db, venue_id, stage_name="Target")
    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {"stage_name": "Admin Changed"}
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/{target.id}",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["stage_name"] == "Admin Changed"


@pytest.mark.anyio
async def test_update_singer_by_kj_allowed(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    target = await _seed_singer(db, venue_id, stage_name="Target")
    kj = await _seed_singer(db, venue_id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    payload = {"notes": "KJ note"}
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/{target.id}",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.anyio
async def test_update_singer_other_singer_forbidden(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    victim = await _seed_singer(db, venue_id, stage_name="Victim")
    attacker = await _seed_singer(db, venue_id, stage_name="Attacker", role="singer")
    token = _token_for_singer(jwt_encode, attacker)
    payload = {"stage_name": "Hacked"}
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/{victim.id}",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_update_singer_not_found(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.put(
        f"/v1/venues/{venue_id}/singers/{uuid.uuid4()}",
        json={"stage_name": "Ghost"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# 5. DELETE (soft)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_delete_singer_admin(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="DeleteMe")
    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/{s.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    # soft-deleted -> invisible
    get_resp = await client.get(
        f"/v1/venues/{venue_id}/singers/{s.id}",
        headers=AUTHORIZATION(token),
    )
    assert get_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_delete_singer_kj_allowed(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="DeleteMe")
    kj = await _seed_singer(db, venue_id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/{s.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.anyio
async def test_delete_singer_singer_forbidden(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="DeleteMe")
    attacker = await _seed_singer(db, venue_id, stage_name="Attacker", role="singer")
    token = _token_for_singer(jwt_encode, attacker)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/{s.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_delete_singer_not_found(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    admin = await _seed_singer(db, venue_id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/{uuid.uuid4()}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# 6. SPRINT 0 STUBS (removed — implemented in test_singer_portal.py)
# ---------------------------------------------------------------------------



@pytest.mark.anyio
async def test_delete_singer_owner_allowed(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    s = await _seed_singer(db, venue_id, stage_name="OwnerDeleteMe")
    # Owner token uses account-style claims (different sub) with the same venue.
    owner_id = str(uuid.uuid4())
    token = jwt_encode(venue_id, role="owner", user_id=owner_id)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/{s.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT
