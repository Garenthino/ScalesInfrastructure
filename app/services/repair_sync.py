"""Full repair sync service.

Aggregates singers, queue, settings, and now-playing into one snapshot, detects
conflicts against the cloud database, supports client-wins and prompt modes, and
preserves data integrity for server-managed fields.

The implementation reuses the conflict-detection patterns from app.routers.kj_sync
but collects conflicts instead of aborting on the first one.
"""

from __future__ import annotations

import asyncio
import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.queue_service import QueueService, QueueEventPublisher
from app.models import QueueRequest, Singer, Song, VenueConfig
from app.schemas import (
    NowPlayingSnapshot,
    RepairSyncConflict,
    RepairSyncJobSummary,
    RepairSyncMode,
    RepairSyncProgress,
    RepairSyncSingerSnapshot,
    RepairSyncQueueSnapshot,
    RepairSyncSettingsSnapshot,
    RepairSyncSnapshot,
    RepairSyncStatus,
    RepairSyncSummary,
    SyncQueueItem,
    SyncSingerItem,
    SyncSettingItem,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# In-memory job store (asyncio-safe). Replace with Redis for multi-process deploys.
# ---------------------------------------------------------------------------

@dataclass
class _RepairSyncJob:
    sync_id: str
    venue_id: str
    mode: RepairSyncMode
    snapshot: RepairSyncSnapshot
    status: RepairSyncStatus = RepairSyncStatus.accepted
    progress: RepairSyncProgress | None = None
    summary: RepairSyncJobSummary | None = None
    conflicts: list[RepairSyncConflict] = field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    idempotency_key: str | None = None
    cancelled: bool = False


_jobs: dict[str, _RepairSyncJob] = {}
_idempotency_map: dict[str, str] = {}
_lock = asyncio.Lock()

IDEMPOTENCY_TTL_SECONDS = 24 * 3600


# ---------------------------------------------------------------------------
# Public job store API
# ---------------------------------------------------------------------------

async def _upsert_job(job: _RepairSyncJob) -> None:
    async with _lock:
        _jobs[job.sync_id] = job
        if job.idempotency_key:
            _idempotency_map[job.idempotency_key] = job.sync_id


async def _get_job(sync_id: str) -> _RepairSyncJob | None:
    async with _lock:
        return _jobs.get(sync_id)


async def _find_by_idempotency(idempotency_key: str) -> _RepairSyncJob | None:
    async with _lock:
        existing_id = _idempotency_map.get(idempotency_key)
        if existing_id:
            return _jobs.get(existing_id)
        return None


async def _update_job(job: _RepairSyncJob) -> None:
    async with _lock:
        _jobs[job.sync_id] = job


async def _delete_job(job: _RepairSyncJob) -> None:
    async with _lock:
        _jobs.pop(job.sync_id, None)
        if job.idempotency_key and _idempotency_map.get(job.idempotency_key) == job.sync_id:
            _idempotency_map.pop(job.idempotency_key, None)


# ---------------------------------------------------------------------------
# Helpers: server-side serialization
# ---------------------------------------------------------------------------

def _queue_item_to_dict(item: QueueRequest) -> dict[str, Any]:
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


def _singer_item_to_dict(singer: Singer) -> dict[str, Any]:
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


def _setting_item_to_dict(row: VenueConfig) -> dict[str, Any]:
    return {
        "key": str(row.config_key),
        "value": str(row.config_value) if row.config_value is not None else None,
        "updated_at": str(row.updated_at) if row.updated_at is not None else _now_iso(),
    }


# ---------------------------------------------------------------------------
# Helpers: field diff and conflict display
# ---------------------------------------------------------------------------

_SINGER_LOCKED_FIELDS = {"total_points", "loyalty_tier_id", "account_id"}
_SINGER_MERGEABLE_FIELDS = {
    "stage_name",
    "first_name",
    "last_name",
    "real_name",
    "pronouns",
    "email",
    "phone",
}


def _diff_dicts(server: dict[str, Any], client: dict[str, Any]) -> list[str]:
    """Return keys whose values differ (treating empty string == None for strings)."""
    keys = set(server.keys()) | set(client.keys())
    changed: list[str] = []
    for key in keys:
        s = server.get(key)
        c = client.get(key)
        if isinstance(s, str) and not s.strip():
            s = None
        if isinstance(c, str) and not c.strip():
            c = None
        if s != c:
            changed.append(key)
    return sorted(changed)


def _singer_display_label(item: SyncSingerItem) -> str:
    return item.stage_name or item.real_name or item.email or str(item.id)


def _build_singer_conflict(existing: Singer, item: SyncSingerItem) -> RepairSyncConflict:
    server_state = _singer_item_to_dict(existing)
    client_state = item.model_dump()
    changed = _diff_dicts(server_state, client_state)
    return RepairSyncConflict(
        entity_type="singers",
        entity_id=str(item.id),
        display_label=_singer_display_label(item),
        changed_fields=changed,
        server_state=server_state,
        client_state=client_state,
        resolution="server_wins",
        locked_fields=sorted(_SINGER_LOCKED_FIELDS),
        mergeable_fields=sorted(_SINGER_MERGEABLE_FIELDS),
    )


def _build_queue_conflict(existing: QueueRequest, item: SyncQueueItem) -> RepairSyncConflict:
    server_state = _queue_item_to_dict(existing)
    client_state = item.model_dump()
    changed = _diff_dicts(server_state, client_state)
    # Try to derive a friendly label.
    label = item.singer_name or item.singer_id
    display = f"Queue item — {label}" if label else f"Queue item {existing.id}"
    return RepairSyncConflict(
        entity_type="queue",
        entity_id=str(existing.id),
        display_label=display,
        changed_fields=changed,
        server_state=server_state,
        client_state=client_state,
        resolution="server_wins",
        locked_fields=[],
        mergeable_fields=None,
    )


def _build_settings_conflict(existing: VenueConfig, item: SyncSettingItem) -> RepairSyncConflict:
    server_state = _setting_item_to_dict(existing)
    client_state = {"key": item.key, "value": item.value, "updated_at": item.updated_at}
    changed = _diff_dicts(server_state, client_state)
    return RepairSyncConflict(
        entity_type="settings",
        entity_id=item.key,
        display_label=f"Setting — {item.key}",
        changed_fields=changed,
        server_state=server_state,
        client_state=client_state,
        resolution="server_wins",
        locked_fields=[],
        mergeable_fields=["value"],
    )


# ---------------------------------------------------------------------------
# Song resolution (mirrors kj_sync)
# ---------------------------------------------------------------------------

async def _resolve_or_create_song(
    db: AsyncSession,
    venue_id: str,
    song_id: str | None,
    song_title: str | None = None,
    song_artist: str | None = None,
) -> str | None:
    if not song_id and not song_title:
        return None

    if song_id:
        existing = (
            await db.execute(
                select(Song).where(Song.id == song_id, Song.venue_id == venue_id)
            )
        ).scalar_one_or_none()
        if existing:
            return str(existing.id)

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


# ---------------------------------------------------------------------------
# Step-level progress helpers
# ---------------------------------------------------------------------------

_STEP_LABELS = [
    "Uploading singers…",
    "Uploading queue and history…",
    "Uploading settings…",
    "Uploading now playing…",
    "Resolving conflicts…",
    "Finalizing…",
]


def _progress(step_index: int) -> RepairSyncProgress:
    total = len(_STEP_LABELS)
    current = max(1, min(step_index + 1, total))
    return RepairSyncProgress(
        total_steps=total,
        current_step=current,
        step_label=_STEP_LABELS[step_index],
        percent=int(round((current / total) * 100)),
    )


# ---------------------------------------------------------------------------
# Core conflict detection
# ---------------------------------------------------------------------------

async def _detect_singer_conflicts(
    db: AsyncSession,
    venue_id: str,
    snapshot: RepairSyncSingerSnapshot | None,
) -> list[RepairSyncConflict]:
    if not snapshot or not snapshot.items:
        return []
    conflicts: list[RepairSyncConflict] = []
    for item in snapshot.items:
        existing = (
            await db.execute(
                select(Singer).where(Singer.id == item.id, Singer.venue_id == venue_id)
            )
        ).scalar_one_or_none()
        if not existing:
            continue
        is_conflict = (
            snapshot.last_modified_at
            and existing.updated_at
            and str(existing.updated_at) > str(snapshot.last_modified_at)
        )
        if is_conflict:
            conflicts.append(_build_singer_conflict(existing, item))
    # Deleted ids
    for del_id in snapshot.deleted_ids:
        existing = (
            await db.execute(
                select(Singer).where(Singer.id == del_id, Singer.venue_id == venue_id)
            )
        ).scalar_one_or_none()
        if existing and snapshot.last_modified_at and existing.updated_at and str(existing.updated_at) > str(snapshot.last_modified_at):
            conflicts.append(
                RepairSyncConflict(
                    entity_type="singers",
                    entity_id=str(del_id),
                    display_label=f"Singer — {existing.stage_name or del_id}",
                    changed_fields=["deleted"],
                    server_state=_singer_item_to_dict(existing),
                    client_state={"deleted": True},
                    resolution="server_wins",
                    locked_fields=sorted(_SINGER_LOCKED_FIELDS),
                    mergeable_fields=None,
                )
            )
    return conflicts


async def _detect_queue_conflicts(
    db: AsyncSession,
    venue_id: str,
    snapshot: RepairSyncQueueSnapshot | None,
) -> list[RepairSyncConflict]:
    if not snapshot or not snapshot.items:
        return []
    conflicts: list[RepairSyncConflict] = []
    for item in snapshot.items:
        existing = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.id == item.request_id,
                    QueueRequest.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()
        if not existing:
            continue
        is_conflict = (
            snapshot.last_modified_at
            and existing.updated_at
            and str(existing.updated_at) > str(snapshot.last_modified_at)
        )
        if is_conflict:
            conflicts.append(_build_queue_conflict(existing, item))
    for del_id in snapshot.deleted_ids:
        row = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.id == del_id,
                    QueueRequest.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()
        if row and snapshot.last_modified_at and row.updated_at and str(row.updated_at) > str(snapshot.last_modified_at):
            conflicts.append(
                RepairSyncConflict(
                    entity_type="queue",
                    entity_id=str(del_id),
                    display_label=f"Queue item {del_id}",
                    changed_fields=["deleted"],
                    server_state=_queue_item_to_dict(row),
                    client_state={"deleted": True},
                    resolution="server_wins",
                    locked_fields=[],
                    mergeable_fields=None,
                )
            )
    return conflicts


async def _detect_settings_conflicts(
    db: AsyncSession,
    venue_id: str,
    snapshot: RepairSyncSettingsSnapshot | None,
) -> list[RepairSyncConflict]:
    if not snapshot or not snapshot.items:
        return []
    conflicts: list[RepairSyncConflict] = []
    for item in snapshot.items:
        existing = (
            await db.execute(
                select(VenueConfig).where(
                    VenueConfig.venue_id == venue_id,
                    VenueConfig.config_key == item.key,
                )
            )
        ).scalar_one_or_none()
        if not existing:
            continue
        is_conflict = (
            snapshot.last_modified_at
            and existing.updated_at
            and str(existing.updated_at) > str(snapshot.last_modified_at)
        )
        if is_conflict:
            conflicts.append(_build_settings_conflict(existing, item))
    return conflicts


async def detect_conflicts(
    db: AsyncSession,
    venue_id: str,
    snapshot: RepairSyncSnapshot,
) -> list[RepairSyncConflict]:
    """Return all conflicts for a snapshot without mutating the database."""
    conflicts: list[RepairSyncConflict] = []
    conflicts.extend(await _detect_singer_conflicts(db, venue_id, snapshot.singers))
    conflicts.extend(await _detect_queue_conflicts(db, venue_id, snapshot.queue))
    conflicts.extend(await _detect_settings_conflicts(db, venue_id, snapshot.settings))
    return conflicts


# ---------------------------------------------------------------------------
# Apply snapshot (client_wins or resolved prompt mode)
# ---------------------------------------------------------------------------

async def _ensure_singer_exists(
    db: AsyncSession,
    venue_id: str,
    singer_id: str,
    fallback_stage: str = "Unknown",
) -> None:
    existing = (
        await db.execute(
            select(Singer).where(Singer.id == singer_id, Singer.venue_id == venue_id)
        )
    ).scalar_one_or_none()
    if existing:
        return

    base_stage = fallback_stage
    counter = 1
    while (
        await db.execute(
            select(Singer.id).where(Singer.venue_id == venue_id, Singer.stage_name == fallback_stage)
        )
    ).scalar_one_or_none():
        counter += 1
        fallback_stage = f"{base_stage} ({counter})"

    db.add(
        Singer(
            id=singer_id,
            venue_id=venue_id,
            stage_name=fallback_stage,
            created_at=_now_iso(),
            updated_at=_now_iso(),
        )
    )


async def _apply_singers(
    db: AsyncSession,
    venue_id: str,
    snapshot: RepairSyncSingerSnapshot | None,
    resolutions: dict[str, RepairSyncConflict] | None = None,
) -> int:
    if not snapshot:
        return 0
    synced = 0
    for item in snapshot.items or []:
        key = f"singers:{item.id}"
        resolution = (resolutions or {}).get(key)
        existing = (
            await db.execute(
                select(Singer).where(Singer.id == item.id, Singer.venue_id == venue_id)
            )
        ).scalar_one_or_none()

        if existing:
            # In prompt mode a server_wins resolution means the server copy wins
            # outright; editable fields are not overwritten by the client.
            if resolution and resolution.resolution == "server_wins":
                continue
            merged = _merge_singer(existing, item, resolution)
            existing.stage_name = merged.stage_name
            existing.first_name = merged.first_name
            existing.last_name = merged.last_name
            existing.real_name = merged.real_name
            existing.pronouns = merged.pronouns
            existing.email = merged.email
            existing.phone = merged.phone
            existing.last_seen = merged.last_seen if merged.last_seen is not None else existing.last_seen
            existing.deactivated_at = merged.deactivated_at
            # account_id, total_points, loyalty_tier_id remain server-managed and untouched.
            existing.updated_at = _now_iso()
        else:
            db.add(
                Singer(
                    id=item.id,
                    venue_id=venue_id,
                    stage_name=item.stage_name,
                    real_name=item.real_name,
                    first_name=item.first_name,
                    last_name=item.last_name,
                    pronouns=item.pronouns,
                    email=item.email,
                    phone=item.phone,
                    last_seen=item.last_seen,
                    deactivated_at=item.deactivated_at,
                    created_at=item.created_at,
                    updated_at=_now_iso(),
                )
            )
        synced += 1

    for del_id in snapshot.deleted_ids or []:
        row = (
            await db.execute(
                select(Singer).where(Singer.id == del_id, Singer.venue_id == venue_id)
            )
        ).scalar_one_or_none()
        if row:
            resolution = (resolutions or {}).get(f"singers:{del_id}")
            if resolution and resolution.resolution == "client_wins":
                row.deleted_at = _now_iso()
                row.updated_at = _now_iso()
    return synced


def _merge_singer(
    existing: Singer,
    item: SyncSingerItem,
    resolution: RepairSyncConflict | None,
) -> SyncSingerItem:
    """Return a SyncSingerItem representing the resolved state."""
    if resolution is None or resolution.resolution != "merge":
        return item

    field_winners: dict[str, str] = {}
    if resolution.field_resolutions:
        field_winners.update(resolution.field_resolutions)
    # Fallback: legacy schema may carry winners inside client_state.
    if isinstance(resolution.client_state, dict):
        for key, val in resolution.client_state.items():
            if isinstance(val, str) and key not in field_winners:
                field_winners[key] = val

    server = _singer_item_to_dict(existing)
    client = item.model_dump()

    result = copy.deepcopy(client)
    for key, winner in field_winners.items():
        if winner == "server":
            result[key] = server.get(key)
        elif winner == "client":
            result[key] = client.get(key)

    return SyncSingerItem(**result)


async def _apply_queue(
    db: AsyncSession,
    venue_id: str,
    snapshot: RepairSyncQueueSnapshot | None,
    resolutions: dict[str, RepairSyncConflict] | None = None,
) -> int:
    if not snapshot:
        return 0
    synced = 0
    for item in snapshot.items or []:
        key = f"queue:{item.request_id}"
        resolution = (resolutions or {}).get(key)
        if resolution and resolution.resolution == "server_wins":
            continue

        # Ensure singer exists (server wins conflict does not stop creating missing singers)
        await _ensure_singer_exists(
            db,
            venue_id,
            item.singer_id,
            fallback_stage=(item.notes or item.singer_name or "Unknown").strip() or "Unknown",
        )
        resolved_song_id = await _resolve_or_create_song(
            db, venue_id, item.song_id, item.song_title, item.song_artist
        )
        if resolved_song_id and item.song_id:
            await db.flush()

        existing = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.id == item.request_id,
                    QueueRequest.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.singer_id = item.singer_id
            if resolved_song_id is not None:
                existing.song_id = resolved_song_id
            elif item.status not in ("rejected", "skipped"):
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
        synced += 1

    for del_id in snapshot.deleted_ids or []:
        row = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.id == del_id,
                    QueueRequest.venue_id == venue_id,
                )
            )
        ).scalar_one_or_none()
        if row:
            resolution = (resolutions or {}).get(f"queue:{del_id}")
            if resolution and resolution.resolution == "server_wins":
                continue
            row.deleted_at = _now_iso()
            row.updated_at = _now_iso()
    return synced


async def _apply_settings(
    db: AsyncSession,
    venue_id: str,
    snapshot: RepairSyncSettingsSnapshot | None,
    resolutions: dict[str, RepairSyncConflict] | None = None,
) -> int:
    if not snapshot:
        return 0
    synced = 0
    for item in snapshot.items or []:
        key = f"settings:{item.key}"
        resolution = (resolutions or {}).get(key)
        if resolution and resolution.resolution == "server_wins":
            continue

        existing = (
            await db.execute(
                select(VenueConfig).where(
                    VenueConfig.venue_id == venue_id,
                    VenueConfig.config_key == item.key,
                )
            )
        ).scalar_one_or_none()

        if existing:
            if resolution and resolution.resolution == "merge" and resolution.field_resolutions:
                field_winners = resolution.field_resolutions
                if field_winners.get("value") == "server":
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
    return synced


async def _apply_now_playing(
    db: AsyncSession,
    venue_id: str,
    snapshot: NowPlayingSnapshot | None,
) -> bool:
    if not snapshot:
        return False

    from sqlalchemy import update

    if not snapshot.is_dj_track:
        await db.execute(
            update(QueueRequest)
            .where(
                QueueRequest.venue_id == venue_id,
                QueueRequest.status == "now_playing",
            )
            .values(status="pending", updated_at=_now_iso())
        )

    if snapshot.singer_id and not snapshot.is_dj_track:
        existing = (
            await db.execute(
                select(QueueRequest).where(
                    QueueRequest.singer_id == snapshot.singer_id,
                    QueueRequest.venue_id == venue_id,
                    QueueRequest.deleted_at.is_(None),
                )
            )
        ).scalars().first()

        if existing:
            existing.status = "now_playing"
            existing.updated_at = _now_iso()
            if snapshot.song_id:
                resolved = await _resolve_or_create_song(
                    db, venue_id, snapshot.song_id, snapshot.song_title, snapshot.song_artist
                )
                if resolved:
                    existing.song_id = resolved
                    await db.flush()
        else:
            db.add(
                QueueRequest(
                    id=str(uuid.uuid4()),
                    venue_id=venue_id,
                    singer_id=snapshot.singer_id,
                    status="now_playing",
                    rotation_position=0,
                    notes=snapshot.singer_name or "",
                    requested_at=_now_iso(),
                    updated_at=_now_iso(),
                )
            )
    await db.commit()

    try:
        svc = QueueService(db)
        now_playing_out = {
            "request_id": str(snapshot.singer_id) if snapshot.singer_id else "dj_track",
            "singer_name": snapshot.singer_name or ("DJ" if snapshot.is_dj_track else snapshot.singer_name),
            "song_title": snapshot.song_title,
            "song_artist": snapshot.song_artist,
            "started_at": snapshot.started_at or _now_iso(),
            "elapsed_seconds": 0,
            "is_dj_track": snapshot.is_dj_track,
        }
        await QueueEventPublisher.publish(venue_id, "now_playing", now_playing_out)
        if not snapshot.is_dj_track:
            await svc.broadcast_queue_state(venue_id)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("broadcast after repair now_playing failed: %s", exc)

    return True


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _resolutions_by_id(resolutions: list[RepairSyncConflict]) -> dict[str, RepairSyncConflict]:
    out: dict[str, RepairSyncConflict] = {}
    for r in resolutions:
        key = str(r.entity_id)
        # Use entity_type to avoid collisions between settings keys and UUIDs.
        out[f"{r.entity_type}:{key}"] = r
    return out


