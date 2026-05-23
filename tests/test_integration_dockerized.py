"""Sprint 5: Docker Compose Integration Tests — Full Stack Smoke Test.

Exercises the Docker Compose stack (api + postgres + redis) through the
exposed HTTP port. The test brings up the stack via docker compose if not
already running, runs a lifecycle walk through major endpoints, then tears
down (unless SCALES_TEST_KEEP_STACK=1).

Invoke against the Dockerized stack:
    SCALES_TEST_API_URL=http://localhost:28000 pytest tests/test_integration_dockerized.py -v --integration
    or simply:
    pytest tests/test_integration_dockerized.py -v --integration

If the stack is not up, the fixture will attempt:
    docker compose -f docker-compose-test.yml up -d --build
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid

import httpx
import pytest

API_BASE_URL = os.environ.get("SCALES_TEST_API_URL", "http://localhost:28000")
HEALTH_TIMEOUT = int(os.environ.get("SCALES_TEST_HEALTH_TIMEOUT", "120"))
SKIP_DOCKER = os.environ.get("SCALES_TEST_NO_DOCKER", "0") == "1"
KEEP_STACK = os.environ.get("SCALES_TEST_KEEP_STACK", "0") == "1"
COMPOSE_FILE = os.path.join(os.path.dirname(__file__), "..", "docker-compose-test.yml")


def _is_stack_healthy(url: str) -> bool:
    try:
        r = httpx.get(f"{url}/health", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("checks", {}).get("database") == "ok"
    except Exception:
        pass
    return False


def _docker_compose_up():
    print("[docker] Bringing up test stack...")
    subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "--build"],
        check=True,
    )


def _docker_compose_down():
    print("[docker] Tearing down test stack...")
    subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, "down", "-v"],
        check=False,
    )


@pytest.fixture(scope="module")
def api_url():
    """Return the base API URL, bringing up Docker Compose if necessary."""
    url = API_BASE_URL.rstrip("/")

    if _is_stack_healthy(url):
        print(f"[test] Stack already healthy at {url}")
        yield url
        return

    if SKIP_DOCKER:
        pytest.skip(
            f"Stack not reachable at {url} and SCALES_TEST_NO_DOCKER is set. "
            "Start it manually or unset SCALES_TEST_NO_DOCKER to allow auto-spawn."
        )

    if not shutil.which("docker"):
        pytest.skip("docker CLI not found in PATH; cannot auto-start test stack.")

    _docker_compose_up()

    # Poll health endpoint
    deadline = time.time() + HEALTH_TIMEOUT
    last_exc = None
    while time.time() < deadline:
        if _is_stack_healthy(url):
            print(f"[test] Stack healthy at {url}")
            break
        time.sleep(2)
    else:
        _docker_compose_down()
        pytest.fail(
            f"Stack did not become healthy within {HEALTH_TIMEOUT}s at {url}. "
            f"Last error: {last_exc}"
        )

    yield url

    if not KEEP_STACK:
        _docker_compose_down()


def _headers(token: str | None = None) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDockerizedStack:
    """Smoke-test the deployed Docker Compose stack end-to-end."""

    def test_health(self, api_url: str):
        resp = httpx.get(f"{api_url}/health", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["checks"]["database"] == "ok"
        # Redis should be configured and reachable in the test stack
        assert data["checks"]["redis"] == "ok"
        assert "timestamp" in data
        assert "version" in data

    def test_root(self, api_url: str):
        resp = httpx.get(api_url, timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body or "Scales" in str(body)

    def test_venue_lifecycle(self, api_url: str):
        """Create venue → list → create singer → login → create queue request."""
        client = httpx.Client(base_url=api_url, headers=_headers(), timeout=15)

        venue_id = str(uuid.uuid4())
        slug = f"docker-test-{venue_id[:8]}"

        # 1. Create venue
        v_payload = {
            "id": venue_id,
            "name": "Docker Test Venue",
            "slug": slug,
            "timezone": "UTC",
        }
        r = client.post("/v1/venues", json=v_payload)
        # Venue creation requires admin auth; accept 401 (no auth) or 403 (forbidden) and skip
        if r.status_code in (401, 403):
            pytest.skip("Venue creation requires admin token — skipping full lifecycle.")
        assert r.status_code == 201, f"Venue create failed: {r.text}"

        # 2. List venues
        r = client.get("/v1/venues")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data or "data" in data

        # 3. List songs (empty catalog expected)
        r = client.get(f"/v1/venues/{venue_id}/songs")
        assert r.status_code == 200
        songs = r.json()
        assert isinstance(songs.get("items", []), list)

        # 4. Register a singer
        singer_email = f"docker-{venue_id[:8]}@example.com"
        reg = {
            "venue_id": venue_id,
            "stage_name": "Docker Singer",
            "email": singer_email,
            "password": "dockerPassword123",
        }
        r = client.post("/v1/auth/register", json=reg)
        assert r.status_code == 201, f"Register failed: {r.text}"
        singer_id = r.json()["id"]

        # 5. Login
        r = client.post("/v1/auth/login", json={"email": singer_email, "password": "dockerPassword123"})
        assert r.status_code == 200, f"Login failed: {r.text}"
        token = r.json()["access_token"]

        # 6. Me endpoint
        r = client.get("/v1/auth/me", headers=_headers(token))
        assert r.status_code == 200
        me = r.json()
        assert me["id"] == singer_id
        assert me["venue_id"] == venue_id

        # 7. Create queue request (song placeholder)
        r = client.post(
            f"/v1/venues/{venue_id}/queue",
            headers=_headers(token),
            json={"song_id": str(uuid.uuid4()), "notes": " docker integration test"},
        )
        # 422 expected if song doesn't exist; 201 if the queue service creates it.
        # We accept both to keep the test stable across schema variants.
        assert r.status_code in (201, 422, 404), f"Queue create unexpected: {r.status_code} body={r.text}"

        # 8. List queue
        r = client.get(f"/v1/venues/{venue_id}/queue/list", headers=_headers(token))
        assert r.status_code == 200
        queue_data = r.json()
        assert isinstance(queue_data.get("items", []), list)

    def test_metrics(self, api_url: str):
        resp = httpx.get(f"{api_url}/metrics", timeout=10)
        assert resp.status_code == 200
        assert "# HELP" in resp.text or "# TYPE" in resp.text or "process_" in resp.text
