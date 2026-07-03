"""Billing lifecycle helpers.

Shared logic for subscription status, trial/grace-period windows, and
billing-aware feature gating.  This module is intentionally Stripe-agnostic
so it can be unit-tested without the Stripe SDK.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from app.models import Venue


GRACE_PERIOD_DAYS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Handle both "Z" and offset formats
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_active_for_billing(venue: Venue) -> bool:
    """Return True if the venue can use paid features right now.

    A venue is active when it is not soft-deleted and its billing state is
    either trialing (before trial_ends_at), active, or within the grace
    period after a missed payment.
    """
    if not venue.is_active or venue.deleted_at:
        return False

    status = (venue.subscription_status or "trialing").lower()
    if status in {"active", "comped"}:
        return True

    if status == "trialing":
        trial_end = _parse_iso(venue.trial_ends_at)
        if trial_end is None:
            return True
        return _now() <= trial_end

    if status == "past_due":
        return in_grace_period(venue)

    # cancelled
    return False


def in_grace_period(venue: Venue) -> bool:
    """Return True if a past_due venue is still within the grace window."""
    if venue.subscription_status != "past_due":
        return False
    plan_expires = _parse_iso(venue.plan_expires_at)
    if plan_expires is None:
        return False
    grace_end = plan_expires + timedelta(days=GRACE_PERIOD_DAYS)
    return _now() <= grace_end


def grace_period_ends_at(venue: Venue) -> str | None:
    """Return the ISO timestamp when the grace period ends, if applicable."""
    if not in_grace_period(venue):
        return None
    plan_expires = _parse_iso(venue.plan_expires_at)
    assert plan_expires is not None
    return _format_iso(plan_expires + timedelta(days=GRACE_PERIOD_DAYS))


def is_trialing(venue: Venue) -> bool:
    """Return True if the venue is currently in its trial period."""
    if venue.subscription_status != "trialing":
        return False
    trial_end = _parse_iso(venue.trial_ends_at)
    if trial_end is None:
        return True
    return _now() <= trial_end


def set_trial_dates(venue: Venue, days: int = 14) -> None:
    """Set trial_ends_at N days from now and keep the venue trialing."""
    now = _now()
    venue.trial_ends_at = _format_iso(now + timedelta(days=days))
    venue.plan_expires_at = None
    venue.subscription_status = "trialing"
    venue.billing_status = "trial"


def set_active_subscription(
    venue: Venue,
    stripe_subscription_id: str,
    period_end: datetime,
) -> None:
    """Mark the venue as having an active paid subscription."""
    venue.stripe_subscription_id = stripe_subscription_id
    venue.subscription_status = "active"
    venue.billing_status = "active"
    venue.plan_expires_at = _format_iso(period_end)


def set_past_due(venue: Venue) -> None:
    """Mark the venue as past due (grace period begins at plan_expires_at)."""
    venue.subscription_status = "past_due"
    venue.billing_status = "past_due"


def set_cancelled(venue: Venue) -> None:
    """Mark the venue as cancelled after the grace period ends."""
    venue.subscription_status = "cancelled"
    venue.billing_status = "cancelled"


def price_id_for_tier(tier: Literal["basic", "enterprise"]) -> str | None:
    """Return the configured Stripe price id for a subscription tier."""
    from app.core.config import settings

    if tier == "enterprise":
        return settings.STRIPE_PRICE_ID_ENTERPRISE
    return settings.STRIPE_PRICE_ID_BASIC


def subscription_status_for_event(event_status: str | None) -> str:
    """Map Stripe subscription status to the canonical Venue subscription_status.

    Stripe statuses: active, past_due, unpaid, canceled, cancelled, trialing,
    paused, incomplete, incomplete_expired.
    """
    if not event_status:
        return "active"
    status = event_status.lower()
    if status in {"active", "trialing"}:
        return status
    if status in {"canceled", "cancelled"}:
        return "cancelled"
    if status in {"past_due", "unpaid", "incomplete", "incomplete_expired"}:
        return "past_due"
    return "active"
