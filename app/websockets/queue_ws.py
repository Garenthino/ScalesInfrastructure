"""WebSocket endpoint for live queue updates."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.security import decode_token
from app.core.permissions import Role
from app.core.queue_service import get_venue_bus, QueueService
from app.core.db import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter()


async def _extract_ws_token(
    websocket: WebSocket,
) -> dict[str, object] | None:
    """Try to decode a JWT from query param ?token=... or subprotocol."""
    token = websocket.query_params.get("token")
    if not token:
        # Check sec-websocket-protocol header (FastAPI maps it to subprotocols)
        # FastAPI populates websocket.headers; we already checked query_params first.
        pass
    if not token:
        return None
    return decode_token(token)


async def _get_current_user_ws(token: dict[str, object] | None) -> dict[str, object] | None:
    if not token:
        return None
    # Validate singer still exists in DB (same as HTTP auth does)
    sub = token.get("sub")
    if not sub:
        return None
    from sqlalchemy.future import select
    from app.models import Singer

    async with async_session_factory() as session:
        result = await session.execute(
            select(Singer).where(
                Singer.id == sub,
                Singer.deleted_at.is_(None),
                Singer.deactivated_at.is_(None),
            )
        )
        singer = result.scalar_one_or_none()
    if not singer:
        return None
    # Attach resolved role from DB (tamper protection)
    token = dict(token)
    token["role"] = getattr(singer, "role", "singer")
    token["venue_id"] = getattr(singer, "venue_id", token.get("venue_id"))
    return token


def _role_allows_ws(role: str) -> bool:
    return role.lower() in {Role.SINGER.value, Role.KJ.value, Role.ADMIN.value, Role.OWNER.value}


@router.websocket("/ws/venues/{venue_id}/queue")
async def queue_websocket(
    websocket: WebSocket,
    venue_id: str,
):
    # Accept the socket before auth so we can send close codes.
    await websocket.accept()

    raw_token = await _extract_ws_token(websocket)
    user = await _get_current_user_ws(raw_token)

    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication required")
        return

    role = str(user.get("role", "")).lower()
    if not _role_allows_ws(role):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Singer or KJ role required")
        return

    token_venue = user.get("venue_id")
    if token_venue and str(token_venue) != str(venue_id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Venue mismatch")
        return

    singer_id = str(user.get("sub", ""))
    is_kj = role in {Role.KJ.value, Role.ADMIN.value, Role.OWNER.value}

    bus = await get_venue_bus(venue_id)
    queue: asyncio.Queue = await bus.subscribe()

    # Send initial queue snapshot
    try:
        async with async_session_factory() as session:
            svc = QueueService(session)
            items = await svc.get_active_queue(venue_id, mode="round_robin", include_details=True)
            await websocket.send_json(
                {
                    "event_type": "queue_updated",
                    "venue_id": venue_id,
                    "data": {
                        "items": [_queue_snapshot(i, idx + 1) for idx, i in enumerate(items)],
                        "total": len(items),
                    },
                }
            )
            now_playing = next((i for i in items if str(i.status) == "now_playing"), None)
            if now_playing:
                await websocket.send_json(
                    {
                        "event_type": "now_playing_changed",
                        "venue_id": venue_id,
                        "data": _queue_snapshot(now_playing, position=None),
                    }
                )

            # For singer clients: send their position
            if not is_kj:
                for idx, item in enumerate(items, start=1):
                    if str(getattr(item, "singer_id", "")) == singer_id:
                        wait_seconds = _estimate_wait(idx - 1, items)
                        await websocket.send_json(
                            {
                                "event_type": "position_moved",
                                "venue_id": venue_id,
                                "data": {
                                    "request_id": str(item.id),
                                    "position": idx,
                                    "estimated_wait_seconds": wait_seconds,
                                },
                            }
                        )
                        break
    except Exception:
        logger.exception("ws_initial_snapshot_failed")

    try:
        while True:
            # Wait for either an event from the bus or a ping from client.
            # Timeout allows periodic health checks / keep-alive.
            raw = await asyncio.wait_for(queue.get(), timeout=30.0)
            event = json.loads(raw)
            await _maybe_relay(websocket, event, is_kj, singer_id)
    except asyncio.TimeoutError:
        # Send keep-alive ping; if client doesn't pong, next iter will notice disconnect
        try:
            await websocket.send_json({"event_type": "ping", "venue_id": venue_id})
            # Wait again for next event
            raw = await asyncio.wait_for(queue.get(), timeout=30.0)
            event = json.loads(raw)
            await _maybe_relay(websocket, event, is_kj, singer_id)
        except asyncio.TimeoutError:
            await websocket.close(code=status.WS_1001_GOING_AWAY)
        except WebSocketDisconnect:
            pass
    except WebSocketDisconnect:
        pass
    finally:
        await bus.unsubscribe(queue)


async def _maybe_relay(
    websocket: WebSocket,
    event: dict,
    is_kj: bool,
    singer_id: str,
) -> None:
    """Filter event payload depending on client role."""
    event_type = event.get("event_type", "")
    data = event.get("data", {})

    if event_type == "request_approved":
        await websocket.send_json(event)
        return
    if event_type in {"singer_completed", "request_skipped", "request_started", "request_rejected"}:
        await websocket.send_json(event)
        return
    if event_type == "queue_updated":
        # For KJ: send full data. For singer: send abbreviated.
        if is_kj:
            await websocket.send_json(event)
        else:
            await websocket.send_json(
                {
                    "event_type": "queue_updated",
                    "venue_id": event.get("venue_id"),
                    "data": {"action": data.get("action"), "request_id": data.get("request_id")},
                }
            )
        return
    # Catch-all relay anything else
    await websocket.send_json(event)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _queue_snapshot(item, position: int | None = None) -> dict:
    song = getattr(item, "song", None)
    singer = getattr(item, "singer", None)
    return {
        "request_id": str(item.id),
        "position": position,
        "status": str(item.status),
        "song": {"title": getattr(song, "title", None), "artist": getattr(song, "artist", None)} if song else None,
        "singer": {"stage_name": getattr(singer, "stage_name", "Unknown")} if singer else None,
        "requested_at": str(item.requested_at) if item.requested_at else None,
    }


def _estimate_wait(position_ahead: int, items: list) -> int | None:
    """Rough estimate: 4 minutes per song ahead."""
    if position_ahead <= 0:
        return 0
    avg_ms = 240000  # 4 minutes
    ahead = items[:position_ahead]
    total = sum(getattr(i.song, "duration_ms", avg_ms) or avg_ms for i in ahead if getattr(i, "song", None))
    if not total:
        total = position_ahead * avg_ms
    return int(total / 1000)
