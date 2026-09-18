from __future__ import annotations

import secrets
from app.core.cache import cache_service
from app.core.config import settings


def generate_otp() -> str:
    """Generate a secure 6-digit numerical code."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def store_otp(email: str, purpose: str, code: str) -> None:
    cache_key = f"otp:{purpose}:{email.lower().strip()}"
    await cache_service.set(cache_key, code, ttl_seconds=settings.OTP_EXPIRE_SECONDS)


async def verify_otp(email: str, purpose: str, code: str) -> bool:
    cache_key = f"otp:{purpose}:{email.lower().strip()}"
    stored_code = await cache_service.get(cache_key)
    if stored_code and secrets.compare_digest(str(stored_code), code.strip()):
        await cache_service.invalidate_prefix(cache_key)
        return True
    return False