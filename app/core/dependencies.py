"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory
from app.core.auth import get_current_user, SingerUser
from app.core.permissions import Role, has_role


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session


def require_role(required: Role):
    """Dependency factory: reject requests from singers without the required role."""
    def _checker(current: SingerUser = Depends(get_current_user)) -> SingerUser:
        if not has_role(current.role, required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required.value}' required",
            )
        return current
    return _checker
