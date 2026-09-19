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

    # PostgreSQL via asyncpg
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/commerce"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # Redis / Caching
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_DEFAULT_TTL: int = 120

    # Upload Limits & MIME Types
    MAX_IMAGE_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_TYPES: list[str] = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/webp", "image/avif"]
    )

    # Cloudflare R2 Storage
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    R2_PUBLIC_DOMAIN: str = ""  # e.g. "https://images.yourdomain.com" or "https://pub-xxx.r2.dev"

    # Frontend URL (Redirect landing after checkout)
    FRONTEND_URL: str = "http://localhost:3000"

    # Active Payment Gateway: "paystack" or "stripe"
    PAYMENT_GATEWAY: str = "paystack"

    # Paystack Configuration
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""
    PAYSTACK_BASE_URL: str = "https://api.paystack.co"
    PAYSTACK_WEBHOOK_SECRET: str = ""

    # Stripe Configuration
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLIC_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_CURRENCY: str = "ngn"  # Base catalog currency sent to Stripe

    # Auth
    SUPER_ADMIN_EMAIL: str = ""
    SUPER_ADMIN_PASSWORD: str = ""
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # CORS
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Email Dispatch Configuration
    # Options: "console" (terminal output), "file" (local HTML files), "resend", "ensend"
    EMAIL_PROVIDER: str = "console"
    EMAILS_FROM: str = "BLHMI Support <noreply@blhmisupplement.com>"

    # Resend Credentials
    RESEND_API_KEY: str = ""

    # Ensend Credentials
    ENSEND_PROJECT_SECRET: str = ""
    ENSEND_SENDER_NAME: str = "BLHMI Supplements"
    ENSEND_SENDER_ADDRESS: str = ""

    OTP_EXPIRE_SECONDS: int = 600  # 10 minutes


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()