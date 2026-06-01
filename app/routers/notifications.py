"""Notification router: device token registration and notification history."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from fastapi import APIRouter, Depends, HTTPException, status, Query

from app.core.auth import get_current_user, SingerUser
from app.core.db import get_db
from app.models import DeviceToken, Notification, Singer, NotificationSetting
from app.schemas import (
    DeviceTokenCreate,
    DeviceTokenOut,
    NotificationOut,
    NotificationListOut,
    NotificationMarkReadRequest,
    NotificationMarkReadResponse,
    PaginatedResponse,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
)

router = APIRouter()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_venue(venue_id: str, current: SingerUser) -> None:
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )


def _notification_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(n.id),
        singer_id=str(n.singer_id),
        venue_id=str(n.venue_id),
        notification_type=str(n.notification_type),
        title=str(n.title),
        body=str(n.body),
        data_json=str(n.data_json) if n.data_json else None,
        is_read=bool(n.is_read),
        sent_at=str(n.sent_at),
        read_at=str(n.read_at) if n.read_at else None,
        created_at=str(n.created_at),
    )


# ---------------------------------------------------------------------------
# Device Tokens
# ---------------------------------------------------------------------------

@router.post("/me/devices", response_model=DeviceTokenOut, status_code=status.HTTP_201_CREATED)
async def register_device(
    venue_id: str,
    body: DeviceTokenCreate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register (or re-register) a device token for FCM/APNs push."""
    _require_venue(venue_id, current)

    # Deactivate any existing token for this singer+platform+token combo,
    # then upsert the active one.
    existing = (
        await db.execute(
            select(DeviceToken)
            .where(
                DeviceToken.singer_id == current.id,
                DeviceToken.venue_id == venue_id,
                DeviceToken.platform == body.platform,
                DeviceToken.token == body.token,
            )
        )
    ).scalar_one_or_none()

    now = _now_iso()
    if existing:
        existing.is_active = 1
        existing.device_name = body.device_name or existing.device_name
        existing.updated_at = now
        await db.commit()
        await db.refresh(existing)
        return DeviceTokenOut(
            id=str(existing.id),
            singer_id=str(existing.singer_id),
            venue_id=str(existing.venue_id),
            platform=str(existing.platform),
            token=str(existing.token),
            device_name=str(existing.device_name) if existing.device_name else None,
            is_active=bool(existing.is_active),
            created_at=str(existing.created_at),
            updated_at=str(existing.updated_at) if existing.updated_at else None,
        )

    # If same singer+platform but different token, deactivate the old one
    await db.execute(
        delete(DeviceToken)
        .where(
            DeviceToken.singer_id == current.id,
            DeviceToken.venue_id == venue_id,
            DeviceToken.platform == body.platform,
            DeviceToken.is_active == 1,
        )
    )

    token = DeviceToken(
        singer_id=current.id,
        venue_id=venue_id,
        platform=body.platform,
        token=body.token,
        device_name=body.device_name,
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return DeviceTokenOut(
        id=str(token.id),
        singer_id=str(token.singer_id),
        venue_id=str(token.venue_id),
        platform=str(token.platform),
        token=str(token.token),
        device_name=str(token.device_name) if token.device_name else None,
        is_active=bool(token.is_active),
        created_at=str(token.created_at),
        updated_at=str(token.updated_at) if token.updated_at else None,
    )


@router.delete("/me/devices/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(
    venue_id: str,
    token_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-unregister a device token by setting is_active = 0."""
    _require_venue(venue_id, current)

    row = (
        await db.execute(
            select(DeviceToken)
            .where(
                DeviceToken.id == token_id,
                DeviceToken.singer_id == current.id,
                DeviceToken.venue_id == venue_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Device token not found")

    row.is_active = 0
    row.updated_at = _now_iso()
    await db.commit()
    return None


@router.get("/me/devices", response_model=PaginatedResponse[DeviceTokenOut])
async def list_devices(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List registered device tokens for the current singer."""
    _require_venue(venue_id, current)

    total = (
        await db.execute(
            select(func.count())
            .select_from(DeviceToken)
            .where(
                DeviceToken.singer_id == current.id,
                DeviceToken.venue_id == venue_id,
            )
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    rows = (
        await db.execute(
            select(DeviceToken)
            .where(
                DeviceToken.singer_id == current.id,
                DeviceToken.venue_id == venue_id,
            )
            .order_by(DeviceToken.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
    ).scalars().all()

    items = [
        DeviceTokenOut(
            id=str(r.id),
            singer_id=str(r.singer_id),
            venue_id=str(r.venue_id),
            platform=str(r.platform),
            token=str(r.token),
            device_name=str(r.device_name) if r.device_name else None,
            is_active=bool(r.is_active),
            created_at=str(r.created_at),
            updated_at=str(r.updated_at) if r.updated_at else None,
        )
        for r in rows
    ]

    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


# ---------------------------------------------------------------------------
# Notifications (In-App)
# ---------------------------------------------------------------------------

@router.get("/me/notifications", response_model=NotificationListOut)
async def list_notifications(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    unread_only: bool = Query(False),
):
    """Return paginated notification history for the current singer, with unread count."""
    _require_venue(venue_id, current)

    filters = [
        Notification.singer_id == current.id,
        Notification.venue_id == venue_id,
    ]
    if unread_only:
        filters.append(Notification.is_read == 0)

    total = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(*filters)
        )
    ).scalar_one()

    unread_count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.singer_id == current.id,
                Notification.venue_id == venue_id,
                Notification.is_read == 0,
            )
        )
    ).scalar_one()

    offset = (page - 1) * per_page
    rows = (
        await db.execute(
            select(Notification)
            .where(*filters)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
    ).scalars().all()

    items = [_notification_out(r) for r in rows]

    return NotificationListOut(
        items=items,
        total=total,
        unread_count=unread_count,
        page=page,
        per_page=per_page,
    )


@router.post("/me/notifications/read", response_model=NotificationMarkReadResponse)
async def mark_read(
    venue_id: str,
    body: NotificationMarkReadRequest,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark notifications as read. If no ids provided, marks ALL as read."""
    _require_venue(venue_id, current)

    from sqlalchemy import update

    now = _now_iso()
    if body.notification_ids:
        result = await db.execute(
            update(Notification)
            .where(
                Notification.singer_id == current.id,
                Notification.venue_id == venue_id,
                Notification.id.in_(body.notification_ids),
            )
            .values(is_read=1, read_at=now)
        )
    else:
        result = await db.execute(
            update(Notification)
            .where(
                Notification.singer_id == current.id,
                Notification.venue_id == venue_id,
                Notification.is_read == 0,
            )
            .values(is_read=1, read_at=now)
        )

    await db.commit()
    return NotificationMarkReadResponse(marked_count=result.rowcount or 0)


# ---------------------------------------------------------------------------
# Unread Count
# ---------------------------------------------------------------------------

@router.get("/me/notifications/unread-count")
async def unread_count(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return unread notification count for the current singer."""
    _require_venue(venue_id, current)

    count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.singer_id == current.id,
                Notification.venue_id == venue_id,
                Notification.is_read == 0,
            )
        )
    ).scalar_one()

    return {"unread_count": count}


