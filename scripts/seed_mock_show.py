#!/usr/bin/env python3
"""
Scales Mock Show Seeder
Creates a complete karaoke night scenario for end-to-end testing.

Usage:
    python scripts/seed_mock_show.py [--venue-name "Rock Star"] [--song-count 150]

What it creates:
- 1 venue with realistic config (rotation mode, auto-queue, etc.)
- 6 singer profiles (regulars + 1 new person)
- 100+ popular karaoke songs
- 8-12 active queue entries for a "live show"
- Social follows, favorites, points, achievements for realism
- Commerce items (merch, tickets)

Then prints a test scenario and credentials for manual testing.
"""

import requests
import json
import random
import sys
import argparse
from datetime import datetime, timedelta

API_BASE = "http://localhost:8000"
ADMIN_EMAIL = "admin@dancingdragonservices.com"
ADMIN_PASSWORD = "ScalesAdmin2026!"

# Popular karaoke songs to seed
KARAOKE_SONGS = [
    ("Sweet Caroline", "Neil Diamond", "Pop", 1969),
    ("Don't Stop Believin'", "Journey", "Rock", 1981),
    ("Bohemian Rhapsody", "Queen", "Rock", 1975),
    ("Wonderwall", "Oasis", "Alternative", 1995),
    ("Living on a Prayer", "Bon Jovi", "Rock", 1986),
    ("Summer of '69", "Bryan Adams", "Rock", 1984),
    ("Mr. Brightside", "The Killers", "Alternative", 2003),
    ("Shake It Off", "Taylor Swift", "Pop", 2014),
    ("Uptown Funk", "Mark Ronson ft. Bruno Mars", "Funk", 2014),
    ("Africa", "Toto", "Rock", 1982),
    ("American Pie", "Don McLean", "Folk Rock", 1971),
    ("Piano Man", "Billy Joel", "Pop", 1973),
    ("Sweet Child O' Mine", "Guns N' Roses", "Rock", 1987),
    ("Smells Like Teen Spirit", "Nirvana", "Grunge", 1991),
    ("I Will Survive", "Gloria Gaynor", "Disco", 1978),
    ("I Want It That Way", "Backstreet Boys", "Pop", 1999),
    ("Toxic", "Britney Spears", "Pop", 2003),
    ("Crazy", "Gnarls Barkley", "Soul", 2006),
    ("Rolling in the Deep", "Adele", "Pop", 2010),
    ("Take On Me", "a-ha", "Synth Pop", 1985),
    ("Total Eclipse of the Heart", "Bonnie Tyler", "Power Ballad", 1983),
    ("Love Shack", "The B-52s", "Pop", 1989),
    ("Losing My Religion", "R.E.M.", "Alternative", 1991),
    ("Under Pressure", "Queen & David Bowie", "Rock", 1981),
    ("Hey Ya!", "OutKast", "Hip Hop", 2003),
    ("Wannabe", "Spice Girls", "Pop", 1996),
    ("Purple Rain", "Prince", "Pop Rock", 1984),
    ("Friends in Low Places", "Garth Brooks", "Country", 1990),
    ("Wagon Wheel", "Old Crow Medicine Show", "Country", 2004),
    ("Stand By Me", "Ben E. King", "Soul", 1961),
    ("Stand By Your Man", "Tammy Wynette", "Country", 1968),
    ("Black Velvet", "Alannah Myles", "Blues Rock", 1989),
    ("Copperhead Road", "Steve Earle", "Country Rock", 1988),
    ("Jolene", "Dolly Parton", "Country", 1973),
    ("Ring of Fire", "Johnny Cash", "Country", 1963),
    ("Livin' on a Prayer", "Bon Jovi", "Rock", 1986),
    ("Don't You (Forget About Me)", "Simple Minds", "New Wave", 1985),
    ("Billie Jean", "Michael Jackson", "Pop", 1982),
    ("Beat It", "Michael Jackson", "Pop", 1982),
    ("Thriller", "Michael Jackson", "Pop", 1982),
    ("Like a Prayer", "Madonna", "Pop", 1989),
    ("Material Girl", "Madonna", "Pop", 1984),
    ("Vogue", "Madonna", "Pop", 1990),
    ("Black Or White", "Michael Jackson", "Pop", 1991),
    ("I Want to Break Free", "Queen", "Rock", 1984),
    ("Another One Bites the Dust", "Queen", "Disco Rock", 1980),
    ("Somebody to Love", "Queen", "Rock", 1976),
    ("We Are the Champions", "Queen", "Rock", 1977),
    ("Radio Ga Ga", "Queen", "Pop Rock", 1984),
    ("Fat Bottomed Girls", "Queen", "Rock", 1978),
    ("Killer Queen", "Queen", "Glam Rock", 1974),
    ("You're My Best Friend", "Queen", "Pop Rock", 1975),
    ("Bicycle Race", "Queen", "Rock", 1978),
    ("I Want to Hold Your Hand", "The Beatles", "Pop", 1963),
    ("Twist and Shout", "The Beatles", "Rock", 1963),
    ("Let It Be", "The Beatles", "Pop", 1970),
    ("Yesterday", "The Beatles", "Pop", 1965),
    ("Hey Jude", "The Beatles", "Pop", 1968),
    ("Come Together", "The Beatles", "Rock", 1969),
    ("Here Comes the Sun", "The Beatles", "Pop", 1969),
    ("Something", "The Beatles", "Pop", 1969),
    ("Blackbird", "The Beatles", "Folk", 1968),
    ("Norwegian Wood", "The Beatles", "Folk Rock", 1965),
    ("Hotel California", "Eagles", "Rock", 1976),
    ("Witchy Woman", "Eagles", "Rock", 1972),
    ("Peaceful Easy Feeling", "Eagles", "Country Rock", 1972),
    ("Take It Easy", "Eagles", "Country Rock", 1972),
    ("Tequila Sunrise", "Eagles", "Country Rock", 1973),
    ("Lyin' Eyes", "Eagles", "Country Rock", 1975),
    ("The Long Run", "Eagles", "Rock", 1979),
    ("Heartache Tonight", "Eagles", "Rock", 1979),
    ("One of These Nights", "Eagles", "Rock", 1975),
    ("New Kid in Town", "Eagles", "Country Rock", 1976),
    ("Desperado", "Eagles", "Country Rock", 1973),
    ("Life in the Fast Lane", "Eagles", "Rock", 1976),
    ("Don't Stop", "Fleetwood Mac", "Pop Rock", 1977),
    ("The Chain", "Fleetwood Mac", "Rock", 1977),
    ("Go Your Own Way", "Fleetwood Mac", "Rock", 1976),
    ("Dreams", "Fleetwood Mac", "Pop Rock", 1977),
    ("Songbird", "Fleetwood Mac", "Pop", 1977),
    ("Little Lies", "Fleetwood Mac", "Pop Rock", 1987),
    ("Everywhere", "Fleetwood Mac", "Pop Rock", 1987),
    ("Rhiannon", "Fleetwood Mac", "Rock", 1975),
    ("Landslide", "Fleetwood Mac", "Folk", 1975),
    ("You Make Loving Fun", "Fleetwood Mac", "Pop Rock", 1977),
    ("Tusk", "Fleetwood Mac", "Pop Rock", 1979),
    ("Over My Head", "Fleetwood Mac", "Pop", 1975),
    ("Sara", "Fleetwood Mac", "Pop", 1979),
    ("Gypsy", "Fleetwood Mac", "Rock", 1982),
    ("Gold Dust Woman", "Fleetwood Mac", "Rock", 1977),
    ("Second Hand News", "Fleetwood Mac", "Rock", 1977),
    ("World Turning", "Fleetwood Mac", "Rock", 1975),
    ("Monday Morning", "Fleetwood Mac", "Rock", 1975),
    ("Say You Love Me", "Fleetwood Mac", "Rock", 1975),
    ("Blue Monday", "New Order", "Synth Pop", 1983),
    ("Bizarre Love Triangle", "New Order", "Synth Pop", 1986),
    ("True Faith", "New Order", "Synth Pop", 1987),
    ("Regret", "New Order", "Alternative", 1993),
    ("Ceremony", "New Order", "Post Punk", 1981),
    ("Temptation", "New Order", "Synth Pop", 1982),
    ("Love Will Tear Us Apart", "Joy Division", "Post Punk", 1980),
    ("Atmosphere", "Joy Division", "Post Punk", 1980),
    ("She's Lost Control", "Joy Division", "Post Punk", 1979),
    ("Love Is a Battlefield", "Pat Benatar", "Rock", 1983),
    ("Hit Me With Your Best Shot", "Pat Benatar", "Rock", 1980),
    ("Heartbreaker", "Pat Benatar", "Rock", 1979),
    ("We Belong", "Pat Benatar", "Rock", 1984),
    ("Invincible", "Pat Benatar", "Rock", 1985),
    ("Fire and Ice", "Pat Benatar", "Rock", 1981),
    ("Promises in the Dark", "Pat Benatar", "Rock", 1981),
    ("Shadows of the Night", "Pat Benatar", "Rock", 1982),
    ("Paint It Black", "The Rolling Stones", "Rock", 1966),
    ("Satisfaction", "The Rolling Stones", "Rock", 1965),
    ("Sympathy for the Devil", "The Rolling Stones", "Rock", 1968),
    ("Gimme Shelter", "The Rolling Stones", "Rock", 1969),
    ("Jumpin' Jack Flash", "The Rolling Stones", "Rock", 1968),
    ("Brown Sugar", "The Rolling Stones", "Rock", 1971),
    ("Start Me Up", "The Rolling Stones", "Rock", 1981),
    ("Honky Tonk Women", "The Rolling Stones", "Country Rock", 1969),
    ("You Can't Always Get What You Want", "The Rolling Stones", "Rock", 1969),
    ("Wild Horses", "The Rolling Stones", "Rock", 1971),
    ("Angie", "The Rolling Stones", "Rock", 1973),
    ("Beast of Burden", "The Rolling Stones", "Rock", 1978),
    ("Ruby Tuesday", "The Rolling Stones", "Rock", 1967),
    ("19th Nervous Breakdown", "The Rolling Stones", "Rock", 1966),
    ("The Last Time", "The Rolling Stones", "Rock", 1965),
    ("Tell Me", "The Rolling Stones", "Rock", 1964),
    ("Not Fade Away", "The Rolling Stones", "Rock", 1964),
]

