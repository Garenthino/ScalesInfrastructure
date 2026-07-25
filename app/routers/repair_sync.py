"""Full repair sync API router.

POST /kj/sync/repair            start a repair sync
GET  /kj/sync/repair/{sync_id}  poll status
POST /kj/sync/repair/{sync_id}/resolve  resolve conflicts (prompt mode)
DELETE /kj/sync/repair/{sync_id}        best-effort cancel
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import kj_auth, KJDeviceUser
from app.core.db import get_db
from app.schemas import (
    ProblemDetail,
    RepairSyncOut,
    RepairSyncResolveRequest,
    RepairSyncStartRequest,
)
from app.services import repair_sync as service

router = APIRouter()


def _problem(status_code: int, detail: str, code: str = "validation_error") -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ProblemDetail(
            type="about:blank",
            title="Repair sync failed",
            status=status_code,
            detail=detail,
        ).model_dump(),
    )


async def _repair_auth(
    request: Request,
) -> KJDeviceUser | dict:
    """Accept KJ device auth (x-api-key/KJ token) or owner/admin/kj Bearer token."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        return await kj_auth(request)

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        from app.core.security import decode_token

        token = auth[7:]
        claims = decode_token(token)
        if not claims:
            raise _problem(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", "permission_denied")
        role = str(claims.get("role", "")).lower()
        if role not in ("owner", "admin", "kj"):
            raise _problem(status.HTTP_403_FORBIDDEN, "Repair sync requires owner, admin, or KJ role", "permission_denied")
        venue_id = claims.get("venue_id")
        if not venue_id:
            raise _problem(status.HTTP_403_FORBIDDEN, "Token missing venue_id", "permission_denied")
        return claims

    raise _problem(status.HTTP_401_UNAUTHORIZED, "Missing x-api-key or valid admin/KJ Bearer token", "permission_denied")


def _venue_id_from_user(user: KJDeviceUser | dict) -> str:
    if isinstance(user, KJDeviceUser):
        return str(user.venue_id)
    return str(user.get("venue_id"))


@router.post("/repair", status_code=status.HTTP_202_ACCEPTED, response_model=RepairSyncOut)
async def start_repair_sync(
    body: RepairSyncStartRequest,
    request: Request,
    current: KJDeviceUser | dict = Depends(_repair_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Start a full repair sync job for a venue snapshot."""
    venue_id = str(body.venue_id)
    if _venue_id_from_user(current) != venue_id:
        raise _problem(status.HTTP_403_FORBIDDEN, "Venue access denied", "permission_denied")

    idempotency_key = request.headers.get("X-Idempotency-Key") or request.headers.get("x-idempotency-key")

    job = await service.start_repair_sync(
        db=db,
        venue_id=venue_id,
        mode=body.mode,
        snapshot=body.snapshot,
        idempotency_key=idempotency_key,
    )
    return service.job_to_out(job)


@router.get("/repair/{sync_id}", response_model=RepairSyncOut)
async def get_repair_sync_status(
    sync_id: str,
    current: KJDeviceUser | dict = Depends(_repair_auth),
) -> dict[str, Any]:
    """Poll the status of a repair sync job."""
    job = await service.get_repair_sync(sync_id)
    if not job:
        raise _problem(status.HTTP_404_NOT_FOUND, "Repair sync job not found", "not_found")
    if _venue_id_from_user(current) != job.venue_id:
        raise _problem(status.HTTP_403_FORBIDDEN, "Venue access denied", "permission_denied")
    return service.job_to_out(job)


@router.post("/repair/{sync_id}/resolve", response_model=RepairSyncOut)
async def resolve_repair_sync(
    sync_id: str,
    body: RepairSyncResolveRequest,
    current: KJDeviceUser | dict = Depends(_repair_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Resolve conflicts for a prompt-mode repair sync and finish applying it."""
    job = await service.get_repair_sync(sync_id)
    if not job:
        raise _problem(status.HTTP_404_NOT_FOUND, "Repair sync job not found", "not_found")
    if _venue_id_from_user(current) != job.venue_id:
        raise _problem(status.HTTP_403_FORBIDDEN, "Venue access denied", "permission_denied")

    try:
        job = await service.resolve_repair_sync(db, sync_id, body.resolutions)
    except ValueError as exc:
        raise _problem(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc), "validation_error")
    return service.job_to_out(job)


@router.delete("/repair/{sync_id}", status_code=status.HTTP_202_ACCEPTED)
async def cancel_repair_sync(
    sync_id: str,
    current: KJDeviceUser | dict = Depends(_repair_auth),
) -> dict[str, Any]:
    """Best-effort cancel of a running repair sync job."""
    job = await service.get_repair_sync(sync_id)
    if not job:
        raise _problem(status.HTTP_404_NOT_FOUND, "Repair sync job not found", "not_found")
    if _venue_id_from_user(current) != job.venue_id:
        raise _problem(status.HTTP_403_FORBIDDEN, "Venue access denied", "permission_denied")

    found, job = await service.cancel_repair_sync(sync_id)
    if not found:
        raise _problem(status.HTTP_404_NOT_FOUND, "Repair sync job not found", "not_found")
    if job:
        return service.job_to_out(job)
    return {"sync_id": sync_id, "status": "cancelled"}
