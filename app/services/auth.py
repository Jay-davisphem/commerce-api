"""Authentication & authorization dependencies for FastAPI.

Exposes:
- `authenticate_user` — credential check for the login endpoint.
- `get_current_user` — resolve the current user from a Bearer token.
- `get_current_optional_user` — same, but returns None for anonymous requests
  (used by checkout so a logged-in buyer's order gets linked).
- `require_seller` — allow sellers and super admins.
- `require_superadmin` — allow super admins only.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.security import decode_token, verify_password

# Auto-detect the `Authorization: Bearer <token>` header.
_bearer = HTTPBearer(auto_error=False)


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | None:
    """Return the User if credentials are valid, else None."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the Bearer token, or 401."""
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise exc

    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise exc

    uid = payload.get("uid")
    if not uid:
        raise exc

    try:
        user_id = uuid.UUID(str(uid))
    except (ValueError, TypeError):
        raise exc

    user = await db.get(User, user_id)
    if user is None:
        raise exc
    return user


async def get_current_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Like `get_current_user`, but returns None when no valid token is present.

    Never raises for a missing/invalid token — callers must handle None.
    """
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        return None

    uid = payload.get("uid")
    if not uid:
        return None
    try:
        user_id = uuid.UUID(str(uid))
    except (ValueError, TypeError):
        return None

    return await db.get(User, user_id)


async def require_seller(user: User = Depends(get_current_user)) -> User:
    """Allow sellers and super admins; reject everyone else with 403."""
    if user.role not in {UserRole.SELLER, UserRole.SUPER_ADMIN}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return user


async def require_superadmin(user: User = Depends(get_current_user)) -> User:
    """Allow only super admins; reject everyone else with 403."""
    if user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin privileges required",
        )
    return user
