"""License API tests.

Covers:
- Admin license CRUD (platform admin)
- Online activation
- Offline activation request and file-based activation
- Status checks including expiry and grace period
- Revocation
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import Venue, Singer, License


AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


async def _seed_venue(session) -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name="License Test Venue",
        slug=f"license-venue-{venue_id[:8]}",
        venue_code="".join(["A", "B", "C", "D", "E", "F"]),
        is_active=1,
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(session, venue_id: str, role: str = "admin") -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=f"{role.capitalize()} User",
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("secret123"),
        role=role,
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


def _token_for_singer(jwt_encode, singer: Singer) -> str:
    return jwt_encode(
        venue_id=str(singer.venue_id), role=str(singer.role), user_id=str(singer.id)
    )


def _now_iso(days_offset: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(days=days_offset)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.anyio
async def test_admin_create_license(client, db, jwt_encode):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    admin = await _seed_singer(db, venue_id, role="admin")
    token = _token_for_singer(jwt_encode, admin)

    resp = await client.post(
        "/v1/admin/licenses",
        json={
            "venue_id": venue_id,
            "plan": "enterprise",
            "expires_at": _now_iso(days_offset=30),
        },
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    data = resp.json()
    assert data["venue_id"] == venue_id
    assert data["plan"] == "enterprise"
    assert data["license_key"].startswith("SCALES-")


@pytest.mark.anyio
async def test_admin_list_licenses(client, db, jwt_encode):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    admin = await _seed_singer(db, venue_id, role="admin")
    token = _token_for_singer(jwt_encode, admin)

    await client.post(
        "/v1/admin/licenses",
        json={"venue_id": venue_id},
        headers=AUTHORIZATION(token),
    )

    resp = await client.get(
        "/v1/admin/licenses",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] >= 1
    assert any(item["venue_id"] == venue_id for item in data["items"])


@pytest.mark.anyio
async def test_admin_revoke_license(client, db, jwt_encode):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    admin = await _seed_singer(db, venue_id, role="admin")
    token = _token_for_singer(jwt_encode, admin)

    create_resp = await client.post(
        "/v1/admin/licenses",
        json={"venue_id": venue_id},
        headers=AUTHORIZATION(token),
    )
    license_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/v1/admin/licenses/{license_id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["status"] == "revoked"


@pytest.mark.anyio
async def test_online_activation(client, db):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    from app.services.license_service import LicenseService
    svc = LicenseService(db)
    license_row, key = await svc.create_license(venue_id=venue_id)

    fingerprint = "fp-12345"
    resp = await client.post(
        "/v1/license/activate",
        json={"license_key": key, "fingerprint": fingerprint},
    )
    assert resp.status_code == status.HTTP_200_OK, resp.text
    data = resp.json()
    assert data["license_id"] == license_row.id
    assert data["venue_id"] == venue_id
    assert data["license_file"]
    assert data["status"] == "active"


@pytest.mark.anyio
async def test_online_activation_invalid_key(client, db):
    resp = await client.post(
        "/v1/license/activate",
        json={"license_key": "SCALES-0000-0000-0000-0000", "fingerprint": "fp"},
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_offline_activation_flow(client, db, jwt_encode):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    admin = await _seed_singer(db, venue_id, role="admin")
    admin_token = _token_for_singer(jwt_encode, admin)
    from app.services.license_service import LicenseService
    svc = LicenseService(db)
    license_row, key = await svc.create_license(venue_id=venue_id)
    license_id = license_row.id

    fingerprint = "fp-offline"
    request_resp = await client.post(
        "/v1/license/offline/request",
        json={"license_key": key, "fingerprint": fingerprint},
    )
    assert request_resp.status_code == status.HTTP_200_OK
    request_data = request_resp.json()
    assert request_data["license_id"] == license_id

    offline_resp = await client.post(
        f"/v1/admin/licenses/{license_id}/offline",
        json={"fingerprint": fingerprint},
        headers=AUTHORIZATION(admin_token),
    )
    assert offline_resp.status_code == status.HTTP_200_OK, offline_resp.text
    file_data = offline_resp.json()
    license_file = file_data["license_file"]
    assert license_file

    activate_resp = await client.post(
        "/v1/license/offline/activate",
        json={"license_file": license_file, "fingerprint": fingerprint},
    )
    assert activate_resp.status_code == status.HTTP_200_OK
    assert activate_resp.json()["status"] == "active"


@pytest.mark.anyio
async def test_license_status_valid(client, db):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    from app.services.license_service import LicenseService
    svc = LicenseService(db)
    license_row, key = await svc.create_license(venue_id=venue_id)
    result = await svc.activate_online(key, "fp-status")
    license_file = result["license_file"]

    resp = await client.get(
        "/v1/license/status",
        params={"license_file": license_file, "fingerprint": "fp-status"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["ok"] is True
    assert data["status"] == "valid"


@pytest.mark.anyio
async def test_license_status_revoked(client, db):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    from app.services.license_service import LicenseService
    svc = LicenseService(db)
    license_row, key = await svc.create_license(venue_id=venue_id)
    result = await svc.activate_online(key, "fp-revoke")
    await svc.revoke_license(str(license_row.id))

    resp = await client.get(
        "/v1/license/status",
        params={"license_file": result["license_file"], "fingerprint": "fp-revoke"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["ok"] is False
    assert data["status"] == "revoked"


@pytest.mark.anyio
async def test_license_status_expired_in_grace(client, db):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    from app.services.license_service import LicenseService
    svc = LicenseService(db)
    expired = _now_iso(days_offset=-1)
    license_row, key = await svc.create_license(
        venue_id=venue_id, expires_at=expired, grace_days=7
    )
    result = await svc.activate_online(key, "fp-grace")

    resp = await client.get(
        "/v1/license/status",
        params={"license_file": result["license_file"], "fingerprint": "fp-grace"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["status"] == "grace"
    assert data["ok"] is True
    assert data["grace_until"]


@pytest.mark.anyio
async def test_check_in_updates_last_seen(client, db):
    venue = await _seed_venue(db)
    venue_id = str(venue.id)
    from app.services.license_service import LicenseService
    svc = LicenseService(db)
    license_row, key = await svc.create_license(venue_id=venue_id)
    result = await svc.activate_online(key, "fp-checkin")

    resp = await client.post(
        "/v1/license/check-in",
        json={"license_file": result["license_file"], "fingerprint": "fp-checkin"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["ok"] is True

    refreshed = await svc.get_license(str(license_row.id))
    assert refreshed is not None
    assert refreshed.last_check_in_at is not None


@pytest.mark.anyio
async def test_admin_create_license_requires_admin(client, db, jwt_encode):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, str(venue.id), role="singer")
    token = _token_for_singer(jwt_encode, singer)

    resp = await client.post(
        "/v1/admin/licenses",
        json={"venue_id": str(venue.id)},
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN
