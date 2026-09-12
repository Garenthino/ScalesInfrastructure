"""License schemas for desktop activation and portal admin."""
from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.dto import ScalesModel


class LicenseStatus(str, Enum):
    UNACTIVATED = "unactivated"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class LicenseActivateRequest(ScalesModel):
    license_key: str = Field(..., min_length=1, max_length=256)
    fingerprint: str = Field(..., min_length=1, max_length=512)
    machine_name: str | None = Field(None, max_length=200)


class LicenseOfflineRequest(ScalesModel):
    license_key: str = Field(..., min_length=1, max_length=256)
    fingerprint: str = Field(..., min_length=1, max_length=512)
    machine_name: str | None = Field(None, max_length=200)


class LicenseOfflineActivationCode(ScalesModel):
    license_id: str
    venue_id: str
    fingerprint: str
    request_payload: dict[str, Any]


class LicenseFilePayload(ScalesModel):
    license_id: str
    venue_id: str
    venue_name: str | None = None
    license_key: str | None = None
    fingerprint: str
    plan: str
    status: str
    expires_at: str | None = None
    grace_days: int
    issued_at: str


class LicenseActivateResponse(ScalesModel):
    license_id: str
    venue_id: str
    venue_name: str | None = None
    license_file: str  # signed JWT
    plan: str
    status: str
    expires_at: str | None = None
    grace_days: int
    issued_at: str | None = None


class LicenseStatusResponse(ScalesModel):
    license_id: str | None = None
    venue_id: str | None = None
    status: str  # valid | expired | revoked | grace | invalid
    plan: str | None = None
    expires_at: str | None = None
    grace_until: str | None = None
    ok: bool = False
    reason: str | None = None


class LicenseCheckInRequest(ScalesModel):
    license_file: str  # signed JWT
    fingerprint: str = Field(..., min_length=1, max_length=512)


class LicenseCheckInResponse(ScalesModel):
    license_id: str | None = None
    status: str
    ok: bool = False
    revoked: bool = False
    expires_at: str | None = None
    grace_until: str | None = None


class LicenseCreate(ScalesModel):
    venue_id: str
    plan: str = Field(default="basic", max_length=50)
    seat_limit: int | None = Field(None, ge=1)
    expires_at: str | None = None  # ISO 8601
    grace_days: int = Field(default=7, ge=0)


class LicenseOut(ScalesModel):
    id: str
    venue_id: str
    license_key_prefix: str
    fingerprint_hash: str | None = None
    status: str
    plan: str
    seat_limit: int | None = None
    expires_at: str | None = None
    grace_days: int
    activated_at: str | None = None
    last_check_in_at: str | None = None
    revoked_at: str | None = None
    created_at: str
    updated_at: str


class LicenseListParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    venue_id: str | None = None
    status: str | None = None
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)


class LicenseAdminCreateResponse(ScalesModel):
    id: str
    license_key: str
    venue_id: str
    plan: str
    expires_at: str | None = None
    created_at: str