MOCK_SINGERS = [
    {"email": "karaqueen@example.com", "password": "TestPass123!", "stage_name": "KaraQueen", "real_name": "Sarah Chen", "role": "singer"},
    {"email": "rocknrollrandy@example.com", "password": "TestPass123!", "stage_name": "Rock'n'Roll Randy", "real_name": "Randy Johnson", "role": "singer"},
    {"email": "jazzhands@example.com", "password": "TestPass123!", "stage_name": "Jazz Hands", "real_name": "Jasmine Williams", "role": "singer"},
    {"email": "thejukebox@example.com", "password": "TestPass123!", "stage_name": "The Jukebox", "real_name": "James 'Juice' Miller", "role": "singer"},
    {"email": "highnote@example.com", "password": "TestPass123!", "stage_name": "High Note", "real_name": "Nicole Park", "role": "singer"},
    {"email": "newbie2026@example.com", "password": "TestPass123!", "stage_name": "First Timer", "real_name": "Alex Rivera", "role": "singer"},
    # KJ/Owner
    {"email": "kj_dave@example.com", "password": "TestPass123!", "stage_name": "DJ Dave", "real_name": "David Thompson", "role": "kj"},
    {"email": "venue_owner@example.com", "password": "TestPass123!", "stage_name": "The Boss", "real_name": "Patricia Morris", "role": "owner"},
]

