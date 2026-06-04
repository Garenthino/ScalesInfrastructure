"""Authentication router: register, login, refresh, me/whoami.

All endpoints are synchronous around I/O and use passlib/argon2+bcrypt
for password hashing.  Tokens carry claims:
- `sub`: singer.id (UUID)
- `venue_id`: the singer's tenant
- `role`: current role string
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.db import async_session_factory
from app.core.security import hash_password, verify_password
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.core.auth import get_current_user, SingerUser
from app.core.permissions import Role
from app.models import Singer

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_session() -> AsyncSession:
    async with async_session_factory() as session:
        return session


async def _get_singer_by_email(session: AsyncSession, email: str) -> Singer | None:
    result = await session.execute(
        select(Singer).where(
            Singer.email == email,
            Singer.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _get_singer_by_id(session: AsyncSession, singer_id: str) -> Singer | None:
    result = await session.execute(
        select(Singer).where(
            Singer.id == singer_id,
            Singer.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


def issue_token_pair(singer: Singer) -> dict[str, object]:
    claims = {
        "venue_id": singer.venue_id,
        "role": getattr(singer, "role", "singer"),
    }
    return {
        "access_token": create_access_token(str(singer.id), extra_claims=claims),
        "token_type": "bearer",
        "expires_in": 60 * 15,
        "refresh_token": create_refresh_token(str(singer.id), extra_claims=claims),
    }


# ---------------------------------------------------------------------------
# Schemas (inline to keep router self-contained)
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field, EmailStr, ConfigDict


class _ScalesModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(_ScalesModel):
    venue_id: str
    stage_name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    real_name: str | None = None
    pronouns: str | None = None
    phone: str | None = None


class RegisterResponse(_ScalesModel):
    id: str
    message: str = "Registration successful"


class LoginRequest(_ScalesModel):
    email: EmailStr
    password: str


class LoginResponse(_ScalesModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    singer_id: str
    venue_id: str


class RefreshRequest(_ScalesModel):
    refresh_token: str


class RefreshResponse(_ScalesModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str


class MeResponse(_ScalesModel):
    id: str
    venue_id: str
    stage_name: str
    real_name: str | None
    email: str | None
    role: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest):
    async with async_session_factory() as session:
        from app.core.rls import set_session_venue_id
        await set_session_venue_id(session, body.venue_id)
        existing = await _get_singer_by_email(session, body.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A singer with this email already exists.",
            )

        import uuid
        singer = Singer(
            id=str(uuid.uuid4()),
            venue_id=body.venue_id,
            stage_name=body.stage_name,
            real_name=body.real_name,
            pronouns=body.pronouns,
            email=body.email,
            phone=body.phone,
            password_hash=hash_password(body.password),
            role="singer",
        )
        session.add(singer)
        await session.commit()
        return RegisterResponse(id=singer.id)


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    async with async_session_factory() as session:
        singer = await _get_singer_by_email(session, body.email)
        if singer:
            from app.core.rls import set_session_venue_id
            await set_session_venue_id(session, str(singer.venue_id))
        if not singer or not singer.password_hash:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not verify_password(body.password, singer.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        tokens = issue_token_pair(singer)
        return LoginResponse(
            access_token=tokens["access_token"],  # type: ignore[arg-type]
            token_type="bearer",
            expires_in=15 * 60,
            refresh_token=tokens["refresh_token"],  # type: ignore[arg-type]
            singer_id=singer.id,
            venue_id=singer.venue_id,
        )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(body: RefreshRequest):
    claims = decode_token(body.refresh_token)
    if not claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if claims.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with async_session_factory() as session:
        from app.core.rls import set_session_venue_id
        singer = await _get_singer_by_id(session, claims["sub"])
        if singer:
            await set_session_venue_id(session, str(singer.venue_id))
        if not singer or singer.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Singer not found or deactivated",
                headers={"WWW-Authenticate": "Bearer"},
            )

    tokens = issue_token_pair(singer)
    return RefreshResponse(
        access_token=tokens["access_token"],  # type: ignore[arg-type]
        token_type="bearer",
        expires_in=15 * 60,
        refresh_token=tokens["refresh_token"],  # type: ignore[arg-type]
    )


@router.get("/me", response_model=MeResponse)
async def me(current: SingerUser = Depends(get_current_user)):
    return MeResponse(
        id=current.id,
        venue_id=current.venue_id,
        stage_name=current.stage_name,
        real_name=None,         # not stored on SingerUser dataclass; read singer row if needed
        email=current.email,
        role=current.role.value,
    )
