from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC now (used for onupdate)."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


class UUIDPrimaryKeyMixin:
    """Shared UUID primary key for all entities."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """created_at / updated_at timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=utcnow,
    )


__all__ = ["Base", "utcnow", "UUIDPrimaryKeyMixin", "TimestampMixin"]
