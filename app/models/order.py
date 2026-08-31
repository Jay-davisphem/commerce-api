from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    CheckConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class OrderStatus(str, enum.Enum):
    """Lifecycle of an order in the one-shot checkout flow."""

    PENDING = "pending"   # Created; waiting for Paystack payment confirmation.
    PAID = "paid"         # Paystack webhook confirmed `charge.success`.
    FAILED = "failed"     # Payment failed or expired.
    CANCELLED = "cancelled"


class PaymentStatus(str, enum.Enum):
    """Finer-grained payment tracking, separate from overall order status."""

    UNPAID = "unpaid"
    PAID = "paid"
    FAILED = "failed"


class Order(Base, TimestampMixin):
    """A customer order placed through the one-shot checkout endpoint.

    Supports guest checkout (no user/auth required). Carries the guest email,
    a snapshot of the delivery address, the server-computed total, payment
    status, and the Paystack transaction reference.
    """

    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "total_amount >= 0",
            name="ck_orders_total_non_negative",
        ),
        Index("ix_orders_paystack_reference", "paystack_reference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # Guest checkout identity — required, no auth required.
    guest_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Optional link to a User account. NULL for pure guest checkout; set when the
    # buyer is authenticated (or linked after registration by matching email).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Delivery details (snapshot).
    delivery_recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    delivery_address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_city: Mapped[str] = mapped_column(String(120), nullable=False)
    delivery_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivery_postal_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    delivery_country: Mapped[str] = mapped_column(String(120), nullable=False)
    # Catch-all for curated/non-standard delivery notes (e.g. landmark).
    delivery_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Server-computed total for the whole order (sum of line totals).
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

    # Paystack transaction reference. Unique-ish (we index it and enforce a
    # partial uniqueness pattern in a real migration); used by the webhook to
    # locate this order when `charge.success` arrives.
    paystack_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    # Paystack access_code used to open the checkout modal on the frontend.
    paystack_access_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional link to the authorization_url we returned to the client.
    paystack_authorization_url: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    # When the payment was confirmed (set by the webhook).
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Line items, populated by the checkout service.
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # The User who placed this order, if the guest later created/attached an account.
    user: Mapped["User | None"] = relationship(back_populates="orders")

    def __repr__(self) -> str:
        return (
            f"<Order id={self.id} email={self.guest_email!r} "
            f"total={self.total_amount} status={self.status.value}>"
        )


from app.models.order_item import OrderItem  # noqa: E402
from app.models.user import User  # noqa: E402
