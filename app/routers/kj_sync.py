"""KJ Desktop App sync router — push/pull endpoints for queue, singers, songs, settings.

Conflict resolution:
- queue: server wins (KJ live state is authoritative while active)
- singers: server wins for fields the cloud manages (loyalty), client wins for
  editable fields (stage_name, notes), merge on checkins
- songs: server wins on catalog changes; client can update availability only
- settings: last-write-wins (LWW) on updated_at

All endpoints require kj_auth() dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.core.auth import kj_auth, KJDeviceUser
from app.core.db import get_db
from app.models import QueueRequest, Singer, Song, VenueConfig
from app.schemas import (
    SyncQueuePushPayload,
    SyncQueuePullOut,
    SyncQueueItem,
    SyncSingersPushPayload,
    SyncSingersPullOut,
    SyncSingerItem,
    SyncSongsPushPayload,
    SyncSongsPullOut,
    SyncSongItem,
    SyncSettingsPushPayload,
    SyncSettingsPullOut,
    SyncSettingItem,
    SyncConflictResponse,
    SyncConflictDetail,
)

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_venue_match(venue_id: str, current: KJDeviceUser) -> None:
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )


async def _get_venue_config_dict(db: AsyncSession, venue_id: str) -> dict[str, SyncSettingItem]:
    """Return all venue_configs as a dict keyed by config_key."""
    result = await db.execute(
        select(VenueConfig).where(
            VenueConfig.venue_id == venue_id,
        )
    )
    rows = result.scalars().all()
    out: dict[str, SyncSettingItem] = {}
    for r in rows:
        out[str(r.config_key)] = SyncSettingItem(
            key=str(r.config_key),
            value=str(r.config_value) if r.config_value is not None else None,
            updated_at=str(r.updated_at) if r.updated_at is not None else _now_iso(),
        )
    return out


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

@router.post("/queue/push")
async def push_queue(
    venue_id: str,
    body: SyncQueuePushPayload,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Push local queue state to cloud. Server wins on conflicts.

    - Upserts items by request_id
    - Soft-deletes items in deleted_ids
    - Returns any conflicts where server state diverged from client expectation
    """
    _require_venue_match(venue_id, current)

    conflicts: list[SyncConflictDetail] = []

    # Process upserts
    for item in body.items:
        # Check if server has newer state
        existing = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.id == item.request_id,
                    QueueRequest.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            # Conflict detection: if server updated_at > client last_modified_at
            if body.last_modified_at and existing.updated_at and str(existing.updated_at) > str(body.last_modified_at):
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="queue",
                        entity_id=item.request_id,
                        server_state=_queue_item_to_dict(existing),
                        client_state=item.model_dump(),
                        resolution="server_wins",
                    )
                )
                # server wins: skip this item, keep server state
                continue

            # Update existing
            existing.singer_id = item.singer_id
            existing.song_id = item.song_id
            existing.status = item.status
            existing.rotation_position = item.position
            existing.notes = item.notes
            existing.requested_at = item.requested_at
            existing.updated_at = _now_iso()
            if item.played_at:
                existing.played_at = item.played_at
            if item.reject_reason:
                existing.reject_reason = item.reject_reason
        else:
            # Insert new
            q = QueueRequest(
                id=item.request_id,
                venue_id=venue_id,
                singer_id=item.singer_id,
                song_id=item.song_id,
                status=item.status,
                notes=item.notes,
                rotation_position=item.position,
                requested_at=item.requested_at,
                updated_at=_now_iso(),
                played_at=item.played_at,
                reject_reason=item.reject_reason,
            )
            db.add(q)

    # Process soft deletes
    for del_id in body.deleted_ids:
        row = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.id == del_id,
                    QueueRequest.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()
        if row:
            # server wins: only delete if client was not stale
            if body.last_modified_at and row.updated_at and str(row.updated_at) > str(body.last_modified_at):
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="queue",
                        entity_id=del_id,
                        server_state=_queue_item_to_dict(row),
                        client_state={"deleted": True},
                        resolution="server_wins",
                    )
                )
                continue
            row.deleted_at = _now_iso()
            row.updated_at = _now_iso()

    await db.commit()

    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SyncConflictResponse(
                detail=f"{len(conflicts)} queue conflict(s) detected — server state preserved",
                conflicts=conflicts,
            ).model_dump(),
        )

    return {"synced": len(body.items), "deleted": len(body.deleted_ids), "conflicts": 0}