async def _apply_snapshot(
    db: AsyncSession,
    venue_id: str,
    snapshot: RepairSyncSnapshot,
    resolutions: list[RepairSyncConflict] | None = None,
) -> RepairSyncSummary:
    """Apply the snapshot to the DB and return the resulting summary."""
    resolutions_map = _resolutions_by_id(resolutions or [])

    singers_synced = await _apply_singers(db, venue_id, snapshot.singers, resolutions_map)
    await db.flush()

    queue_synced = await _apply_queue(db, venue_id, snapshot.queue, resolutions_map)
    await db.flush()

    settings_synced = await _apply_settings(db, venue_id, snapshot.settings, resolutions_map)
    await db.flush()

    now_playing_synced = await _apply_now_playing(db, venue_id, snapshot.now_playing)

    summary = RepairSyncSummary(
        singers_synced=singers_synced,
        queue_synced=queue_synced,
        settings_synced=settings_synced,
        now_playing_synced=now_playing_synced,
        conflicts_resolved=len(resolutions or []),
        server_modified_at=_now_iso(),
    )
    return summary


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------

async def start_repair_sync(
    db: AsyncSession,
    venue_id: str,
    mode: RepairSyncMode,
    snapshot: RepairSyncSnapshot,
    idempotency_key: str | None = None,
) -> _RepairSyncJob:
    """Start a repair sync job. If idempotency_key exists, return existing job."""
    if idempotency_key:
        existing = await _find_by_idempotency(idempotency_key)
        if existing:
            return existing

    sync_id = str(uuid.uuid4())
    job = _RepairSyncJob(
        sync_id=sync_id,
        venue_id=venue_id,
        mode=mode,
        snapshot=snapshot,
        idempotency_key=idempotency_key,
    )
    await _upsert_job(job)

    # Synchronous processing for testability and simplicity.  The contract
    # requires a quick response; real-world scaling can move this to a
    # background worker later without changing the API surface.
    try:
        job.status = RepairSyncStatus.processing
        job.progress = _progress(0)
        await _update_job(job)

        conflicts = await detect_conflicts(db, venue_id, snapshot)

        if mode == RepairSyncMode.prompt and conflicts:
            job.status = RepairSyncStatus.needs_resolution
            job.progress = _progress(4)
            job.conflicts = conflicts
            job.updated_at = _now_iso()
            await _update_job(job)
            return job

        # client_wins or no conflicts: apply directly
        job.progress = _progress(4)
        await _update_job(job)

        if mode == RepairSyncMode.client_wins and conflicts:
            # In client_wins mode, treat every conflict as client_wins except
            # server-managed fields which _apply_singers already protects.
            for c in conflicts:
                c.resolution = "client_wins"

        summary = await _apply_snapshot(db, venue_id, snapshot, conflicts)
        job.status = RepairSyncStatus.completed
        job.summary = RepairSyncJobSummary(
            singers_synced=summary.singers_synced,
            queue_synced=summary.queue_synced,
            settings_synced=summary.settings_synced,
            now_playing_synced=summary.now_playing_synced,
            conflicts_resolved=summary.conflicts_resolved,
            server_modified_at=summary.server_modified_at,
        )
        job.progress = _progress(5)
        job.updated_at = _now_iso()
        await _update_job(job)
    except Exception as exc:
        job.status = RepairSyncStatus.failed
        job.error = {"type": "about:blank", "title": "Repair sync failed", "status": 500, "detail": str(exc), "code": "support_required"}
        job.updated_at = _now_iso()
        await _update_job(job)

    return job


