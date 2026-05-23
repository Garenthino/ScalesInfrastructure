"""Commerce router tests.

Covers:
- Singer: list products, add-to-cart, get-cart, checkout, list orders, get order detail
- Admin (KJ): list admin products, create product, update product
- Auth boundaries: role checks, venue scoping, cart ownership
- Business rules: inventory reduction on checkout, empty cart rejection,
  stock validation, cart merging
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Venue, Singer, Product, Order, OrderItem
from app.core.db import get_db as _orig_get_db
from app.routers import commerce as _mod


def AUTHORIZATION(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def _commerce_venue(db: AsyncSession):
    """Create a venue with products and two singers."""
    venue_id = str(uuid.uuid4())
    venue = Venue(id=venue_id, name="Merch Venue", slug=f"merch-{venue_id[:8]}")
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
    )
    singer2 = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name="Singer Two",
        role="singer",
    )
    db.add_all([kj, singer, singer2])
    await db.commit()

    products = [
        Product(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            name="T-Shirt",
            sku="TS-001",
            price_cents=2500,
            stock_quantity=10,
            is_active=1,
        ),
        Product(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            name="Hoodie",
            sku="HD-001",
            price_cents=5000,
            stock_quantity=5,
            is_active=1,
        ),
        Product(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            name="Sticker",
            sku="ST-001",
            price_cents=100,
            stock_quantity=100,
            is_active=0,
        ),
    ]
    for p in products:
        db.add(p)

    await db.commit()
    for p in products:
        await db.refresh(p)
    for s in [kj, singer, singer2]:
        await db.refresh(s)

    return venue_id, kj, singer, singer2, products


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
# Helper to grab the ephemeral cart id for a singer
# ---------------------------------------------------------------------------

def _get_cart_id(singer_id: str) -> str | None:
    return _mod._singer_cart.get(singer_id)


# ---------------------------------------------------------------------------
# List products
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_products_singer(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, products = _commerce_venue
    token = _token(singer)
    r = await client.get(f"/v1/venues/{venue_id}/merch", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["total"] == 2
    ids = {i["id"] for i in data["items"]}
    assert products[0].id in ids  # T-Shirt (active)
    assert products[1].id in ids  # Hoodie (active)
    assert products[2].id not in ids  # Sticker (inactive)


@pytest.mark.asyncio
async def test_list_products_venue_not_found(client: AsyncClient, _commerce_venue):
    _, _, singer, _, _ = _commerce_venue
    token = _token(singer)
    r = await client.get(f"/v1/venues/{str(uuid.uuid4())}/merch", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Cart operations
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_to_cart_and_get_cart(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, products = _commerce_venue
    token = _token(singer)

    # Add T-Shirt x 2
    r = await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[0].id, "quantity": 2},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["total_cents"] == 5000
    assert len(data["items"]) == 1
    assert data["items"][0]["quantity"] == 2
    assert data["items"][0]["subtotal_cents"] == 5000

    # Add Hoodie x 1
    r = await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[1].id, "quantity": 1},
        headers=AUTHORIZATION(token),
    )
    data = r.json()
    assert data["total_cents"] == 10000
    assert len(data["items"]) == 2

    # Get cart
    r = await client.get(f"/v1/venues/{venue_id}/merch/cart", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["total_cents"] == 10000


@pytest.mark.asyncio
async def test_add_to_cart_stock_insufficient(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, products = _commerce_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[1].id, "quantity": 100},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_409_CONFLICT
    assert "stock" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_add_to_cart_wrong_venue(client: AsyncClient, _commerce_venue):
    _, _, singer, _, products = _commerce_venue
    other_venue = str(uuid.uuid4())
    token = _token(singer)
    r = await client.post(
        f"/v1/venues/{other_venue}/merch/cart",
        json={"product_id": products[0].id, "quantity": 1},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_add_to_cart_inactive_product(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, products = _commerce_venue
    token = _token(singer)
    r = await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[2].id, "quantity": 1},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_checkout_creates_order_reduces_stock(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, products = _commerce_venue
    token = _token(singer)

    # Add items
    await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[0].id, "quantity": 2},
        headers=AUTHORIZATION(token),
    )
    await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[1].id, "quantity": 1},
        headers=AUTHORIZATION(token),
    )

    cart_id = _get_cart_id(singer.id)
    assert cart_id

    r = await client.post(
        f"/v1/venues/{venue_id}/merch/checkout",
        json={"cart_id": cart_id, "success_url": "http://ok", "cancel_url": "http://cancel"},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_201_CREATED
    order = r.json()
    assert order["status"] == "completed"
    assert order["total_cents"] == 10000
    assert len(order["items"]) == 2

    # Stock reduced
    async for db in _orig_get_db():
        ts = await db.execute(select(Product).where(Product.id == products[0].id))
        p0 = ts.scalar_one_or_none()
        assert p0 is not None
        assert p0.stock_quantity == 8  # 10 - 2
        hd = await db.execute(select(Product).where(Product.id == products[1].id))
        p1 = hd.scalar_one_or_none()
        assert p1 is not None
        assert p1.stock_quantity == 4  # 5 - 1
        break

    # Cart cleared
    assert cart_id not in _mod._cart_items
    assert singer.id not in _mod._singer_cart


@pytest.mark.asyncio
async def test_checkout_empty_cart(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, _ = _commerce_venue
    token = _token(singer)

    r = await client.post(
        f"/v1/venues/{venue_id}/merch/checkout",
        json={"cart_id": str(uuid.uuid4()), "success_url": "http://ok", "cancel_url": "http://cancel"},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_checkout_venue_mismatch(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, products = _commerce_venue
    token = _token(singer)

    await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[0].id, "quantity": 1},
        headers=AUTHORIZATION(token),
    )
    cart_id = _get_cart_id(singer.id)
    other_venue = str(uuid.uuid4())
    r = await client.post(
        f"/v1/venues/{other_venue}/merch/checkout",
        json={"cart_id": cart_id, "success_url": "http://ok", "cancel_url": "http://cancel"},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_checkout_unauthorized_cart(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, singer2, products = _commerce_venue

    # Singer1 adds to cart
    token1 = _token(singer)
    await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[0].id, "quantity": 1},
        headers=AUTHORIZATION(token1),
    )
    cart_id = _get_cart_id(singer.id)
    assert cart_id

    # Singer2 tries to checkout with singer1's cart
    token2 = _token(singer2)
    r = await client.post(
        f"/v1/venues/{venue_id}/merch/checkout",
        json={"cart_id": cart_id, "success_url": "http://ok", "cancel_url": "http://cancel"},
        headers=AUTHORIZATION(token2),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN
    assert "Cart access denied" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_orders_and_order_detail(client: AsyncClient, _commerce_venue):
    venue_id, kj, singer, _, products = _commerce_venue
    token = _token(singer)

    order_id = str(uuid.uuid4())
    order = Order(
        id=order_id,
        venue_id=venue_id,
        singer_id=singer.id,
        status="completed",
        total_cents=2500,
        currency="USD",
    )
    async for db in _orig_get_db():
        db.add(order)
        await db.flush()
        db.add(
            OrderItem(
                id=str(uuid.uuid4()),
                order_id=order_id,
                product_id=products[0].id,
                quantity=1,
                unit_price_cents=2500,
            )
        )
        await db.commit()
        break

    r = await client.get(f"/v1/venues/{venue_id}/merch/orders", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == order_id

    # Detail
    r = await client.get(
        f"/v1/venues/{venue_id}/merch/orders/{order_id}", headers=AUTHORIZATION(token)
    )
    assert r.status_code == status.HTTP_200_OK
    detail = r.json()
    assert detail["total_cents"] == 2500
    assert len(detail["items"]) == 1

    # KJ cannot see singer's order detail (404 because KJ is not owner)
    token_kj = _token(kj)
    r = await client.get(
        f"/v1/venues/{venue_id}/merch/orders/{order_id}", headers=AUTHORIZATION(token_kj)
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_order_detail_not_found(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, _ = _commerce_venue
    token = _token(singer)
    r = await client.get(
        f"/v1/venues/{venue_id}/merch/orders/{str(uuid.uuid4())}", headers=AUTHORIZATION(token)
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_list_orders_wrong_venue(client: AsyncClient, _commerce_venue):
    _, _, singer, _, _ = _commerce_venue
    token = _token(singer)
    r = await client.get(
        f"/v1/venues/{str(uuid.uuid4())}/merch/orders", headers=AUTHORIZATION(token)
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_admin_list_products(client: AsyncClient, _commerce_venue):
    venue_id, kj, _, _, products = _commerce_venue
    token = _token(kj)
    r = await client.get(f"/v1/venues/{venue_id}/merch/admin", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert len(data) == 3  # includes inactive product
    ids = {p["id"] for p in data}
    assert all(p.id in ids for p in products)


@pytest.mark.asyncio
async def test_admin_create_product(client: AsyncClient, _commerce_venue):
    venue_id, kj, _, _, _ = _commerce_venue
    token = _token(kj)
    payload = {
        "name": "Mug",
        "description": "Ceramic mug",
        "sku": "MU-001",
        "price_cents": 1500,
        "currency": "USD",
        "image_url": "https://example.com/mug.jpg",
        "stock_quantity": 20,
        "is_active": True,
    }
    r = await client.post(
        f"/v1/venues/{venue_id}/merch/admin", json=payload, headers=AUTHORIZATION(token)
    )
    assert r.status_code == status.HTTP_201_CREATED
    data = r.json()
    assert data["name"] == "Mug"
    assert data["price_cents"] == 1500
    assert data["stock_quantity"] == 20
    assert data["venue_id"] == venue_id


@pytest.mark.asyncio
async def test_admin_update_product(client: AsyncClient, _commerce_venue):
    venue_id, kj, _, _, products = _commerce_venue
    token = _token(kj)
    ts = products[0]
    payload = {
        "name": "T-Shirt V2",
        "description": "Updated",
        "sku": ts.sku,
        "price_cents": 3000,
        "currency": "USD",
        "image_url": ts.image_url,
        "stock_quantity": 15,
        "is_active": True,
    }
    r = await client.put(
        f"/v1/venues/{venue_id}/merch/admin/{ts.id}", json=payload, headers=AUTHORIZATION(token)
    )
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert data["name"] == "T-Shirt V2"
    assert data["price_cents"] == 3000
    assert data["stock_quantity"] == 15


@pytest.mark.asyncio
async def test_admin_update_product_not_found(client: AsyncClient, _commerce_venue):
    venue_id, kj, _, _, _ = _commerce_venue
    token = _token(kj)
    payload = {
        "name": "Ghost",
        "price_cents": 100,
        "stock_quantity": 0,
        "is_active": True,
    }
    r = await client.put(
        f"/v1/venues/{venue_id}/merch/admin/{str(uuid.uuid4())}", json=payload, headers=AUTHORIZATION(token)
    )
    assert r.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_admin_list_singer_forbidden(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, _ = _commerce_venue
    token = _token(singer)
    r = await client.get(f"/v1/venues/{venue_id}/merch/admin", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_admin_create_singer_forbidden(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, _ = _commerce_venue
    token = _token(singer)
    r = await client.post(
        f"/v1/venues/{venue_id}/merch/admin",
        json={"name": "X", "price_cents": 1, "stock_quantity": 1, "is_active": True},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_admin_update_singer_forbidden(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, products = _commerce_venue
    token = _token(singer)
    r = await client.put(
        f"/v1/venues/{venue_id}/merch/admin/{products[0].id}",
        json={"name": "T-Shirt V3", "price_cents": 100, "stock_quantity": 0, "is_active": True},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_admin_endpoints_venue_mismatch(client: AsyncClient, _commerce_venue):
    _, kj, _, _, products = _commerce_venue
    token = _token(kj)
    other_venue = str(uuid.uuid4())
    r = await client.get(f"/v1/venues/{other_venue}/merch/admin", headers=AUTHORIZATION(token))
    assert r.status_code == status.HTTP_403_FORBIDDEN

    r = await client.post(
        f"/v1/venues/{other_venue}/merch/admin",
        json={"name": "X", "price_cents": 1, "stock_quantity": 1, "is_active": True},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN

    r = await client.put(
        f"/v1/venues/{other_venue}/merch/admin/{products[0].id}",
        json={"name": "X", "price_cents": 1, "stock_quantity": 1, "is_active": True},
        headers=AUTHORIZATION(token),
    )
    assert r.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# Cart merging / duplicate handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cart_merge_quantity(client: AsyncClient, _commerce_venue):
    venue_id, _, singer, _, products = _commerce_venue
    token = _token(singer)

    # Add product 0 twice
    await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[0].id, "quantity": 2},
        headers=AUTHORIZATION(token),
    )
    await client.post(
        f"/v1/venues/{venue_id}/merch/cart",
        json={"product_id": products[0].id, "quantity": 1},
        headers=AUTHORIZATION(token),
    )

    r = await client.get(f"/v1/venues/{venue_id}/merch/cart", headers=AUTHORIZATION(token))
    data = r.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["quantity"] == 3