def _queue_item_to_dict(item: QueueRequest) -> dict[str, Any]:
    return {
        "request_id": str(item.id),
        "singer_id": str(item.singer_id),
        "song_id": str(item.song_id),
        "status": str(item.status),
        "position": item.rotation_position,
        "notes": str(item.notes) if item.notes is not None else None,
        "requested_at": str(item.requested_at),
        "updated_at": str(item.updated_at) if item.updated_at is not None else None,
        "played_at": str(item.played_at) if item.played_at is not None else None,
        "reject_reason": str(item.reject_reason) if item.reject_reason is not None else None,
    }


def _queue_item_to_sync(item: QueueRequest) -> SyncQueueItem:
    return SyncQueueItem(
        request_id=str(item.id),
        singer_id=str(item.singer_id),
        song_id=str(item.song_id),
        status=str(item.status),  # type: ignore[arg-type]
        position=item.rotation_position,
        notes=str(item.notes) if item.notes is not None else None,
        requested_at=str(item.requested_at),
        updated_at=str(item.updated_at) if item.updated_at is not None else None,
        played_at=str(item.played_at) if item.played_at is not None else None,
        reject_reason=str(item.reject_reason) if item.reject_reason is not None else None,
    )


@router.get("/queue/pull", response_model=SyncQueuePullOut)
async def pull_queue(
    venue_id: str,
    since: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> SyncQueuePullOut:
    """Fetch current cloud queue state for venue. Optionally filter by since timestamp."""
    _require_venue_match(venue_id, current)

    filters = [
        QueueRequest.venue_id == venue_id,
    ]
    if since:
        filters.append(or_(
            QueueRequest.updated_at > since,
            QueueRequest.updated_at.is_(None),
        ))

    result = await db.execute(
        select(QueueRequest).where(and_(*filters)).order_by(QueueRequest.rotation_position)
    )
    items = [_queue_item_to_sync(row) for row in result.scalars().all()]

    # Also return soft-deleted IDs if since is provided
    deleted_ids: list[str] = []
    if since:
        del_result = await db.execute(
            select(QueueRequest.id).where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.deleted_at.isnot(None),
                QueueRequest.updated_at > since,
            )
        )
        deleted_ids = [str(r[0]) for r in del_result.all()]

    return SyncQueuePullOut(
        items=items,
        deleted_ids=deleted_ids,
        server_modified_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Singers
# ---------------------------------------------------------------------------

@router.post("/singers/push")
async def push_singers(
    venue_id: str,
    body: SyncSingersPushPayload,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Push singer roster changes. Merge: client wins on editable fields, server wins on loyalty."""
    _require_venue_match(venue_id, current)

    conflicts: list[SyncConflictDetail] = []

    for item in body.items:
        existing = (
            await db.execute(
                select(Singer).where(
                    Singer.id == item.id,
                    Singer.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            if body.last_modified_at and existing.updated_at and str(existing.updated_at) > str(body.last_modified_at):
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="singers",
                        entity_id=item.id,
                        server_state=_singer_item_to_dict(existing),
                        client_state=item.model_dump(),
                        resolution="server_wins",
                    )
                )
                continue

            # Client wins on editable fields; preserve server loyalty/tier
            existing.stage_name = item.stage_name
            existing.real_name = item.real_name
            existing.pronouns = item.pronouns
            existing.email = item.email
            existing.phone = item.phone
            existing.notes = item.notes
            existing.last_seen = item.last_seen or existing.last_seen
            existing.deactivated_at = item.deactivated_at
            existing.updated_at = _now_iso()
        else:
            singer = Singer(
                id=item.id,
                venue_id=venue_id,
                stage_name=item.stage_name,
                real_name=item.real_name,
                pronouns=item.pronouns,
                email=item.email,
                phone=item.phone,
                notes=item.notes,
                total_points=item.total_points,
                loyalty_tier_id=item.loyalty_tier_id,
                last_seen=item.last_seen,
                deactivated_at=item.deactivated_at,
                created_at=item.created_at,
                updated_at=_now_iso(),
            )
            db.add(singer)

    # Soft deletes
    for del_id in body.deleted_ids:
        row = (
            await db.execute(
                select(Singer).where(
                    Singer.id == del_id,
                    Singer.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()
        if row:
            if body.last_modified_at and row.updated_at and str(row.updated_at) > str(body.last_modified_at):
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="singers",
                        entity_id=del_id,
                        server_state=_singer_item_to_dict(row),
                        client_state={"deleted": True},
                        resolution="server_wins",
                    )
                )
                continue
            row.deleted_at = _now_iso()
            row.updated_at = _now_iso()

    await db.commit()

    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SyncConflictResponse(
                detail=f"{len(conflicts)} singer conflict(s) detected — server state preserved",
                conflicts=conflicts,
            ).model_dump(),
        )

    return {"synced": len(body.items), "deleted": len(body.deleted_ids), "conflicts": 0}


def _singer_item_to_dict(singer: Singer) -> dict[str, Any]:
    return {
        "id": str(singer.id),
        "stage_name": str(singer.stage_name),
        "real_name": str(singer.real_name) if singer.real_name is not None else None,
        "pronouns": str(singer.pronouns) if singer.pronouns is not None else None,
        "email": str(singer.email) if singer.email is not None else None,
        "phone": str(singer.phone) if singer.phone is not None else None,
        "notes": str(singer.notes) if singer.notes is not None else None,
        "total_points": singer.total_points or 0,
        "loyalty_tier_id": str(singer.loyalty_tier_id) if singer.loyalty_tier_id is not None else None,
        "last_seen": str(singer.last_seen) if singer.last_seen is not None else None,
        "deactivated_at": str(singer.deactivated_at) if singer.deactivated_at is not None else None,
        "created_at": str(singer.created_at),
        "updated_at": str(singer.updated_at) if singer.updated_at is not None else None,
    }


def _singer_item_to_sync(singer: Singer) -> SyncSingerItem:
    return SyncSingerItem(
        id=str(singer.id),
        stage_name=str(singer.stage_name),
        real_name=str(singer.real_name) if singer.real_name is not None else None,
        pronouns=str(singer.pronouns) if singer.pronouns is not None else None,
        email=str(singer.email) if singer.email is not None else None,
        phone=str(singer.phone) if singer.phone is not None else None,
        notes=str(singer.notes) if singer.notes is not None else None,
        total_points=singer.total_points or 0,
        loyalty_tier_id=str(singer.loyalty_tier_id) if singer.loyalty_tier_id is not None else None,
        last_seen=str(singer.last_seen) if singer.last_seen is not None else None,
        deactivated_at=str(singer.deactivated_at) if singer.deactivated_at is not None else None,
        created_at=str(singer.created_at),
        updated_at=str(singer.updated_at) if singer.updated_at is not None else None,
    )


@router.get("/singers/pull", response_model=SyncSingersPullOut)
async def pull_singers(
    venue_id: str,
    since: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> SyncSingersPullOut:
    """Fetch singer list with loyalty data for venue."""
    _require_venue_match(venue_id, current)

    filters = [
        Singer.venue_id == venue_id,
        Singer.deleted_at.is_(None),
    ]
    if since:
        filters.append(or_(
            Singer.updated_at > since,
            Singer.updated_at.is_(None),
        ))

    result = await db.execute(
        select(Singer).where(and_(*filters)).order_by(Singer.stage_name)
    )
    items = [_singer_item_to_sync(row) for row in result.scalars().all()]

    deleted_ids: list[str] = []
    if since:
        del_result = await db.execute(
            select(Singer.id).where(
                Singer.venue_id == venue_id,
                Singer.deleted_at.isnot(None),
                Singer.updated_at > since,
            )
        )
        deleted_ids = [str(r[0]) for r in del_result.all()]

    return SyncSingersPullOut(
        items=items,
        deleted_ids=deleted_ids,
        server_modified_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Songs
# ---------------------------------------------------------------------------

@router.post("/songs/push")
async def push_songs(
    venue_id: str,
    body: SyncSongsPushPayload,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Push song plays/history and availability changes. Server wins on catalog fields."""
    _require_venue_match(venue_id, current)

    conflicts: list[SyncConflictDetail] = []

    for item in body.items:
        existing = (
            await db.execute(
                select(Song).where(
                    Song.id == item.id,
                    Song.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            if body.last_modified_at and existing.updated_at and str(existing.updated_at) > str(body.last_modified_at):
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="songs",
                        entity_id=item.id,
                        server_state=_song_item_to_dict(existing),
                        client_state=item.model_dump(),
                        resolution="server_wins",
                    )
                )
                continue

            # Client may only update availability; server wins on catalog fields
            existing.is_available = 1 if item.is_available else 0
            existing.updated_at = _now_iso()
        else:
            # New song from local catalog import
            song = Song(
                id=item.id,
                venue_id=venue_id,
                catalog_id=item.catalog_id,
                title=item.title,
                artist=item.artist,
                album=item.album,
                genre=item.genre,
                category=item.category,
                language=item.language,
                duration_ms=item.duration_ms,
                year=item.year,
                is_available=1 if item.is_available else 0,
                is_active=1,
                created_at=item.created_at,
                updated_at=_now_iso(),
            )
            db.add(song)

    # Process plays (append-only, no conflicts)
    for play in body.plays:
        # plays are stored as analytics_events for now
        from app.models import AnalyticsEvent
        evt = AnalyticsEvent(
            id=str(uuid.uuid4()),
            venue_id=venue_id,
            event_type="song_played",
            singer_id=play.get("singer_id"),
            song_id=play.get("song_id"),
            session_id=play.get("session_id"),
            payload_json=str(play),
            created_at=play.get("played_at", _now_iso()),
        )
        db.add(evt)

    # Soft deletes
    for del_id in body.deleted_ids:
        row = (
            await db.execute(
                select(Song).where(
                    Song.id == del_id,
                    Song.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()
        if row:
            if body.last_modified_at and row.updated_at and str(row.updated_at) > str(body.last_modified_at):
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="songs",
                        entity_id=del_id,
                        server_state=_song_item_to_dict(row),
                        client_state={"deleted": True},
                        resolution="server_wins",
                    )
                )
                continue
            row.is_active = 0
            row.deleted_at = _now_iso()
            row.updated_at = _now_iso()

    await db.commit()

    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SyncConflictResponse(
                detail=f"{len(conflicts)} song conflict(s) detected — server state preserved",
                conflicts=conflicts,
            ).model_dump(),
        )

    return {"synced": len(body.items), "plays_recorded": len(body.plays), "deleted": len(body.deleted_ids), "conflicts": 0}


def _song_item_to_dict(song: Song) -> dict[str, Any]:
    return {
        "id": str(song.id),
        "catalog_id": str(song.catalog_id) if song.catalog_id is not None else None,
        "title": str(song.title),
        "artist": str(song.artist),
        "album": str(song.album) if song.album is not None else None,
        "genre": str(song.genre) if song.genre is not None else None,
        "category": str(song.category) if song.category is not None else None,
        "language": str(song.language) if song.language is not None else None,
        "duration_ms": song.duration_ms,
        "year": song.year,
        "is_available": bool(song.is_available),
        "is_active": bool(song.is_active),
        "created_at": str(song.created_at),
        "updated_at": str(song.updated_at) if song.updated_at is not None else None,
    }


def _song_item_to_sync(song: Song) -> SyncSongItem:
    return SyncSongItem(
        id=str(song.id),
        catalog_id=str(song.catalog_id) if song.catalog_id is not None else None,
        title=str(song.title),
        artist=str(song.artist),
        album=str(song.album) if song.album is not None else None,
        genre=str(song.genre) if song.genre is not None else None,
        category=str(song.category) if song.category is not None else None,
        language=str(song.language) if song.language is not None else None,
        duration_ms=song.duration_ms,
        year=song.year,
        is_available=bool(song.is_available),
        is_active=bool(song.is_active),
        created_at=str(song.created_at),
        updated_at=str(song.updated_at) if song.updated_at is not None else None,
    )


@router.get("/songs/pull", response_model=SyncSongsPullOut)
async def pull_songs(
    venue_id: str,
    since: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> SyncSongsPullOut:
    """Fetch venue song catalog."""
    _require_venue_match(venue_id, current)

    filters = [
        Song.venue_id == venue_id,
        Song.deleted_at.is_(None),
    ]
    if since:
        filters.append(or_(
            Song.updated_at > since,
            Song.updated_at.is_(None),
        ))

    result = await db.execute(
        select(Song).where(and_(*filters)).order_by(Song.title)
    )
    items = [_song_item_to_sync(row) for row in result.scalars().all()]

    deleted_ids: list[str] = []
    if since:
        del_result = await db.execute(
            select(Song.id).where(
                Song.venue_id == venue_id,
                Song.deleted_at.isnot(None),
                Song.updated_at > since,
            )
        )
        deleted_ids = [str(r[0]) for r in del_result.all()]

    return SyncSongsPullOut(
        items=items,
        deleted_ids=deleted_ids,
        server_modified_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.post("/settings/push")
async def push_settings(
    venue_id: str,
    body: SyncSettingsPushPayload,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Push KJ app settings to cloud. Last-write-wins (LWW) on updated_at."""
    _require_venue_match(venue_id, current)

    conflicts: list[SyncConflictDetail] = []
    now = _now_iso()

    # Get current server settings
    server_settings = await _get_venue_config_dict(db, venue_id)

    for item in body.items:
        server_item = server_settings.get(item.key)

        if server_item:
            # LWW: compare updated_at timestamps
            if item.updated_at and server_item.updated_at and str(server_item.updated_at) > str(item.updated_at):
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="settings",
                        entity_id=item.key,
                        server_state=server_item.model_dump(),
                        client_state=item.model_dump(),
                        resolution="server_wins",
                    )
                )
                continue

        # Upsert via VenueConfig
        existing = (
            await db.execute(
                select(VenueConfig).where(
                    VenueConfig.venue_id == venue_id,
                    VenueConfig.config_key == item.key,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.config_value = item.value
            existing.updated_at = now
        else:
            cfg = VenueConfig(
                id=str(uuid.uuid4()),
                venue_id=venue_id,
                config_key=item.key,
                config_value=item.value,
                updated_at=now,
            )
            db.add(cfg)

    await db.commit()

    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SyncConflictResponse(
                detail=f"{len(conflicts)} setting conflict(s) detected — server wins on older timestamps",
                conflicts=conflicts,
            ).model_dump(),
        )

    return {"synced": len(body.items), "conflicts": 0}


@router.get("/settings/pull", response_model=SyncSettingsPullOut)
async def pull_settings(
    venue_id: str,
    since: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> SyncSettingsPullOut:
    """Fetch venue defaults (venue_configs)."""
    _require_venue_match(venue_id, current)

    filters = [
        VenueConfig.venue_id == venue_id,
    ]
    if since:
        filters.append(or_(
            VenueConfig.updated_at > since,
            VenueConfig.updated_at.is_(None),
        ))

    result = await db.execute(
        select(VenueConfig).where(and_(*filters))
    )
    items = [
        SyncSettingItem(
            key=str(r.config_key),
            value=str(r.config_value) if r.config_value is not None else None,
            updated_at=str(r.updated_at) if r.updated_at is not None else _now_iso(),
        )
        for r in result.scalars().all()
    ]

    return SyncSettingsPullOut(
        items=items,
        server_modified_at=_now_iso(),
    )
