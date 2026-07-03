"""Billing router: subscription checkout + status.

Endpoints
---------
Owner/admin:
    POST /billing/checkout-session     — create Stripe Checkout session for a subscription
    GET  /billing/status               — current subscription status with trial/grace info

Webhook:
    POST /billing/webhook              — Stripe webhook handler (mounted separately)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.auth import get_current_user, SingerUser
from app.core.config import settings
from app.core.db import get_db
from app.core.stripe_client import get_stripe_client, stripe_enabled
from app.core.permissions import Role, has_role
from app.models import Venue, BillingEvent
from app.schemas import (
    CheckoutSessionRequest,
    CheckoutSessionOut,
    SubscriptionStatusOut,
)
from app.services.billing_lifecycle import (
    _format_iso,
    price_id_for_tier,
    is_active_for_billing,
    is_trialing,
    in_grace_period,
    grace_period_ends_at,
    subscription_status_for_event,
    set_active_subscription,
    set_past_due,
    set_cancelled,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _require_own_venue(
    current: SingerUser,
    venue_id: str,
    db: AsyncSession,
) -> Venue:
    """Resolve the venue and enforce that the caller owns or admins it."""
    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    is_admin = has_role(current.role, Role.ADMIN)
    if not is_admin and str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    return venue


# ---------------------------------------------------------------------------
# Checkout session
# ---------------------------------------------------------------------------

@router.post("/checkout-session", response_model=CheckoutSessionOut)
async def create_checkout_session(
    venue_id: str,
    body: CheckoutSessionRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for a subscription.

    Requires owner or platform admin.  The venue must already have a
    Stripe customer id (created during signup).  If it does not, we attempt
    to create it on the fly before starting checkout.
    """
    venue = await _require_own_venue(current, venue_id, db)

    if not stripe_enabled():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe billing is not configured",
        )

    client = get_stripe_client()
    assert client is not None

    # Ensure Stripe customer exists
    if not venue.stripe_customer_id:
        from app.services.billing_customer import create_stripe_customer_for_venue
        await create_stripe_customer_for_venue(db, venue)
        if not venue.stripe_customer_id:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                detail="Unable to create Stripe customer for this venue",
            )

    price_id = price_id_for_tier(body.tier)
    if not price_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Stripe price id for tier '{body.tier}' is not configured",
        )

    try:
        session = client.v1.checkout.sessions.create(
            params={
                "customer": venue.stripe_customer_id,
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": body.success_url,
                "cancel_url": body.cancel_url,
                "metadata": {
                    "venue_id": venue.id,
                    "tier": body.tier,
                },
                "subscription_data": {
                    "metadata": {
                        "venue_id": venue.id,
                        "tier": body.tier,
                    },
                },
            }
        )
    except Exception as exc:
        logger.exception("Stripe checkout session creation failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe checkout error: {exc}",
        )

    # Update tier choice optimistically so the UI reflects intent
    if body.tier != venue.subscription_tier:
        venue.subscription_tier = body.tier
        venue.updated_at = _now_iso()
        await db.commit()
        await db.refresh(venue)

    return CheckoutSessionOut(
        checkout_url=session.url,
        session_id=session.id,
        stripe_customer_id=venue.stripe_customer_id,
    )


