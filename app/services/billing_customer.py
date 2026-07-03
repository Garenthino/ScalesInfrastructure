"""Stripe customer lifecycle helpers.

Creating a Stripe Customer is a side effect of venue creation.  We isolate it
here so that onboarding and admin provisioning can share the same logic, and
so that failures are logged but do not block the core signup flow.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.stripe_client import get_stripe_client, stripe_enabled
from app.models import Venue

logger = logging.getLogger(__name__)


async def create_stripe_customer_for_venue(
    db: AsyncSession,
    venue: Venue,
) -> str | None:
    """Create a Stripe Customer for this venue and persist the id.

    Returns the Stripe customer id, or None when Stripe is not configured.
    Never raises — failures are logged and swallowed so signup continues.
    """
    if not stripe_enabled():
        logger.debug("Stripe not configured; skipping customer creation for venue %s", venue.id)
        return None

    client = get_stripe_client()
    assert client is not None

    try:
        params: dict[str, Any] = {
            "name": venue.name,
            "metadata": {"venue_id": venue.id, "venue_slug": venue.slug},
        }
        if venue.billing_email:
            params["email"] = venue.billing_email

        customer = client.v1.customers.create(params=params)
        stripe_customer_id = customer.id

        venue.stripe_customer_id = stripe_customer_id
        await db.flush()
        logger.info(
            "Created Stripe customer %s for venue %s",
            stripe_customer_id,
            venue.id,
        )
        return stripe_customer_id
    except Exception as exc:
        logger.exception(
            "Failed to create Stripe customer for venue %s: %s",
            venue.id,
            exc,
        )
        return None
