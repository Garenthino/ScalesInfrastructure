"""Global account router for mobile identity.

Endpoints
---------
Public:
    POST /accounts/register  — create a global mobile account
    POST /accounts/login     — authenticate a global account

Authenticated:
    GET  /accounts/me        — return current account profile
    PUT  /accounts/me        — update current account profile
    POST /accounts/me/avatar — upload account avatar
    POST /accounts/refresh   — refresh account access token
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
import os

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.db import async_session_factory
from app.core.queue_service import SingerEventPublisher
from app.core.security import hash_password, verify_password
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.auth import get_current_user, SingerUser
from app.models import Account, Singer
from app.schemas import (
    AccountRegisterRequest,
    AccountLoginRequest,
    AccountMeOut,
    AccountMeUpdate,
    AccountRegisterResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_account_by_email(session: AsyncSession, email: str) -> Account | None:
    result = await session.execute(
        select(Account)
        .where(
            Account.email == email,
            Account.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _get_account_by_id(session: AsyncSession, account_id: str) -> Account | None:
    result = await session.execute(
        select(Account).where(
            Account.id == account_id,
            Account.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


def _issue_account_token_pair(account: Account) -> dict[str, Any]:
    claims = {
        "account_id": account.id,
        "role": "account",
    }
    return {
        "access_token": create_access_token(str(account.id), extra_claims=claims),
        "token_type": "bearer",
        "expires_in": 60 * 15,
        "refresh_token": create_refresh_token(str(account.id), extra_claims=claims),
    }


def _account_out(account: Account) -> AccountMeOut:
    return AccountMeOut(
        id=account.id,
        email=account.email,
        real_name=account.real_name,
        pronouns=account.pronouns,
        phone=account.phone,
        bio=account.bio,
        avatar_url=account.avatar_url,
        social_links=account.social_links,
        is_active=bool(account.is_active),
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/register", response_model=AccountRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_account(body: AccountRegisterRequest):
    """Create a global mobile account.

    The account can later join one or more venues via POST /venues/{venue_id}/join.
    """
    async with async_session_factory() as session:
        existing = await _get_account_by_email(session, body.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            )

        now = _now_iso()
        account = Account(
            id=str(uuid.uuid4()),
            email=body.email,
            password_hash=hash_password(body.password),
            real_name=body.real_name,
            pronouns=body.pronouns,
            phone=body.phone,
            bio=body.bio,
            avatar_url=body.avatar_url,
            social_links=body.social_links,
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)

        tokens = _issue_account_token_pair(account)
        return AccountRegisterResponse(
            access_token=tokens["access_token"],
            token_type=tokens["token_type"],
            expires_in=tokens["expires_in"],
            refresh_token=tokens["refresh_token"],
            account_id=account.id,
        )


@router.post("/login", response_model=AccountRegisterResponse)
async def login_account(body: AccountLoginRequest):
    """Authenticate a global account and return tokens."""
    async with async_session_factory() as session:
        try:
            await session.rollback()
        except Exception:
            pass

        account = await _get_account_by_email(session, body.email)
        if not account or not account.password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not verify_password(body.password, account.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        tokens = _issue_account_token_pair(account)
        return AccountRegisterResponse(
            access_token=tokens["access_token"],
            token_type=tokens["token_type"],
            expires_in=tokens["expires_in"],
            refresh_token=tokens["refresh_token"],
            account_id=account.id,
        )


# ---------------------------------------------------------------------------
# Authenticated endpoints
# ---------------------------------------------------------------------------

@router.get("/me", response_model=AccountMeOut)
async def account_me(current: SingerUser = Depends(get_current_user)):
    """Return the current global account profile.

    Requires an account-level access token (sub=account_id, role=account).
    """
    if getattr(current, "role", None) != "account":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account-scoped token required",
        )

    async with async_session_factory() as session:
        account = await _get_account_by_id(session, current.id)
        if not account:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Account not found")
        return _account_out(account)


@router.put("/me", response_model=AccountMeOut)
async def update_account_me(
    body: AccountMeUpdate,
    current: SingerUser = Depends(get_current_user),
):
    """Update the current global account profile.

    Also propagates changed fields to every linked per-venue singer row
    and broadcasts singer_changed events so the portal/KJ host stay in sync.
    """
    if getattr(current, "role", None) != "account":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account-scoped token required",
        )

    update_data = body.model_dump(exclude_unset=True)
    allowed = {"real_name", "pronouns", "phone", "bio", "avatar_url", "social_links"}

    async with async_session_factory() as session:
        account = await _get_account_by_id(session, current.id)
        if not account:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Account not found")

        for key, value in update_data.items():
            if key in allowed and value is not None:
                setattr(account, key, value)

        account.updated_at = _now_iso()
        await session.commit()
        await session.refresh(account)

        # Sync the same profile fields to every per-venue singer linked to this account
        result = await session.execute(
            select(Singer).where(
                Singer.account_id == account.id,
                Singer.deleted_at.is_(None),
            )
        )
        linked_singers = result.scalars().all()
        now = _now_iso()
        for singer in linked_singers:
            for key, value in update_data.items():
                if key in allowed and value is not None:
                    setattr(singer, key, value)
            singer.updated_at = now
        await session.commit()

        # Broadcast real-time updates to each venue
        for singer in linked_singers:
            await SingerEventPublisher.publish_singer_changed(
                str(singer.venue_id), singer, event_type="singer_changed"
            )

        return _account_out(account)


_AVATAR_UPLOAD_DIR = os.environ.get(
    "ACCOUNT_AVATAR_UPLOAD_DIR",
    os.path.join(
        os.path.dirname(__file__), "..", "..", "uploads", "avatars", "accounts"
    ),
)
_MAX_AVATAR_BYTES = 5 * 1024 * 1024
_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@router.post("/me/avatar", response_model=AccountMeOut)
async def upload_account_avatar(
    file: UploadFile = File(...),
    current: SingerUser = Depends(get_current_user),
):
    """Upload an avatar for the current account. Max 5MB. JPEG/PNG/WebP/GIF only."""
    if getattr(current, "role", None) != "account":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account-scoped token required",
        )

    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported image type: {file.content_type}",
        )

    contents = await file.read()
    if len(contents) > _MAX_AVATAR_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image too large. Max 5 MB.",
        )

    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        ext = "jpg"

    os.makedirs(_AVATAR_UPLOAD_DIR, exist_ok=True)
    file_id = str(uuid.uuid4())
    file_name = f"{current.id}_{file_id}.{ext}"
    file_path = os.path.join(_AVATAR_UPLOAD_DIR, file_name)

    with open(file_path, "wb") as f:
        f.write(contents)

    avatar_url = f"/uploads/avatars/accounts/{file_name}"

    async with async_session_factory() as session:
        account = await _get_account_by_id(session, current.id)
        if not account:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Account not found")
        account.avatar_url = avatar_url
        account.updated_at = _now_iso()
        await session.commit()
        await session.refresh(account)

        # Sync the new avatar to every linked per-venue singer row
        result = await session.execute(
            select(Singer).where(
                Singer.account_id == account.id,
                Singer.deleted_at.is_(None),
            )
        )
        linked_singers = result.scalars().all()
        now = _now_iso()
        for singer in linked_singers:
            singer.avatar_url = avatar_url
            singer.updated_at = now
        await session.commit()

        # Broadcast real-time updates to each venue
        for singer in linked_singers:
            await SingerEventPublisher.publish_singer_changed(
                str(singer.venue_id), singer, event_type="singer_changed"
            )

        return _account_out(account)


@router.post("/refresh", response_model=AccountRegisterResponse)
async def refresh_account(body: dict[str, Any]):
    claims = decode_token(body.get("refresh_token", ""))
    if not claims or claims.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with async_session_factory() as session:
        account = await _get_account_by_id(session, claims["sub"])
        if not account or account.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account not found or deactivated",
                headers={"WWW-Authenticate": "Bearer"},
            )

    tokens = _issue_account_token_pair(account)
    return AccountRegisterResponse(
        access_token=tokens["access_token"],
        token_type=tokens["token_type"],
        expires_in=tokens["expires_in"],
        refresh_token=tokens["refresh_token"],
        account_id=account.id,
    )
