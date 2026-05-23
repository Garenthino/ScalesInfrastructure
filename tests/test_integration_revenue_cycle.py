"""Sprint 4: Full Revenue Integration Tests.

Exercises the complete revenue flywheel:
singer checks in → performs song → earns loyalty points → browses merch
  → adds to cart → checks out → claims quest → shares achievement
  → leaderboard reflects updated ranking.

Invoke:
    pytest tests/test_integration_revenue_cycle.py -v --integration
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import (
    Venue, Singer, Song, Product, LoyaltyTier, LoyaltyQuest, LoyaltyQuestCompletion, LoyaltyPoints, ShareEvent,
)
from app.core.db import get_db as _orig_get_db
from app.core.security import hash_password
from app.routers import commerce as _commerce_mod


def AUTHORIZATION(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def revenue_venue(db: AsyncSession):
    """A venue seeded for the full revenue cycle."""
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name="Revenue Venue",
        slug=f"revenue-{venue_id[:8]}",
        is_active=1,
    )
    db.add(venue)

    kj = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="KJ",
        email="kj@revenue.example.com",
        password_hash=hash_password("kjpassword"),
        role="kj",
    )
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Revenue Singer",
        email="singer@revenue.example.com",
        password_hash=hash_password("password123"),
        role="singer",
        total_points=0,
    )
    db.add_all([kj, singer])

    song = Song(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        title="Classic Hit",
        artist="Classic Artist",
        is_available=1,
        is_active=1,
        genre="Rock",
        duration_ms=180_000,
    )
    db.add(song)

    product = Product(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Band Tee",
        price_cents=3000,
        stock_quantity=50,
        is_active=1,
    )
    db.add(product)

    # Bronze / Silver tiers so singer can tier-up
    bronze = LoyaltyTier(id=str(uuid.uuid4()), venue_id=venue_id, name="Bronze", min_points=0, multiplier=1.0, is_active=1)
    silver = LoyaltyTier(id=str(uuid.uuid4()), venue_id=venue_id, name="Silver", min_points=100, multiplier=1.2, is_active=1)
    db.add_all([bronze, silver])

    # Quest: perform 1 song for 50 pts (so first complete triggers claimable)
    quest = LoyaltyQuest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="First Song",
        description="Perform your first song",
        criteria_json='{"type":"perform_N_songs","target":1}',
        reward_points=50,
        is_active=1,
    )
    db.add(quest)

    await db.commit()
    for obj in (kj, singer, song, product, bronze, silver, quest):
        await db.refresh(obj)

    return venue_id, kj, singer, song, product, silver, quest


def _token(singer: Singer) -> str:
    from jose import jwt
    from app.core.config import settings
    now = datetime.now(timezone.utc)
    payload = {
        "sub": singer.id,
        "venue_id": singer.venue_id,
        "role": singer.role,
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm="HS256")


# ---------------------------------------------------------------------------
# Revenue flywheel
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.integration
async def test_full_revenue_flywheel(client, db, revenue_venue):
    """End-to-end: check in → perform → earn points → merch → cart →
    checkout → claim quest → share → leaderboard updated.
    """
    venue_id, kj, singer, song, product, silver, quest = revenue_venue

    # Step 0: log in as singer
    singer_login = await client.post(
        "/v1/auth/login",
        json={"email": "singer@revenue.example.com", "password": "password123"},
    )
    assert singer_login.status_code == status.HTTP_200_OK
    singer_token = singer_login.json()["access_token"]

    # Step 0.5: log in as KJ
    kj_login = await client.post(
        "/v1/auth/login",
        json={"email": "kj@revenue.example.com", "password": "kjpassword"},
    )
    assert kj_login.status_code == status.HTTP_200_OK
    kj_token = kj_login.json()["access_token"]

    # -----------------------------------------------------------------
    # Step 1: Singer checks in
    # -----------------------------------------------------------------
    checkin = await client.post(
        f"/v1/venues/{venue_id}/singers/checkin",
        headers=AUTHORIZATION(singer_token),
        json={"nickname": "Rock Legend"},
    )
    assert checkin.status_code == status.HTTP_200_OK
    assert checkin.json()["stage_name"] == "Revenue Singer"

    # -----------------------------------------------------------------
    # Step 2: Singer joins queue
    # -----------------------------------------------------------------
    join_q = await client.post(
        f"/v1/venues/{venue_id}/queue/join",
        headers=AUTHORIZATION(singer_token),
        json={"song_id": song.id, "notes": "For my family"},
    )
    assert join_q.status_code == status.HTTP_201_CREATED
    req_id = join_q.json()["request_id"]

    # -----------------------------------------------------------------
    # Step 3: KJ approves and starts
    # -----------------------------------------------------------------
    approve = await client.post(
        f"/v1/venues/{venue_id}/queue/admin/{req_id}/approve",
        headers=AUTHORIZATION(kj_token),
    )
    assert approve.status_code == status.HTTP_200_OK

    start = await client.post(
        f"/v1/venues/{venue_id}/queue/{req_id}/start",
        headers=AUTHORIZATION(kj_token),
    )
    assert start.status_code == status.HTTP_200_OK
    assert start.json()["status"] == "now_playing"

    # -----------------------------------------------------------------
    # Step 4: KJ completes → singer earns points
    # -----------------------------------------------------------------
    complete = await client.post(
        f"/v1/venues/{venue_id}/queue/{req_id}/complete",
        headers=AUTHORIZATION(kj_token),
    )
    complete_data = complete.json()
    assert complete_data["status"] == "completed"

    # Verify points in DB
    async for db in _orig_get_db():
        s = (await db.execute(select(Singer).where(Singer.id == singer.id))).scalar_one()
        assert s.total_points >= 10  # PERFORMANCE_POINTS
        txns = (
            await db.execute(
                select(LoyaltyPoints).where(
                    LoyaltyPoints.singer_id == singer.id,
                    LoyaltyPoints.reason == "Performance completed",
                )
            )
        ).scalars().all()
        assert len(txns) >= 1
        break

    # -----------------------------------------------------------------
    # Step 5: Browse merch
    # -----------------------------------------------------------------
    merch = await client.get(
        f"/v1/venues/{venue_id}/merch",
        headers=AUTHORIZATION(singer_token),
    )
    assert merch.status_code == status.HTTP_200_OK
    assert merch.json()["total"] >= 1

    # -----------------------------------------------------------------
    # Step 6: Add to cart
    # -----------------------------------------------------------------
    cart = await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        headers=AUTHORIZATION(singer_token),
        json={"product_id": product.id, "quantity": 2},
    )
    assert cart.status_code == status.HTTP_200_OK
    cart_data = cart.json()
    assert cart_data["total_cents"] == 6000

    # -----------------------------------------------------------------
    # Step 7: Checkout (reduces inventory + awards purchase points)
    # -----------------------------------------------------------------
    cart_id = _commerce_mod._singer_cart.get(singer.id)
    assert cart_id is not None

    checkout = await client.post(
        f"/v1/venues/{venue_id}/merch/checkout",
        headers=AUTHORIZATION(singer_token),
        json={"cart_id": cart_id, "success_url": "http://ok", "cancel_url": "http://cancel"},
    )
    assert checkout.status_code == status.HTTP_201_CREATED
    order_data = checkout.json()
    assert order_data["status"] == "completed"
    assert order_data["total_cents"] == 6000

    # Verify stock reduced
    async for db in _orig_get_db():
        p = (await db.execute(select(Product).where(Product.id == product.id))).scalar_one()
        assert p.stock_quantity == 48
        break

    # Verify purchase points
    async for db in _orig_get_db():
        txns = (
            await db.execute(
                select(LoyaltyPoints).where(
                    LoyaltyPoints.singer_id == singer.id,
                    LoyaltyPoints.reason == "Merch purchase",
                )
            )
        ).scalars().all()
        assert len(txns) >= 1
        break

    # 48h: Singer tier should have auto-recomputed
    async for db in _orig_get_db():
        s = (await db.execute(select(Singer).where(Singer.id == singer.id))).scalar_one()
        assert s.total_points >= 70  # 10 perf + 60 purchase + 50 first bonus
        break

    # -----------------------------------------------------------------
    # Step 8: Claim quest
    # -----------------------------------------------------------------
    claim = await client.post(
        f"/v1/singer/loyalty/quests/{quest.id}/claim",
        headers=AUTHORIZATION(singer_token),
    )
    assert claim.status_code == status.HTTP_200_OK
    claim_data = claim.json()
    assert claim_data["claimed"] is True
    assert claim_data["reward_points"] == 50

    # Verify quest completion persisted
    async for db in _orig_get_db():
        comp = (
            await db.execute(
                select(LoyaltyQuestCompletion).where(
                    LoyaltyQuestCompletion.quest_id == quest.id,
                    LoyaltyQuestCompletion.singer_id == singer.id,
                )
            )
        ).scalar_one_or_none()
        assert comp is not None
        break

    # -----------------------------------------------------------------
    # Step 9: Share achievement
    # -----------------------------------------------------------------
    share = await client.post(
        f"/v1/venues/{venue_id}/leaderboard/share",
        headers=AUTHORIZATION(singer_token),
        json={"content_type": "quest_first_song", "content_id": quest.id},
    )
    assert share.status_code == status.HTTP_200_OK
    share_data = share.json()
    assert share_data["url"].startswith("http://share.scales/")
    assert "expires_at" in share_data

    # Verify share_event in DB
    async for db in _orig_get_db():
        evt = (
            await db.execute(
                select(ShareEvent).where(ShareEvent.singer_id == singer.id)
            )
        ).scalar_one_or_none()
        assert evt is not None
        assert evt.content_type == "quest_first_song"
        break

    # -----------------------------------------------------------------
    # Step 10: Leaderboard reflects updated ranking
    # -----------------------------------------------------------------
    lb = await client.get(
        f"/v1/venues/{venue_id}/leaderboard",
    )
    assert lb.status_code == status.HTTP_200_OK
    lb_data = lb.json()
    assert lb_data["total"] >= 1
    found = next((entry for entry in lb_data["items"] if entry["singer_id"] == singer.id), None)
    assert found is not None, "Singer must appear on leaderboard"
    # Should be top-1 since only singer with points
    assert found["rank"] == 1
    assert found["score"] >= 120  # 10 perf + 60 purchase + 50 first bonus + 50 quest

    # -----------------------------------------------------------------
    # Step 11: Get individual leaderboard entry
    # -----------------------------------------------------------------
    entry = await client.get(
        f"/v1/venues/{venue_id}/leaderboard/{singer.id}",
    )
    assert entry.status_code == status.HTTP_200_OK
    entry_data = entry.json()
    assert entry_data["singer_id"] == singer.id
    assert entry_data["rank"] == 1


# ---------------------------------------------------------------------------
# Boundary checks
# ---------------------------------------------------------------------------

@pytest.mark.anyio
@pytest.mark.integration
async def test_leaderboard_venue_not_found(client):
    r = await client.get(f"/v1/venues/{str(uuid.uuid4())}/leaderboard")
    assert r.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
@pytest.mark.integration
async def test_share_without_auth(client, revenue_venue):
    venue_id, _, _, _, _, _, _ = revenue_venue
    r = await client.post(
        f"/v1/venues/{venue_id}/leaderboard/share",
        json={"content_type": "test", "content_id": str(uuid.uuid4())},
    )
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
@pytest.mark.integration
async def test_share_wrong_venue(client, revenue_venue):
    """Share endpoint must venue-scope."""
    venue_id, _, singer, _, _, _, _ = revenue_venue
    token = _token(singer)
    r = await client.post(
        f"/v1/venues/{str(uuid.uuid4())}/leaderboard/share",
        headers=AUTHORIZATION(token),
        json={"content_type": "test", "content_id": str(uuid.uuid4())},
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN
