"""Authentication layer: singer resolution + token helpers + venue scoping + KJ device auth.

Provides three usage patterns:
1. SingerUser resolution (auth router, RBAC deps) — get_current_user, SingerUser
2. Raw token dicts (song catalog router) — require_admin, optional_token, venue_match
3. KJ device auth (KJ desktop apps) — kj_auth, KJDeviceUser
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.orm import undefer

from app.core.db import async_session_factory
from app.core.security import decode_token, verify_password
from app.core.permissions import Role
from app.models import Singer, KJDevice, _now_iso, Account


# ---------------------------------------------------------------------------
# SingerUser dataclass (used by auth router and RBAC deps)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SingerUser:
    id: str
    venue_id: str
    stage_name: str
    email: str | None
    role: Role
    token_claims: dict[str, object]


async def get_current_user(request: Request) -> SingerUser:
    """Dependency: resolve current singer or account from the Authorization header."""

    auth = request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = auth[7:]  # strip 'Bearer '
    claims = decode_token(token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Account-scoped token (mobile global identity)
    if claims.get("role") == "account":
        async with async_session_factory() as session:
            try:
                await session.rollback()
            except Exception:
                pass
            account = await _load_account(session, sub)
            if not account or account.deleted_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account not found or deactivated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return SingerUser(
            id=account.id,
            venue_id="",
            stage_name=account.real_name or account.email,
            email=account.email,
            role=Role.ACCOUNT,
            token_claims=claims,
        )

    # Singer-scoped token (legacy venue identity)
    async with async_session_factory() as session:
        from app.core.rls import set_session_venue_id
        try:
            await session.rollback()
        except Exception:
            pass
        await set_session_venue_id(session, claims.get("venue_id"))
        singer = await _load_singer(session, sub)

    if not singer or singer.deleted_at is not None or singer.deactivated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Singer not found or deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role = Role.from_string(getattr(singer, "role", "singer") or "singer") or Role.SINGER

    # Token venue_id should match DB venue_id for tamper protection
    token_venue = claims.get("venue_id")
    if token_venue and token_venue != singer.venue_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token venue mismatch",
        )

    return SingerUser(
        id=singer.id,
        venue_id=singer.venue_id,
        stage_name=singer.stage_name,
        email=singer.email,
        role=role,
        token_claims=claims,
    )


async def _load_account(session: AsyncSession, account_id: str) -> Account | None:
    result = await session.execute(
        select(Account).options(undefer(Account.password_hash)).where(Account.id == account_id)
    )
    return result.scalar_one_or_none()


async def _load_singer(session: AsyncSession, singer_id: str) -> Singer | None:
    result = await session.execute(
        select(Singer).options(undefer(Singer.password_hash)).where(Singer.id == singer_id)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# KJ device auth
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KJDeviceUser:
    id: str
    venue_id: str
    name: str
    token_claims: dict[str, object]


async def kj_auth(request: Request) -> KJDeviceUser:
    """Dependency: validate KJ device via x-api-key header or Bearer JWT.

    Priority:
      1. x-api-key header → look up device by API key hash (bcrypt verify)
      2. Authorization: Bearer <token> → decode JWT with kj_device_id claim
    """
    api_key = request.headers.get("x-api-key")
    if api_key:
        return await _kj_auth_by_api_key(api_key)

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
        claims = decode_token(token)
        if claims and claims.get("kj_device_id"):
            return _kj_auth_by_token_claims(claims)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing x-api-key or valid KJ Bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _kj_auth_by_api_key(api_key: str) -> KJDeviceUser:
    """Lookup KJ device by API key. Verify hash, check not revoked, update last_seen.

    Bcrypt is CPU-intensive and can corrupt SQLAlchemy\'s asyncpg greenlet state.
    We do the DB fetch (async), then close the session, verify bcrypt in a threadpool,
    then open a fresh session for the update.
    """
    import asyncio

    # Step 1: fetch candidate devices (async DB call)
    async with async_session_factory() as session:
        result = await session.execute(
            select(KJDevice).where(KJDevice.revoked_at.is_(None))
        )
        devices = result.scalars().all()

        # Collect (id, venue_id, name, api_key_hash) so we can close session before bcrypt
        candidates = [
            (d.id, d.venue_id, d.name, d.api_key_hash)
            for d in devices
        ]

    # Step 2: verify bcrypt OUTSIDE any async session (threadpool)
    device_id = venue_id = name = None
    for cid, cvid, cname, chash in candidates:
        # bcrypt releases the GIL; threadpool prevents greenlet corruption
        is_match = await asyncio.to_thread(verify_password, api_key, chash)
        if is_match:
            device_id = cid
            venue_id = cvid
            name = cname
            break

    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Step 3: update last_seen in a fresh session
    async with async_session_factory() as session:
        from app.core.rls import set_session_venue_id
        try:
            await set_session_venue_id(session, str(venue_id))
        except Exception:
            pass
        await session.execute(
            update(KJDevice)
            .where(KJDevice.id == device_id)
            .values(last_seen=_now_iso())
        )
        await session.commit()

    return KJDeviceUser(
        id=device_id,
        venue_id=venue_id,
        name=name,
        token_claims={},
    )


def _kj_auth_by_token_claims(claims: dict) -> KJDeviceUser:
    """Validate KJ JWT claims and return KJDeviceUser."""
    device_id = claims.get("kj_device_id")
    venue_id = claims.get("venue_id")
    name = claims.get("kj_device_name", "")
    if not device_id or not venue_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid KJ token claims",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return KJDeviceUser(
        id=device_id,
        venue_id=venue_id,
        name=name,
        token_claims=claims,
    )


# ---------------------------------------------------------------------------
# Raw-token helpers (used by song catalog router for backward compat)
# ---------------------------------------------------------------------------

def _extract_token(request: Request) -> str:
    """Extract Bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth[len("Bearer "):]