async def get_repair_sync(sync_id: str) -> _RepairSyncJob | None:
    return await _get_job(sync_id)


async def resolve_repair_sync(
    db: AsyncSession,
    sync_id: str,
    resolutions: list[RepairSyncConflict],
) -> _RepairSyncJob:
    """Resolve conflicts for a prompt-mode job and finish applying the snapshot."""
    job = await _get_job(sync_id)
    if not job:
        raise ValueError("Sync job not found")

    if job.status != RepairSyncStatus.needs_resolution:
        raise ValueError(f"Job status is {job.status.value}, expected needs_resolution")

    required = {f"{c.entity_type}:{c.entity_id}" for c in job.conflicts}
    provided = {f"{r.entity_type}:{r.entity_id}" for r in resolutions}
    missing = required - provided
    if missing:
        raise ValueError(f"Unresolved conflicts: {sorted(missing)}")

    try:
        job.status = RepairSyncStatus.processing
        job.progress = _progress(4)
        await _update_job(job)

        summary = await _apply_snapshot(db, job.venue_id, job.snapshot, resolutions)
        job.status = RepairSyncStatus.completed
        job.summary = RepairSyncJobSummary(
            singers_synced=summary.singers_synced,
            queue_synced=summary.queue_synced,
            settings_synced=summary.settings_synced,
            now_playing_synced=summary.now_playing_synced,
            conflicts_resolved=summary.conflicts_resolved,
            server_modified_at=summary.server_modified_at,
        )
        job.conflicts = []
        job.progress = _progress(5)
        job.updated_at = _now_iso()
        await _update_job(job)
    except Exception as exc:
        job.status = RepairSyncStatus.failed
        job.error = {"type": "about:blank", "title": "Repair sync failed", "status": 500, "detail": str(exc), "code": "support_required"}
        job.updated_at = _now_iso()
        await _update_job(job)

    return job