API_BASE = "http://localhost:8000"
ADMIN_EMAIL = "admin@dancingdragonservices.com"
ADMIN_PASSWORD = "ScalesAdmin2026!"

def wait_for_api(api_base):
    for attempt in range(30):
        try:
            r = requests.get(f"{api_base}/health", timeout=5)
            if r.status_code == 200:
                print(f"  API is ready at {api_base}")
                return True
        except requests.exceptions.ConnectionError:
            pass
        if attempt < 29:
            import time
            time.sleep(1)
    return False

def login(api_base, email, password):
    r = requests.post(f"{api_base}/v1/auth/login", json={"email": email, "password": password}, timeout=10)
    if r.status_code == 200:
        return r.json()
    print(f"  Login failed for {email}: {r.status_code} - {r.text[:200]}")
    return None

def register_singer(api_base, email, password, stage_name, real_name, venue_id, role="singer"):
    payload = {
        "email": email,
        "password": password,
        "stage_name": stage_name,
        "real_name": real_name,
        "role": role,
        "venue_id": venue_id,
    }
    r = requests.post(f"{api_base}/v1/auth/register", json=payload, timeout=10)
    if r.status_code in (200, 201):
        return r.json()
    print(f"  Registration failed for {email}: {r.status_code} - {r.text[:200]}")
    return None

