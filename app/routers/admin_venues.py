"""Admin venue management router.

Endpoints
---------
All require platform admin role.

    GET  /admin/venues                 — list all venues with stats
    GET  /admin/venues/{venue_id}      — full venue detail
    PUT  /admin/venues/{venue_id}/status — update billing/tier/status
    POST /admin/venues/{venue_id}/impersonate — issue owner-scoped support token
    POST /admin/venues/provision       — sales-assisted venue creation
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.core.auth import require_platform_admin
from app.core.db import get_db
from app.core.security import hash_password, create_access_token, create_refresh_token
from app.models import Venue, Singer, KJDevice, QueueRequest, _now_iso, _venue_code
from app.schemas import (
    PaginatedResponse,
    AdminVenueOut,
    AdminVenueListItem,
    AdminVenueStatusUpdate,
    AdminVenueProvisionRequest,
    VenueBillingOut,
    VenueStats,
    VenueAddress,
    VenueContact,
    VenueBranding,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_address(venue: Venue) -> VenueAddress:
    raw = venue.address
    if raw:
        try:
            return VenueAddress(**__import__("json").loads(raw))
        except Exception:
            pass
    return VenueAddress()


def _serialize_contact(venue: Venue) -> VenueContact:
    raw = venue.contact_json
    if raw:
        try:
            return VenueContact(**__import__("json").loads(raw))
        except Exception:
            pass
    return VenueContact()


def _serialize_branding(venue: Venue) -> VenueBranding:
    raw = venue.branding_json
    if raw:
        try:
            return VenueBranding(**__import__("json").loads(raw))
        except Exception:
            pass
    return VenueBranding()


def _billing_out(venue: Venue) -> VenueBillingOut:
    return VenueBillingOut(
        subscription_tier=venue.subscription_tier or "basic",
        subscription_status=venue.subscription_status or "trialing",
        billing_status=venue.billing_status or "trial",
        plan_expires_at=venue.plan_expires_at,
        trial_ends_at=venue.trial_ends_at,
        billing_email=venue.billing_email,
        signup_source=venue.signup_source or "self_serve",
        sales_rep_email=venue.sales_rep_email,
    )


def _issue_owner_token(owner: Singer) -> dict[str, Any]:
    claims = {
        "venue_id": owner.venue_id,
        "role": "owner",
    }
    return {
        "access_token": create_access_token(str(owner.id), extra_claims=claims, expires_delta=__import__("datetime").timedelta(minutes=15)),
        "token_type": "bearer",
        "expires_in": 15 * 60,
    }


async def _get_venue_stats(db: AsyncSession, venue_id: str) -> dict[str, int]:
    singers = (
        await db.execute(
            select(func.count())
            .select_from(Singer)
            .where(Singer.venue_id == venue_id, Singer.deleted_at.is_(None))
        )
    ).scalar_one()
    kj_devices = (
        await db.execute(
            select(func.count())
            .select_from(KJDevice)
            .where(KJDevice.venue_id == venue_id)
        )
    ).scalar_one()
    queue_depth = (
        await db.execute(
            select(func.count())
            .select_from(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status.in_(("pending", "approved", "now_playing")),
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    return {
        "total_singers": singers,
        "total_kj_devices": kj_devices,
        "queue_depth": queue_depth,
    }


async def _get_owner_email(db: AsyncSession, venue_id: str) -> str | None:
    result = await db.execute(
        select(Singer.email)
        .where(
            Singer.venue_id == venue_id,
            Singer.role == "owner",
            Singer.deleted_at.is_(None),
        )
        .order_by(Singer.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _admin_venue_out(venue: Venue, stats: dict[str, int], owner_email: str | None) -> AdminVenueOut:
    return AdminVenueOut(
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
        stats=VenueStats(
            queue_depth=stats["queue_depth"],
            current_song=None,
            total_songs=0,
            total_singers=stats["total_singers"],
            active_singers=0,
        ),
        billing=_billing_out(venue),
        owner_email=owner_email,
        total_singers=stats["total_singers"],
        total_kj_devices=stats["total_kj_devices"],
        queue_depth=stats["queue_depth"],
    )


async def _check_email_available(db: AsyncSession, email: str) -> bool:
    existing = await db.execute(
        select(func.count())
        .select_from(Singer)
        .where(Singer.email == email, Singer.deleted_at.is_(None))
    )
    return existing.scalar_one() == 0


async def _check_slug_available(db: AsyncSession, slug: str) -> bool:
    existing = await db.execute(
        select(func.count())
        .select_from(Venue)
        .where(Venue.slug == slug, Venue.deleted_at.is_(None))
    )
    return existing.scalar_one() == 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/venues", response_model=PaginatedResponse[AdminVenueListItem])
async def list_venues(
    _: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=100),
    status: str | None = Query(None),
    tier: str | None = Query(None),
):
    """List all venues with aggregate stats. Platform admin only."""

    filters = [Venue.deleted_at.is_(None)]
    if search:
        like = f"%{search}%"
        filters.append(
            (Venue.name.ilike(like))
            | (Venue.slug.ilike(like))
            | (Venue.venue_code.ilike(like))
        )
    if status:
        filters.append(Venue.subscription_status == status)
    if tier:
        filters.append(Venue.subscription_tier == tier)

    total = (
        await db.execute(
            select(func.count()).select_from(Venue).where(*filters)
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    venues = (
        await db.execute(
            select(Venue)
            .where(*filters)
            .order_by(Venue.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
    ).scalars().all()

    items: list[AdminVenueListItem] = []
    for venue in venues:
        stats = await _get_venue_stats(db, venue.id)
        owner_email = await _get_owner_email(db, venue.id)
        items.append(
            AdminVenueListItem(
                id=venue.id,
                name=venue.name,
                slug=venue.slug,
                venue_code=venue.venue_code,
                timezone=venue.timezone or "UTC",
                is_active=bool(venue.is_active),
                billing=_billing_out(venue),
                owner_email=owner_email,
                total_singers=stats["total_singers"],
                total_kj_devices=stats["total_kj_devices"],
                queue_depth=stats["queue_depth"],
                created_at=venue.created_at,
            )
        )

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/venues/{venue_id}", response_model=AdminVenueOut)
async def get_venue(
    venue_id: str,
    _: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get full venue details including billing and stats."""
    venue = (
        await db.execute(
            select(Venue).where(Venue.id == venue_id, Venue.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not venue:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    stats = await _get_venue_stats(db, venue_id)
    owner_email = await _get_owner_email(db, venue_id)
    return _admin_venue_out(venue, stats, owner_email)


@router.put("/venues/{venue_id}/status", response_model=AdminVenueOut)
async def update_venue_status(
    venue_id: str,
    body: AdminVenueStatusUpdate,
    _: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update venue billing/tier/status fields."""
    venue = (
        await db.execute(
            select(Venue).where(Venue.id == venue_id, Venue.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not venue:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    data = body.model_dump(exclude_unset=True)
    allowed = {
        "is_active",
        "subscription_tier",
        "subscription_status",
        "billing_status",
        "plan_expires_at",
        "trial_ends_at",
        "sales_rep_email",
    }
    for key, value in data.items():
        if key in allowed and hasattr(venue, key):
            setattr(venue, key, value)

    venue.updated_at = _now_iso()
    await db.commit()
    await db.refresh(venue)

    stats = await _get_venue_stats(db, venue_id)
    owner_email = await _get_owner_email(db, venue_id)
    return _admin_venue_out(venue, stats, owner_email)


@router.post("/venues/{venue_id}/impersonate")
async def impersonate_venue_owner(
    venue_id: str,
    _: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Generate a short-lived owner token for support."""
    owner = (
        await db.execute(
            select(Singer)
            .where(
                Singer.venue_id == venue_id,
                Singer.role == "owner",
                Singer.deleted_at.is_(None),
            )
            .order_by(Singer.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not owner:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="No owner found for this venue",
        )

    token = _issue_owner_token(owner)
    return {
        "singer_id": owner.id,
        "venue_id": owner.venue_id,
        "access_token": token["access_token"],
        "token_type": token["token_type"],
        "expires_in": token["expires_in"],
    }


@router.post("/venues/provision", response_model=AdminVenueOut, status_code=status.HTTP_201_CREATED)
async def provision_venue(
    body: AdminVenueProvisionRequest,
    _: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Sales-assisted venue provisioning. Creates venue + owner."""

    if not await _check_slug_available(db, body.slug):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Venue slug already exists",
        )
    if not await _check_email_available(db, body.owner_email):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    venue_id = str(uuid.uuid4())
    singer_id = str(uuid.uuid4())
    now = _now_iso()

    venue = Venue(
        id=venue_id,
        name=body.venue_name,
        slug=body.slug,
        venue_code=_venue_code(),
        timezone=body.timezone or "UTC",
        is_active=1,
        subscription_tier=body.subscription_tier,
        billing_email=body.owner_email,
        subscription_status="trialing",
        billing_status="trial",
        signup_source="sales_assisted",
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

    stats = await _get_venue_stats(db, venue_id)
    owner_email = await _get_owner_email(db, venue_id)
    return _admin_venue_out(venue, stats, owner_email)
