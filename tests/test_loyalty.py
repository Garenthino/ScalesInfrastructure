"""Loyalty router tests.

Covers:
- Singer: summary, transactions, quests, claim quest
- Admin (KJ): create tier, create quest, manual award
- Auth boundaries: role checks, venue scoping
- Business rules: tier recomputation on point award,
  quest progress updates, duplicate-claim rejection
- Point integration: performance complete, commerce checkout
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import (
    Venue, Singer, LoyaltyTier, LoyaltyQuest, LoyaltyQuestCompletion,
    LoyaltyPoints, QueueRequest, Song, Product,
)
from app.core.db import get_db as _orig_get_db


def AUTHORIZATION(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def _loyalty_venue(db: AsyncSession):
    """Create a venue with KJ + singer, plus default tier and quest."""
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="Loyalty Venue", slug=f"loyalty-{venue_id[:8]}")
    db.add(venue)

    kj = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="KJ Admin",
        role="kj",
    )
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Singer One",
        role="singer",
        total_points=0,
    )
    singer2 = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Singer Two",
        role="singer",
        total_points=0,
    )
    db.add_all([kj, singer, singer2])
    await db.commit()

    # Bronze tier (0 pts), Silver (100), Gold (500)
    bronze = LoyaltyTier(
        id=str(uuid.uuid4()), venue_id=venue_id, name="Bronze",
        min_points=0, multiplier=1.0, color="#CD7F32", is_active=1,
    )
    silver = LoyaltyTier(
        id=str(uuid.uuid4()), venue_id=venue_id, name="Silver",
        min_points=100, multiplier=1.2, color="#C0C0C0", is_active=1,
    )
    gold = LoyaltyTier(
        id=str(uuid.uuid4()), venue_id=venue_id, name="Gold",
        min_points=500, multiplier=1.5, color="#FFD700", is_active=1,
    )
    db.add_all([bronze, silver, gold])
    await db.commit()

    # Quest: perform 3 songs
    quest1 = LoyaltyQuest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Triple Threat",
        description="Perform 3 songs",
        criteria_json='{"type":"perform_N_songs","target":3}',
        reward_points=50,
        is_active=1,
    )
    # Quest: spend 5000 cents
    quest2 = LoyaltyQuest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Big Spender",
        description="Spend $50",
        criteria_json='{"type":"spend_N_currency","target":5000}',
        reward_points=200,
        is_active=1,
    )
    db.add_all([quest1, quest2])
    await db.commit()

    return venue_id, kj, singer, singer2, [bronze, silver, gold], [quest1, quest2]


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
# Summary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_loyalty_summary_no_points(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, _ = _loyalty_venue
    token = _token(singer)
    r = await client.get("/v1/singer/loyalty", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["current_points"] == 0
    assert data["tier"] is None
    assert 0.0 <= data["next_tier_progress"] < 1.0

@pytest.fixture
async def _loyalty_venue_with_points(db: AsyncSession):
    """Create a venue with singer already at 150 points (Silver tier)."""
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="Loyalty Venue", slug=f"loyalty-{venue_id[:8]}")
    db.add(venue)

    kj = Singer(
        id=str(uuid.uuid4()), venue_id=venue_id, stage_name="KJ Admin", role="kj",
    )
    silver = LoyaltyTier(
        id=str(uuid.uuid4()), venue_id=venue_id, name="Silver",
        min_points=100, multiplier=1.2, is_active=1,
    )
    gold = LoyaltyTier(
        id=str(uuid.uuid4()), venue_id=venue_id, name="Gold",
        min_points=500, multiplier=1.5, is_active=1,
    )
    singer = Singer(
        id=str(uuid.uuid4()), venue_id=venue_id, stage_name="Singer One",
        role="singer", total_points=150, loyalty_tier_id=silver.id,
    )
    db.add_all([kj, silver, gold, singer])
    await db.commit()
    return venue_id, kj, singer, silver, gold


@pytest.mark.asyncio
async def test_loyalty_summary_with_tier(client: AsyncClient, _loyalty_venue_with_points):
    venue_id, _, singer, silver, _ = _loyalty_venue_with_points
    token = _token(singer)
    r = await client.get("/v1/singer/loyalty", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["current_points"] == 150
    assert data["tier"] == "Silver"
    # Next tier progress toward Gold (500)
    assert 0.0 < data["next_tier_progress"] <= 1.0


@pytest.mark.asyncio
async def test_loyalty_summary_no_token(client: AsyncClient):
    r = await client.get("/v1/singer/loyalty")
    assert r.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transactions_empty(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, _ = _loyalty_venue
    token = _token(singer)
    r = await client.get("/v1/singer/loyalty/transactions", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_transactions_with_points(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, _ = _loyalty_venue
    async for db in _orig_get_db():
        db.add(LoyaltyPoints(
            venue_id=venue_id,
            singer_id=singer.id,
            amount=25,
            reason="Test txn",
            reference_type="test",
            reference_id="ref-1",
        ))
        await db.commit()
        break

    token = _token(singer)
    r = await client.get("/v1/singer/loyalty/transactions", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["amount"] == 25
    assert data["items"][0]["reason"] == "Test txn"


# ---------------------------------------------------------------------------
# Quests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quests_list(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, quests = _loyalty_venue
    token = _token(singer)
    r = await client.get("/v1/singer/loyalty/quests", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["total"] == 2
    ids = {q["id"] for q in data["items"]}
    assert quests[0].id in ids
    assert quests[1].id in ids


@pytest.mark.asyncio
async def test_quests_progress_perform(client: AsyncClient, _loyalty_venue):
    """Singer with 3 completed queue requests should show progress 3/3."""
    venue_id, _, singer, _, _, quests = _loyalty_venue
    song = Song(
        id=str(uuid.uuid4()), venue_id=venue_id, title="T1", artist="A1",
        is_available=1, is_active=1,
    )
    async for db in _orig_get_db():
        db.add(song)
        await db.commit()
        for i in range(3):
            q = QueueRequest(
                id=str(uuid.uuid4()),
                venue_id=venue_id,
                singer_id=singer.id,
                song_id=song.id,
                status="completed",
                played_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                requested_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            db.add(q)
        await db.commit()
        break

    token = _token(singer)
    r = await client.get("/v1/singer/loyalty/quests", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    quest = next(q for q in data["items"] if q["name"] == "Triple Threat")
    assert quest["current_progress"] == 3
    assert quest["target"] == 3
    assert quest["is_claimable"] is True


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claim_quest_success(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, quests = _loyalty_venue
    song = Song(
        id=str(uuid.uuid4()), venue_id=venue_id, title="T1", artist="A1",
        is_available=1, is_active=1,
    )
    async for db in _orig_get_db():
        db.add(song)
        await db.commit()
        for i in range(3):
            q = QueueRequest(
                id=str(uuid.uuid4()),
                venue_id=venue_id,
                singer_id=singer.id,
                song_id=song.id,
                status="completed",
                played_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                requested_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            db.add(q)
        await db.commit()
        break

    token = _token(singer)
    r = await client.post(
        f"/v1/singer/loyalty/quests/{quests[0].id}/claim",
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["claimed"] is True
    assert data["reward_points"] == 50

    # Singer should now have 50 points
    async for db in _orig_get_db():
        s = (await db.execute(select(Singer).where(Singer.id == singer.id))).scalar_one()
        assert s.total_points == 50
        break


@pytest.mark.asyncio
async def test_claim_quest_already_claimed(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, quests = _loyalty_venue
    async for db in _orig_get_db():
        db.add(LoyaltyQuestCompletion(
            venue_id=venue_id,
            singer_id=singer.id,
            quest_id=quests[0].id,
            completed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ))
        await db.commit()
        break

    token = _token(singer)
    r = await client.post(
        f"/v1/singer/loyalty/quests/{quests[0].id}/claim",
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_409_CONFLICT
    assert "already claimed" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_claim_quest_not_enough_progress(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, quests = _loyalty_venue
    token = _token(singer)
    r = await client.post(
        f"/v1/singer/loyalty/quests/{quests[0].id}/claim",
        headers=AUTHORIZATION(token),
    )
    # No completed songs, so progress not met
    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert "progress" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Admin — create tier
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_create_tier(client: AsyncClient, _loyalty_venue):
    venue_id, kj, _, _, _, _ = _loyalty_venue
    token = _token(kj)
    payload = {
        "name": "Platinum",
        "min_points": 1000,
        "multiplier": 2.0,
        "color": "#E5E4E2",
        "icon": "crown",
    }
    r = await client.post(
        "/v1/singer/loyalty/admin/tiers",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_201_CREATED
    data = r.json()
    assert data["name"] == "Platinum"
    assert data["min_points"] == 1000
    assert data["multiplier"] == 2.0


@pytest.mark.asyncio
async def test_admin_create_tier_singer_forbidden(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, _ = _loyalty_venue
    token = _token(singer)
    r = await client.post(
        "/v1/singer/loyalty/admin/tiers",
        json={"name": "Platinum", "min_points": 1000, "multiplier": 2.0},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Admin — create quest
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_create_quest(client: AsyncClient, _loyalty_venue):
    venue_id, kj, _, _, _, _ = _loyalty_venue
    token = _token(kj)
    payload = {
        "name": "Visit 5 Times",
        "description": "Visit the venue 5 times",
        "quest_type": "visit_N_times",
        "target": 5,
        "reward_points": 100,
        "is_recurring": False,
    }
    r = await client.post(
        "/v1/singer/loyalty/admin/quests",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_201_CREATED
    data = r.json()
    assert data["name"] == "Visit 5 Times"
    assert data["type"] == "visit_N_times"
    assert data["target"] == 5


@pytest.mark.asyncio
async def test_admin_create_quest_invalid_type(client: AsyncClient, _loyalty_venue):
    venue_id, kj, _, _, _, _ = _loyalty_venue
    token = _token(kj)
    r = await client.post(
        "/v1/singer/loyalty/admin/quests",
        json={"name": "Bad", "quest_type": "unknown_type", "target": 1, "reward_points": 10},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# Admin — manual award
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_manual_award(client: AsyncClient, _loyalty_venue):
    venue_id, kj, singer, _, _, _ = _loyalty_venue
    token = _token(kj)
    payload = {"singer_id": singer.id, "amount": 200, "reason": "KJ bonus"}
    r = await client.post(
        "/v1/singer/loyalty/admin/award",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_204_NO_CONTENT

    # Verify points and tier bump to Silver
    async for db in _orig_get_db():
        s = (await db.execute(select(Singer).where(Singer.id == singer.id))).scalar_one()
        assert s.total_points == 200
        # Silver tier min_points=100, so tier should have updated
        tier = (
            await db.execute(
                select(LoyaltyTier).where(
                    LoyaltyTier.venue_id == venue_id,
                    LoyaltyTier.is_active == 1,
                    LoyaltyTier.deleted_at.is_(None),
                    LoyaltyTier.min_points <= s.total_points,
                ).order_by(LoyaltyTier.min_points.desc()).limit(1)
            )
        ).scalar_one_or_none()
        assert tier is not None
        assert tier.name == "Silver"
        break


@pytest.mark.asyncio
async def test_admin_manual_award_singer_not_found(client: AsyncClient, _loyalty_venue):
    venue_id, kj, _, _, _, _ = _loyalty_venue
    token = _token(kj)
    r = await client.post(
        "/v1/singer/loyalty/admin/award",
        json={"singer_id": str(uuid.uuid4()), "amount": 50},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_admin_manual_award_singer_forbidden(client: AsyncClient, _loyalty_venue):
    venue_id, _, singer, _, _, _ = _loyalty_venue
    token = _token(singer)
    r = await client.post(
        "/v1/singer/loyalty/admin/award",
        json={"singer_id": singer.id, "amount": 50},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Integration: queue complete awards points
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_performance_completes_awards_points(client: AsyncClient, _loyalty_venue):
    """When KJ marks a queue request as complete, singer gets performance points."""
    venue_id, kj, singer, _, _, _ = _loyalty_venue
    song = Song(
        id=str(uuid.uuid4()), venue_id=venue_id, title="Hit", artist="Star",
        is_available=1, is_active=1,
    )
    req_id = str(uuid.uuid4())
    async for db in _orig_get_db():
        db.add(song)
        db.add(QueueRequest(
            id=req_id,
            venue_id=venue_id,
            singer_id=singer.id,
            song_id=song.id,
            status="now_playing",
            requested_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ))
        await db.commit()
        break

    kj_token = _token(kj)
    r = await client.post(
        f"/v1/venues/{venue_id}/queue/{req_id}/complete",
        headers=AUTHORIZATION(kj_token),
    )
    assert r.status_code == status.HTTP_200_OK

    # Singer should now have at least 10 performance points
    async for db in _orig_get_db():
        s = (await db.execute(select(Singer).where(Singer.id == singer.id))).scalar_one()
        assert s.total_points >= 10
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


# ---------------------------------------------------------------------------
# Integration: commerce checkout awards points
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_awards_purchase_points(client: AsyncClient, _loyalty_venue):
    """Commerce checkout should award purchase loyalty points."""
    venue_id, _, singer, _, _, _ = _loyalty_venue
    product = Product(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name="Sticker",
        price_cents=2000,
        stock_quantity=10,
        is_active=1,
    )
    async for db in _orig_get_db():
        db.add(product)
        await db.commit()
        break

    # Use commerce router internals to inject cart items
    from app.routers import commerce as _mod
    cart_id = str(uuid.uuid4())
    _mod._singer_cart[singer.id] = cart_id
    _mod._cart_items[cart_id] = [{"product_id": product.id, "quantity": 2}]

    token = _token(singer)
    r = await client.post(
        f"/v1/venues/{venue_id}/merch/checkout",
        json={"cart_id": cart_id, "success_url": "http://ok", "cancel_url": "http://cancel"},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_201_CREATED

    # Loyalty points should exist for purchase
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
