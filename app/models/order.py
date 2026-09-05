from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OrderStatus(str, enum.Enum):
    """Lifecycle of an order in the checkout & delivery flow."""

    PENDING = "pending"
    PAID = "paid"
    IN_ESCROW = "in_escrow"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    """Payment tracking separate from delivery status."""

    UNPAID = "unpaid"
    PAID = "paid"
    FAILED = "failed"


class Order(Base, TimestampMixin):
    """A customer order placed through checkout or registered at POS."""

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "total_amount >= 0",
            name="ck_orders_total_non_negative",
        ),
        Index("ix_orders_paystack_reference", "paystack_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    guest_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    delivery_recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_city: Mapped[str] = mapped_column(String(120), nullable=False)
    delivery_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivery_postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    delivery_country: Mapped[str] = mapped_column(String(120), nullable=False)
    delivery_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"),
        default=OrderStatus.PENDING,
        nullable=False,
        index=True,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"),
        default=PaymentStatus.UNPAID,
        nullable=False,
    )

    order_source: Mapped[str] = mapped_column(
        String(20),
        default="ONLINE",
        nullable=False,
        server_default="ONLINE",
    )

    paystack_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paystack_access_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    paystack_authorization_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    user: Mapped["User | None"] = relationship(back_populates="orders", lazy="joined")

    @property
    def order_reference(self) -> str:
        if self.paystack_reference:
            return self.paystack_reference
        return f"#BLHMI-{str(self.id)[:8].upper()}"

    @property
    def customer_name(self) -> str:
        if self.delivery_recipient_name:
            return self.delivery_recipient_name
        if self.user and self.user.full_name:
            return self.user.full_name
        return "Customer"

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id} email={self.guest_email!r} "
            f"total={self.total_amount} status={self.status.value}>"
        )


from app.models.order_item import OrderItem  # noqa: E402
from app.models.user import User  # noqa: E402