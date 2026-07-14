"""Tests for app.services.singer_merge."""
import pytest
from sqlalchemy import select

from app.models import Account, QueueRequest, Singer, SingerLinkMergeLog, Song
from app.services.singer_merge import merge_local_singer_into_mobile


@pytest.mark.asyncio
async def test_merge_reassigns_queue_history(db):
    venue_id = "venue-merge-test"

    account = Account(
        id="acc-merge-1",
        email="mobile@example.com",
        stage_name="Mobile Star",
        password_hash="x",
    )
    local = Singer(
        id="local-merge-1",
        venue_id=venue_id,
        stage_name="Old Local",
        first_name="Local",
        last_name="Singer",
    )
    mobile = Singer(
        id="mobile-merge-1",
        venue_id=venue_id,
        account_id="acc-merge-1",
        stage_name="Mobile Star",
    )
    song = Song(id="song-merge-1", venue_id=venue_id, title="Test Song", artist="Artist", file_path="/x.mp3")
    db.add_all([account, local, mobile, song])
    await db.commit()

    qr = QueueRequest(
        id="qr-merge-1",
        venue_id=venue_id,
        singer_id="local-merge-1",
        song_id="song-merge-1",
        status="completed",
        requested_at="2026-07-14T10:00:00Z",
    )
    db.add(qr)
    await db.commit()

    result = await merge_local_singer_into_mobile(
        db,
        venue_id=venue_id,
        local_singer_id="local-merge-1",
        target_singer_id="mobile-merge-1",
    )
    await db.commit()

    assert result.local_singer_id == "local-merge-1"
    assert result.target_singer_id == "mobile-merge-1"
    assert result.merged_records["queue_requests"] == 1

    row = await db.get(QueueRequest, "qr-merge-1")
    assert row.singer_id == "mobile-merge-1"

    local_after = await db.get(Singer, "local-merge-1")
    assert local_after.deleted_at is not None
    assert local_after.linked_singer_id == "mobile-merge-1"

    log = (await db.execute(
        select(SingerLinkMergeLog).where(SingerLinkMergeLog.source_singer_id == "local-merge-1")
    )).scalar_one_or_none()
    assert log is not None
    assert log.target_singer_id == "mobile-merge-1"
