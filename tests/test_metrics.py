"""Metrics and health endpoint tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health_returns_structured_response(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "version" in data
    assert "timestamp" in data
    assert "checks" in data
    assert "database" in data["checks"]
    assert "redis" in data["checks"]
    # In test env the real engine may not be reachable (uses SQLite override)
    # We assert structured response, not live connectivity.
    assert data["checks"]["database"] in {"ok", "error", "degraded"} or data["checks"]["database"].startswith("error:")
    assert data["checks"]["redis"] in {"ok", "error", "unconfigured"} or data["checks"]["redis"].startswith("error:")


@pytest.mark.anyio
async def test_metrics_returns_valid_prometheus(client: AsyncClient):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")
    body = r.text
    assert "requests_total" in body or "request_duration_seconds" in body or "active_connections" in body
    assert "# HELP" in body
    assert "# TYPE" in body
