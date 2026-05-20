"""Song catalog CRUD + search tests (36)."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import status

from app.models import Song


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

AUTHORIZATION = lambda token: {"Authorization": f"Bearer {token}"}


# =====================================================================
# 1. LIST
# =====================================================================

@pytest.mark.anyio
async def test_list_songs_no_token(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 4  # 5 seeded, 1 unavailable
    assert len(data["items"]) == 4


@pytest.mark.anyio
async def test_list_songs_with_admin_token(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="admin")
    # All songs are for this venue; nothing extra to seed
    resp = await client.get(
        f"/v1/venues/{venue_id}/songs",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["total"] == 4


@pytest.mark.anyio
async def test_list_songs_with_kj_token(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="kj")
    resp = await client.get(
        f"/v1/venues/{venue_id}/songs",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.anyio
async def test_list_songs_with_singer_token(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="singer")
    resp = await client.get(
        f"/v1/venues/{venue_id}/songs",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.anyio
async def test_list_songs_pagination(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?page=1&per_page=2")
    data = resp.json()
    assert data["page"] == 1
    assert data["per_page"] == 2
    assert data["total"] == 4
    assert len(data["items"]) == 2


@pytest.mark.anyio
async def test_list_songs_pagination_page2(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?page=2&per_page=2")
    data = resp.json()
    assert data["page"] == 2
    assert len(data["items"]) == 2


@pytest.mark.anyio
async def test_list_songs_with_available_only(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?available_only=true")
    data = resp.json()
    # already all available except Creep
    assert data["total"] == 4


# =====================================================================
# 2. SEARCH
# =====================================================================

@pytest.mark.anyio
async def test_search_by_title(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?q=Bohemian")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Bohemian Rhapsody"


@pytest.mark.anyio
async def test_search_by_artist(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?q=Eagles")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["artist"] == "Eagles"


@pytest.mark.anyio
async def test_search_no_results(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?q=zzzznotfound")
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.anyio
async def test_search_case_insensitive(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?q=bohemian")
    data = resp.json()
    assert data["total"] == 1


# =====================================================================
# 3. FILTER
# =====================================================================

@pytest.mark.anyio
async def test_filter_genre(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?genre=Rock")
    data = resp.json()
    assert data["total"] == 2
    titles = {item["title"] for item in data["items"]}
    assert titles == {"Bohemian Rhapsody", "Hotel California"}


@pytest.mark.anyio
async def test_filter_category(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?category=Classic")
    data = resp.json()
    assert data["total"] == 2


@pytest.mark.anyio
async def test_filter_decade(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?decade=1970s")
    data = resp.json()
    assert data["total"] == 2


@pytest.mark.anyio
async def test_filter_decade_1980s(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?decade=1980s")
    data = resp.json()
    assert data["total"] == 2


@pytest.mark.anyio
async def test_filter_decade_invalid_format(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?decade=80s")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.anyio
async def test_filter_language(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?language=English")
    data = resp.json()
    # All seeded are English
    assert data["total"] == 4


@pytest.mark.anyio
async def test_filter_combo_search_and_genre(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?q=Hotel&genre=Rock")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Hotel California"


# =====================================================================
# 4. SORT
# =====================================================================

@pytest.mark.anyio
async def test_sort_by_title_asc(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?sort=title&order=asc")
    data = resp.json()
    titles = [i["title"] for i in data["items"]]
    assert titles == sorted(titles)


@pytest.mark.anyio
async def test_sort_by_title_desc(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?sort=title&order=desc")
    data = resp.json()
    titles = [i["title"] for i in data["items"]]
    assert titles == sorted(titles, reverse=True)


@pytest.mark.anyio
async def test_sort_by_year_asc(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?sort=year&order=asc")
    data = resp.json()
    years = [i["year"] for i in data["items"]]
    assert years == sorted(years)


@pytest.mark.anyio
async def test_sort_by_artist_asc(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?sort=artist&order=asc")
    data = resp.json()
    artists = [i["artist"] for i in data["items"]]
    assert artists == sorted(artists)


# =====================================================================
# 5. GET SINGLE
# =====================================================================

@pytest.mark.anyio
async def test_get_song_success(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    song = songs[0]
    resp = await client.get(f"/v1/venues/{venue_id}/songs/{song.id}")
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["id"] == song.id
    assert data["title"] == song.title


@pytest.mark.anyio
async def test_get_song_not_found(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs/{uuid.uuid4()}")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_get_song_wrong_venue(client, db, admin_token_mismatch, venue_with_songs):
    token, other_venue = admin_token_mismatch
    venue_id, songs = venue_with_songs
    song = songs[0]
    resp = await client.get(
        f"/v1/venues/{other_venue}/songs/{song.id}",
        headers=AUTHORIZATION(token),
    )
    # other_venue does not exist in DB => 404 before venue_match
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =====================================================================
# 6. CREATE
# =====================================================================

@pytest.mark.anyio
async def test_create_song_admin(client, db, jwt_encode, admin_token):
    token, venue_id = admin_token
    # create a venue first
    from app.models import Venue as V
    db.add(V(id=venue_id, name="Admin Venue", slug=f"admin-{venue_id[:8]}"))
    await db.commit()

    payload = {
        "title": "New Song",
        "artist": "New Artist",
        "genre": "Pop",
        "category": "Modern",
        "year": 2024,
        "is_available": True,
    }
    resp = await client.post(
        f"/v1/venues/{venue_id}/songs",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["title"] == "New Song"
    assert data["artist"] == "New Artist"
    assert data["genre"] == "Pop"
    assert data["category"] == "Modern"
    assert data["year"] == 2024


@pytest.mark.anyio
async def test_create_song_kj(client, db, jwt_encode, kj_token):
    token, venue_id = kj_token
    from app.models import Venue as V
    db.add(V(id=venue_id, name="KJ Venue", slug=f"kj-{venue_id[:8]}"))
    await db.commit()

    payload = {"title": "KJ Song", "artist": "KJ Artist"}
    resp = await client.post(
        f"/v1/venues/{venue_id}/songs",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_201_CREATED


@pytest.mark.anyio
async def test_create_song_singer_forbidden(client, db, jwt_encode, singer_token):
    token, venue_id = singer_token
    from app.models import Venue as V
    db.add(V(id=venue_id, name="Singer Venue", slug=f"sing-{venue_id[:8]}"))
    await db.commit()

    payload = {"title": "Bad Song", "artist": "Bad Artist"}
    resp = await client.post(
        f"/v1/venues/{venue_id}/songs",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_create_song_venue_mismatch(client, db, admin_token_mismatch):
    token, other_venue = admin_token_mismatch
    payload = {"title": "Mismatch", "artist": "Artist"}
    resp = await client.post(
        f"/v1/venues/{other_venue}/songs",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    # Token venue does not match other_venue (by design of mismatch fixture)
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_create_song_venue_not_found(client, db, jwt_encode):
    fake_id = str(uuid.uuid4())
    token = jwt_encode(fake_id, role="admin")
    payload = {"title": "Orphan", "artist": "Artist"}
    resp = await client.post(
        f"/v1/venues/{fake_id}/songs",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    # Token venue == fake_id but venue doesn't exist in DB => 404
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.anyio
async def test_create_song_unauthorized_no_token(client, db, venue_with_songs):
    venue_id, songs = venue_with_songs
    payload = {"title": "No Auth", "artist": "Artist"}
    resp = await client.post(
        f"/v1/venues/{venue_id}/songs",
        json=payload,
    )
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# =====================================================================
# 7. UPDATE
# =====================================================================

@pytest.mark.anyio
async def test_update_song_admin(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="admin")
    song = songs[0]
    payload = {"title": "Updated Title"}
    resp = await client.put(
        f"/v1/venues/{venue_id}/songs/{song.id}",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["title"] == "Updated Title"
    assert data["artist"] == song.artist  # unchanged


@pytest.mark.anyio
async def test_update_song_kj(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="kj")
    song = songs[0]
    payload = {"genre": "Updated Genre"}
    resp = await client.put(
        f"/v1/venues/{venue_id}/songs/{song.id}",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_200_OK


@pytest.mark.anyio
async def test_update_song_singer_forbidden(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="singer")
    song = songs[0]
    payload = {"title": "Singer Hack"}
    resp = await client.put(
        f"/v1/venues/{venue_id}/songs/{song.id}",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_update_song_not_found(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="admin")
    payload = {"title": "Ghost"}
    resp = await client.put(
        f"/v1/venues/{venue_id}/songs/{uuid.uuid4()}",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =====================================================================
# 8. DELETE
# =====================================================================

@pytest.mark.anyio
async def test_delete_song_admin(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="admin")
    song = songs[0]
    resp = await client.delete(
        f"/v1/venues/{venue_id}/songs/{song.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT

    # song is soft-deleted -> invisible
    get_resp = await client.get(f"/v1/venues/{venue_id}/songs/{song.id}")
    assert get_resp.status_code == status.HTTP_404_NOT_FOUND

    list_resp = await client.get(f"/v1/venues/{venue_id}/songs")
    assert list_resp.json()["total"] == 3


@pytest.mark.anyio
async def test_delete_song_kj(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="kj")
    song = songs[1]
    resp = await client.delete(
        f"/v1/venues/{venue_id}/songs/{song.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.anyio
async def test_delete_song_singer_forbidden(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="singer")
    song = songs[0]
    resp = await client.delete(
        f"/v1/venues/{venue_id}/songs/{song.id}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.anyio
async def test_delete_song_not_found(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    token = jwt_encode(venue_id, role="admin")
    resp = await client.delete(
        f"/v1/venues/{venue_id}/songs/{uuid.uuid4()}",
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =====================================================================
# 9. VENUE SCOPING
# =====================================================================

@pytest.mark.anyio
async def test_list_songs_different_venue_only_sees_own(client, db, jwt_encode, venue_with_songs):
    # create a separate venue with a song
    venue_id, songs = venue_with_songs
    other_id = str(uuid.uuid4())
    from app.models import Venue as V, Song as S
    db.add(V(id=other_id, name="Other", slug=f"other-{other_id[:8]}"))
    db.add(S(venue_id=other_id, title="Other Song", artist="Other", is_available=1))
    await db.commit()

    # listing the original venue without token should only show original songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs")
    data = resp.json()
    assert data["total"] == 4
    assert not any(i["title"] == "Other Song" for i in data["items"])


# =====================================================================
# 10. EDGE / ADDITIONAL
# =====================================================================

@pytest.mark.anyio
async def test_search_songs_endpoint(client, db, venue_with_songs):
    """Test the dedicated /search endpoint."""
    venue_id, songs = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs/search?q=Queen")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Bohemian Rhapsody"


@pytest.mark.anyio
async def test_list_songs_empty_venue(client, db):
    from app.models import Venue as V
    vid = str(uuid.uuid4())
    db.add(V(id=vid, name="Empty", slug=f"empty-{vid[:8]}"))
    await db.commit()
    resp = await client.get(f"/v1/venues/{vid}/songs")
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.anyio
async def test_create_song_defaults(client, db, jwt_encode):
    venue_id = str(uuid.uuid4())
    from app.models import Venue as V
    db.add(V(id=venue_id, name="Default Venue", slug=f"def-{venue_id[:8]}"))
    await db.commit()

    token = jwt_encode(venue_id, role="admin")
    payload = {"title": "Minimal", "artist": "Min"}
    resp = await client.post(
        f"/v1/venues/{venue_id}/songs",
        json=payload,
        headers=AUTHORIZATION(token),
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["catalog_id"] is None
    assert data["album"] is None
    assert data["is_active"] is True


@pytest.mark.anyio
async def test_list_songs_invalid_decade_format(client, db, venue_with_songs):
    venue_id, _ = venue_with_songs
    resp = await client.get(f"/v1/venues/{venue_id}/songs?decade=abc")
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.anyio
async def test_delete_already_soft_deleted_not_found(client, db, jwt_encode, venue_with_songs):
    venue_id, songs = venue_with_songs
    song = songs[0]
    token = jwt_encode(venue_id, role="admin")
    r1 = await client.delete(
        f"/v1/venues/{venue_id}/songs/{song.id}",
        headers=AUTHORIZATION(token),
    )
    assert r1.status_code == status.HTTP_204_NO_CONTENT
    r2 = await client.delete(
        f"/v1/venues/{venue_id}/songs/{song.id}",
        headers=AUTHORIZATION(token),
    )
    assert r2.status_code == status.HTTP_404_NOT_FOUND
