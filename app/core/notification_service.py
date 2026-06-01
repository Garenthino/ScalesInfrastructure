"""Notification delivery service: Celery tasks + Firebase Admin SDK."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Lazy imports so unit tests can run without firebase-admin installed
try:
    from firebase_admin import messaging, initialize_app, get_app
    from firebase_admin.credentials import Certificate
    _firebase_available = True
except Exception:  # pragma: no cover
    _firebase_available = False
    messaging = None  # type: ignore
    initialize_app = None  # type: ignore
    get_app = None  # type: ignore
    Certificate = None  # type: ignore

try:
    from celery import Celery
    _celery_available = True
except Exception:  # pragma: no cover
    _celery_available = False
    Celery = None  # type: ignore

# ---------------------------------------------------------------------------
# Firebase init (best-effort; missing creds → graceful no-op)
# ---------------------------------------------------------------------------

_FIREBASE_APP = None


def _init_firebase() -> Any | None:
    global _FIREBASE_APP
    if _FIREBASE_APP is not None:
        return _FIREBASE_APP
    if not _firebase_available:
        logger.debug("firebase_admin not installed")
        return None
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    if not cred_path:
        logger.debug("FIREBASE_CREDENTIALS_PATH not set; skipping Firebase init")
        return None
    if not os.path.exists(cred_path):
        logger.warning("Firebase credentials path missing: %s", cred_path)
        return None
    try:
        _FIREBASE_APP = initialize_app(Certificate(cred_path))
        logger.info("Firebase Admin SDK initialized")
        return _FIREBASE_APP
    except Exception as exc:
        logger.warning("Firebase init failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Celery app factory
# ---------------------------------------------------------------------------

_celery_app = None


def get_celery_app() -> Any | None:
    global _celery_app
    if _celery_app is not None:
        return _celery_app
    if not _celery_available:
        return None
    broker = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL"))
    if not broker:
        logger.debug("No CELERY_BROKER_URL or REDIS_URL; Celery unavailable")
        return None
    try:
        _celery_app = Celery("scales_notifications", broker=broker, backend=broker)
        _celery_app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            task_time_limit=30,
            task_soft_time_limit=20,
        )
        logger.info("Celery app created with broker %s", broker)
        return _celery_app
    except Exception as exc:
        logger.warning("Celery init failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Send FCM push
# ---------------------------------------------------------------------------

def _send_fcm(device_token: str, title: str, body: str, data: dict | None = None) -> bool:
    app = _init_firebase()
    if app is None or messaging is None:
        logger.debug("Firebase unavailable; dropping FCM push")
        return False
    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=device_token,
        )
        response = messaging.send(message, app=app)
        logger.debug("FCM sent: %s", response)
        return True
    except Exception as exc:
        logger.warning("FCM send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Notification queue
# ---------------------------------------------------------------------------

def enqueue_push_notification(
    device_tokens: list[str],
    title: str,
    body: str,
    data: dict | None = None,
) -> Any:
    """Enqueue a push-notification Celery task. Returns AsyncResult or None."""
    app = get_celery_app()
    if app is None:
        logger.debug("Celery unavailable; sending push synchronously")
        # Fall back to synchronous best-effort
        for token in device_tokens:
            _send_fcm(token, title, body, data)
        return None
    return app.send_task(
        "notification.send_push",
        args=[device_tokens, title, body, data],
        countdown=0,
    )


# ---------------------------------------------------------------------------
# Async helpers: persist + deliver
# ---------------------------------------------------------------------------

async def notify_singer(
    db: AsyncSession,
    singer_id: str,
    venue_id: str,
    notification_type: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> None:
    """Persist an in-app notification and enqueue push to all active device tokens."""
    from app.models import DeviceToken, Notification
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Persist in-app notification
    notification = Notification(
        singer_id=singer_id,
        venue_id=venue_id,
        notification_type=notification_type,
        title=title,
        body=body,
        data_json=json.dumps(data) if data else None,
        is_read=0,
        sent_at=now,
        created_at=now,
    )
    db.add(notification)

    # Fetch active device tokens
    rows = await db.execute(
        select(DeviceToken)
        .where(
            DeviceToken.singer_id == singer_id,
            DeviceToken.venue_id == venue_id,
            DeviceToken.is_active == 1,
        )
    )
    tokens = [str(r.token) for r in rows.scalars().all()]

    if tokens:
        enqueue_push_notification(
            device_tokens=tokens,
            title=title,
            body=body,
            data={"type": notification_type, **(data or {})},
        )

    # Best-effort: don't let notification failures break queue ops
    try:
        await db.commit()
    except Exception as exc:
        logger.warning("Notification persist failed: %s", exc)
        await db.rollback()


# ---------------------------------------------------------------------------
# Celery task registration (call once at startup)
# ---------------------------------------------------------------------------

def register_tasks() -> None:
    """Call during app startup to register the notification Celery task."""
    app = get_celery_app()
    if app is None:
        return

    @app.task(name="notification.send_push", ignore_result=True)
    def _send_push_task(device_tokens: list[str], title: str, body: str, data: dict | None = None) -> None:
        for token in device_tokens:
            _send_fcm(token, title, body, data)

    logger.info("Registered notification.send_push Celery task")
