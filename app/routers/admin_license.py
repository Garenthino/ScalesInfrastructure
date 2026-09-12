"""Admin license management router.

Requires platform admin role.

Endpoints:
    GET  /admin/licenses                — list licenses
    POST /admin/licenses                — create a license (returns key once)
    GET  /admin/licenses/{license_id}   — license detail
    DELETE /admin/licenses/{license_id}  — revoke license
    POST /admin/licenses/{license_id}/offline — issue signed offline file
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_platform_admin
from app.core.db import get_db
from app.services.license_service import LicenseService, LicenseServiceError
from app.schemas import (
    PaginatedResponse,
    LicenseCreate,
    LicenseOut,
    LicenseAdminCreateResponse,
    LicenseListParams,
)

router = APIRouter(prefix="/licenses", tags=["Admin Licenses"])


def _service(db: AsyncSession) -> LicenseService:
    return LicenseService(db)


@router.get("", response_model=PaginatedResponse[LicenseOut])
async def list_licenses(
    admin: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
    venue_id: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List license keys with optional venue/status filters."""
    svc = _service(db)
    total = await svc.count_licenses(venue_id=venue_id, status=status)
    offset = (page - 1) * per_page
    rows = await svc.list_licenses(
        venue_id=venue_id, status=status, offset=offset, limit=per_page
    )
    return PaginatedResponse(
        items=[LicenseOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("", response_model=LicenseAdminCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_license(
    body: LicenseCreate,
    admin: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new license for a venue. The full key is returned only once."""
    svc = _service(db)
    license_row, key = await svc.create_license(
        venue_id=body.venue_id,
        plan=body.plan,
        seat_limit=body.seat_limit,
        expires_at=body.expires_at,
        grace_days=body.grace_days,
    )
    expires_at_raw = license_row.expires_at
    expires_at = str(expires_at_raw) if expires_at_raw is not None else None
    return LicenseAdminCreateResponse(
        id=str(license_row.id),
        license_key=key,
        venue_id=str(license_row.venue_id),
        plan=str(license_row.plan),
        expires_at=expires_at,
        created_at=str(license_row.created_at),
    )


@router.get("/{license_id}", response_model=LicenseOut)
async def get_license(
    license_id: str,
    admin: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get license details."""
    svc = _service(db)
    row = await svc.get_license(license_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="License not found")
    return LicenseOut.model_validate(row)


@router.delete("/{license_id}", response_model=LicenseOut)
async def revoke_license(
    license_id: str,
    admin: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a license."""
    svc = _service(db)
    row = await svc.revoke_license(license_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="License not found")
    return LicenseOut.model_validate(row)


class _OfflineActivationBody(LicenseCreate):
    fingerprint: str


@router.post("/{license_id}/offline", response_model=dict)
async def create_offline_activation_file(
    license_id: str,
    body: dict,
    admin: dict = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a signed offline activation file for a device fingerprint.

    Request body:
        {
            "fingerprint": "...",
        }
    """
    fingerprint = body.get("fingerprint")
    if not fingerprint or not isinstance(fingerprint, str):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fingerprint is required",
        )

    svc = _service(db)
    row = await svc.get_license(license_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="License not found")

    try:
        result = await svc.create_offline_activation_file(
            license_id=license_id,
            admin_venue_id=str(row.venue_id),
            fingerprint=fingerprint,
        )
    except LicenseServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    venue = result.get("venue")
    return {
        "license_id": str(result["license_row"].id),
        "license_file": result["license_file"],
        "venue_id": str(result["license_row"].venue_id),
        "venue_name": str(venue.name) if venue else None,
    }
