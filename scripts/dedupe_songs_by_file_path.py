#!/usr/bin/env python3
"""Deduplicate active songs by (venue_id, file_path).

Historical sync bugs allowed multiple active Song rows for the same file_path
in the same venue.  This script keeps the oldest row per (venue_id, file_path)
and soft-deletes the rest, so the unique partial index can be applied safely.

Run inside the API container:
    docker compose exec -T api python /app/scripts/dedupe_songs_by_file_path.py [--dry-run]
"""
import asyncio
import sys

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory
from app.models import Song


async def main(dry_run: bool = False) -> None:
    async with async_session_factory() as session:
        session: AsyncSession
        # Find groups of active (venue_id, file_path) with more than one row
        subq = (
            select(Song.venue_id, Song.file_path)
            .where(Song.deleted_at.is_(None))
            .group_by(Song.venue_id, Song.file_path)
            .having(func.count() > 1)
        )
        result = await session.execute(subq)
        groups = result.all()
        print(f"found {len(groups)} duplicate (venue_id, file_path) groups")

        total_kept = 0
        total_removed = 0
        for venue_id, file_path in groups:
            rows_result = await session.execute(
                select(Song)
                .where(
                    Song.venue_id == venue_id,
                    Song.file_path == file_path,
                    Song.deleted_at.is_(None),
                )
                .order_by(Song.created_at.asc())
            )
            rows = rows_result.scalars().all()
            if len(rows) <= 1:
                continue
            keep = rows[0]
            duplicates = rows[1:]
            print(f"venue={venue_id} path={file_path!r}: keep {keep.id}, remove {len(duplicates)} dups")
            if not dry_run:
                for dup in duplicates:
                    dup.is_available = 0
                    dup.is_active = 0
                    dup.deleted_at = func.now()
                    dup.unavailable_reason = "duplicate_file_path"
            total_kept += 1
            total_removed += len(duplicates)

        if not dry_run:
            await session.commit()

        print(f"summary: kept={total_kept} rows, removed={total_removed} duplicate rows")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("dry-run mode: no changes will be committed")
    asyncio.run(main(dry_run=dry))
