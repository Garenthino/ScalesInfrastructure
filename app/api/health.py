"""Health check and metrics endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text

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
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        db_ok = False
        checks["database"] = f"error: {exc}"

    redis_status = None
    if settings.REDIS_URL:
        try:
            import redis.asyncio as aioredis
            r = aioredis.from_url(settings.REDIS_URL)
            await r.ping()
            redis_status = "ok"
            await r.close()
        except Exception as exc:
            redis_status = f"error: {exc}"
    else:
        redis_status = "unconfigured"

    checks["redis"] = redis_status

    return HealthCheck(
        status="ok" if db_ok else "degraded",
        version=settings.APP_VERSION,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        checks=checks,
    )


@health_router.get("/")
async def root():
    return {
        "message": "Scales API",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs" if settings.DEBUG else None,
    }


@health_router.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )
