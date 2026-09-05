from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.order import OrderStatus, PaymentStatus


class DeliveryAddress(BaseModel):
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
    product_id: uuid.UUID
    quantity: int = Field(gt=0, le=1000)


class CheckoutRequest(BaseModel):
    guest_email: EmailStr | None = None
    delivery: DeliveryAddress | None = None
    use_saved_address: bool = False
    items: list[CheckoutItem] = Field(min_length=1)


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    guest_email: EmailStr
    delivery: DeliveryAddress | None = None
    total_amount: Decimal
    status: OrderStatus
    payment_status: PaymentStatus
    paystack_reference: str | None = None
    paid_at: datetime | None = None
    created_at: datetime
    items: list[OrderItemRead] = []


# Export alias so legacy imports do not break
OrderResponse = OrderRead


class CheckoutResponse(BaseModel):
    order: OrderRead
    authorization_url: str
    access_code: str | None = None
    reference: str


class OrderStatusUpdate(BaseModel):
    status: OrderStatus