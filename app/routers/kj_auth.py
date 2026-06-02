"""KJ device authentication router.

Machine-to-machine auth for KJ desktop apps:
- Register a device (admin only) → receive API key (shown once)
- Exchange API key → short-lived JWT
- List, revoke, rotate keys per venue (admin only)
- Authenticated endpoints use kj_auth() dependency (x-api-key or Bearer JWT)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.auth import get_current_user, SingerUser, kj_auth, KJDeviceUser
from app.core.permissions import Role, has_role
from app.core.db import async_session_factory, get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.core.rls import set_session_venue_id
from app.models import KJDevice, Venue

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KJDeviceRegisterRequest(_Base):
    venue_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=100)


class KJDeviceRegisterResponse(_Base):
    id: str
    api_key: str
    message: str = "Device registered. Store this API key — it will not be shown again."


class KJTokenRequest(_Base):
    api_key: str = Field(..., min_length=1)


class KJTokenResponse(_Base):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class KJDeviceOut(_Base):
    id: str
    venue_id: str
    name: str
    created_at: str
    last_seen: str | None
    revoked_at: str | None


class KJDeviceListResponse(_Base):
    items: list[KJDeviceOut]


class KJDeviceRotateResponse(_Base):
    id: str
    api_key: str
    message: str = "API key rotated. Store this new key — it will not be shown again."


class MessageResponse(_Base):
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_admin(current: SingerUser) -> None:
    if not has_role(current.role, Role.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


async def _get_device_by_id(session: AsyncSession, device_id: str, venue_id: str) -> KJDevice:
    result = await session.execute(
        select(KJDevice).where(
            KJDevice.id == device_id,
            KJDevice.venue_id == venue_id,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    await set_session_venue_id(session, str(device.venue_id))
    return device


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=KJDeviceRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def kj_register(
    body: KJDeviceRegisterRequest,
    current: SingerUser = Depends(get_current_user),
):
    """Register a new KJ device for a venue. Admin only."""
    await _require_admin(current)

    async with async_session_factory() as session:
        await set_session_venue_id(session, body.venue_id)
        # Verify venue exists
        venue_result = await session.execute(
            select(Venue).where(Venue.id == body.venue_id, Venue.deleted_at.is_(None))
        )
        if not venue_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Venue not found",
            )

        # Verify admin can manage this venue
        if current.venue_id != body.venue_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot manage devices for another venue",
            )

        raw_key = str(uuid.uuid4()) + str(uuid.uuid4())
        device = KJDevice(
            id=str(uuid.uuid4()),
            venue_id=body.venue_id,
            name=body.name,
            api_key_hash=hash_password(raw_key),
            created_at=_now_iso(),
        )
        session.add(device)
        await session.commit()

        return KJDeviceRegisterResponse(
            id=device.id,
            api_key=raw_key,
        )


@router.post("/token", response_model=KJTokenResponse)
async def kj_token(body: KJTokenRequest):
    """Exchange a KJ device API key for a short-lived JWT."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(KJDevice).where(KJDevice.revoked_at.is_(None))
        )
        devices = result.scalars().all()

        device: KJDevice | None = None
        for d in devices:
            if verify_password(body.api_key, d.api_key_hash):
                device = d
                break

        if not device:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

        device.last_seen = _now_iso()
        await session.commit()

        claims = {
            "venue_id": device.venue_id,
            "kj_device_id": device.id,
            "kj_device_name": device.name,
        }
        token = create_access_token(
            subject=device.id,
            extra_claims=claims,
            expires_delta=timedelta(minutes=15),
        )

        return KJTokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=15 * 60,
        )


@router.get("/devices", response_model=KJDeviceListResponse)
async def kj_list_devices(
    current: SingerUser = Depends(get_current_user),
):
    """List all KJ devices for the admin's venue. Admin only."""
    await _require_admin(current)

    async with async_session_factory() as session:
        await set_session_venue_id(session, current.venue_id)
        result = await session.execute(
            select(KJDevice).where(
                KJDevice.venue_id == current.venue_id,
            ).order_by(KJDevice.created_at.desc())
        )
        devices = result.scalars().all()

        return KJDeviceListResponse(
            items=[
                KJDeviceOut(
                    id=d.id,
                    venue_id=d.venue_id,
                    name=d.name,
                    created_at=d.created_at,
                    last_seen=d.last_seen,
                    revoked_at=d.revoked_at,
                )
                for d in devices
            ],
        )