# ---------------------------------------------------------------------------
# Notification Settings
# ---------------------------------------------------------------------------

def _settings_out(s: NotificationSetting) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        singer_id=str(s.singer_id),
        venue_id=str(s.venue_id),
        up_soon=bool(s.up_soon),
        on_stage=bool(s.on_stage),
        bumped=bool(s.bumped),
        queue_update=bool(s.queue_update),
        announcement=bool(s.announcement),
        social=bool(s.social),
        payment=bool(s.payment),
        created_at=str(s.created_at),
        updated_at=str(s.updated_at) if s.updated_at else None,
    )


async def _get_or_create_settings(
    db: AsyncSession, singer_id: str, venue_id: str
) -> NotificationSetting:
    row = (
        await db.execute(
            select(NotificationSetting)
            .where(
                NotificationSetting.singer_id == singer_id,
                NotificationSetting.venue_id == venue_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        now = _now_iso()
        row = NotificationSetting(
            singer_id=singer_id,
            venue_id=venue_id,
            up_soon=1,
            on_stage=1,
            bumped=1,
            queue_update=1,
            announcement=1,
            social=1,
            payment=1,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)

    return row


@router.get("/me/notification-settings", response_model=NotificationSettingsOut)
async def get_settings(
    venue_id: str,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current notification settings (auto-creates defaults if missing)."""
    _require_venue(venue_id, current)
    row = await _get_or_create_settings(db, current.id, venue_id)
    return _settings_out(row)


@router.put("/me/notification-settings", response_model=NotificationSettingsOut)
async def update_settings(
    venue_id: str,
    body: NotificationSettingsUpdate,
    current: SingerUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notification settings and return the updated record."""
    _require_venue(venue_id, current)

    row = await _get_or_create_settings(db, current.id, venue_id)

    for field in (
        "up_soon",
        "on_stage",
        "bumped",
        "queue_update",
        "announcement",
        "social",
        "payment",
    ):
        val = getattr(body, field, None)
        if val is not None:
            setattr(row, field, 1 if val else 0)

    row.updated_at = _now_iso()
    await db.commit()
    await db.refresh(row)
    return _settings_out(row)
