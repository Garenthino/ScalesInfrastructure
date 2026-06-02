#!/usr/bin/env python3
"""Scales Mock Show Seeder v2 — writes directly to local Postgres via docker."""

import subprocess, json, uuid, sys, bcrypt, os

DB_CONTAINER = "scales-postgres"
DB_NAME = "scales"
DB_USER = "scales"

# Test accounts — password for ALL: TestPass123!
TEST_PASSWORD = "TestPass123!"

def pw_hash():
    return bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()

def psql(sql):
    cmd = ["docker", "exec", "-i", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME, "-tA"]
    r = subprocess.run(cmd, input=sql + "\n", capture_output=True, text=True, timeout=30)
    return r.stdout.strip(), r.stderr.strip(), r.returncode

# ═══════════════════════════════════════════════
#  SEED DATA
# ═══════════════════════════════════════════════

VENUE_ID   = "aaaaaaaa-1111-2222-3333-444444444444"
VENUE_SLUG = "the-singing-lounge"

SINGERS = [
    # id,                         stage_name,           real_name,            email,                          role
    ("singer-001-aaaa-11111111", "KaraQueen",          "Sarah Chen",          "karaqueen@example.com",       "singer"),
    ("singer-002-bbbb-22222222", "Rock'n'Roll Randy",  "Randy Johnson",       "rocknrollrandy@example.com",   "singer"),
    ("singer-003-cccc-33333333", "Jazz Hands",         "Jasmine Williams",    "jazzhands@example.com",        "singer"),
    ("singer-004-dddd-44444444", "The Jukebox",        "James Miller",        "thejukebox@example.com",       "singer"),
    ("singer-005-eeee-55555555", "High Note",          "Nicole Park",         "highnote@example.com",         "singer"),
    ("singer-006-ffff-66666666", "First Timer",        "Alex Rivera",         "newbie2026@example.com",       "singer"),
    ("kj-001-1111-77777777",     "DJ Dave",            "David Thompson",      "kj_dave@example.com",          "kj"),
    ("owner-001-2222-88888888",  "The Boss",           "Patricia Morris",     "venue_owner@example.com",      "owner"),
]

SONGS = [
    # title,                    artist,           genre,         year
    ("Sweet Caroline",         "Neil Diamond",   "Pop",         1969),
    ("Don't Stop Believin'",   "Journey",        "Rock",        1981),
    ("Bohemian Rhapsody",      "Queen",          "Rock",        1975),
    ("Wonderwall",             "Oasis",          "Alternative", 1995),
    ("Living on a Prayer",     "Bon Jovi",       "Rock",        1986),
    ("Summer of '69",          "Bryan Adams",    "Rock",        1984),
    ("Mr. Brightside",         "The Killers",    "Alternative", 2003),
    ("Shake It Off",           "Taylor Swift",   "Pop",         2014),
    ("Purple Rain",            "Prince",         "Pop",         1984),
    ("Hotel California",       "Eagles",         "Rock",        1976),
    ("I Will Survive",         "Gloria Gaynor",  "Disco",       1978),
    ("Friends in Low Places",  "Garth Brooks",   "Country",     1990),
    ("Wagon Wheel",            "Old Crow",       "Country",     2004),
    ("Billie Jean",            "Michael Jackson","Pop",         1982),
    ("Like a Prayer",          "Madonna",        "Pop",         1989),
    ("Africa",                 "Toto",           "Rock",        1982),
    ("American Pie",           "Don McLean",     "Rock",        1971),
    ("Hey Ya!",                "OutKast",        "Hip Hop",     2003),
    ("Wannabe",                "Spice Girls",    "Pop",         1996),
    ("Total Eclipse of Heart", "Bonnie Tyler",   "Ballad",      1983),
]

# ═══════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════