@router.post("/devices/{device_id}/revoke", response_model=MessageResponse)
async def kj_revoke_device(
    device_id: str,
    current: SingerUser = Depends(get_current_user),
):
    """Revoke a KJ device. Admin only."""
    await _require_admin(current)

    async with async_session_factory() as session:
        await set_session_venue_id(session, current.venue_id)
        device = await _get_device_by_id(session, device_id, current.venue_id)
        if device.revoked_at:
            return MessageResponse(message="Device already revoked")
        device.revoked_at = _now_iso()
        await session.commit()
        return MessageResponse(message="Device revoked successfully")


@router.post("/devices/{device_id}/rotate", response_model=KJDeviceRotateResponse)
async def kj_rotate_key(
    device_id: str,
    current: SingerUser = Depends(get_current_user),
):
    """Rotate API key for a KJ device. Admin only. Returns the new key once."""
    await _require_admin(current)

    raw_key = str(uuid.uuid4()) + str(uuid.uuid4())

    async with async_session_factory() as session:
        await set_session_venue_id(session, current.venue_id)
        device = await _get_device_by_id(session, device_id, current.venue_id)
        device.api_key_hash = hash_password(raw_key)
        device.revoked_at = None  # un-revoke if rotating
        await session.commit()

        return KJDeviceRotateResponse(
            id=device.id,
            api_key=raw_key,
        )

# ═══════════════════════════════════════════════════════════════════════════════
# Venue-scoped routes (used by web portal)
# ═══════════════════════════════════════════════════════════════════════════════

venue_router = APIRouter(prefix="/venues/{venue_id}/kj-devices", tags=["KJ Devices"])

@venue_router.get("", response_model=KJDeviceListResponse)
async def list_kj_devices_for_venue(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all KJ devices for a venue (admin/owner only)."""
    if current.role not in ("admin", "owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or owner access required")
    result = await db.execute(
        select(KJDevice).where(KJDevice.venue_id == venue_id, KJDevice.revoked_at.is_(None))
    )
    devices = result.scalars().all()
    return KJDeviceListResponse(
        items=[KJDeviceOut(
            id=str(d.id),
            venue_id=str(d.venue_id),
            name=str(d.name),
            created_at=str(d.created_at) if d.created_at else "",
            last_seen=str(d.last_seen) if d.last_seen else None,
            revoked_at=str(d.revoked_at) if d.revoked_at else None,
        ) for d in devices]
    )

@venue_router.post("", response_model=KJDeviceRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_kj_device_for_venue(
    venue_id: str,
    body: KJDeviceRegisterRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new KJ device for a venue. Returns the API key once."""
    if current.role not in ("admin", "owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or owner access required")
    if current.venue_id != venue_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot manage devices for another venue")
    
    venue_result = await db.execute(select(Venue).where(Venue.id == venue_id, Venue.deleted_at.is_(None)))
    if not venue_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    
    raw_key = str(uuid.uuid4()) + str(uuid.uuid4())
    device = KJDevice(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name=body.name,
        api_key_hash=hash_password(raw_key),
        created_at=_now_iso(),
    )
    db.add(device)
    await db.commit()
    
    return KJDeviceRegisterResponse(
        id=device.id,
        api_key=raw_key,
    )

@venue_router.post("/{device_id}/revoke", response_model=MessageResponse)
async def revoke_kj_device_for_venue(
    venue_id: str,
    device_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a KJ device for a venue."""
    if current.role not in ("admin", "owner"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or owner access required")
    result = await db.execute(
        select(KJDevice).where(KJDevice.id == device_id, KJDevice.venue_id == venue_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    if device.revoked_at:
        return MessageResponse(message="Device already revoked")
    device.revoked_at = _now_iso()
    await db.commit()
    return MessageResponse(message="Device revoked successfully")
