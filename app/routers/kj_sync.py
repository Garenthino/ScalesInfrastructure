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
from typing import Any, Literal

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status, Path, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, update

from app.core.auth import kj_auth, KJDeviceUser, require_admin, venue_match_or_admin
from app.core.db import get_db
from app.core.queue_service import QueueService, QueueEventPublisher, TERMINAL_STATUSES
from app.models import QueueRequest, Singer, Song, VenueConfig, SingerRemoval
from app.services.singer_merge import merge_local_singer_into_mobile
from app.schemas import (
    SyncQueuePushPayload,
    SyncQueuePullOut,
    SyncQueueItem,
    SyncHistoryBatchPushPayload,
    SyncHistoryBatchPushOut,
    SyncSingersPushPayload,
    SyncSingersPullOut,
    SyncSingerItem,
    SyncSongsPullOut,
    SyncSongPullItem,
    SyncSongsScanPayload,
    SyncSongsAvailabilityBatch,
    SyncSettingsPushPayload,
    SyncSettingsPullOut,
    SyncSettingItem,
    SyncConflictResponse,
    SyncConflictDetail,
    SingerLinkRequest,
    SingerLinkMergeOut,
    SingerMergeRequest,
)

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _require_venue_match(venue_id: str, current: KJDeviceUser) -> None:
    if str(current.venue_id) != str(venue_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Venue access denied",
        )


def _is_uuid(value: str) -> bool:
    """Return True if the value looks like a UUID."""
    if not value:
        return False
    v = value.strip().lower().replace("-", "")
    if len(v) != 32:
        return False
    try:
        int(v, 16)
        return True
    except ValueError:
        return False


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

async def _removed_singer_ids_for_venue(db: AsyncSession, venue_id: str) -> set[str]:
    """Return singer ids that have an unacknowledged removal for this venue."""
    result = await db.execute(
        select(SingerRemoval.singer_id).where(
            SingerRemoval.venue_id == venue_id,
            SingerRemoval.acknowledged_at.is_(None),
        )
    )
    return {str(r[0]) for r in result.all()}


@router.post("/queue/push")
async def push_queue(
    body: SyncQueuePushPayload,
    background_tasks: BackgroundTasks,
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
            # Auto-create a stub singer for an unknown singer_id. Use the
            # request notes only as a fallback display name; do not store them
            # in singer.notes (that column is for internal venue notes only).
            fallback_stage = (item.notes or "Unknown").strip()
            if not fallback_stage:
                fallback_stage = "Unknown"

            # The venue enforces a unique (venue_id, stage_name) constraint.
            # If the desired stage name is already taken, append a numeric
            # suffix until we find a free name so the KJ desktop's queue push
            # does not fail with a 500.
            base_stage = fallback_stage
            counter = 1
            while (
                await db.execute(
                    select(Singer.id).where(
                        Singer.venue_id == venue_id,
                        Singer.stage_name == fallback_stage,
                    )
                )
            ).scalar_one_or_none():
                counter += 1
                fallback_stage = f"{base_stage} ({counter})"

            db.add(Singer(
                id=item.singer_id,
                venue_id=venue_id,
                stage_name=fallback_stage,
                created_at=_now_iso(),
                updated_at=_now_iso(),
            ))

    # If the singer has been removed from rotation server-side (e.g. by the
    # portal or a prior KJ remove call), do not let an incoming KJ snapshot
    # resurrect their queue rows. Skip the upsert and mark the request as
    # deleted on our side.
    removed_singer_ids = await _removed_singer_ids_for_venue(db, venue_id)

    # Process upserts
    for item in body.items:
        if item.singer_id in removed_singer_ids:
            # Skip re-creating a removed singer's queue item.
            continue
        # Resolve song_id to a server Song UUID (auto-create stub if needed)
        resolved_song_id = await _resolve_or_create_song(
            db, venue_id, item.song_id, item.song_title, item.song_artist
        )
        # Flush so any newly created Song stub is visible to FK constraints
        # before queue item updates/inserts are flushed.
        if resolved_song_id and item.song_id:
            await db.flush()

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
            is_conflict = (
                body.last_modified_at
                and existing.updated_at
                and str(existing.updated_at) > str(body.last_modified_at)
            )
            if is_conflict:
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="queue",
                        entity_id=str(existing.id),
                        server_state=_queue_item_to_dict(existing),
                        client_state=item.model_dump(),
                        resolution="server_wins",
                    )
                )
                # KJ desktop is authoritative while it is online, so still apply
                # the incoming queue state. The conflict record is informational.
            # Always trust the KJ desktop's incoming status unless the server
            # has already moved this item to a terminal state.
            existing.singer_id = item.singer_id
            if resolved_song_id is not None:
                existing.song_id = resolved_song_id
            # Only clear song_id when the KJ desktop explicitly removes a song
            # from a non-terminal request. Do NOT clear it on rejection/skip,
            # because queue_requests.song_id is NOT NULL and the rejection reason
            # refers to the song that was originally requested.
            elif item.status not in ("rejected", "skipped") and str(existing.status) not in TERMINAL_STATUSES:
                existing.song_id = None
            existing.status = item.status
            existing.source = getattr(item, "source", "host")
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
                source=getattr(item, "source", "host"),
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

    # Broadcast off the request path so the portal still updates, but the KJ
    # desktop gets a fast 200 response and does not retry/time out.
    background_tasks.add_task(_broadcast_queue_state, venue_id)

    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SyncConflictResponse(
                detail=f"{len(conflicts)} queue conflict(s) detected — server state preserved",
                conflicts=conflicts,
            ).model_dump(),
        )

    return {"synced": len(body.items), "deleted": len(body.deleted_ids), "conflicts": 0}


