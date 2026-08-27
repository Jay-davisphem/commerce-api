from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "commerce-api"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # PostgreSQL via asyncpg. Example:
    # postgresql+asyncpg://postgres:postgres@localhost:5432/commerce
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/commerce"

    # Paystack
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""
    PAYSTACK_BASE_URL: str = "https://api.paystack.co"

    # Webhook HMAC. Prefer PAYSTACK_SECRET_KEY; override not needed for Paystack
    # (Paystack signs with the secret key), but kept for clarity.
    PAYSTACK_WEBHOOK_SECRET: str = ""

    # CORS
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor usable as a FastAPI dependency."""
    return Settings()


settings = get_settings()
