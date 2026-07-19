"""Venue CRUD + multi-tenancy tests — full coverage for venues router."""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import Singer, Venue, Song, QueueRequest


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(session, name: str = "Test Venue", **kwargs) -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=kwargs.get("slug") or f"test-{venue_id[:8]}",
        venue_code=kwargs.get("venue_code") or "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6)),
        address=kwargs.get("address"),
        contact_json=kwargs.get("contact_json"),
        timezone=kwargs.get("timezone", "UTC"),
        branding_json=kwargs.get("branding_json"),
        is_active=kwargs.get("is_active", 1),
        allow_priority_bump=kwargs.get("allow_priority_bump", 0),
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
) -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password) if password else None,
        role=role,
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


def _token_for_singer(jwt_encode, singer: Singer, expires=None) -> str:
    return jwt_encode(venue_id=singer.venue_id, role=singer.role, user_id=singer.id, expires=expires)


_NOW = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# =====================================================================
# 1. LIST
# =====================================================================

@pytest.mark.anyio
async def test_list_venues_requires_auth(client, db):
    resp = await client.get("/v1/venues")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_list_venues_admin_sees_all(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue One")
    v2 = await _seed_venue(db, "Venue Two")
    admin = await _seed_singer(db, v1.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get("/v1/venues", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] >= 2
    names = {item["name"] for item in data["items"]}
    assert "Venue One" in names
    assert "Venue Two" in names


@pytest.mark.anyio
async def test_list_venues_kj_sees_own_only(client, db, jwt_encode):
    own = await _seed_venue(db, "Own Venue")
    other = await _seed_venue(db, "Other Venue")
    kj = await _seed_singer(db, own.id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.get("/v1/venues", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == own.id


@pytest.mark.anyio
async def test_list_venues_singer_sees_own_only(client, db, jwt_encode):
    own = await _seed_venue(db, "Own Venue")
    other = await _seed_venue(db, "Other Venue")
    singer = await _seed_singer(db, own.id, stage_name="Singer", role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get("/v1/venues", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == own.id


@pytest.mark.anyio
async def test_list_venues_pagination(client, db, jwt_encode):
    for i in range(5):
        await _seed_venue(db, f"Paginated Venue {i}")
    admin = await _seed_singer(db, "placeholder", stage_name="Admin", role="admin")
    # Create a real venue for the admin
    admin_venue = await _seed_venue(db, "Admin Venue")
    admin.venue_id = admin_venue.id
    await db.commit()
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get("/v1/venues?page=1&per_page=3", headers=AUTHORIZATION(token))
    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 3
    assert len(data["items"]) == 3


@pytest.mark.anyio
async def test_list_venues_excludes_soft_deleted(client, db, jwt_encode):
    v = await _seed_venue(db, "Deleted Venue")
    v.deleted_at = _NOW()
    await db.commit()
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get("/v1/venues", headers=AUTHORIZATION(token))
    data = resp.json()
    ids = {item["id"] for item in data["items"]}
    assert v.id not in ids


# =====================================================================
# 2. CREATE
# =====================================================================

@pytest.mark.anyio
async def test_create_venue_admin(client, db, jwt_encode):
    admin = await _seed_singer(db, "placeholder", stage_name="Admin", role="admin")
    admin_venue = await _seed_venue(db, "Admin Venue")
    admin.venue_id = admin_venue.id
    await db.commit()
    token = _token_for_singer(jwt_encode, admin)
    payload = {
        "name": "New Venue",
        "slug": "new-venue",
        "timezone": "America/New_York",
    }
    resp = await client.post("/v1/venues", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["name"] == "New Venue"
    assert data["slug"] == "new-venue"
    assert data["timezone"] == "America/New_York"
    assert data["is_active"] is True
    assert data["stats"]["total_songs"] == 0
    assert data["stats"]["total_singers"] == 0


@pytest.mark.anyio
async def test_create_venue_kj_forbidden(client, db, jwt_encode):
    v = await _seed_venue(db, "KJ Venue")
    kj = await _seed_singer(db, v.id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    payload = {"name": "Hacker Venue", "slug": "hacker-venue"}
    resp = await client.post("/v1/venues", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_create_venue_singer_forbidden(client, db, jwt_encode):
    v = await _seed_venue(db, "Singer Venue")
    singer = await _seed_singer(db, v.id, stage_name="Singer", role="singer")
    token = _token_for_singer(jwt_encode, singer)
    payload = {"name": "Hacker Venue", "slug": "hacker-venue"}
    resp = await client.post("/v1/venues", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_create_venue_duplicate_slug(client, db, jwt_encode):
    v = await _seed_venue(db, "Existing Venue", slug="unique-slug")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {"name": "Another Venue", "slug": "unique-slug"}
    resp = await client.post("/v1/venues", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_409_CONFLICT


@pytest.mark.anyio
async def test_create_venue_unauthorized(client, db):
    payload = {"name": "No Auth", "slug": "no-auth"}
    resp = await client.post("/v1/venues", json=payload)
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_create_venue_with_full_payload(client, db, jwt_encode):
    admin = await _seed_singer(db, "placeholder", stage_name="Admin", role="admin")
    admin_venue = await _seed_venue(db, "Admin Venue")
    admin.venue_id = admin_venue.id
    await db.commit()
    token = _token_for_singer(jwt_encode, admin)
    payload = {
        "name": "Full Venue",
        "slug": "full-venue",
        "address": {"street": "123 Main St", "city": "Springfield", "state": "IL", "zip": "62701", "country": "USA"},
        "contact": {"phone": "+1-555-1234", "email": "venue@example.com"},
        "timezone": "America/Chicago",
        "branding": {"primary_color": "#FF5733", "secondary_color": "#33FF57", "logo_url": "https://example.com/logo.png", "favicon_url": "https://example.com/favicon.ico"},
    }
    resp = await client.post("/v1/venues", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["address"]["street"] == "123 Main St"
    assert data["address"]["city"] == "Springfield"
    assert data["contact"]["phone"] == "+1-555-1234"
    assert data["contact"]["email"] == "venue@example.com"
    assert data["branding"]["primary_color"] == "#FF5733"
    assert data["branding"]["logo_url"] == "https://example.com/logo.png"


# =====================================================================
# 3. GET
# =====================================================================

@pytest.mark.anyio
async def test_get_venue_admin(client, db, jwt_encode):
    v = await _seed_venue(db, "Target Venue")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["id"] == v.id
    assert data["name"] == "Target Venue"
    assert "stats" in data


@pytest.mark.anyio
async def test_get_venue_kj_own_venue(client, db, jwt_encode):
    v = await _seed_venue(db, "KJ Venue")
    kj = await _seed_singer(db, v.id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.get(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["id"] == v.id


@pytest.mark.anyio
async def test_get_venue_singer_own_venue(client, db, jwt_encode):
    v = await _seed_venue(db, "Singer Venue")
    singer = await _seed_singer(db, v.id, stage_name="Singer", role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["id"] == v.id


@pytest.mark.anyio
async def test_get_venue_wrong_venue_forbidden(client, db, jwt_encode):
    own = await _seed_venue(db, "Own Venue")
    other = await _seed_venue(db, "Other Venue")
    singer = await _seed_singer(db, own.id, stage_name="Singer", role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(f"/v1/venues/{other.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_get_venue_not_found(client, db, jwt_encode):
    v = await _seed_venue(db, "Some Venue")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(f"/v1/venues/{uuid.uuid4()}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_get_venue_stats_reflect_content(client, db, jwt_encode):
    v = await _seed_venue(db, "Stats Venue")
    # Add songs and singers
    s1 = Song(venue_id=v.id, title="Song 1", artist="Artist 1", is_available=1, is_active=1)
    s2 = Song(venue_id=v.id, title="Song 2", artist="Artist 2", is_available=1, is_active=1)
    singer1 = await _seed_singer(db, v.id, stage_name="Singer1")
    singer2 = await _seed_singer(db, v.id, stage_name="Singer2")
    db.add(s1)
    db.add(s2)
    await db.commit()

    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    data = resp.json()
    assert data["stats"]["total_songs"] == 2
    assert data["stats"]["total_singers"] == 3  # 2 singers + admin
    assert data["stats"]["queue_depth"] == 0


@pytest.mark.anyio
async def test_get_venue_stats_queue_depth(client, db, jwt_encode):
    v = await _seed_venue(db, "Queue Stats Venue")
    singer = await _seed_singer(db, v.id, stage_name="Singer")
    song = Song(venue_id=v.id, title="Song", artist="Artist", is_available=1, is_active=1)
    db.add(song)
    await db.commit()
    await db.refresh(song)

    # Add pending queue request
    q = QueueRequest(
        venue_id=v.id,
        singer_id=singer.id,
        song_id=song.id,
        status="pending",
        requested_at="2024-01-01T00:00:00Z",
    )
    db.add(q)
    await db.commit()

    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    data = resp.json()
    assert data["stats"]["queue_depth"] == 1


# =====================================================================
# 4. UPDATE
# =====================================================================

@pytest.mark.anyio
async def test_update_venue_admin(client, db, jwt_encode):
    v = await _seed_venue(db, "Old Name")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {"name": "Updated Name"}
    resp = await client.put(f"/v1/venues/{v.id}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["name"] == "Updated Name"


@pytest.mark.anyio
async def test_update_venue_kj_own_venue(client, db, jwt_encode):
    v = await _seed_venue(db, "KJ Venue")
    kj = await _seed_singer(db, v.id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    payload = {"name": "KJ Updated"}
    resp = await client.put(f"/v1/venues/{v.id}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["name"] == "KJ Updated"


@pytest.mark.anyio
async def test_update_venue_kj_other_venue_forbidden(client, db, jwt_encode):
    own = await _seed_venue(db, "Own Venue")
    other = await _seed_venue(db, "Other Venue")
    kj = await _seed_singer(db, own.id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    payload = {"name": "Hacked"}
    resp = await client.put(f"/v1/venues/{other.id}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_update_venue_singer_forbidden(client, db, jwt_encode):
    v = await _seed_venue(db, "Singer Venue")
    singer = await _seed_singer(db, v.id, stage_name="Singer", role="singer")
    token = _token_for_singer(jwt_encode, singer)
    payload = {"name": "Hacked"}
    resp = await client.put(f"/v1/venues/{v.id}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_update_venue_duplicate_slug(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue One", slug="slug-one")
    v2 = await _seed_venue(db, "Venue Two", slug="slug-two")
    admin = await _seed_singer(db, v1.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {"slug": "slug-two"}
    resp = await client.put(f"/v1/venues/{v1.id}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_409_CONFLICT


@pytest.mark.anyio
async def test_update_venue_not_found(client, db, jwt_encode):
    v = await _seed_venue(db, "Some Venue")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {"name": "Ghost"}
    resp = await client.put(f"/v1/venues/{uuid.uuid4()}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_update_venue_nested_fields(client, db, jwt_encode):
    v = await _seed_venue(db, "Nested Venue")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {
        "address": {"street": "456 Oak Ave", "city": "Portland"},
        "contact": {"phone": "+1-555-9999"},
        "branding": {"primary_color": "#000000"},
    }
    resp = await client.put(f"/v1/venues/{v.id}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["address"]["street"] == "456 Oak Ave"
    assert data["address"]["city"] == "Portland"
    assert data["contact"]["phone"] == "+1-555-9999"
    assert data["branding"]["primary_color"] == "#000000"


@pytest.mark.anyio
async def test_update_venue_partial_unset_fields_preserved(client, db, jwt_encode):
    v = await _seed_venue(db, "Partial Venue", timezone="America/Los_Angeles")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {"name": "Partially Updated"}
    resp = await client.put(f"/v1/venues/{v.id}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["name"] == "Partially Updated"
    assert data["timezone"] == "America/Los_Angeles"


# =====================================================================
# 5. DELETE
# =====================================================================

@pytest.mark.anyio
async def test_delete_venue_admin(client, db, jwt_encode):
    v = await _seed_venue(db, "Delete Me")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.delete(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    # Verify soft delete
    get_resp = await client.get(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert get_resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_delete_venue_kj_forbidden(client, db, jwt_encode):
    v = await _seed_venue(db, "KJ Venue")
    kj = await _seed_singer(db, v.id, stage_name="KJ", role="kj")
    token = _token_for_singer(jwt_encode, kj)
    resp = await client.delete(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_delete_venue_singer_forbidden(client, db, jwt_encode):
    v = await _seed_venue(db, "Singer Venue")
    singer = await _seed_singer(db, v.id, stage_name="Singer", role="singer")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.delete(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_delete_venue_not_found(client, db, jwt_encode):
    v = await _seed_venue(db, "Some Venue")
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.delete(f"/v1/venues/{uuid.uuid4()}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_delete_venue_already_deleted(client, db, jwt_encode):
    v = await _seed_venue(db, "Already Deleted")
    v.deleted_at = _NOW()
    await db.commit()
    admin = await _seed_singer(db, v.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.delete(f"/v1/venues/{v.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =====================================================================
# 6. CROSS-VENUE ISOLATION
# =====================================================================

@pytest.mark.anyio
async def test_admin_can_access_any_venue(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue A")
    v2 = await _seed_venue(db, "Venue B")
    admin = await _seed_singer(db, v1.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.get(f"/v1/venues/{v2.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["id"] == v2.id


@pytest.mark.anyio
async def test_admin_can_update_any_venue(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue A")
    v2 = await _seed_venue(db, "Venue B")
    admin = await _seed_singer(db, v1.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    payload = {"name": "Venue B Updated"}
    resp = await client.put(f"/v1/venues/{v2.id}", json=payload, headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["name"] == "Venue B Updated"


@pytest.mark.anyio
async def test_admin_can_delete_any_venue(client, db, jwt_encode):
    v1 = await _seed_venue(db, "Venue A")
    v2 = await _seed_venue(db, "Venue B")
    admin = await _seed_singer(db, v1.id, stage_name="Admin", role="admin")
    token = _token_for_singer(jwt_encode, admin)
    resp = await client.delete(f"/v1/venues/{v2.id}", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_204_NO_CONTENT
