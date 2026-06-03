"""Socket.IO gateway tests (broadcast endpoint + Redis bridge)."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest


GATEWAY_URL = "http://localhost:23001"
BROADCAST_URL = f"{GATEWAY_URL}/broadcast"
HEALTH_URL = f"{GATEWAY_URL}/health"
METRICS_URL = f"{GATEWAY_URL}/metrics"
INTERNAL_SECRET = "test-gateway-secret"


def _gateway_ok() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _gateway_ok(), reason="Socket.IO gateway not running")


@pytest.fixture
async def http_client():
    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=10.0) as c:
        yield c


@pytest.mark.anyio
async def test_gateway_health(http_client: httpx.AsyncClient):
    r = await http_client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "scales-gateway"
    assert data["status"] in ("ok", "degraded")


@pytest.mark.anyio
async def test_gateway_metrics(http_client: httpx.AsyncClient):
    r = await http_client.get("/metrics")
    assert r.status_code == 200
    body = r.text
    assert "scales_gateway_connections_total" in body


@pytest.mark.anyio
async def test_broadcast_rejects_unauthenticated(http_client: httpx.AsyncClient):
    r = await http_client.post("/broadcast", json={"venue_id": "v1", "event_type": "test"})
    assert r.status_code == 403


@pytest.mark.anyio
async def test_broadcast_requires_venue_and_event(http_client: httpx.AsyncClient):
    r = await http_client.post(
        "/broadcast",
        json={},
        headers={"Authorization": f"Bearer {INTERNAL_SECRET}"},
    )
    assert r.status_code == 400
    assert "venue_id and event_type required" in r.json()["error"]


@pytest.mark.anyio
async def test_broadcast_room_success(http_client: httpx.AsyncClient):
    venue_id = str(uuid.uuid4())
    r = await http_client.post(
        "/broadcast",
        json={
            "venue_id": venue_id,
            "event_type": "queue_updated",
            "payload": {"action": "test"},
            "broadcast_mode": "room",
        },
        headers={"Authorization": f"Bearer {INTERNAL_SECRET}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["room"] == f"venue:{venue_id}"


@pytest.mark.anyio
async def test_broadcast_all_mode(http_client: httpx.AsyncClient):
    venue_id = str(uuid.uuid4())
    r = await http_client.post(
        "/broadcast",
        json={
            "venue_id": venue_id,
            "event_type": "ping",
            "payload": {"data": 1},
            "broadcast_mode": "all",
        },
        headers={"Authorization": f"Bearer {INTERNAL_SECRET}"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