async def cancel_repair_sync(sync_id: str) -> tuple[bool, _RepairSyncJob | None]:
    """Best-effort cancel. Returns (was_cancelled, job)."""
    job = await _get_job(sync_id)
    if not job:
        return False, None
    if job.status not in (RepairSyncStatus.completed, RepairSyncStatus.failed, RepairSyncStatus.cancelled):
        job.status = RepairSyncStatus.cancelled
        job.updated_at = _now_iso()
        await _update_job(job)
    return True, job


# ---------------------------------------------------------------------------
# Response serialization
# ---------------------------------------------------------------------------

def job_to_out(job: _RepairSyncJob) -> dict[str, Any]:
    error = None
    if job.error:
        from app.schemas import ProblemDetail
        error = ProblemDetail(**job.error).model_dump()
    summary = None
    if job.summary:
        summary = RepairSyncSummary(
            singers_synced=job.summary.singers_synced,
            queue_synced=job.summary.queue_synced,
            settings_synced=job.summary.settings_synced,
            now_playing_synced=job.summary.now_playing_synced,
            conflicts_resolved=job.summary.conflicts_resolved,
            server_modified_at=job.summary.server_modified_at or _now_iso(),
        ).model_dump()
    return {
        "sync_id": job.sync_id,
        "status": job.status.value,
        "mode": job.mode.value,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "progress": job.progress.model_dump() if job.progress else None,
        "summary": summary,
        "conflicts": [c.model_dump() for c in job.conflicts] if job.conflicts else None,
        "error": error,
    }
