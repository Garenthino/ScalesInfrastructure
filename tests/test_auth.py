"""JWT Auth + RBAC tests (async, SQLite aiosqlite)."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Set env BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-32-bytes-long-!!")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app as _real_app
from app.core.db import Base
from app.core.security import hash_password, decode_token
from app.core.permissions import Role, has_role
from app.models import Singer, Venue

TEST_DB_PATH = Path("./test.db")

_engine = None
_factory = None


def _init_test_db():
    """Idempotent setup of the test engine / session factory."""
    global _engine, _factory
    if _engine is not None:
        return _engine, _factory
    _engine = create_async_engine(os.environ["DATABASE_URL"], echo=False)
    _factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine, _factory


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine():
    e, _ = _init_test_db()
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield e
    await e.dispose()
    TEST_DB_PATH.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def session(engine):
    """Fresh session — auto-rollback on teardown."""
    _, factory = _init_test_db()
    async with factory() as s:
        yield s
        await s.rollback()


@pytest_asyncio.fixture
async def client(engine):
    # Patch the module-level session factory so the app uses test engine
    import app.core.db as db_mod
    import app.routers.auth as auth_mod
    import app.core.auth as core_auth_mod
    import app.routers.accounts as accounts_mod

    _orig_db_factory = getattr(db_mod, "async_session_factory", None)
    _orig_auth_factory = getattr(auth_mod, "async_session_factory", None)
    _orig_core_factory = getattr(core_auth_mod, "async_session_factory", None)
    _orig_accounts_factory = getattr(accounts_mod, "async_session_factory", None)

    _, factory = _init_test_db()
    db_mod.async_session_factory = factory
    auth_mod.async_session_factory = factory
    core_auth_mod.async_session_factory = factory
    accounts_mod.async_session_factory = factory
    db_mod.engine = engine

    transport = ASGITransport(app=_real_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    db_mod.async_session_factory = _orig_db_factory
    auth_mod.async_session_factory = _orig_auth_factory
    core_auth_mod.async_session_factory = _orig_core_factory
    accounts_mod.async_session_factory = _orig_accounts_factory


@pytest_asyncio.fixture
async def sample_venue(session):
    v = Venue(
        id=str(uuid.uuid4()),
        name="Test Karaoke",
        slug=f"test-karaoke-{uuid.uuid4().hex[:6]}",
    )
    session.add(v)
    await session.commit()
    return v


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def seed_singer(
    session,
    venue_id: str,
    role: str = "singer",
    password: str | None = "secret123",
    email: str | None = None,
):
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Test Singer",
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password) if password else None,
        role=role,
    )
    session.add(singer)
    await session.commit()
    return singer


async def login_for_token(client, email: str, password: str = "secret123") -> str:
    resp = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# 7 main e2e auth tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_register_returns_201_with_id(client, session, sample_venue):
    resp = await client.post("/v1/auth/register", json={
        "venue_id": sample_venue.id,
        "stage_name": "New Singer",
        "email": f"{uuid.uuid4().hex[:8]}@example.com",
        "password": "securepass123",
        "real_name": "Alice",
        "pronouns": "she/her",
        "phone": "+1234567890",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["message"] == "Registration successful"


@pytest.mark.anyio
async def test_register_duplicate_email_returns_409(client, session, sample_venue):
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    r1 = await client.post("/v1/auth/register", json={
        "venue_id": sample_venue.id,
        "stage_name": "First",
        "email": email,
        "password": "securepass123",
    })
    assert r1.status_code == 201

    r2 = await client.post("/v1/auth/register", json={
        "venue_id": sample_venue.id,
        "stage_name": "Second",
        "email": email,
        "password": "securepass123",
    })
    assert r2.status_code == 409


@pytest.mark.anyio
async def test_login_returns_valid_jwt_with_venue_id(client, session, sample_venue):
    singer = await seed_singer(session, sample_venue.id)
    resp = await client.post("/v1/auth/login", json={
        "email": singer.email,
        "password": "secret123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["singer_id"] == singer.id
    assert data["venue_id"] == sample_venue.id

    claims = decode_token(data["access_token"])
    assert claims is not None
    assert claims.get("venue_id") == sample_venue.id
    assert claims.get("role") == "singer"


@pytest.mark.anyio
async def test_login_invalid_credentials_returns_401(client, session, sample_venue):
    singer = await seed_singer(session, sample_venue.id)
    resp = await client.post("/v1/auth/login", json={
        "email": singer.email,
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_me_requires_token_returns_401(client):
    resp = await client.get("/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_me_with_valid_token_returns_profile(client, session, sample_venue):
    singer = await seed_singer(session, sample_venue.id)
    token = await login_for_token(client, singer.email)
    resp = await client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == singer.id
    assert data["venue_id"] == sample_venue.id
    assert data["role"] == "singer"
    assert data["stage_name"] == singer.stage_name


@pytest.mark.anyio
async def test_refresh_token_rotates_pair(client, session, sample_venue):
    singer = await seed_singer(session, sample_venue.id)
    login = await client.post("/v1/auth/login", json={
        "email": singer.email,
        "password": "secret123",
    })
    rt = login.json()["refresh_token"]

    resp = await client.post("/v1/auth/refresh", json={"refresh_token": rt})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data

    claims = decode_token(data["access_token"])
    assert claims is not None
    assert claims["sub"] == singer.id


@pytest.mark.anyio
async def test_refresh_invalid_token_returns_401(client):
    resp = await client.post("/v1/auth/refresh", json={"refresh_token": "totally.invalid.token"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Global account identity + venue join regression
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_account_register_login_refresh_me_venue_join_and_singers_me(client, session):
    """Regression: global account can register, login, refresh, call /me, join a venue,
    and the resulting per-venue singer profile includes account_id."""
    # Create a venue with an owner so the venue exists
    venue = Venue(
        id=str(uuid.uuid4()),
        name="Account QA Venue",
        slug=f"account-qa-{uuid.uuid4().hex[:6]}",
        is_active=1,
    )
    session.add(venue)
    await session.commit()

    email = f"{uuid.uuid4().hex[:8]}@example.com"
    password = "securepass123"

    # Register global account
    reg = await client.post("/v1/accounts/register", json={
        "email": email,
        "password": password,
        "stage_name": "Mobile QA",
        "first_name": "QA",
        "last_name": "Mobile",
    })
    assert reg.status_code == 201
    reg_data = reg.json()
    account_id = reg_data["account_id"]
    access_token = reg_data["access_token"]
    refresh_token = reg_data["refresh_token"]

    # /accounts/me
    me = await client.get("/v1/accounts/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    me_data = me.json()
    assert me_data["email"] == email
    assert me_data["first_name"] == "QA"
    assert me_data["last_name"] == "Mobile"
    assert me_data["real_name"] == "QA Mobile"

    # PUT /accounts/me with first/last name and stage_name
    put = await client.put(
        "/v1/accounts/me",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "first_name": "Updated",
            "last_name": "Name",
            "stage_name": "UpdatedStage",
            "bio": "Updated bio",
            "social_links": [{"platform": "x", "url": "https://x.com/qa"}],
        },
    )
    assert put.status_code == 200, put.text
    put_data = put.json()
    assert put_data["first_name"] == "Updated"
    assert put_data["last_name"] == "Name"
    assert put_data["real_name"] == "Updated Name"
    assert put_data["bio"] == "Updated bio"
    assert '"platform": "x"' in put_data["social_links"]

    # POST /accounts/me/avatar regression
    avatar = await client.post(
        "/v1/accounts/me/avatar",
        headers={"Authorization": f"Bearer {access_token}"},
        files={"file": ("avatar.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert avatar.status_code == 200, avatar.text
    assert avatar.json()["avatar_url"].startswith("/uploads/avatars/accounts/")

    # Join venue first so there is a linked singer row to propagate updates into
    join = await client.post(f"/v1/venues/{venue.id}/join", headers={"Authorization": f"Bearer {access_token}"})
    assert join.status_code == 200
    singer_id = join.json()["account_id"]
    singer_token = join.json()["access_token"]

    # /singers/me must expose account_id for mobile identity continuity
    sm = await client.get(f"/v1/venues/{venue.id}/singers/me", headers={"Authorization": f"Bearer {singer_token}"})
    assert sm.status_code == 200
    sm_data = sm.json()
    assert sm_data["id"] == singer_id
    assert sm_data.get("account_id") == account_id, f"expected account_id {account_id}, got {sm_data.get('account_id')}"

    # Per-venue singer row should reflect the account-level updates made before joining
    assert sm_data["first_name"] == "Updated"
    assert sm_data["last_name"] == "Name"
    assert sm_data["real_name"] == "Updated Name"
    assert sm_data["stage_name"] == "UpdatedStage"
    assert sm_data["bio"] == "Updated bio"
    assert '"platform": "x"' in sm_data["social_links"]
    assert sm_data["avatar_url"].startswith("/uploads/avatars/accounts/")

    # Duplicate stage_name at the venue should be rejected
    dup_stage = await client.put(
        "/v1/accounts/me",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"stage_name": "UpdatedStage"},
    )
    # Same singer keeping same name is allowed; here it is a no-op.
    assert dup_stage.status_code == 200, dup_stage.text

    # Another account trying to use the same stage_name at the same venue should fail
    other_email = f"{uuid.uuid4().hex[:8]}@example.com"
    other_reg = await client.post("/v1/accounts/register", json={
        "email": other_email,
        "password": password,
        "stage_name": "Other Stage",
    })
    assert other_reg.status_code == 201
    other_token = other_reg.json()["access_token"]
    other_join = await client.post(f"/v1/venues/{venue.id}/join", headers={"Authorization": f"Bearer {other_token}"})
    assert other_join.status_code == 200
    other_singer_token = other_join.json()["access_token"]

    # Try to change other singer's stage_name to UpdatedStage via /singers/profile
    dup_resp = await client.put(
        f"/v1/venues/{venue.id}/singers/profile",
        headers={"Authorization": f"Bearer {other_singer_token}"},
        json={"stage_name": "UpdatedStage"},
    )
    assert dup_resp.status_code == 409, dup_resp.text
    assert "already taken" in dup_resp.json()["detail"].lower()

    # Refresh
    refresh = await client.post("/v1/accounts/refresh", json={"refresh_token": refresh_token})
    assert refresh.status_code == 200
    new_token = refresh.json()["access_token"]

    # Re-joining the same venue should be idempotent and still return the same singer
    rejoin = await client.post(f"/v1/venues/{venue.id}/join", headers={"Authorization": f"Bearer {new_token}"})
    assert rejoin.status_code == 200
    assert rejoin.json()["account_id"] == singer_id


# ---------------------------------------------------------------------------
# RBAC middleware tests — using dynamic routes on the real app
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_role_based_rejects_unauthorized_role(client, session, sample_venue):
    from fastapi import Depends
    from app.core.dependencies import require_role
    from app.core.auth import SingerUser

    # Add a temporary route directly on the app under test
    @_real_app.get("/__admin_test__")
    async def _handler(current: SingerUser = Depends(require_role(Role.ADMIN))):
        return {"ok": True}

    singer = await seed_singer(session, sample_venue.id, role="singer")
    token = await login_for_token(client, singer.email)

    resp = await client.get("/__admin_test__", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert "admin" in resp.json()["detail"].lower()
    # clean up
    for r in list(_real_app.routes):
        if getattr(r, "path", None) == "/__admin_test__":
            _real_app.routes.remove(r)


@pytest.mark.anyio
async def test_role_based_allows_authorized_role(client, session, sample_venue):
    from fastapi import Depends
    from app.core.dependencies import require_role
    from app.core.auth import SingerUser

    @_real_app.get("/__admin2__")
    async def _handler2(current: SingerUser = Depends(require_role(Role.ADMIN))):
        return {"role": current.role.value}

    admin = await seed_singer(session, sample_venue.id, role="admin")
    token = await login_for_token(client, admin.email)

    resp = await client.get("/__admin2__", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
    for r in list(_real_app.routes):
        if getattr(r, "path", None) == "/__admin2__":
            _real_app.routes.remove(r)


# ---------------------------------------------------------------------------
# Direct unit tests for permission helpers
# ---------------------------------------------------------------------------

def test_has_role_hierarchy():
    assert has_role(Role.ADMIN, Role.SINGER)
    assert has_role(Role.ADMIN, Role.KJ)
    assert has_role(Role.ADMIN, Role.OWNER)
    assert has_role(Role.OWNER, Role.KJ)
    assert has_role(Role.OWNER, Role.SINGER)
    assert has_role(Role.KJ, Role.SINGER)
    assert has_role(Role.SINGER, Role.SINGER)
    assert not has_role(Role.SINGER, Role.KJ)
    assert not has_role(Role.KJ, Role.ADMIN)


def test_role_from_string():
    assert Role.from_string("admin") == Role.ADMIN
    assert Role.from_string("kj") == Role.KJ
    assert Role.from_string("Singer") == Role.SINGER
    assert Role.from_string("unknown") is None
