from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Product(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A sellable product."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
        CheckConstraint("inventory_count >= 0", name="ck_products_inventory_non_negative"),
        # Composite B-tree indexes for Keyset/Cursor ordering
        Index("ix_products_created_id_desc", "created_at", "id"),
        Index("ix_products_price_id_desc", "price", "id"),
        Index("ix_products_owner_created", "owner_id", "created_at"),
        # PostgreSQL GIN Trigram Indexes for instant substring matching
        Index(
            "ix_products_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_products_desc_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    inventory_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    gallery_images: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default="[]",
        nullable=False,
    )
    specifications: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    discount_percentage: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=15, nullable=False, server_default="15")
    tag: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    rating: Mapped[Decimal] = mapped_column(Numeric(2, 1), default=Decimal("5.0"), server_default="5.0", nullable=False)
    reviews_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    name = synonym("title")

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    order_items: Mapped[list["OrderItem"]] = relationship(
        back_populates="product",
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    owner: Mapped["User | None"] = relationship(back_populates="products")

    def __repr__(self) -> str:
        return f"<Product id={self.id} title={self.title!r} sku={self.sku!r} price={self.price} rating={self.rating}>"


from app.models.order_item import OrderItem  # noqa: E402
from app.models.review import Review  # noqa: E402
from app.models.user import User  # noqa: E402