"""Shared pytest fixtures."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncIterator

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: mark test as integration (requires docker or external services)")

# Patch app settings BEFORE anything else imports them
from app.core.config import settings

settings.JWT_SECRET_KEY = "test-jwt-secret-do-not-use-in-production"
settings.JWT_ALGORITHM = "HS256"

from app.middleware import security as _sec_mod
_sec_mod._buckets.clear()

# Prevent rate limiting from interfering with rapid test sequences
settings.RATE_LIMIT_REQUESTS = 10_000
settings.RATE_LIMIT_UNAUTHED_REQUESTS = 10_000
settings.RATE_LIMIT_WINDOW = 60

from app.main import app
from app.core.db import Base, get_db
from app.models import Venue, Song


@pytest.fixture(scope="session")
def event_loop():
    """Provide a session-scoped event loop."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def jwt_encode():
    """Return a JWT encoder for tests."""
    from jose import jwt

    def _encode(
        venue_id: str,
        role: str = "singer",
        user_id: str | None = None,
        expires: datetime | None = None,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id or str(uuid.uuid4()),
            "venue_id": venue_id,
            "role": role,
            "iat": now,
            "exp": expires or now.replace(year=now.year + 1),
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")

    return _encode


@pytest.fixture
def admin_token():
    venue_id = str(uuid.uuid4())
    return _admin_token(venue_id), venue_id


@pytest.fixture
def kj_token():
    venue_id = str(uuid.uuid4())
    return _admin_token(venue_id, role="kj"), venue_id


@pytest.fixture
def singer_token():
    venue_id = str(uuid.uuid4())
    return _admin_token(venue_id, role="singer"), venue_id


@pytest.fixture
def admin_token_mismatch():
    """Admin token with one venue_id, test should use a different venue_id for the URL."""
    return _admin_token(str(uuid.uuid4()), role="admin"), str(uuid.uuid4())


def _admin_token(venue_id: str, role: str = "admin") -> str:
    from jose import jwt
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "venue_id": venue_id,
        "role": role,
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------------------
# Async DB fixtures with fresh SQLite per test (NullPool)
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    """Yield an async session backed by a fresh SQLite file."""
    db_path = f"/tmp/test_scales_{uuid.uuid4().hex}.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        poolclass=NullPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()
    import os
    try:
        os.remove(db_path)
    except FileNotFoundError:
        pass


@pytest.fixture
async def client(db) -> AsyncIterator[AsyncClient]:
    """HTTPX async client with DB overridden."""
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    # Patch global session factory so auth helpers (get_current_user)
    # resolve singers from the test DB, not the default engine.
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    import app.core.db as _db_mod
    import app.core.auth as _auth_mod
    import app.routers.auth as _auth_router
    import app.routers.kj_auth as _kj_auth_router
    import app.websockets.queue_ws as _ws_mod
    _orig_db_factory = _db_mod.async_session_factory
    _orig_auth_factory = _auth_mod.async_session_factory
    _orig_router_factory = _auth_router.async_session_factory
    _orig_kj_factory = _kj_auth_router.async_session_factory
    _orig_ws_factory = _ws_mod.async_session_factory
    _fresh_factory = async_sessionmaker(
        db.bind, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    _db_mod.async_session_factory = _fresh_factory
    _auth_mod.async_session_factory = _fresh_factory
    _auth_router.async_session_factory = _fresh_factory
    _kj_auth_router.async_session_factory = _fresh_factory
    _ws_mod.async_session_factory = _fresh_factory

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
    app.dependency_overrides.clear()
    _db_mod.async_session_factory = _orig_db_factory
    _auth_mod.async_session_factory = _orig_auth_factory
    _auth_router.async_session_factory = _orig_router_factory
    _kj_auth_router.async_session_factory = _orig_kj_factory
    _ws_mod.async_session_factory = _orig_ws_factory


@pytest.fixture
async def venue_with_songs(db: AsyncSession):
    """Fixture: a venue with 5 seeded songs."""
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name="Test Venue",
        slug=f"test-venue-{venue_id[:8]}",
    )
    db.add(venue)
    await db.commit()

    songs = [
        Song(
            venue_id=venue_id,
            title="Bohemian Rhapsody",
            artist="Queen",
            album="A Night at the Opera",
            genre="Rock",
            category="Classic",
            language="English",
            duration_ms=354000,
            year=1975,
            is_available=1,
        ),
        Song(
            venue_id=venue_id,
            title="Hotel California",
            artist="Eagles",
            album="Hotel California",
            genre="Rock",
            category="Classic",
            language="English",
            duration_ms=391000,
            year=1977,
            is_available=1,
        ),
        Song(
            venue_id=venue_id,
            title="Thriller",
            artist="Michael Jackson",
            album="Thriller",
            genre="Pop",
            category="Dance",
            language="English",
            duration_ms=357000,
            year=1983,
            is_available=1,
        ),
        Song(
            venue_id=venue_id,
            title="Like a Prayer",
            artist="Madonna",
            album="Like a Prayer",
            genre="Pop",
            category="Dance",
            language="English",
            duration_ms=345000,
            year=1989,
            is_available=1,
        ),
        Song(
            venue_id=venue_id,
            title="Creep",
            artist="Radiohead",
            album="Pablo Honey",
            genre="Alternative",
            category="Indie",
            language="English",
            duration_ms=237000,
            year=1993,
            is_available=0,
        ),
    ]
    for s in songs:
        db.add(s)
    await db.commit()
    for s in songs:
        await db.refresh(s)
    return venue_id, songs
