"""Authentication layer: singer resolution + token helpers + venue scoping.

Provides two usage patterns:
1. SingerUser resolution (auth router, RBAC deps) — get_current_user, SingerUser
2. Raw token dicts (song catalog router) — require_admin, optional_token, venue_match
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.db import async_session_factory
from app.core.security import decode_token
from app.core.permissions import Role
from app.models import Singer


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
    """Dependency: resolve current singer from the Authorization header."""
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

    # Load singer from DB for current role / venue_id (could be stale in token)
    async with async_session_factory() as session:
        singer = await _load_singer(session, sub)

    if not singer or singer.deleted_at is not None:
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


async def _load_singer(session: AsyncSession, singer_id: str) -> Singer | None:
    result = await session.execute(
        select(Singer).where(Singer.id == singer_id)
    )
    return result.scalar_one_or_none()


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
    """Dependency: enforce role == admin or kj. 403 otherwise. Returns raw token dict."""
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
