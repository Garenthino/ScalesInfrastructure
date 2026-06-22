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
from sqlalchemy import select, func, and_, or_, update

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
    SyncSongPullItem,
    SyncSongsScanPayload,
    SyncSongsAvailabilityBatch,
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


async def _resolve_or_create_song(
    db: AsyncSession,
    venue_id: str,
    song_id: str | None,
    song_title: str | None = None,
    song_artist: str | None = None,
) -> str | None:
    """Resolve a song_id from the KJ client to a server Song UUID.

    The KJ desktop uses local integer IDs; the server uses UUID strings.
    Strategy:
    1. If song_id matches an existing Song UUID, use it.
    2. If not, try to find by title + artist + venue.
    3. If still no match, auto-create a stub Song row so the portal can display it.
    Returns the server Song UUID, or None if no song info was provided.
    """
    if not song_id and not song_title:
        return None

    # 1. Try direct UUID match
    if song_id:
        existing = (
            await db.execute(
                select(Song).where(
                    Song.id == song_id,
                    Song.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return str(existing.id)

    # 2. Try title + artist match (use .first() to avoid MultipleResultsFound
    #    if duplicate songs exist in the catalog)
    if song_title and song_artist:
        existing = (
            await db.execute(
                select(Song).where(
                    Song.venue_id == venue_id,
                    Song.title == song_title,
                    Song.artist == song_artist,
                    Song.deleted_at.is_(None),
                ).limit(1)
            )
        ).scalars().first()
        if existing:
            return str(existing.id)

    # 3. Auto-create stub song
    new_id = str(uuid.uuid4())
    song = Song(
        id=new_id,
        venue_id=venue_id,
        catalog_id=song_id,
        title=song_title or "Unknown",
        artist=song_artist or "Unknown",
        is_available=1,
        is_active=1,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )
    db.add(song)
    return new_id


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
    body: SyncQueuePushPayload,
    venue_id: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Push local queue state to cloud. Server wins on conflicts.

    - Upserts items by request_id
    - Soft-deletes items in deleted_ids
    - Returns any conflicts where server state diverged from client expectation
    """
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    conflicts: list[SyncConflictDetail] = []

    # Ensure all referenced singers exist (auto-create stubs if missing)
    for item in body.items:
        existing_singer = (
            await db.execute(
                select(Singer).where(
                    Singer.id == item.singer_id,
                    Singer.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()
        if not existing_singer:
            db.add(Singer(
                id=item.singer_id,
                venue_id=venue_id,
                stage_name=item.notes or "Unknown",
                created_at=_now_iso(),
                updated_at=_now_iso(),
            ))

    # Process upserts
    for item in body.items:
        # Resolve song_id to a server Song UUID (auto-create stub if needed)
        resolved_song_id = await _resolve_or_create_song(
            db, venue_id, item.song_id, item.song_title, item.song_artist
        )

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

            # Update existing — preserve song_id ONLY for now_playing items
            # (KJ desktop removes the song from rotation after playback starts,
            # but the portal's Now Playing bar still needs to display it).
            # For other items, allow null to clear the song so played songs
            # don't linger next to singers who have no new song queued.
            existing.singer_id = item.singer_id
            if resolved_song_id is not None:
                existing.song_id = resolved_song_id
            elif item.status != "now_playing":
                existing.song_id = None
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
                song_id=resolved_song_id,
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

    # Broadcast the updated queue state via WebSocket so the portal reflects
    # the KJ desktop's changes in real-time.
    try:
        from app.core.queue_service import QueueService
        svc = QueueService(db)
        await svc.broadcast_queue_state(venue_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("broadcast after queue push failed: %s", exc)

    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SyncConflictResponse(
                detail=f"{len(conflicts)} queue conflict(s) detected — server state preserved",
                conflicts=conflicts,
            ).model_dump(),
        )

    return {"synced": len(body.items), "deleted": len(body.deleted_ids), "conflicts": 0}


# ---------------------------------------------------------------------------
# NOW PLAYING
# ---------------------------------------------------------------------------

@router.post("/now_playing")
async def push_now_playing(
    body: dict[str, Any],
    venue_id: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Push currently playing singer to cloud."""
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    singer_id = body.get("singer_id")
    song_id = body.get("song_id")

    # Clear previous now_playing
    await db.execute(
        update(QueueRequest)
        .where(
            QueueRequest.venue_id == venue_id,
            QueueRequest.status == "now_playing",
        )
        .values(status="pending", updated_at=_now_iso())
    )

    if singer_id:
        # Find existing queue item for this singer
        existing = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.singer_id == singer_id,
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.status = "now_playing"
            existing.updated_at = _now_iso()
            if song_id:
                existing.song_id = song_id
        else:
            db.add(QueueRequest(
                id=str(uuid.uuid4()),
                venue_id=venue_id,
                singer_id=singer_id,
                song_id=song_id,
                status="now_playing",
                rotation_position=0,
                notes=body.get("notes", ""),
                requested_at=_now_iso(),
                updated_at=_now_iso(),
            ))

    await db.commit()
    return {"status": "ok", "singer_id": singer_id}


def _queue_item_to_dict(item: QueueRequest) -> dict[str, Any]:
    # Avoid accessing lazy-loaded relationships (item.singer, item.song) in
    # async context — that triggers MissingGreenlet.  Use only scalar columns.
    return {
        "request_id": str(item.id),
        "singer_id": str(item.singer_id),
        "song_id": str(item.song_id) if item.song_id is not None else None,
        "status": str(item.status),
        "position": (item.rotation_position or 0) + 1,
        "notes": str(item.notes) if item.notes is not None else None,
        "requested_at": str(item.requested_at),
        "updated_at": str(item.updated_at) if item.updated_at is not None else None,
        "played_at": str(item.played_at) if item.played_at is not None else None,
        "reject_reason": str(item.reject_reason) if item.reject_reason is not None else None,
    }


def _queue_item_to_sync(item: QueueRequest) -> SyncQueueItem:
    # Avoid accessing lazy-loaded relationships (item.song) in async context.
    # song_title/song_artist will be None on pull; the client can enrich
    # from its own local DB if needed.
    return SyncQueueItem(
        request_id=str(item.id),
        singer_id=str(item.singer_id),
        song_id=str(item.song_id) if item.song_id is not None else None,
        song_title=None,
        song_artist=None,
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
    venue_id: str | None = None,
    since: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> SyncQueuePullOut:
    """Fetch current cloud queue state for venue. Optionally filter by since timestamp."""
    venue_id = venue_id or str(current.venue_id)
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
    body: SyncSingersPushPayload,
    venue_id: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Push singer roster changes. Merge: client wins on editable fields, server wins on loyalty."""
    venue_id = venue_id or str(current.venue_id)
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
    venue_id: str | None = None,
    since: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> SyncSingersPullOut:
    """Fetch singer list with loyalty data for venue."""
    venue_id = venue_id or str(current.venue_id)
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



# ---------------------------------------------------------------------------
# Songs (desktop-scan authoritative, cloud read-only except metadata_lock)
# ---------------------------------------------------------------------------


@router.post("/songs", status_code=200)
async def push_song_scan(
    payload: SyncSongsScanPayload,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """DragonHost2 pushes a full scan of its music library."""
    _require_venue_match(payload.venue_id, current)

    created = updated = marked_unavailable = 0

    for item in payload.new_or_updated:
        result = await db.execute(
            select(Song).where(
                and_(Song.venue_id == payload.venue_id, Song.file_path == item.get("file_path"))
            )
        )
        song = result.scalar_one_or_none()
        if song:
            song.file_hash = item.get("file_hash")
            song.file_size = item.get("file_size")
            song.file_path = item.get("file_path")
            song.is_available = 1
            song.is_active = 1
            song.unavailable_reason = None
            song.last_scanned_at = payload.scan_timestamp
            if not song.metadata_locked:
                if item.get("title"):  song.title = item.get("title")
                if item.get("artist"): song.artist = item.get("artist")
                if item.get("genre"):  song.genre = item.get("genre")
                if item.get("duration") is not None: song.duration_ms = item.get("duration")
                if item.get("year") is not None:     song.year = item.get("year")
                if item.get("category"): song.category = item.get("category")
            updated += 1
        else:
            db.add(Song(
                venue_id=payload.venue_id,
                file_path=item.get("file_path"),
                file_hash=item.get("file_hash"),
                file_size=item.get("file_size"),
                title=item.get("title") or "Unknown",
                artist=item.get("artist") or "Unknown",
                genre=item.get("genre"),
                duration_ms=item.get("duration"),
                year=item.get("year"),
                category=item.get("category"),
                is_available=1,
                is_active=1,
                last_scanned_at=payload.scan_timestamp,
                metadata_locked=0,
            ))
            created += 1

    for path in payload.missing_from_disk:
        result = await db.execute(
            select(Song).where(
                and_(Song.venue_id == payload.venue_id, Song.file_path == path)
            )
        )
        song = result.scalar_one_or_none()
        if song:
            song.is_available = 0
            song.is_active = 0
            song.unavailable_reason = "removed_from_library"
            song.deleted_at = _now_iso()
            song.last_scanned_at = payload.scan_timestamp
            marked_unavailable += 1

    for item in payload.corrupted:
        path = item.get("file_path")
        reason = item.get("reason", "file_corrupted")
        if not path: continue
        result = await db.execute(
            select(Song).where(
                and_(Song.venue_id == payload.venue_id, Song.file_path == path)
            )
        )
        song = result.scalar_one_or_none()
        if song:
            song.is_available = 0
            song.unavailable_reason = reason
            song.last_scanned_at = payload.scan_timestamp
            marked_unavailable += 1

    await db.commit()
    return {
        "venue_id": payload.venue_id,
        "device_id": payload.device_id,
        "scan_timestamp": payload.scan_timestamp,
        "created": created,
        "updated": updated,
        "marked_unavailable": marked_unavailable,
    }


@router.post("/songs/availability", status_code=200)
async def push_song_availability(
    payload: SyncSongsAvailabilityBatch,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """DragonHost2 pushes immediate availability changes."""
    _require_venue_match(payload.venue_id, current)
    changed = 0
    for item in payload.updates:
        song = None
        if item.song_id:
            result = await db.execute(
                select(Song).where(
                    and_(Song.id == item.song_id, Song.venue_id == payload.venue_id)
                )
            )
            song = result.scalar_one_or_none()
        elif item.get("file_path"):
            result = await db.execute(
                select(Song).where(
                    and_(Song.venue_id == payload.venue_id, Song.file_path == item.get("file_path"))
                )
            )
            song = result.scalar_one_or_none()
        if song:
            song.is_available = 1 if item.available else 0
            song.unavailable_reason = item.reason if not item.available else None
            if not item.available:
                song.last_scanned_at = _now_iso()
            changed += 1
    await db.commit()
    return {"venue_id": payload.venue_id, "changed": changed}


@router.get("/songs", response_model=SyncSongsPullOut)
async def pull_song_metadata_corrections(
    venue_id: str,
    since: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """DragonHost2 pulls back admin metadata corrections."""
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)
    query = select(Song).where(
        and_(Song.venue_id == venue_id, Song.metadata_locked == 1)
    )
    if since:
        query = query.where(Song.updated_at > since)
    result = await db.execute(query)
    songs = result.scalars().all()
    items = [
        SyncSongPullItem(
            id=str(s.id),
            title=s.title,
            artist=s.artist,
            genre=s.genre,
            duration=s.duration_ms,
            year=s.year,
            category=s.category,
            available=bool(s.is_available),
            metadata_locked=bool(s.metadata_locked),
            file_path=s.file_path,
            file_hash=s.file_hash,
        )
        for s in songs
    ]
    return SyncSongsPullOut(sync_timestamp=_now_iso(), updated_songs=items)



