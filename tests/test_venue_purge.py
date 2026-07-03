"""Tests for venue purge + retention scheduler compliance logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Venue, Singer, Payment, Order, AdminAuditLog
from app.services.venue_purge import (
    purge_venue,
    venue_has_billing_history,
    purge_expired_soft_deleted_venues,
)


async def _seed_venue(
    db: AsyncSession,
    name: str = "Purge Venue",
    deleted_at: str | None = None,
) -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=f"purge-{venue_id[:8]}",
        venue_code=venue_id[:6].upper(),
        billing_email="owner@example.com",
        subscription_tier="basic",
        subscription_status="trialing",
        billing_status="trial",
        deleted_at=deleted_at,
    )
    db.add(venue)
    await db.commit()
    return venue


async def _seed_singer(db: AsyncSession, venue_id: str, stage_name: str = "Singer") -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=f"{uuid.uuid4().hex}@example.com",
    )
    db.add(singer)
    await db.commit()
    return singer


@pytest.mark.anyio
async def test_venue_has_billing_history_false_without_payments(db: AsyncSession):
    venue = await _seed_venue(db)
    assert await venue_has_billing_history(db, venue.id) is False


@pytest.mark.anyio
async def test_venue_has_billing_history_true_with_succeeded_payment(db: AsyncSession):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    payment = Payment(
        id=str(uuid.uuid4()),
        venue_id=venue.id,
        singer_id=singer.id,
        amount_cents=100,
        payment_type="tip",
        status="succeeded",
    )
    db.add(payment)
    await db.commit()
    assert await venue_has_billing_history(db, venue.id) is True


@pytest.mark.anyio
async def test_venue_has_billing_history_true_with_paid_order(db: AsyncSession):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id)
    order = Order(
        id=str(uuid.uuid4()),
        venue_id=venue.id,
        singer_id=singer.id,
        total_cents=500,
        status="paid",
    )
    db.add(order)
    await db.commit()
    assert await venue_has_billing_history(db, venue.id) is True


@pytest.mark.anyio
async def test_purge_hard_deletes_venue_without_billing(db: AsyncSession):
    venue = await _seed_venue(db)
    await _seed_singer(db, venue.id)
    result = await purge_venue(
        db,
        venue.id,
        admin_email="qa@example.com",
        admin_action_details={"reason": "test"},
    )
    assert result["action"] == "hard_delete"
    gone = await db.get(Venue, venue.id)
    assert gone is None

    # Audit log is written inside the purge transaction before the venue row
    # is deleted, so PostgreSQL never sees an FK violation. SQLite keeps the
    # venue_id because it does not emulate ON DELETE SET NULL by default.
    audit = (
        await db.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "venue.purge",
                AdminAuditLog.admin_email == "qa@example.com",
            )
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.venue_name == venue.name
    assert audit.details_json == '{"reason": "test"}'


@pytest.mark.anyio
async def test_purge_anonymizes_venue_with_billing(db: AsyncSession):
    venue = await _seed_venue(db)
    singer = await _seed_singer(db, venue.id, stage_name="Original Name")
    payment = Payment(
        id=str(uuid.uuid4()),
        venue_id=venue.id,
        singer_id=singer.id,
        amount_cents=250,
        payment_type="priority_bump",
        status="succeeded",
    )
    db.add(payment)
    await db.commit()

    result = await purge_venue(db, venue.id)
    assert result["action"] == "anonymize"
    assert result["anonymized_singer_count"] == 1

    venue_after = await db.get(Venue, venue.id)
    assert venue_after is not None
    assert "Anonymized" in venue_after.name
    assert venue_after.billing_email is None
    assert venue_after.is_active == 0

    singer_after = await db.get(Singer, singer.id)
    assert singer_after is not None
    assert singer_after.stage_name.startswith("Singer")
    assert singer_after.email != "original@example.com"
    assert singer_after.phone is not None
    assert singer_after.phone != "555-0000"
    assert singer_after.password_hash is None

    # Financial record preserved
    payment_after = await db.get(Payment, payment.id)
    assert payment_after is not None
    assert payment_after.amount_cents == 250


@pytest.mark.anyio
async def test_purge_expired_soft_deleted_venues(db: AsyncSession):
    old = await _seed_venue(db, deleted_at="2020-01-01T00:00:00Z")
    fresh = await _seed_venue(db, deleted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    results = await purge_expired_soft_deleted_venues(db, retention_days=30)
    ids = {r["venue_id"] for r in results}
    assert old.id in ids
    assert fresh.id not in ids


@pytest.mark.anyio
async def test_admin_purge_endpoint_requires_soft_delete_first(client: AsyncClient, db: AsyncSession):
    from tests.test_venues import _seed_singer
    venue = await _seed_venue(db)
    admin = await _seed_singer(db, venue.id, stage_name="Admin", role="admin")
    token = __import__("jose").jwt.encode(
        {"sub": admin.id, "venue_id": admin.venue_id, "role": "admin"},
        "test-jwt-secret-do-not-use-in-production",
        algorithm="HS256",
    )
    resp = await client.delete(f"/v1/admin/venues/{venue.id}/purge", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 409


@pytest.mark.anyio
async def test_admin_purge_endpoint_hard_deletes_soft_deleted(client: AsyncClient, db: AsyncSession):
    from tests.test_venues import _seed_singer
    venue = await _seed_venue(db, deleted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    admin = await _seed_singer(db, venue.id, stage_name="Admin", role="admin")
    token = __import__("jose").jwt.encode(
        {"sub": admin.id, "venue_id": admin.venue_id, "role": "admin", "email": admin.email},
        "test-jwt-secret-do-not-use-in-production",
        algorithm="HS256",
    )
    resp = await client.delete(f"/v1/admin/venues/{venue.id}/purge", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "hard_delete"

    # The audit log row is written inside the purge transaction before the venue
    # row is deleted, so PostgreSQL never sees an FK violation.
    audit = (
        await db.execute(
            select(AdminAuditLog).where(
                AdminAuditLog.action == "venue.purge",
                AdminAuditLog.admin_email == admin.email,
            )
        )
    ).scalar_one_or_none()
    assert audit is not None
    assert audit.venue_name == venue.name
    assert audit.details_json is not None


@pytest.mark.anyio
async def test_admin_restore_endpoint(client: AsyncClient, db: AsyncSession):
    from tests.test_venues import _seed_singer
    venue = await _seed_venue(db, deleted_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    admin = await _seed_singer(db, venue.id, stage_name="Admin", role="admin")
    token = __import__("jose").jwt.encode(
        {"sub": admin.id, "venue_id": admin.venue_id, "role": "admin"},
        "test-jwt-secret-do-not-use-in-production",
        algorithm="HS256",
    )
    resp = await client.post(f"/v1/admin/venues/{venue.id}/restore", json={}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted_at"] is None
    assert data["is_active"] is True


@pytest.mark.anyio
async def test_admin_list_deleted_venues(client: AsyncClient, db: AsyncSession):
    from tests.test_venues import _seed_singer
    active = await _seed_venue(db)
    deleted = await _seed_venue(db, deleted_at="2020-01-01T00:00:00Z")
    admin = await _seed_singer(db, active.id, stage_name="Admin", role="admin")
    token = __import__("jose").jwt.encode(
        {"sub": admin.id, "venue_id": admin.venue_id, "role": "admin"},
        "test-jwt-secret-do-not-use-in-production",
        algorithm="HS256",
    )
    resp = await client.get("/v1/admin/venues?deleted=true", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert deleted.id in {v["id"] for v in data["items"]}
    assert active.id not in {v["id"] for v in data["items"]}
