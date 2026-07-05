"""Global account router for mobile identity.

Endpoints
---------
Public:
    POST /accounts/register  — create a global mobile account
    POST /accounts/login     — authenticate a global account

Authenticated:
    GET  /accounts/me        — return current account profile
    POST /accounts/refresh   — refresh account access token
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import undefer

from app.core.db import async_session_factory
from app.core.security import hash_password, verify_password
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.auth import get_current_user, SingerUser
from app.models import Account, Singer
from app.schemas import (
    AccountRegisterRequest,
    AccountLoginRequest,
    AccountMeOut,
    AccountRegisterResponse,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_account_by_email(session: AsyncSession, email: str) -> Account | None:
    result = await session.execute(
        select(Account)
        .options(undefer(Account.password_hash))
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

        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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
