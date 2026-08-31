from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Product(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A sellable product.

    Price/inventory live here — the checkout flow reads these values
    directly from the DB so the client can never set its own prices.
    """

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
        CheckConstraint("inventory_count >= 0", name="ck_products_inventory_non_negative"),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Price in the storefront's base currency (minor units are handled at the
    # Paystack layer, see schemas/services). Stored as Numeric(12,2).
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    inventory_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Optional owning user (seller). NULL for system/admin-created products.
    # Server derives this from the authenticated user — the client never sets it.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Back-reference to order items — helpful for eager loading and integrity.
    order_items: Mapped[list["OrderItem"]] = relationship(
        back_populates="product",
    )
    owner: Mapped["User | None"] = relationship(back_populates="products")

    def __repr__(self) -> str:
        return f"<Product id={self.id} title={self.title!r} price={self.price}>"


# Local import to avoid a module-level circular import; OrderItem is defined
# in this package and registered on the same Base before queries run.
from app.models.order_item import OrderItem  # noqa: E402
from app.models.user import User  # noqa: E402
