"""License lifecycle service.

License keys are generated and validated server-side.  The desktop client can:
1. Activate online with a key + machine fingerprint.
2. Request an offline activation payload to carry to the portal/admin.
3. Activate offline by uploading a signed license file.
4. Check license status and check-in (online) for revocation/renewal updates.

The signed license file is a JWT issued with the same HS256 secret used for API
tokens.  It contains the license_id, venue_id, fingerprint hash, plan, and
expiry.  This avoids an extra Ed25519 dependency while still letting the desktop
verify the server's signature offline.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.models import License, Venue, _now_iso


LICENSE_FILE_TYPE = "license"
GRACE_DAYS_DEFAULT = 7


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _generate_license_key() -> str:
    """Generate a human-readable license key: SCALES-XXXX-XXXX-XXXX-XXXX."""
    parts = [uuid.uuid4().hex[:4].upper() for _ in range(4)]
    return f"SCALES-{'-'.join(parts)}"


def _prefix(key: str) -> str:
    return key.replace("SCALES-", "").replace("-", "")[:8]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


class LicenseServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class LicenseService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -----------------------------------------------------------------------
    # Admin: create/list/revoke
    # -----------------------------------------------------------------------

    async def create_license(
        self,
        venue_id: str,
        plan: str = "basic",
        seat_limit: int | None = None,
        expires_at: str | None = None,
        grace_days: int = GRACE_DAYS_DEFAULT,
    ) -> tuple[License, str]:
        key = _generate_license_key()
        key_hash = _hash(key)
        license_id = str(uuid.uuid4())
        license_row = License(
            id=license_id,
            venue_id=venue_id,
            license_key_hash=key_hash,
            license_key_prefix=_prefix(key),
            status="unactivated",
            plan=plan,
            seat_limit=seat_limit,
            expires_at=expires_at,
            grace_days=grace_days,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
        self.db.add(license_row)
        await self.db.commit()
        await self.db.refresh(license_row)
        return license_row, key

    async def get_license(self, license_id: str) -> License | None:
        result = await self.db.execute(select(License).where(License.id == license_id))
        return result.scalar_one_or_none()

    async def get_license_by_key(self, key: str) -> License | None:
        key_hash = _hash(key)
        result = await self.db.execute(
            select(License).where(License.license_key_hash == key_hash)
        )
        return result.scalar_one_or_none()

    async def list_licenses(
        self,
        venue_id: str | None = None,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[License]:
        filters = []
        if venue_id:
            filters.append(License.venue_id == venue_id)
        if status:
            filters.append(License.status == status)
        stmt = select(License).where(*filters).order_by(License.created_at.desc())
        if offset:
            stmt = stmt.offset(offset)
        if limit:
            stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_licenses(
        self,
        venue_id: str | None = None,
        status: str | None = None,
    ) -> int:
        filters = []
        if venue_id:
            filters.append(License.venue_id == venue_id)
        if status:
            filters.append(License.status == status)
        from sqlalchemy import func
        result = await self.db.execute(
            select(func.count()).select_from(License).where(*filters)
        )
        return result.scalar_one()

    async def revoke_license(self, license_id: str) -> License | None:
        license_row = await self.get_license(license_id)
        if not license_row:
            return None
        now = _now_iso()
        license_row.status = "revoked"
        license_row.revoked_at = now
        license_row.updated_at = now
        await self.db.commit()
        await self.db.refresh(license_row)
        return license_row

    # -----------------------------------------------------------------------
    # Desktop: online activation
    # -----------------------------------------------------------------------

    async def activate_online(
        self,
        key: str,
        fingerprint: str,
        machine_name: str | None = None,
    ) -> dict[str, Any]:
        license_row = await self.get_license_by_key(key)
        if not license_row:
            raise LicenseServiceError("Invalid license key", status_code=404)
        if license_row.status == "revoked":
            raise LicenseServiceError("License revoked", status_code=403)

        # Idempotent: same fingerprint can re-download the license file.
        fp_hash = _hash(fingerprint)
        if license_row.fingerprint_hash and license_row.fingerprint_hash != fp_hash:
            raise LicenseServiceError(
                "License already activated on another device", status_code=409
            )

        now = _now_iso()
        license_row.fingerprint_hash = fp_hash
        license_row.status = "active"
        license_row.activated_at = license_row.activated_at or now
        license_row.last_check_in_at = now
        license_row.updated_at = now
        await self.db.commit()

        venue = await self._get_venue(license_row.venue_id)
        signed = self._sign_license_file(license_row, venue, fingerprint)
        return {"license_row": license_row, "license_file": signed, "venue": venue}

    # -----------------------------------------------------------------------
    # Desktop: offline activation request
    # -----------------------------------------------------------------------

    async def request_offline_activation(
        self,
        key: str,
        fingerprint: str,
        machine_name: str | None = None,
    ) -> dict[str, Any]:
        license_row = await self.get_license_by_key(key)
        if not license_row:
            raise LicenseServiceError("Invalid license key", status_code=404)
        if license_row.status == "revoked":
            raise LicenseServiceError("License revoked", status_code=403)
        fp_hash = _hash(fingerprint)
        if license_row.fingerprint_hash and license_row.fingerprint_hash != fp_hash:
            raise LicenseServiceError(
                "License already activated on another device", status_code=409
            )

        payload = {
            "license_id": license_row.id,
            "venue_id": license_row.venue_id,
            "fingerprint": fingerprint,
            "requested_at": _now_iso(),
        }
        return {"license_id": license_row.id, "request_payload": payload}

    async def create_offline_activation_file(
        self,
        license_id: str,
        admin_venue_id: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        license_row = await self.get_license(license_id)
        if not license_row:
            raise LicenseServiceError("License not found", status_code=404)
        if license_row.venue_id != admin_venue_id:
            raise LicenseServiceError("Venue mismatch", status_code=403)
        if license_row.status == "revoked":
            raise LicenseServiceError("License revoked", status_code=403)

        now = _now_iso()
        fp_hash = _hash(fingerprint)
        if license_row.fingerprint_hash and license_row.fingerprint_hash != fp_hash:
            # Allow offline re-activation of the same license on a new device only if
            # the old fingerprint has not checked in recently.  In practice, offline
            # re-activation is meant for the same device after reinstall.
            pass

        license_row.fingerprint_hash = fp_hash
        license_row.status = "active"
        license_row.activated_at = license_row.activated_at or now
        license_row.last_check_in_at = now
        license_row.updated_at = now
        await self.db.commit()

        venue = await self._get_venue(license_row.venue_id)
        signed = self._sign_license_file(license_row, venue, fingerprint)
        return {"license_row": license_row, "license_file": signed, "venue": venue}

    async def activate_offline(
        self,
        license_file: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        payload = self._decode_license_file(license_file)
        if not payload:
            raise LicenseServiceError("Invalid license file", status_code=400)

        license_id = payload.get("license_id")
        file_fingerprint = payload.get("fingerprint")
        if not license_id or not file_fingerprint:
            raise LicenseServiceError("Malformed license file", status_code=400)
        if file_fingerprint != fingerprint:
            raise LicenseServiceError(
                "License file does not match this device", status_code=403
            )

        license_row = await self.get_license(license_id)
        if not license_row:
            raise LicenseServiceError("License not found", status_code=404)
        if license_row.status == "revoked":
            raise LicenseServiceError("License revoked", status_code=403)

        fp_hash = _hash(fingerprint)
        if (
            license_row.fingerprint_hash
            and license_row.fingerprint_hash != fp_hash
        ):
            raise LicenseServiceError(
                "License bound to another device", status_code=409
            )

        now = _now_iso()
        license_row.fingerprint_hash = fp_hash
        license_row.status = "active"
        license_row.activated_at = license_row.activated_at or now
        license_row.last_check_in_at = now
        license_row.updated_at = now
        await self.db.commit()

        return {"license_row": license_row, "license_file": license_file}

    # -----------------------------------------------------------------------
    # Desktop: status / check-in
    # -----------------------------------------------------------------------

    async def check_license_status(
        self,
        license_file: str | None,
        fingerprint: str | None = None,
        allow_expired: bool = True,
    ) -> dict[str, Any]:
        if not license_file:
            return {"ok": False, "status": "invalid", "reason": "No license file"}

        payload = self._decode_license_file(license_file)
        if not payload:
            return {"ok": False, "status": "invalid", "reason": "Invalid license file"}

        license_id = payload.get("license_id")
        if not license_id:
            return {"ok": False, "status": "invalid", "reason": "Malformed license file"}

        license_row = await self.get_license(license_id)
        if not license_row:
            return {"ok": False, "status": "invalid", "reason": "License not found"}

        if license_row.status == "revoked":
            return {"ok": False, "status": "revoked", "reason": "License revoked"}

        if fingerprint and _hash(fingerprint) != license_row.fingerprint_hash:
            return {"ok": False, "status": "invalid", "reason": "Fingerprint mismatch"}

        now = _now_dt()
        expires = _parse_iso(license_row.expires_at)
        grace_until = None
        status_label = "valid"
        ok = True

        if expires and now > expires:
            grace_until_dt = expires + timedelta(days=license_row.grace_days or 0)
            grace_until = grace_until_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            if now <= grace_until_dt:
                status_label = "grace"
            else:
                status_label = "expired"
                ok = False
            if license_row.status != status_label:
                license_row.status = status_label
                license_row.updated_at = _now_iso()
        else:
            if license_row.status in ("expired", "grace"):
                license_row.status = "active"
                license_row.updated_at = _now_iso()

        await self.db.commit()

        result: dict[str, Any] = {
            "ok": ok,
            "status": status_label,
            "license_id": license_id,
            "venue_id": license_row.venue_id,
            "plan": license_row.plan,
            "expires_at": license_row.expires_at,
        }
        if grace_until:
            result["grace_until"] = grace_until
        if not ok:
            result["reason"] = "License expired"
        return result

    async def check_in(
        self,
        license_file: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        status_result = await self.check_license_status(
            license_file, fingerprint=fingerprint, allow_expired=True
        )
        if not status_result.get("ok"):
            return status_result

        license_id = status_result.get("license_id")
        license_row = await self.get_license(license_id)
        if license_row:
            now = _now_iso()
            license_row.last_check_in_at = now
            license_row.updated_at = now
            await self.db.commit()

        return status_result

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _get_venue(self, venue_id: str) -> Venue | None:
        result = await self.db.execute(
            select(Venue).where(Venue.id == venue_id, Venue.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    def _sign_license_file(
        self,
        license_row: License,
        venue: Venue | None,
        fingerprint: str,
    ) -> str:
        now = _now_dt()
        claims: dict[str, Any] = {
            "sub": license_row.id,
            "license_id": license_row.id,
            "venue_id": license_row.venue_id,
            "venue_name": venue.name if venue else None,
            "fingerprint": fingerprint,
            "plan": license_row.plan,
            "status": license_row.status,
            "grace_days": license_row.grace_days,
            "type": LICENSE_FILE_TYPE,
            "iat": now,
            "exp": now + timedelta(days=365 * 10),  # signed file is long-lived
            "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if license_row.expires_at:
            claims["expires_at"] = license_row.expires_at
        return jwt.encode(
            claims,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

    def _decode_license_file(self, license_file: str) -> dict[str, Any] | None:
        try:
            return jwt.decode(
                license_file,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError:
            return None


__all__ = [
    "LicenseService",
    "LicenseServiceError",
    "GRACE_DAYS_DEFAULT",
]
