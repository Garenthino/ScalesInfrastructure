"""Commerce / merchandise router.

Endpoints
---------
Singer:
    GET  /venues/{venue_id}/merch           — list active products
    POST /venues/{venue_id}/merch/cart       — add item to cart
    GET  /venues/{venue_id}/merch/cart       — view cart
    POST /venues/{venue_id}/merch/checkout   — checkout (reduces inventory)
    GET  /venues/{venue_id}/merch/orders     — list my orders
    GET  /venues/{venue_id}/merch/orders/{order_id} — order detail

Admin (KJ+ only):
    GET  /venues/{venue_id}/merch/admin           — list all products + inventory
    POST /venues/{venue_id}/merch/admin           — create product
    PUT  /venues/{venue_id}/merch/admin/{product_id} — edit product
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.core.dependencies import require_role
from app.core.permissions import Role
from app.models import Product, Order, OrderItem, Venue
from app.schemas import (
    ProductCreate,
    ProductOut,
    CartOut,
    CartItemCreate,
    CheckoutRequest,
    OrderOut,
    PaginatedResponse,
)

router = APIRouter()


def NOW() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Ephemeral in-memory cart store (singer-scoped)
# ---------------------------------------------------------------------------
_cart_items: dict[str, list[dict[str, Any]]] = {}   # cart_id -> items
_singer_cart: dict[str, str] = {}                   # singer_id -> cart_id


def _get_or_create_cart(singer_id: str) -> str:
    cart_id = _singer_cart.get(singer_id)
    if not cart_id:
        cart_id = str(uuid.uuid4())
        _singer_cart[singer_id] = cart_id
        _cart_items[cart_id] = []
    return cart_id


def _get_cart_items(cart_id: str | None) -> list[dict[str, Any]]:
    if not cart_id:
        return []
    return _cart_items.get(cart_id, [])


def _clear_cart(cart_id: str) -> None:
    singer_id = None
    for sid, cid in list(_singer_cart.items()):
        if cid == cart_id:
            singer_id = sid
            break
    if singer_id:
        del _singer_cart[singer_id]
    _cart_items.pop(cart_id, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_venue(db: AsyncSession, venue_id: str) -> Venue:
    venue = (
        await db.execute(
            select(Venue).where(
                Venue.id == venue_id,
                Venue.is_active == 1,
                Venue.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


async def _build_cart_response(db: AsyncSession, cart_items: list[dict[str, Any]]) -> CartOut:
    total_cents = 0
    out_items: list[dict[str, Any]] = []
    for item in cart_items:
        prod = (
            await db.execute(select(Product).where(Product.id == item["product_id"]))
        ).scalar_one_or_none()
        if not prod:
            continue
        subtotal = prod.price_cents * item["quantity"]
        total_cents += subtotal
        out_items.append(
            {
                "product_id": item["product_id"],
                "name": prod.name,
                "price_cents": prod.price_cents,
                "quantity": item["quantity"],
                "subtotal_cents": subtotal,
            }
        )
    return CartOut(items=out_items, total_cents=total_cents)


async def _build_order_response(db: AsyncSession, order: Order) -> OrderOut:
    items_result = await db.execute(
        select(OrderItem, Product)
        .join(Product, Product.id == OrderItem.product_id)
        .where(OrderItem.order_id == order.id)
    )
    items: list[dict[str, Any]] = []
    for oi, prod in items_result.all():
        items.append(
            {
                "product_id": oi.product_id,
                "name": prod.name if prod else "Unknown",
                "quantity": oi.quantity,
                "unit_price_cents": oi.unit_price_cents,
                "subtotal_cents": oi.unit_price_cents * oi.quantity,
            }
        )
    return OrderOut(
        id=order.id,
        status=order.status,
        total_cents=order.total_cents,
        currency=order.currency or "USD",
        items=items,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


# ---------------------------------------------------------------------------
# Singer-facing endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[ProductOut])
async def list_products(
    venue_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List active products for a venue."""
    await _require_venue(db, venue_id)

    offset = (page - 1) * per_page
    result = await db.execute(
        select(Product)
        .where(
            Product.venue_id == venue_id,
            Product.is_active == 1,
            Product.deleted_at.is_(None),
        )
        .order_by(Product.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    items = result.scalars().all()

    count_result = await db.execute(
        select(func.count())
        .select_from(Product)
        .where(
            Product.venue_id == venue_id,
            Product.is_active == 1,
            Product.deleted_at.is_(None),
        )
    )
    total = count_result.scalar_one()

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/cart", response_model=CartOut)
async def add_to_cart(
    venue_id: str,
    body: CartItemCreate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a product to the singer's cart."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    await _require_venue(db, venue_id)

    # Verify product
    product = (
        await db.execute(
            select(Product).where(
                Product.id == body.product_id,
                Product.venue_id == venue_id,
                Product.is_active == 1,
                Product.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Product not found")
    if product.stock_quantity < body.quantity:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Insufficient stock")

    cart_id = _get_or_create_cart(current.id)
    cart_items = _cart_items[cart_id]

    # Update existing or append
    for item in cart_items:
        if item["product_id"] == body.product_id:
            item["quantity"] += body.quantity
            break
    else:
        cart_items.append({"product_id": body.product_id, "quantity": body.quantity})

    return await _build_cart_response(db, cart_items)


@router.get("/cart", response_model=CartOut)
async def get_cart(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the singer's current cart."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    cart_id = _singer_cart.get(current.id)
    cart_items = _get_cart_items(cart_id)
    return await _build_cart_response(db, cart_items)


@router.post("/checkout", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def checkout(
    venue_id: str,
    body: CheckoutRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Checkout: validate cart, reduce inventory, create Order + OrderItems."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    await _require_venue(db, venue_id)

    cart_items = _get_cart_items(body.cart_id)
    if not cart_items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Cart is empty")

    # Verify cart ownership
    cart_singer = None
    for sid, cid in _singer_cart.items():
        if cid == body.cart_id:
            cart_singer = sid
            break
    if cart_singer != current.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cart access denied")

    # Lock products and check inventory
    total_cents = 0
    order_items_data: list[dict[str, Any]] = []

    for item in cart_items:
        product = (
            await db.execute(
                select(Product).where(
                    Product.id == item["product_id"],
                    Product.venue_id == venue_id,
                    Product.is_active == 1,
                    Product.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if product is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"Product {item['product_id']} not found",
            )
        if product.stock_quantity < item["quantity"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Insufficient stock for {product.name}",
            )

        subtotal = product.price_cents * item["quantity"]
        total_cents += subtotal
        order_items_data.append(
            {
                "product_id": product.id,
                "quantity": item["quantity"],
                "unit_price_cents": product.price_cents,
                "subtotal_cents": subtotal,
            }
        )
        # Deduct inventory
        product.stock_quantity -= item["quantity"]

    # Persist order
    order_id = str(uuid.uuid4())
    order = Order(
        id=order_id,
        venue_id=venue_id,
        singer_id=current.id,
        status="completed",
        total_cents=total_cents,
        currency="USD",
    )
    db.add(order)
    await db.flush()

    for d in order_items_data:
        db.add(
            OrderItem(
                id=str(uuid.uuid4()),
                order_id=order_id,
                product_id=d["product_id"],
                quantity=d["quantity"],
                unit_price_cents=d["unit_price_cents"],
                created_at=NOW(),
            )
        )

    await db.commit()
    await db.refresh(order)

    # Clear ephemeral cart
    _clear_cart(body.cart_id)

    return await _build_order_response(db, order)


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the singer's orders at this venue."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    result = await db.execute(
        select(Order)
        .where(
            Order.venue_id == venue_id,
            Order.singer_id == current.id,
            Order.deleted_at.is_(None),
        )
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()
    return [await _build_order_response(db, o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(
    venue_id: str,
    order_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get order detail (must belong to singer at this venue)."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    order = (
        await db.execute(
            select(Order).where(
                Order.id == order_id,
                Order.venue_id == venue_id,
                Order.singer_id == current.id,
                Order.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found")

    return await _build_order_response(db, order)


# ---------------------------------------------------------------------------
# Admin (KJ+) endpoints
# ---------------------------------------------------------------------------

@router.get("/admin", response_model=list[ProductOut])
async def admin_list_products(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all products including inventory (KJ+ only)."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    checker = require_role(Role.KJ)
    checker(current)

    result = await db.execute(
        select(Product)
        .where(
            Product.venue_id == venue_id,
            Product.deleted_at.is_(None),
        )
        .order_by(Product.created_at.desc())
    )
    return result.scalars().all()


@router.post("/admin", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def admin_create_product(
    venue_id: str,
    body: ProductCreate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new product (KJ+ only)."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    checker = require_role(Role.KJ)
    checker(current)

    product = Product(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        name=body.name,
        description=body.description,
        sku=body.sku,
        price_cents=body.price_cents,
        currency=body.currency or "USD",
        image_url=body.image_url,
        stock_quantity=body.stock_quantity,
        is_active=1 if body.is_active else 0,
        dropshipper_id=body.dropshipper_id,
        created_at=NOW(),
        updated_at=NOW(),
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.put("/admin/{product_id}", response_model=ProductOut)
async def admin_update_product(
    venue_id: str,
    product_id: str,
    body: ProductCreate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit an existing product (KJ+ only)."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    checker = require_role(Role.KJ)
    checker(current)

    product = (
        await db.execute(
            select(Product).where(
                Product.id == product_id,
                Product.venue_id == venue_id,
                Product.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Product not found")

    product.name = body.name
    product.description = body.description
    product.sku = body.sku
    product.price_cents = body.price_cents
    product.currency = body.currency or "USD"
    product.image_url = body.image_url
    product.stock_quantity = body.stock_quantity
    product.is_active = 1 if body.is_active else 0
    product.dropshipper_id = body.dropshipper_id
    product.updated_at = NOW()

    await db.commit()
    await db.refresh(product)
    return product
