from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.order import OrderStatus, PaymentStatus


# -------------------------------
# Request side (one-shot checkout)
# -------------------------------

class DeliveryAddress(BaseModel):
    """Delivery details submitted at checkout."""

    recipient_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str = Field(min_length=1, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=1, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=30)
    country: str = Field(min_length=1, max_length=120)
    notes: str | None = None


class CheckoutItem(BaseModel):
    """A single cart line sent by the frontend.

    IMPORTANT: No price is accepted here. The server always queries the DB for
    the authoritative `unit_price` — frontend-supplied prices are never trusted.
    """

    product_id: uuid.UUID
    quantity: int = Field(gt=0, le=1000)


class CheckoutRequest(BaseModel):
    """The single payload the frontend posts to the checkout endpoint."""

    guest_email: EmailStr
    delivery: DeliveryAddress
    items: list[CheckoutItem] = Field(min_length=1)


# -------------------------------
# Response side
# -------------------------------

class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderRead(BaseModel):
    """Full order representation returned to the client."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    guest_email: EmailStr
    delivery: DeliveryAddress | None = None  # flattened in service mapper
    total_amount: Decimal
    status: OrderStatus
    payment_status: PaymentStatus
    paystack_reference: str | None = None
    paid_at: datetime | None = None
    created_at: datetime
    items: list[OrderItemRead] = []


class CheckoutResponse(BaseModel):
    """Returned by the checkout endpoint.

    Carries the persisted order plus the Paystack payment details the frontend
    needs to redirect the guest (`authorization_url`) and, optionally, to open
    the modal (`access_code`).
    """

    order: OrderRead
    authorization_url: str
    access_code: str | None = None
    # The reference the frontend can pass back / listen for in webhook events.
    reference: str


class OrderStatusUpdate(BaseModel):
    """Used by internal/admin tools (not the customer-facing checkout)."""

    status: OrderStatus