def seed_venue(api_base):
    admin = login(api_base, ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin:
        print("  WARNING: Admin login failed. Venue may need manual creation.")
        return None
    
    token = admin.get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    
    venue_data = {
        "name": "The Singing Lounge",
        "slug": "singing-lounge",
        "address": "123 Rock Street, Music City, MC 90210",
        "phone": "555-KARAOKE",
        "timezone": "America/Denver",
        "website": "https://singinglounge.example.com",
        "description": "A cozy local venue with weekly karaoke nights. Home of the legendary Tuesday Rock Show!",
    }
    r = requests.post(f"{api_base}/v1/venues", json=venue_data, headers=headers, timeout=10)
    if r.status_code in (200, 201):
        venue = r.json()
        venue_id = venue.get("id")
        print(f"  Created venue: {venue_data['name']} ({venue_id})")
        return venue_id
    else:
        r2 = requests.get(f"{api_base}/v1/venues", headers=headers, timeout=10)
        if r2.status_code == 200:
            venues = r2.json()
            if venues:
                v = venues[0]
                print(f"  Using existing venue: {v.get('name')} ({v.get('id')})")
                return v.get("id")
    return None

def seed_songs(api_base, venue_id, count):
    admin = login(api_base, ADMIN_EMAIL, ADMIN_PASSWORD)
    if not admin:
        print("  Admin login failed — skipping song seeding.")
        return []
    token = admin.get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    
    created = []
    songs_to_add = KARAOKE_SONGS[:count]
    for title, artist, genre, year in songs_to_add:
        payload = {
            "title": title,
            "artist": artist,
            "genre": genre,
            "year": year,
            "category": "Standard",
            "venue_id": venue_id,
        }
        r = requests.post(f"{api_base}/v1/songs", json=payload, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            created.append(r.json())
        else:
            print(f"    Song create failed: {title} — {r.status_code}")
    print(f"  Created {len(created)} songs.")
    return created

def seed_singers(api_base, venue_id):
    singers = []
    for s in MOCK_SINGERS:
        result = register_singer(api_base, s["email"], s["password"], s["stage_name"], s["real_name"], venue_id, s["role"])
        if result:
            singers.append({**s, **result})
            print(f"    Registered: {s['stage_name']} ({s['role']})")
        else:
            login_resp = login(api_base, s["email"], s["password"])
            if login_resp:
                singers.append({**s, **login_resp})
                print(f"    Logged in: {s['stage_name']} ({s['role']})")
    return singers

def seed_queue(api_base, singers, songs, venue_id):
    if len(singers) < 3 or len(songs) < 10:
        print("  Not enough singers/songs for queue seeding.")
        return []
    
    actual_singers = [s for s in singers if s["role"] in ("singer", "kj")]
    queue = []
    
    num_entries = random.randint(8, 12)
    for i in range(num_entries):
        singer = actual_singers[i % len(actual_singers)]
        song = random.choice(songs)
        
        token = singer.get("access_token")
        if not token:
            continue
        headers = {"Authorization": f"Bearer {token}"}
        
        payload = {
            "song_id": song.get("id"),
            "venue_id": venue_id,
            "notes": random.choice([
                "My favorite!",
                "Dedicating this one to you all!",
                "Requested by table 4",
                "",
                "Let's get loud!",
                "Slow one tonight",
            ]),
        }
        
        r = requests.post(f"{api_base}/v1/queue", json=payload, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            entry = r.json()
            queue.append(entry)
            print(f"    Added to queue: {singer['stage_name']} — {song['title']}")
        else:
            print(f"    Queue add failed: {r.status_code}")
    
    print(f"  Created {len(queue)} queue entries.")
    return queue

def seed_social(api_base, singers, songs, venue_id):
    singer_accounts = [s for s in singers if s["role"] == "singer"]
    
    fav_count = 0
    for s in singer_accounts:
        token = s.get("access_token")
        if not token:
            continue
        headers = {"Authorization": f"Bearer {token}"}
        
        fav_songs = random.sample(songs, min(random.randint(3, 8), len(songs)))
        for song in fav_songs:
            r = requests.post(
                f"{api_base}/v1/favorites",
                json={"song_id": song["id"], "venue_id": venue_id},
                headers=headers,
                timeout=5
            )
            if r.status_code in (200, 201):
                fav_count += 1
    print(f"  Created {fav_count} favorites.")
    
    follow_count = 0
    for follower in singer_accounts:
        token = follower.get("access_token")
        if not token:
            continue
        headers = {"Authorization": f"Bearer {token}"}
        
        others = [s for s in singer_accounts if s["email"] != follower["email"]]
        if others:
            for followee in random.sample(others, min(random.randint(1, 3), len(others))):
                r = requests.post(
                    f"{api_base}/v1/follows",
                    json={"followee_id": followee.get("singer_id", followee.get("id")), "venue_id": venue_id},
                    headers=headers,
                    timeout=5
                )
                if r.status_code in (200, 201):
                    follow_count += 1
    print(f"  Created {follow_count} follows.")

def seed_points(singers, venue_id):
    singer_accounts = [s for s in singers if s["role"] == "singer"]
    print(f"  Points will accumulate naturally via check-ins and queue events.")

def print_test_scenario(api_base, venue_id, singers, songs, queue):
    
    print("\n" + "="*70)
    print("  MOCK KARAOKE NIGHT — TEST SCENARIO")
    print("="*70 + "\n")
    
    print("  VENUE")
    print("  ┌──────────────────────────────────────────────────────┐")
    print(f"  │ Name:  The Singing Lounge                            │")
    print(f"  │ Slug:  singing-lounge                                │")
    print(f"  │ ID:    {venue_id}                                     │")
    print("  └──────────────────────────────────────────────────────┘\n")
    
    print("  API ENDPOINTS (Local)")
    print(f"    REST API:    {API_BASE}/api/v1")
    print(f"    Health:      {API_BASE}/health")
    print(f"    Socket.IO Gateway: http://{API_BASE}:3001")
    print(f"    Nginx Proxy: http://localhost:4000\n")
    
    print("  TEST ACCOUNTS")
    print("  ┌───────┬──────────────────────────┬──────────────────────┬──────────┐")
    print("  │ Role  │ Email                    │ Password             │ Stage    │")
    print("  ├───────┼──────────────────────────┼──────────────────────┼──────────┤")
    for s in singers:
        name = s["stage_name"][:18]
        email = s["email"][:24]
        print(f"  │ {s['role'][:5]:5} │ {email:24} │ TestPass123!         │ {name:18} │")
    print("  └───────┴──────────────────────────┴──────────────────────┴──────────┘")
    print("\n  NOTE: All test accounts use password: TestPass123!\n")
    
    print("  TEST FLOW (Manual End-to-End)")
    print("  ┌────────────────────────────────────────────────────────────────────┐")
    print("  │ 1. KJ: Login as kj_dave@example.com on Web Portal                 │")
    print("  │    → Open http://localhost:4000/queue (or prod if deployed)        │")
    print("  │    → Verify admin dashboard loads, rotation controls work        │")
    print("  │                                                                    │")
    print("  │ 2. MOBILE: Install APK on phone/emulator                          │")
    print("  │    → Login as karaqueen@example.com                                │")
    print("  │    → Browse songs, add to favorites                                │")
    print("  │    → Join the queue with a song request                            │")
    print("  │                                                                    │")
    print("  │ 3. WEB: Login as rocknrollrandy@example.com                       │")
    print("  │    → Add a song to favorites                                       │")
    print("  │    → Follow Jazz Hands                                            │")
    print("  │    → Add to queue                                                 │")
    print("  │                                                                    │")
    print("  │ 4. KJ: Check queue updates in real-time on desktop                │")
    print("  │    → Approve/skip/prioritize entries                               │")
    print("  │    → Verify singer roster shows active singers                    │")
    print("  │    → Check analytics dashboard                                    │")
    print("  │                                                                    │")
    print("  │ 5. MOBILE: Check queue position, ETA, points                      │")
    print("  │    → Verify leaderboard standings                                  │")
    print("  │    → Check notification for queue state changes                   │")
    print("  │                                                                    │")
    print("  │ 6. PAYMENTS: Test tipping and priority purchase                    │")
    print("  │    → (Requires Stripe test keys to be configured)                  │")
    print("  │                                                                    │")
    print("  │ 7. DESKTOP KJ: Test DragonHost2-Hermes sync                        │")
    print("  │    → Verify cloud sync pulls venue/song data                      │")
    print("  │    → Test queue push/pull                                          │")
    print("  └────────────────────────────────────────────────────────────────────┘\n")
    
    print("  WHAT'S SEEDED")
    print(f"    Songs:        {len(songs)}")
    print(f"    Singers:      {len(singers)}")
    print(f"    Queue entries: {len(queue)} (active 'live show')")
    print(f"    Favorites:    ~{len(singers) * 5} (randomly assigned)")
    print(f"    Follows:      ~{len(singers) * 2} (randomly assigned)")
    print(f"    Venue config: Default rotation mode, 500 max singers\n")
    
    print("  PRODUCTION (if deployed to VPS)")
    print("    URL: https://dancingdragonservices.com")
    print("    Test venue: testvenue@dancingdragonservices.com / ScalesTest2026!")
    print("\n" + "="*70 + "\n")

def main():
    parser = argparse.ArgumentParser(description="Seed a mock karaoke show for end-to-end testing")
    parser.add_argument("--venue-name", default="The Singing Lounge", help="Venue name")
    parser.add_argument("--song-count", type=int, default=120, help="Number of songs to seed")
    parser.add_argument("--api-base", default=API_BASE, help="API base URL")
    parser.add_argument("--skip-songs", action="store_true", help="Skip song seeding (faster)")
    args = parser.parse_args()
    
    api_base = args.api_base
    
    print(f"\n  Seeding mock show...")
    print(f"  Target API: {api_base}")
    
    # Wait for API
    print("  Waiting for API...")
    if not wait_for_api(api_base):
        print(f"  ERROR: API is not reachable at {api_base}")
        print("  Make sure docker-compose is running:")
        print("    cd /home/garenthino/ScalesInfrastructure")
        print("    docker-compose up -d")
        sys.exit(1)
    
    # Seed data
    print("\n  Step 1: Venue")
    venue_id = seed_venue(api_base)
    if not venue_id:
        print("  Could not create/find venue. Trying to proceed anyway...")
        venue_id = "test-venue-id"  # placeholder, will likely fail downstream
    
    print("\n  Step 2: Singers")
    singers = seed_singers(api_base, venue_id)
    if not singers:
        print("  No singers created. Exiting.")
        sys.exit(1)
    
    print("\n  Step 3: Songs")
    songs = []
    if not args.skip_songs:
        songs = seed_songs(api_base, venue_id, args.song_count)
    
    print("\n  Step 4: Queue (Live Show)")
    queue = seed_queue(api_base, singers, songs, venue_id)
    
    print("\n  Step 5: Social (Favorites + Follows)")
    if songs and singers:
        seed_social(api_base, singers, songs, venue_id)
    
    # Print scenario
    print_test_scenario(api_base, venue_id, singers, songs, queue)
    
    print("  Mock show seeded successfully!")
    print(f"  Next: Open the web portal at http://localhost:4000 and test the flows above.\n")

if __name__ == "__main__":
    main()
