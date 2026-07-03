"""Pydantic-based application settings."""

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "ScalesAPI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DATABASE_URL: str = "postgresql+asyncpg://scales:scales@localhost:5432/scales"
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_RECYCLE: int = 3600

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    REDIS_URL: str | None = None

    # Real-time gateway (Socket.IO) for multi-container broadcast
    GATEWAY_URL: str | None = None
    GATEWAY_INTERNAL_SECRET: str | None = None

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # Security hardening
    RATE_LIMIT_REQUESTS: int = 300
    RATE_LIMIT_READ_REQUESTS: int = 1200
    RATE_LIMIT_UNAUTHED_REQUESTS: int = 30
    RATE_LIMIT_WINDOW: int = 60
    SECURITY_HEADERS_ENABLED: bool = True
    CORS_ORIGINS_PROD: str | None = None
    REQUEST_MAX_BODY_SIZE_MB: float = 1.0

    # Stripe
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_TEST_SECRET_KEY: str | None = None  # deprecated alias; prefer STRIPE_SECRET_KEY
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_ID_BASIC: str | None = None
    STRIPE_PRICE_ID_ENTERPRISE: str | None = None
    STRIPE_BASIC_MONTHLY_AMOUNT_CENTS: int = 4900
    STRIPE_ENTERPRISE_MONTHLY_AMOUNT_CENTS: int = 9900

    # Data retention / compliance
    PURGE_RETENTION_DAYS: int = 30

    # Error tracking (optional — set SENTRY_DSN env var to enable)
    SENTRY_DSN: str | None = None

    @model_validator(mode="after")
    def _reject_default_jwt_secret(self):
        if self.ENVIRONMENT != "development" and (
            self.JWT_SECRET_KEY == "change-me" or len(self.JWT_SECRET_KEY) < 32
        ):
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters and not the default "
                "value in non-development environments"
            )
        return self

    @model_validator(mode="after")
    def _warn_missing_redis(self):
        import logging
        logger = logging.getLogger(__name__)
        if not self.REDIS_URL:
            logger.warning(
                "REDIS_URL is not set. Application will use in-memory fallback for "
                "rate limiting and queue pub/sub. Set REDIS_URL for production "
                "horizontal scaling."
            )
        return self


settings = Settings()
