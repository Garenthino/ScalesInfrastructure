"""Payments router: Stripe PaymentIntent, tips, priority bumps, webhooks.

Endpoints
---------
Singer:
    POST /payments/tip              — create PaymentIntent for tip
    POST /payments/priority-bump    — create PaymentIntent for queue priority bump
    GET  /singers/me/payments       — payment history (paginated)

Webhook:
    POST /stripe/webhook            — Stripe webhook handler
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.auth import get_current_user, SingerUser
from app.core.config import settings
from app.core.db import get_db
from app.core.points_service import add_points
from app.core.queue_service import QueueService
from app.models import Payment, Singer, Venue, QueueRequest
from app.schemas import (
    TipRequest,
    PriorityBumpRequest,
    PaymentIntentOut,
    PaymentOut,
    PaymentHistoryOut,
    PaginatedResponse,
    RefundRequest,
    RefundOut,
    WebhookSimulationRequest,
)

router = APIRouter()


def _NOW() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_cents(amount_cents: int, currency: str = "USD") -> str:
    """Format cents as human-readable currency string."""
    return f"${amount_cents / 100:.2f}"


# ---------------------------------------------------------------------------
# Stripe client (lazy init)
# ---------------------------------------------------------------------------

_stripe_client: Any = None


def _get_stripe():
    global _stripe_client
    if _stripe_client is None:
        import stripe
        stripe.api_key = settings.STRIPE_TEST_SECRET_KEY or "sk_test_"
        _stripe_client = stripe
    return _stripe_client


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


async def _count_priority_bumps_tonight(db: AsyncSession, venue_id: str, singer_id: str) -> int:
    """Count how many priority bumps this singer has made tonight."""
    # ISO date starts with YYYY-MM-DD, so LIKE comparison works on TEXT
    today_prefix = _NOW()[:10]
    result = await db.execute(
        select(func.count())
        .select_from(Payment)
        .where(
            Payment.venue_id == venue_id,
            Payment.singer_id == singer_id,
            Payment.payment_type == "priority_bump",
            Payment.status == "succeeded",
            Payment.created_at >= f"{today_prefix}T00:00:00Z",
            Payment.deleted_at.is_(None),
        )
    )
    return int(result.scalar_one() or 0)


def _payment_out(payment: Payment) -> PaymentOut:
    return PaymentOut(
        id=str(payment.id),
        venue_id=str(payment.venue_id),
        singer_id=str(payment.singer_id),
        recipient_id=str(payment.recipient_id) if payment.recipient_id else None,
        amount_cents=payment.amount_cents,
        currency=payment.currency,
        payment_type=payment.payment_type,  # type: ignore[arg-type]
        status=payment.status,  # type: ignore[arg-type]
        message=payment.message,
        refunded_at=payment.refunded_at,
        refund_amount_cents=payment.refund_amount_cents or 0,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        formatted_amount=_format_cents(payment.amount_cents, payment.currency),
    )


# ---------------------------------------------------------------------------
# TIP
# ---------------------------------------------------------------------------

@router.post("/tip", response_model=PaymentIntentOut)
async def create_tip_intent(
    venue_id: str,
    body: TipRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe PaymentIntent for tipping a singer/KJ."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    await _require_venue(db, venue_id)

    # Verify recipient exists at this venue
    recipient = (
        await db.execute(
            select(Singer).where(
                Singer.id == body.recipient_id,
                Singer.venue_id == venue_id,
                Singer.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if recipient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recipient not found")

    # Create Payment row
    payment_id = str(uuid.uuid4())
    payment = Payment(
        id=payment_id,
        venue_id=venue_id,
        singer_id=current.id,
        recipient_id=body.recipient_id,
        amount_cents=body.amount_cents,
        currency=body.currency,
        payment_type="tip",
        status="pending",
        message=body.message,
        created_at=_NOW(),
        updated_at=_NOW(),
    )
    db.add(payment)
    await db.flush()

    # Create Stripe PaymentIntent
    try:
        stripe = _get_stripe()
        intent = stripe.PaymentIntent.create(
            amount=body.amount_cents,
            currency=body.currency.lower(),
            metadata={
                "payment_id": payment_id,
                "venue_id": venue_id,
                "singer_id": current.id,
                "recipient_id": body.recipient_id,
                "payment_type": "tip",
            },
        )
        payment.stripe_payment_intent_id = intent.id
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc}",
        )

    return PaymentIntentOut(
        client_secret=intent.client_secret,
        payment_intent_id=intent.id,
    )


# ---------------------------------------------------------------------------
# PRIORITY BUMP
# ---------------------------------------------------------------------------

@router.post("/priority-bump", response_model=PaymentIntentOut)
async def create_priority_bump_intent(
    venue_id: str,
    body: PriorityBumpRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe PaymentIntent for a priority bump (max 2/night)."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    await _require_venue(db, venue_id)

    # Validate singer has an active queue request to bump
    queue_req = (
        await db.execute(
            select(QueueRequest).where(
                QueueRequest.id == body.request_id,
                QueueRequest.venue_id == venue_id,
                QueueRequest.singer_id == current.id,
                QueueRequest.status.in_(["pending", "approved"]),
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if queue_req is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Active queue request not found",
        )

    # Enforce max 2 priority bumps per singer per night
    bump_count = await _count_priority_bumps_tonight(db, venue_id, current.id)
    if bump_count >= 2:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Maximum of 2 priority bumps per night reached",
        )

    # Create Payment row
    payment_id = str(uuid.uuid4())
    payment = Payment(
        id=payment_id,
        venue_id=venue_id,
        singer_id=current.id,
        recipient_id=None,
        amount_cents=body.amount_cents,
        currency=body.currency,
        payment_type="priority_bump",
        status="pending",
        reference_type="queue_request",
        reference_id=body.request_id,
        created_at=_NOW(),
        updated_at=_NOW(),
    )
    db.add(payment)
    await db.flush()

    # Create Stripe PaymentIntent
    try:
        stripe = _get_stripe()
        intent = stripe.PaymentIntent.create(
            amount=body.amount_cents,
            currency=body.currency.lower(),
            metadata={
                "payment_id": payment_id,
                "venue_id": venue_id,
                "singer_id": current.id,
                "request_id": body.request_id,
                "payment_type": "priority_bump",
            },
        )
        payment.stripe_payment_intent_id = intent.id
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc}",
        )

    return PaymentIntentOut(
        client_secret=intent.client_secret,
        payment_intent_id=intent.id,
    )


# ---------------------------------------------------------------------------
# PAYMENT HISTORY
# ---------------------------------------------------------------------------

@router.get("/history", response_model=PaymentHistoryOut)
async def list_payments(
    venue_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current singer's payment history at this venue."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    offset = (page - 1) * per_page
    result = await db.execute(
        select(Payment)
        .where(
            Payment.venue_id == venue_id,
            Payment.singer_id == current.id,
            Payment.deleted_at.is_(None),
        )
        .order_by(Payment.created_at.desc())
        .offset(offset)
        .limit(per_page)
    )
    items = result.scalars().all()

    count_result = await db.execute(
        select(func.count())
        .select_from(Payment)
        .where(
            Payment.venue_id == venue_id,
            Payment.singer_id == current.id,
            Payment.deleted_at.is_(None),
        )
    )
    total = count_result.scalar_one()

    return PaymentHistoryOut(
        items=[_payment_out(p) for p in items],
        total=total,
        page=page,
        per_page=per_page,
    )


# ---------------------------------------------------------------------------
# STRIPE WEBHOOK
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """Handle Stripe webhook events for payment confirmation."""
    payload = await request.body()

    stripe = _get_stripe()
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        if webhook_secret and stripe_signature:
            event = stripe.Webhook.construct_event(
                payload, stripe_signature, webhook_secret
            )
        else:
            # In dev/test, parse raw JSON
            event = json.loads(payload)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Webhook validation failed: {exc}",
        )

    event_type = event.get("type", "")
    data_object = event.get("data", {}).get("object", {})

    if event_type == "payment_intent.succeeded":
        intent_id = data_object.get("id")
        metadata = data_object.get("metadata", {})
        payment_id = metadata.get("payment_id")

        if not payment_id:
            return {"status": "ignored", "reason": "no payment_id in metadata"}

        # Find payment
        payment = (
            await db.execute(
                select(Payment).where(
                    Payment.id == payment_id,
                    Payment.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if payment is None:
            return {"status": "ignored", "reason": "payment not found"}

        payment.status = "succeeded"
        payment.stripe_payment_intent_id = intent_id
        payment.updated_at = _NOW()
        await db.commit()

        # Handle side effects
        if payment.payment_type == "tip":
            await _handle_tip_success(db, payment)
        elif payment.payment_type == "priority_bump":
            await _handle_priority_bump_success(db, payment)

    elif event_type == "payment_intent.payment_failed":
        intent_id = data_object.get("id")
        payment = (
            await db.execute(
                select(Payment).where(
                    Payment.stripe_payment_intent_id == intent_id,
                    Payment.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if payment:
            payment.status = "failed"
            payment.updated_at = _NOW()
            await db.commit()

    return {"status": "ok"}


async def _handle_tip_success(db: AsyncSession, payment: Payment) -> None:
    """Award points for a successful tip."""
    await add_points(
        db,
        str(payment.venue_id),
        str(payment.singer_id),
        payment.amount_cents,
        f"Tip of {_format_cents(payment.amount_cents)}",
        "tip",
        str(payment.id),
    )


async def _handle_priority_bump_success(db: AsyncSession, payment: Payment) -> None:
    """Advance the queue request by up to 2 positions."""
    request_id = payment.reference_id
    if not request_id:
        return

    # Fetch the queue request
    queue_req = (
        await db.execute(
            select(QueueRequest).where(
                QueueRequest.id == request_id,
                QueueRequest.venue_id == payment.venue_id,
                QueueRequest.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if queue_req is None:
        return

    # Advance rotation_position by 2 (lower number = earlier in queue)
    # We do this by decrementing rotation_position, or renumbering
    current_pos = queue_req.rotation_position or 9999
    new_pos = max(1, current_pos - 2)

    # To avoid collisions, shift all items between new_pos and current_pos up by 1
    if new_pos < current_pos:
        affected = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.venue_id == payment.venue_id,
                    QueueRequest.rotation_position >= new_pos,
                    QueueRequest.rotation_position < current_pos,
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for item in affected:
            item.rotation_position = (item.rotation_position or 0) + 1
            item.updated_at = _NOW()
        queue_req.rotation_position = new_pos
        queue_req.updated_at = _NOW()
        await db.commit()


# ---------------------------------------------------------------------------
# REFUND
# ---------------------------------------------------------------------------

@router.post("/{payment_id}/refund", response_model=RefundOut)
async def refund_payment(
    venue_id: str,
    payment_id: str,
    body: RefundRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Refund a payment. Only admin/KJ or the original payer may refund."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.venue_id == venue_id,
                Payment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payment not found")

    # Authorization: admin/KJ can refund any; singers can only refund their own
    if current.role.value not in ("admin", "kj") and str(payment.singer_id) != str(current.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cannot refund this payment")

    if payment.status not in ("succeeded", "refunded", "partially_refunded"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot refund payment with status '{payment.status}'",
        )

    refund_amount = body.amount_cents if body.amount_cents is not None else payment.amount_cents
    if refund_amount < 1 or refund_amount > payment.amount_cents:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid refund amount",
        )

    # Check if total refunds exceed payment amount
    already_refunded = payment.refund_amount_cents or 0
    if already_refunded + refund_amount > payment.amount_cents:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Refund amount exceeds remaining balance",
        )

    refunded_at = _NOW()
    payment.refunded_at = refunded_at
    payment.refund_amount_cents = already_refunded + refund_amount
    payment.updated_at = refunded_at

    if payment.refund_amount_cents >= payment.amount_cents:
        payment.status = "refunded"
    else:
        payment.status = "partially_refunded"

    await db.commit()

    return RefundOut(
        payment_id=str(payment.id),
        status=payment.status,  # type: ignore[arg-type]
        refund_amount_cents=payment.refund_amount_cents,
        original_amount_cents=payment.amount_cents,
        refunded_at=refunded_at,
        reason=body.reason,
    )


@router.get("/{payment_id}/refund/status", response_model=RefundOut)
async def refund_status(
    venue_id: str,
    payment_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get refund status for a payment."""
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Venue access denied")

    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.venue_id == venue_id,
                Payment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payment not found")

    # Authorization
    if current.role.value not in ("admin", "kj") and str(payment.singer_id) != str(current.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cannot view this payment")

    refund_at = payment.refunded_at or _NOW()
    status_val = "refunded" if (payment.refund_amount_cents or 0) >= (payment.amount_cents or 0) else "partially_refunded"
    if payment.status == "refunded" or payment.status == "partially_refunded":
        status_val = payment.status  # type: ignore

    return RefundOut(
        payment_id=str(payment.id),
        status=status_val,  # type: ignore[arg-type]
        refund_amount_cents=payment.refund_amount_cents or 0,
        original_amount_cents=payment.amount_cents,
        refunded_at=payment.refunded_at if payment.refunded_at else "",
        reason=None,
    )


# ---------------------------------------------------------------------------
# WEBHOOK SIMULATION (admin/KJ gated — useful for CI and staging)
# ---------------------------------------------------------------------------

from app.core.auth import require_admin

@router.post("/simulate-webhook")
async def simulate_webhook(
    venue_id: str,
    body: WebhookSimulationRequest,
    _admin=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Simulate a Stripe webhook event for testing — admin/KJ only."""
    payment = (
        await db.execute(
            select(Payment).where(
                Payment.id == body.payment_id,
                Payment.venue_id == venue_id,
                Payment.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payment not found")

    now = _NOW()

    if body.event_type == "payment_intent.succeeded":
        payment.status = "succeeded"
        payment.updated_at = now
        if body.stripe_payment_intent_id:
            payment.stripe_payment_intent_id = body.stripe_payment_intent_id
        await db.commit()

        # Trigger side effects
        if payment.payment_type == "tip":
            await _handle_tip_success(db, payment)
        elif payment.payment_type == "priority_bump":
            await _handle_priority_bump_success(db, payment)

    elif body.event_type == "payment_intent.payment_failed":
        payment.status = "failed"
        payment.updated_at = now
        await db.commit()

    return {
        "status": "ok",
        "event_type": body.event_type,
        "payment_id": str(payment.id),
        "new_status": payment.status,
    }
