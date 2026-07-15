"""Venue CRUD router — multi-tenant backbone for Scales.

RBAC:
- platform_admin: full CRUD, access to all venues
- venue_admin / kj: access to their own venue only
- singer: list (own venue), get (own venue)

JWT claims carry venue_id for venue_admin, kj, platform_admin.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.queue_service import SingerEventPublisher
from app.core.security import create_access_token, create_refresh_token
from app.core.auth import get_current_user, SingerUser
from app.core.permissions import Role, has_role
from app.core.db import get_db
from app.models import Venue, Song, Singer, QueueRequest, Account
from app.schemas import (
    VenueCreate,
    VenueUpdate,
    VenueOut,
    VenueCompactOut,
    PaginatedResponse,
    VenueBranding,
    VenueAddress,
    VenueContact,
    VenueStats,
    TokenPairOut,
)

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_platform_admin(current: SingerUser) -> None:
    if not has_role(current.role, Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )


def _serialize_branding(venue: Venue) -> VenueBranding:
    raw = venue.branding_json
    if raw:
        try:
            data = json.loads(raw)
            return VenueBranding(**data)
        except Exception:
            pass
    return VenueBranding()


def _serialize_address(venue: Venue) -> VenueAddress:
    raw = venue.address
    if raw:
        try:
            data = json.loads(raw)
            return VenueAddress(**data)
        except Exception:
            pass
    return VenueAddress()


def _serialize_contact(venue: Venue) -> VenueContact:
    raw = venue.contact_json
    if raw:
        try:
            data = json.loads(raw)
            return VenueContact(**data)
        except Exception:
            pass
    return VenueContact()


def _venue_out(venue: Venue, stats: VenueStats | None = None) -> VenueOut:
    return VenueOut(
        id=venue.id,
        name=venue.name,
        slug=venue.slug,
        venue_code=venue.venue_code,
        address=_serialize_address(venue),
        contact=_serialize_contact(venue),
        timezone=venue.timezone or "UTC",
        branding=_serialize_branding(venue),
        settings=None,  # stored in venue_configs table; out of scope for now
        operating_hours=None,  # stored in venue_configs table; out of scope for now
        is_active=bool(venue.is_active),
        created_at=venue.created_at,
        updated_at=venue.updated_at,
        deleted_at=venue.deleted_at,
        stats=stats,
    )


def _venue_compact(venue: Venue) -> VenueCompactOut:
    return VenueCompactOut(
        id=venue.id,
        name=venue.name,
        slug=venue.slug,
        venue_code=venue.venue_code,
        timezone=venue.timezone or "UTC",
        is_active=bool(venue.is_active),
    )


def _build_branding_json(body: VenueCreate | VenueUpdate) -> str | None:
    if body.branding is None:
        return None
    data = body.branding.model_dump(exclude_unset=True)
    if not data:
        return None
    return json.dumps(data)


def _build_address_json(body: VenueCreate | VenueUpdate) -> str | None:
    if body.address is None:
        return None
    data = body.address.model_dump(exclude_unset=True)
    if not data:
        return None
    return json.dumps(data)


def _build_contact_json(body: VenueCreate | VenueUpdate) -> str | None:
    if body.contact is None:
        return None
    data = body.contact.model_dump(exclude_unset=True)
    if not data:
        return None
    return json.dumps(data)


async def _compute_venue_stats(db: AsyncSession, venue_id: str) -> VenueStats:
    """Compute aggregated stats for a venue."""
    # queue depth: active queue requests
    queue_count = (
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

    # total songs
    song_count = (
        await db.execute(
            select(func.count())
            .select_from(Song)
            .where(
                Song.venue_id == venue_id,
                Song.is_active == 1,
                Song.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    # total singers
    singer_count = (
        await db.execute(
            select(func.count())
            .select_from(Singer)
            .where(
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    return VenueStats(
        queue_depth=queue_count,
        current_song=None,
        total_songs=song_count,
        total_singers=singer_count,
        active_singers=0,
    )


# ------------------------------------------------------------------
# LIST
# ------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[VenueCompactOut])
async def list_venues(
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List venues the caller can access.

    - platform_admin: all venues
    - venue_admin / kj / singer: own venue only
    """
    if has_role(current.role, Role.ADMIN):
        # platform admin sees all
        filters = [Venue.deleted_at.is_(None)]
    else:
        # non-admin only sees their own venue
        filters = [
            Venue.id == current.venue_id,
            Venue.deleted_at.is_(None),
        ]

    total = (
        await db.execute(
            select(func.count()).select_from(Venue).where(*filters)
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    stmt = (
        select(Venue)
        .where(*filters)
        .order_by(Venue.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await db.execute(stmt)
    items = [_venue_compact(row) for row in result.scalars().all()]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


# ------------------------------------------------------------------
# PUBLIC LOOKUP (no auth — used by mobile onboarding)
# ------------------------------------------------------------------

@router.get("/lookup", response_model=VenueCompactOut)
async def lookup_venue_by_code(
    code: str = Query(..., min_length=6, max_length=6, pattern=r"^[A-Z0-9]{6}$"),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a venue code to a venue (used by singer app onboarding).

    No authentication required — this is a public discovery endpoint.
    """
    result = await db.execute(
        select(Venue).where(
            Venue.venue_code == code.upper(),
            Venue.is_active == 1,
            Venue.deleted_at.is_(None),
        )
    )
    venue = result.scalar_one_or_none()
    if venue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Venue not found. Please check your code and try again.",
        )
    return _venue_compact(venue)


# ------------------------------------------------------------------
# JOIN (account-scoped mobile identity)
# ------------------------------------------------------------------

@router.post("/{venue_id}/join", response_model=TokenPairOut)
async def join_venue(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Link a global account to a venue, creating a per-venue singer row.

    Returns a venue-scoped token pair for subsequent singer endpoints.
    Idempotent: returns existing membership if already present.
    """
    # Account-scoped token (first join) or singer-scoped token for an existing
    # membership (rejoin / refreshed token). Resolve to the canonical account.
    if current.role == Role.ACCOUNT:
        account_id = current.id
    elif current.role == Role.SINGER:
        existing_singer = (
            await db.execute(
                select(Singer).where(
                    Singer.id == current.id,
                    Singer.venue_id == venue_id,
                    Singer.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_singer is None or existing_singer.account_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account-scoped token required",
            )
        account_id = existing_singer.account_id
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account-scoped token required",
        )

    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.is_active == 1,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")

    account = (
        await db.execute(
            select(Account).where(
                Account.id == account_id,
                Account.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Account not found")

    # Check existing membership
    existing = (
        await db.execute(
            select(Singer).where(
                Singer.account_id == account_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    now = _now_iso()
    if existing:
        singer = existing
    else:
        singer = Singer(
            id=str(uuid.uuid4()),
            account_id=account.id,
            venue_id=venue_id,
            stage_name=account.stage_name or account.real_name or account.email.split("@")[0],
            real_name=account.real_name,
            first_name=account.first_name,
            last_name=account.last_name,
            pronouns=account.pronouns,
            email=account.email,
            phone=account.phone,
            bio=account.bio,
            avatar_url=account.avatar_url,
            social_links=account.social_links,
            role="singer",
            created_at=now,
            updated_at=now,
        )
        db.add(singer)
        await db.commit()
        await db.refresh(singer)

    # Issue venue-scoped tokens
    claims = {
        "venue_id": singer.venue_id,
        "role": "singer",
    }
    await SingerEventPublisher.publish_singer_changed(venue_id, singer, event_type="singer_joined")
    return TokenPairOut(
        access_token=create_access_token(str(singer.id), extra_claims=claims),
        token_type="bearer",
        expires_in=60 * 15,
        refresh_token=create_refresh_token(str(singer.id), extra_claims=claims),
        account_id=singer.id,
    )


# ------------------------------------------------------------------
# CREATE
# ------------------------------------------------------------------

@router.post("", response_model=VenueOut, status_code=status.HTTP_201_CREATED)
async def create_venue(
    body: VenueCreate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new venue. Requires platform admin."""
    _require_platform_admin(current)

    # slug uniqueness check
    existing = (
        await db.execute(
            select(Venue).where(
                Venue.slug == body.slug,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Venue slug already exists",
        )

    # If no venue_code provided, let the model default generator run.
    # If provided, validate it is unique.
    venue_code = body.venue_code
    if venue_code:
        existing_code = (
            await db.execute(
                select(Venue).where(
                    Venue.venue_code == venue_code.upper(),
                    Venue.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_code is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Venue code already exists",
            )
    else:
        venue_code = None  # let model default handle it

    venue = Venue(
        id=str(uuid.uuid4()),
        name=body.name,
        slug=body.slug,
        venue_code=venue_code,
        address=_build_address_json(body),
        contact_json=_build_contact_json(body),
        timezone=body.timezone or "UTC",
        branding_json=_build_branding_json(body),
        is_active=1,
    )
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    stats = await _compute_venue_stats(db, venue.id)
    return _venue_out(venue, stats=stats)


# ------------------------------------------------------------------
# GET
# ------------------------------------------------------------------

@router.get("/{venue_id}", response_model=VenueOut)
async def get_venue(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get venue details with stats."""
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

    # Cross-venue access control: admin sees all, others see own venue only
    if not has_role(current.role, Role.ADMIN) and str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    stats = await _compute_venue_stats(db, venue_id)
    return _venue_out(venue, stats=stats)


# ------------------------------------------------------------------
# UPDATE
# ------------------------------------------------------------------

@router.put("/{venue_id}", response_model=VenueOut)
async def update_venue(
    venue_id: str,
    body: VenueUpdate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update venue. platform_admin or venue_admin/kj for own venue."""
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

    own_venue = str(current.venue_id) == str(venue_id)
    can_admin = has_role(current.role, Role.ADMIN) or (
        has_role(current.role, Role.KJ) and own_venue
    )
    if not can_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Admin or venue operator access required",
        )

    update_data = body.model_dump(exclude_unset=True)

    # Handle nested schema fields separately
    if "address" in update_data:
        venue.address = _build_address_json(body)
        update_data.pop("address")
    if "contact" in update_data:
        venue.contact_json = _build_contact_json(body)
        update_data.pop("contact")
    if "branding" in update_data:
        venue.branding_json = _build_branding_json(body)
        update_data.pop("branding")
    if "timezone" in update_data:
        venue.timezone = body.timezone
        update_data.pop("timezone")
    if "name" in update_data:
        venue.name = body.name
        update_data.pop("name")
    if "slug" in update_data:
        # slug uniqueness check
        existing = (
            await db.execute(
                select(Venue).where(
                    Venue.slug == body.slug,
                    Venue.id != venue_id,
                    Venue.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Venue slug already exists",
            )
        venue.slug = body.slug
        update_data.pop("slug")
    if "venue_code" in update_data:
        # venue_code uniqueness check
        new_code = body.venue_code.upper()
        existing_code = (
            await db.execute(
                select(Venue).where(
                    Venue.venue_code == new_code,
                    Venue.id != venue_id,
                    Venue.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing_code is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Venue code already exists",
            )
        venue.venue_code = new_code
        update_data.pop("venue_code")
    if "settings" in update_data:
        update_data.pop("settings")  # out of scope for Sprint 2
    if "operating_hours" in update_data:
        update_data.pop("operating_hours")  # out of scope for Sprint 2

    # Any remaining scalar fields
    for key, value in update_data.items():
        if value is not None and hasattr(venue, key):
            setattr(venue, key, value)

    venue.updated_at = _now_iso()
    await db.commit()
    await db.refresh(venue)
    stats = await _compute_venue_stats(db, venue_id)
    return _venue_out(venue, stats=stats)


# ------------------------------------------------------------------
# DELETE (soft)
# ------------------------------------------------------------------

@router.delete("/{venue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_venue(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a venue. Requires platform admin."""
    _require_platform_admin(current)

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

    venue.is_active = 0
    venue.deleted_at = _now_iso()
    await db.commit()
    return None
