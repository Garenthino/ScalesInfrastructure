"""License router for desktop activation and status checks.

Public endpoints (no auth required):
    POST /v1/license/activate            — online activation
    POST /v1/license/offline/request     — generate offline activation request
    POST /v1/license/offline/activate     — activate with signed file
    GET  /v1/license/status              — check license status
    POST /v1/license/check-in            — online check-in / refresh
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services.license_service import LicenseService, LicenseServiceError
from app.schemas import (
    LicenseActivateRequest,
    LicenseActivateResponse,
    LicenseOfflineRequest,
    LicenseOfflineActivationCode,
    LicenseStatusResponse,
    LicenseCheckInRequest,
    LicenseCheckInResponse,
)

router = APIRouter(tags=["License"])


def _service(db: AsyncSession) -> LicenseService:
    return LicenseService(db)


@router.post("/activate", response_model=LicenseActivateResponse)
async def activate_license(
    body: LicenseActivateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Activate a license online with a key and device fingerprint."""
    svc = _service(db)
    try:
        result = await svc.activate_online(
            body.license_key, body.fingerprint, body.machine_name
        )
    except LicenseServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    license_row = result["license_row"]
    venue = result["venue"]
    signed = result["license_file"]
    return LicenseActivateResponse(
        license_id=license_row.id,
        venue_id=license_row.venue_id,
        venue_name=str(venue.name) if venue else None,
        license_file=signed,
        plan=license_row.plan,
        status=license_row.status,
        expires_at=license_row.expires_at,
        grace_days=license_row.grace_days,
        issued_at=None,
    )


@router.post("/offline/request", response_model=LicenseOfflineActivationCode)
async def request_offline_activation(
    body: LicenseOfflineRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request an offline activation payload to take to the portal/admin."""
    svc = _service(db)
    try:
        result = await svc.request_offline_activation(
            body.license_key, body.fingerprint, body.machine_name
        )
    except LicenseServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return LicenseOfflineActivationCode(
        license_id=result["license_id"],
        venue_id=result["request_payload"]["venue_id"],
        fingerprint=body.fingerprint,
        request_payload=result["request_payload"],
    )


@router.post("/offline/activate", response_model=LicenseActivateResponse)
async def activate_offline(
    body: LicenseCheckInRequest,
    db: AsyncSession = Depends(get_db),
):
    """Activate using a signed offline license file from the portal/admin."""
    svc = _service(db)
    try:
        result = await svc.activate_offline(body.license_file, body.fingerprint)
    except LicenseServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    license_row = result["license_row"]
    venue = await svc._get_venue(license_row.venue_id)
    signed = result["license_file"]
    return LicenseActivateResponse(
        license_id=license_row.id,
        venue_id=license_row.venue_id,
        venue_name=str(venue.name) if venue else None,
        license_file=signed,
        plan=license_row.plan,
        status=license_row.status,
        expires_at=license_row.expires_at,
        grace_days=license_row.grace_days,
        issued_at=None,
    )


@router.get("/status", response_model=LicenseStatusResponse)
async def license_status(
    license_file: str,
    fingerprint: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Check whether a license file is valid, expired, in grace, or revoked."""
    svc = _service(db)
    result = await svc.check_license_status(license_file, fingerprint=fingerprint)
    return LicenseStatusResponse(
        license_id=result.get("license_id"),
        venue_id=result.get("venue_id"),
        status=result.get("status", "invalid"),
        plan=result.get("plan"),
        expires_at=result.get("expires_at"),
        grace_until=result.get("grace_until"),
        ok=result.get("ok", False),
        reason=result.get("reason"),
    )


@router.post("/check-in", response_model=LicenseCheckInResponse)
async def license_check_in(
    body: LicenseCheckInRequest,
    db: AsyncSession = Depends(get_db),
):
    """Online check-in: refresh server-side revocation/expiry state."""
    svc = _service(db)
    result = await svc.check_in(body.license_file, body.fingerprint)
    return LicenseCheckInResponse(
        license_id=result.get("license_id"),
        status=result.get("status", "invalid"),
        ok=result.get("ok", False),
        revoked=result.get("status") == "revoked",
        expires_at=result.get("expires_at"),
        grace_until=result.get("grace_until"),
    )
