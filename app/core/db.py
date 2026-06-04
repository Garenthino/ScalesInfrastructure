"""Async SQLAlchemy engine, session, and declarative base."""

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base

from app.core.config import settings
from app.core.rls import (
    get_current_request,
    set_session_venue_id,
    resolve_venue_id_from_token,
)

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    pool_recycle=settings.DATABASE_POOL_RECYCLE,
    echo=settings.DEBUG,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async DB session.

    Automatically sets the PostgreSQL ``app.current_venue_id`` session
    variable for RLS when a venue_id can be resolved from the request.
    """
    async with async_session_factory() as session:
        request = get_current_request()
        if request is not None:
            vid = resolve_venue_id_from_token(request)
            try:
                await set_session_venue_id(session, vid)
            except Exception:
                # If RLS setup fails (e.g. aborted transaction), roll back
                # and try once more; if it still fails, continue without RLS.
                await session.rollback()
                try:
                    await set_session_venue_id(session, vid)
                except Exception:
                    pass
        yield session

