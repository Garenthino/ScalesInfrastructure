"""Async SQLAlchemy engine, session, and declarative base."""

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base

from sqlalchemy import text

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
    If no token is present we explicitly set it to '' so RLS policies that
    use COALESCE with '' behave predictably.
    """
    async with async_session_factory() as session:
        request = get_current_request()
        if request is not None:
            vid = resolve_venue_id_from_token(request)
            try:
                await set_session_venue_id(session, vid)
            except Exception:
                # RLS setup may fail when the connection has a left-over aborted
                # transaction from a prior request.  Roll back and try again.
                await session.rollback()
                try:
                    await set_session_venue_id(session, vid)
                except Exception:
                    pass
        else:
            # No request context (e.g. startup scripts) — ensure variable is set
            # so policies that check '' don't inadvertently block everything.
            try:
                await session.execute(text("SET LOCAL app.current_venue_id = ''"))
            except Exception:
                pass
        yield session

