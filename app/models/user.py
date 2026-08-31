from __future__ import annotations

import enum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(str, enum.Enum):
    """Role granted to a platform user (RBAC).

    - BUYER: guest who optionally created an account to track/purchase orders
      (no product-management rights).
    - SELLER: can create/manage their own products.
    - SUPER_ADMIN: full control (manages all products and users).
    """

    BUYER = "buyer"
    SELLER = "seller"
    SUPER_ADMIN = "super_admin"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A platform user (buyer, seller, or super admin).

    Buyers do NOT need an account — checkout is guest-first. An account may be
    created after a purchase to link past guest orders (via `Order.user_id`) and
    to save default delivery details so checkout can be prefilled.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        default=UserRole.SELLER,
        nullable=False,
    )

    # Default delivery details — optional, used to prefill checkout for a buyer
    # who has saved an address ("buyer picks source": saved address OR new one).
    default_recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    default_country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    default_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Product this user owns (seller-created products).
    products: Mapped[list[Product]] = relationship(back_populates="owner")

    # Orders placed by this user (optionally linked after checkout/registration).
    orders: Mapped[list[Order]] = relationship(back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role.value}>"


# Local imports to avoid module-level circular imports; these classes are defined
# in the same package and registered on the same Base before queries run.
from app.models.order import Order
from app.models.product import Product

__all__ = ["User", "UserRole"]