# ---------------------------------------------------------------------------
# Subscription status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=SubscriptionStatusOut)
async def get_subscription_status(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current subscription status including trial and grace info."""
    venue = await _require_own_venue(current, venue_id, db)

    return SubscriptionStatusOut(
        venue_id=venue.id,
        subscription_tier=venue.subscription_tier or "basic",
        subscription_status=venue.subscription_status or "trialing",
        billing_status=venue.billing_status or "trial",
        trial_ends_at=venue.trial_ends_at,
        plan_expires_at=venue.plan_expires_at,
        stripe_subscription_id=venue.stripe_subscription_id,
        is_trialing=is_trialing(venue),
        in_grace_period=in_grace_period(venue),
        grace_period_ends_at=grace_period_ends_at(venue),
    )


# ---------------------------------------------------------------------------
# Webhook handler (mounted under /billing/webhook)
# ---------------------------------------------------------------------------

async def handle_billing_webhook(
    request: Request,
    stripe_signature: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    """Validate and dispatch Stripe billing webhooks.

    Handles:
    - checkout.session.completed
    - invoice.payment_succeeded
    - invoice.payment_failed
    """
    payload = await request.body()
    client = get_stripe_client()

    event: dict[str, Any]
    if client and settings.STRIPE_WEBHOOK_SECRET and stripe_signature:
        try:
            event = client.webhooks.construct_event(
                payload=payload,
                sig_header=stripe_signature,
                secret=settings.STRIPE_WEBHOOK_SECRET,
            )
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Webhook validation failed: {exc}",
            )
    else:
        # Dev/test fallback: parse raw JSON
        import json
        try:
            event = json.loads(payload)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload: {exc}",
            )

    event_type = event.get("type", "")
    event_id = event.get("id")
    data_object = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        return await _handle_checkout_completed(db, event_id, data_object)
    if event_type == "invoice.payment_succeeded":
        return await _handle_invoice_payment_succeeded(db, event_id, data_object)
    if event_type == "invoice.payment_failed":
        return await _handle_invoice_payment_failed(db, event_id, data_object)

    return {"status": "ignored", "event_id": event_id, "reason": "unhandled event type"}


async def _handle_checkout_completed(
    db: AsyncSession,
    event_id: str | None,
    data_object: dict[str, Any],
) -> dict[str, Any]:
    """Persist the new subscription id and move the venue to active."""
    venue_id = data_object.get("metadata", {}).get("venue_id")
    if not venue_id:
        venue_id = data_object.get("subscription_data", {}).get("metadata", {}).get("venue_id")
    if not venue_id:
        return {"status": "ignored", "event_id": event_id, "reason": "no venue_id in session metadata"}

    if event_id and await _event_already_processed(db, venue_id, event_id):
        return {"status": "ignored", "event_id": event_id, "reason": "event already processed"}

    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        return {"status": "ignored", "event_id": event_id, "reason": "venue not found"}

    subscription_id = data_object.get("subscription")
    if not subscription_id:
        return {"status": "ignored", "event_id": event_id, "reason": "no subscription id"}

    # Fetch subscription to get current period end and status
    client = get_stripe_client()
    period_end: datetime | None = None
    subscription_status = "active"
    if client:
        try:
            subscription = client.v1.subscriptions.retrieve(
                subscription_id,
                params={"expand": ["latest_invoice"]},
            )
            subscription_status = getattr(subscription, "status", "active")
            period_end_ts = getattr(subscription, "current_period_end", None)
            if period_end_ts:
                period_end = datetime.fromtimestamp(period_end_ts, tz=timezone.utc)
        except Exception as exc:
            logger.warning("Failed to retrieve subscription %s: %s", subscription_id, exc)

    status = subscription_status_for_event(subscription_status)
    if status == "active" and period_end:
        set_active_subscription(venue, subscription_id, period_end)
    elif status == "past_due":
        venue.stripe_subscription_id = subscription_id
        set_past_due(venue)
    elif status == "cancelled":
        venue.stripe_subscription_id = subscription_id
        set_cancelled(venue)
    else:
        venue.stripe_subscription_id = subscription_id
        venue.subscription_status = status

    venue.updated_at = _now_iso()
    await _record_billing_event(db, venue_id, event_id, "checkout.session.completed", subscription_id)
    await db.commit()

    return {"status": "ok", "event_id": event_id, "venue_id": venue_id}


async def _handle_invoice_payment_succeeded(
    db: AsyncSession,
    event_id: str | None,
    data_object: dict[str, Any],
) -> dict[str, Any]:
    """Renew the active subscription period."""
    subscription_id = data_object.get("subscription")
    if not subscription_id:
        return {"status": "ignored", "event_id": event_id, "reason": "no subscription id"}

    venue = (
        await db.execute(
            select(Venue).where(
                Venue.stripe_subscription_id == subscription_id,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        return {"status": "ignored", "event_id": event_id, "reason": "subscription not linked to venue"}

    if event_id and await _event_already_processed(db, venue.id, event_id):
        return {"status": "ignored", "event_id": event_id, "reason": "event already processed"}

    period_end_ts = data_object.get("period_end")
    period_end: datetime | None = None
    if period_end_ts:
        period_end = datetime.fromtimestamp(period_end_ts, tz=timezone.utc)

    if period_end:
        venue.plan_expires_at = _format_iso(period_end)
    venue.subscription_status = "active"
    venue.billing_status = "active"
    venue.updated_at = _now_iso()

    await _record_billing_event(db, venue.id, event_id, "invoice.payment_succeeded", subscription_id)
    await db.commit()

    return {"status": "ok", "event_id": event_id, "venue_id": venue.id}


async def _handle_invoice_payment_failed(
    db: AsyncSession,
    event_id: str | None,
    data_object: dict[str, Any],
) -> dict[str, Any]:
    """Move the venue to past_due; grace period starts at plan_expires_at."""
    subscription_id = data_object.get("subscription")
    if not subscription_id:
        return {"status": "ignored", "event_id": event_id, "reason": "no subscription id"}

    venue = (
        await db.execute(
            select(Venue).where(
                Venue.stripe_subscription_id == subscription_id,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        return {"status": "ignored", "event_id": event_id, "reason": "subscription not linked to venue"}

    if event_id and await _event_already_processed(db, venue.id, event_id):
        return {"status": "ignored", "event_id": event_id, "reason": "event already processed"}

    set_past_due(venue)
    venue.updated_at = _now_iso()

    await _record_billing_event(db, venue.id, event_id, "invoice.payment_failed", subscription_id)
    await db.commit()

    return {"status": "ok", "event_id": event_id, "venue_id": venue.id}


async def _event_already_processed(
    db: AsyncSession,
    venue_id: str,
    event_id: str,
) -> bool:
    """Check whether this Stripe event id has already been handled."""
    result = await db.execute(
        select(BillingEvent).where(
            BillingEvent.venue_id == venue_id,
            BillingEvent.stripe_event_id == event_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def _record_billing_event(
    db: AsyncSession,
    venue_id: str,
    event_id: str | None,
    event_type: str,
    subscription_id: str | None,
) -> None:
    """Idempotency record for webhook events."""
    if not event_id:
        return
    db.add(
        BillingEvent(
            venue_id=venue_id,
            stripe_event_id=event_id,
            event_type=event_type,
            stripe_subscription_id=subscription_id,
            processed=1,
            created_at=_now_iso(),
        )
    )


@router.post("/webhook")
async def billing_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """Stripe webhook entrypoint for subscription lifecycle events."""
    return await handle_billing_webhook(request, stripe_signature, db)
