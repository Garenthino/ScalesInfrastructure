"""Scales FastAPI backend application core."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.db import engine
from app.api.router import api_router
from app.api.health import health_router
from app.middleware import (
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    RateLimitMiddleware,
    RequestSizeMiddleware,
)
from app.middleware.observability import ObservabilityMiddleware
from app.websockets.queue_ws import router as ws_router

from fastapi.staticfiles import StaticFiles


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    from app.core.notification_service import register_tasks
    register_tasks()
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Scales Karaoke Platform REST API",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Order: request_id -> security_headers -> rate_limit -> observability -> request_size -> CORS
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)
app.add_middleware(RequestSizeMiddleware)

# CORS
if settings.DEBUG:
    origins = ["*"]
else:
    origins = []
    if settings.CORS_ORIGINS_PROD:
        origins = [o.strip() for o in settings.CORS_ORIGINS_PROD.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["Health"])
app.include_router(api_router, prefix="/v1")

# Serve static uploads (avatars etc.)
_UPLOADS_ROOT = os.path.join(os.path.dirname(__file__), "..", "uploads")
app.mount("/uploads", StaticFiles(directory=_UPLOADS_ROOT, check_dir=False), name="uploads")

app.include_router(ws_router, tags=["WebSocket"])
