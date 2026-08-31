"""Password hashing (bcrypt) and JWT token creation/verification (PyJWT).

bcrypt is used directly (no passlib) to avoid deprecated-library friction.
Tokens are HS256-signed with `settings.JWT_SECRET_KEY`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.models.user import UserRole


def hash_password(password: str) -> str:
    """Return a bcrypt hash for the given plaintext password."""
    if not password:
        raise ValueError("Password must not be empty")
    # bcrypt requires bytes and accepts a cost factor; default (12) is used.
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash (e.g. not a bcrypt hash) — treat as invalid.
        return False


def create_access_token(
    *,
    subject: str,
    role: UserRole,
    user_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token for the given user.

    `subject` is the user's email (used as the standard `sub` claim).
    Custom claims carry the user id and role for fast authorization without a
    DB lookup on every request.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": subject,
        "uid": user_id,
        "role": role.value,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jwt.PyJWTError on invalid/expired tokens."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


__all__ = [
    "create_access_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
