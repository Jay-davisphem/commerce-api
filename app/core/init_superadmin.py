"""Idempotent super admin bootstrap.

At application startup, ensure a super admin exists using credentials from the
environment (`SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`). This is skipped
safely if either value is blank, and never re-creates an existing user.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User, UserRole
from app.services.security import hash_password

logger = logging.getLogger(__name__)


async def ensure_superadmin(db: AsyncSession) -> User | None:
    """Create the super admin from settings if one does not exist.

    Returns the super admin user if present/created, else None if the env
    variables are not configured. Idempotent — safe to call on every startup.
    """
    email = (settings.SUPER_ADMIN_EMAIL or "").strip().lower()
    password = settings.SUPER_ADMIN_PASSWORD or ""

    if not email or not password:
        logger.info(
            "SUPER_ADMIN_EMAIL / SUPER_ADMIN_PASSWORD not set — skipping super admin bootstrap."
        )
        return None

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        # Already bootstrapped — nothing to do.
        return None

    admin = User(
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.SUPER_ADMIN,
    )
    db.add(admin)
    await db.commit()
    logger.info("Bootstrapped super admin <%s> from environment.", email)
    return admin
