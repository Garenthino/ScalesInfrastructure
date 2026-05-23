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

    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    REDIS_URL: str | None = None

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # Security hardening
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW: int = 60
    SECURITY_HEADERS_ENABLED: bool = True
    CORS_ORIGINS_PROD: str | None = None
    REQUEST_MAX_BODY_SIZE_MB: float = 1.0

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


settings = Settings()
