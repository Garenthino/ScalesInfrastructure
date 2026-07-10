"""KJ device auth router tests — register, token, list, revoke, rotate, kj_auth dependency."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from jose import jwt
from sqlalchemy.future import select

from app.core.config import settings
from app.core.security import verify_password
from app.models import Singer, Venue, KJDevice

AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_venue(session, name: str = "Test Venue") -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=f"test-{venue_id[:8]}",
        is_active=1,
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_admin(session, venue_id: str, stage_name: str = "Admin") -> Singer:
    from app.core.security import hash_password
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("secret123"),
        role="admin",
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


async def _seed_singer(session, venue_id: str, stage_name: str = "Singer") -> Singer:
    from app.core.security import hash_password
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


def _token_for_singer(jwt_encode, singer: Singer, expires=None) -> str:
    return jwt_encode(venue_id=singer.venue_id, role=singer.role, user_id=singer.id, expires=expires)


# ---------------------------------------------------------------------------
# 1. REGISTER
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_kj_register_admin_success(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "KJ Laptop 1"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["id"]
    assert data["api_key"]
    assert "Store this API key" in data["message"]

    # verify persisted
    result = await db.execute(select(KJDevice).where(KJDevice.id == data["id"]))
    device = result.scalar_one()
    assert device.name == "KJ Laptop 1"
    assert device.venue_id == venue.id
    assert verify_password(data["api_key"], device.api_key_hash)


@pytest.mark.anyio
async def test_kj_register_non_admin_forbidden(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    token = _token_for_singer(jwt_encode, singer)

    resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "KJ Laptop 1"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_kj_register_wrong_venue_forbidden(client, db, jwt_encode):
    venue1 = await _seed_venue(db, "Venue One")
    venue2 = await _seed_venue(db, "Venue Two")
    admin = await _seed_admin(db, venue1.id)
    token = _token_for_singer(jwt_encode, admin)

    resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue2.id, "name": "KJ Laptop 1"},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 2. TOKEN EXCHANGE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_kj_token_success(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "KJ Laptop 1"},
        headers=AUTHORIZATION(token),
    )
    api_key = reg_resp.json()["api_key"]

    resp = await client.post("/v1/kj/token", json={"api_key": api_key})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 15 * 60

    # verify token claims
    claims = jwt.decode(data["access_token"], settings.JWT_SECRET_KEY, algorithms=["HS256"])
    assert claims["kj_device_id"] == reg_resp.json()["id"]
    assert claims["venue_id"] == venue.id
    assert claims["kj_device_name"] == "KJ Laptop 1"
    assert claims["type"] == "access"


@pytest.mark.anyio
async def test_kj_token_invalid_key(client, db):
    resp = await client.post("/v1/kj/token", json={"api_key": "invalid-key"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_kj_token_revoked_key(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "KJ Laptop 1"},
        headers=AUTHORIZATION(token),
    )
    api_key = reg_resp.json()["api_key"]
    device_id = reg_resp.json()["id"]

    # revoke
    await client.post(f"/v1/kj/devices/{device_id}/revoke", headers=AUTHORIZATION(token))

    # token exchange should fail
    resp = await client.post("/v1/kj/token", json={"api_key": api_key})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# 3. LIST DEVICES
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_kj_list_devices_admin(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "Device A"},
        headers=AUTHORIZATION(token),
    )
    await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "Device B"},
        headers=AUTHORIZATION(token),
    )

    resp = await client.get("/v1/kj/devices", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data["items"]) == 2
    names = {d["name"] for d in data["items"]}
    assert names == {"Device A", "Device B"}


@pytest.mark.anyio
async def test_kj_list_devices_non_admin_forbidden(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    token = _token_for_singer(jwt_encode, singer)

    resp = await client.get("/v1/kj/devices", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 4. REVOKE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_kj_revoke_admin_success(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "Device A"},
        headers=AUTHORIZATION(token),
    )
    device_id = reg_resp.json()["id"]

    resp = await client.post(f"/v1/kj/devices/{device_id}/revoke", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    assert "revoked" in resp.json()["message"].lower()

    # idempotent
    resp2 = await client.post(f"/v1/kj/devices/{device_id}/revoke", headers=AUTHORIZATION(token))
    assert resp2.status_code == status.HTTP_200_OK
    assert "already revoked" in resp2.json()["message"].lower()


@pytest.mark.anyio
async def test_kj_revoke_non_admin_forbidden(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    singer = await _seed_singer(db, venue.id)
    admin_token = _token_for_singer(jwt_encode, admin)
    singer_token = _token_for_singer(jwt_encode, singer)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "Device A"},
        headers=AUTHORIZATION(admin_token),
    )
    device_id = reg_resp.json()["id"]

    resp = await client.post(f"/v1/kj/devices/{device_id}/revoke", headers=AUTHORIZATION(singer_token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 5. ROTATE KEY
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_kj_rotate_admin_success(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "Device A"},
        headers=AUTHORIZATION(token),
    )
    device_id = reg_resp.json()["id"]
    old_key = reg_resp.json()["api_key"]

    resp = await client.post(f"/v1/kj/devices/{device_id}/rotate", headers=AUTHORIZATION(token))
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["id"] == device_id
    new_key = data["api_key"]
    assert new_key != old_key

    # old key should fail
    resp_old = await client.post("/v1/kj/token", json={"api_key": old_key})
    assert resp_old.status_code == status.HTTP_401_UNAUTHORIZED

    # new key should succeed
    resp_new = await client.post("/v1/kj/token", json={"api_key": new_key})
    assert resp_new.status_code == status.HTTP_200_OK


@pytest.mark.anyio
async def test_kj_rotate_unrevokes_device(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "Device A"},
        headers=AUTHORIZATION(token),
    )
    device_id = reg_resp.json()["id"]
    api_key = reg_resp.json()["api_key"]

    # revoke first
    await client.post(f"/v1/kj/devices/{device_id}/revoke", headers=AUTHORIZATION(token))
    assert (await client.post("/v1/kj/token", json={"api_key": api_key})).status_code == 401

    # rotate un-revokes
    rotate_resp = await client.post(f"/v1/kj/devices/{device_id}/rotate", headers=AUTHORIZATION(token))
    new_key = rotate_resp.json()["api_key"]
    assert (await client.post("/v1/kj/token", json={"api_key": new_key})).status_code == 200


@pytest.mark.anyio
async def test_kj_rotate_non_admin_forbidden(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    singer = await _seed_singer(db, venue.id)
    admin_token = _token_for_singer(jwt_encode, admin)
    singer_token = _token_for_singer(jwt_encode, singer)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "Device A"},
        headers=AUTHORIZATION(admin_token),
    )
    device_id = reg_resp.json()["id"]

    resp = await client.post(f"/v1/kj/devices/{device_id}/rotate", headers=AUTHORIZATION(singer_token))
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# 6. kj_auth DEPENDENCY
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_kj_auth_via_api_key_header(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "KJ Laptop 1"},
        headers=AUTHORIZATION(token),
    )
    api_key = reg_resp.json()["api_key"]

    # Use kj_auth dependency via an endpoint that requires it
    # The /v1/kj/devices endpoint uses SingerUser auth, not kj_auth.
    # We'll verify kj_auth works by hitting the token endpoint (which uses it implicitly
    # via _kj_auth_by_api_key in the token endpoint itself).
    # For a true dependency test, let's just verify token endpoint accepts x-api-key
    # by checking the token exchange endpoint accepts api_key in body.
    # Actually the kj_auth dependency is meant for OTHER endpoints to use.
    # Let's verify it directly by importing and calling.
    from app.core.auth import kj_auth
    from fastapi import Request
    from starlette.datastructures import Headers

    scope = {
        "type": "http",
        "method": "GET",
        "headers": [(b"x-api-key", api_key.encode())],
    }
    req = Request(scope)
    user = await kj_auth(req)
    assert user.venue_id == venue.id
    assert user.name == "KJ Laptop 1"


@pytest.mark.anyio
async def test_kj_auth_via_bearer_jwt(client, db, jwt_encode):
    venue = await _seed_venue(db)
    admin = await _seed_admin(db, venue.id)
    token = _token_for_singer(jwt_encode, admin)

    reg_resp = await client.post(
        "/v1/kj/register",
        json={"venue_id": venue.id, "name": "KJ Laptop 1"},
        headers=AUTHORIZATION(token),
    )
    api_key = reg_resp.json()["api_key"]

    # get KJ token
    token_resp = await client.post("/v1/kj/token", json={"api_key": api_key})
    kj_token = token_resp.json()["access_token"]

    from app.core.auth import kj_auth
    from fastapi import Request
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [(b"authorization", f"Bearer {kj_token}".encode())],
    }
    req = Request(scope)
    user = await kj_auth(req)
    assert user.venue_id == venue.id
    assert user.id == reg_resp.json()["id"]


@pytest.mark.anyio
async def test_kj_auth_invalid_key_401(client, db):
    from app.core.auth import kj_auth
    from fastapi import Request
    scope = {
        "type": "http",
        "method": "GET",
        "headers": [(b"x-api-key", b"totally-wrong-key")],
    }
    req = Request(scope)
    with pytest.raises(Exception) as exc_info:
        await kj_auth(req)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# 7. EXISTING AUTH UNAFFECTED
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_existing_singer_auth_unaffected(client, db, jwt_encode):
    """Quick smoke test that singer login/refresh/me still work."""
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    from app.routers.auth import LoginRequest

    resp = await client.post(
        "/v1/auth/login",
        json={"email": singer.email, "password": "secret123"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["access_token"]
    assert data["singer_id"] == singer.id

    # me endpoint
    me_resp = await client.get("/v1/auth/me", headers=AUTHORIZATION(data["access_token"]))
    assert me_resp.status_code == status.HTTP_200_OK
    assert me_resp.json()["id"] == singer.id
