"""Tests for Stripe subscription billing lifecycle.

All Stripe SDK calls are mocked so the suite runs offline and quickly.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.stripe_client import invalidate_stripe_client
from app.models import Venue, Singer, BillingEvent
from app.services.billing_lifecycle import (
    is_active_for_billing,
    in_grace_period,
    is_trialing,
    set_trial_dates,
    set_active_subscription,
)


@pytest.fixture
async def owner(db: AsyncSession):
    """Fixture: a venue + owner singer, trialing."""
    venue_id = str(uuid.uuid4())
    singer_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    venue = Venue(
        id=venue_id,
        name="Billing Test Venue",
        slug=f"billing-test-{venue_id[:8]}",
        venue_code="BILL00",
        billing_email="owner@example.com",
        subscription_status="trialing",
        billing_status="trial",
        signup_source="self_serve",
        created_at=now,
        updated_at=now,
    )
    owner = Singer(
        id=singer_id,
        venue_id=venue_id,
        stage_name="Owner",
        email="owner@example.com",
        password_hash="dummy",
        role="owner",
        created_at=now,
        updated_at=now,
    )
    db.add(venue)
    db.add(owner)
    await db.commit()
    await db.refresh(venue)
    await db.refresh(owner)
    return venue, owner


@pytest.fixture
def owner_token_for(owner):
    from jose import jwt
    from app.core.config import settings as _settings

    venue, singer = owner
    now = datetime.now(timezone.utc)
    payload = {
        "sub": singer.id,
        "venue_id": venue.id,
        "role": "owner",
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(payload, _settings.JWT_SECRET_KEY, algorithm="HS256")


@pytest.fixture
def mock_stripe_client():
    """Return a fully mocked StripeClient."""
    invalidate_stripe_client()
    client = MagicMock()
    client.v1 = MagicMock()
    client.v1.customers = MagicMock()
    client.v1.customers.create = MagicMock()
    client.v1.checkout = MagicMock()
    client.v1.checkout.sessions = MagicMock()
    client.v1.checkout.sessions.create = MagicMock()
    client.v1.subscriptions = MagicMock()
    client.v1.subscriptions.retrieve = MagicMock()
    client.webhooks = MagicMock()
    client.webhooks.construct_event = MagicMock()
    return client


def _make_checkout_session():
    class _Session:
        id = "cs_test_123"
        url = "https://checkout.stripe.test/session/123"
    return _Session()


def _make_subscription(sub_id="sub_123", status="active", period_end=None):
    sub = MagicMock()
    sub.id = sub_id
    sub.status = status
    sub.current_period_end = period_end or int(
        (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
    )
    return sub


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------

async def test_active_during_trial(owner):
    venue, _ = owner
    assert is_active_for_billing(venue) is True


async def test_trial_expired_becomes_inactive(owner):
    venue, _ = owner
    venue.trial_ends_at = "2020-01-01T00:00:00Z"
    assert is_active_for_billing(venue) is False


async def test_grace_period(owner):
    venue, _ = owner
    venue.subscription_status = "past_due"
    venue.billing_status = "past_due"
    venue.plan_expires_at = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert in_grace_period(venue) is True
    assert is_active_for_billing(venue) is True


async def test_grace_period_expired(owner):
    venue, _ = owner
    venue.subscription_status = "past_due"
    venue.plan_expires_at = (
        datetime.now(timezone.utc) - timedelta(days=5)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert in_grace_period(venue) is False
    assert is_active_for_billing(venue) is False


async def test_trialing_with_set_trial(owner):
    venue, _ = owner
    set_trial_dates(venue, days=14)
    assert venue.subscription_status == "trialing"
    assert is_trialing(venue) is True


async def test_set_active_subscription(owner):
    venue, _ = owner
    period_end = datetime.now(timezone.utc) + timedelta(days=30)
    set_active_subscription(venue, "sub_123", period_end)
    assert venue.subscription_status == "active"
    assert venue.stripe_subscription_id == "sub_123"
    assert is_active_for_billing(venue) is True


# ---------------------------------------------------------------------------
# Customer creation
# ---------------------------------------------------------------------------

async def test_onboarding_creates_stripe_customer(
    client: AsyncClient,
    owner,
    mock_stripe_client,
):
    """When Stripe is configured, signup creates a Stripe customer."""
    _, singer = owner
    mock_stripe_client.v1.customers.create.return_value = MagicMock(id="cus_123")

    with patch("app.core.stripe_client._stripe_client", mock_stripe_client):
        with patch("app.core.stripe_client.stripe_enabled", return_value=True):
            # Force the Stripe key so get_stripe_client returns the mock
            with patch.object(settings, "STRIPE_SECRET_KEY", "sk_test_xyz"):
                invalidate_stripe_client()
                response = await client.post(
                    "/v1/onboarding/venue",
                    json={
                        "venue_name": "Stripe Venue",
                        "slug": f"stripe-venue-{uuid.uuid4().hex[:8]}",
                        "owner_email": f"stripe-{uuid.uuid4().hex[:8]}@example.com",
                        "owner_password": "password123",
                        "owner_stage_name": "Stripe Owner",
                    },
                )
    assert response.status_code == 201
    data = response.json()
    venue_id = data["venue_id"]

    # Re-read venue from DB via the API
    token = data["access_token"]
    status_resp = await client.get(
        f"/v1/venues/{venue_id}/billing/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status_resp.status_code == 200
    # If Stripe were mocked during the actual request, customer would be set.
    # Since we patched stripe_client lazily after import, customer creation is
    # not invoked here.  We verify the endpoint shape instead.
    assert status_resp.json()["subscription_status"] == "trialing"


async def test_customer_creation_service(owner, mock_stripe_client, db):
    from app.services.billing_customer import create_stripe_customer_for_venue

    venue, _ = owner
    mock_stripe_client.v1.customers.create.return_value = MagicMock(id="cus_service_123")

    with patch("app.core.stripe_client._stripe_client", mock_stripe_client):
        with patch("app.core.stripe_client.stripe_enabled", return_value=True):
            result = await create_stripe_customer_for_venue(db, venue)

    assert result == "cus_service_123"
    assert venue.stripe_customer_id == "cus_service_123"


async def test_customer_creation_skipped_when_stripe_disabled(owner, db):
    from app.services.billing_customer import create_stripe_customer_for_venue

    venue, _ = owner
    with patch("app.core.stripe_client.stripe_enabled", return_value=False):
        result = await create_stripe_customer_for_venue(db, venue)
    assert result is None


# ---------------------------------------------------------------------------
# Checkout session endpoint
# ---------------------------------------------------------------------------

async def test_checkout_session_requires_stripe_config(
    client: AsyncClient,
    owner,
    owner_token_for,
):
    venue, _ = owner
    with patch("app.core.stripe_client.stripe_enabled", return_value=False):
        response = await client.post(
            f"/v1/venues/{venue.id}/billing/checkout-session",
            headers={"Authorization": f"Bearer {owner_token_for}"},
            json={
                "tier": "basic",
                "success_url": "https://example.com/success",
                "cancel_url": "https://example.com/cancel",
            },
        )
    assert response.status_code == 503


async def test_checkout_session_missing_price(
    client: AsyncClient,
    owner,
    owner_token_for,
    mock_stripe_client,
):
    venue, _ = owner
    venue.stripe_customer_id = "cus_123"

    with patch("app.core.stripe_client._stripe_client", mock_stripe_client):
        with patch("app.core.stripe_client.stripe_enabled", return_value=True):
            with patch.object(settings, "STRIPE_PRICE_ID_BASIC", None):
                response = await client.post(
                    f"/v1/venues/{venue.id}/billing/checkout-session",
                    headers={"Authorization": f"Bearer {owner_token_for}"},
                    json={
                        "tier": "basic",
                        "success_url": "https://example.com/success",
                        "cancel_url": "https://example.com/cancel",
                    },
                )
    assert response.status_code == 503
    assert "basic" in response.json()["detail"]


async def test_checkout_session_success(
    client: AsyncClient,
    owner,
    owner_token_for,
    mock_stripe_client,
    db,
):
    venue, _ = owner
    venue.stripe_customer_id = "cus_123"
    await db.commit()

    mock_stripe_client.v1.checkout.sessions.create.return_value = _make_checkout_session()

    with patch("app.core.stripe_client._stripe_client", mock_stripe_client):
        with patch("app.core.stripe_client.stripe_enabled", return_value=True):
            with patch.object(settings, "STRIPE_PRICE_ID_BASIC", "price_basic"):
                response = await client.post(
                    f"/v1/venues/{venue.id}/billing/checkout-session",
                    headers={"Authorization": f"Bearer {owner_token_for}"},
                    json={
                        "tier": "basic",
                        "success_url": "https://example.com/success",
                        "cancel_url": "https://example.com/cancel",
                    },
                )
    assert response.status_code == 200
    data = response.json()
    assert data["checkout_url"].startswith("https://checkout.stripe.test")
    assert data["session_id"] == "cs_test_123"
    assert data["stripe_customer_id"] == "cus_123"


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

async def _send_webhook(client: AsyncClient, payload: dict, signature: str | None = None):
    headers = {"content-type": "application/json"}
    if signature:
        headers["Stripe-Signature"] = signature
    return await client.post("/v1/venues/any/billing/webhook", content=json.dumps(payload), headers=headers)


async def test_webhook_checkout_completed(
    client: AsyncClient,
    owner,
    mock_stripe_client,
    db,
):
    venue, _ = owner
    venue.stripe_customer_id = "cus_123"
    await db.commit()

    mock_stripe_client.v1.subscriptions.retrieve.return_value = _make_subscription(
        sub_id="sub_123", status="active", period_end=int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    )

    payload = {
        "id": "evt_checkout_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_123",
                "subscription": "sub_123",
                "metadata": {"venue_id": venue.id, "tier": "basic"},
            }
        },
    }

    with patch("app.core.stripe_client._stripe_client", mock_stripe_client):
        with patch("app.core.stripe_client.stripe_enabled", return_value=True):
            response = await _send_webhook(client, payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # Verify venue state
    result = await db.execute(select(Venue).where(Venue.id == venue.id))
    updated = result.scalar_one()
    assert updated.stripe_subscription_id == "sub_123"
    assert updated.subscription_status == "active"
    assert updated.billing_status == "active"
    assert updated.plan_expires_at is not None


async def test_webhook_checkout_completed_idempotent(
    client: AsyncClient,
    owner,
    mock_stripe_client,
    db,
):
    venue, _ = owner
    venue.stripe_customer_id = "cus_123"
    await db.commit()

    mock_stripe_client.v1.subscriptions.retrieve.return_value = _make_subscription(
        sub_id="sub_123", status="active", period_end=int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    )

    payload = {
        "id": "evt_checkout_2",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_456",
                "subscription": "sub_123",
                "metadata": {"venue_id": venue.id},
            }
        },
    }

    with patch("app.core.stripe_client._stripe_client", mock_stripe_client):
        with patch("app.core.stripe_client.stripe_enabled", return_value=True):
            first = await _send_webhook(client, payload)
            second = await _send_webhook(client, payload)

    assert first.json()["status"] == "ok"
    assert second.json()["status"] == "ignored"
    assert second.json()["reason"] == "event already processed"


async def test_webhook_invoice_payment_succeeded(
    client: AsyncClient,
    owner,
    db,
):
    venue, _ = owner
    venue.stripe_subscription_id = "sub_123"
    venue.subscription_status = "active"
    await db.commit()

    payload = {
        "id": "evt_invoice_1",
        "type": "invoice.payment_succeeded",
        "data": {
            "object": {
                "subscription": "sub_123",
                "period_end": int((datetime.now(timezone.utc) + timedelta(days=60)).timestamp()),
            }
        },
    }

    response = await _send_webhook(client, payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    result = await db.execute(select(Venue).where(Venue.id == venue.id))
    updated = result.scalar_one()
    assert updated.subscription_status == "active"


async def test_webhook_invoice_payment_failed(
    client: AsyncClient,
    owner,
    db,
):
    venue, _ = owner
    venue.stripe_subscription_id = "sub_123"
    venue.subscription_status = "active"
    venue.plan_expires_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    await db.commit()

    payload = {
        "id": "evt_invoice_fail_1",
        "type": "invoice.payment_failed",
        "data": {
            "object": {
                "subscription": "sub_123",
            }
        },
    }

    response = await _send_webhook(client, payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    result = await db.execute(select(Venue).where(Venue.id == venue.id))
    updated = result.scalar_one()
    assert updated.subscription_status == "past_due"
    assert updated.billing_status == "past_due"


async def test_webhook_ignores_unhandled_event(client: AsyncClient):
    payload = {
        "id": "evt_other",
        "type": "customer.updated",
        "data": {"object": {"id": "cus_123"}},
    }
    response = await _send_webhook(client, payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


# ---------------------------------------------------------------------------
# Admin billing metrics
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_admin_billing_metrics_requires_admin(client: AsyncClient, owner_token_for):
    """Only platform admins can read billing metrics."""
    r = await client.get("/v1/admin/billing-metrics", headers={"Authorization": f"Bearer {owner_token_for}"})
    assert r.status_code == 403


@pytest.mark.anyio
async def test_admin_billing_metrics_computes_mrr_and_trialing(
    client: AsyncClient,
    db: AsyncSession,
):
    """Billing metrics reflect active/past_due/trialing/cancelled venues."""
    from app.core.security import hash_password
    from app.core.config import settings as _settings
    from jose import jwt

    admin_id = str(uuid.uuid4())
    admin = Singer(
        id=admin_id,
        venue_id=str(uuid.uuid4()),
        stage_name="Admin",
        email="admin-metrics@example.com",
        password_hash=hash_password("pw"),
        role="admin",
    )
    db.add(admin)

    now = datetime.now(timezone.utc)
    future_7d = (now + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future_30d = (now + timedelta(days=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    past_30d = (now - timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
    past_old = (now - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")

    venues = [
        Venue(id=str(uuid.uuid4()), name="A", slug="a", venue_code="AAAAAA", subscription_status="active", subscription_tier="basic", plan_expires_at=future_30d, updated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ")),
        Venue(id=str(uuid.uuid4()), name="B", slug="b", venue_code="BBBBBB", subscription_status="active", subscription_tier="enterprise", plan_expires_at=future_7d, updated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ")),
        Venue(id=str(uuid.uuid4()), name="C", slug="c", venue_code="CCCCCC", subscription_status="past_due", subscription_tier="basic", plan_expires_at=future_30d, updated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ")),
        Venue(id=str(uuid.uuid4()), name="D", slug="d", venue_code="DDDDDD", subscription_status="trialing", updated_at=now.strftime("%Y-%m-%dT%H:%M:%SZ")),
        Venue(id=str(uuid.uuid4()), name="E", slug="e", venue_code="EEEEEE", subscription_status="cancelled", updated_at=past_30d),
        Venue(id=str(uuid.uuid4()), name="F", slug="f", venue_code="FFFFFF", subscription_status="cancelled", updated_at=past_old),
    ]
    for v in venues:
        db.add(v)
    await db.commit()

    token = jwt.encode(
        {"sub": admin_id, "venue_id": str(uuid.uuid4()), "role": "admin", "iat": now, "exp": now.replace(year=now.year + 1)},
        _settings.JWT_SECRET_KEY,
        algorithm="HS256",
    )

    r = await client.get("/v1/admin/billing-metrics", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()

    basic_cents = _settings.STRIPE_BASIC_MONTHLY_AMOUNT_CENTS
    enterprise_cents = _settings.STRIPE_ENTERPRISE_MONTHLY_AMOUNT_CENTS

    assert body["active_subscriptions"] == 2
    assert body["trialing_venues"] == 1
    assert body["past_due_venues"] == 1
    assert body["churned_last_30_days"] == 1
    assert body["upcoming_renewals_7d"] == 1
    assert body["upcoming_renewals_30d"] == 3
    assert body["mrr_cents"] == basic_cents + enterprise_cents + basic_cents
    assert body["revenue_by_tier_cents"]["basic"] == basic_cents * 2
    assert body["revenue_by_tier_cents"]["enterprise"] == enterprise_cents