async def _broadcast_queue_state(venue_id: str) -> None:
    """Background broadcast of queue state; uses a fresh DB session."""
    from app.core.db import async_session_factory
    import logging as _logging
    async with async_session_factory() as db:
        try:
            svc = QueueService(db)
            await svc.broadcast_queue_state(venue_id)
        except Exception as exc:
            _logging.getLogger(__name__).warning("background broadcast failed: %s", exc)


# ---------------------------------------------------------------------------
# History batch push
# ---------------------------------------------------------------------------

@router.post("/history/batch", response_model=SyncHistoryBatchPushOut)
async def push_history_batch(
    body: SyncHistoryBatchPushPayload,
    venue_id: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
) -> SyncHistoryBatchPushOut:
    """Bulk push completed play-history rows from the KJ desktop.

    Deduplication order:
    1. request_id already exists in this venue -> skip.
    2. (singer_id, song_id, played_at) already exists -> skip.
    3. Otherwise insert a completed QueueRequest row.

    Missing singers and songs are auto-created as stubs so a full history sync
    does not fail on FK constraints.
    """
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    inserted = 0
    skipped = 0
    errors = 0

    if not body.items:
        return SyncHistoryBatchPushOut(inserted=0, skipped=0, errors=0)

    # Pre-fetch existing request_ids and identity tuples in one query.
    incoming_request_ids = [it.request_id for it in body.items]
    incoming_identity_tuples = {
        (it.singer_id, it.song_id, it.played_at) for it in body.items if it.played_at
    }

    existing_by_request_id = {
        str(r[0])
        for r in (
            await db.execute(
                select(QueueRequest.id).where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.id.in_(incoming_request_ids),
                )
            )
        ).all()
    }

    existing_by_identity = {
        (str(r[0]), str(r[1]) if r[1] is not None else None, str(r[2]))
        for r in (
            await db.execute(
                select(QueueRequest.singer_id, QueueRequest.song_id, QueueRequest.played_at).where(
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.status == "completed",
                    QueueRequest.singer_id.in_({it.singer_id for it in body.items if it.singer_id}),
                )
            )
        ).all()
    }

    for item in body.items:
        try:
            if item.request_id in existing_by_request_id:
                skipped += 1
                continue
            identity = (item.singer_id, item.song_id, item.played_at)
            if item.played_at and identity in existing_by_identity:
                skipped += 1
                continue

            # Ensure singer exists
            existing_singer = (
                await db.execute(
                    select(Singer).where(
                        Singer.id == item.singer_id,
                        Singer.venue_id == venue_id,
                    )
                )
            ).scalar_one_or_none()
            if not existing_singer:
                fallback_stage = (item.singer_name or "Unknown").strip() or "Unknown"
                counter = 0
                base_stage = fallback_stage
                while True:
                    dup = (
                        await db.execute(
                            select(Singer.id).where(
                                Singer.venue_id == venue_id,
                                Singer.stage_name == fallback_stage,
                            ).limit(1)
                        )
                    ).scalar_one_or_none()
                    if not dup:
                        break
                    counter += 1
                    fallback_stage = f"{base_stage} ({counter})"
                db.add(
                    Singer(
                        id=item.singer_id,
                        venue_id=venue_id,
                        stage_name=fallback_stage,
                        created_at=_now_iso(),
                        updated_at=_now_iso(),
                    )
                )
                await db.flush()

            resolved_song_id = await _resolve_or_create_song(
                db, venue_id, item.song_id, item.song_title, item.song_artist
            )
            if resolved_song_id and item.song_id:
                await db.flush()

            q = QueueRequest(
                id=item.request_id,
                venue_id=venue_id,
                singer_id=item.singer_id,
                song_id=resolved_song_id,
                status="completed",
                notes=item.notes,
                source=getattr(item, "source", "host"),
                rotation_position=item.position if item.position is not None else 0,
                requested_at=item.requested_at,
                updated_at=_now_iso(),
                played_at=item.played_at,
                reject_reason=item.reject_reason,
            )
            db.add(q)
            inserted += 1
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "history batch item failed: request_id=%s error=%s", item.request_id, exc
            )
            errors += 1

    await db.commit()

    # Broadcast so portal/mobile reflect new history rows
    try:
        svc = QueueService(db)
        await svc.broadcast_queue_state(venue_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("broadcast after history batch failed: %s", exc)

    return SyncHistoryBatchPushOut(inserted=inserted, skipped=skipped, errors=errors)


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
    """Push currently playing track to cloud (singer or DJ/filler)."""
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    singer_id = body.get("singer_id")
    song_id = body.get("song_id")
    song_title = body.get("song_title")
    song_artist = body.get("song_artist")
    singer_name = body.get("singer_name")
    is_dj_track = body.get("is_dj_track", False)

    # Clear previous now_playing — but ONLY for karaoke singer tracks.
    # DJ/filler tracks don't change the queue state; the previous singer
    # keeps their now_playing status in the queue table.
    if not is_dj_track:
        await db.execute(
            update(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status == "now_playing",
            )
            .values(status="pending", updated_at=_now_iso())
        )

    if singer_id and not is_dj_track:
        # Karaoke singer — update their queue item to now_playing
        existing = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.singer_id == singer_id,
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalars().first()

        if existing:
            existing.status = "now_playing"
            existing.updated_at = _now_iso()
            if song_id:
                # Resolve song_id (may be a local integer ID from the client)
                resolved = await _resolve_or_create_song(
                    db, venue_id, song_id, song_title, song_artist
                )
                if resolved:
                    existing.song_id = resolved
                    # Flush so the Song stub (if newly created) is visible
                    # to the FK constraint before the queue update commits.
                    await db.flush()
        else:
            db.add(QueueRequest(
                id=str(uuid.uuid4()),
                venue_id=venue_id,
                singer_id=singer_id,
                status="now_playing",
                source="host",
                rotation_position=0,
                notes=singer_name or body.get("notes") or "",
                requested_at=_now_iso(),
                updated_at=_now_iso(),
            ))

    await db.commit()

    # Broadcast now_playing via WebSocket so the portal updates in real-time.
    # For DJ tracks, send the song info directly without broadcasting the
    # queue state (the queue hasn't changed, and broadcast_queue_state would
    # send an empty now_playing event that overwrites our DJ track event).
    try:
        svc = QueueService(db)
        now_playing_out = {
            "request_id": str(singer_id) if singer_id else "dj_track",
            "singer_name": singer_name or "DJ" if is_dj_track else singer_name,
            "song_title": song_title,
            "song_artist": song_artist,
            "started_at": _now_iso(),
            "elapsed_seconds": 0,
            "is_dj_track": is_dj_track,
        }
        await QueueEventPublisher.publish(venue_id, "now_playing", now_playing_out)
        # Broadcast queue state for karaoke singers (queue changed:
        # previous now_playing cleared, new now_playing set).
        # Skip for DJ tracks — queue is unchanged.
        if not is_dj_track:
            svc = QueueService(db)
            await svc.broadcast_queue_state(venue_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("broadcast after now_playing push failed: %s", exc)

    return {"status": "ok", "singer_id": singer_id, "is_dj_track": is_dj_track}


def _queue_item_to_dict(item: QueueRequest) -> dict[str, Any]:
    # Avoid accessing lazy-loaded relationships (item.singer, item.song) in
    # async context — that triggers MissingGreenlet.  Use only scalar columns.
    # Send empty strings for optional text fields so the KJ desktop client can
    # safely call .strip() without crashing on None.
    return {
        "request_id": str(item.id),
        "singer_id": str(item.singer_id),
        "song_id": str(item.song_id) if item.song_id is not None else None,
        "status": str(item.status),
        "position": (item.rotation_position or 0) + 1,
        "notes": str(item.notes or ""),
        "requested_at": str(item.requested_at),
        "updated_at": str(item.updated_at) if item.updated_at is not None else None,
        "played_at": str(item.played_at) if item.played_at is not None else None,
        "reject_reason": str(item.reject_reason or ""),
    }


def _queue_item_to_sync(item: QueueRequest, song: Song | None = None, singer_name: str | None = None) -> SyncQueueItem:
    # song_title/song_artist are populated from the eagerly-loaded Song row so
    # the KJ desktop can match requests against its local catalog.
    # singer_name is included so the KJ can display the requester without an
    # extra round-trip.
    return SyncQueueItem(
        request_id=str(item.id),
        singer_id=str(item.singer_id),
        singer_name=singer_name or "",
        song_id=str(item.song_id) if item.song_id is not None else None,
        song_title=song.title if song else None,
        song_artist=song.artist if song else None,
        status=str(item.status),  # type: ignore[arg-type]
        position=item.rotation_position,
        notes=str(item.notes or ""),
        requested_at=str(item.requested_at),
        updated_at=str(item.updated_at) if item.updated_at is not None else None,
        played_at=str(item.played_at) if item.played_at is not None else None,
        reject_reason=str(item.reject_reason or ""),
        source=cast(Literal["mobile", "portal", "host"], str(item.source) if item.source is not None else "mobile"),
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
        QueueRequest.deleted_at.is_(None),
        QueueRequest.source.in_(("mobile", "portal")),
    ]
    if since:
        filters.append(or_(
            QueueRequest.updated_at > since,
            QueueRequest.updated_at.is_(None),
        ))

    result = await db.execute(
        select(QueueRequest, Song, Singer.stage_name)
        .outerjoin(Song, QueueRequest.song_id == Song.id)
        .outerjoin(Singer, QueueRequest.singer_id == Singer.id)
        .where(and_(*filters))
        .order_by(QueueRequest.rotation_position)
    )
    items = [_queue_item_to_sync(row[0], row[1], row[2]) for row in result.all()]

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

    # Unacknowledged singer removals for this venue
    removal_result = await db.execute(
        select(SingerRemoval.singer_id).where(
            SingerRemoval.venue_id == venue_id,
            SingerRemoval.acknowledged_at.is_(None),
        )
    )
    removed_singer_ids = [
        str(r[0]) for r in removal_result.all()
        if _is_uuid(str(r[0]))
    ]

    return SyncQueuePullOut(
        items=items,
        deleted_ids=deleted_ids,
        removed_singer_ids=removed_singer_ids,
        server_modified_at=_now_iso(),
    )


@router.post("/queue/{request_id}/ack", status_code=status.HTTP_204_NO_CONTENT)
async def ack_queue_request(
    background_tasks: BackgroundTasks,
    request_id: str,
    venue_id: str | None = Query(None),
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """KJ desktop acknowledges/dismisses a queue request so it is not re-sent."""
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    row = (
        await db.execute(
            select(QueueRequest).where(
                QueueRequest.id == request_id,
                QueueRequest.venue_id == venue_id,
            )
        )
    ).scalar_one_or_none()
    if row:
        row.deleted_at = _now_iso()
        row.updated_at = _now_iso()
        await db.commit()
        background_tasks.add_task(_broadcast_queue_state, venue_id)
    return None


# ---------------------------------------------------------------------------
# Singer removals (venue portal removes singer from rotation)
# ---------------------------------------------------------------------------

def _uuid_singer_id(singer_id: str = Path(..., title="Cloud singer UUID")) -> str:
    if not _is_uuid(singer_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "singer_id must be a cloud singer UUID. "
                "The KJ desktop appears to be sending a local integer id; "
                "please restart/rebuild the desktop app so it can mint cloud UUIDs for local singers."
            ),
        )
    return singer_id


@router.post("/queue/singers/{singer_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
async def remove_singer_from_rotation(
    background_tasks: BackgroundTasks,
    venue_id: str | None = None,
    singer_id: str = Depends(_uuid_singer_id),
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """KJ desktop removes a singer from the current rotation.

    Cancels all active queue requests for the singer and records a removal
    so the portal and other clients can pull it and remove the singer.

    The KJ desktop must send the canonical cloud singer UUID, not the local
    integer id. Rejecting local ids prevents the server from minting stub
    singers keyed by small integers that the portal cannot target.
    """
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    svc = QueueService(db)
    await svc.remove_singer_from_rotation(
        venue_id, singer_id, removed_by_device_id=str(current.id), broadcast=False
    )
    background_tasks.add_task(_broadcast_queue_state, venue_id)
    return None


@router.post("/queue/removals/ack", response_model=dict)
async def ack_singer_removals(
    body: dict,
    venue_id: str | None = Query(None),
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """KJ desktop acknowledges singer removals so they are not re-sent."""
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    singer_ids = [s for s in body.get("singer_ids", []) if _is_uuid(str(s))]
    if not singer_ids:
        return {"acknowledged": []}

    result = await db.execute(
        update(SingerRemoval)
        .where(
            SingerRemoval.venue_id == venue_id,
            SingerRemoval.singer_id.in_(singer_ids),
            SingerRemoval.acknowledged_at.is_(None),
        )
        .values(acknowledged_at=_now_iso())
    )
    await db.commit()
    print(f"[kj_sync] acked {result.rowcount} singer removals for ids={singer_ids}")
    return {"acknowledged": singer_ids, "rowcount": result.rowcount}


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

            # Client wins on editable fields; preserve server loyalty/tier.
            # KJ desktop "notes" stay in QueueRequest.notes and are never
            # written to Singer.notes, which is reserved for internal venue notes.
            existing.stage_name = item.stage_name
            existing.first_name = item.first_name
            existing.last_name = item.last_name
            existing.real_name = item.real_name
            existing.pronouns = item.pronouns
            existing.email = item.email
            existing.phone = item.phone
            existing.last_seen = item.last_seen or existing.last_seen
            existing.deactivated_at = item.deactivated_at
            existing.updated_at = _now_iso()
        else:
            singer = Singer(
                id=item.id,
                venue_id=venue_id,
                stage_name=item.stage_name,
                real_name=item.real_name,
                first_name=item.first_name,
                last_name=item.last_name,
                pronouns=item.pronouns,
                email=item.email,
                phone=item.phone,
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
    # Send empty strings instead of null for optional text fields. The KJ
    # desktop client calls .strip() on several of these and crashes on None.
    account_id_str = str(singer.account_id) if singer.account_id is not None else ""
    return {
        "id": str(singer.id),
        "singer_id": str(singer.id),
        "account_id": account_id_str,
        "stage_name": str(singer.stage_name or ""),
        "first_name": str(singer.first_name or ""),
        "last_name": str(singer.last_name or ""),
        "real_name": str(singer.real_name or ""),
        "pronouns": str(singer.pronouns or ""),
        "email": str(singer.email or ""),
        "phone": str(singer.phone or ""),
        "notes": str(singer.notes or ""),
        "total_points": singer.total_points or 0,
        "loyalty_tier_id": str(singer.loyalty_tier_id) if singer.loyalty_tier_id is not None else None,
        "last_seen": str(singer.last_seen) if singer.last_seen is not None else None,
        "deactivated_at": str(singer.deactivated_at) if singer.deactivated_at is not None else None,
        "created_at": str(singer.created_at),
        "updated_at": str(singer.updated_at) if singer.updated_at is not None else None,
    }


def _singer_item_to_sync(singer: Singer) -> SyncSingerItem:
    # Send empty strings instead of null for optional text fields so the KJ
    # desktop client's .strip() calls do not crash on None.
    account_id_str = str(singer.account_id) if singer.account_id is not None else ""
    return SyncSingerItem(
        id=str(singer.id),
        singer_id=str(singer.id),
        account_id=account_id_str,
        stage_name=str(singer.stage_name or ""),
        first_name=str(singer.first_name or ""),
        last_name=str(singer.last_name or ""),
        real_name=str(singer.real_name or ""),
        pronouns=str(singer.pronouns or ""),
        email=str(singer.email or ""),
        phone=str(singer.phone or ""),
        notes=str(singer.notes or ""),
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

    # Return both active and recently soft-deleted singers. The desktop needs to
    # see merged/deleted rows so it can clean up its local duplicate instead of
    # recreating it on the next pull.
    filters = [Singer.venue_id == venue_id]
    if since:
        filters.append(or_(
            Singer.updated_at > since,
            Singer.updated_at.is_(None),
        ))

    result = await db.execute(
        select(Singer).where(and_(*filters)).order_by(Singer.stage_name)
    )
    items = []
    for row in result.scalars().all():
        item = _singer_item_to_sync(row)
        if row.deleted_at is not None:
            item = item.model_copy(update={"deleted_at": str(row.deleted_at)})
        items.append(item)

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


@router.post("/singers/{local_singer_id}/link", response_model=SingerLinkMergeOut)
async def link_singer_to_mobile(
    local_singer_id: str,
    body: SingerLinkRequest,
    venue_id: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """Merge a non-mobile (local) singer into a mobile-linked target singer.

    The local singer keeps its stage history, queue requests, payments,
    favorites, and achievements. All those records are reassigned to the
    target singer row, and the local singer is soft-deleted.
    """
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    result = await merge_local_singer_into_mobile(
        db=db,
        venue_id=venue_id,
        local_singer_id=local_singer_id,
        target_singer_id=body.target_singer_id,
        target_account_email=body.target_account_email,
        merged_by_account_id=None,
        merged_by_kj_device_id=current.id,
    )
    await db.commit()
    # Refresh target after commit so the broadcast has updated totals.
    target_result = await db.execute(select(Singer).where(Singer.id == result.target_singer_id))
    target = target_result.scalar_one_or_none()
    if target:
        from app.core.queue_service import SingerEventPublisher
        await SingerEventPublisher.publish_singer_changed(
            venue_id, target, event_type="singer_changed"
        )
    return result


@router.post("/singers/merge", response_model=SingerLinkMergeOut)
async def merge_local_singer_by_details(
    body: SingerMergeRequest,
    venue_id: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """Merge a local-only singer into a mobile-linked target using details.

    If the local row has not been pushed to the cloud yet (no cloud_singer_id),
    the KJ desktop can call this endpoint with the local display name/email and
    the target singer id. The server finds or creates a stub source singer,
    then performs the merge and soft-deletes the source.
    """
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    result = await merge_local_singer_into_mobile(
        db=db,
        venue_id=venue_id,
        local_singer_id=body.local_singer_id,
        local_name=body.local_name,
        local_first_name=body.local_first_name,
        local_last_name=body.local_last_name,
        local_email=body.local_email,
        local_phone=body.local_phone,
        target_singer_id=body.target_singer_id,
        target_account_email=body.target_account_email,
        merged_by_account_id=None,
        merged_by_kj_device_id=current.id,
        create_stub_if_missing=True,
    )
    await db.commit()
    target_result = await db.execute(select(Singer).where(Singer.id == result.target_singer_id))
    target = target_result.scalar_one_or_none()
    if target:
        from app.core.queue_service import SingerEventPublisher
        await SingerEventPublisher.publish_singer_changed(
            venue_id, target, event_type="singer_changed"
        )
    return result


# ---------------------------------------------------------------------------
# Songs (desktop-scan authoritative, cloud read-only except metadata_lock)
# ---------------------------------------------------------------------------


@router.post("/songs", status_code=200)
async def push_song_scan(  # type: ignore[no-redef]
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
        elif item.file_path:
            result = await db.execute(
                select(Song).where(
                    and_(Song.venue_id == payload.venue_id, Song.file_path == item.file_path)
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


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@router.get("/settings/pull", response_model=SyncSettingsPullOut)
async def pull_settings(
    venue_id: str | None = None,
    since: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """Fetch venue config settings for KJ desktop."""
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    query = select(VenueConfig).where(VenueConfig.venue_id == venue_id)
    if since:
        query = query.where(
            or_(
                VenueConfig.updated_at > since,
                VenueConfig.updated_at.is_(None),
            )
        )
    result = await db.execute(query)
    rows = result.scalars().all()
    items = [
        SyncSettingItem(
            key=str(r.config_key),
            value=str(r.config_value) if r.config_value is not None else None,
            updated_at=str(r.updated_at) if r.updated_at is not None else _now_iso(),
        )
        for r in rows
    ]
    return SyncSettingsPullOut(items=items, server_modified_at=_now_iso())


@router.post("/settings/push", status_code=200)
async def push_settings(
    body: SyncSettingsPushPayload,
    venue_id: str | None = None,
    current: KJDeviceUser = Depends(kj_auth),
    db: AsyncSession = Depends(get_db),
):
    """Push venue config settings from KJ desktop with last-write-wins conflict resolution."""
    venue_id = venue_id or str(current.venue_id)
    _require_venue_match(venue_id, current)

    conflicts: list[SyncConflictDetail] = []
    synced = 0

    for item in body.items:
        existing = (
            await db.execute(
                select(VenueConfig).where(
                    VenueConfig.venue_id == venue_id,
                    VenueConfig.config_key == item.key,
                )
            )
        ).scalar_one_or_none()

        if existing:
            if (
                body.last_modified_at
                and existing.updated_at
                and str(existing.updated_at) > str(body.last_modified_at)
            ):
                conflicts.append(
                    SyncConflictDetail(
                        entity_type="settings",
                        entity_id=item.key,
                        server_state={
                            "key": str(existing.config_key),
                            "value": str(existing.config_value) if existing.config_value is not None else None,
                            "updated_at": str(existing.updated_at),
                        },
                        client_state={"key": item.key, "value": item.value, "updated_at": item.updated_at},
                        resolution="server_wins",
                    )
                )
                continue
            existing.config_value = item.value
            existing.updated_at = item.updated_at
        else:
            db.add(
                VenueConfig(
                    id=str(uuid.uuid4()),
                    venue_id=venue_id,
                    config_key=item.key,
                    config_value=item.value,
                    updated_at=item.updated_at,
                )
            )
        synced += 1

    await db.commit()

    if conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=SyncConflictResponse(
                detail=f"{len(conflicts)} setting conflict(s) detected — server state preserved",
                conflicts=conflicts,
            ).model_dump(),
        )

    return {"synced": synced, "conflicts": 0}



