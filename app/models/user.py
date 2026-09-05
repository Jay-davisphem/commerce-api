from __future__ import annotations

import enum
from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(str, enum.Enum):
    """Role granted to a platform user (RBAC)."""

    BUYER = "buyer"
    SELLER = "seller"
    SUPER_ADMIN = "super_admin"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A platform user (buyer, seller, or super admin)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        default=UserRole.SELLER,
        nullable=False,
    )

    default_recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    default_country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    products: Mapped[list["Product"]] = relationship(back_populates="owner")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role.value}>"


from app.models.order import Order  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.models.review import Review  # noqa: E402

__all__ = ["User", "UserRole"]