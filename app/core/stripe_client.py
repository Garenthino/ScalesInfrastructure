"""Stripe SDK client lifecycle.

Provides a lazy-initialized, app-wide StripeClient singleton that safely
handles missing configuration in development/test environments.
"""

from __future__ import annotations

from typing import Any

import stripe as stripe_module

from app.core.config import settings


_stripe_client: stripe_module.StripeClient | None = None


def get_stripe_client() -> stripe_module.StripeClient | None:
    """Return the app StripeClient, or None if no secret key is configured."""
    global _stripe_client
    if _stripe_client is not None:
        return _stripe_client

    key = settings.STRIPE_SECRET_KEY or settings.STRIPE_TEST_SECRET_KEY
    if not key:
        return None

    _stripe_client = stripe_module.StripeClient(key)
    return _stripe_client


def stripe_enabled() -> bool:
    """Return True when Stripe is configured and ready to use."""
    return get_stripe_client() is not None


def invalidate_stripe_client() -> None:
    """Reset the cached Stripe client. Useful in tests."""
    global _stripe_client
    _stripe_client = None