async def require_admin(request: Request) -> dict:
    """Dependency: enforce role == admin or kj and venue_id present in token."""
    token = _extract_token(request)
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = payload.get("role", "").lower()
    if role not in ("admin", "kj"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or KJ access required",
        )
    if not payload.get("venue_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token missing venue_id",
        )
    return payload


async def require_platform_admin(request: Request) -> dict:
    """Dependency: enforce platform admin role only."""
    token = _extract_token(request)
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = payload.get("role", "").lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return payload


async def optional_token(request: Request) -> Optional[dict]:
    """Dependency: return decoded token if present, else None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        return decode_token(auth[len("Bearer "):])
    except Exception:
        return None


def venue_match(venue_id_param: str, token_payload: dict) -> bool:
    """Return True when the URL venue_id matches the token venue_id."""
    token_venue = token_payload.get("venue_id")
    if token_venue is None:
        return True
    return str(token_venue) == str(venue_id_param)


async def get_current_user_or_kj(request: Request) -> SingerUser | KJDeviceUser:
    """Allow either a singer Bearer token or a KJ device x-api-key/Bearer."""
    api_key = request.headers.get("x-api-key")
    auth = request.headers.get("Authorization", "")
    if api_key or (auth.lower().startswith("bearer ") and not _looks_like_singer_token(auth)):
        return await kj_auth(request)
    return await get_current_user(request)


def _looks_like_singer_token(auth_header: str) -> bool:
    """Heuristic: singer tokens have a singer_id sub, not kj_device_id."""
    try:
        token = auth_header[7:]
        claims = decode_token(token)
        if not claims:
            return False
        return "kj_device_id" not in claims and "account" not in claims.get("role", "")
    except Exception:
        return False


def venue_match_or_admin(venue_id_param: str, token_payload: dict) -> bool:
    """Return True for matching venue, admin, or KJ tokens."""
    if venue_match(venue_id_param, token_payload):
        return True
    role = (token_payload.get("role") or "").lower()
    return role in ("admin", "kj")