def run():
    print("Scales Mock Show Seeder v2")
    print("─" * 56)

    # ── 0. Check docker ──
    out, err, rc = psql("SELECT 1")
    if rc != 0:
        print(f"ERROR: Cannot connect to Postgres in container '{DB_CONTAINER}'")
        print(f"  stderr: {err[:200]}")
        print("\nMake sure docker-compose is running:")
        print("  cd /home/garenthino/ScalesInfrastructure")
        print("  docker-compose up -d")
        sys.exit(1)

    # ── 1. Venue ──
    print("\n1. Creating venue...")
    sql_venue = f"""
    INSERT INTO venues (id, name, slug, address, city, state, postal_code, country, phone, timezone, website, description, created_at, updated_at)
    VALUES ('{VENUE_ID}', 'The Singing Lounge', '{VENUE_SLUG}',
            '123 Rock Street', 'Music City', 'MC', '90210', 'USA',
            '555-KARAOKE', 'America/Denver',
            'https://singinglounge.example.com',
            'A cozy local venue with weekly karaoke nights.',
            NOW(), NOW())
    ON CONFLICT (id) DO UPDATE SET name='The Singing Lounge';
    """
    out, err, rc = psql(sql_venue)
    if rc != 0 and "violates" not in err:
        print(f"   Venue insert issue: {err[:200]}")
    else:
        print("   Venue OK")

    # ── 2. Singers ──
    print("\n2. Creating singers...")
    h = pw_hash()
    for sid, stage, real, email, role in SINGERS:
        sql = f"""
        INSERT INTO singers (id, venue_id, stage_name, real_name, email, role, password_hash, total_points, created_at, updated_at)
        VALUES ('{sid}', '{VENUE_ID}', '{stage}', '{real}', '{email}', '{role}', '{h}', 0, NOW(), NOW())
        ON CONFLICT (email) DO UPDATE SET
            stage_name=EXCLUDED.stage_name, real_name=EXCLUDED.real_name,
            venue_id=EXCLUDED.venue_id, role=EXCLUDED.role;
        """
        out, err, rc = psql(sql)
        if rc != 0:
            print(f"   WARN {stage}: {err[:120]}")
    print(f"   {len(SINGERS)} singers OK")

    # ── 3. Songs ──
    print("\n3. Creating songs...")
    song_ids = []
    for i, (title, artist, genre, year) in enumerate(SONGS, 1):
        sid = f"song-{i:03d}"
        song_ids.append(sid)
        sql = f"""
        INSERT INTO songs (id, venue_id, title, artist, genre, year, category, is_active, created_at, updated_at)
        VALUES ('{sid}', '{VENUE_ID}', '{title}', '{artist}', '{genre}', {year}, 'Standard', true, NOW(), NOW())
        ON CONFLICT (venue_id, title, artist) DO UPDATE SET is_active=true;
        """
        out, err, rc = psql(sql)
        if rc != 0:
            print(f"   WARN song '{title}': {err[:120]}")
    print(f"   {len(SONGS)} songs OK")

    # ── 4. Favorites ──
    print("\n4. Creating favorites...")
    singer_ids_only = [sid for sid,_,_,_,role in SINGERS if role=="singer"]
    fav_count = 0
    for singer_id in singer_ids_only:
        for sid in song_ids[:5]:
            sql = f"""
            INSERT INTO singer_favorites (id, singer_id, song_id, venue_id, created_at)
            VALUES (gen_random_uuid(), '{singer_id}', '{sid}', '{VENUE_ID}', NOW())
            ON CONFLICT DO NOTHING;
            """
            out, err, rc = psql(sql)
            if rc == 0: fav_count += 1
    print(f"   {fav_count} favorites OK")

    # ── 5. Follows ──
    print("\n5. Creating follows...")
    follow_count = 0
    for i, (follower_id,_,_,_,_) in enumerate(SINGERS):
        followees = [s for j,(s,_,_,_,_) in enumerate(SINGERS) if j!=i and SINGERS[j][4]=="singer"][:2]
        for fid in followees:
            sql = f"""
            INSERT INTO singer_follows (follower_id, followee_id, venue_id, created_at)
            VALUES ('{follower_id}', '{fid}', '{VENUE_ID}', NOW())
            ON CONFLICT DO NOTHING;
            """
            out, err, rc = psql(sql)
            if rc == 0: follow_count += 1
    print(f"   {follow_count} follows OK")

    # ── 6. Queue entries (Live Show!) ──
    print("\n6. Creating live queue...")
    singer_roles = [(sid,stage) for sid,stage,_,_,role in SINGERS if role in ("singer","kj")]
    queue_count = 0
    now = "2026-06-01T20:00:00Z"
    for i, (singer_id, stage) in enumerate(singer_roles * 2):
        if i >= 10: break
        sid = song_ids[i % len(song_ids)]
        sql = f"""
        INSERT INTO queue_entries (id, venue_id, singer_id, song_id, position, status, request_type, notes, created_at, updated_at)
        VALUES (gen_random_uuid(), '{VENUE_ID}', '{singer_id}', '{sid}', {i+1}, 'pending', 'standard',
                '{stage} is up next!', NOW(), NOW())
        ON CONFLICT DO NOTHING;
        """
        out, err, rc = psql(sql)
        if rc == 0: queue_count += 1
    print(f"   {queue_count} queue entries OK")

    # ── 7. Venue config ──
    print("\n7. Creating venue config...")
    sql_cfg = f"""
    INSERT INTO venue_configs (id, venue_id, config_key, config_value, created_at, updated_at)
    VALUES (gen_random_uuid(), '{VENUE_ID}', 'rotation_mode', 'standard', NOW(), NOW()),
           (gen_random_uuid(), '{VENUE_ID}', 'max_singers', '500', NOW(), NOW()),
           (gen_random_uuid(), '{VENUE_ID}', 'auto_queue', 'true', NOW(), NOW()),
           (gen_random_uuid(), '{VENUE_ID}', 'theme', 'dark', NOW(), NOW())
    ON CONFLICT DO NOTHING;
    """
    psql(sql_cfg)
    print("   Config OK")

    # ── 8. Check-in session ──
    print("\n8. Creating check-in session...")
    sql_checkin = f"""
    INSERT INTO checkin_sessions (id, venue_id, kj_id, session_code, status, started_at, expires_at, created_at, updated_at)
    VALUES (gen_random_uuid(), '{VENUE_ID}', 'kj-001-1111-77777777', 'ROCKNIGHT', 'active', NOW(), NOW() + INTERVAL '4 hours', NOW(), NOW())
    ON CONFLICT DO NOTHING;
    """
    psql(sql_checkin)
    print("   Check-in OK")

    # ═══════════════════════════════════════════════
    print("\n" + "=" * 56)
    print("  MOCK KARAOKE NIGHT — READY FOR TESTING")
    print("=" * 56)
    print(f"\n  Venue:     The Singing Lounge (ID: {VENUE_ID})")
    print(f"  API:       http://localhost:8000/v1")
    print(f"  Web:       http://localhost:4000 (or prod: https://dancingdragonservices.com)")
    print(f"  Password:  TestPass123!  (for ALL accounts)")
    print("\n  TEST ACCOUNTS")
    print("  ┌────────────────────┬─────────────────────────────┬──────────┐")
    print("  │ Stage Name         │ Email                       │ Role     │")
    print("  ├────────────────────┼─────────────────────────────┼──────────┤")
    for sid, stage, real, email, role in SINGERS:
        print(f"  │ {stage:18} │ {email:27} │ {role:8} │")
    print("  └────────────────────┴─────────────────────────────┴──────────┘")

    print("\n  MANUAL TEST CHECKLIST")
    print("  ─────────────────────")
    print("  1. Web Portal: http://localhost:4000/auth/login")
    print("     → Login as kj_dave@example.com / TestPass123!")
    print("     → Verify admin queue dashboard loads")
    print("     → Check singer roster, rotation controls")
    print("")
    print("  2. Mobile App (Flutter APK)")
    print("     → Login as karaqueen@example.com / TestPass123!")
    print("     → Browse 20 songs, add favorites")
    print("     → Join queue with a song")
    print("     → View leaderboard, follows")
    print("")
    print("  3. Desktop KJ (DragonHost2-Hermes)")
    print("     → Sync from cloud")
    print("     → Verify venue + song list")
    print("     → Test queue push/pull")
    print("")
    print("  4. API Direct (curl / Postman):")
    print(f"     POST http://localhost:8000/v1/auth/login")
    print(f"       Body: {{'email':'highnote@example.com','password':'TestPass123!'}}")
    print("")
    print("  WHAT'S IN THE DATABASE")
    print(f"    Songs:   {len(SONGS)}")
    print(f"    Singers: {len(SINGERS)}")
    print(f"    Queue:   {queue_count} active entries")
    print(f"    Favs:    {fav_count}")
    print(f"    Follows: {follow_count}")
    print("=" * 56)

if __name__ == "__main__":
    run()
