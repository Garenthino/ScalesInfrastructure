"""Health check endpoint."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.core.config import settings
from app.core.db import engine
from app.schemas import HealthCheck

health_router = APIRouter()


@health_router.get("/health", response_model=HealthCheck)
async def health_check():
    checks = {}
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as exc:
        db_ok = False
        checks["database"] = f"error: {exc}"

    return HealthCheck(
        status="ok" if db_ok else "degraded",
        version=settings.APP_VERSION,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        checks=checks,
    )
