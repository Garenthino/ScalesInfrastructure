"""Payments router tests.

Covers:
- POST /venues/{venue_id}/payments/tip  — create tip PaymentIntent
- POST /venues/{venue_id}/payments/priority-bump — create priority bump PaymentIntent
- GET  /venues/{venue_id}/payments/history — paginated payment history
- POST /venues/{venue_id}/payments/webhook — Stripe webhook handler
- Validation: min $1 (100 cents), max 2 priority bumps per night
- Stripe error handling, venue scoping, auth boundaries
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Venue, Singer, QueueRequest, Payment, Song


def AUTHORIZATION(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _token(singer: Singer) -> str:
    from jose import jwt
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


@pytest.fixture
async def _payment_venue(db: AsyncSession):
    """Create a venue with two singers, a song, and a queue request."""
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="Payment Venue", slug=f"pay-{venue_id[:8]}")
    db.add(venue)

    kj = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="KJ Host",
        role="kj",
    )
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Singer One",
        role="singer",
    )
    singer2 = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Singer Two",
        role="singer",
    )
    db.add_all([kj, singer, singer2])
    await db.commit()

    song = Song(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        title="Test Song",
        artist="Test Artist",
        is_available=1,
    )
    db.add(song)
    await db.commit()

    # Queue request for singer (to be bumped)
    qr = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=singer.id,
        song_id=song.id,
        status="pending",
        requested_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        rotation_position=5,
    )
    db.add(qr)
    await db.commit()

    for obj in [venue, kj, singer, singer2, song, qr]:
        await db.refresh(obj)

    return venue_id, kj, singer, singer2, song, qr


@pytest.fixture
async def _priority_bump_payments(db: AsyncSession, _payment_venue):
    """Create 2 existing priority-bump payments for singer to test the 2/night limit."""
    venue_id, _, singer, _, _, qr = _payment_venue
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in range(2):
        p = Payment(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=singer.id,
            amount_cents=200,
            currency="USD",
            payment_type="priority_bump",
            status="succeeded",
            created_at=now,
            updated_at=now,
        )
        db.add(p)
    await db.commit()
    return _payment_venue


# ---------------------------------------------------------------------------
# Mock Stripe
# ---------------------------------------------------------------------------

def _mock_stripe():
    mock = MagicMock()
    mock.PaymentIntent.create.return_value = MagicMock(
        id="pi_test_123",
        client_secret="pi_test_123_secret",
    )
    mock.Webhook.construct_event = MagicMock(side_effect=lambda payload, sig, secret: json.loads(payload))
    return mock


# ---------------------------------------------------------------------------
# Tip endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.routers.payments._stripe_client", None)
@patch("app.routers.payments._get_stripe")
async def test_tip_create_payment_intent(mock_get_stripe, client: AsyncClient, _payment_venue):
    mock_get_stripe.return_value = _mock_stripe()
    venue_id, kj, singer, _, _, _ = _payment_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{venue_id}/payments/tip",
        json={"amount_cents": 500, "currency": "USD", "recipient_id": kj.id},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["payment_intent_id"] == "pi_test_123"
    assert data["client_secret"] == "pi_test_123_secret"


@pytest.mark.asyncio
@patch("app.routers.payments._stripe_client", None)
@patch("app.routers.payments._get_stripe")
async def test_tip_recipient_not_found(mock_get_stripe, client: AsyncClient, _payment_venue):
    mock_get_stripe.return_value = _mock_stripe()
    venue_id, _, singer, _, _, _ = _payment_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{venue_id}/payments/tip",
        json={"amount_cents": 500, "recipient_id": str(uuid.uuid4())},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
@patch("app.routers.payments._stripe_client", None)
@patch("app.routers.payments._get_stripe")
async def test_tip_wrong_venue(mock_get_stripe, client: AsyncClient, _payment_venue):
    mock_get_stripe.return_value = _mock_stripe()
    _, _, singer, _, _, _ = _payment_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{str(uuid.uuid4())}/payments/tip",
        json={"amount_cents": 500, "recipient_id": str(uuid.uuid4())},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_tip_below_minimum(client: AsyncClient, _payment_venue):
    venue_id, kj, singer, _, _, _ = _payment_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{venue_id}/payments/tip",
        json={"amount_cents": 50, "recipient_id": kj.id},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# Priority bump
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("app.routers.payments._stripe_client", None)
@patch("app.routers.payments._get_stripe")
async def test_priority_bump_create_payment_intent(mock_get_stripe, client: AsyncClient, _payment_venue):
    mock_get_stripe.return_value = _mock_stripe()
    venue_id, _, singer, _, _, qr = _payment_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{venue_id}/payments/priority-bump",
        json={"amount_cents": 200, "request_id": qr.id},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["payment_intent_id"] == "pi_test_123"


@pytest.mark.asyncio
async def test_priority_bump_request_not_found(client: AsyncClient, _payment_venue):
    venue_id, _, singer, _, _, _ = _payment_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{venue_id}/payments/priority-bump",
        json={"amount_cents": 200, "request_id": str(uuid.uuid4())},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_priority_bump_max_limit(client: AsyncClient, db: AsyncSession, _payment_venue):
    venue_id, _, singer, _, _, qr = _payment_venue
    token = _token(singer)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for _ in range(2):
        p = Payment(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            singer_id=singer.id,
            amount_cents=200,
            currency="USD",
            payment_type="priority_bump",
            status="succeeded",
            created_at=now,
            updated_at=now,
        )
        db.add(p)
    await db.commit()

    r = await client.post(
        f"/v1/venues/{venue_id}/payments/priority-bump",
        json={"amount_cents": 200, "request_id": qr.id},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_409_CONFLICT
    assert "Maximum" in r.json()["detail"]


@pytest.mark.asyncio
async def test_priority_bump_below_minimum(client: AsyncClient, _payment_venue):
    venue_id, _, singer, _, _, qr = _payment_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{venue_id}/payments/priority-bump",
        json={"amount_cents": 50, "request_id": qr.id},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# Payment history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_history_paginated(client: AsyncClient, _payment_venue):
    _, _, singer, _, _, _ = _payment_venue
    token = _token(singer)
    venue_id = singer.venue_id

    r = await client.get(
        f"/v1/venues/{venue_id}/payments/history",
        params={"page": 1, "per_page": 10},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_payment_history_wrong_venue(client: AsyncClient, _payment_venue):
    _, _, singer, _, _, _ = _payment_venue
    token = _token(singer)

    r = await client.get(
        f"/v1/venues/{str(uuid.uuid4())}/payments/history",
        params={"page": 1, "per_page": 10},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_tip_succeeded(client: AsyncClient, _payment_venue):
    _, _, _, _, _, _ = _payment_venue

    payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_webhook_123",
                "metadata": {
                    "payment_id": str(uuid.uuid4()),
                },
            }
        }
    }
    r = await client.post(
        "/v1/venues/test/payments/webhook",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    # Should be ignored since payment_id doesn't exist
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_invalid_payload(client: AsyncClient, _payment_venue):
    r = await client.post(
        "/v1/venues/test/payments/webhook",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_webhook_payment_failed(client: AsyncClient, _payment_venue):
    payload = {
        "type": "payment_intent.payment_failed",
        "data": {
            "object": {
                "id": "pi_fail_123",
            }
        }
    }
    r = await client.post(
        "/v1/venues/test/payments/webhook",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == status.HTTP_200_OK
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Formatted amount display
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payment_out_formatting():
    from app.routers.payments import _format_cents
    assert _format_cents(100) == "$1.00"
    assert _format_cents(500) == "$5.00"
    assert _format_cents(1234) == "$12.34"
    assert _format_cents(0) == "$0.00"
