"""GDPR compliance tests — data portability (GET /me/export) and right to erasure (DELETE /me)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import status

from app.core.security import hash_password
from app.models import (
    Singer,
    Venue,
    QueueRequest,
    Song,
    SingerFavorite,
    SingerFollow,
    PointsLedger,
    CheckInSession,
    Consent,
    ShareEvent,
    LeaderboardEntry,
    Leaderboard,
    SingerAchievement,
)
from sqlalchemy import select


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}

async def _seed_venue(session, name: str = "Test Venue") -> Venue:
    venue_id = str(uuid.uuid4())
    venue = Venue(
        id=venue_id,
        name=name,
        slug=f"test-{venue_id[:8]}",
        venue_code="".join(__import__("random").choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6)),
    )
    session.add(venue)
    await session.commit()
    return venue


async def _seed_singer(
    session,
    venue_id: str,
    stage_name: str = "Test Singer",
    role: str = "singer",
    password: str | None = "secret123",
    email: str | None = None,
    real_name: str | None = None,
    pronouns: str | None = None,
    phone: str | None = None,
    bio: str | None = None,
    social_links: str | None = None,
    avatar_url: str | None = None,
    notes: str | None = None,
) -> Singer:
    singer = Singer(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        stage_name=stage_name,
        email=email or f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password(password) if password else None,
        role=role,
        real_name=real_name,
        pronouns=pronouns,
        phone=phone,
        bio=bio,
        social_links=social_links,
        avatar_url=avatar_url,
        notes=notes,
    )
    session.add(singer)
    await session.commit()
    await session.refresh(singer)
    return singer


async def _seed_song(session, venue_id: str, title: str = "Test Song", genre: str = "Rock") -> Song:
    song = Song(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        title=title,
        artist="Test Artist",
        genre=genre,
        is_available=1,
        is_active=1,
    )
    session.add(song)
    await session.commit()
    await session.refresh(song)
    return song


def _token_for_singer(jwt_encode, singer: Singer) -> str:
    return jwt_encode(venue_id=singer.venue_id, role=singer.role, user_id=singer.id)


# ---------------------------------------------------------------------------
# GET /me/export
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_export_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/singers/me/export")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_export_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other_venue = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other_venue.id, stage_name="Outsider")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/export",
        headers=_auth_header(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_export_not_found(client, db, venue_with_songs, jwt_encode):
    """Token for a non-existent singer (unseeded UUID) should get 401 from get_current_user."""
    venue_id, _ = venue_with_songs
    fake_id = str(uuid.uuid4())
    token = jwt_encode(venue_id=venue_id, role="singer", user_id=fake_id)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/export",
        headers=_auth_header(token),
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_export_returns_structured_data(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(
        db, venue_id, stage_name="ExportMe", real_name="Real Name", pronouns="they/them", phone="555-0100"
    )
    song = await _seed_song(db, venue_id, title="ExportSong")

    # Queue request
    qr = QueueRequest(
        id=str(uuid.uuid4()),
        venue_id=venue_id,
        singer_id=singer.id,
        song_id=song.id,
        status="completed",
        requested_at="2026-01-01T12:00:00Z",
        played_at="2026-01-01T12:05:00Z",
        notes="export test",
    )
    db.add(qr)

    # Favorite
    fav = SingerFavorite(id=str(uuid.uuid4()), venue_id=venue_id, singer_id=singer.id, song_id=song.id)
    db.add(fav)

    # Follow
    other_singer = await _seed_singer(db, venue_id, stage_name="Followed")
    follow = SingerFollow(id=str(uuid.uuid4()), venue_id=venue_id, follower_id=singer.id, followee_id=other_singer.id)
    db.add(follow)

    # Points ledger
    pl = PointsLedger(id=str(uuid.uuid4()), venue_id=venue_id, singer_id=singer.id, amount=100, reason="test", reference_type="checkin", reference_id=str(uuid.uuid4()))
    db.add(pl)

    # Check-in session
    cis = CheckInSession(id=str(uuid.uuid4()), singer_id=singer.id, venue_id=venue_id, checked_in_at="2026-01-01T10:00:00Z", expires_at="2026-01-01T14:00:00Z", table_number="12")
    db.add(cis)

    # Consent
    consent = Consent(id=str(uuid.uuid4()), venue_id=venue_id, singer_id=singer.id, consent_type="marketing", granted=1, granted_at="2026-01-01T09:00:00Z", ip_address="1.2.3.4")
    db.add(consent)

    # Share event
    se = ShareEvent(id=str(uuid.uuid4()), venue_id=venue_id, singer_id=singer.id, platform="twitter", url="https://x.com/share/1", content_type="song")
    db.add(se)

    # Leaderboard + entry
    lb = Leaderboard(id=str(uuid.uuid4()), venue_id=venue_id, name="Top Monthly", metric_type="points", period_start="2026-01-01", period_end="2026-01-31")
    db.add(lb)
    await db.commit()
    await db.refresh(lb)
    entry = LeaderboardEntry(id=str(uuid.uuid4()), leaderboard_id=lb.id, singer_id=singer.id, venue_id=venue_id, score=500.0, rank=1)
    db.add(entry)

    # Achievement
    ach = SingerAchievement(id=str(uuid.uuid4()), venue_id=venue_id, singer_id=singer.id, achievement_key="first_song", unlocked_at="2026-01-01T13:00:00Z", progress=1)
    db.add(ach)

    await db.commit()

    token = _token_for_singer(jwt_encode, singer)
    resp = await client.get(
        f"/v1/venues/{venue_id}/singers/me/export",
        headers=_auth_header(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()

    assert data["singer_id"] == singer.id
    assert data["venue_id"] == venue_id
    assert "exported_at" in data

    # Profile assertions
    profile = data["profile"]
    assert profile["stage_name"] == "ExportMe"
    assert profile["real_name"] == "Real Name"
    assert profile["pronouns"] == "they/them"
    assert profile["phone"] == "555-0100"

    # Sub-collections
    assert len(data["queue_history"]) == 1
    assert data["queue_history"][0]["song_title"] == "ExportSong"
    assert data["queue_history"][0]["notes"] == "export test"

    assert len(data["favorites"]) == 1
    assert data["favorites"][0]["song_id"] == song.id

    assert len(data["follows"]) == 1
    assert data["follows"][0]["followee_id"] == other_singer.id

    assert len(data["points_ledger"]) == 1
    assert data["points_ledger"][0]["amount"] == 100

    assert len(data["check_in_sessions"]) == 1
    assert data["check_in_sessions"][0]["table_number"] == "12"

    assert len(data["consents"]) == 1
    assert data["consents"][0]["consent_type"] == "marketing"
    assert data["consents"][0]["granted"] is True

    assert len(data["share_events"]) == 1
    assert data["share_events"][0]["platform"] == "twitter"

    assert len(data["leaderboard_entries"]) == 1
    assert data["leaderboard_entries"][0]["score"] == 500.0

    assert len(data["achievements"]) == 1
    assert data["achievements"][0]["key"] == "first_song"

    # Payments — empty list is fine (no payments seeded)
    assert data["payments"] == []


# ---------------------------------------------------------------------------
# DELETE /me
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_delete_me_requires_auth(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.delete(f"/v1/venues/{venue_id}/singers/me")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.anyio
async def test_delete_me_wrong_venue(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    other_venue = await _seed_venue(db, "Other")
    singer = await _seed_singer(db, other_venue.id, stage_name="Outsider")
    token = _token_for_singer(jwt_encode, singer)
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/me",
        headers=_auth_header(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_delete_me_erasure_flow(client, db, venue_with_songs, jwt_encode):
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(
        db, venue_id, stage_name="EraseMe", email="erase@example.com", phone="555-0200",
        bio="About me", real_name="Real", notes="notes", social_links="{}", avatar_url="/uploads/x.jpg"
    )
    token = _token_for_singer(jwt_encode, singer)

    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/me",
        headers=_auth_header(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["singer_id"] == singer.id
    assert data["status"] == "erasure_initiated"
    assert "erased_at" in data
    assert data["retention_days"] == 30
    assert "permanently deleted" in data["message"].lower()

    # Verify DB state
    result = await db.execute(select(Singer).where(Singer.id == singer.id))
    updated = result.scalar_one()
    assert updated.gdpr_erased_at is not None
    assert updated.deactivated_at is not None
    assert updated.email is None
    assert updated.phone is None
    assert updated.bio is None
    assert updated.social_links is None
    assert updated.avatar_url is None
    assert updated.real_name is None
    assert updated.notes is None


@pytest.mark.anyio
async def test_delete_me_after_erasure_token_rejected(client, db, venue_with_songs, jwt_encode):
    """Once gdpr_erased_at is set, the singer should no longer authenticate."""
    venue_id, _ = venue_with_songs
    singer = await _seed_singer(db, venue_id, stage_name="EraseMe", email="erase@example.com")
    token = _token_for_singer(jwt_encode, singer)

    # First call succeeds
    resp = await client.delete(
        f"/v1/venues/{venue_id}/singers/me",
        headers=_auth_header(token),
    )
    assert resp.status_code == status.HTTP_200_OK

    # Second call with same token should now get 401 because get_current_user
    # will see deactivated_at / gdpr_erased_at and reject.
    resp2 = await client.delete(
        f"/v1/venues/{venue_id}/singers/me",
        headers=_auth_header(token),
    )
    assert resp2.status_code == status.HTTP_401_UNAUTHORIZED
