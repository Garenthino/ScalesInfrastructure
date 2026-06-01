"""Async load-test script for the Scales backend.

Usage (from repo root):
    python3 scripts/load_test.py [--host http://localhost:8000] [--users 50] [--duration 30]

Requires: pip install httpx rich
"""
from __future__ import annotations

import argparse
import asyncio
import random
import time
import uuid
from dataclasses import dataclass

import httpx


@dataclass
class LoadResult:
    endpoint: str
    status: int
    latency_ms: float


class LoadTester:
    def __init__(self, base_url: str, users: int, duration: int):
        self.base_url = base_url.rstrip("/")
        self.users = users
        self.duration = duration
        self.results: list[LoadResult] = []
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()

    async def _worker(self, client: httpx.AsyncClient, user_id: int):
        # Register a singer and login to get a token
        email = f"load{user_id}_{uuid.uuid4().hex[:8]}@test.example"
        stage = f"LoadSinger{user_id}"
        venue_id = self._venue_id

        # Create singer (no auth needed for registration in test env)
        r = await client.post(
            f"{self.base_url}/v1/auth/register",
            json={
                "email": email,
                "password": "LoadTest123!",
                "stage_name": stage,
                "venue_id": venue_id,
            },
            timeout=10,
        )
        if r.status_code not in (200, 201):
            print(f"[User {user_id}] register failed: {r.status_code}")
            return

        token = r.json().get("access_token")
        if not token:
            print(f"[User {user_id}] no token")
            return

        headers = {"Authorization": f"Bearer {token}"}

        endpoints = [
            ("GET", f"/v1/venues/{venue_id}/songs?page=1&per_page=20"),
            ("GET", f"/v1/venues/{venue_id}/singers?page=1&per_page=20"),
            ("GET", "/health"),
            ("GET", f"/v1/venues/{venue_id}/queue/list"),
            ("GET", "/v1/auth/me"),
        ]

        song_ids: list[str] = []
        while not self._stop.is_set():
            method, path = random.choice(endpoints)
            url = f"{self.base_url}{path}"
            start = time.perf_counter()
            try:
                if method == "GET":
                    r = await client.get(url, headers=headers, timeout=10)
                else:
                    r = await client.post(url, headers=headers, timeout=10)
            except Exception as exc:
                print(f"[User {user_id}] {method} {path} error: {exc}")
                await asyncio.sleep(0.5)
                continue
            latency = (time.perf_counter() - start) * 1000
            async with self._lock:
                self.results.append(LoadResult(endpoint=path, status=r.status_code, latency_ms=latency))

            # Collect some song IDs for queue submission
            if path.startswith(f"/v1/venues/{venue_id}/songs") and r.status_code == 200:
                data = r.json()
                for item in data.get("items", [])[:5]:
                    sid = item.get("id")
                    if sid and sid not in song_ids:
                        song_ids.append(sid)

            # Occasionally submit a queue request
            if song_ids and random.random() < 0.15:
                song_id = random.choice(song_ids)
                start = time.perf_counter()
                qr = await client.post(
                    f"{self.base_url}/v1/venues/{venue_id}/queue",
                    headers=headers,
                    json={"song_id": song_id, "notes": "load test"},
                    timeout=10,
                )
                latency = (time.perf_counter() - start) * 1000
                async with self._lock:
                    self.results.append(
                        LoadResult(endpoint=f"/v1/venues/{venue_id}/queue", status=qr.status_code, latency_ms=latency)
                    )

            await asyncio.sleep(random.uniform(0.1, 0.5))

    async def run(self):
        # Create a test venue first via a direct API call (needs an admin token)
        # For local load tests we create a fresh SQLite DB per run; but here we
        # assume the server is running with a seeded DB. We use a pre-known
        # venue if available, otherwise we create one via a temp admin account.
        async with httpx.AsyncClient() as client:
            # Try to create a venue using a temp admin token
            admin_tok = self._mint_admin_token()
            r = await client.post(
                f"{self.base_url}/v1/venues",
                headers={"Authorization": f"Bearer {admin_tok}"},
                json={"name": "LoadTestVenue", "slug": f"load-{uuid.uuid4().hex[:8]}"},
                timeout=10,
            )
            if r.status_code in (200, 201):
                self._venue_id = r.json()["id"]
            else:
                # Fallback: list existing venues and pick the first
                r2 = await client.get(f"{self.base_url}/v1/venues", headers={"Authorization": f"Bearer {admin_tok}"}, timeout=10)
                if r2.status_code == 200 and r2.json().get("items"):
                    self._venue_id = r2.json()["items"][0]["id"]
                else:
                    print("Could not get/create a venue for load test.")
                    return

        print(f"Load test venue_id: {self._venue_id}")
        print(f"Running {self.users} concurrent users for {self.duration}s ...")

        self._stop.clear()
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=200, max_keepalive_connections=50)) as client:
            workers = [asyncio.create_task(self._worker(client, i)) for i in range(self.users)]
            await asyncio.sleep(self.duration)
            self._stop.set()
            await asyncio.gather(*workers, return_exceptions=True)

        self._report()

    def _mint_admin_token(self) -> str:
        # Create a local admin JWT for venue creation
        from jose import jwt
        from datetime import datetime, timezone, timedelta
        secret = "test-jwt-secret-do-not-use-in-production"
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(uuid.uuid4()),
            "venue_id": str(uuid.uuid4()),
            "role": "admin",
            "iat": now,
            "exp": now + timedelta(hours=1),
        }
        return jwt.encode(payload, secret, algorithm="HS256")

    def _report(self):
        total = len(self.results)
        if not total:
            print("No results collected.")
            return
        latencies = [r.latency_ms for r in self.results]
        ok = sum(1 for r in self.results if r.status == 200)
        created = sum(1 for r in self.results if r.status == 201)
        errors = sum(1 for r in self.results if r.status >= 400)
        rate_limited = sum(1 for r in self.results if r.status == 429)
        min_ms = min(latencies)
        max_ms = max(latencies)
        avg_ms = sum(latencies) / total
        p50 = sorted(latencies)[int(total * 0.5)]
        p95 = sorted(latencies)[int(total * 0.95)]
        p99 = sorted(latencies)[int(total * 0.99)]
        rps = total / self.duration

        print("\n=== Load Test Results ===")
        print(f"  Total requests : {total}")
        print(f"  OK (200)       : {ok}")
        print(f"  Created (201)  : {created}")
        print(f"  Errors (4xx+)  : {errors}")
        print(f"  Rate-limited   : {rate_limited}")
        print(f"  Min latency    : {min_ms:.1f} ms")
        print(f"  Avg latency    : {avg_ms:.1f} ms")
        print(f"  Max latency    : {max_ms:.1f} ms")
        print(f"  P50 latency    : {p50:.1f} ms")
        print(f"  P95 latency    : {p95:.1f} ms")
        print(f"  P99 latency    : {p99:.1f} ms")
        print(f"  Req/sec        : {rps:.1f}")
        print("=========================\n")

        # Return non-zero exit code if too many errors or high p95
        if errors / total > 0.05 or p95 > 2000:
            print("FAIL: error rate >5% or P95 > 2000ms")
            raise SystemExit(1)
        print("PASS")


def main():
    parser = argparse.ArgumentParser(description="Scales backend load test")
    parser.add_argument("--host", default="http://localhost:8000", help="Base API URL")
    parser.add_argument("--users", type=int, default=50, help="Concurrent users")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds")
    args = parser.parse_args()

    tester = LoadTester(args.host, args.users, args.duration)
    asyncio.run(tester.run())


if __name__ == "__main__":
    main()
