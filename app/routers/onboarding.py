"""Public venue onboarding router.

Endpoints
---------
Public:
    POST /onboarding/venue           — self-serve venue + owner signup
    GET  /onboarding/check-slug/{slug} — slug availability

Authenticated:
    GET  /onboarding/me              — current venue + owner profile
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.core.db import get_db, async_session_factory
from app.core.security import hash_password, create_access_token, create_refresh_token
from app.core.auth import get_current_user, SingerUser
from app.core.rls import set_session_venue_id
from app.models import Venue, Singer, KJDevice, _now_iso, _venue_code
from app.schemas import (
    VenueSignupRequest,
    VenueSignupResponse,
    VenueOut,
    VenueStats,
    VenueAddress,
    VenueContact,
    VenueBranding,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _serialize_address(venue: Venue) -> VenueAddress:
    if venue.address:
        try:
            return VenueAddress(**__import__("json").loads(venue.address))
        except Exception:
            pass
    return VenueAddress()


def _serialize_contact(venue: Venue) -> VenueContact:
    if venue.contact_json:
        try:
            return VenueContact(**__import__("json").loads(venue.contact_json))
        except Exception:
            pass
    return VenueContact()


def _serialize_branding(venue: Venue) -> VenueBranding:
    if venue.branding_json:
        try:
            return VenueBranding(**__import__("json").loads(venue.branding_json))
        except Exception:
            pass
    return VenueBranding()


def _issue_token_pair(singer: Singer) -> dict[str, Any]:
    claims = {
        "venue_id": singer.venue_id,
        "role": getattr(singer, "role", "singer"),
    }
    return {
        "access_token": create_access_token(str(singer.id), extra_claims=claims),
        "token_type": "bearer",
        "expires_in": 60 * 15,
        "refresh_token": create_refresh_token(str(singer.id), extra_claims=claims),
    }


def _venue_out(venue: Venue) -> VenueOut:
    return VenueOut(
        id=venue.id,
        name=venue.name,
        slug=venue.slug,
        venue_code=venue.venue_code,
        address=_serialize_address(venue),
        contact=_serialize_contact(venue),
        timezone=venue.timezone or "UTC",
        branding=_serialize_branding(venue),
        settings=None,
        operating_hours=None,
        is_active=bool(venue.is_active),
        created_at=venue.created_at,
        updated_at=venue.updated_at,
        deleted_at=venue.deleted_at,
        stats=None,
    )


async def _check_slug_available(db: AsyncSession, slug: str) -> bool:
    existing = await db.execute(
        select(func.count())
        .select_from(Venue)
        .where(Venue.slug == slug, Venue.deleted_at.is_(None))
    )
    return existing.scalar_one() == 0


async def _check_email_available(db: AsyncSession, email: str) -> bool:
    existing = await db.execute(
        select(func.count())
        .select_from(Singer)
        .where(Singer.email == email, Singer.deleted_at.is_(None))
    )
    return existing.scalar_one() == 0


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

@router.post("/venue", response_model=VenueSignupResponse, status_code=status.HTTP_201_CREATED)
async def signup_venue(body: VenueSignupRequest, db: AsyncSession = Depends(get_db)):
    """Create a new venue and owner singer. Public, self-serve endpoint."""

    # Validate slug format
    if not _SLUG_RE.match(body.slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug may only contain lowercase letters, numbers, and hyphens.",
        )

    # Unique slug
    if not await _check_slug_available(db, body.slug):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That venue URL slug is already taken.",
        )

    # Unique email
    if not await _check_email_available(db, body.owner_email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    venue_id = str(uuid.uuid4())
    singer_id = str(uuid.uuid4())
    code = _venue_code()
    now = _now_iso()

    # Phase 1: no Stripe; venue is in manual/trial mode for dashboard/Android.
    # Hosting software trial is tracked separately in the Windows app.
    venue = Venue(
        id=venue_id,
        name=body.venue_name,
        slug=body.slug,
        venue_code=code,
        timezone=body.timezone or "UTC",
        is_active=1,
        billing_email=body.owner_email,
        subscription_status="trialing",
        billing_status="trial",
        signup_source=body.signup_source,
        sales_rep_email=body.sales_rep_email,
    )

    owner = Singer(
        id=singer_id,
        venue_id=venue_id,
        stage_name=body.owner_stage_name,
        email=body.owner_email,
        password_hash=hash_password(body.owner_password),
        role="owner",
        created_at=now,
        updated_at=now,
    )

    db.add(venue)
    db.add(owner)
    await db.commit()
    await db.refresh(venue)
    await db.refresh(owner)

    tokens = _issue_token_pair(owner)
    return VenueSignupResponse(
        venue_id=venue.id,
        singer_id=owner.id,
        venue_code=venue.venue_code,
        access_token=tokens["access_token"],
        token_type="bearer",
        expires_in=tokens["expires_in"],
        refresh_token=tokens["refresh_token"],
    )


@router.get("/check-slug/{slug}")
async def check_slug(slug: str, db: AsyncSession = Depends(get_db)):
    """Return whether a venue slug is available."""
    if not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug may only contain lowercase letters, numbers, and hyphens.",
        )
    available = await _check_slug_available(db, slug)
    return {"slug": slug, "available": available}


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------

@router.get("/me", response_model=VenueOut)
async def onboarding_me(
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's venue profile."""
    await set_session_venue_id(db, current.venue_id)
    venue = await db.execute(
        select(Venue).where(Venue.id == current.venue_id, Venue.deleted_at.is_(None))
    )
    venue = venue.scalar_one_or_none()
    if not venue:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return _venue_out(venue)
